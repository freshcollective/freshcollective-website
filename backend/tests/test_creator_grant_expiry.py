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
    GRACE_PERIOD,
    NEVER_EXPIRE_PLAN_SLUGS,
    RENEWAL_WINDOW,
    SYSTEM_REVOKED_REASON,
    classify_grant,
    community_is_the_fallback,
    reconcile_expired_grants,
)

NOW = datetime(2026, 10, 4, 12, 0, 0)
#: Term ended yesterday — inside the 7-day grace window, so Creator
#: access continues and nothing is due yet.
IN_GRACE = NOW - timedelta(days=1)
#: Term ended 8 days ago — grace has run out, so fallback is due.
PAST_GRACE = NOW - timedelta(days=8)
#: Still inside the term, before the 14-day renewal window opens.
FUTURE = NOW + timedelta(days=30)
#: Inside the final 14 days — the renewal window.
IN_RENEWAL = NOW + timedelta(days=7)

# Historical alias: every pre-grace test meant "due for fallback".
PAST = PAST_GRACE


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

    def test_at_the_end_of_grace_the_grant_expires(self, plans, db, make_user):
        """The boundary is ``ends_at + GRACE_PERIOD``, not ``ends_at``.

        A creator must never drop to Community on their end date — they
        get the grace window to decide first.
        """
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=NOW - GRACE_PERIOD)

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
        assert event.reason == SYSTEM_REVOKED_REASON
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


# ---------------------------------------------------------------------------
# Lifecycle classification — renewal window, grace, fallback
# ---------------------------------------------------------------------------


def _classify(db, sub, plan_slug, now=NOW):
    from app.services.creator_grant_expiry import has_active_paid_subscription
    return classify_grant(
        sub, plan_slug, now,
        has_paid_subscription=has_active_paid_subscription(db, sub.user_id),
    )


class TestLifecycleClassification:
    def test_the_windows_are_the_agreed_durations(self):
        assert RENEWAL_WINDOW == timedelta(days=14)
        assert GRACE_PERIOD == timedelta(days=7)

    def test_well_inside_the_term_is_plain_active(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=FUTURE)
        assert _classify(db, sub, "creator") == "active"

    def test_the_renewal_window_opens_fourteen_days_out(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        # One second inside the boundary.
        sub = _grant(
            db, creator, plans["creator"],
            ends_at=NOW + RENEWAL_WINDOW - timedelta(seconds=1),
        )
        assert _classify(db, sub, "creator") == "renewal window"

    def test_one_second_before_the_window_is_active(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(
            db, creator, plans["creator"],
            ends_at=NOW + RENEWAL_WINDOW + timedelta(seconds=1),
        )
        assert _classify(db, sub, "creator") == "active"

    def test_past_the_end_date_is_grace_not_fallback(
        self, plans, db, make_user,
    ):
        """The product rule: never straight to Community at ends_at."""
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=IN_GRACE)
        assert _classify(db, sub, "creator") == "grace"

    def test_after_grace_it_would_fall_back(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        assert _classify(db, sub, "creator") == "would fall back"

    def test_an_elected_creator_is_excluded_even_past_grace(
        self, plans, db, make_user,
    ):
        """A paid row — including a not-yet-charged early election —
        takes the creator out of this lifecycle entirely."""
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=creator.id,
            creator_plan_id=plans["creator"].id,
            status=CreatorSubscriptionStatus.past_due,   # trial running
            starts_at=NOW, source="stripe_paid",
            stripe_subscription_id="sub_trial_1",
        ))
        db.flush()
        assert _classify(db, sub, "creator") == (
            "excluded: paid subscription already active"
        )

    @pytest.mark.parametrize("slug", ["founding-creator", "organisation"])
    def test_protected_plans_are_excluded_by_slug(
        self, plans, db, make_user, slug,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans[slug], ends_at=PAST_GRACE)
        assert _classify(db, sub, slug) == f"excluded: plan={slug}"

    def test_an_indefinite_grant_is_excluded(self, plans, db, make_user):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=None)
        assert _classify(db, sub, "creator") == "excluded: indefinite"


class TestGraceProtectsAccess:
    def test_a_creator_in_grace_keeps_creator_capability(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_GRACE)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0, "grace must not fall back"
        resolved = resolve_creator_plan(creator, db)
        assert resolved.slug == "creator"
        assert resolved.paid_offers_enabled is True

    def test_a_creator_in_the_renewal_window_is_untouched(
        self, plans, db, make_user,
    ):
        creator = make_user(role="creator")
        sub = _grant(db, creator, plans["creator"], ends_at=IN_RENEWAL)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert sub.status == CreatorSubscriptionStatus.active


