"""Stage 5A.4b — the four lifecycle gaps found in the readiness review.

1. Ending a membership told nobody when Stripe's webhook got there
   first, which it almost always does.
2. Resuming a renewal told nobody at all.
3. Dates rendered in UTC, so one period showed two different days
   depending on which surface you read.
4. Resuming twice answered 409 where cancelling twice answers success.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.comms.models import CommunicationEvent
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import PaymentTransaction
from app.services import collective_membership_lifecycle as lifecycle
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()
#: 14:00 UTC on the 20th is 01:00 on the 21st in Melbourne — the case
#: that separates a localised date from a raw one.
CROSSES_MIDNIGHT = datetime(2026, 12, 20, 14, 0, 0)


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")


@pytest.fixture
def space(db, make_space, make_user):
    creator = make_user(role="creator")
    s = make_space(creator=creator)
    s.pricing_type = "paid_monthly"
    s.pricing_amount_cents = 599
    s.pricing_currency = "AUD"
    s.timezone = "Australia/Melbourne"
    db.flush()
    return s


@pytest.fixture
def member(make_user):
    return make_user()


def _agreement(db, space, member, status, **kw):
    kw.setdefault("interval", "month")
    kw.setdefault("interval_count", 1)
    kw.setdefault("amount_cents", 599)
    kw.setdefault("currency", "AUD")
    kw.setdefault("platform_fee_basis_points", 800)
    kw.setdefault("stripe_subscription_id", "sub_live")
    kw.setdefault("current_period_end", CROSSES_MIDNIGHT)
    row = CollectiveMembership(
        id=f"cmem_pol_{len(db.query(CollectiveMembership).all())}",
        space_id=space.id, user_id=member.id,
        creator_user_id=space.creator_id, status=status,
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _events(db, row, event_type):
    return db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == event_type,
        CommunicationEvent.subject_id == row.id,
    ).count()


def _deleted(row):
    return {"id": row.stripe_subscription_id,
            "metadata": {"collective_membership_id": row.id}}


class TestEndingAlwaysNotifies:

    ENDED = "collective.membership.ended"

    def test_the_stripe_webhook_emits_the_ended_event(self, db, space, member):
        """The path that normally runs, and the one that was silent."""
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        handlers.handle_subscription_deleted(
            _deleted(row), db, event_id="evt_del_1")
        db.expire_all()
        assert _events(db, row, self.ENDED) == 1

    def test_the_reconciler_path_still_emits(self, db, space, member):
        from app.services import collective_membership_access as access
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        with patch("stripe.Subscription.delete"):
            access.end_subscription(
                db, subscription=row, reason="paid_period_ended", now=NOW)
        db.flush()
        assert _events(db, row, self.ENDED) == 1

    def test_a_replayed_deletion_does_not_notify_twice(
        self, db, space, member,
    ):
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        handlers.handle_subscription_deleted(
            _deleted(row), db, event_id="evt_del_1")
        handlers.handle_subscription_deleted(
            _deleted(row), db, event_id="evt_del_2")
        db.expire_all()
        assert _events(db, row, self.ENDED) == 1

    def test_webhook_then_reconciler_produces_one_message(
        self, db, space, member,
    ):
        """Both paths may legitimately run. Only one member-facing
        message may come out, which is what the dedupe key is for."""
        from app.services import collective_membership_access as access
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        handlers.handle_subscription_deleted(
            _deleted(row), db, event_id="evt_del_1")
        db.expire_all()
        row = db.query(CollectiveMembership).filter(
            CollectiveMembership.id == row.id).one()
        with patch("stripe.Subscription.delete"):
            access.end_subscription(
                db, subscription=row, reason="reconcile", now=NOW)
        db.flush()
        assert _events(db, row, self.ENDED) == 1

    def test_scheduling_a_cancellation_does_not_say_it_ended(
        self, db, space, member,
    ):
        """The distinction the whole family rests on."""
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        with patch("stripe.Subscription.modify"):
            lifecycle.schedule_cancellation(db, subscription=row, now=NOW)
        db.flush()
        assert _events(db, row, self.ENDED) == 0
        assert _events(
            db, row, "collective.membership.cancellation_scheduled") == 1

    def test_ending_keeps_the_money_and_the_history(self, db, space, member):
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        db.add(PaymentTransaction(
            id="txn_keep", transaction_type="member_collective_subscription",
            status="succeeded", payment_provider="stripe",
            payer_user_id=member.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD", gross_amount_cents=599,
            platform_fee_basis_points=800, platform_fee_cents=48,
            net_creator_amount_cents=551, created_at=NOW, updated_at=NOW,
        ))
        db.flush()
        handlers.handle_subscription_deleted(
            _deleted(row), db, event_id="evt_del_1")
        db.expire_all()
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == "txn_keep").one()
        assert (txn.gross_amount_cents, txn.platform_fee_cents,
                txn.net_creator_amount_cents) == (599, 48, 551)


class TestResumingConfirms:

    RESUMED = "collective.membership.renewal_resumed"

    def _scheduled(self, db, space, member):
        return _agreement(
            db, space, member,
            CollectiveMembershipStatus.cancel_scheduled.value,
            cancel_at_period_end=True, cancelled_at=NOW,
            cancelled_reason="member_cancelled_renewal",
        )

    def test_a_successful_resume_emits_its_own_event(self, db, space, member):
        row = self._scheduled(db, space, member)
        with patch("stripe.Subscription.modify"):
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)
        db.flush()
        assert _events(db, row, self.RESUMED) == 1

    def test_it_is_not_the_reactivated_event(self, db, space, member):
        """Reactivated means access came back after a lapse. This
        member never lost it."""
        row = self._scheduled(db, space, member)
        with patch("stripe.Subscription.modify"):
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)
        db.flush()
        assert _events(db, row, "collective.membership.reactivated") == 0

    def test_the_existing_subscription_is_reused_and_nothing_charged(
        self, db, space, member,
    ):
        row = self._scheduled(db, space, member)
        before = row.stripe_subscription_id
        with patch("stripe.Subscription.modify") as modify, \
             patch("stripe.Subscription.create") as create, \
             patch("stripe.checkout.Session.create") as session:
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)
        modify.assert_called_once()
        assert modify.call_args.kwargs["cancel_at_period_end"] is False
        create.assert_not_called()
        session.assert_not_called()
        assert row.stripe_subscription_id == before
        assert row.current_period_end == CROSSES_MIDNIGHT
        assert row.amount_cents == 599

    def test_a_stripe_failure_sends_no_confirmation(self, db, space, member):
        row = self._scheduled(db, space, member)
        import stripe as _stripe
        with patch("stripe.Subscription.modify",
                   side_effect=_stripe.StripeError("nope")):
            with pytest.raises(_stripe.StripeError):
                lifecycle.resume_cancelled_renewal(
                    db, subscription=row, now=NOW)
        assert _events(db, row, self.RESUMED) == 0
        assert row.status == CollectiveMembershipStatus.cancel_scheduled.value

    def test_resuming_twice_confirms_once(self, db, space, member):
        row = self._scheduled(db, space, member)
        with patch("stripe.Subscription.modify"):
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)
        db.flush()
        assert _events(db, row, self.RESUMED) == 1


class TestRepeatedResumeIsIdempotent:

    def test_an_already_active_agreement_returns_rather_than_raises(
        self, db, space, member,
    ):
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value,
                         cancel_at_period_end=False)
        with patch("stripe.Subscription.modify") as modify:
            out = lifecycle.resume_cancelled_renewal(
                db, subscription=row, now=NOW)
        assert out is row
        assert out.status == CollectiveMembershipStatus.active.value
        modify.assert_not_called()

    @pytest.mark.parametrize("status", [
        CollectiveMembershipStatus.ended.value,
        CollectiveMembershipStatus.cancelled.value,
        CollectiveMembershipStatus.pending.value,
    ])
    def test_a_genuinely_invalid_state_still_raises(
        self, db, space, member, status,
    ):
        """Idempotency is narrow on purpose — succeeding here would
        hide a real problem."""
        row = _agreement(db, space, member, status)
        with pytest.raises(ValueError):
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)

    def test_an_active_agreement_still_winding_down_is_not_swallowed(
        self, db, space, member,
    ):
        """``active`` with ``cancel_at_period_end`` set still needs the
        Stripe call — the shortcut must not absorb it."""
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value,
                         cancel_at_period_end=True)
        with pytest.raises(ValueError):
            lifecycle.resume_cancelled_renewal(db, subscription=row, now=NOW)

    def test_cancelling_twice_is_still_idempotent(self, db, space, member):
        row = _agreement(db, space, member,
                         CollectiveMembershipStatus.active.value)
        with patch("stripe.Subscription.modify"):
            lifecycle.schedule_cancellation(db, subscription=row, now=NOW)
            first = row.cancelled_at
            lifecycle.schedule_cancellation(
                db, subscription=row, now=NOW + timedelta(hours=1))
        assert row.cancelled_at == first
        db.flush()
        assert _events(
            db, row, "collective.membership.cancellation_scheduled") == 1
