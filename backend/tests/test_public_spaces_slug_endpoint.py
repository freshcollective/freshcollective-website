"""GET /api/public/spaces/{slug} — Stage 1 public single-Collective endpoint.

Contract:
  * Unauthenticated.
  * Returns the same shape as an entry in ``GET /api/public/spaces``
    (PublicSpaceCard). No private fields are exposed.
  * Applies the *identical* visibility filter as the list route so a
    Collective that would not appear in the list is 404 here.
  * Unknown slugs → 404. Private / draft / auto-grant Spaces → 404.

Handlers are invoked directly (matching the pattern used by
``test_world_builders_access.py``) so the tests share the same
SAVEPOINT-wrapped session the fixtures write into. TestClient would
open a fresh session and miss the un-committed rows.

The list route is exercised implicitly to confirm it still works
after the shared-helper refactor.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.spaces.routes import get_public_space, list_public_spaces


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def public_space(db, make_space):
    """A publicly-visible active Collective addressable via the endpoint."""
    space = make_space(
        slug=f"public-{uuid.uuid4().hex[:8]}",
        name="Public Collective",
        status="active",
        is_public=True,
        auto_grant_role=None,
    )
    db.flush()
    return space


@pytest.fixture
def private_space(db, make_space):
    space = make_space(
        slug=f"private-{uuid.uuid4().hex[:8]}",
        status="active",
        is_public=False,
        auto_grant_role=None,
    )
    db.flush()
    return space


@pytest.fixture
def draft_space(db, make_space):
    space = make_space(
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        status="draft",
        is_public=True,
        auto_grant_role=None,
    )
    db.flush()
    return space


@pytest.fixture
def auto_grant_space(db, make_space):
    """World-Builders-style auto-grant Space — operational, not for
    public discovery or self-serve join."""
    space = make_space(
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        status="active",
        is_public=True,
        auto_grant_role="creator",
    )
    db.flush()
    return space


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_public_space_returns_expected_data(db, public_space) -> None:
    card = get_public_space(public_space.slug, db=db)
    assert card.slug == public_space.slug
    assert card.name == public_space.name


def test_public_space_response_shape_matches_list_entry(db, public_space) -> None:
    """The single-slug endpoint must return the same shape the list
    endpoint returns for the same Collective — the frontend renders
    the same component for both surfaces."""
    listing = list_public_spaces(db=db)
    list_entry = next((row for row in listing if row.slug == public_space.slug), None)
    assert list_entry is not None
    slug_card = get_public_space(public_space.slug, db=db)
    assert slug_card.model_dump().keys() == list_entry.model_dump().keys()


# ---------------------------------------------------------------------------
# 404 for anything not publicly visible
# ---------------------------------------------------------------------------


def test_unknown_slug_returns_404(db) -> None:
    with pytest.raises(HTTPException) as exc:
        get_public_space("does-not-exist-xyz", db=db)
    assert exc.value.status_code == 404


def test_private_space_is_not_exposed(db, private_space) -> None:
    with pytest.raises(HTTPException) as exc:
        get_public_space(private_space.slug, db=db)
    assert exc.value.status_code == 404


def test_draft_space_is_not_exposed(db, draft_space) -> None:
    with pytest.raises(HTTPException) as exc:
        get_public_space(draft_space.slug, db=db)
    assert exc.value.status_code == 404


def test_auto_grant_space_is_not_exposed(db, auto_grant_space) -> None:
    """Operational Spaces (World Builders) must never be surfaced via
    the public single-slug endpoint — they don't appear in the list
    either."""
    with pytest.raises(HTTPException) as exc:
        get_public_space(auto_grant_space.slug, db=db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Private fields are not exposed
# ---------------------------------------------------------------------------


_PRIVATE_FIELDS = {
    # Owner / management identifiers
    "creator_id",
    "creator_email",
    # Internal admin / lifecycle
    "auto_grant_role",
    "admin_note",
    # Membership internals never belong in a public response
    "memberships",
    "space_memberships",
}


def test_public_response_does_not_leak_private_fields(db, public_space) -> None:
    card = get_public_space(public_space.slug, db=db)
    payload_keys = set(card.model_dump().keys())
    leaked = payload_keys & _PRIVATE_FIELDS
    assert leaked == set(), f"Public endpoint leaked private fields: {leaked}"


# ---------------------------------------------------------------------------
# List endpoint remains unchanged (regression against the refactor)
# ---------------------------------------------------------------------------


def test_list_endpoint_still_serves_public_spaces(db, public_space) -> None:
    slugs = {row.slug for row in list_public_spaces(db=db)}
    assert public_space.slug in slugs


def test_list_endpoint_still_hides_private_and_auto_grant(
    db, private_space, auto_grant_space,
) -> None:
    slugs = {row.slug for row in list_public_spaces(db=db)}
    assert private_space.slug not in slugs
    assert auto_grant_space.slug not in slugs
