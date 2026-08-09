"""Container Style persistence — validator + end-to-end round-trip.

The frontend's shared colour picker emits three storage flavours for a
block's ``container_style``:

  * ``palette:<role>``  (palette-driven, resolved at render time)
  * ``custom:#RRGGBB``  (literal hex, preserved across palette changes)
  * legacy fixed keys   (teal|gold|blue|rose|sage|grey|lilac|orange)

A prior version of ``_validate_container_style`` accepted only the
legacy set, so palette-driven and custom-hex selections were silently
rejected by Pydantic. The frontend autosave swallows the resulting
422 and the block never persists the new value — so previews looked
right but reloads reverted to no container.

These tests lock the validator's acceptance shape and the block
round-trip (POST + PATCH + response) so the regression can't recur.
"""

from __future__ import annotations

import uuid

import pytest

from app.creator.routes import create_step_block, update_step_block
from app.creator.schemas import (
    StepBlockCreateRequest,
    StepBlockUpdateRequest,
    _validate_container_style,
)
from app.models.platform import (
    Pathway,
    PathwayStep,
    PathwayType,
    StepContentType,
)


# ---------------------------------------------------------------------------
# Validator — accepts the three storage flavours; rejects garbage.
# ---------------------------------------------------------------------------


class TestValidator:
    def test_none_and_empty_return_none(self):
        assert _validate_container_style(None) is None
        assert _validate_container_style("") is None

    @pytest.mark.parametrize("v", [
        "teal", "gold", "blue", "rose", "sage", "grey", "lilac", "orange",
    ])
    def test_legacy_keys_pass_through(self, v):
        assert _validate_container_style(v) == v

    @pytest.mark.parametrize("role", ["primary", "secondary", "accent", "background"])
    def test_palette_role_pass_through(self, role):
        v = f"palette:{role}"
        assert _validate_container_style(v) == v

    @pytest.mark.parametrize("hex_", [
        "#3A6B7A", "#000000", "#FFFFFF", "#abcdef", "#ABCDEF",
    ])
    def test_custom_hex_pass_through(self, hex_):
        v = f"custom:{hex_}"
        assert _validate_container_style(v) == v

    def test_unknown_palette_role_rejected(self):
        with pytest.raises(ValueError):
            _validate_container_style("palette:banana")

    def test_short_custom_hex_rejected(self):
        with pytest.raises(ValueError):
            _validate_container_style("custom:#abc")

    def test_missing_hash_rejected(self):
        with pytest.raises(ValueError):
            _validate_container_style("custom:abcdef")

    def test_plain_hex_without_custom_prefix_rejected(self):
        with pytest.raises(ValueError):
            _validate_container_style("#3A6B7A")

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            _validate_container_style("teal-strong")
        with pytest.raises(ValueError):
            _validate_container_style("random_value")


# ---------------------------------------------------------------------------
# Schema request objects — same acceptance shape as the validator.
# ---------------------------------------------------------------------------


class TestSchema:
    def test_create_request_accepts_palette_role(self):
        body = StepBlockCreateRequest(
            block_type="text",
            container_style="palette:primary",
        )
        assert body.container_style == "palette:primary"

    def test_create_request_accepts_custom_hex(self):
        body = StepBlockCreateRequest(
            block_type="text",
            container_style="custom:#3A6B7A",
        )
        assert body.container_style == "custom:#3A6B7A"

    def test_create_request_accepts_legacy_key(self):
        body = StepBlockCreateRequest(
            block_type="text",
            container_style="teal",
        )
        assert body.container_style == "teal"

    def test_update_request_accepts_palette_role(self):
        body = StepBlockUpdateRequest(container_style="palette:secondary")
        assert body.container_style == "palette:secondary"

    def test_create_request_rejects_unknown_palette_role(self):
        with pytest.raises(ValueError):
            StepBlockCreateRequest(
                block_type="text",
                container_style="palette:banana",
            )


# ---------------------------------------------------------------------------
# End-to-end round-trip — POST creates a block with the value; PATCH
# updates it; the response carries whatever the model has.
# ---------------------------------------------------------------------------


def _pathway_and_step(db, space) -> PathwayStep:
    p = Pathway(
        id=f"pw_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="p",
        status="active",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    s = PathwayStep(
        id=f"pst_{uuid.uuid4().hex[:12]}",
        pathway_id=p.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title="s",
        position=0,
        content_type=StepContentType.text,
    )
    db.add(s)
    db.flush()
    return s


class TestRoundTrip:
    def test_palette_role_survives_create(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="text",
                content="hello",
                container_style="palette:primary",
            ),
            db=db, current_user=creator,
        )
        assert block.container_style == "palette:primary"

    def test_custom_hex_survives_create(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="text",
                content="hello",
                container_style="custom:#3A6B7A",
            ),
            db=db, current_user=creator,
        )
        assert block.container_style == "custom:#3A6B7A"

    def test_patch_updates_container_style(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="text",
                content="hello",
                container_style=None,
            ),
            db=db, current_user=creator,
        )
        assert block.container_style is None

        updated = update_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            block_id=block.id,
            body=StepBlockUpdateRequest(container_style="palette:primary"),
            db=db, current_user=creator,
        )
        assert updated.container_style == "palette:primary"

    def test_no_container_block_stays_no_container(self, db, make_user, make_space):
        # Regression guard — the fix for the palette flavours must not
        # touch existing blocks that have never set a container style.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="text",
                content="hello",
            ),
            db=db, current_user=creator,
        )
        assert block.container_style is None
