"""FC-API-M — a caption longer than 500 characters saves.

The failure
-----------
``pathway_step_blocks.caption`` was ``VARCHAR(500)``. On a media block
that column is the figcaption, and creators use it for what a
figcaption is for in a teaching Pathway: how to do the practice, what
to listen for, a transcript.

An external creator writing instructions for a mindfulness audio
practice went past 500 characters and

    PATCH …/steps/{step_slug}/blocks/{block_id}

returned HTTP 500 — ``psycopg2.errors.StringDataRightTruncation`` out
of ``UPDATE pathway_step_blocks SET caption = …``. Five occurrences in
Sentry.

Nothing in the API checked the length first, so the only limit in the
system was the column and the only feedback was a server error on a
save the creator had every reason to expect to work. Migration 182
widens the column to ``TEXT``, matching ``content`` on the same table.

These tests drive the real endpoints, because the defect lived in the
round trip between a request with no length rule and a column with
one — a service-level test would have missed it entirely.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user, get_verified_creator_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Pathway,
    PathwayStep,
    PathwayStepBlock,
    PathwayType,
    StepContentType,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# The caption from the Sentry report.
#
# Only the heading line is reproduced — it is the identifying detail from
# the issue and is the creator's own wording for a practice title. Her
# actual instructions are private creator content and are deliberately
# not reconstructed here; the body below is filler of the right shape
# and length.
# ---------------------------------------------------------------------------

ORIGINAL_HEADING = "Mindfulness Practice: Letting go of limiting stories"

LONG_CAPTION = (
    f"{ORIGINAL_HEADING}\n\n"
    + "Find a seat where your spine can be long and your shoulders soft. "
    "Let the breath arrive without managing it. When a familiar story "
    "about yourself appears, name it quietly and let it pass. "
    * 6
)

assert len(LONG_CAPTION) > 500, "the regression fixture must exceed the old limit"


@pytest.fixture
def creator_client(db, make_user, make_space):
    """An authenticated creator, their Collective, a Pathway and a Step.

    Both creator dependencies are overridden: the block routes use
    ``get_verified_creator_user`` and the list route uses
    ``get_creator_user``, and a test that overrode only one would 401
    on half the endpoints.
    """
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    pathway = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Daring Heart", status="active", access_type="included",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy", currency="AUD",
    )
    db.add(pathway)
    db.flush()

    step = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id,
        slug=f"st-{uuid.uuid4().hex[:8]}",
        title="Lesson 3: Rewriting Your Story for Positive Change",
        content_type=StepContentType.text, position=0,
    )
    db.add(step)
    db.flush()

    app.dependency_overrides[get_verified_creator_user] = lambda: creator
    app.dependency_overrides[get_creator_user] = lambda: creator
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)

    base = (
        f"/api/creator/spaces/{space.slug}/pathways/{pathway.slug}"
        f"/steps/{step.slug}/blocks"
    )
    yield {
        "client": client, "base": base, "creator": creator,
        "space": space, "pathway": pathway, "step": step,
    }

    app.dependency_overrides.pop(get_verified_creator_user, None)
    app.dependency_overrides.pop(get_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


def _create(ctx, **fields):
    payload = {"block_type": "audio", **fields}
    return ctx["client"].post(ctx["base"], json=payload)


# ---------------------------------------------------------------------------
# 1. The original failure
# ---------------------------------------------------------------------------


class TestTheOriginalFailure:
    def test_updating_a_block_with_a_long_caption_succeeds(self, db, ctx_update):
        """The exact shape of FC-API-M: an existing audio block whose
        caption is replaced with practice instructions longer than the
        old column allowed."""
        ctx, block_id = ctx_update

        r = ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"caption": LONG_CAPTION},
        )
        assert r.status_code == 200, r.text
        assert r.json()["caption"] == LONG_CAPTION

    def test_the_whole_caption_is_stored_not_a_prefix(self, db, ctx_update):
        """Truncation would have been the other bad outcome — a 200 with
        the end of somebody's instructions missing."""
        ctx, block_id = ctx_update
        ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"caption": LONG_CAPTION},
        )

        block = db.get(PathwayStepBlock, block_id)
        db.refresh(block)
        assert block.caption == LONG_CAPTION
        assert len(block.caption) == len(LONG_CAPTION)
        assert block.caption.startswith(ORIGINAL_HEADING)
        assert block.caption.endswith(LONG_CAPTION[-40:])

    def test_it_reads_back_complete_through_the_api(self, ctx_update):
        ctx, block_id = ctx_update
        ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"caption": LONG_CAPTION},
        )

        listed = ctx["client"].get(ctx["base"])
        assert listed.status_code == 200, listed.text
        block = next(b for b in listed.json() if b["id"] == block_id)
        assert block["caption"] == LONG_CAPTION


