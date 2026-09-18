"""Production-shape cover for booking-confirmation dedupe.

The savepoint-based ``db`` fixture restarts its SAVEPOINT after every
``.commit()``, which collides with ``emit()``'s ``begin_nested`` dedupe
path — so a unit test that emits, commits, then emits again would have
its second emit fail for a fixture reason and be swallowed by
``emit_booking_confirmed``'s ``except``. It would then "pass" for
entirely the wrong reason.

This file therefore uses its own committing ``sessionmaker`` bound
straight to the test engine, the same shape a request or webhook
handler gets from ``SessionLocal``. It exists to prove the two claims
that actually depend on commit-then-emit:

* a replay of the same booking produces no second email;
* a genuine rebooking (fresh ``booked_at``) does produce one.

Same self-cleaning contract as the reminder integration test: nothing
is rolled back for us, so every row is removed in a ``finally`` and ids
are suffixed per run.
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
from app.services.gathering_booking_emit import emit_booking_confirmed


EVENT_TYPE = "gathering.booking.confirmed"

SUFFIX = uuid.uuid4().hex[:10]
USER_ID = f"u_bk_{SUFFIX}"
SPACE_ID = f"sp_bk_{SUFFIX}"
EVENT_ID = f"ev_bk_{SUFFIX}"
BOOKING_ID = f"bk_bk_{SUFFIX}"


@pytest.fixture
def real_sessions(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _no_dispatch():
    """Routing is stubbed — this file is about dedupe, not delivery.
    The reminder integration test already covers the full dispatch
    chain end to end."""
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


def _cleanup(Session) -> None:
    with Session() as s:
        event_ids = [
            r[0] for r in s.query(CommunicationEvent.id).filter(
                CommunicationEvent.subject_id == EVENT_ID,
                CommunicationEvent.event_type == EVENT_TYPE,
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
        for model, pk in (
            (EventBooking, BOOKING_ID), (Event, EVENT_ID),
            (Space, SPACE_ID), (User, USER_ID),
        ):
            s.query(model).filter(model.id == pk).delete(
                synchronize_session=False,
            )
        s.commit()


def _seed(Session, *, booked_at: datetime) -> None:
    with Session() as s:
        s.add(User(
            id=USER_ID, email=f"booking-{SUFFIX}@example.test",
            name="Ada Lovelace", role="user",
            password_hash="$2b$12$" + "0" * 53,
            email_verified_at=datetime.utcnow(),
        ))
        s.add(Space(
            id=SPACE_ID, slug=f"still-water-bk-{SUFFIX}", name="Still Water",
            timezone="Australia/Melbourne", status="active",
        ))
        s.add(Event(
            id=EVENT_ID, space_id=SPACE_ID, title="Morning Sit",
            starts_at=datetime.utcnow() + timedelta(days=7),
            status="active", is_published=True, requires_booking=True,
        ))
        s.add(EventBooking(
            id=BOOKING_ID, event_id=EVENT_ID, user_id=USER_ID,
            status=BookingStatus.confirmed, booked_at=booked_at,
        ))
        s.commit()


def _count(Session) -> int:
    with Session() as s:
        return s.query(CommunicationEvent).filter(
            CommunicationEvent.subject_id == EVENT_ID,
            CommunicationEvent.event_type == EVENT_TYPE,
        ).count()


def test_replay_does_not_duplicate_but_a_genuine_rebooking_does_confirm(
    real_sessions,
):
    """Commit a booking, emit from a fresh session, then replay it — the
    second attempt must be refused by the dedupe key. Then restamp
    ``booked_at`` as a reactivation does, and confirm that genuinely
    emits again."""
    Session = real_sessions
    original_booked_at = datetime.utcnow() - timedelta(days=14)

    try:
        _cleanup(Session)
        _seed(Session, booked_at=original_booked_at)

        # ── First confirmation, from a request-shaped session ─────────
        with Session() as s:
            booking = s.query(EventBooking).filter(
                EventBooking.id == BOOKING_ID,
            ).one()
            assert emit_booking_confirmed(s, booking=booking) is not None
        assert _count(Session) == 1

        # ── Replay: Stripe re-delivers, or the request is retried ─────
        for _ in range(3):
            with Session() as s:
                booking = s.query(EventBooking).filter(
                    EventBooking.id == BOOKING_ID,
                ).one()
                assert emit_booking_confirmed(s, booking=booking) is None
        assert _count(Session) == 1

        # ── Genuine rebooking: same row, fresh booked_at ──────────────
        with Session() as s:
            booking = s.query(EventBooking).filter(
                EventBooking.id == BOOKING_ID,
            ).one()
            booking.status = BookingStatus.confirmed
            booking.booked_at = datetime.utcnow()
            s.commit()

        with Session() as s:
            booking = s.query(EventBooking).filter(
                EventBooking.id == BOOKING_ID,
            ).one()
            assert emit_booking_confirmed(s, booking=booking) is not None
        assert _count(Session) == 2
    finally:
        _cleanup(Session)
