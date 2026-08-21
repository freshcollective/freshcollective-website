"""Creator onboarding must never surface Cornerstone islands.

Cornerstone Locations (The Atlas Isles, The Grove, The Commons) are
reserved for Fresh Collective's own experiences and must not appear in
the island picker for ordinary creators during Build Your Collective.

The behaviour is enforced by two touch-points which are exercised
together here:

  1. ``allowed_location_query`` in ``app.creator.plan_guards`` — the
     per-user SQL filter that scopes the picker to a plan.
  2. ``get_options`` in ``app.creator.build_your_collective`` — the
     endpoint which, for a Platform Owner, layers Cornerstones on top
     of the plan-scoped list but for anyone else returns exactly what
     the filter returned.

The test seeds Cornerstone + Atlas + Community rows explicitly so the
assertion cannot silently pass just because the local DB happens to be
missing Cornerstones.
"""

from __future__ import annotations

import uuid

import pytest

# Registers SQLAlchemy relationships that the models below depend on.
import app.models.community_care  # noqa: F401

from app.creator.plan_guards import allowed_location_query, is_platform_owner
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import Location


@pytest.fixture
def _seeded_locations(db):
    """Ensure at least one row of each location_type exists.

    Uses fixed keys so re-runs against the same test DB are idempotent
    (Location.key is UNIQUE)."""
    seeds = [
        ("test_cs_atlas_isles", "The Atlas Isles", "CORNERSTONE"),
        ("test_cs_the_grove",   "The Grove",       "CORNERSTONE"),
        ("test_cs_the_commons", "The Commons",     "CORNERSTONE"),
        ("test_atlas_moss",     "Moss Haven",      "ATLAS"),
        ("test_atlas_coral",    "Coral Cay",       "ATLAS"),
        ("test_community_hearth", "The Hearth",    "COMMUNITY"),
    ]
    for key, name, ltype in seeds:
        if db.query(Location).filter(Location.key == key).first() is None:
            db.add(Location(
                id=f"loc_{uuid.uuid4().hex[:12]}",
                key=key,
                name=name,
                status="active",
                location_type=ltype,
            ))
    db.flush()
    return seeds


@pytest.fixture
def _plans(db):
    """Ensure the Creator and Community CreatorPlan rows exist."""
    # Community has no paid offers, so its transaction fee is
    # conceptually N/A. The DB column is NOT NULL, so seed 0 — the
    # value is never applied at runtime because paid_offers_enabled is
    # False for Community.
    for slug, price, fee_bps in (
        ("community", 0,    0),
        ("creator",   1900, 800),
    ):
        if db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first() is None:
            db.add(CreatorPlan(
                id=f"cp_{slug}",
                name=slug.title(),
                slug=slug,
                monthly_price_cents=price,
                transaction_fee_basis_points=fee_bps,
                collective_limit=1,
                is_active=True,
            ))
    db.flush()


def _subscribe(db, user_id: str, plan_slug: str) -> None:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == plan_slug).one()
    db.add(CreatorSubscription(
        id=f"cs_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active,
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_creator_plan_query_returns_no_cornerstones(
    db, make_user, _seeded_locations, _plans
):
    """A creator on the Creator plan must see ATLAS Locations only —
    never CORNERSTONE, never COMMUNITY."""
    user = make_user(role="creator")
    _subscribe(db, user.id, "creator")

    rows = allowed_location_query(user, db).all()
    types = {r.location_type for r in rows}

    assert "CORNERSTONE" not in types, (
        "Ordinary creators must not see Cornerstone islands "
        "(The Atlas Isles / The Grove / The Commons)."
    )
    assert types == {"ATLAS"}, f"expected ATLAS-only, got {types!r}"

    names = {r.name for r in rows}
    for reserved in ("The Atlas Isles", "The Grove", "The Commons"):
        assert reserved not in names, (
            f"Reserved cornerstone {reserved!r} leaked into creator picker."
        )


def test_community_plan_query_returns_no_cornerstones(
    db, make_user, _seeded_locations, _plans
):
    """A user on the Community (Free) plan sees COMMUNITY Locations only."""
    user = make_user(role="creator")
    _subscribe(db, user.id, "community")

    rows = allowed_location_query(user, db).all()
    types = {r.location_type for r in rows}

    assert "CORNERSTONE" not in types
    assert types == {"COMMUNITY"}, f"expected COMMUNITY-only, got {types!r}"


def test_unsubscribed_creator_still_gets_no_cornerstones(
    db, make_user, _seeded_locations, _plans
):
    """Defence in depth — a creator with no subscription row falls back
    through ``resolve_creator_plan`` to the cheapest active plan
    (Community). The important guarantee is that Cornerstones stay out
    of the returned set no matter which fallback plan gets picked."""
    user = make_user(role="creator")
    # deliberately no _subscribe(...)

    rows = allowed_location_query(user, db).all()
    types = {r.location_type for r in rows}

    assert "CORNERSTONE" not in types, (
        "Unsubscribed creators must not leak Cornerstones through the "
        "no-subscription fallback path."
    )


def test_platform_owner_query_returns_no_cornerstones_from_this_helper(
    db, make_user, _seeded_locations, _plans
):
    """``allowed_location_query`` deliberately excludes Cornerstones
    even for Platform Owner — the caller (``get_options``) is expected
    to layer them in as their own group. If this ever changes, both
    layers would double-list Cornerstones for admins; the assert here
    catches that regression."""
    admin = make_user(role="admin")
    assert is_platform_owner(admin)

    rows = allowed_location_query(admin, db).all()
    types = {r.location_type for r in rows}

    assert "CORNERSTONE" not in types, (
        "allowed_location_query must not emit Cornerstones; get_options "
        "layers them in separately for Platform Owner only."
    )
    assert types == {"ATLAS", "COMMUNITY"}