@pytest.fixture
def ctx_update(creator_client):
    """A saved audio block, ready to be updated — the state the creator
    was in when the error happened."""
    r = _create(
        creator_client,
        heading="Mindfulness Practice: Letting go of limiting stories",
        caption="A short caption, as first saved.",
    )
    assert r.status_code in (200, 201), r.text
    return creator_client, r.json()["id"]


# ---------------------------------------------------------------------------
# 2. Creating, and the lengths either side of the old limit
# ---------------------------------------------------------------------------


class TestCreatingBlocksWithCaptions:
    def test_a_short_caption_still_works(self, creator_client):
        r = _create(creator_client, caption="Listen before Lesson 4.")
        assert r.status_code in (200, 201), r.text
        assert r.json()["caption"] == "Listen before Lesson 4."

    @pytest.mark.parametrize("length", [499, 500, 501, 2000, 20000])
    def test_captions_of_any_length_are_accepted(self, db, creator_client, length):
        """501 is the one that used to fail. The others are here so a
        future narrowing shows up as a boundary rather than as a single
        broken case."""
        caption = "c" * length
        r = _create(creator_client, caption=caption)
        assert r.status_code in (200, 201), f"{length}: {r.text}"
        assert len(r.json()["caption"]) == length

        block = db.get(PathwayStepBlock, r.json()["id"])
        assert len(block.caption) == length

    def test_a_multiline_caption_keeps_its_line_breaks(self, db, creator_client):
        """Plain text, not markdown — but the newlines the creator typed
        are part of what they wrote and must survive the round trip, or
        a transcript comes back as one paragraph."""
        caption = (
            "Before you begin:\n"
            "• Find a quiet room.\n"
            "• Sit upright.\n"
            "\n"
            "During the practice:\n"
            "Let each thought pass without following it.\n"
        ) * 12
        assert len(caption) > 500

        r = _create(creator_client, caption=caption)
        assert r.status_code in (200, 201), r.text

        block = db.get(PathwayStepBlock, r.json()["id"])
        assert block.caption == caption
        assert block.caption.count("\n") == caption.count("\n")
        assert "\n\n" in block.caption

    def test_an_absent_caption_is_still_null(self, db, creator_client):
        r = _create(creator_client)
        assert r.status_code in (200, 201), r.text
        block = db.get(PathwayStepBlock, r.json()["id"])
        assert block.caption is None

    def test_an_empty_caption_is_stored_as_given(self, db, creator_client):
        """Nullability and emptiness are unchanged by this migration —
        whatever the editor sent before, it sends and stores now."""
        r = _create(creator_client, caption="")
        assert r.status_code in (200, 201), r.text
        block = db.get(PathwayStepBlock, r.json()["id"])
        assert block.caption == ""

    def test_clearing_a_caption_to_null_still_works(self, db, ctx_update):
        """The route applies ``model_dump(exclude_unset=True)``, so an
        explicitly sent ``null`` clears the caption while an omitted
        field leaves it alone. Both halves pinned — the two are easy to
        confuse and the distinction is what lets a creator delete a
        caption without wiping the rest of the block."""
        ctx, block_id = ctx_update
        r = ctx["client"].patch(f"{ctx['base']}/{block_id}", json={"caption": None})
        assert r.status_code == 200, r.text
        block = db.get(PathwayStepBlock, block_id)
        db.refresh(block)
        assert block.caption is None

    def test_a_long_caption_can_be_cleared_again(self, db, ctx_update):
        ctx, block_id = ctx_update
        ctx["client"].patch(f"{ctx['base']}/{block_id}", json={"caption": LONG_CAPTION})
        r = ctx["client"].patch(f"{ctx['base']}/{block_id}", json={"caption": None})
        assert r.status_code == 200, r.text
        block = db.get(PathwayStepBlock, block_id)
        db.refresh(block)
        assert block.caption is None


# ---------------------------------------------------------------------------
# 3. Existing content and unrelated fields
# ---------------------------------------------------------------------------


