"""Copying one Pathway step, and what cannot come with it.

A creator whose ten steps share a shape — introduction, content,
reflection, exercise, resources — should build that scaffolding once.

The thing worth testing is not that the copy exists; it is that the
copy is **independent**. Three properties carry that, and each has a
mechanism behind it rather than a convention:

* ``StepProgress`` and ``StepComment`` key on ``step_id``, which is new.
* ``ExerciseResponse`` keys on ``block_id``, and every copied block gets
  a new id — which is why blocks cannot be copied by reusing ids, and
  why a member's answers stay with the step they answered.
* Nothing instance-specific is filtered out of a copy; it is never
  read. The duplicate is built field by field from a named list, so a
  column added later is absent until somebody carries it deliberately.

Ordering is the other half. Two position columns — Pathway-wide and
within-section — and positions that are not guaranteed contiguous,
because ``create_step`` appends ``max + 1`` and deleting leaves gaps.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_pathway_step_duplication.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    ExerciseResponse,
    Pathway,
    PathwaySection,
    PathwayStatus,
    PathwayStep,
    PathwayStepBlock,
    PathwayStepManualRelease,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepBlockType,
    StepComment,
    StepContentType,
    StepProgress,
    StepResource,
)
from app.models.user import User


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).one()


@pytest.fixture
def client(db, owner):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def pathway(db, space):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"p-{uuid.uuid4().hex[:8]}",
        title="Know Yourself", status=PathwayStatus.draft, position=0,
    )
    db.add(row)
    db.flush()
    return row


def make_step(db, pathway, title: str, position: int, **kw) -> PathwayStep:
    step = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id,
        slug=kw.pop("slug", f"s-{uuid.uuid4().hex[:8]}"),
        title=title, position=position,
        content_type=kw.pop("content_type", StepContentType.text),
        **kw,
    )
    db.add(step)
    db.flush()
    return step


def add_block(db, step, block_type, position, **kw) -> PathwayStepBlock:
    block = PathwayStepBlock(
        id=_uid("blk"), step_id=step.id, block_type=block_type,
        position=position, **kw,
    )
    db.add(block)
    db.flush()
    return block


def url(space, pathway, step) -> str:
    return (
        f"/api/creator/spaces/{space.slug}/pathways/{pathway.slug}"
        f"/steps/{step.slug}/duplicate"
    )


def steps_in_order(db, pathway) -> list[PathwayStep]:
    return (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )


# ---------------------------------------------------------------------------
# The content
# ---------------------------------------------------------------------------


@pytest.fixture
def rich_step(db, pathway):
    """A step with the five-element shape the feature exists for."""
    step = make_step(
        db, pathway, "Understanding Your Patterns", 1,
        content_body="# A heading\n\nSome **markdown** with a [link](https://x.test).",
        content_url="https://video.test/abc",
        estimated_minutes=25,
        is_required=True,
        reflection_enabled=True,
        discussion_enabled=False,
        banner_image_url="https://cdn.test/banner.jpg",
        release_type="days_after_enrollment",
        release_offset_days=7,
    )
    add_block(db, step, StepBlockType.text, 0,
              content="Welcome to this step.\n\n*Take your time.*")
    add_block(db, step, StepBlockType.video_embed, 1,
              embed_url="https://youtube.test/watch?v=1",
              heading="Watch first", caption="12 minutes")
    add_block(db, step, StepBlockType.reflection_prompt, 2,
              content="What pattern do you notice?")
    add_block(db, step, StepBlockType.exercise, 3,
              content="Write three sentences.", response_enabled=True)
    add_block(db, step, StepBlockType.callout, 4,
              content="Be gentle with yourself.", label="tip",
              container_style="teal")
    db.add(StepResource(
        id=_uid("sr"), step_id=step.id, title="Workbook",
        resource_type="pdf", url="uploads/workbook.pdf",
        file_name="workbook.pdf", file_size=1024, mime_type="application/pdf",
        position=0, is_downloadable=True,
    ))
    db.flush()
    return step


class TestWhatIsCopied:
    def test_the_step_configuration_comes_with_it(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        body = client.post(url(space, pathway, rich_step))
        assert body.status_code == 201, body.text
        new = db.get(PathwayStep, body.json()["id"])

        assert new.content_body == rich_step.content_body
        assert new.content_url == rich_step.content_url
        assert new.content_type == rich_step.content_type
        assert new.estimated_minutes == 25
        assert new.is_required is True
        assert new.reflection_enabled is True
        assert new.discussion_enabled is False
        assert new.banner_image_url == "https://cdn.test/banner.jpg"
        assert new.release_type == "days_after_enrollment"
        assert new.release_offset_days == 7

    def test_the_markdown_arrives_intact(
        self, client, db, space, pathway, rich_step,
    ):
        """Not flattened to plain text, and not re-escaped."""
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        new = db.get(PathwayStep, new_id)
        assert new.content_body == (
            "# A heading\n\nSome **markdown** with a [link](https://x.test)."
        )

    def test_the_title_is_suffixed(self, client, db, space, pathway, rich_step):
        db.commit()
        body = client.post(url(space, pathway, rich_step)).json()
        assert body["title"] == "Understanding Your Patterns (Copy)"

    def test_the_blocks_come_across_in_order(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        blocks = (
            db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == new_id)
            .order_by(PathwayStepBlock.position)
            .all()
        )
        assert [b.block_type for b in blocks] == [
            StepBlockType.text, StepBlockType.video_embed,
            StepBlockType.reflection_prompt, StepBlockType.exercise,
            StepBlockType.callout,
        ]
        assert [b.position for b in blocks] == [0, 1, 2, 3, 4]

    def test_every_block_field_comes_across(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        new_blocks = {
            b.position: b for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == new_id).all()
        }
        old_blocks = {
            b.position: b for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == rich_step.id).all()
        }
        from app.services.pathway_step_duplication import BLOCK_FIELDS

        for position, old in old_blocks.items():
            for field in BLOCK_FIELDS:
                assert getattr(new_blocks[position], field) == getattr(old, field), (
                    f"block {position} lost {field}"
                )

    def test_the_step_resources_come_across(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        copied = db.query(StepResource).filter(
            StepResource.step_id == new_id).all()
        assert len(copied) == 1
        assert copied[0].title == "Workbook"
        assert copied[0].url == "uploads/workbook.pdf"
        assert copied[0].file_size == 1024

    def test_a_step_with_no_blocks_still_duplicates(
        self, client, db, space, pathway,
    ):
        bare = make_step(db, pathway, "Just a title", 0)
        db.commit()
        r = client.post(url(space, pathway, bare))
        assert r.status_code == 201, r.text
        assert db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == r.json()["id"]).count() == 0


class TestMediaIsReferencedNotReuploaded:
    @pytest.fixture
    def with_media(self, db, space, pathway, owner):
        from app.models.platform import CreatorMediaAsset

        from app.models.platform import MediaType

        asset = CreatorMediaAsset(
            id=_uid("ma"), space_id=space.id,
            uploaded_by_user_id=owner.id,
            title="A photo", original_filename="photo.jpg",
            stored_filename="photo.jpg",
            storage_path="media/x/photo.jpg",
            file_url="https://cdn.test/media/x/photo.jpg",
            mime_type="image/jpeg", media_type=MediaType.image,
            file_size_bytes=2048, extension="jpg",
        )
        db.add(asset)
        step = make_step(db, pathway, "With media", 0)
        add_block(db, step, StepBlockType.image, 0,
                  media_asset_id=asset.id, caption="A photo")
        db.flush()
        return step, asset

    def test_the_block_points_at_the_same_asset(
        self, client, db, space, pathway, with_media,
    ):
        """One asset, two blocks. A Media Library asset already serves
        many blocks across many steps, so this is the established
        arrangement and costs no storage."""
        from app.models.platform import CreatorMediaAsset

        step, asset = with_media
        before = db.query(CreatorMediaAsset).count()
        db.commit()
        new_id = client.post(url(space, pathway, step)).json()["id"]

        copied = db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == new_id).one()
        assert copied.media_asset_id == asset.id
        assert db.query(CreatorMediaAsset).count() == before, (
            "duplication uploaded a second copy of the file"
        )

    def test_deleting_the_duplicates_block_leaves_the_asset(
        self, client, db, space, pathway, with_media,
    ):
        """And therefore leaves the original's block working."""
        from app.models.platform import CreatorMediaAsset

        step, asset = with_media
        db.commit()
        new_id = client.post(url(space, pathway, step)).json()["id"]

        db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == new_id).delete()
        db.commit()

        assert db.get(CreatorMediaAsset, asset.id) is not None
        original_block = db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == step.id).one()
        assert original_block.media_asset_id == asset.id

    def test_deleting_the_duplicate_step_leaves_the_asset(
        self, client, db, space, pathway, with_media,
    ):
        from app.models.platform import CreatorMediaAsset

        step, asset = with_media
        db.commit()
        new_id = client.post(url(space, pathway, step)).json()["id"]
        db.delete(db.get(PathwayStep, new_id))
        db.commit()
        assert db.get(CreatorMediaAsset, asset.id) is not None


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------


