"""Expiry of finite complimentary Creator grants.

A grant of complimentary Creator access for a fixed term must actually
end. These tests pin both halves of that: the lifecycle
``Community → complimentary Creator → Community``, and the much longer
list of grants that must be left strictly alone.

They also pin what expiry must *not* touch. A creator whose grant ends
keeps their account, their Creator role, their Collective, their
content and their World Builders membership; no Stripe subscription is
created and nobody is charged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.creator.plan_guards import resolve_creator_plan
from app.models.creator_billing import (
    CreatorPlan,
    CreatorPlanGrant,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.creator_grant_expiry import (
    EXPIRABLE_GRANT_REASONS,
    NEVER_EXPIRE_PLAN_SLUGS,
    community_is_the_fallback,
    reconcile_expired_grants,
)

NOW = datetime(2026, 10, 4, 12, 0, 0)
PAST = NOW - timedelta(days=1)
FUTURE = NOW + timedelta(days=30)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def plans(db):
    """The five creator plans, priced so Community is the cheapest.

    The test database is bootstrapped from a schema dump taken past
    migration 068, so its forward INSERT of the Community row never ran
    here and ``creator_plans`` starts empty.
    """
    rows = [
        ("community", "Community", 0, 1),
        ("creator", "Creator", 1900, 3),
        ("pro", "Pro", 7900, 10),
        ("founding-creator", "Founding Creator", 0, 10),
        ("organisation", "Organisation", 0, 50),
    ]
    out = {}
    for slug, name, cents, limit in rows:
        existing = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if existing is None:
            existing = CreatorPlan(
                id=_uid("cp"), name=name, slug=slug,
                monthly_price_cents=cents, currency="AUD",
                transaction_fee_basis_points=0,
                collective_limit=limit, is_active=True,
            )
            db.add(existing)
        out[slug] = existing
    db.flush()
    return out


def _grant(db, user, plan, *, reason="comp", ends_at=PAST,
           status=CreatorSubscriptionStatus.active, source="manual_grant"):
    sub = CreatorSubscription(
        id=_uid("sub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=status,
        starts_at=NOW - timedelta(days=180),
        ends_at=ends_at,
        source=source,
        grant_reason=reason,
    )
    db.add(sub)
    db.flush()
    return sub


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------


class TestFiniteGrantLifecycle:
    def test_before_expiry_the_creator_is_still_on_creator(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=FUTURE)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert resolve_creator_plan(creator, db).slug == "creator"

    def test_at_the_end_date_the_grant_expires(self, plans, db, make_user):
        """``ends_at <= now`` — the boundary itself is due, not just past."""
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=NOW)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 1
        assert sub.status == CreatorSubscriptionStatus.cancelled

    def test_after_expiry_the_creator_falls_back_to_community(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=PAST)

        reconcile_expired_grants(db, NOW, apply=True)
        db.flush()
        resolved = resolve_creator_plan(creator, db)
        assert resolved is not None
        assert resolved.slug == "community"
        assert resolved.paid_offers_enabled is False
        assert resolved.active_collective_limit == 1

    def test_no_replacement_subscription_row_is_written(
        self, plans, db, make_user,
    ):
        """A Community row would make the creator's later paid upgrade
        raise ActivationConflictError after they had been charged."""
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=PAST)

        reconcile_expired_grants(db, NOW, apply=True)
        active = (
            db.query(CreatorSubscription)
            .filter(
                CreatorSubscription.user_id == creator.id,
                CreatorSubscription.status.in_([
                    CreatorSubscriptionStatus.active,
                    CreatorSubscriptionStatus.trialing,
                ]),
            )
            .all()
        )
        assert active == []

    def test_no_stripe_subscription_is_created_and_nothing_is_charged(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)

        reconcile_expired_grants(db, NOW, apply=True)
        assert sub.stripe_subscription_id is None
        assert sub.stripe_customer_id is None
        assert sub.current_period_end is None
        # Every row for this user, not just the one we expired.
        for row in db.query(CreatorSubscription).filter(
            CreatorSubscription.user_id == creator.id,
        ).all():
            assert row.source == "manual_grant"
            assert row.stripe_subscription_id is None


class TestExpiryPreservesEverythingElse:
    def test_account_role_collective_and_world_builders_survive(
        self, plans, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        collective = make_space(creator=creator)
        world_builders = make_space(
            creator=make_user(role="admin"), auto_grant_role="creator",
        )
        wb_membership = SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=creator.id,
            space_id=world_builders.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="auto_role",
        )
        db.add(wb_membership)
        _grant(db, creator, plans["creator"], ends_at=PAST)
        db.flush()

        reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert creator.id is not None                      # account remains
        assert creator.role == "creator"                   # capability remains
        assert collective.status != "archived"             # Collective remains
        assert wb_membership.status == SpaceMembershipStatus.active


# ---------------------------------------------------------------------------
# Exclusions — the long list of grants that must not be touched
# ---------------------------------------------------------------------------


class TestExclusions:
    def test_an_indefinite_grant_never_expires(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=None)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active

    def test_founding_creator_never_expires(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["founding-creator"], ends_at=PAST)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active

    def test_organisation_never_expires(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["organisation"], ends_at=PAST)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active

    def test_a_stripe_paid_subscription_never_expires_through_this_path(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(
            db, creator, plans["creator"], ends_at=PAST,
            source="stripe_paid", reason=None,
        )
        sub.stripe_subscription_id = "sub_live_x"
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active

    def test_a_stripe_paid_row_is_excluded_even_if_it_carries_a_comp_reason(
        self, plans, db, make_user,
    ):
        """Makes the ``source`` filter load-bearing.

        A real ``stripe_paid`` row leaves ``grant_reason`` NULL, so the
        reason filter already excludes it — which means the source
        filter is only exercised by an anomalous row that has both. It
        is exactly that anomaly the filter exists for: a paid
        subscription must never be cancelled by the grant reconciler,
        whatever its other columns say.
        """
        creator = make_user(role="creator")
        sub = _grant(
            db, creator, plans["creator"], ends_at=PAST,
            source="stripe_paid", reason="comp",
        )
        sub.stripe_subscription_id = "sub_live_anomaly"
        sub.stripe_customer_id = "cus_live_anomaly"
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active
        assert sub.revoked_at is None

    @pytest.mark.parametrize(
        "reason",
        ["beta", "migration", "correction", "replacement", "internal", "other"],
    )
    def test_non_complimentary_reasons_are_left_alone(
        self, plans, db, make_user, reason,
    ):
        """Only 'comp' and 'temporary' mean time-boxed free access.

        The rest are remediation, programmes or staff tooling, where an
        end date is more likely a note than an instruction.
        """
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], reason=reason, ends_at=PAST)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active

    @pytest.mark.parametrize("reason", sorted(EXPIRABLE_GRANT_REASONS))
    def test_both_complimentary_reasons_do_expire(
        self, plans, db, make_user, reason,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], reason=reason, ends_at=PAST)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 1
        assert sub.status == CreatorSubscriptionStatus.cancelled

    def test_an_already_cancelled_grant_is_not_reprocessed(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(
            db, creator, plans["creator"], ends_at=PAST,
            status=CreatorSubscriptionStatus.cancelled,
        )

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.revoked_at is None

    def test_the_exclusion_sets_are_what_we_think_they_are(self):
        assert EXPIRABLE_GRANT_REASONS == {"comp", "temporary"}
        assert "founding-creator" in NEVER_EXPIRE_PLAN_SLUGS
        assert "organisation" in NEVER_EXPIRE_PLAN_SLUGS
        assert "community" in NEVER_EXPIRE_PLAN_SLUGS
        assert "creator" not in NEVER_EXPIRE_PLAN_SLUGS
        assert "pro" not in NEVER_EXPIRE_PLAN_SLUGS


# ---------------------------------------------------------------------------
# Failing safe
# ---------------------------------------------------------------------------


class TestFailsSafe:
    def test_too_many_collectives_leaves_the_grant_alone(
        self, plans, db, make_user, make_space,
    ):
        """Mirrors change_creator_plan_atomic: "never picks which
        Collectives to close"."""
        creator = make_user(role="creator")
        make_space(creator=creator)
        make_space(creator=creator)     # 2 > Community's limit of 1
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert report.skipped_count == 1
        assert "collectives_exceed_community_limit" in report.skipped[0].reason
        assert sub.status == CreatorSubscriptionStatus.active

    def test_archived_collectives_do_not_block_expiry(
        self, plans, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        make_space(creator=creator)
        make_space(creator=creator, status="archived")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 1
        assert sub.status == CreatorSubscriptionStatus.cancelled

    def test_a_creator_selling_tickets_is_left_alone(
        self, plans, db, make_user, make_space, make_event,
    ):
        """Community forbids paid offers and there is no read-side plan
        gate, so expiring would either strand live checkouts or leave
        paid offers purchasable on a plan that bans them."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space)
        event.ticket_price_cents = 2500
        event.ticket_currency = "AUD"
        event.status = "published"
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert report.skipped_count == 1
        assert report.skipped[0].reason == "creator_has_paid_content"
        assert sub.status == CreatorSubscriptionStatus.active

    def test_the_run_halts_if_community_is_not_the_cheapest_plan(
        self, plans, db, make_user,
    ):
        """Without Community as the fallback, cancelling a grant could
        resolve the creator somewhere *more* capable."""
        plans["community"].is_active = False
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)
        db.flush()

        assert community_is_the_fallback(db) is False
        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.halted_reason == "community_is_not_the_cheapest_active_plan"
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active


# ---------------------------------------------------------------------------
# Dry run, idempotency, audit
# ---------------------------------------------------------------------------


class TestDryRunAndIdempotency:
    def test_dry_run_reports_without_writing(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)

        report = reconcile_expired_grants(db, NOW, apply=False)
        assert report.applied is False
        assert report.expired_count == 1
        assert sub.status == CreatorSubscriptionStatus.active
        assert sub.revoked_at is None
        assert resolve_creator_plan(creator, db).slug == "creator"

    def test_repeated_runs_are_idempotent(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)

        first = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()
        revoked_at = sub.revoked_at
        second = reconcile_expired_grants(db, NOW, apply=True)
        third = reconcile_expired_grants(db, NOW, apply=True)

        assert first.expired_count == 1
        assert second.expired_count == 0
        assert third.expired_count == 0
        assert sub.revoked_at == revoked_at
        grants = (
            db.query(CreatorPlanGrant)
            .filter(CreatorPlanGrant.subscription_id == sub.id)
            .all()
        )
        assert len(grants) == 1, "one audit row per actual transition"

    def test_safe_when_the_creator_is_already_on_community(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        # No subscription row at all — already a Community creator.
        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert resolve_creator_plan(creator, db).slug == "community"

    def test_an_admin_plan_change_before_the_run_wins(
        self, plans, db, make_user,
    ):
        """If an admin moved the creator to Pro, the old grant row is no
        longer active and the reconciler must not disturb the new one."""
        creator = make_user(role="creator")
        old = _grant(
            db, creator, plans["creator"], ends_at=PAST,
            status=CreatorSubscriptionStatus.cancelled,
        )
        new = _grant(db, creator, plans["pro"], ends_at=None)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert new.status == CreatorSubscriptionStatus.active
        assert old.status == CreatorSubscriptionStatus.cancelled
        assert resolve_creator_plan(creator, db).slug == "pro"

    def test_an_admin_extension_before_the_run_wins(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=FUTURE)

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active


class TestAuditTrail:
    def test_a_system_expiry_is_distinguishable_from_an_admin_revoke(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)

        reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        # Every admin path sets the acting admin; the system leaves it NULL.
        assert sub.revoked_by_user_id is None
        assert sub.revoked_at == NOW
        assert "end date" in (sub.revoked_reason or "")

        event = (
            db.query(CreatorPlanGrant)
            .filter(CreatorPlanGrant.subscription_id == sub.id)
            .one()
        )
        assert event.action == "revoked"
        assert event.actor_user_id is None
        assert event.reason == "complimentary_grant_expired"
        assert "Community" in (event.note or "")

    def test_the_audit_row_preserves_the_original_term(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST)
        original_ends_at = sub.ends_at

        reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        event = (
            db.query(CreatorPlanGrant)
            .filter(CreatorPlanGrant.subscription_id == sub.id)
            .one()
        )
        assert event.ends_at == original_ends_at
        assert event.creator_plan_id == plans["creator"].id
