"""Production-shape cover for multi-booking dedupe.

Same reason as the single-booking and reminder integration files: the
shared ``db`` fixture restarts its SAVEPOINT after every ``.commit()``,
which collides with ``emit()``'s ``begin_nested`` dedupe path. An
emit-commit-emit test on that fixture has its second emit fail for a
fixture reason, get swallowed by the ``except`` in the emit helper, and
"pass" for entirely the wrong reason — so those assertions live here,
on ordinary committing sessions.

Proves the two claims the anti-spam design rests on:

* one booking operation produces exactly ONE summary, and replaying it
  produces none;
* a genuinely separate later operation does produce its own.

Self-cleaning: nothing is rolled back for us, so every row is removed
in a ``finally`` and ids are suffixed per run.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.models import (
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationIntent,
)
from app.models.platform import BookingStatus, Event, EventBooking, Space
from app.models.user import User
from app.services.gathering_booking_emit import emit_multi_booking_confirmed


MULTI = "gathering.multi_booking.confirmed"

SUFFIX = uuid.uuid4().hex[:10]
USER_ID = f"u_mb_{SUFFIX}"
SPACE_ID = f"sp_mb_{SUFFIX}"
SESSIONS = 4


@pytest.fixture
def real_sessions(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


def _cleanup(Session) -> None:
    with Session() as s:
        event_ids = [
            r[0] for r in s.query(CommunicationEvent.id).filter(
                CommunicationEvent.event_type == MULTI,
                CommunicationEvent.source_id == SPACE_ID,
            ).all()
        ]
        if event_ids:
            intent_ids = [
                r[0] for r in s.query(CommunicationIntent.id).filter(
                    CommunicationIntent.event_id.in_(event_ids),
                ).all()
            ]
            if intent_ids:
                s.query(CommunicationDelivery).filter(
                    CommunicationDelivery.intent_id.in_(intent_ids),
                ).delete(synchronize_session=False)
                s.query(CommunicationIntent).filter(
                    CommunicationIntent.id.in_(intent_ids),
                ).delete(synchronize_session=False)
            s.query(CommunicationEvent).filter(
                CommunicationEvent.id.in_(event_ids),
            ).delete(synchronize_session=False)
        s.query(EventBooking).filter(
            EventBooking.id.like(f"bk_mb_{SUFFIX}%"),
        ).delete(synchronize_session=False)
        s.query(Event).filter(
            Event.id.like(f"ev_mb_{SUFFIX}%"),
        ).delete(synchronize_session=False)
        s.query(Space).filter(Space.id == SPACE_ID).delete(
            synchronize_session=False,
        )
        s.query(User).filter(User.id == USER_ID).delete(
            synchronize_session=False,
        )
        s.commit()


def _seed(Session, *, booked_at: datetime) -> None:
    with Session() as s:
        s.add(User(
            id=USER_ID, email=f"multibooking-{SUFFIX}@example.test",
            name="Ada Lovelace", role="user",
            password_hash="$2b$12$" + "0" * 53,
            email_verified_at=datetime.utcnow(),
        ))
        s.add(Space(
            id=SPACE_ID, slug=f"still-water-mb-{SUFFIX}", name="Still Water",
            timezone="Australia/Melbourne", status="active",
        ))
        for i in range(SESSIONS):
            s.add(Event(
                id=f"ev_mb_{SUFFIX}_{i}", space_id=SPACE_ID,
                title=f"Week {i + 1}",
                starts_at=datetime.utcnow() + timedelta(days=7 * (i + 1)),
                status="active", is_published=True, requires_booking=True,
            ))
            s.add(EventBooking(
                id=f"bk_mb_{SUFFIX}_{i}", event_id=f"ev_mb_{SUFFIX}_{i}",
                user_id=USER_ID, status=BookingStatus.confirmed,
                booked_at=booked_at,
            ))
        s.commit()


def _count(Session) -> int:
    with Session() as s:
        return s.query(CommunicationEvent).filter(
            CommunicationEvent.event_type == MULTI,
            CommunicationEvent.source_id == SPACE_ID,
        ).count()


def test_one_operation_one_summary_replay_none_later_operation_one_more(
    real_sessions,
):
    Session = real_sessions
    operation_at = datetime.utcnow() - timedelta(minutes=5)

    try:
        _cleanup(Session)
        _seed(Session, booked_at=operation_at)

        def _emit(scope, at):
            with Session() as s:
                space = s.query(Space).filter(Space.id == SPACE_ID).one()
                bookings = s.query(EventBooking).filter(
                    EventBooking.user_id == USER_ID,
                ).all()
                assert len(bookings) == SESSIONS
                return emit_multi_booking_confirmed(
                    s, user_id=USER_ID, bookings=bookings, space=space,
                    scope=scope, operation_at=at,
                )

        # One action booking four sessions → exactly one summary.
        assert _emit("series:s1", operation_at) is not None
        assert _count(Session) == 1

        # Replay of the same action → nothing, however many times.
        for _ in range(3):
            assert _emit("series:s1", operation_at) is None
        assert _count(Session) == 1

        # Four bookings, one email — the whole point of the design.
        with Session() as s:
            ev = s.query(CommunicationEvent).filter(
                CommunicationEvent.event_type == MULTI,
                CommunicationEvent.source_id == SPACE_ID,
            ).one()
            assert ev.payload["session_count"] == SESSIONS
            assert len(ev.context["booking_ids"]) == SESSIONS

        # A genuinely separate later action → its own summary.
        later = operation_at + timedelta(days=1)
        assert _emit("series:s1", later) is not None
        assert _count(Session) == 2
    finally:
        _cleanup(Session)
