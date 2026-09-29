"""The delayed-webhook oversell race, reproduced end to end.

The sequence this file exists for, exactly as it would happen:

  1. A holds the final seat
  2. A pays just before the hold's local expiry
  3. the completion webhook is delayed
  4. the hold's window elapses
  5. B attempts to buy the same final seat
  6. B is refused
  7. A's delayed webhook arrives
  8. exactly one confirmed booking and one AccessPass

Step 6 is the fix. Before it, ``capacity_used`` dropped A's expired hold,
B bought the seat, and A's late webhook confirmed A as well — two
confirmed bookings against capacity 1.

Step 8 is the other half, and the reason the fix is not simply "reject
late payment": A really did pay. Refusing fulfilment because a local
clock elapsed would take the money and grant nothing, which is worse
than the oversell. So the seat stays counted, and the late completion is
still honoured.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.access_pass import AccessPass
from app.models.payment import PaymentTransactionStatus
from app.models.platform import BookingStatus, EventBooking
from app.services import discount_stripe_sessions as _sessions
from app.services import gathering_tickets as gt


def _fee_defaults():
    return dict(fee_bps=0, creator_plan_id=None, creator_subscription_id=None)


def _hold_for(db, *, event, buyer, make_pending_txn, session_id):
    """A live hold with a Stripe Session recorded, as the endpoint leaves it."""
    txn, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
    txn.provider_checkout_session_id = session_id
    offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
    outcome = gt.create_or_reuse_hold(
        db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
    )
    # The endpoint writes Stripe's own expiry back onto the hold; do the
    # same here so the fixture matches production shape.
    outcome.booking.payment_transaction_id = txn.id
    db.commit()
    return outcome.booking, txn


def _elapse(db, booking, *, minutes=1):
    """Move the hold's window into the past, as waiting would."""
    booking.hold_expires_at = datetime.utcnow() - timedelta(minutes=minutes)
    db.commit()


