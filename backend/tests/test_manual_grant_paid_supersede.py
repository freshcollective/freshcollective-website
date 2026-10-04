"""Converting a complimentary Creator grant into a paid subscription.

The defect this covers was a live billing failure, not a future
feature. ``creator_subscriptions_one_active_per_user_uidx`` is
``UNIQUE (user_id) WHERE status IN ('active','trialing')``, so a
complimentary grant held the only active slot. A creator who paid to
continue therefore hit one of:

  * the ``invoice.paid`` webhook writing ``status='active'`` into an
    occupied slot → IntegrityError *after* the charge, failing on every
    redelivery;
  * the claim path's idempotency check keying on ``creator_plan_id``
    alone → "manual Creator" read as "paid Creator", a silent no-op
    that recorded no paid subscription;
  * ``ActivationConflictError`` when the paid plan differed.

All three took the money and failed to grant what was bought. Both
paths now route through ``supersede_active_manual_grant``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import stripe

from app.creator.plan_activation import (
    ActivationConflictError,
    ActivationSource,
    SUPERSEDED_BY_PAID_REASON,
    activate_creator_plan,
)
from app.creator.plan_guards import resolve_creator_plan
from app.models.creator_billing import (
    CreatorPlan,
    CreatorPlanGrant,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)

_RETRIEVE = "app.webhooks.creator_billing_handlers.scb.retrieve_subscription"
GRANT_STARTED = datetime(2026, 4, 4, 12, 0, 0)
GRANT_ENDS = datetime(2026, 10, 4, 12, 0, 0)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def plans(db):
    out = {}
    for slug, cents in (("community", 0), ("creator", 1900), ("pro", 7900),
                        ("founding-creator", 0), ("organisation", 0)):
        row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if row is None:
            row = CreatorPlan(
                id=_uid("cp"), name=slug.title(), slug=slug,
                monthly_price_cents=cents, currency="AUD",
                transaction_fee_basis_points=0 if cents == 0 else 800,
                collective_limit=1, is_active=True,
            )
            db.add(row)
        out[slug] = row
    db.flush()
    return out


def _grant(db, user, plan, *, reason="comp", status=CreatorSubscriptionStatus.active):
    sub = CreatorSubscription(
        id=_uid("sub"), user_id=user.id, creator_plan_id=plan.id,
        status=status, starts_at=GRANT_STARTED, ends_at=GRANT_ENDS,
        source="manual_grant", grant_reason=reason,
        grant_note="internal note — must not leak",
    )
    db.add(sub)
    db.flush()
    return sub


def _paid_source(sub_id="sub_live_1", cus_id="cus_live_1"):
    return ActivationSource(
        source="stripe_paid",
        stripe_subscription_id=sub_id,
        stripe_customer_id=cus_id,
    )


def _active_rows(db, user):
    return (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == user.id,
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
            ]),
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Claim path — activate_creator_plan
# ---------------------------------------------------------------------------


class TestManualCreatorToPaidCreator:
    """Same plan. Previously a silent no-op: the grant was returned and
    no paid subscription was ever recorded."""

    def test_the_paid_subscription_activates(self, plans, db, make_user):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])

        result = activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        assert result.was_noop is False, (
            "a paid activation must not be mistaken for the grant it replaces"
        )
        assert result.subscription.source == "stripe_paid"
        assert result.subscription.status == CreatorSubscriptionStatus.active
        assert result.subscription.stripe_subscription_id == "sub_live_1"

    def test_the_grant_leaves_the_active_slot(self, plans, db, make_user):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])

        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        assert grant.status == CreatorSubscriptionStatus.cancelled
        assert len(_active_rows(db, creator)) == 1, (
            "the partial unique index allows exactly one active row"
        )

    def test_the_commit_succeeds_without_an_index_violation(
        self, plans, db, make_user,
    ):
        """The failure mode was an IntegrityError at write time."""
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])

        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()   # would raise if both rows were active

    def test_the_canonical_plan_is_now_the_paid_one(self, plans, db, make_user):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])

        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        resolved = resolve_creator_plan(creator, db)
        assert resolved is not None
        assert resolved.slug == "creator"
        assert resolved.paid_offers_enabled is True


class TestManualCreatorToPaidPro:
    """Different plan. Previously ActivationConflictError, after the
    charge."""

    def test_the_upgrade_succeeds(self, plans, db, make_user):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])

        result = activate_creator_plan(db, creator, "pro", _paid_source())
        db.flush()

        assert result.subscription.source == "stripe_paid"
        assert result.subscription.creator_plan_id == plans["pro"].id
        assert grant.status == CreatorSubscriptionStatus.cancelled
        assert len(_active_rows(db, creator)) == 1

    def test_no_activation_conflict_is_raised(self, plans, db, make_user):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])
        try:
            activate_creator_plan(db, creator, "pro", _paid_source())
        except ActivationConflictError as exc:  # pragma: no cover
            pytest.fail(f"paid upgrade must not conflict with a grant: {exc}")

    def test_pro_becomes_the_canonical_current_plan(self, plans, db, make_user):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])

        activate_creator_plan(db, creator, "pro", _paid_source())
        db.flush()
        assert resolve_creator_plan(creator, db).slug == "pro"


# ---------------------------------------------------------------------------
# What must NOT change
# ---------------------------------------------------------------------------


class TestOrdinaryPaidFlowUnchanged:
    def test_a_creator_with_no_grant_activates_normally(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        result = activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        assert result.was_noop is False
        assert result.subscription.source == "stripe_paid"
        assert len(_active_rows(db, creator)) == 1

    def test_a_repeat_paid_activation_on_the_same_plan_is_still_a_no_op(
        self, plans, db, make_user,
    ):
        """The idempotency branch must survive for same-source repeats —
        only the manual_grant case was wrong."""
        creator = make_user(role="creator")
        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()
        second = activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        assert second.was_noop is True
        assert len(_active_rows(db, creator)) == 1

    def test_two_different_paid_plans_still_conflict(
        self, plans, db, make_user,
    ):
        """Supersede is for grants only. Two paid subscriptions remain a
        genuine conflict the caller must resolve."""
        creator = make_user(role="creator")
        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()
        with pytest.raises(ActivationConflictError):
            activate_creator_plan(db, creator, "pro", _paid_source("sub_live_2"))

    def test_an_admin_grant_does_not_supersede_another_grant(
        self, plans, db, make_user,
    ):
        """Only ``stripe_paid`` supersedes. Admin grant-over-grant must
        keep its existing conflict behaviour so Change Plan stays the
        deliberate path."""
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])
        with pytest.raises(ActivationConflictError):
            activate_creator_plan(
                db, creator, "pro",
                ActivationSource(source="manual_grant", reason="comp"),
            )

    @pytest.mark.parametrize("slug", ["founding-creator", "organisation"])
    def test_other_plans_are_untouched_by_this_path(
        self, plans, db, make_user, slug,
    ):
        """A Founding Creator / Organisation grant is only ever displaced
        by a genuine paid activation — never spontaneously."""
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans[slug], reason="internal")
        db.flush()
        assert grant.status == CreatorSubscriptionStatus.active
        assert resolve_creator_plan(creator, db).slug == slug


# ---------------------------------------------------------------------------
# Audit provenance
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_the_grant_row_is_preserved_not_deleted(self, plans, db, make_user):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        grant_id = grant.id

        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        still_there = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.id == grant_id)
            .one()
        )
        assert still_there.source == "manual_grant"
        assert still_there.grant_reason == "comp"
        # The complimentary period stays readable after conversion.
        assert still_there.starts_at == GRANT_STARTED
        assert still_there.ends_at == GRANT_ENDS

    def test_the_transition_reason_is_explicit(self, plans, db, make_user):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])

        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        assert SUPERSEDED_BY_PAID_REASON == "superseded_by_paid_subscription"
        event = (
            db.query(CreatorPlanGrant)
            .filter(
                CreatorPlanGrant.subscription_id == grant.id,
                CreatorPlanGrant.action == "revoked",
            )
            .one()
        )
        assert event.reason == SUPERSEDED_BY_PAID_REASON
        # No admin did this.
        assert event.actor_user_id is None
        assert grant.revoked_by_user_id is None
        assert "paid" in (grant.revoked_reason or "").lower()

    def test_the_internal_grant_note_is_not_rewritten(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()
        assert grant.grant_note == "internal note — must not leak"


# ---------------------------------------------------------------------------
# Webhook path — the one that actually broke
# ---------------------------------------------------------------------------


def _real_subscription(**kwargs) -> stripe.Subscription:
    return stripe.Subscription.construct_from(
        {
            "id": kwargs.get("id", "sub_live_1"),
            "object": "subscription",
            "customer": "cus_live_1",
            "current_period_end": 1793000000,
            "cancel_at_period_end": False,
            "metadata": kwargs.get("metadata", {}),
        },
        "sk_test_dummy",
    )


def _creator_sub_object(*, creator_user_id: str, plan_slug: str = "creator",
                        sub_id: str = "sub_live_1") -> stripe.Subscription:
    return _real_subscription(
        id=sub_id,
        metadata={
            "purchase_type": "creator_subscription",
            "creator_user_id": creator_user_id,
            "creator_plan_slug": plan_slug,
        },
    )


def _invoice(*, subscription_id: str) -> dict:
    return {
        "id": f"in_{uuid.uuid4().hex[:12]}",
        "object": "invoice",
        "subscription": subscription_id,
    }


class TestInvoicePaidWebhook:
    @staticmethod
    def _placeholder(db, creator, plan, sub_id="sub_live_1"):
        """What ``checkout.session.completed`` leaves behind: a linked
        but not-yet-activated paid row."""
        row = CreatorSubscription(
            id=_uid("csub"), user_id=creator.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.past_due,
            starts_at=datetime.utcnow(), source="stripe_paid",
            stripe_subscription_id=sub_id, stripe_customer_id="cus_live_1",
        )
        db.add(row)
        db.flush()
        return row

    def _fire(self, db, creator, sub_id="sub_live_1", plan_slug="creator",
              event_id=None):
        from app.webhooks.creator_billing_handlers import handle_invoice_paid
        subscription = _creator_sub_object(
            creator_user_id=creator.id, plan_slug=plan_slug, sub_id=sub_id,
        )
        with patch(_RETRIEVE, return_value=subscription):
            return handle_invoice_paid(
                _invoice(subscription_id=sub_id),
                db,
                event_id=event_id or f"evt_{uuid.uuid4().hex[:12]}",
                event_type="invoice.paid",
            )

    def test_activation_succeeds_with_an_active_grant_present(
        self, plans, db, make_user,
    ):
        """Previously an IntegrityError after the charge."""
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        paid = self._placeholder(db, creator, plans["creator"])
        db.commit()

        assert self._fire(db, creator) is True
        db.expire_all()

        db.refresh(paid)
        db.refresh(grant)
        assert paid.status == CreatorSubscriptionStatus.active
        assert grant.status == CreatorSubscriptionStatus.cancelled
        assert len(_active_rows(db, creator)) == 1

    def test_the_grant_transition_is_audited_from_the_webhook_too(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        self._placeholder(db, creator, plans["creator"])
        db.commit()

        self._fire(db, creator)
        db.expire_all()

        event = (
            db.query(CreatorPlanGrant)
            .filter(
                CreatorPlanGrant.subscription_id == grant.id,
                CreatorPlanGrant.action == "revoked",
            )
            .one()
        )
        assert event.reason == SUPERSEDED_BY_PAID_REASON

    def test_redelivery_is_idempotent(self, plans, db, make_user):
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        paid = self._placeholder(db, creator, plans["creator"])
        db.commit()

        self._fire(db, creator)
        db.expire_all()
        db.refresh(grant)
        first_revoked_at = grant.revoked_at

        # Same subscription, a fresh delivery id (a genuine redelivery
        # reuses the event id and is stopped by the dedup table; this is
        # the harder case of a *different* event for the same sub).
        self._fire(db, creator)
        self._fire(db, creator)
        db.expire_all()

        db.refresh(grant)
        db.refresh(paid)
        assert grant.revoked_at == first_revoked_at, "no repeated transition"
        assert paid.status == CreatorSubscriptionStatus.active
        assert len(_active_rows(db, creator)) == 1
        events = (
            db.query(CreatorPlanGrant)
            .filter(
                CreatorPlanGrant.subscription_id == grant.id,
                CreatorPlanGrant.action == "revoked",
            )
            .all()
        )
        assert len(events) == 1, "one audit row per actual transition"

    def test_the_right_paid_row_is_identified_by_stripe_id(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"])
        wrong = self._placeholder(db, creator, plans["creator"], sub_id="sub_other")
        right = self._placeholder(db, creator, plans["creator"], sub_id="sub_live_1")
        db.commit()

        self._fire(db, creator, sub_id="sub_live_1")
        db.expire_all()

        db.refresh(right)
        db.refresh(wrong)
        assert right.status == CreatorSubscriptionStatus.active
        assert wrong.status == CreatorSubscriptionStatus.past_due

    def test_an_ordinary_renewal_without_a_grant_is_unaffected(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        paid = self._placeholder(db, creator, plans["creator"])
        db.commit()

        assert self._fire(db, creator) is True
        db.expire_all()
        db.refresh(paid)
        assert paid.status == CreatorSubscriptionStatus.active
        assert len(_active_rows(db, creator)) == 1


class TestSupersedePredicateBoundaries:
    """Direct coverage for the two narrow filters in
    ``supersede_active_manual_grant``. Both are defensive, and both were
    invisible to the end-to-end tests above — which is exactly how a
    defensive clause rots.
    """

    def test_only_rows_holding_the_active_slot_are_superseded(
        self, plans, db, make_user,
    ):
        """``creator_subscriptions_one_active_per_user_uidx`` covers
        ``active`` and ``trialing`` only. A ``past_due`` grant is not in
        the way, so touching it would be an unrequested revocation.
        """
        from app.creator.plan_activation import supersede_active_manual_grant

        creator = make_user(role="creator")
        grant = _grant(
            db, creator, plans["creator"],
            status=CreatorSubscriptionStatus.past_due,
        )
        db.flush()

        superseded = supersede_active_manual_grant(db, creator.id)
        db.flush()

        assert superseded is None
        assert grant.status == CreatorSubscriptionStatus.past_due
        assert grant.revoked_at is None

    def test_a_trialing_grant_is_superseded(self, plans, db, make_user):
        """``trialing`` does hold the slot, so it must be displaced."""
        from app.creator.plan_activation import supersede_active_manual_grant

        creator = make_user(role="creator")
        grant = _grant(
            db, creator, plans["creator"],
            status=CreatorSubscriptionStatus.trialing,
        )
        db.flush()

        superseded = supersede_active_manual_grant(db, creator.id)
        db.flush()

        assert superseded is not None
        assert grant.status == CreatorSubscriptionStatus.cancelled

    def test_keep_subscription_id_protects_the_row_being_activated(
        self, plans, db, make_user,
    ):
        """Guards the degenerate case of the caller's own row being a
        manual grant — it must never revoke the thing it is activating.
        """
        from app.creator.plan_activation import supersede_active_manual_grant

        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        db.flush()

        superseded = supersede_active_manual_grant(
            db, creator.id, keep_subscription_id=grant.id,
        )
        db.flush()

        assert superseded is None
        assert grant.status == CreatorSubscriptionStatus.active

    def test_calling_it_twice_transitions_once(self, plans, db, make_user):
        from app.creator.plan_activation import supersede_active_manual_grant

        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        db.flush()

        first = supersede_active_manual_grant(db, creator.id)
        db.flush()
        revoked_at = grant.revoked_at
        second = supersede_active_manual_grant(db, creator.id)
        db.flush()

        assert first is not None
        assert second is None, "already out of the slot — nothing to do"
        assert grant.revoked_at == revoked_at
        assert len(
            db.query(CreatorPlanGrant)
            .filter(
                CreatorPlanGrant.subscription_id == grant.id,
                CreatorPlanGrant.action == "revoked",
            )
            .all()
        ) == 1


class TestConvertedCreatorIsSafeFromExpiry:
    """Cross-check against the (still unarmed) expiry reconciler.

    Before the supersede fix, a converted creator's row stayed
    ``source='manual_grant'`` with ``grant_reason='comp'`` and its
    original ``ends_at``. The expiry reconciler matches exactly that
    shape, so arming it would have revoked Creator access from someone
    Stripe was charging every month. The supersede closes that by
    taking the grant out of ``status='active'``, which is the first
    clause of the reconciler's predicate.
    """

    def test_a_converted_grant_is_no_longer_a_candidate_for_expiry(
        self, plans, db, make_user,
    ):
        from app.services.creator_grant_expiry import reconcile_expired_grants

        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"])
        # The grant's term has passed — the reconciler's other clauses
        # all match, so only the status change protects this creator.
        activate_creator_plan(db, creator, "creator", _paid_source())
        db.flush()

        report = reconcile_expired_grants(
            db, GRANT_ENDS + timedelta(days=30), apply=True,
        )

        assert report.expired_count == 0
        assert report.skipped_count == 0
        assert grant.status == CreatorSubscriptionStatus.cancelled
        # And the paid subscription is untouched.
        assert resolve_creator_plan(creator, db).slug == "creator"
        assert len(_active_rows(db, creator)) == 1
        assert _active_rows(db, creator)[0].source == "stripe_paid"
