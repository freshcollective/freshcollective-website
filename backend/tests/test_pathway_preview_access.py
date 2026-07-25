"""Preview access — a collective's owner or manager can view draft
pathways through the public overview / list / step endpoints; public
visitors and non-managers still get a 404.

The bypass is auth-transparent (no query flag, no cookie) and lives in
``_get_space_visible_to``. Public routes that don't take the helper
(e.g. ``list_public_spaces``, ``join_space``) keep the strict
active-status filter, so nothing about discovery or join semantics
shifts.
"""

from __future__ import annotations

from datetime import datetime
import uuid

import pytest
from fastapi import HTTPException

from app.models.platform import (
    Pathway,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces.routes import (
    get_pathway_overview,
    list_pathways,
    list_pathway_about_blocks,
)


@pytest.fixture
def draft_space(db, make_user):
    """A draft collective owned by a fresh creator user."""
    owner = make_user(role="creator")
    space = Space(
        id=f"s_{uuid.uuid4().hex[:12]}",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        name="Draft Collective",
        status="draft",
        is_public=False,
        creator_id=owner.id,
    )
    db.add(space)
    db.flush()
    return space, owner


@pytest.fixture
def draft_pathway(db, draft_space):
    space, _owner = draft_space
    pw = Pathway(
        id=f"p_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=f"draft-path-{uuid.uuid4().hex[:8]}",
        title="Draft pathway",
        status="draft",
        position=0,
    )
    db.add(pw)
    db.flush()
    return pw


# ---------------------------------------------------------------------------
# get_pathway_overview
# ---------------------------------------------------------------------------


class TestOverviewVisibility:
    def test_public_visitor_gets_404_on_draft_collective(
        self, db, draft_space, draft_pathway
    ):
        space, _ = draft_space
        with pytest.raises(HTTPException) as e:
            get_pathway_overview(
                slug=space.slug,
                pathway_slug=draft_pathway.slug,
                db=db,
                current_user=None,
            )
        assert e.value.status_code == 404

    def test_unrelated_user_gets_404_on_draft_collective(
        self, db, make_user, draft_space, draft_pathway
    ):
        space, _ = draft_space
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            get_pathway_overview(
                slug=space.slug,
                pathway_slug=draft_pathway.slug,
                db=db,
                current_user=stranger,
            )
        assert e.value.status_code == 404

    def test_owner_can_preview_draft_pathway(
        self, db, draft_space, draft_pathway
    ):
        space, owner = draft_space
        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=draft_pathway.slug,
            db=db,
            current_user=owner,
        )
        assert result.id == draft_pathway.id
        assert result.user_has_access is True

    def test_admin_can_preview_draft_pathway(
        self, db, make_user, draft_space, draft_pathway
    ):
        space, _ = draft_space
        admin = make_user(role="admin")
        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=draft_pathway.slug,
            db=db,
            current_user=admin,
        )
        assert result.id == draft_pathway.id

    def test_creator_membership_can_preview_draft_pathway(
        self, db, make_user, draft_space, draft_pathway
    ):
        space, _ = draft_space
        coach = make_user(role="user")
        db.add(SpaceMembership(
            id=f"m_{uuid.uuid4().hex[:12]}",
            user_id=coach.id,
            space_id=space.id,
            role=SpaceRole.creator,
            status=SpaceMembershipStatus.active,
            source="invited",
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=draft_pathway.slug,
            db=db,
            current_user=coach,
        )
        assert result.id == draft_pathway.id


# ---------------------------------------------------------------------------
# list_pathways — draft collective, draft pathways still hidden from non-managers
# ---------------------------------------------------------------------------


class TestPathwayListVisibility:
    def test_public_visitor_gets_404_when_collective_is_draft(
        self, db, draft_space, draft_pathway
    ):
        space, _ = draft_space
        with pytest.raises(HTTPException) as e:
            list_pathways(slug=space.slug, db=db, current_user=None)
        assert e.value.status_code == 404

    def test_owner_sees_draft_pathways_listed(
        self, db, draft_space, draft_pathway
    ):
        space, owner = draft_space
        result = list_pathways(slug=space.slug, db=db, current_user=owner)
        assert any(p.id == draft_pathway.id for p in result)


# ---------------------------------------------------------------------------
# list_pathway_about_blocks
# ---------------------------------------------------------------------------


class TestAboutBlocksVisibility:
    def test_public_visitor_gets_404_on_draft_collective(
        self, db, draft_space, draft_pathway
    ):
        space, _ = draft_space
        with pytest.raises(HTTPException) as e:
            list_pathway_about_blocks(
                slug=space.slug,
                pathway_slug=draft_pathway.slug,
                db=db,
                current_user=None,
            )
        assert e.value.status_code == 404

    def test_owner_can_read_draft_about_blocks(
        self, db, draft_space, draft_pathway
    ):
        space, owner = draft_space
        # Empty about-blocks list is fine — the test only cares that the
        # route doesn't 404 for the owner.
        result = list_pathway_about_blocks(
            slug=space.slug,
            pathway_slug=draft_pathway.slug,
            db=db,
            current_user=owner,
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Public discovery + join must NOT be affected
# ---------------------------------------------------------------------------


class TestPublicRoutesUnaffected:
    def test_draft_collective_still_hidden_from_public_list(
        self, db, draft_space
    ):
        """The public discovery list still filters by ``status='active'``
        (via ``list_public_spaces``), not the visible-to helper. A
        preview-eligible manager doesn't accidentally expose their
        drafts to the world."""
        from app.spaces.routes import list_public_spaces
        space, _ = draft_space
        rows = list_public_spaces(db=db)
        assert not any(r.id == space.id for r in rows)
