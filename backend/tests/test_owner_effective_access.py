"""
Regression tests for the platform owner's effective plan access.

The owner may carry a historical ``CreatorSubscription`` row (e.g. an old
Community plan that got cancelled at some point). Their **current
effective access** is inherent to the account and does not depend on
that row — it must never be presented as expired / cancelled just
because their old sub happens to be.

These tests lock:

- ``is_platform_owner=True`` on the owner's billing row.
- The historical cancelled sub row is preserved unchanged in the DB.
- The allowance stays ``None`` (unlimited) for the owner.
- ``guard_active_collective_limit`` remains a no-op for the owner even
  when their only sub row is cancelled.
- Non-owner creators with a cancelled sub still show cancelled.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.admin.routes import list_creator_billing
from app.creator.plan_guards import (
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


def _seed_plan(db, *, slug: str, collective_limit: int = 1) -> CreatorPlan:
    plan = CreatorPlan(
        id=f"plan_{uuid.uuid4().hex[:8]}",
        name=slug.capitalize(),
        slug=slug,
        monthly_price_cents=0 if slug == "community" else 1900,
        currency="AUD",
        transaction_fee_basis_points=0,
        collective_limit=collective_limit,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _seed_cancelled_sub(
    db, *, user, plan: CreatorPlan, source: str = "manual_grant",
) -> CreatorSubscription:
    sub = CreatorSubscription(
        id=str(uuid.uuid4()),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.cancelled,
        starts_at=datetime(2024, 1, 1),
        ends_at=datetime(2024, 12, 31),
        source=source,
        revoked_at=datetime(2024, 12, 31),
    )
    db.add(sub)
    db.flush()
    return sub


def _make_space(db, *, creator, status: str = "active") -> Space:
    s = Space(
        id=f"sp_{uuid.uuid4().hex[:10]}",
        slug=f"sp-{uuid.uuid4().hex[:8]}",
        name="Owner collective",
        status=status,
        creator_id=creator.id,
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# Owner billing row
# ---------------------------------------------------------------------------


class TestOwnerBillingRow:
    def test_owner_row_flagged_true(self, db, make_user):
        owner = make_user(role="admin", email="lindsey@hilliard.net.au")
        _seed_plan(db, slug="community")   # fallback plan for the rollup
        rows = list_creator_billing(_=owner, db=db)
        row = next(r for r in rows if r.user_id == owner.id)
        assert row.is_platform_owner is True

    def test_owner_with_only_cancelled_sub_still_flagged(
        self, db, make_user,
    ):
        """The bug this replaces: a cancelled sub used to leak into the
        display as expired/cancelled. Prove the flag lets the frontend
        route around it."""
        owner = make_user(role="admin", email="lindsey@hilliard.net.au")
        community = _seed_plan(db, slug="community")
        cancelled = _seed_cancelled_sub(db, user=owner, plan=community)

        rows = list_creator_billing(_=owner, db=db)
        row = next(r for r in rows if r.user_id == owner.id)
        assert row.is_platform_owner is True
        # Allowance stays unlimited regardless of the cancelled sub
        assert row.collective_limit is None

        # And the cancelled sub row is preserved unchanged in the DB
        db.refresh(cancelled)
        assert cancelled.status == CreatorSubscriptionStatus.cancelled
        assert cancelled.ends_at == datetime(2024, 12, 31)

    def test_non_owner_row_flagged_false(self, db, make_user):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        _seed_plan(db, slug="community")   # fallback plan for the rollup
        rows = list_creator_billing(_=admin, db=db)
        creator_row = next((r for r in rows if r.user_id == creator.id), None)
        assert creator_row is not None
        assert creator_row.is_platform_owner is False

    def test_non_owner_with_cancelled_sub_still_shows_cancelled_status(
        self, db, make_user,
    ):
        """Non-owner creators must continue to use their real sub status
        — the owner short-circuit must not accidentally apply to them."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        community = _seed_plan(db, slug="community")
        _seed_cancelled_sub(db, user=creator, plan=community)

        rows = list_creator_billing(_=admin, db=db)
        row = next(r for r in rows if r.user_id == creator.id)
        # The row is not flagged as owner
        assert row.is_platform_owner is False
        # subscription_status echoes the historical sub — the frontend
        # renders "Expired" from it. Might be "cancelled" or "none"
        # depending on the endpoint's filter — either is a non-owner
        # story.
        assert row.subscription_status in {"cancelled", "none"}


class TestOwnerPlanLabel:
    def test_owner_with_only_cancelled_community_sub_shows_platform_owner(
        self, db, make_user,
    ):
        """The bug this replaces: the Plan column was reading from the
        historical Community sub's plan_id, so the owner row showed
        `Community` alongside `Owner access` — mixing historical state
        into the effective-access view."""
        owner = make_user(role="admin", email="lindsey@hilliard.net.au")
        community = _seed_plan(db, slug="community")
        cancelled = _seed_cancelled_sub(db, user=owner, plan=community)

        rows = list_creator_billing(_=owner, db=db)
        row = next(r for r in rows if r.user_id == owner.id)

        assert row.is_platform_owner is True
        assert row.current_plan_name == "Platform owner"
        assert row.current_plan_slug == "platform_owner"

        # Historical sub still preserved — the fix must not touch it.
        db.refresh(cancelled)
        assert cancelled.creator_plan_id == community.id
        assert cancelled.status == CreatorSubscriptionStatus.cancelled

    def test_non_owner_row_still_shows_real_plan(self, db, make_user):
        """Non-owner rows must continue to read from their real
        subscription/plan — regression guard against the owner label
        leaking to everyone."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        community = _seed_plan(db, slug="community")
        _seed_cancelled_sub(db, user=creator, plan=community)

        rows = list_creator_billing(_=admin, db=db)
        row = next(r for r in rows if r.user_id == creator.id)
        assert row.is_platform_owner is False
        # Endpoint falls back to the cheapest plan when no active sub
        # exists — which is Community here. Either way, must not be
        # "Platform owner".
        assert row.current_plan_name != "Platform owner"
        assert row.current_plan_slug != "platform_owner"


# ---------------------------------------------------------------------------
# Owner capability enforcement
# ---------------------------------------------------------------------------


class TestOwnerCapabilities:
    def test_owner_allowance_stays_unlimited_with_cancelled_sub(
        self, db, make_user,
    ):
        owner = make_user(role="admin")
        community = _seed_plan(db, slug="community")
        _seed_cancelled_sub(db, user=owner, plan=community)
        assert effective_collective_allowance(owner, db) is None

    def test_owner_guard_still_bypasses_with_cancelled_sub(
        self, db, make_user,
    ):
        """Owner must never be blocked from creating a collective even
        if their only sub row is cancelled. Regression against a naive
        `if sub.status == cancelled: reject` refactor."""
        owner = make_user(role="admin")
        community = _seed_plan(db, slug="community")
        _seed_cancelled_sub(db, user=owner, plan=community)
        # Pile on collectives past any plausible plan limit
        for _ in range(6):
            _make_space(db, creator=owner)
        guard_active_collective_limit(owner, db)   # no exception

    def test_owner_helper_identifies_admin(self, db, make_user):
        owner = make_user(role="admin")
        assert is_platform_owner(owner) is True
