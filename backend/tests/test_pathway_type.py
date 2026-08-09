"""Tests for the Pathway Type extension (guided_experience vs
knowledge_guide).

Covers:
  * Model default: new pathways are ``guided_experience``.
  * Creator PATCH accepts + persists ``pathway_type``.
  * Creator PATCH rejects unknown values.
  * Creator + member response payloads include ``pathway_type``.
  * Member ``/complete`` returns 409 for a Knowledge Guide.
  * Member ``/notes`` is deliberately still open for KG (personal
    reflection is orthogonal to progress).
  * Member ``/guide`` returns the continuous document for a KG.
  * Member ``/guide`` returns 409 for a Guided Experience.
  * Sections + orphan steps are laid out in the expected order.

Route functions are called directly (matching the pattern in
``test_comms_admin_events.py``) rather than through TestClient — no need
to stand up the auth stack for this narrow contract test.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    get_pathway as creator_get_pathway,
    update_pathway as creator_update_pathway,
)
from app.creator.schemas import PathwayUpdateRequest
from app.models.platform import (
    Pathway,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepBlockType,
    StepContentType,
)
from app.spaces.routes import (
    complete_step,
    get_knowledge_guide,
    get_pathway_overview,
    save_notes,
)
from app.spaces.schemas import CompleteStepRequest, SaveNotesRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pathway(
    db, space, *, pathway_type: str = "guided_experience", slug: str | None = None,
) -> Pathway:
    p = Pathway(
        id=f"pw_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=slug or f"pw-{uuid.uuid4().hex[:8]}",
        title="A pathway",
        description="An example pathway.",
        pathway_type=PathwayType(pathway_type),
        status="active",
    )
    db.add(p)
    db.flush()
    return p


def _make_section(db, pathway, *, title: str, position: int) -> PathwaySection:
    sec = PathwaySection(
        id=f"ps_{uuid.uuid4().hex[:12]}",
        pathway_id=pathway.id,
        title=title,
        position=position,
    )
    db.add(sec)
    db.flush()
    return sec


def _make_step(
    db, pathway, *, title: str, position: int,
    section: PathwaySection | None = None, section_position: int | None = None,
) -> PathwayStep:
    st = PathwayStep(
        id=f"pst_{uuid.uuid4().hex[:12]}",
        pathway_id=pathway.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title=title,
        position=position,
        section_id=section.id if section else None,
        section_position=section_position,
        content_type=StepContentType.text,
        content_body=None,
    )
    db.add(st)
    db.flush()
    return st


def _make_block(db, step, *, position: int, content: str) -> PathwayStepBlock:
    b = PathwayStepBlock(
        id=f"psb_{uuid.uuid4().hex[:12]}",
        step_id=step.id,
        block_type=StepBlockType.text,
        position=position,
        content=content,
    )
    db.add(b)
    db.flush()
    return b


def _make_member(db, make_user, space, *, role: SpaceRole = SpaceRole.learner):
    """Create a user + active membership so pathway access checks pass."""
    u = make_user(role="user")
    db.add(SpaceMembership(
        id=f"sm_{uuid.uuid4().hex[:12]}",
        user_id=u.id,
        space_id=space.id,
        role=role,
        status=SpaceMembershipStatus.active,
    ))
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Model + schema defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_new_pathway_defaults_to_guided_experience(self, db, make_space):
        space = make_space()
        p = Pathway(
            id=f"pw_{uuid.uuid4().hex[:12]}",
            space_id=space.id,
            slug="new-pw",
            title="New",
            status="active",
        )
        db.add(p)
        db.flush()
        db.refresh(p)
        assert p.pathway_type == PathwayType.guided_experience


# ---------------------------------------------------------------------------
# Creator PATCH pathway_type
# ---------------------------------------------------------------------------


class TestUpdatePathwayType:
    def test_creator_can_switch_to_knowledge_guide(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)
        db.commit()

        result = creator_update_pathway(
            slug=space.slug,
            pathway_slug=pathway.slug,
            body=PathwayUpdateRequest(pathway_type="knowledge_guide"),
            db=db,
            current_user=creator,
        )
        assert result["pathway_type"] == "knowledge_guide"
        db.refresh(pathway)
        assert pathway.pathway_type == PathwayType.knowledge_guide

    def test_creator_can_switch_back_to_guided(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        db.commit()

        result = creator_update_pathway(
            slug=space.slug,
            pathway_slug=pathway.slug,
            body=PathwayUpdateRequest(pathway_type="guided_experience"),
            db=db,
            current_user=creator,
        )
        assert result["pathway_type"] == "guided_experience"

    def test_schema_rejects_unknown_pathway_type(self):
        with pytest.raises(ValueError):
            PathwayUpdateRequest(pathway_type="documentation")

    def test_creator_get_pathway_includes_pathway_type(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        db.commit()

        result = creator_get_pathway(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=creator,
        )
        assert result["pathway_type"] == "knowledge_guide"


# ---------------------------------------------------------------------------
# Member overview payload includes pathway_type
# ---------------------------------------------------------------------------


class TestMemberOverviewIncludesType:
    def test_overview_returns_pathway_type(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        member = _make_member(db, make_user, space)
        db.commit()

        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=member,
        )
        assert result.pathway_type == "knowledge_guide"

    def test_overview_sections_carry_slug(self, db, make_user, make_space):
        # The step-URL redirect for a Knowledge Guide needs to look up
        # the owning section's slug to build the canonical chapter URL.
        # Overview payload must expose it (it did not before this
        # commit) so the redirect stays a single fetch.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        sec = _make_section(db, pathway, title="Getting Started", position=0)
        _make_step(db, pathway, title="First", position=0, section=sec, section_position=0)
        member = _make_member(db, make_user, space)
        db.commit()

        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=member,
        )
        assert len(result.sections) == 1
        assert result.sections[0].slug.startswith("getting-started-")

    def test_guided_pathway_overview_reports_guided_type(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)  # default = guided_experience
        member = _make_member(db, make_user, space)
        db.commit()

        result = get_pathway_overview(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=member,
        )
        assert result.pathway_type == "guided_experience"


# ---------------------------------------------------------------------------
# /complete endpoint — 409 for Knowledge Guide, still works for Guided
# ---------------------------------------------------------------------------


class TestCompleteRefusesKnowledgeGuide:
    def test_kg_complete_returns_409(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        step = _make_step(db, pathway, title="One", position=0)
        member = _make_member(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            complete_step(
                slug=space.slug,
                pathway_slug=pathway.slug,
                step_slug=step.slug,
                body=CompleteStepRequest(reflection_text=None),
                db=db,
                current_user=member,
            )
        assert exc.value.status_code == 409

    def test_guided_complete_still_works(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)  # guided_experience
        step = _make_step(db, pathway, title="One", position=0)
        member = _make_member(db, make_user, space)
        db.commit()

        result = complete_step(
            slug=space.slug,
            pathway_slug=pathway.slug,
            step_slug=step.slug,
            body=CompleteStepRequest(reflection_text=None),
            db=db,
            current_user=member,
        )
        assert result.is_completed is True


class TestNotesRemainsOpenOnKnowledgeGuide:
    """/notes stores personal reflection text — deliberately NOT
    guarded by pathway_type because the data model has no dependency
    on completion state. If it turns out to be tightly coupled in
    practice we'd add a guard, but v1 leaves the surface unchanged.
    """

    def test_kg_notes_still_persists(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        step = _make_step(db, pathway, title="One", position=0)
        member = _make_member(db, make_user, space)
        db.commit()

        result = save_notes(
            slug=space.slug,
            pathway_slug=pathway.slug,
            step_slug=step.slug,
            body=SaveNotesRequest(reflection_text="a private note"),
            db=db,
            current_user=member,
        )
        assert result.saved is True


# ---------------------------------------------------------------------------
# /guide endpoint — Knowledge Guide continuous view
# ---------------------------------------------------------------------------


class TestKnowledgeGuideEndpoint:
    def test_guide_returns_sections_with_steps_and_blocks(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")

        setup = _make_section(db, pathway, title="Setting up", position=0)
        s1 = _make_step(
            db, pathway, title="Create your Collective",
            position=0, section=setup, section_position=0,
        )
        _make_block(db, s1, position=0, content="A")
        _make_block(db, s1, position=1, content="B")

        config = _make_section(db, pathway, title="Configuration", position=1)
        s2 = _make_step(
            db, pathway, title="Choose a Palette",
            position=1, section=config, section_position=0,
        )
        _make_block(db, s2, position=0, content="C")

        member = _make_member(db, make_user, space)
        db.commit()

        result = get_knowledge_guide(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=member,
        )
        assert result.pathway_type == "knowledge_guide"
        assert result.title == pathway.title
        assert [s.title for s in result.sections] == ["Setting up", "Configuration"]
        # Each section serialises its steps + blocks inline.
        assert [st.title for st in result.sections[0].steps] == ["Create your Collective"]
        assert len(result.sections[0].steps[0].blocks) == 2
        assert len(result.sections[1].steps[0].blocks) == 1
        # Section slugs are stable and URL-safe.
        assert result.sections[0].slug.startswith("setting-up-")

    def test_guide_puts_sectionless_steps_in_orphan_bucket(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space, pathway_type="knowledge_guide")
        # No sections at all → every step ends up in orphan_steps.
        s1 = _make_step(db, pathway, title="Intro", position=0)
        _make_block(db, s1, position=0, content="hello")
        member = _make_member(db, make_user, space)
        db.commit()

        result = get_knowledge_guide(
            slug=space.slug,
            pathway_slug=pathway.slug,
            db=db,
            current_user=member,
        )
        assert result.sections == []
        assert [s.title for s in result.orphan_steps] == ["Intro"]

    def test_guide_endpoint_refuses_guided_experience(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _make_pathway(db, space)  # guided_experience
        member = _make_member(db, make_user, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_knowledge_guide(
                slug=space.slug,
                pathway_slug=pathway.slug,
                db=db,
                current_user=member,
            )
        assert exc.value.status_code == 409
