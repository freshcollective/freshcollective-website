"""Tests for ``app.comms.emit`` (Milestone 1).

Covers:
  * Basic persistence and category inference from topic.
  * Idempotent dedupe.
  * Source validation (fresh_collective forbids id; collective/creator
    require id).
  * Unknown event_type rejection.
  * priority_hint override.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.comms import Priority, Source, emit
from app.comms.events import InvalidSourceError, UnknownEventTypeError
from app.comms.models import CommunicationEvent


class TestEmitPersistence:
    def test_emit_persists_event(self, db, make_user):
        actor = make_user()
        ev = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
            subject_type="user",
            subject_id=actor.id,
            payload={"signup_channel": "email"},
        )
        assert ev is not None
        assert ev.id.startswith("evt_")
        assert ev.event_type == "account.created"
        assert ev.source_type == "fresh_collective"
        assert ev.source_id is None
        assert ev.actor_user_id == actor.id
        assert ev.payload == {"signup_channel": "email"}
        assert ev.category_key == "account"
        assert ev.topic_key == "account"
        # account.created is a silent bookkeeping event
        assert ev.priority_hint == "silent"
        assert ev.sequence_number is not None and ev.sequence_number > 0

    def test_emit_defaults_context_and_payload_to_empty(self, db, make_user):
        actor = make_user()
        ev = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        assert ev is not None
        assert ev.context == {}
        assert ev.payload == {}


class TestSourceValidation:
    def test_fresh_collective_source_forbids_id(self, db):
        with pytest.raises(InvalidSourceError):
            emit(
                db,
                event_type="account.created",
                source_type=Source.FRESH_COLLECTIVE,
                source_id="some-id",
            )

    def test_creator_source_requires_id(self, db):
        with pytest.raises(InvalidSourceError):
            emit(
                db,
                event_type="creator.update.sent",
                source_type=Source.CREATOR,
                source_id=None,
            )

    def test_collective_source_requires_id(self, db):
        with pytest.raises(InvalidSourceError):
            emit(
                db,
                event_type="collective.membership.joined",
                source_type=Source.COLLECTIVE,
                source_id=None,
            )

    def test_unknown_source_type_rejected(self, db):
        with pytest.raises(InvalidSourceError):
            emit(
                db,
                event_type="account.created",
                source_type="platform_owner",  # type: ignore[arg-type]
            )


class TestRegistry:
    def test_unknown_event_type_rejected(self, db):
        with pytest.raises(UnknownEventTypeError):
            emit(
                db,
                event_type="totally.made.up.event",
                source_type=Source.FRESH_COLLECTIVE,
            )

    def test_topic_and_category_inferred_from_registry(self, db, make_user):
        actor = make_user()
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
        )
        assert ev is not None
        assert ev.topic_key == "conversations"
        assert ev.category_key == "community"

    def test_priority_hint_overrides_default(self, db):
        # community.post.published defaults to immediate; caller
        # can downgrade to a digest for a specific emit.
        ev = emit(
            db,
            event_type="community.post.published",
            source_type=Source.COLLECTIVE,
            source_id="col_abc123",
            priority_hint=Priority.DAILY_DIGEST,
        )
        assert ev is not None
        assert ev.priority_hint == "daily_digest"


class TestDedupe:
    def test_repeat_dedupe_key_returns_none(self, db, make_user):
        actor = make_user()
        key = f"pathway_completed:{uuid.uuid4().hex[:8]}"

        first = emit(
            db,
            event_type="pathway.enrolment.completed",
            source_type=Source.CREATOR,
            source_id=actor.id,
            dedupe_key=key,
        )
        second = emit(
            db,
            event_type="pathway.enrolment.completed",
            source_type=Source.CREATOR,
            source_id=actor.id,
            dedupe_key=key,
        )

        assert first is not None
        assert second is None

        rows = db.execute(
            select(CommunicationEvent).where(CommunicationEvent.dedupe_key == key)
        ).scalars().all()
        assert len(rows) == 1

    def test_same_dedupe_key_across_different_event_types_does_not_collide(
        self, db, make_user,
    ):
        actor = make_user()
        key = f"shared:{uuid.uuid4().hex[:8]}"

        first = emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
            dedupe_key=key,
        )
        second = emit(
            db,
            event_type="pathway.published",
            source_type=Source.CREATOR,
            source_id=actor.id,
            dedupe_key=key,
        )
        assert first is not None
        assert second is not None
        assert first.id != second.id

    def test_null_dedupe_key_never_collides(self, db, make_user):
        actor = make_user()
        a = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        b = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        assert a is not None and b is not None
        assert a.id != b.id


class TestSequenceNumber:
    def test_sequence_number_is_monotonic(self, db, make_user):
        actor = make_user()
        first = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        second = emit(
            db,
            event_type="account.created",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=actor.id,
        )
        assert first is not None and second is not None
        assert second.sequence_number > first.sequence_number
