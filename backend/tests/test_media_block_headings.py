"""An optional heading on media blocks, and the promise that it is optional.

Round 1, item 7. Video, audio and file-download blocks gained a
``heading`` column so a creator can title a recording or a worksheet
without spending the caption on it.

The interesting assertions here are not that a heading can be saved —
they are the ones about *absence*. Every block in production predates
this column, so the whole change rests on ``NULL`` being indistinguishable
from how those rows behaved before. A column that quietly turned into
``''``, or a response model that refused to serialise a row without a
heading, would break published content rather than extend it.

``heading`` is deliberately its own column rather than a reuse of
``label`` or ``caption``: neither was free across all three block types,
and starting to render a field that is currently written-but-never-shown
would have surfaced stray text on live pages. That reasoning is recorded
in migration 151.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_media_block_headings.py
"""

from __future__ import annotations

import uuid

import pytest

from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
    StepBlockCreateRequest,
    StepBlockResponse,
    StepBlockUpdateRequest,
)
from app.models.platform import (
    PathwayAboutBlock,
    PathwayStep,
    PathwayStepBlock,
    Pathway,
)

MEDIA_TYPES = ("video_embed", "audio", "file_download")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def pathway(db, make_space):
    space = make_space()
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway",
        status="active",
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def step(db, pathway):
    s = PathwayStep(
        id=_uid("st"),
        pathway_id=pathway.id,
        slug=f"st-{uuid.uuid4().hex[:8]}",
        title="A Step",
        position=0,
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# The column exists on both tables and defaults to absent
# ---------------------------------------------------------------------------


class TestTheColumn:
    @pytest.mark.parametrize("block_type", MEDIA_TYPES)
    def test_a_step_block_written_without_a_heading_has_none(
        self, db, step, block_type,
    ):
        # Exactly the shape of every row already in production.
        block = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type=block_type, position=0,
        )
        db.add(block)
        db.flush()
        db.refresh(block)
        assert block.heading is None

    @pytest.mark.parametrize("block_type", MEDIA_TYPES)
    def test_an_about_block_written_without_a_heading_has_none(
        self, db, pathway, block_type,
    ):
        block = PathwayAboutBlock(
            id=_uid("ab"), pathway_id=pathway.id, block_type=block_type, position=0,
        )
        db.add(block)
        db.flush()
        db.refresh(block)
        assert block.heading is None

    def test_a_heading_round_trips(self, db, step):
        block = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type="audio", position=0,
            heading="Morning meditation",
        )
        db.add(block)
        db.flush()
        db.expire(block)
        assert block.heading == "Morning meditation"

    def test_it_accepts_the_full_declared_width(self, db, step):
        # String(300), matching ``label``. A shorter effective limit
        # would truncate silently on write.
        long_heading = "x" * 300
        block = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type="audio", position=0,
            heading=long_heading,
        )
        db.add(block)
        db.flush()
        db.expire(block)
        assert block.heading is not None
        assert len(block.heading) == 300

    def test_a_heading_can_be_cleared_back_to_absent(self, db, step):
        block = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type="audio", position=0,
            heading="Temporary",
        )
        db.add(block)
        db.flush()
        block.heading = None
        db.flush()
        db.expire(block)
        assert block.heading is None


# ---------------------------------------------------------------------------
# The API carries it, in both directions, for both tables
# ---------------------------------------------------------------------------


class TestTheSchemas:
    def test_both_responses_serialise_a_block_with_no_heading(self, db, step, pathway):
        # The compatibility assertion that matters most: a required
        # field with no default would make every pre-existing row fail
        # to serialise, turning a read of published content into a 500.
        sb = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type="audio", position=0,
        )
        ab = PathwayAboutBlock(
            id=_uid("ab"), pathway_id=pathway.id, block_type="audio", position=0,
        )
        db.add_all([sb, ab])
        db.flush()

        assert StepBlockResponse.model_validate(sb).heading is None
        assert AboutBlockResponse.model_validate(ab).heading is None

    def test_both_responses_carry_a_heading_when_present(self, db, step, pathway):
        sb = PathwayStepBlock(
            id=_uid("b"), step_id=step.id, block_type="video_embed", position=0,
            heading="This week's practice",
        )
        ab = PathwayAboutBlock(
            id=_uid("ab"), pathway_id=pathway.id, block_type="video_embed", position=0,
            heading="What to expect",
        )
        db.add_all([sb, ab])
        db.flush()

        assert StepBlockResponse.model_validate(sb).heading == "This week's practice"
        assert AboutBlockResponse.model_validate(ab).heading == "What to expect"

    @pytest.mark.parametrize(
        "model", [StepBlockCreateRequest, AboutBlockCreateRequest],
    )
    def test_create_requests_accept_a_heading_and_default_to_none(self, model):
        assert model(block_type="audio").heading is None
        assert model(block_type="audio", heading="Titled").heading == "Titled"

    @pytest.mark.parametrize(
        "model", [StepBlockUpdateRequest, AboutBlockUpdateRequest],
    )
    def test_update_requests_distinguish_absent_from_cleared(self, model):
        # The endpoints apply ``model_dump(exclude_unset=True)``, so an
        # omitted heading must stay omitted — otherwise every autosave
        # of an unrelated field would wipe the heading.
        untouched = model()
        assert "heading" not in untouched.model_dump(exclude_unset=True)

        cleared = model(heading=None)
        assert cleared.model_dump(exclude_unset=True) == {"heading": None}

        set_to = model(heading="Workbook")
        assert set_to.model_dump(exclude_unset=True) == {"heading": "Workbook"}

    def test_a_heading_on_a_non_media_block_is_not_rejected(self):
        # No per-type validation exists for label or caption either, and
        # inventing it here would make the write path refuse payloads the
        # editor may legitimately send while a creator switches a block's
        # type. Renderers simply do not read it for other types.
        assert StepBlockCreateRequest(block_type="text", heading="x").heading == "x"


# ---------------------------------------------------------------------------
# Existing content is unaffected
# ---------------------------------------------------------------------------


class TestPublishedContentIsUnaffected:
    def test_no_existing_row_is_given_a_heading_by_the_migration(self, db, step):
        # Migration 151 adds the column with no server default and no
        # backfill. Anything that wrote a value — a default, a trigger, a
        # backfill added later — would put text on published pages that
        # no creator typed.
        for block_type in MEDIA_TYPES:
            db.add(PathwayStepBlock(
                id=_uid("b"), step_id=step.id, block_type=block_type, position=0,
            ))
        db.flush()
        headings = [
            b.heading
            for b in db.query(PathwayStepBlock).filter(
                PathwayStepBlock.step_id == step.id,
            ).all()
        ]
        assert headings == [None] * len(MEDIA_TYPES)

    def test_the_column_is_nullable_in_the_live_schema(self, db):
        # Reads the database rather than the model, so a migration that
        # drifted from the model is caught.
        from sqlalchemy import text
        rows = db.execute(text(
            """
            SELECT table_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE column_name = 'heading'
              AND table_name IN ('pathway_step_blocks', 'pathway_about_blocks')
            ORDER BY table_name
            """
        )).all()
        assert len(rows) == 2, "heading missing from one of the two block tables"
        for _table, is_nullable, column_default in rows:
            assert is_nullable == "YES"
            assert column_default is None
