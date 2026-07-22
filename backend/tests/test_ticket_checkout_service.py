"""
Service-layer tests for the standalone Gathering ticket flow.

We test at the service layer (not the HTTP layer) because it gives us
precise control over concurrency + row locking + rollback boundaries
and doesn't pull FastAPI dependency injection into every test. The
HTTP endpoint is a thin wrapper; the service invariants tested here
are the actual load-bearing logic.

Covers the 17 scenarios from the Stage 2 spec plus extras from Stage 2A.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.access_pass import (
    AccessPass,
    AccessPassEvent,
    AccessPassStatus,
    AccessPassSource,
    AccessPassType,
)
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import BookingStatus, EventBooking
from app.services import gathering_tickets as gt


# ---------------------------------------------------------------------------
# Fixture: enable the live-mode guard for the duration of a test
# ---------------------------------------------------------------------------

@pytest.fixture
def sales_enabled(monkeypatch):
    monkeypatch.setattr(settings, "standalone_gathering_sales_enabled", True)


@pytest.fixture
def sales_disabled(monkeypatch):
    monkeypatch.setattr(settings, "standalone_gathering_sales_enabled", False)


def _fee_defaults():
    return {"fee_bps": 800, "creator_plan_id": None, "creator_subscription_id": None}


# ---------------------------------------------------------------------------
# 1. Configuration guard
# ---------------------------------------------------------------------------

class TestLiveModeGuard:
    def test_flag_off_refuses_regardless_of_stripe_mode(self, sales_disabled):
        with pytest.raises(gt.TicketSalesDisabled):
            gt.ensure_sales_enabled_or_raise()

    def test_flag_on_permits(self, sales_enabled):
        gt.ensure_sales_enabled_or_raise()  # must not raise


# ---------------------------------------------------------------------------
# 2. load_and_validate_offer — every negative case
# ---------------------------------------------------------------------------

class TestOfferValidation:
    def test_unknown_space(self, db, make_event):
        make_event()
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, "not-a-real-space", "any-event")

    def test_wrong_space(self, db, make_event, make_space):
        event = make_event()
        other = make_space()
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, other.slug, event.id)

    def test_not_paid_separately_rejected(self, db, make_event):
        event = make_event(
            booking_access_type="included_with_collective",
            ticket_price_cents=None, ticket_currency=None,
        )
        with pytest.raises(gt.NotAPaidGathering):
            gt.load_and_validate_offer(db, event.space.slug, event.id)

    def test_unpublished_rejected(self, db, make_event):
        event = make_event(is_published=False)
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, event.space.slug, event.id)

    def test_cancelled_rejected(self, db, make_event):
        event = make_event(status="cancelled")
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, event.space.slug, event.id)

    def test_ended_rejected(self, db, make_event):
        event = make_event(
            starts_at=datetime.utcnow() - timedelta(days=2),
            ends_at=datetime.utcnow() - timedelta(days=2, hours=-1),
        )
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, event.space.slug, event.id)

    def test_booking_closed_rejected(self, db, make_event):
        event = make_event(booking_closes_at=datetime.utcnow() - timedelta(hours=1))
        with pytest.raises(gt.GatheringUnavailable):
            gt.load_and_validate_offer(db, event.space.slug, event.id)

    def test_happy_path_returns_trusted_offer(self, db, make_event):
        event = make_event()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        assert offer.event.id == event.id
        assert offer.space.id == event.space.id
        assert offer.price_cents == 2500
        assert offer.currency == "AUD"


# ---------------------------------------------------------------------------
# 3. Hold creation — spec scenarios 1..7
# ---------------------------------------------------------------------------

class TestHoldCreation:
    def test_creates_pending_hold_and_transaction(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        outcome = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )
        assert outcome.reused is False
        assert outcome.booking.status == BookingStatus.pending_payment
        assert outcome.booking.hold_expires_at > datetime.utcnow()
        assert outcome.booking.source == "ticket_purchase"
        assert outcome.booking.payment_transaction_id == outcome.transaction.id
        assert outcome.transaction.status == PaymentTransactionStatus.pending
        assert outcome.transaction.gross_amount_cents == 2500
        assert outcome.transaction.currency == "AUD"
        # 8% platform fee resolved
        assert outcome.transaction.platform_fee_basis_points == 800
        assert outcome.transaction.platform_fee_cents == 200
        assert outcome.transaction.net_creator_amount_cents == 2300
        assert outcome.transaction.transaction_type == PaymentTransactionType.gathering_ticket_purchase
        assert outcome.transaction.payout_status == PayoutStatus.pending

    def test_platform_owned_space_gets_zero_fee_notapplicable_payout(
        self, db, make_space, make_event, make_user,
    ):
        space = make_space(creator_id=None)
        # Override creator_id on event too
        event = make_event(space=space, created_by_id=None)  # noqa: safe: created_by nullable
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, space.slug, event.id)
        outcome = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer,
            fee_bps=0, creator_plan_id=None, creator_subscription_id=None,
            hold_ttl_minutes=30,
        )
        assert outcome.transaction.platform_fee_cents == 0
        assert outcome.transaction.payout_status == PayoutStatus.not_applicable

    def test_rejects_when_sold_out(self, db, make_event, make_user):
        event = make_event(capacity=1)
        # Pre-populate a confirmed booking to fill the seat
        pre_buyer = make_user()
        db.add(EventBooking(
            id="bk_pre_" + "x" * 12, event_id=event.id, user_id=pre_buyer.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
        ))
        db.flush()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        buyer = make_user()
        with pytest.raises(gt.SoldOut):
            gt.create_or_reuse_hold(
                db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
            )

    def test_active_hold_consumes_capacity(self, db, make_event, make_user):
        event = make_event(capacity=1)
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        buyer_a = make_user()
        gt.create_or_reuse_hold(db, offer=offer, buyer=buyer_a,
                                hold_ttl_minutes=30, **_fee_defaults())
        buyer_b = make_user()
        with pytest.raises(gt.SoldOut):
            gt.create_or_reuse_hold(db, offer=offer, buyer=buyer_b,
                                    hold_ttl_minutes=30, **_fee_defaults())

    def test_expired_hold_ignored_by_capacity(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event(capacity=1)
        # Insert an EXPIRED pending_payment row for someone else
        other = make_user()
        txn, _ = make_pending_txn(space=event.space, event=event, payer=other)
        db.add(EventBooking(
            id="bk_stale_" + "x" * 10,
            event_id=event.id, user_id=other.id,
            status=BookingStatus.pending_payment,
            hold_expires_at=datetime.utcnow() - timedelta(minutes=5),
            payment_transaction_id=txn.id,
        ))
        db.flush()

        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        buyer = make_user()
        # Must succeed — the expired hold does not count
        outcome = gt.create_or_reuse_hold(db, offer=offer, buyer=buyer,
                                          hold_ttl_minutes=30, **_fee_defaults())
        assert outcome.booking.status == BookingStatus.pending_payment

    def test_already_confirmed_user_cannot_buy_again(
        self, db, make_event, make_user,
    ):
        event = make_event(capacity=10)
        buyer = make_user()
        db.add(EventBooking(
            id="bk_conf_" + "x" * 12, event_id=event.id, user_id=buyer.id,
            status=BookingStatus.confirmed, source="ticket_purchase",
        ))
        db.flush()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        with pytest.raises(gt.AlreadyHasTicket):
            gt.create_or_reuse_hold(db, offer=offer, buyer=buyer,
                                    hold_ttl_minutes=30, **_fee_defaults())

    def test_expired_hold_by_same_user_is_reused(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event()
        buyer = make_user()
        stale_txn, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        db.add(EventBooking(
            id="bk_stale_" + "x" * 10,
            event_id=event.id, user_id=buyer.id,
            status=BookingStatus.pending_payment,
            hold_expires_at=datetime.utcnow() - timedelta(minutes=5),
            payment_transaction_id=stale_txn.id,
            source="ticket_purchase",
        ))
        db.flush()

        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        outcome = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )
        assert outcome.reused is True
        # Still exactly one booking row for (event, user)
        n = db.execute(
            text("SELECT COUNT(*) FROM event_bookings WHERE event_id=:e AND user_id=:u"),
            {"e": event.id, "u": buyer.id},
        ).scalar_one()
        assert n == 1
        assert outcome.booking.payment_transaction_id == outcome.transaction.id
        # And it's the NEW transaction, not the stale one
        assert outcome.transaction.id != stale_txn.id


# ---------------------------------------------------------------------------
# 4. Webhook fulfilment
# ---------------------------------------------------------------------------

class TestFulfilment:
    def _seed_hold(self, db, event, buyer):
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        return gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )

    def test_successful_fulfilment_creates_all_artifacts(
        self, db, make_event, make_user,
    ):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)

        result = gt.fulfil_ticket_purchase(
            db,
            transaction_id=outcome.transaction.id,
            event_id=event.id,
            payer_user_id=buyer.id,
            stripe_amount_total=2500,
            stripe_currency="AUD",
            stripe_payment_intent_id="pi_fake_1",
            stripe_charge_id="ch_fake_1",
        )
        assert result.already_fulfilled is False
        assert result.booking.status == BookingStatus.confirmed
        assert result.booking.hold_expires_at is None
        assert result.booking.access_pass_id == result.access_pass.id
        assert result.access_pass.pass_type == AccessPassType.event_ticket
        assert result.access_pass.status == AccessPassStatus.active
        assert result.access_pass.source == AccessPassSource.one_time_purchase
        assert result.transaction.status == PaymentTransactionStatus.succeeded
        assert result.transaction.provider_payment_intent_id == "pi_fake_1"
        assert result.transaction.provider_charge_id == "ch_fake_1"

        # AccessPassEvent join populated for the specific event
        rows = db.execute(
            text("SELECT event_id FROM access_pass_events WHERE access_pass_id=:ap"),
            {"ap": result.access_pass.id},
        ).all()
        assert [r[0] for r in rows] == [event.id]

    def test_repeated_webhook_is_noop(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        r1 = gt.fulfil_ticket_purchase(
            db, transaction_id=outcome.transaction.id, event_id=event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi_1", stripe_charge_id=None,
        )
        r2 = gt.fulfil_ticket_purchase(
            db, transaction_id=outcome.transaction.id, event_id=event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi_1", stripe_charge_id=None,
        )
        assert r1.already_fulfilled is False
        assert r2.already_fulfilled is True
        # Still exactly one booking + one access pass
        assert db.execute(
            text("SELECT COUNT(*) FROM event_bookings WHERE event_id=:e AND user_id=:u"),
            {"e": event.id, "u": buyer.id},
        ).scalar_one() == 1
        assert db.execute(
            text("SELECT COUNT(*) FROM access_passes WHERE payment_transaction_id=:t"),
            {"t": outcome.transaction.id},
        ).scalar_one() == 1

    def test_amount_mismatch_is_refused(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        with pytest.raises(ValueError, match="amount"):
            gt.fulfil_ticket_purchase(
                db, transaction_id=outcome.transaction.id, event_id=event.id,
                payer_user_id=buyer.id, stripe_amount_total=9999, stripe_currency="AUD",
                stripe_payment_intent_id="pi_x", stripe_charge_id=None,
            )
        # Transaction and booking stay pending
        db.refresh(outcome.transaction)
        db.refresh(outcome.booking)
        assert outcome.transaction.status == PaymentTransactionStatus.pending
        assert outcome.booking.status == BookingStatus.pending_payment

    def test_currency_mismatch_is_refused(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        with pytest.raises(ValueError, match="currency"):
            gt.fulfil_ticket_purchase(
                db, transaction_id=outcome.transaction.id, event_id=event.id,
                payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="USD",
                stripe_payment_intent_id="pi_x", stripe_charge_id=None,
            )


# ---------------------------------------------------------------------------
# 5. Expiry / failure release
# ---------------------------------------------------------------------------

class TestExpiryAndFailure:
    def _seed_hold(self, db, event, buyer):
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        return gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )

    def test_checkout_expired_cancels_hold_and_txn(
        self, db, make_event, make_user,
    ):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        gt.release_hold_for_transaction(
            db,
            transaction_id=outcome.transaction.id,
            final_status=PaymentTransactionStatus.cancelled,
            reason="checkout_expired",
        )
        db.refresh(outcome.transaction)
        db.refresh(outcome.booking)
        assert outcome.transaction.status == PaymentTransactionStatus.cancelled
        assert outcome.booking.status == BookingStatus.cancelled
        assert outcome.booking.cancelled_at is not None
        assert outcome.booking.hold_expires_at is None

    def test_payment_failed_marks_txn_failed(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        gt.release_hold_for_transaction(
            db,
            transaction_id=outcome.transaction.id,
            final_status=PaymentTransactionStatus.failed,
            reason="payment_failed",
        )
        db.refresh(outcome.transaction)
        db.refresh(outcome.booking)
        assert outcome.transaction.status == PaymentTransactionStatus.failed
        assert outcome.booking.status == BookingStatus.cancelled

    def test_release_is_idempotent(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        outcome = self._seed_hold(db, event, buyer)
        gt.release_hold_for_transaction(
            db, transaction_id=outcome.transaction.id,
            final_status=PaymentTransactionStatus.cancelled, reason="x",
        )
        gt.release_hold_for_transaction(
            db, transaction_id=outcome.transaction.id,
            final_status=PaymentTransactionStatus.failed, reason="y",
        )
        db.refresh(outcome.transaction)
        assert outcome.transaction.status == PaymentTransactionStatus.cancelled

    def test_capacity_released_after_expiry(
        self, db, make_event, make_user,
    ):
        event = make_event(capacity=1)
        buyer_a = make_user()
        outcome = self._seed_hold(db, event, buyer_a)
        # Someone else CANNOT buy while the hold is live
        buyer_b = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        with pytest.raises(gt.SoldOut):
            gt.create_or_reuse_hold(db, offer=offer, buyer=buyer_b,
                                    hold_ttl_minutes=30, **_fee_defaults())
        # After release, capacity opens back up
        gt.release_hold_for_transaction(
            db, transaction_id=outcome.transaction.id,
            final_status=PaymentTransactionStatus.cancelled, reason="test",
        )
        outcome2 = gt.create_or_reuse_hold(db, offer=offer, buyer=buyer_b,
                                           hold_ttl_minutes=30, **_fee_defaults())
        assert outcome2.booking.status == BookingStatus.pending_payment


# ---------------------------------------------------------------------------
# 6. Access-scope invariants — a paid ticket unlocks ONLY the purchased event.
# ---------------------------------------------------------------------------

class TestAccessScope:
    def test_pass_grants_only_the_purchased_event(
        self, db, make_event, make_user,
    ):
        space_owner_event = make_event()
        space = space_owner_event.space
        # Another event in the SAME Collective
        other_event = make_event(space=space)
        buyer = make_user()

        offer = gt.load_and_validate_offer(db, space.slug, space_owner_event.id)
        held = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )
        gt.fulfil_ticket_purchase(
            db, transaction_id=held.transaction.id, event_id=space_owner_event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi", stripe_charge_id=None,
        )

        # AccessPassEvent has exactly ONE row and it's the purchased event
        rows = db.execute(text("""
            SELECT event_id FROM access_pass_events ape
            JOIN access_passes ap ON ap.id = ape.access_pass_id
            WHERE ap.user_id = :u
        """), {"u": buyer.id}).all()
        assert [r[0] for r in rows] == [space_owner_event.id]
        assert other_event.id not in [r[0] for r in rows]

    def test_pass_does_not_create_space_membership(
        self, db, make_event, make_user,
    ):
        event = make_event()
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        held = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )
        gt.fulfil_ticket_purchase(
            db, transaction_id=held.transaction.id, event_id=event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi", stripe_charge_id=None,
        )
        n = db.execute(text(
            "SELECT COUNT(*) FROM space_memberships WHERE user_id=:u AND space_id=:s"
        ), {"u": buyer.id, "s": event.space.id}).scalar_one()
        assert n == 0

    def test_pass_does_not_grant_pathway_entitlement(
        self, db, make_event, make_user,
    ):
        event = make_event()
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        held = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30, **_fee_defaults(),
        )
        gt.fulfil_ticket_purchase(
            db, transaction_id=held.transaction.id, event_id=event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi", stripe_charge_id=None,
        )
        n = db.execute(text(
            "SELECT COUNT(*) FROM pathway_entitlements WHERE user_id=:u"
        ), {"u": buyer.id}).scalar_one()
        assert n == 0


# ---------------------------------------------------------------------------
# 7. Attendee source labels — Paid vs Creator added vs Complimentary
# ---------------------------------------------------------------------------

class TestAccessSourceLabels:
    def test_paid_label(self, db, make_event, make_user):
        event = make_event()
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        held = gt.create_or_reuse_hold(db, offer=offer, buyer=buyer,
                                       hold_ttl_minutes=30, **_fee_defaults())
        gt.fulfil_ticket_purchase(
            db, transaction_id=held.transaction.id, event_id=event.id,
            payer_user_id=buyer.id, stripe_amount_total=2500, stripe_currency="AUD",
            stripe_payment_intent_id="pi", stripe_charge_id=None,
        )
        assert gt.booking_access_source_label(held.booking) == "Paid"

    def test_creator_added_label(self, db, make_event, make_user):
        event = make_event()
        u = make_user()
        booking = EventBooking(
            id="bk_ca_" + "x" * 12, event_id=event.id, user_id=u.id,
            status=BookingStatus.confirmed, source="creator_manual",
        )
        db.add(booking); db.flush()
        assert gt.booking_access_source_label(booking) == "Creator added"

    def test_complimentary_label(self, db, make_event, make_user):
        """No source set + no txn_id + confirmed = Complimentary bucket."""
        event = make_event()
        u = make_user()
        booking = EventBooking(
            id="bk_cp_" + "x" * 12, event_id=event.id, user_id=u.id,
            status=BookingStatus.confirmed, source=None,
        )
        db.add(booking); db.flush()
        assert gt.booking_access_source_label(booking) == "Complimentary"

    def test_payment_pending_label(self, db, make_event, make_user):
        event = make_event()
        u = make_user()
        booking = EventBooking(
            id="bk_pp_" + "x" * 12, event_id=event.id, user_id=u.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=15),
        )
        db.add(booking); db.flush()
        assert gt.booking_access_source_label(booking) == "Payment pending"