class TestTheDelayedWebhookRace:
    def test_b_is_refused_while_a_may_still_be_paying(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Steps 1–6. The seat A holds is not resold merely because its
        window elapsed — Stripe has not said A's checkout is dead."""
        event = make_event(capacity=1)
        a, b = make_user(), make_user()
        booking_a, _ = _hold_for(db, event=event, buyer=a,
                                 make_pending_txn=make_pending_txn,
                                 session_id="cs_a")
        _elapse(db, booking_a)

        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        with patch.object(_sessions, "session_status", return_value="complete"):
            # B's attempt triggers verification of A's stale hold. Stripe
            # says A paid, so the seat is A's and B is refused.
            assert gt.sweep_stale_holds(db, event_id=event.id) == 0
            with pytest.raises(gt.SoldOut):
                gt.create_or_reuse_hold(db, offer=offer, buyer=b,
                                        hold_ttl_minutes=30, **_fee_defaults())

        assert gt.capacity_used(db, event.id) == 1

    def test_and_as_delayed_webhook_still_fulfils(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Steps 7–8. The completion arrives after the window and is
        honoured anyway: exactly one confirmed booking, one pass."""
        event = make_event(capacity=1)
        a = make_user()
        booking_a, txn_a = _hold_for(db, event=event, buyer=a,
                                     make_pending_txn=make_pending_txn,
                                     session_id="cs_a")
        _elapse(db, booking_a, minutes=5)

        outcome = gt.fulfil_ticket_purchase(
            db,
            transaction_id=txn_a.id,
            event_id=event.id,
            payer_user_id=a.id,
            stripe_amount_total=txn_a.gross_amount_cents,
            stripe_currency=txn_a.currency,
            stripe_payment_intent_id="pi_a",
            stripe_charge_id=None,
        )
        db.commit()

        assert outcome.booking.status == BookingStatus.confirmed
        assert db.query(EventBooking).filter_by(
            event_id=event.id, status=BookingStatus.confirmed).count() == 1
        assert db.query(AccessPass).filter_by(
            payment_transaction_id=txn_a.id).count() == 1

    def test_the_whole_sequence_yields_one_seat_one_pass(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """All eight steps in order — the regression itself."""
        event = make_event(capacity=1)
        a, b = make_user(), make_user()

        # 1–2. A holds the final seat and pays.
        booking_a, txn_a = _hold_for(db, event=event, buyer=a,
                                     make_pending_txn=make_pending_txn,
                                     session_id="cs_a")
        # 3–4. Webhook delayed; the window elapses.
        _elapse(db, booking_a)

        # 5–6. B attempts and is refused.
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        with patch.object(_sessions, "session_status", return_value="complete"):
            gt.sweep_stale_holds(db, event_id=event.id)
            with pytest.raises(gt.SoldOut):
                gt.create_or_reuse_hold(db, offer=offer, buyer=b,
                                        hold_ttl_minutes=30, **_fee_defaults())

        # 7. A's webhook finally arrives.
        gt.fulfil_ticket_purchase(
            db, transaction_id=txn_a.id, event_id=event.id, payer_user_id=a.id,
            stripe_amount_total=txn_a.gross_amount_cents,
            stripe_currency=txn_a.currency,
            stripe_payment_intent_id="pi_a", stripe_charge_id=None,
        )
        db.commit()

        # 8. One seat, one pass, and it belongs to the person who paid.
        confirmed = db.query(EventBooking).filter_by(
            event_id=event.id, status=BookingStatus.confirmed).all()
        assert len(confirmed) == 1
        assert confirmed[0].user_id == a.id
        assert db.query(AccessPass).filter_by(
            payment_transaction_id=txn_a.id).count() == 1
        assert gt.capacity_used(db, event.id) == 1

    def test_b_gets_the_seat_when_a_genuinely_abandoned_it(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """The counterpart. Holding seats past expiry must not mean
        holding them forever — once Stripe confirms A's Session is dead,
        B buys normally."""
        event = make_event(capacity=1)
        a, b = make_user(), make_user()
        booking_a, _ = _hold_for(db, event=event, buyer=a,
                                 make_pending_txn=make_pending_txn,
                                 session_id="cs_a")
        _elapse(db, booking_a)

        with patch.object(_sessions, "session_status", return_value="expired"):
            assert gt.sweep_stale_holds(db, event_id=event.id) == 1

        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        outcome = gt.create_or_reuse_hold(
            db, offer=offer, buyer=b, hold_ttl_minutes=30, **_fee_defaults())

        assert outcome.booking.user_id == b.id
        db.refresh(booking_a)
        assert booking_a.status == BookingStatus.cancelled

    def test_an_open_session_past_its_window_is_expired_then_released(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """We close it ourselves rather than waiting on Stripe's own
        24-hour timeout, then let the re-read decide."""
        event = make_event(capacity=1)
        a = make_user()
        booking_a, _ = _hold_for(db, event=event, buyer=a,
                                 make_pending_txn=make_pending_txn,
                                 session_id="cs_a")
        _elapse(db, booking_a)

        with patch.object(_sessions, "session_status",
                          side_effect=["open", "expired"]), \
             patch.object(_sessions, "expire_session") as expire:
            assert gt.sweep_stale_holds(db, event_id=event.id) == 1

        assert expire.called
        assert gt.capacity_used(db, event.id) == 0

    def test_a_session_paid_during_the_expire_attempt_keeps_its_seat(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Losing the race to a buyer paying at that instant. The re-read
        decides, and it says paid."""
        event = make_event(capacity=1)
        a = make_user()
        booking_a, _ = _hold_for(db, event=event, buyer=a,
                                 make_pending_txn=make_pending_txn,
                                 session_id="cs_a")
        _elapse(db, booking_a)

        with patch.object(_sessions, "session_status",
                          side_effect=["open", "complete"]), \
             patch.object(_sessions, "expire_session",
                          side_effect=_sessions.StripeStateChanged("moved")):
            assert gt.sweep_stale_holds(db, event_id=event.id) == 0

        assert gt.capacity_used(db, event.id) == 1
        db.refresh(booking_a)
        assert booking_a.status == BookingStatus.pending_payment

    def test_verification_never_runs_under_the_event_lock(self, db):
        """Structural, asserted against the AST: a Stripe call inside the
        Event row lock would queue every other buyer of that Gathering
        behind a third-party request. Checked as CALLS rather than text,
        because the docstrings mention Stripe precisely to explain why it
        is absent."""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(gt.create_or_reuse_hold)))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    called.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    called.add(fn.attr)
        for forbidden in ("verify_stale_hold", "sweep_stale_holds",
                          "session_status", "expire_session"):
            assert forbidden not in called, forbidden

    def test_capacity_has_no_clock_in_it(self, db):
        """The one-line root cause, pinned. Reintroducing a time
        comparison here is the oversell."""
        sql = str(gt.CAPACITY_USED_SQL)
        assert "hold_expires_at" not in sql
        assert "NOW" not in sql.upper()
        assert "pending_payment" in sql and "confirmed" in sql
