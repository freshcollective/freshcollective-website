"""Media usage detection reaches images inside columns blocks.

Round 2, item 1. Columns blocks keep their cells as a JSON envelope in
``content`` rather than in real columns, so an image placed in a column
has no ``media_asset_id`` for the usage endpoint to find. Before this,
``GET /spaces/{slug}/media/{id}/usage`` would tell a creator an image
was used nowhere while it sat on a published step — and that endpoint
exists precisely to be trusted before archiving something.

Two failure modes are worth more than the happy path, and most of what
follows is about them.

*Silence.* Reporting no references is the dangerous answer, because it
is the one a creator acts on. So there are cases for an image in a
step column, in an About page column, in several columns at once, and
in a column parked by a narrower layout.

*Noise.* The query cannot simply look for the id inside ``content``: a
creator who typed an asset id into a paragraph would be told the image
is in use on a step that merely mentions it, and they would then not
archive something they meant to. So the envelope is parsed, and a bare
textual mention must report nothing.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_columns_media_usage.py
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.creator._columns_media import columns_image_asset_columns
from app.creator.routes import get_media_usage
from app.models.platform import (
    CreatorMediaAsset,
    Pathway,
    PathwayAboutBlock,
    PathwayStep,
    PathwayStepBlock,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def columns_content(*cells: dict, variant: str = "50-50") -> str:
    """A columns envelope in the shape the frontend writes."""
    return json.dumps({
        "layout": {"kind": "columns", "variant": variant},
        "cells": list(cells),
    })


def text_cell(html: str = "<p>Words</p>") -> dict:
    return {"content": html}


def image_cell(asset_id: str | None, url: str = "/uploads/media/s/p.jpg") -> dict:
    return {
        "kind": "image",
        "content": "",
        "image": {"assetId": asset_id, "url": url, "alt": None, "caption": None},
    }


# ---------------------------------------------------------------------------
# The parser, on its own
# ---------------------------------------------------------------------------


class TestTheEnvelopeParser:
    def test_it_finds_an_image_by_column_number(self):
        content = columns_content(text_cell(), image_cell("a1"))
        assert columns_image_asset_columns(content, "a1") == [2]

    def test_it_finds_every_column_holding_the_asset(self):
        content = columns_content(
            image_cell("a1"), text_cell(), image_cell("a1"),
            variant="33-33-33",
        )
        assert columns_image_asset_columns(content, "a1") == [1, 3]

    def test_it_ignores_a_different_asset(self):
        content = columns_content(image_cell("other"), text_cell())
        assert columns_image_asset_columns(content, "a1") == []

    def test_a_textual_mention_is_not_a_reference(self):
        # The whole reason this parses rather than pattern-matches.
        content = columns_content(text_cell("<p>see asset a1 for this</p>"), text_cell())
        assert columns_image_asset_columns(content, "a1") == []

    def test_an_image_parked_on_a_text_cell_still_counts(self):
        # Switching a column back to Text keeps the image, and it
        # returns if the creator switches again. Archiving the asset
        # would break it, so it is still a reference.
        parked = {"content": "<p>Words</p>",
                  "image": {"assetId": "a1", "url": "/uploads/media/s/p.jpg"}}
        assert columns_image_asset_columns(columns_content(parked, text_cell()), "a1") == [1]

    def test_a_column_parked_by_a_narrower_layout_still_counts(self):
        # Four cells stored, two shown. The third is coming back the
        # moment the layout widens.
        content = columns_content(
            text_cell(), text_cell(), image_cell("a1"), text_cell(),
            variant="50-50",
        )
        assert columns_image_asset_columns(content, "a1") == [3]

    @pytest.mark.parametrize("content", [
        None, "", "   ", "not json", "null", "[]", "{}",
        '{"layout":{"kind":"cards"},"cells":[{"image":{"assetId":"a1"}}]}',
        '{"layout":{"kind":"columns","variant":"50-50"}}',
        '{"layout":{"kind":"columns","variant":"50-50"},"cells":"nope"}',
        '{"layout":{"kind":"columns","variant":"50-50"},"cells":[null,7,"x"]}',
        '{"cells":[{"image":{"assetId":"a1"}}]}',
    ])
    def test_it_never_raises_on_anything_unexpected(self, content):
        assert columns_image_asset_columns(content, "a1") == []

    def test_an_empty_asset_id_matches_nothing(self):
        content = columns_content(image_cell(None), text_cell())
        assert columns_image_asset_columns(content, "") == []


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def collective(db, make_user, make_space):
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    pathway = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status="active",
    )
    db.add(pathway)
    db.flush()
    step = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id, slug=f"st-{uuid.uuid4().hex[:8]}",
        title="A Step", position=0,
    )
    db.add(step)
    asset = CreatorMediaAsset(
        id=_uid("ma"), space_id=space.id, uploaded_by_user_id=creator.id,
        title="Morning light", original_filename="one.jpg",
        stored_filename="one.jpg", storage_path="media/one.jpg",
        file_url="/uploads/media/s/one.jpg", mime_type="image/jpeg",
        media_type="image", file_size_bytes=1234, extension="jpg",
        status="active",
    )
    db.add(asset)
    db.flush()
    return {
        "creator": creator, "space": space,
        "pathway": pathway, "step": step, "asset": asset,
    }


def usage(db, collective):
    return get_media_usage(
        slug=collective["space"].slug,
        media_id=collective["asset"].id,
        db=db,
        current_user=collective["creator"],
    )


def add_step_columns(db, collective, content: str):
    block = PathwayStepBlock(
        id=_uid("b"), step_id=collective["step"].id,
        block_type="columns", position=0, content=content,
    )
    db.add(block)
    db.flush()
    return block


def add_about_columns(db, collective, content: str):
    block = PathwayAboutBlock(
        id=_uid("ab"), pathway_id=collective["pathway"].id,
        block_type="columns", position=0, content=content,
    )
    db.add(block)
    db.flush()
    return block


class TestUsageInsideColumns:
    def test_an_unused_asset_reports_nothing(self, db, collective):
        assert usage(db, collective).references == []

    def test_an_image_in_a_step_column_is_reported(self, db, collective):
        add_step_columns(db, collective, columns_content(
            text_cell(), image_cell(collective["asset"].id),
        ))
        refs = usage(db, collective).references
        assert len(refs) == 1
        assert refs[0].kind == "step_block_columns"
        assert refs[0].pathway_slug == collective["pathway"].slug
        assert refs[0].step_slug == collective["step"].slug
        assert "column 2" in refs[0].label

    def test_an_image_in_an_about_page_column_is_reported(self, db, collective):
        add_about_columns(db, collective, columns_content(
            image_cell(collective["asset"].id), text_cell(),
        ))
        refs = usage(db, collective).references
        assert len(refs) == 1
        assert refs[0].kind == "about_block_columns"
        assert refs[0].pathway_slug == collective["pathway"].slug
        assert refs[0].step_id is None
        assert "about page" in refs[0].label
        assert "column 1" in refs[0].label

    def test_both_surfaces_are_reported_together(self, db, collective):
        add_step_columns(db, collective, columns_content(
            image_cell(collective["asset"].id), text_cell(),
        ))
        add_about_columns(db, collective, columns_content(
            text_cell(), image_cell(collective["asset"].id),
        ))
        kinds = sorted(r.kind for r in usage(db, collective).references)
        assert kinds == ["about_block_columns", "step_block_columns"]

    def test_one_block_using_the_image_twice_reports_both_columns(self, db, collective):
        add_step_columns(db, collective, columns_content(
            image_cell(collective["asset"].id), image_cell(collective["asset"].id),
        ))
        refs = usage(db, collective).references
        assert len(refs) == 2
        assert sorted(r.label for r in refs) == [
            f"A Pathway — A Step (columns · column {n})" for n in (1, 2)
        ]

    def test_a_textual_mention_is_not_reported(self, db, collective):
        # The id appears in the content, so the SQL prefilter matches —
        # and the parser must then reject it. Without this the creator
        # is told an image is in use where it is not, and leaves clutter
        # in their library forever.
        add_step_columns(db, collective, columns_content(
            text_cell(f"<p>the old picture was {collective['asset'].id}</p>"),
            text_cell(),
        ))
        assert usage(db, collective).references == []

    def test_a_text_only_columns_block_is_not_reported(self, db, collective):
        add_step_columns(db, collective, columns_content(text_cell(), text_cell()))
        assert usage(db, collective).references == []

    def test_a_column_image_in_another_collective_is_not_reported(self, db, collective,
                                                                  make_user, make_space):
        other_creator = make_user(role="creator")
        other_space = make_space(creator=other_creator)
        other_pathway = Pathway(
            id=_uid("pw"), space_id=other_space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}", title="Theirs", status="active",
        )
        db.add(other_pathway)
        db.flush()
        other_step = PathwayStep(
            id=_uid("st"), pathway_id=other_pathway.id,
            slug=f"st-{uuid.uuid4().hex[:8]}", title="Their Step", position=0,
        )
        db.add(other_step)
        db.flush()
        db.add(PathwayStepBlock(
            id=_uid("b"), step_id=other_step.id, block_type="columns", position=0,
            content=columns_content(image_cell(collective["asset"].id), text_cell()),
        ))
        db.flush()
        # Cross-collective references must not leak either way.
        assert usage(db, collective).references == []

    def test_another_block_type_mentioning_the_id_is_not_reported(self, db, collective):
        # Belt and braces behind the block_type prefilter: even if a
        # text block reaches the parser, it has no columns
        # envelope, so it cannot be mistaken for a reference. (The
        # prefilter is for cost, not correctness — removing it changes
        # nothing an assertion here could observe.)
        db.add(PathwayStepBlock(
            id=_uid("b"), step_id=collective["step"].id, block_type="text",
            position=2, content=f"<p>mentions {collective['asset'].id}</p>",
        ))
        db.flush()
        assert usage(db, collective).references == []

    def test_a_corrupt_columns_block_does_not_break_the_endpoint(self, db, collective):
        add_step_columns(db, collective, f'{{"broken": "{collective["asset"].id}"')
        assert usage(db, collective).references == []

    def test_the_existing_media_asset_id_checks_still_work(self, db, collective):
        # The columns scan is additive; the original query must be
        # untouched.
        db.add(PathwayStepBlock(
            id=_uid("b"), step_id=collective["step"].id, block_type="image",
            position=1, media_asset_id=collective["asset"].id,
        ))
        db.add(PathwayAboutBlock(
            id=_uid("ab"), pathway_id=collective["pathway"].id, block_type="image",
            position=1, media_asset_id=collective["asset"].id,
        ))
        db.flush()
        kinds = sorted(r.kind for r in usage(db, collective).references)
        assert kinds == ["about_block_image", "step_block_image"]

    def test_block_and_column_references_are_reported_together(self, db, collective):
        db.add(PathwayStepBlock(
            id=_uid("b"), step_id=collective["step"].id, block_type="image",
            position=1, media_asset_id=collective["asset"].id,
        ))
        db.flush()
        add_step_columns(db, collective, columns_content(
            text_cell(), image_cell(collective["asset"].id),
        ))
        kinds = sorted(r.kind for r in usage(db, collective).references)
        assert kinds == ["step_block_columns", "step_block_image"]