class TestPaidElectionIsNeverExpired:
    def test_an_early_election_survives_past_grace(
        self, plans, db, make_user,
    ):
        """The window this protects: the creator committed and Stripe is
        running a trial to their end date, so the paid row is
        ``past_due`` and the grant is deliberately still active. Without
        the exclusion the job would revoke the access they just paid
        for."""
        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=creator.id,
            creator_plan_id=plans["creator"].id,
            status=CreatorSubscriptionStatus.past_due,
            starts_at=NOW, source="stripe_paid",
            stripe_subscription_id="sub_trial_2",
        ))
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert report.skipped_count == 1
        assert report.skipped[0].reason == "paid_subscription_active"
        assert grant.status == CreatorSubscriptionStatus.active

    def test_a_fully_converted_creator_is_out_of_the_lifecycle(
        self, plans, db, make_user,
    ):
        """After the first paid invoice, ``plan_activation``'s supersede
        has already cancelled the grant — the index would not permit two
        active rows anyway, which is what the conversion fix exists to
        respect. So the grant is excluded by status, before the
        paid-subscription check is even reached.
        """
        creator = make_user(role="creator")
        grant = _grant(
            db, creator, plans["creator"], ends_at=PAST_GRACE,
            status=CreatorSubscriptionStatus.cancelled,
        )
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=creator.id,
            creator_plan_id=plans["creator"].id,
            status=CreatorSubscriptionStatus.active,
            starts_at=NOW, source="stripe_paid",
            stripe_subscription_id="sub_live_9",
        ))
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 0
        assert report.skipped_count == 0
        assert grant.status == CreatorSubscriptionStatus.cancelled
        assert resolve_creator_plan(creator, db).slug == "creator"


# ---------------------------------------------------------------------------
# Commercial safety after fallback
# ---------------------------------------------------------------------------


class TestCommercialSafetyAfterFallback:
    """Production runs with ``CREATOR_PLAN_GUARD_ENABLED=true``
    (confirmed 2026-10-04), so a creator with no active subscription is
    refused at checkout rather than silently falling back to a 0% fee.
    These tests pin that, because it is the whole basis on which paid
    content is allowed to remain stored after a downgrade: dormant, not
    destroyed.
    """

    @pytest.fixture
    def guard_on(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "creator_plan_guard_enabled", True)

    def _fall_back(self, db, creator, plans):
        _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        db.flush()
        report = reconcile_expired_grants(db, NOW, apply=True)
        assert report.expired_count == 1
        db.flush()

    def test_the_canonical_plan_is_community(self, plans, db, make_user):
        creator = make_user(role="creator")
        self._fall_back(db, creator, plans)
        assert resolve_creator_plan(creator, db).slug == "community"

    def test_existing_paid_offers_can_no_longer_be_checked_out(
        self, plans, db, make_user, guard_on,
    ):
        """The proof that stored paid content is inert rather than
        sellable."""
        from app.services.checkout_orchestration import (
            NoActiveCreatorPlanError,
            _resolve_fee_bps_for_creator,
        )

        creator = make_user(role="creator")
        self._fall_back(db, creator, plans)

        with pytest.raises(NoActiveCreatorPlanError):
            _resolve_fee_bps_for_creator(creator.id, db)

    def test_a_creator_in_grace_can_still_transact(
        self, plans, db, make_user, guard_on,
    ):
        """Grace means Creator access really continues — including
        commerce — so the deadline is the only thing that changes."""
        from app.services.checkout_orchestration import (
            _resolve_fee_bps_for_creator,
        )

        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_GRACE)
        db.flush()
        reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        fee_bps, plan_id, _ = _resolve_fee_bps_for_creator(creator.id, db)
        assert plan_id == plans["creator"].id

    def test_no_new_paid_offers_can_be_created(self, plans, db, make_user):
        from fastapi import HTTPException

        from app.creator.plan_guards import guard_paid_offers_enabled

        creator = make_user(role="creator")
        self._fall_back(db, creator, plans)

        with pytest.raises(HTTPException) as exc:
            guard_paid_offers_enabled(creator, db, "paid_monthly")
        assert exc.value.status_code == 403

    def test_free_offers_still_work(self, plans, db, make_user):
        from app.creator.plan_guards import guard_paid_offers_enabled

        creator = make_user(role="creator")
        self._fall_back(db, creator, plans)
        guard_paid_offers_enabled(creator, db, "free")   # does not raise

    def test_stored_commercial_content_is_not_deleted(
        self, plans, db, make_user, make_space, make_event,
    ):
        """Downgrade must leave the work intact so a later upgrade
        reactivates rather than recreates."""
        from app.models.platform import Pathway

        creator = make_user(role="creator")
        space = make_space(creator=creator, pricing_type="paid_monthly")
        pathway = Pathway(
            id=str(uuid.uuid4()), space_id=space.id,
            slug="p-paid", title="A paid pathway",
        )
        db.add(pathway)
        event = make_event(space=space)
        event.ticket_price_cents = 2500
        event.status = "published"
        db.flush()

        # The reconciler refuses to expire a creator who is selling, so
        # reach the fallback state the way an admin would: the grant is
        # gone and no paid subscription exists.
        grant = _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        grant.status = CreatorSubscriptionStatus.cancelled
        db.flush()

        assert resolve_creator_plan(creator, db).slug == "community"
        # Every artefact is still there.
        db.refresh(space)
        db.refresh(pathway)
        db.refresh(event)
        assert space.pricing_type == "paid_monthly"
        assert pathway.title == "A paid pathway"
        assert event.ticket_price_cents == 2500


