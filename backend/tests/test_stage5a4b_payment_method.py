"""Stage 5A.4b — the card change that 500'd after Stripe had accepted it.

``dict()`` on a ``StripeObject`` raises ``KeyError: 0``. In
stripe-python 15.x a ``StripeObject`` is not a dict subclass and has
neither ``keys()`` nor ``get()``, so ``dict()`` cannot use the mapping
protocol and falls back to the legacy sequence one — asking for
``obj[0]``.

Only one of the two completion paths ever hit it. The webhook unpacks
its event with ``json.loads`` and is plain dicts throughout; the return
page retrieves a live ``StripeObject``. So in production the webhook
applied the card and the browser reported failure.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from stripe import StripeObject

from app.comms.models import CommunicationEvent
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import PaymentTransaction
from app.services import collective_membership_payment_method as pm
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()
PM_UPDATED = "collective.membership.payment_method_updated"


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
def agreement(db, space, member):
    row = CollectiveMembership(
        id="cmem_pm_test", space_id=space.id, user_id=member.id,
        creator_user_id=space.creator_id,
        status=CollectiveMembershipStatus.active.value,
        interval="month", interval_count=1, amount_cents=599, currency="AUD",
        platform_fee_basis_points=800,
        stripe_customer_id="cus_sophie",
        stripe_subscription_id="sub_live",
        current_period_end=NOW + timedelta(days=28),
        created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _raw(agreement, *, session_id="cs_setup_1", customer="cus_sophie",
         pm_id="pm_new", purchase_type=None):
    return {
        "id": session_id, "object": "checkout.session",
        "customer": customer,
        "metadata": {
            "purchase_type": purchase_type or pm.METADATA_PURCHASE_TYPE,
            "collective_membership_id": agreement.id,
        },
        "setup_intent": {"id": "seti_1", "payment_method": pm_id},
    }


def _stripe_object(raw):
    """The shape the *return page* gets: a live StripeObject."""
    return StripeObject.construct_from(raw, "sk_test_x")


def _events(db, event_type=PM_UPDATED):
    return db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == event_type).count()


# ===========================================================================
# The exception itself
# ===========================================================================


class TestTheStripeObjectConversion:

    def test_a_StripeObject_is_not_a_dict_and_has_no_keys(self):
        """The two facts the old code assumed away."""
        md = _stripe_object({"metadata": {"a": "b"}})["metadata"]
        assert not isinstance(md, dict)
        assert not hasattr(md, "keys")

    def test_the_old_conversion_still_raises_KeyError_zero(self):
        """Pinned so nobody reintroduces ``dict(stripe_object)``."""
        md = _stripe_object({"metadata": {"a": "b"}})["metadata"]
        with pytest.raises(KeyError) as caught:
            dict(md)
        assert caught.value.args[0] == 0

    def test_the_helper_reads_both_shapes(self, agreement):
        raw = _raw(agreement)
        assert pm._mapping_field(_stripe_object(raw), "metadata") == raw["metadata"]
        assert pm._mapping_field(raw, "metadata") == raw["metadata"]

    def test_an_absent_or_unreadable_field_is_empty_not_a_guess(self, agreement):
        assert pm._mapping_field(_stripe_object(_raw(agreement)), "nope") == {}
        assert pm._mapping_field({}, "metadata") == {}


# ===========================================================================
# Ownership is unchanged by the fix
# ===========================================================================


class TestOwnershipStillHolds:

    @pytest.mark.parametrize("shape", ["stripe_object", "dict"])
    def test_a_session_for_another_agreement_is_refused(
        self, db, agreement, shape,
    ):
        raw = _raw(agreement)
        raw["metadata"]["collective_membership_id"] = "cmem_somebody_else"
        session = _stripe_object(raw) if shape == "stripe_object" else raw
        with pytest.raises(pm.PaymentMethodUnavailable):
            pm.apply_session(db, subscription=agreement, session=session, now=NOW)

    @pytest.mark.parametrize("shape", ["stripe_object", "dict"])
    def test_a_session_for_another_customer_is_refused(
        self, db, agreement, shape,
    ):
        raw = _raw(agreement, customer="cus_someone_else")
        session = _stripe_object(raw) if shape == "stripe_object" else raw
        with pytest.raises(pm.PaymentMethodUnavailable):
            pm.apply_session(db, subscription=agreement, session=session, now=NOW)

    def test_a_session_of_the_wrong_kind_is_refused(self, db, agreement):
        raw = _raw(agreement, purchase_type="something_else")
        with pytest.raises(pm.PaymentMethodUnavailable):
            pm.apply_session(
                db, subscription=agreement, session=_stripe_object(raw), now=NOW)

    def test_unreadable_metadata_refuses_rather_than_proceeds(
        self, db, agreement,
    ):
        """``{}`` fails the ownership checks, which is the safe way to
        fail."""
        class Hostile:
            def to_dict(self):
                raise RuntimeError("no")
        with patch.object(pm, "_session_field", return_value=Hostile()):
            with pytest.raises(pm.PaymentMethodUnavailable):
                pm.apply_session(
                    db, subscription=agreement,
                    session=_stripe_object(_raw(agreement)), now=NOW)


# ===========================================================================
# Both completion paths, and the race between them
# ===========================================================================


class TestCompletionPaths:

    def test_the_browser_path_now_succeeds(self, db, agreement):
        """The production 500, fixed."""
        with patch("stripe.Subscription.modify") as modify:
            out = pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        assert out["updated"] is True
        assert out["already_applied"] is False
        modify.assert_called_once_with(
            "sub_live", default_payment_method="pm_new")

    def test_the_webhook_path_still_succeeds(self, db, agreement):
        with patch("stripe.Subscription.modify"):
            out = pm.apply_session(
                db, subscription=agreement, session=_raw(agreement), now=NOW)
        assert out["updated"] is True

    def test_webhook_first_then_browser_is_recognised_as_done(
        self, db, agreement,
    ):
        """The browser must not report failure for work already done."""
        raw = _raw(agreement)
        with patch("stripe.Subscription.modify") as modify:
            pm.apply_session(db, subscription=agreement, session=raw, now=NOW)
            second = pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
        assert second["updated"] is True
        assert second["already_applied"] is True
        modify.assert_called_once()          # Stripe asked exactly once

    def test_browser_first_then_webhook_is_also_recognised(
        self, db, agreement,
    ):
        raw = _raw(agreement)
        with patch("stripe.Subscription.modify") as modify:
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
            second = pm.apply_session(
                db, subscription=agreement, session=raw, now=NOW)
        assert second["already_applied"] is True
        modify.assert_called_once()

    def test_an_incomplete_setup_changes_nothing(self, db, agreement):
        raw = _raw(agreement)
        raw["setup_intent"] = None
        with patch("stripe.Subscription.modify") as modify:
            out = pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
        assert out["updated"] is False
        assert out["reason"] == "no_payment_method_yet"
        modify.assert_not_called()

    def test_a_later_session_replaces_an_earlier_one(self, db, agreement):
        """Last-completed-wins, kept deliberately."""
        with patch("stripe.Subscription.modify") as modify:
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(
                    _raw(agreement, session_id="cs_setup_2", pm_id="pm_newer")),
                now=NOW)
        assert agreement.payment_method_setup_session_id == "cs_setup_2"
        assert modify.call_count == 2


# ===========================================================================
# Isolation and safety
# ===========================================================================


class TestNothingElseMoves:

    def test_only_the_subscription_default_changes(self, db, agreement):
        with patch("stripe.Subscription.modify") as modify, \
             patch("stripe.Customer.modify") as customer, \
             patch("stripe.Subscription.create") as create, \
             patch("stripe.Invoice.create") as invoice, \
             patch("stripe.Invoice.pay") as pay, \
             patch("stripe.PaymentIntent.create") as intent:
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        modify.assert_called_once_with(
            "sub_live", default_payment_method="pm_new")
        for never in (customer, create, invoice, pay, intent):
            never.assert_not_called()

    def test_the_agreement_keeps_its_identity_and_terms(self, db, agreement):
        before = (agreement.stripe_subscription_id, agreement.amount_cents,
                  agreement.currency, agreement.current_period_end,
                  agreement.status)
        with patch("stripe.Subscription.modify"):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        assert (agreement.stripe_subscription_id, agreement.amount_cents,
                agreement.currency, agreement.current_period_end,
                agreement.status) == before

    def test_financial_records_are_untouched(self, db, agreement, space, member):
        db.add(PaymentTransaction(
            id="txn_pm", transaction_type="member_collective_subscription",
            status="succeeded", payment_provider="stripe",
            payer_user_id=member.id, creator_user_id=space.creator_id,
            space_id=space.id, currency="AUD", gross_amount_cents=599,
            platform_fee_basis_points=800, platform_fee_cents=48,
            net_creator_amount_cents=551, created_at=NOW, updated_at=NOW,
        ))
        db.flush()
        with patch("stripe.Subscription.modify"):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.id == "txn_pm").one()
        assert (txn.gross_amount_cents, txn.platform_fee_cents,
                txn.net_creator_amount_cents) == (599, 48, 551)

    def test_an_active_membership_is_never_charged(self, db, agreement):
        """``_retry_open_invoice`` only runs during recovery."""
        with patch("stripe.Subscription.modify"), \
             patch("stripe.Invoice.list") as listed, \
             patch("stripe.Invoice.pay") as pay:
            out = pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        assert out["payment_retried"] is False
        listed.assert_not_called()
        pay.assert_not_called()


# ===========================================================================
# The confirmation
# ===========================================================================


class TestTheMemberIsTold:

    def test_a_successful_change_emits_a_confirmation(self, db, agreement):
        with patch("stripe.Subscription.modify"):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        db.flush()
        assert _events(db) == 1

    def test_the_two_paths_confirm_once_between_them(self, db, agreement):
        raw = _raw(agreement)
        with patch("stripe.Subscription.modify"):
            pm.apply_session(db, subscription=agreement, session=raw, now=NOW)
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
        db.flush()
        assert _events(db) == 1

    def test_a_duplicate_webhook_confirms_once(self, db, agreement):
        raw = _raw(agreement)
        with patch("stripe.Subscription.modify"):
            pm.apply_session(db, subscription=agreement, session=raw, now=NOW)
            pm.apply_session(db, subscription=agreement, session=raw, now=NOW)
        db.flush()
        assert _events(db) == 1

    def test_two_genuine_card_changes_each_confirm(self, db, agreement):
        """Keyed on the Session, not the agreement — a member may
        legitimately change their card twice."""
        with patch("stripe.Subscription.modify"):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(
                    _raw(agreement, session_id="cs_setup_2")), now=NOW)
        db.flush()
        assert _events(db) == 2

    def test_an_incomplete_setup_confirms_nothing(self, db, agreement):
        raw = _raw(agreement)
        raw["setup_intent"] = None
        with patch("stripe.Subscription.modify"):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
        db.flush()
        assert _events(db) == 0

    def test_a_refused_session_confirms_nothing(self, db, agreement):
        raw = _raw(agreement, customer="cus_other")
        with pytest.raises(pm.PaymentMethodUnavailable):
            pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(raw), now=NOW)
        assert _events(db) == 0

    def test_a_routing_failure_cannot_undo_the_change(
        self, db, agreement, monkeypatch,
    ):
        monkeypatch.setattr(
            "app.comms.rollout.schedule_routing_if_needed",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("comms down")),
        )
        with patch("stripe.Subscription.modify"):
            out = pm.apply_session(
                db, subscription=agreement,
                session=_stripe_object(_raw(agreement)), now=NOW)
        from app.services import collective_membership_emit as emit_mod
        emit_mod.route_pending(db)
        assert out["updated"] is True
        assert agreement.payment_method_setup_session_id == "cs_setup_1"

    def test_the_webhook_handler_commits_and_routes(self, db, agreement):
        """End to end through the real handler."""
        with patch("stripe.Subscription.modify"):
            handlers.handle_payment_method_setup_completed(
                _raw(agreement), db, event_id="evt_pm_1")
        db.expire_all()
        row = db.query(CollectiveMembership).filter(
            CollectiveMembership.id == agreement.id).one()
        assert row.payment_method_setup_session_id == "cs_setup_1"
        assert row.payment_method_updated_at is not None
        assert _events(db) == 1