class TestNothingElseMoved:
    def test_an_existing_short_caption_is_untouched_by_other_edits(
        self, db, ctx_update,
    ):
        ctx, block_id = ctx_update
        before = db.get(PathwayStepBlock, block_id).caption

        r = ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"heading": "A new heading"},
        )
        assert r.status_code == 200, r.text

        block = db.get(PathwayStepBlock, block_id)
        db.refresh(block)
        assert block.caption == before
        assert block.heading == "A new heading"

    def test_a_long_caption_does_not_disturb_the_other_fields(
        self, db, creator_client,
    ):
        r = _create(
            creator_client,
            heading="Morning practice",
            caption=LONG_CAPTION,
            container_style="teal",
            position=3,
        )
        assert r.status_code in (200, 201), r.text

        block = db.get(PathwayStepBlock, r.json()["id"])
        assert block.caption == LONG_CAPTION
        assert block.heading == "Morning practice"
        assert block.container_style == "teal"
        assert block.position == 3
        assert str(
            block.block_type.value if hasattr(block.block_type, "value")
            else block.block_type
        ) == "audio"

    def test_the_coloured_container_survives_a_long_caption(
        self, db, ctx_update,
    ):
        """The optional coloured wrapper is a separate column and must
        keep working whether or not the caption is long."""
        ctx, block_id = ctx_update
        ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"container_style": "rose"},
        )
        r = ctx["client"].patch(
            f"{ctx['base']}/{block_id}", json={"caption": LONG_CAPTION},
        )
        assert r.status_code == 200, r.text

        block = db.get(PathwayStepBlock, block_id)
        db.refresh(block)
        assert block.container_style == "rose"
        assert block.caption == LONG_CAPTION

    @pytest.mark.parametrize(
        "block_type", ["audio", "video_embed", "image", "link", "embed"],
    )
    def test_every_block_type_that_uses_caption_accepts_a_long_one(
        self, creator_client, block_type,
    ):
        """``caption`` is shared across block types. The column was the
        limit, so widening it has to work for all of them — not only
        the one in the Sentry report."""
        payload = {"block_type": block_type, "caption": LONG_CAPTION}
        if block_type == "link":
            payload["embed_url"] = "https://example.com/a-resource"
        elif block_type in ("embed", "video_embed"):
            # ``embed`` and ``video_embed`` validate the host against the
            # allowlist, so an arbitrary URL is a 400 for reasons that
            # have nothing to do with caption length.
            payload["embed_url"] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        r = creator_client["client"].post(creator_client["base"], json=payload)
        assert r.status_code in (200, 201), f"{block_type}: {r.text}"
        assert r.json()["caption"] == LONG_CAPTION


# ---------------------------------------------------------------------------
# 4. The guards that must not have moved
# ---------------------------------------------------------------------------


class TestPermissionsAreUnchanged:
    def test_the_write_routes_still_require_a_verified_creator(self):
        """A longer column must not come with a wider door. Asserted on
        the dependencies, because the fixtures override them."""
        paths = {
            "/api/creator/spaces/{slug}/pathways/{pathway_slug}/steps/"
            "{step_slug}/blocks",
            "/api/creator/spaces/{slug}/pathways/{pathway_slug}/steps/"
            "{step_slug}/blocks/{block_id}",
        }
        checked = 0
        for route in app.routes:
            if getattr(route, "path", "") not in paths:
                continue
            names = [d.call.__name__ for d in route.dependant.dependencies]
            methods = route.methods or set()
            if methods & {"POST", "PATCH", "DELETE"}:
                assert "get_verified_creator_user" in names, (
                    f"{methods} {route.path}: {names}"
                )
                checked += 1
        assert checked >= 3, f"expected the write routes, found {checked}"

    def test_another_creators_collective_is_refused(
        self, db, creator_client, make_user, make_space,
    ):
        """``_get_managed_space`` still gates every one of these routes.
        Driven with a real second Collective and a creator who does not
        manage it."""
        outsider = make_user(role="creator")
        app.dependency_overrides[get_verified_creator_user] = lambda: outsider

        r = creator_client["client"].post(
            creator_client["base"],
            json={"block_type": "audio", "caption": LONG_CAPTION},
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 5. The column itself
# ---------------------------------------------------------------------------


class TestTheColumn:
    def test_caption_is_text_with_no_length_limit(self, db):
        """Read from the live database rather than the model, so a
        migration that was written but not applied fails here."""
        from sqlalchemy import text

        row = db.execute(text(
            "SELECT data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'pathway_step_blocks' "
            "AND column_name = 'caption'"
        )).first()
        assert row is not None, "pathway_step_blocks.caption is missing"
        data_type, max_length, is_nullable = row
        assert data_type == "text", data_type
        assert max_length is None, max_length
        # Nullability deliberately unchanged: blocks with no caption
        # must keep reading as "no caption".
        assert is_nullable == "YES"

    def test_the_neighbouring_columns_were_not_widened_too(self, db):
        """The migration alters one column. ``label`` and ``heading``
        keep their own limits — see the report's note about the editor
        controls that do not cap ``label``."""
        from sqlalchemy import text

        rows = dict(db.execute(text(
            "SELECT column_name, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_name = 'pathway_step_blocks'"
        )).all())
        assert rows["label"] == 300
        assert rows["heading"] == 300
        assert rows["embed_url"] == 1000
        assert rows["container_style"] == 32
        assert rows["content"] is None
