"""Stage 5A close — voluntary departure says what it actually did.

Leaving a paid Collective cancelled a live subscription, ended access
and refunded nothing, and the member was told none of it: the dialog
predated paid membership and no message was sent at all.

The hard part is honesty about the billing. Cancelling at Stripe can
fail while the departure succeeds — deliberately, because a member
must be able to leave when Stripe is unreachable — so the message has
two forms, and the reconciler closes the second one when its retry
lands.
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
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import membership_removal

NOW = datetime.utcnow()
DEPARTED = "collective.membership.voluntary_departure"
BILLING_STOPPED = "collective.membership.departure_billing_stopped"


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


@pytest.fixture
def world(db, space, member):
    sm = SpaceMembership(
        id="sm_dep", space_id=space.id, user_id=member.id,
        role="learner", status=SpaceMembershipStatus.active, joined_at=NOW,
    )
    db.add(sm)
    agreement = CollectiveMembership(
        id="cmem_dep", space_id=space.id, user_id=member.id,
        creator_user_id=space.creator_id,
        status=CollectiveMembershipStatus.active.value,
        interval="month", interval_count=1, amount_cents=599, currency="AUD",
        platform_fee_basis_points=800,
        stripe_customer_id="cus_s", stripe_subscription_id="sub_live",
        current_period_end=NOW + timedelta(days=28),
        created_at=NOW, updated_at=NOW,
    )
    db.add(agreement)
    db.flush()
    return {"space": space, "member": member, "sm": sm, "sub": agreement}


def _leave(db, world, **kw):
    return membership_removal.end_membership(
        db,
        membership=world["sm"], space=world["space"],
        actor_user_id=world["member"].id, now=NOW,
        decision=membership_removal.RemovalDecision(
            kind=kw.pop("kind", membership_removal.REMOVAL_VOLUNTARY),
        ),
        revoke_purchased_access=False, cancel_passes=False,
        cancel_future_bookings=False, note="left",
        **kw,
    )


def _events(db, event_type):
    return db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == event_type).count()


def _payload(db, event_type):
    row = db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == event_type).one()
    return row.payload or {}


class TestLeavingIsConfirmed:

    def test_a_successful_departure_is_confirmed(self, db, world):
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
        db.flush()
        assert _events(db, DEPARTED) == 1

    def test_it_reports_the_billing_as_cancelled(self, db, world):
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
        db.flush()
        assert _payload(db, DEPARTED)["billing_cancelled"] is True

    def test_it_is_not_the_membership_ended_message(self, db, world):
        """Leaving is the member's own act, not something that
        happened to them."""
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
        db.flush()
        assert _events(db, "collective.membership.ended") == 0

    def test_a_creator_removal_does_not_say_you_left(self, db, world):
        """The same function serves removals and bans."""
        with patch("stripe.Subscription.delete"):
            _leave(db, world, kind=membership_removal.REMOVAL_BY_CREATOR)
        db.flush()
        assert _events(db, DEPARTED) == 0

    def test_leaving_a_free_collective_sends_nothing(
        self, db, world,
    ):
        """No billing outcome to report, and the screen already said
        the rest."""
        world["space"].pricing_type = "free"
        db.delete(world["sub"])
        db.flush()
        with patch("stripe.Subscription.delete") as delete:
            _leave(db, world)
        db.flush()
        delete.assert_not_called()
        assert _events(db, DEPARTED) == 0


class TestWhenStripeWillNotCancel:

    def _failing(self, db, world):
        import stripe as _stripe
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            return _leave(db, world)

    def test_the_member_still_leaves(self, db, world):
        self._failing(db, world)
        assert world["sm"].status is SpaceMembershipStatus.removed

    def test_the_message_does_not_promise_payments_have_stopped(
        self, db, world,
    ):
        self._failing(db, world)
        db.flush()
        assert _events(db, DEPARTED) == 1
        assert _payload(db, DEPARTED)["billing_cancelled"] is False

    def test_the_rendered_wording_differs(self, db, world):
        import app.comms.templates  # noqa: F401
        from app.comms.templates.registry import get_template_for
        from app.comms.routing.resolver import ResolvedRecipient

        tpl = get_template_for(DEPARTED, "email_transactional")
        base = {"first_name": "Sophie", "collective_name": "Tom's",
                "membership_url": "https://x/settings/membership"}

        def render(cancelled):
            r = ResolvedRecipient(
                user_id="u", role_in_event="member", human_reason="",
                template_context={**base, "billing_cancelled": cancelled})
            return tpl.render(db, None, r).body_text

        done, pending = render(True), render(False)
        assert "no further payments will be taken" in done
        assert "still finalising" in pending
        assert "no further payments will be taken" not in pending

    def test_the_operator_flag_is_raised(self, db, world):
        self._failing(db, world)
        assert world["sm"].payment_action_required is True


class TestTheRecoveryCloses:

    def test_the_reconciler_confirms_when_its_retry_lands(self, db, world):
        from app.services import collective_membership_reconcile as rec

        import stripe as _stripe
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            _leave(db, world)
        db.flush()
        assert _payload(db, DEPARTED)["billing_cancelled"] is False

        with patch("stripe.Subscription.delete"):
            rec._sweep_billing_after_departure(
                db, now=datetime.utcnow(), report=rec.ReconcileReport())
        db.flush()
        assert _events(db, BILLING_STOPPED) == 1

    def test_it_does_not_fire_when_the_first_message_was_already_final(
        self, db, world,
    ):
        """Nothing outlived the departure, so there is nothing to
        close."""
        from app.services import collective_membership_reconcile as rec

        with patch("stripe.Subscription.delete"):
            _leave(db, world)
            rec._sweep_billing_after_departure(
                db, now=datetime.utcnow(), report=rec.ReconcileReport())
        db.flush()
        assert _events(db, BILLING_STOPPED) == 0

    def test_repeated_sweeps_confirm_once(self, db, world):
        from app.services import collective_membership_reconcile as rec

        import stripe as _stripe
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            _leave(db, world)
        with patch("stripe.Subscription.delete"):
            for _ in range(2):
                rec._sweep_billing_after_departure(
                    db, now=datetime.utcnow(), report=rec.ReconcileReport())
        db.flush()
        assert _events(db, BILLING_STOPPED) == 1


class TestNothingElseChanges:

    def test_the_payment_record_survives(self, db, world, space, member):
        db.add(PaymentTransaction(
            id="txn_dep", transaction_type="member_collective_subscription",
            status="succeeded", payment_provider="stripe",
            payer_user_id=member.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD", gross_amount_cents=599,
            platform_fee_basis_points=800, platform_fee_cents=48,
            net_creator_amount_cents=551, created_at=NOW, updated_at=NOW,
        ))
        db.flush()
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == "txn_dep").one()
        assert (txn.gross_amount_cents, txn.platform_fee_cents,
                txn.net_creator_amount_cents) == (599, 48, 551)

    def test_no_refund_is_issued(self, db, world):
        with patch("stripe.Subscription.delete"), \
             patch("stripe.Refund.create") as refund:
            _leave(db, world)
        refund.assert_not_called()

    def test_a_voluntary_departure_still_permits_rejoining(self, db, world):
        from app.services import membership_grant
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
        assert membership_grant.may_rejoin(world["sm"]) is True

    def test_leaving_twice_confirms_once(self, db, world):
        """The route 404s a second attempt; the service is pinned too."""
        with patch("stripe.Subscription.delete"):
            _leave(db, world)
            _leave(db, world)
        db.flush()
        assert _events(db, DEPARTED) == 1
