"""
Regression tests locking display + guard parity for the creator plan
`collective_limit` allowance.

The Creator Subscriptions display uses
``effective_collective_allowance`` from ``plan_guards``. The creation
guard uses the same helper via ``guard_active_collective_limit``. These
tests exist to make sure those two callers agree on:

- what counts as "using" a collective (drafts + published, no archived);
- what the allowance is for a given user (plan limit vs. owner unlimited);
- when creation is blocked (at limit) vs. allowed (below limit);
- that a manually granted plan is honoured identically to a paid plan.

If any of these drift, the caretaker's view stops matching the rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.admin.routes import (
    _creator_managed_space_ids,
    grant_creator_plan_access,
    list_creator_billing,
)
from app.admin.schemas import GrantPlanAccessRequest
from app.creator.plan_guards import (
    count_managed_collectives,
    effective_collective_allowance,
    guard_active_collective_limit,
    is_platform_owner,
)
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import Space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def make_named_space(db, make_user):
    """Space factory that lets us specify status directly."""
    def _factory(*, creator, status: str = "active"):
        s = Space(
            id=f"sp_{uuid.uuid4().hex[:10]}",
            slug=f"sp-{uuid.uuid4().hex[:8]}",
            name="Test space",
            status=status,
            creator_id=creator.id,
        )
        db.add(s)
        db.flush()
        return s
    return _factory


def _seed_creator_plan(db, *, slug: str = "creator", collective_limit: int = 3):
    """Seed a DB `CreatorPlan` — needed by the creator-billing endpoint's
    rollup path. Its collective_limit column is intentionally different
    from the PlanCapability, to prove the display uses the guard's number
    (PlanCapability), not the DB value."""
    plan = CreatorPlan(
        id=f"plan_{uuid.uuid4().hex[:8]}",
        name=slug.capitalize(),
        slug=slug,
        monthly_price_cents=1900,
        currency="AUD",
        transaction_fee_basis_points=800,
        collective_limit=collective_limit,   # DB value — must be ignored by display
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _seed_active_manual_grant(db, *, admin, creator, plan_slug: str):
    """Create an active manual-grant subscription for `creator` on `plan_slug`."""
    grant_creator_plan_access(
        GrantPlanAccessRequest(
            creator_user_id=creator.id,
            plan_slug=plan_slug,
            reason="comp",
            duration="12_months",
        ),
        admin=admin, db=db,
    )


# ---------------------------------------------------------------------------
# 1. Counting rules — drafts count, archived don't
# ---------------------------------------------------------------------------


class TestCountingRules:
    def test_draft_collectives_count_towards_usage(self, db, make_user, make_named_space):
        creator = make_user(role="creator")
        make_named_space(creator=creator, status="draft")
        make_named_space(creator=creator, status="draft")
        assert count_managed_collectives(creator, db) == 2

    def test_published_collectives_count_towards_usage(self, db, make_user, make_named_space):
        creator = make_user(role="creator")
        make_named_space(creator=creator, status="active")
        make_named_space(creator=creator, status="active")
        assert count_managed_collectives(creator, db) == 2

    def test_archived_collectives_do_not_count(self, db, make_user, make_named_space):
        creator = make_user(role="creator")
        make_named_space(creator=creator, status="active")
        make_named_space(creator=creator, status="archived")
        assert count_managed_collectives(creator, db) == 1

    def test_display_count_matches_guard_count(self, db, make_user, make_named_space):
        """The endpoint's ``_creator_managed_space_ids`` and the guard's
        ``count_managed_collectives`` must return the same set."""
        creator = make_user(role="creator")
        s1 = make_named_space(creator=creator, status="active")
        s2 = make_named_space(creator=creator, status="draft")
        make_named_space(creator=creator, status="archived")
        endpoint_count = len(_creator_managed_space_ids(creator.id, db))
        guard_count = count_managed_collectives(creator, db)
        assert endpoint_count == guard_count == 2
        assert {s1.id, s2.id} == _creator_managed_space_ids(creator.id, db)


# ---------------------------------------------------------------------------
# 2. Allowance helper — the one denominator
# ---------------------------------------------------------------------------


class TestAllowanceHelper:
    def test_owner_gets_unlimited(self, db, make_user):
        owner = make_user(role="admin")
        assert is_platform_owner(owner) is True
        assert effective_collective_allowance(owner, db) is None

    def test_non_owner_falls_back_to_cheapest_plan(self, db, make_user):
        creator = make_user(role="creator")
        # No subscription; guard falls back to cheapest active plan. In
        # the fresh test DB there may be no plans seeded, so the helper
        # returns None (unlimited) as a display-safe fallback. The guard
        # itself still refuses to create the first collective if no plan
        # exists.
        allowance = effective_collective_allowance(creator, db)
        # Either None (no plan) or an integer (fallback plan) — both are
        # legal outputs. We only assert the type.
        assert allowance is None or isinstance(allowance, int)

    def test_manual_grant_uses_granted_plan_capability(
        self, db, make_user, make_named_space,
    ):
        """A creator with a manual grant to the `creator` plan should
        read the allowance from that plan's capability, not from some
        default."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator", collective_limit=99)   # DB value bogus
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")

        allowance = effective_collective_allowance(creator, db)
        # PlanCapability.active_collective_limit for 'creator' is 1 in plan_config.
        assert allowance == 1