class TestTheCopyIsIndependent:
    def test_every_identity_is_new(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        body = client.post(url(space, pathway, rich_step)).json()
        assert body["id"] != rich_step.id
        assert body["slug"] != rich_step.slug

        old_block_ids = {
            b.id for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == rich_step.id).all()
        }
        new_block_ids = {
            b.id for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == body["id"]).all()
        }
        assert old_block_ids and new_block_ids
        assert not (old_block_ids & new_block_ids), (
            "a block id is shared, so member responses would follow"
        )

    def test_editing_the_duplicate_leaves_the_original(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        new = db.get(PathwayStep, new_id)
        new.title = "Something else entirely"
        new.content_body = "Rewritten."
        db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == new_id,
            PathwayStepBlock.position == 0,
        ).update({"content": "Changed."})
        db.commit()
        db.expire_all()

        source = db.get(PathwayStep, rich_step.id)
        assert source.title == "Understanding Your Patterns"
        assert source.content_body.startswith("# A heading")
        first = db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == rich_step.id,
            PathwayStepBlock.position == 0,
        ).one()
        assert first.content == "Welcome to this step.\n\n*Take your time.*"

    def test_editing_the_original_leaves_the_duplicate(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        source = db.get(PathwayStep, rich_step.id)
        source.content_body = "The original moved on."
        db.commit()
        db.expire_all()
        assert db.get(PathwayStep, new_id).content_body.startswith("# A heading")

    def test_deleting_the_duplicate_leaves_the_original(
        self, client, db, space, pathway, rich_step,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        db.delete(db.get(PathwayStep, new_id))
        db.commit()

        assert db.get(PathwayStep, rich_step.id) is not None
        assert db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == rich_step.id).count() == 5
        assert db.query(StepResource).filter(
            StepResource.step_id == rich_step.id).count() == 1


# ---------------------------------------------------------------------------
# Member activity
# ---------------------------------------------------------------------------


class TestMemberActivityDoesNotFollow:
    @pytest.fixture
    def member_with_activity(self, db, space, pathway, rich_step, make_user):
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.add(StepProgress(
            id=_uid("sp"), user_id=member.id, step_id=rich_step.id,
            completed_at=datetime.utcnow(),
            reflection_text="What I noticed was…",
        ))
        exercise = db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == rich_step.id,
            PathwayStepBlock.block_type == StepBlockType.exercise,
        ).one()
        db.add(ExerciseResponse(
            id=_uid("er"), user_id=member.id, block_id=exercise.id,
            response_text="My three sentences.",
        ))
        db.add(StepComment(
            id=_uid("sc"), step_id=rich_step.id, author_id=member.id,
            body="A question about this step.",
        ))
        db.add(PathwayStepManualRelease(
            id=_uid("mr"), step_id=rich_step.id, user_id=member.id,
        ))
        db.flush()
        return member

    def test_no_completion_record_comes_with_it(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        assert db.query(StepProgress).filter(
            StepProgress.step_id == new_id).count() == 0

    def test_no_reflection_text_comes_with_it(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        rows = db.query(StepProgress).filter(
            StepProgress.step_id == new_id).all()
        assert rows == []

    def test_no_exercise_response_comes_with_it(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        """Keyed on ``block_id``, and the copied blocks are new rows —
        so this holds by construction rather than by filtering."""
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        new_block_ids = [
            b.id for b in db.query(PathwayStepBlock)
            .filter(PathwayStepBlock.step_id == new_id).all()
        ]
        assert db.query(ExerciseResponse).filter(
            ExerciseResponse.block_id.in_(new_block_ids)).count() == 0

    def test_no_comment_comes_with_it(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        assert db.query(StepComment).filter(
            StepComment.step_id == new_id).count() == 0

    def test_no_manual_release_comes_with_it(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        """A member individually let into the original is not let into
        the copy."""
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        assert db.query(PathwayStepManualRelease).filter(
            PathwayStepManualRelease.step_id == new_id).count() == 0

    def test_the_originals_activity_is_untouched(
        self, client, db, space, pathway, rich_step, member_with_activity,
    ):
        """The property that matters most: a member's answers stay
        where they answered."""
        db.commit()
        client.post(url(space, pathway, rich_step))
        db.expire_all()

        progress = db.query(StepProgress).filter(
            StepProgress.step_id == rich_step.id).one()
        assert progress.reflection_text == "What I noticed was…"
        assert progress.completed_at is not None

        exercise = db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == rich_step.id,
            PathwayStepBlock.block_type == StepBlockType.exercise,
        ).one()
        response = db.query(ExerciseResponse).filter(
            ExerciseResponse.block_id == exercise.id).one()
        assert response.response_text == "My three sentences."

        assert db.query(StepComment).filter(
            StepComment.step_id == rich_step.id).count() == 1
        assert db.query(PathwayStepManualRelease).filter(
            PathwayStepManualRelease.step_id == rich_step.id).count() == 1


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    @pytest.fixture
    def three_steps(self, db, pathway):
        a = make_step(db, pathway, "Welcome", 0)
        b = make_step(db, pathway, "Understanding Your Patterns", 1)
        c = make_step(db, pathway, "Reflection", 2)
        db.flush()
        return a, b, c

    def test_a_middle_step_lands_immediately_after_its_source(
        self, client, db, space, pathway, three_steps,
    ):
        a, b, c = three_steps
        db.commit()
        new_id = client.post(url(space, pathway, b)).json()["id"]
        db.expire_all()
        assert [s.title for s in steps_in_order(db, pathway)] == [
            "Welcome",
            "Understanding Your Patterns",
            "Understanding Your Patterns (Copy)",
            "Reflection",
        ]
        assert db.get(PathwayStep, new_id).position == 2

    def test_the_first_step(self, client, db, space, pathway, three_steps):
        a, b, c = three_steps
        db.commit()
        client.post(url(space, pathway, a))
        db.expire_all()
        assert [s.title for s in steps_in_order(db, pathway)] == [
            "Welcome", "Welcome (Copy)",
            "Understanding Your Patterns", "Reflection",
        ]

    def test_the_last_step(self, client, db, space, pathway, three_steps):
        a, b, c = three_steps
        db.commit()
        client.post(url(space, pathway, c))
        db.expire_all()
        assert [s.title for s in steps_in_order(db, pathway)] == [
            "Welcome", "Understanding Your Patterns",
            "Reflection", "Reflection (Copy)",
        ]

    def test_the_source_keeps_its_position(
        self, client, db, space, pathway, three_steps,
    ):
        a, b, c = three_steps
        db.commit()
        client.post(url(space, pathway, b))
        db.expire_all()
        assert db.get(PathwayStep, b.id).position == 1

    def test_no_two_steps_share_a_position(
        self, client, db, space, pathway, three_steps,
    ):
        a, b, c = three_steps
        db.commit()
        client.post(url(space, pathway, b))
        db.expire_all()
        positions = [s.position for s in steps_in_order(db, pathway)]
        assert len(set(positions)) == len(positions), positions

    def test_gaps_in_the_existing_positions_are_tolerated(
        self, client, db, space, pathway,
    ):
        """``create_step`` appends ``max + 1`` and deleting leaves gaps,
        so contiguity cannot be assumed."""
        a = make_step(db, pathway, "First", 0)
        b = make_step(db, pathway, "Second", 5)
        c = make_step(db, pathway, "Third", 11)
        db.commit()
        client.post(url(space, pathway, b))
        db.expire_all()
        ordered = steps_in_order(db, pathway)
        assert [s.title for s in ordered] == [
            "First", "Second", "Second (Copy)", "Third",
        ]
        positions = [s.position for s in ordered]
        assert len(set(positions)) == len(positions), positions

    def test_duplicating_repeatedly(self, client, db, space, pathway, three_steps):
        a, b, c = three_steps
        db.commit()
        client.post(url(space, pathway, b))
        client.post(url(space, pathway, b))
        client.post(url(space, pathway, b))
        db.expire_all()
        titles = [s.title for s in steps_in_order(db, pathway)]
        assert titles[0] == "Welcome"
        assert titles[1] == "Understanding Your Patterns"
        assert titles[-1] == "Reflection"
        assert titles.count("Understanding Your Patterns (Copy)") == 3
        positions = [s.position for s in steps_in_order(db, pathway)]
        assert len(set(positions)) == len(positions), positions

    def test_each_repeat_gets_its_own_slug(
        self, client, db, space, pathway, three_steps,
    ):
        a, b, c = three_steps
        db.commit()
        slugs = [
            client.post(url(space, pathway, b)).json()["slug"]
            for _ in range(3)
        ]
        assert len(set(slugs)) == 3, slugs
        assert b.slug not in slugs

    def test_the_duplicate_can_be_reordered_normally(
        self, client, db, space, pathway, three_steps,
    ):
        a, b, c = three_steps
        db.commit()
        new_id = client.post(url(space, pathway, b)).json()["id"]
        ordered = steps_in_order(db, pathway)
        reversed_ids = [s.id for s in reversed(ordered)]
        r = client.post(
            f"/api/creator/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/reorder",
            json={"ids": reversed_ids},
        )
        assert r.status_code == 204, r.text
        db.expire_all()
        assert [s.id for s in steps_in_order(db, pathway)] == reversed_ids
        assert db.get(PathwayStep, new_id) is not None


class TestSectionedOrdering:
    @pytest.fixture
    def sectioned(self, db, pathway):
        section = PathwaySection(
            id=_uid("sec"), pathway_id=pathway.id, title="Module One",
            position=0,
        )
        db.add(section)
        db.flush()
        a = make_step(db, pathway, "Alpha", 0,
                      section_id=section.id, section_position=0)
        b = make_step(db, pathway, "Beta", 1,
                      section_id=section.id, section_position=1)
        c = make_step(db, pathway, "Gamma", 2,
                      section_id=section.id, section_position=2)
        db.flush()
        return section, (a, b, c)

    def test_both_position_columns_shift(
        self, client, db, space, pathway, sectioned,
    ):
        """A sectioned step is ordered twice over — Pathway-wide and
        within its section — so shifting one would place the duplicate
        correctly in one view and wrongly in the other."""
        section, (a, b, c) = sectioned
        db.commit()
        new_id = client.post(url(space, pathway, b)).json()["id"]
        db.expire_all()

        by_section = (
            db.query(PathwayStep)
            .filter(PathwayStep.section_id == section.id)
            .order_by(PathwayStep.section_position)
            .all()
        )
        assert [s.title for s in by_section] == [
            "Alpha", "Beta", "Beta (Copy)", "Gamma",
        ]
        assert [s.section_position for s in by_section] == [0, 1, 2, 3]
        assert [s.title for s in steps_in_order(db, pathway)] == [
            "Alpha", "Beta", "Beta (Copy)", "Gamma",
        ]
        assert db.get(PathwayStep, new_id).section_id == section.id

    def test_an_unsectioned_step_keeps_a_null_section_position(
        self, client, db, space, pathway,
    ):
        step = make_step(db, pathway, "Loose", 0)
        db.commit()
        new_id = client.post(url(space, pathway, step)).json()["id"]
        new = db.get(PathwayStep, new_id)
        assert new.section_id is None
        assert new.section_position is None


# ---------------------------------------------------------------------------
# Visibility and notifications
# ---------------------------------------------------------------------------


class TestNothingIsAnnounced:
    @pytest.fixture
    def published_pathway_with_member(self, db, space, pathway, make_user):
        pathway.status = PathwayStatus.active
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        return member

    def test_no_communication_event_on_a_draft_pathway(
        self, client, db, space, pathway, rich_step,
    ):
        from app.comms.models import CommunicationEvent

        db.commit()
        before = db.query(CommunicationEvent).count()
        r = client.post(url(space, pathway, rich_step))
        assert r.status_code == 201, r.text
        assert db.query(CommunicationEvent).count() == before

    def test_no_communication_event_on_a_published_pathway(
        self, client, db, space, pathway, rich_step,
        published_pathway_with_member,
    ):
        """``create_step`` queues ``trigger_new_step`` when the Pathway
        is member-visible. Duplication must not: the copy arrives
        carrying somebody else's words and is about to be rewritten."""
        from app.comms.models import CommunicationEvent

        db.commit()
        before = db.query(CommunicationEvent).count()
        r = client.post(url(space, pathway, rich_step))
        assert r.status_code == 201, r.text
        assert db.query(CommunicationEvent).count() == before

    def test_no_notification_row(
        self, client, db, space, pathway, rich_step,
        published_pathway_with_member,
    ):
        from app.models.notification import Notification

        db.commit()
        before = db.query(Notification).count()
        client.post(url(space, pathway, rich_step))
        assert db.query(Notification).count() == before

    def test_no_shared_activity_row(
        self, client, db, space, pathway, rich_step,
        published_pathway_with_member,
    ):
        """``create_step`` records ``step_published`` activity. A
        duplicate is not a publication."""
        from app.models.activity import Activity

        db.commit()
        before = db.query(Activity).count()
        client.post(url(space, pathway, rich_step))
        assert db.query(Activity).count() == before

    def test_the_route_does_not_reach_for_the_step_announcer(self):
        """A source check as well, because the absence of a call is
        what these assert and an absence is easy to reintroduce."""
        import inspect

        from app.creator import routes

        # The docstring names both by way of explaining their absence,
        # so it is stripped before the check — otherwise this asserts
        # that the reason cannot be written down.
        source = inspect.getsource(routes.duplicate_pathway_step)
        body = source.split('"""')[2] if source.count('"""') >= 2 else source
        for forbidden in (
            "trigger_new_step", "record_step_published",
            "background_tasks", "BackgroundTasks",
        ):
            assert forbidden not in body, forbidden

    def test_a_duplicate_in_a_published_pathway_is_still_in_it(
        self, client, db, space, pathway, rich_step,
        published_pathway_with_member,
    ):
        """Steps have no draft state of their own — visibility is the
        Pathway's. Asserted so the limitation is recorded rather than
        assumed, and so inventing a per-step draft later is a
        deliberate act that breaks this test."""
        db.commit()
        new_id = client.post(url(space, pathway, rich_step)).json()["id"]
        new = db.get(PathwayStep, new_id)
        assert new.pathway_id == pathway.id
        assert not hasattr(new, "is_published"), (
            "a step now has its own publication state — the duplication "
            "route should set it to draft"
        )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_a_stranger_cannot_duplicate(
        self, db, space, pathway, rich_step, make_user,
    ):
        db.commit()
        outsider = make_user(role="creator")
        try:
            r = as_user(db, outsider).post(url(space, pathway, rich_step))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_an_ordinary_member_cannot_duplicate(
        self, db, space, pathway, rich_step, make_user,
    ):
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, member).post(url(space, pathway, rich_step))
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_of_the_collective_may_duplicate(
        self, db, space, pathway, rich_step, make_user,
    ):
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        try:
            r = as_user(db, moderator).post(url(space, pathway, rich_step))
            assert r.status_code == 201, r.text
        finally:
            app.dependency_overrides.clear()

    def test_a_pathway_in_another_collective_is_not_found(
        self, client, db, make_space, space, pathway,
    ):
        """Cross-Collective duplication. The lookup is scoped to the
        Collective the creator manages, so the step is simply absent."""
        other = make_space()
        elsewhere = Pathway(
            id=_uid("pw"), space_id=other.id,
            slug=f"p-{uuid.uuid4().hex[:8]}", title="Theirs",
            status=PathwayStatus.draft, position=0,
        )
        db.add(elsewhere)
        db.flush()
        their_step = make_step(db, elsewhere, "Their step", 0)
        db.commit()
        r = client.post(url(space, pathway, their_step))
        assert r.status_code == 404, r.status_code

    def test_a_missing_step_is_not_found(self, client, db, space, pathway):
        db.commit()
        r = client.post(
            f"/api/creator/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/no-such-step/duplicate"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


class TestItIsAllOrNothing:
    def test_the_service_never_commits(self, db, space, pathway, rich_step):
        """The caller owns the transaction. If the copy committed in
        pieces, a failure part-way could leave a step with half its
        content, or a Pathway whose ordering was shifted for a step
        that never arrived."""
        from app.services import pathway_step_duplication as dup

        commits = []
        real_commit = type(db).commit

        def counted(self, *a, **kw):
            commits.append(1)
            return real_commit(self, *a, **kw)

        db.commit()
        try:
            type(db).commit = counted
            dup.duplicate_step(db, rich_step, slug="alpha-copy")
            assert commits == [], (
                "the duplication service committed on its own"
            )
        finally:
            type(db).commit = real_commit

    def test_the_route_commits_once_and_only_after_the_content(
        self, db, space, pathway, rich_step, owner, monkeypatch,
    ):
        """What makes the whole operation atomic: the shift, the step,
        the blocks and the resources all land in one transaction, and
        the single commit is the last thing that happens.

        Asserted by instrumentation rather than by forcing a rollback.
        A true rollback test needs a second connection to observe
        from, and this suite runs every test inside one outer
        transaction with savepoints — a ``db.rollback()`` here discards
        the fixtures along with the work, and a second connection
        cannot see uncommitted fixture rows at all. The ordering of the
        commit relative to the copying is the property that matters and
        it is observable."""
        from app.creator import routes
        from app.services import pathway_step_duplication as dup

        make_step(db, pathway, "After", 2)
        db.commit()

        events: list[str] = []
        real_blocks = dup.duplicate_blocks
        real_resources = dup.duplicate_resources
        real_commit = type(db).commit

        def spy_blocks(*a, **kw):
            events.append("blocks")
            return real_blocks(*a, **kw)

        def spy_resources(*a, **kw):
            events.append("resources")
            return real_resources(*a, **kw)

        def spy_commit(self, *a, **kw):
            events.append("commit")
            return real_commit(self, *a, **kw)

        monkeypatch.setattr(dup, "duplicate_blocks", spy_blocks)
        monkeypatch.setattr(dup, "duplicate_resources", spy_resources)
        try:
            type(db).commit = spy_commit
            routes.duplicate_pathway_step(
                space.slug, pathway.slug, rich_step.slug,
                db=db, current_user=owner,
            )
        finally:
            type(db).commit = real_commit

        assert events == ["blocks", "resources", "commit"], events

    def test_a_failure_copying_blocks_raises_rather_than_half_copying(
        self, db, space, pathway, rich_step, owner, monkeypatch,
    ):
        """The step row and its blocks are written before any commit,
        so a failure propagates with nothing committed. Observed as the
        exception reaching the caller with no commit having run."""
        from app.creator import routes
        from app.services import pathway_step_duplication as dup

        db.commit()
        commits = []
        real_commit = type(db).commit

        def counted(self, *a, **kw):
            commits.append(1)
            return real_commit(self, *a, **kw)

        def explode(*a, **kw):
            raise RuntimeError("copying blocks failed")

        monkeypatch.setattr(dup, "duplicate_blocks", explode)
        try:
            type(db).commit = counted
            with pytest.raises(RuntimeError):
                routes.duplicate_pathway_step(
                    space.slug, pathway.slug, rich_step.slug,
                    db=db, current_user=owner,
                )
            assert commits == [], "a failed duplication committed anyway"
        finally:
            type(db).commit = real_commit

    def test_the_route_locks_the_pathway(self):
        """Two duplications in one Pathway must not both read the same
        source position and insert at it. Asserted on the source: the
        race needs two connections, which this suite's single-session
        fixtures cannot provide, so the mechanism is checked instead of
        the symptom."""
        import inspect

        from app.creator import routes

        source = inspect.getsource(routes.duplicate_pathway_step)
        assert "with_for_update()" in source, (
            "the Pathway row is no longer locked for the duration"
        )


class TestTheTitleSuffix:
    def test_a_long_title_keeps_the_suffix(self):
        from app.services.pathway_step_duplication import copied_title

        limit = PathwayStep.__table__.columns["title"].type.length
        out = copied_title("x" * limit)
        assert len(out) <= limit
        assert out.endswith("(Copy)")

    def test_an_ordinary_title(self):
        from app.services.pathway_step_duplication import copied_title

        assert copied_title("Understanding Your Patterns") == (
            "Understanding Your Patterns (Copy)"
        )

    def test_a_copy_of_a_copy_is_tellable_apart_by_slug(
        self, client, db, space, pathway,
    ):
        """The title gains a second suffix, which is honest — and the
        slug is what keeps them addressable."""
        step = make_step(db, pathway, "Alpha", 0)
        db.commit()
        first = client.post(url(space, pathway, step)).json()
        again = client.post(
            f"/api/creator/spaces/{space.slug}/pathways/{pathway.slug}"
            f"/steps/{first['slug']}/duplicate"
        ).json()
        assert again["title"] == "Alpha (Copy) (Copy)"
        assert again["slug"] != first["slug"]