# ---------------------------------------------------------------------------
# Lifecycle notifications
# ---------------------------------------------------------------------------


class TestLifecycleNotifications:
    """In-app notifications for the three states the creator should hear
    about. Conversion to paid is already announced by
    ``plan_activation._notify_creator``, so it is not duplicated.

    Dedup is derived from the grant's own dates, so a daily schedule
    sends each message once per term rather than once per run.
    """

    @staticmethod
    def _notifications(db, user, kind=None):
        from app.models.notification import Notification
        q = db.query(Notification).filter(Notification.user_id == user.id)
        if kind:
            q = q.filter(Notification.notification_type == kind)
        return q.all()

    def test_the_renewal_window_notifies_once(self, plans, db, make_user):
        from app.services.creator_grant_expiry import NOTIFY_ENDING_SOON

        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_RENEWAL)
        db.flush()

        first = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()
        second = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert first.in_renewal == 1
        assert first.notified == 1
        assert second.notified == 0, "a daily run must not re-notify"
        sent = self._notifications(db, creator, NOTIFY_ENDING_SOON)
        assert len(sent) == 1
        assert "4" in sent[0].message or "ends on" in sent[0].message
        assert "grace" in sent[0].message
        assert "remain" in sent[0].message

    def test_grace_notifies_with_the_deadline(self, plans, db, make_user):
        from app.services.creator_grant_expiry import NOTIFY_GRACE

        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_GRACE)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert report.in_grace == 1
        sent = self._notifications(db, creator, NOTIFY_GRACE)
        assert len(sent) == 1
        assert "until" in sent[0].message
        assert "Community" in sent[0].message

    def test_fallback_notifies_that_content_is_intact(
        self, plans, db, make_user,
    ):
        from app.services.creator_grant_expiry import NOTIFY_ENDED

        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert report.expired_count == 1
        sent = self._notifications(db, creator, NOTIFY_ENDED)
        assert len(sent) == 1
        assert "still here" in sent[0].message
        assert "Community" in sent[0].message

    def test_no_notification_claims_an_automatic_charge(
        self, plans, db, make_user,
    ):
        for ends_at in (IN_RENEWAL, IN_GRACE, PAST_GRACE):
            creator = make_user(role="creator")
            _grant(db, creator, plans["creator"], ends_at=ends_at)
            db.flush()
            reconcile_expired_grants(db, NOW, apply=True)
            db.flush()
            for n in self._notifications(db, creator):
                assert "charged automatically" not in n.message.lower()
                assert "will be charged" not in n.message.lower()

    def test_a_dry_run_counts_but_sends_nothing(self, plans, db, make_user):
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_RENEWAL)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=False)
        db.flush()

        assert report.in_renewal == 1
        assert report.notified == 0
        assert self._notifications(db, creator) == []

    def test_an_elected_creator_is_not_nagged(self, plans, db, make_user):
        """A creator who already committed should not be asked again."""
        creator = make_user(role="creator")
        _grant(db, creator, plans["creator"], ends_at=IN_RENEWAL)
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=creator.id,
            creator_plan_id=plans["creator"].id,
            status=CreatorSubscriptionStatus.past_due,
            starts_at=NOW, source="stripe_paid",
            stripe_subscription_id="sub_trial_3",
        ))
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert report.in_renewal == 0
        assert report.notified == 0
        assert self._notifications(db, creator) == []

    @pytest.mark.parametrize("slug", ["founding-creator", "organisation"])
    def test_protected_plans_are_never_notified(
        self, plans, db, make_user, slug,
    ):
        creator = make_user(role="creator")
        _grant(db, creator, plans[slug], ends_at=IN_RENEWAL)
        db.flush()

        report = reconcile_expired_grants(db, NOW, apply=True)
        db.flush()

        assert report.in_renewal == 0
        assert report.notified == 0
        assert self._notifications(db, creator) == []


class TestSurveyReport:
    def test_the_survey_classifies_every_manual_grant(
        self, plans, db, make_user,
    ):
        from app.services.creator_grant_expiry import survey_manual_grants

        comp = make_user(role="creator")
        _grant(db, comp, plans["creator"], ends_at=IN_RENEWAL)
        founding = make_user(role="creator")
        _grant(db, founding, plans["founding-creator"], ends_at=None,
               reason="internal")
        db.flush()

        rows = {r.user_id: r for r in survey_manual_grants(db, NOW)}
        assert rows[comp.id].lifecycle == "renewal window"
        assert rows[comp.id].user_email is not None
        assert rows[founding.id].lifecycle.startswith("excluded")

    def test_the_survey_mutates_nothing(self, plans, db, make_user):
        from app.services.creator_grant_expiry import survey_manual_grants

        creator = make_user(role="creator")
        grant = _grant(db, creator, plans["creator"], ends_at=PAST_GRACE)
        db.flush()

        survey_manual_grants(db, NOW)
        db.flush()
        assert grant.status == CreatorSubscriptionStatus.active
        assert grant.revoked_at is None
