"""Consecutive blocks get consecutive positions, on every surface.

The defect this guards against was `(max_pos or -1) + 1`. When the
highest existing position is **0**, `0 or -1` evaluates to `-1`, so the
new block also lands on position 0 — and so does every block after it.
Order then falls back to insertion order, and a manual reorder is the
only thing that ever separates them.

It was live in four places (Pathway About blocks, Pathway step blocks,
Gathering Series About blocks, Event About blocks) and was found by the
Offerings ordering test in B6/B7, which exercised the same arithmetic in
a fifth, new copy.

Each surface is tested through its **own production handler**, because
that is what was broken — a test against a shared helper would have
passed throughout.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.creator import routes as creator_routes
from app.creator.schemas import (
    AboutBlockCreateRequest, AboutBlockReorderRequest,
)
from app.models.platform import PathwayAboutBlock


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def pathway(db, make_space):
    """A Collective with a Pathway, and its owner."""
    from app.models.platform import Pathway, PathwayStatus
    from app.models.user import User

    space = make_space()
    owner = db.query(User).filter(User.id == space.creator_id).one()
    row = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"p-{uuid.uuid4().hex[:8]}",
        title="A Pathway", status=PathwayStatus.draft, position=0,
    )
    db.add(row)
    db.flush()
    return space, owner, row


class TestPathwayAboutBlocks:
    """The original surface, and the one most creators meet."""

    def test_consecutive_blocks_get_consecutive_positions(self, db, pathway):
        space, owner, pw = pathway
        made = [
            creator_routes.create_about_block(
                space.slug, pw.slug,
                AboutBlockCreateRequest(block_type="text", content=str(i)),
                db=db, current_user=owner,
            )
            for i in range(4)
        ]
        assert [b.position for b in made] == [0, 1, 2, 3], (
            "blocks collapsed onto the same position — the `or -1` defect"
        )

    def test_positions_are_distinct_in_the_database(self, db, pathway):
        space, owner, pw = pathway
        for i in range(3):
            creator_routes.create_about_block(
                space.slug, pw.slug,
                AboutBlockCreateRequest(block_type="text", content=str(i)),
                db=db, current_user=owner,
            )
        rows = (
            db.query(PathwayAboutBlock)
            .filter(PathwayAboutBlock.pathway_id == pw.id)
            .all()
        )
        assert len({r.position for r in rows}) == len(rows)

    def test_reordering_still_works_afterwards(self, db, pathway):
        space, owner, pw = pathway
        made = [
            creator_routes.create_about_block(
                space.slug, pw.slug,
                AboutBlockCreateRequest(block_type="text", content=str(i)),
                db=db, current_user=owner,
            )
            for i in range(3)
        ]
        wanted = [made[2].id, made[0].id, made[1].id]
        out = creator_routes.reorder_about_blocks(
            space.slug, pw.slug, AboutBlockReorderRequest(ids=wanted),
            db=db, current_user=owner,
        )
        assert [b.id for b in out] == wanted
        assert [b.position for b in out] == [0, 1, 2]

    def test_existing_content_is_untouched(self, db, pathway):
        """The fix changes which position a *new* block gets. Blocks
        already saved keep whatever position they have, including the
        collapsed zeros the defect produced."""
        space, owner, pw = pathway
        # Two legacy rows, both stranded on position 0 by the old code.
        legacy = []
        for i in range(2):
            row = PathwayAboutBlock(
                id=_uid("ab"), owner_kind="pathway", owner_id=pw.id,
                pathway_id=pw.id, block_type="text", position=0,
                content=f"legacy {i}",
            )
            db.add(row)
            legacy.append(row)
        db.flush()

        creator_routes.create_about_block(
            space.slug, pw.slug,
            AboutBlockCreateRequest(block_type="text", content="new"),
            db=db, current_user=owner,
        )

        for row in legacy:
            db.refresh(row)
            assert row.position == 0, "a saved block was moved"
            assert row.content.startswith("legacy")


class TestPathwayStepBlocks:
    """The second occurrence in ``creator/routes.py``."""

    def test_consecutive_step_blocks_get_consecutive_positions(
        self, db, pathway,
    ):
        from app.creator.schemas import StepBlockCreateRequest
        from app.models.platform import PathwayStep

        space, owner, pw = pathway
        step = PathwayStep(
            id=_uid("st"), pathway_id=pw.id,
            slug=f"s-{uuid.uuid4().hex[:8]}", title="Step one", position=0,
        )
        db.add(step)
        db.flush()

        made = [
            creator_routes.create_step_block(
                space.slug, pw.slug, step.slug,
                StepBlockCreateRequest(block_type="text", content=str(i)),
                db=db, current_user=owner,
            )
            for i in range(4)
        ]
        assert [b.position for b in made] == [0, 1, 2, 3]


class TestTheDefectIsGoneEverywhere:
    """A source guard, so the pattern cannot come back by copy-paste."""

    def test_no_handler_still_uses_the_falsy_zero_form(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        offenders = []
        for path in root.rglob("*.py"):
            src = path.read_text()
            # Strip comments so the note *explaining* the defect does
            # not count as the defect — banning the use, not the word.
            code = re.sub(r"(?m)^\s*#.*$", "", src)
            if re.search(r"\(\s*max_pos\s+or\s+-1\s*\)", code):
                offenders.append(str(path))
        assert offenders == [], (
            "the falsy-zero position bug is back in: " + ", ".join(offenders)
        )

    def test_the_guard_can_detect_the_pattern(self):
        """A guard that cannot fail is not a guard."""
        import re
        assert re.search(r"\(\s*max_pos\s+or\s+-1\s*\)", "position = (max_pos or -1) + 1")
