"""CRUD tests for Event About blocks (M1 refinement — MF2).

Extends the polymorphic ``pathway_about_blocks`` table with
``owner_kind='event'``. Reuses every existing schema + validator +
renderer without a code-path split.

Uses direct route-function invocation (rather than TestClient) so
the SAVEPOINT-scoped ``db`` fixture is visible to the handler —
same pattern ``tests/test_checkout_unified.py`` uses.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.creator._event_about_routes import (
    create_event_about_block,
    delete_event_about_block,
    list_event_about_blocks,
    reorder_event_about_blocks,
    update_event_about_block,
)
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockUpdateRequest,
)
from app.models.platform import Event, PathwayAboutBlock


def _make_event(db: Session, space, *, title: str = "Session One"):
    ev = Event(
        id=f"ev_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        created_by_id=space.creator_id,
        title=title,
        starts_at="2027-01-01T10:00:00",
        ends_at="2027-01-01T11:00:00",
        location_type="zoom",
        is_published=True,
        status="active",
        requires_booking=False,
        capacity=20,
        booking_access_type="included_with_collective",
        gathering_type="workshop",
        attendance_format="online",
    )
    db.add(ev)
    db.flush()
    return ev


class TestEventAboutBlockCRUD:
    def test_create_list_update_reorder_delete_roundtrip(
        self, db: Session, make_user, make_space,
    ) -> None:
        # Fetch the auto-created creator user for the fixture Space
        # via its ``creator_id`` so subsequent auth-scoped calls see
        # the same person.
        space = make_space()
        from app.models.user import User
        creator = db.query(User).filter(User.id == space.creator_id).first()
        event = _make_event(db, space)

        # Empty initially.
        listed = list_event_about_blocks(
            slug=space.slug, event_id=event.id, db=db, current_user=creator,
        )
        assert listed == []

        # Create four different block types.
        ids: list[str] = []
        for kind in ("text", "callout", "image", "heading"):
            body = AboutBlockCreateRequest(block_type=kind)
            block = create_event_about_block(
                slug=space.slug, event_id=event.id, body=body,
                db=db, current_user=creator,
            )
            assert block.block_type.value == kind if hasattr(block.block_type, "value") else block.block_type == kind
            assert block.owner_kind == "event"
            assert block.owner_id == event.id
            # Event-owned blocks NEVER set ``pathway_id``.
            assert block.pathway_id is None
            ids.append(block.id)

        # List returns them in insertion order.
        listed = list_event_about_blocks(
            slug=space.slug, event_id=event.id, db=db, current_user=creator,
        )
        assert [b.id for b in listed] == ids

        # Update the first block's content.
        updated = update_event_about_block(
            slug=space.slug, event_id=event.id, block_id=ids[0],
            body=AboutBlockUpdateRequest(content="hello world"),
            db=db, current_user=creator,
        )
        assert updated.content == "hello world"

        # Reverse order.
        reordered = reorder_event_about_blocks(
            slug=space.slug, event_id=event.id,
            body=AboutBlockReorderRequest(ids=list(reversed(ids))),
            db=db, current_user=creator,
        )
        assert [b.id for b in reordered] == list(reversed(ids))

        # Delete each.
        for bid in ids:
            delete_event_about_block(
                slug=space.slug, event_id=event.id, block_id=bid,
                db=db, current_user=creator,
            )

        listed = list_event_about_blocks(
            slug=space.slug, event_id=event.id, db=db, current_user=creator,
        )
        assert listed == []

    def test_owner_isolation_across_events(
        self, db: Session, make_user, make_space,
    ) -> None:
        """A block written for Event A must not leak into Event B."""
        space = make_space()
        from app.models.user import User
        creator = db.query(User).filter(User.id == space.creator_id).first()

        ev_a = _make_event(db, space, title="A")
        ev_b = _make_event(db, space, title="B")

        create_event_about_block(
            slug=space.slug, event_id=ev_a.id,
            body=AboutBlockCreateRequest(block_type="text", content="A-only"),
            db=db, current_user=creator,
        )

        b_blocks = list_event_about_blocks(
            slug=space.slug, event_id=ev_b.id, db=db, current_user=creator,
        )
        assert b_blocks == []

        # Direct DB check — the row is scoped by (owner_kind, owner_id).
        rows = (
            db.query(PathwayAboutBlock)
            .filter(
                PathwayAboutBlock.owner_kind == "event",
                PathwayAboutBlock.owner_id == ev_a.id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].pathway_id is None

    def test_404_for_event_in_another_space(
        self, db: Session, make_space,
    ) -> None:
        space_a = make_space()
        space_b = make_space()
        from app.models.user import User
        creator_a = db.query(User).filter(User.id == space_a.creator_id).first()
        # Event lives in space_b.
        ev = _make_event(db, space_b)

        with pytest.raises(HTTPException) as ei:
            list_event_about_blocks(
                slug=space_a.slug, event_id=ev.id,
                db=db, current_user=creator_a,
            )
        assert ei.value.status_code == 404


class TestMemberSideEventAboutBlocks:
    def test_member_read_of_public_event(
        self, db: Session, make_space,
    ) -> None:
        from app.models.user import User
        from app.spaces._series_member_routes import get_member_event_about_blocks

        space = make_space()
        creator = db.query(User).filter(User.id == space.creator_id).first()
        event = _make_event(db, space)
        event.is_public = True
        db.flush()

        create_event_about_block(
            slug=space.slug, event_id=event.id,
            body=AboutBlockCreateRequest(block_type="text", content="member sees this"),
            db=db, current_user=creator,
        )

        # Anonymous read — public event allows it.
        blocks = get_member_event_about_blocks(
            slug=space.slug, event_id=event.id,
            db=db, current_user=None,
        )
        assert len(blocks) == 1
        assert blocks[0].content == "member sees this"
        assert blocks[0].owner_kind == "event"

    def test_member_read_gated_for_private_event(
        self, db: Session, make_space,
    ) -> None:
        from app.spaces._series_member_routes import get_member_event_about_blocks

        space = make_space()
        event = _make_event(db, space)
        event.is_public = False
        db.flush()

        with pytest.raises(HTTPException) as ei:
            get_member_event_about_blocks(
                slug=space.slug, event_id=event.id,
                db=db, current_user=None,
            )
        assert ei.value.status_code == 404
