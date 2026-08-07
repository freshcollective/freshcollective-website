"""Tests for the /api/admin/comms/events surface (Milestone 1).

Route functions are called directly rather than through TestClient —
matching the pattern in ``test_admin_periodic_endpoints.py`` — so we
don't need to stand up the auth stack for this narrow API test.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.comms import Source, emit
from app.comms.routes import get_event, list_events, list_registry


class TestListEvents:
    def test_returns_recent_events_ordered_desc(self, db, make_user):
        admin = make_user(role="admin")
        actor = make_user()

        e1 = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        e2 = emit(
            db,
            event_type="pathway.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        db.flush()

        assert e1 is not None and e2 is not None

        resp = list_events(db=db, _=admin)  # type: ignore[arg-type]
        ids = [row.id for row in resp.items]
        assert e2.id in ids
        assert e1.id in ids
        # Most-recent-first ordering.
        assert ids.index(e2.id) < ids.index(e1.id)
        assert resp.total >= 2

    def test_filter_by_event_type(self, db, make_user):
        admin = make_user(role="admin")
        actor = make_user()
        emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        target = emit(
            db,
            event_type="pathway.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        db.flush()

        resp = list_events(
            event_type="pathway.published",
            db=db,
            _=admin,  # type: ignore[arg-type]
        )
        assert all(r.event_type == "pathway.published" for r in resp.items)
        assert target is not None
        assert any(r.id == target.id for r in resp.items)

    def test_filter_by_source_type(self, db, make_user):
        admin = make_user(role="admin")
        actor = make_user()
        emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        db.flush()

        resp = list_events(
            source_type="fresh_collective",
            db=db,
            _=admin,  # type: ignore[arg-type]
        )
        assert all(r.source_type == "fresh_collective" for r in resp.items)

    def test_rejects_unknown_source_type(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            list_events(
                source_type="platform_owner",
                db=db,
                _=admin,  # type: ignore[arg-type]
            )
        assert exc.value.status_code == 400

    def test_rejects_unknown_category(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            list_events(
                category="totally_made_up",
                db=db,
                _=admin,  # type: ignore[arg-type]
            )
        assert exc.value.status_code == 400


class TestGetEvent:
    def test_returns_full_detail(self, db, make_user):
        admin = make_user(role="admin")
        actor = make_user()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
            payload={"post_id": "p_abc"},
            context={"space_id": "s_xyz"},
        )
        assert ev is not None
        db.flush()

        detail = get_event(event_id=ev.id, db=db, _=admin)  # type: ignore[arg-type]
        assert detail.id == ev.id
        assert detail.payload == {"post_id": "p_abc"}
        assert detail.context == {"space_id": "s_xyz"}

    def test_missing_id_returns_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            get_event(event_id="evt_nonexistent", db=db, _=admin)  # type: ignore[arg-type]
        assert exc.value.status_code == 404


class TestRegistry:
    def test_lists_registered_event_types(self, db, make_user):
        admin = make_user(role="admin")
        resp = list_registry(_=admin)  # type: ignore[arg-type]
        types = {e.event_type for e in resp.events}
        # A representative sample from every domain area seeded in
        # registry.py.
        for expected in [
            "account.created",
            "community.post.published",
            "pathway.published",
            "gathering.booking.confirmed",
            "dm.message.sent",
            "creator.update.sent",
            "moderation.action.applied",
        ]:
            assert expected in types

        # Every entry has a resolvable topic + category.
        for e in resp.events:
            assert e.topic
            assert e.category
            assert e.default_priority