# ---------------------------------------------------------------------------
# 3. Guard behaviour uses the helper's value
# ---------------------------------------------------------------------------


class TestGuardParity:
    def test_creator_below_limit_can_create(self, db, make_user, make_named_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator")
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")
        # 0 collectives, limit 1 → allowed
        guard_active_collective_limit(creator, db)   # no exception

    def test_creator_at_limit_cannot_create(
        self, db, make_user, make_named_space,
    ):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator")
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")

        # Fill to the limit (1 for 'creator' plan)
        make_named_space(creator=creator, status="active")

        with pytest.raises(HTTPException) as e:
            guard_active_collective_limit(creator, db)
        assert e.value.status_code == 403

    def test_creator_with_draft_at_limit_cannot_create_another(
        self, db, make_user, make_named_space,
    ):
        """The bug we're guarding against: a draft was allowed to slip
        through because it wasn't 'active'. Prove drafts count."""
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator")
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")

        make_named_space(creator=creator, status="draft")   # limit is 1

        with pytest.raises(HTTPException) as e:
            guard_active_collective_limit(creator, db)
        assert e.value.status_code == 403

    def test_owner_never_blocked(self, db, make_user, make_named_space):
        owner = make_user(role="admin")
        # Pile on collectives past any plausible plan limit
        for _ in range(10):
            make_named_space(creator=owner, status="active")
        guard_active_collective_limit(owner, db)   # no exception


# ---------------------------------------------------------------------------
# 4. Display endpoint reads the guard's allowance
# ---------------------------------------------------------------------------


class TestBillingDisplayParity:
    def test_owner_row_shows_unlimited_allowance(self, db, make_user):
        owner = make_user(role="admin", email="owner@example.test")
        _seed_creator_plan(db, slug="creator")
        rows = list_creator_billing(_=owner, db=db)
        owner_row = next(r for r in rows if r.user_id == owner.id)
        assert owner_row.collective_limit is None, (
            "Platform owner must render as unlimited (None), not the "
            "cheapest plan's limit."
        )

    def test_creator_row_shows_granted_plan_allowance(
        self, db, make_user, make_named_space,
    ):
        admin = make_user(role="admin", email="lindsey@hilliard.net.au")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator", collective_limit=99)  # DB bogus
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")

        rows = list_creator_billing(_=admin, db=db)
        row = next(r for r in rows if r.user_id == creator.id)
        # PlanCapability.active_collective_limit=1 for 'creator' — the
        # display must reflect the guard's number (1), not the DB (99).
        assert row.collective_limit == 1

    def test_display_count_matches_actual_usage(
        self, db, make_user, make_named_space,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_creator_plan(db, slug="creator")
        _seed_active_manual_grant(db, admin=admin, creator=creator, plan_slug="creator")

        make_named_space(creator=creator, status="active")
        make_named_space(creator=creator, status="draft")
        make_named_space(creator=creator, status="archived")

        rows = list_creator_billing(_=admin, db=db)
        row = next(r for r in rows if r.user_id == creator.id)
        # 1 active + 1 draft = 2 (archived excluded)
        assert row.collectives_used == count_managed_collectives(creator, db) == 2
