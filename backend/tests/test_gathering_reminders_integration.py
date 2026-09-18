"""Production-shape integration test for the 24-hour reminder sweep.

Why this file exists
--------------------

``tests/test_gathering_reminders.py`` drives the sweep through the
shared ``db`` fixture, which wraps each test in a SAVEPOINT and
restarts it after every ``.commit()``. That listener collides with
``emit()``'s own ``begin_nested`` dedupe path, so those tests stage
rows with ``flush()`` rather than ``commit()`` — which means they never
exercise the sequence the cron actually performs: **commit real rows,
then open a fresh session and sweep.**

This file closes that gap by not using the ``db`` fixture at all. It
builds its own ``sessionmaker`` bound straight to the test engine, so
every session here is an ordinary committing session — the same shape
``SessionLocal`` gives the cron process. Deliberately kept to a single
end-to-end case; the per-rule eligibility matrix stays in the unit
file.

Isolation
---------

Nothing here is rolled back for us, so the test owns its cleanup: every
row it creates (and every row the comms pipeline creates downstream of
it) is deleted in a ``finally``. Ids are uniquely suffixed so a crashed
run cannot collide with a later one.

Safety
------

``ResendProvider.send`` is patched at the provider boundary rather than
at the Resend SDK, so there is no code path from this test to the
network at all. Everything below that boundary — routing, the decision
pipeline, intent creation, dispatch, delivery recording — runs for
real, which is the point.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import (
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationIntent,
)
from app.comms.providers.base import ProviderResult
from app.comms.providers.resend import ResendProvider
from app.models.platform import BookingStatus, Event, EventBooking, Space
from app.models.user import User
from app.services.gathering_reminders import REMINDER_LEAD, sweep_due_reminders


EVENT_TYPE = "gathering.reminder.24h"

SUFFIX = uuid.uuid4().hex[:10]
USER_ID = f"u_rem_{SUFFIX}"
SPACE_ID = f"sp_rem_{SUFFIX}"
EVENT_ID = f"ev_rem_{SUFFIX}"
BOOKING_ID = f"bk_rem_{SUFFIX}"
DEDUPE_KEY = f"gathering_reminder_24h:{BOOKING_ID}"


@pytest.fixture
def real_sessions(engine):
    """A committing sessionmaker bound to the test engine — the same
    shape ``app.core.database.SessionLocal`` hands the cron."""
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _cleanup(Session) -> None:
    """Remove everything this test committed, innermost first."""
    with Session() as s:
        event_ids = [
            r[0] for r in s.query(CommunicationEvent.id)
            .filter(CommunicationEvent.dedupe_key == DEDUPE_KEY).all()
        ]
        # Delivery rows stamped with this run's fake message ids go
        # first, whether or not their intent still exists — they hold a
        # real unique constraint on (provider_key, provider_message_id)
        # and a stray one would break a later run for the wrong reason.
        s.query(CommunicationDelivery).filter(
            CommunicationDelivery.provider_message_id.like(f"msg_{SUFFIX}_%"),
        ).delete(synchronize_session=False)
        if event_ids:
            intent_ids = [
                r[0] for r in s.query(CommunicationIntent.id)
                .filter(CommunicationIntent.event_id.in_(event_ids)).all()
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
            (EventBooking, BOOKING_ID),
            (Event, EVENT_ID),
            (Space, SPACE_ID),
            (User, USER_ID),
        ):
            s.query(model).filter(model.id == pk).delete(
                synchronize_session=False,
            )
        s.commit()


def _seed(Session, *, now: datetime) -> None:
    """Persist a genuinely eligible booking and COMMIT it, exactly as a
    member booking a place would leave the database."""
    with Session() as s:
        s.add(User(
            id=USER_ID,
            email=f"reminder-{SUFFIX}@example.test",
            name="Ada Lovelace",
            role="user",
            password_hash="$2b$12$" + "0" * 53,
            email_verified_at=datetime.utcnow(),
        ))
        s.add(Space(
            id=SPACE_ID, slug=f"still-water-{SUFFIX}", name="Still Water",
            timezone="Australia/Melbourne",
        ))
        starts_at = now + REMINDER_LEAD - timedelta(minutes=5)
        s.add(Event(
            id=EVENT_ID, space_id=SPACE_ID, title="Morning Sit",
            starts_at=starts_at, status="active", is_published=True,
            requires_booking=True,
        ))
        s.add(EventBooking(
            id=BOOKING_ID, event_id=EVENT_ID, user_id=USER_ID,
            status=BookingStatus.confirmed,
            booked_at=starts_at - timedelta(days=3),
        ))
        s.commit()


def test_cron_shaped_sweep_emits_once_and_persists_then_dedupes(
    real_sessions, engine,
):
    """The full cron path: committed booking → fresh session sweeps →
    one reminder emitted, routed, dispatched and recorded → a second
    fresh sweep finds nothing new."""
    Session = real_sessions
    now = datetime.utcnow()

    sends: list = []

    def _fake_send(self, payload):
        sends.append(payload)
        # Unique per run — ``communication_deliveries`` has a genuine
        # unique index on (provider_key, provider_message_id), so a
        # fixed id would collide with any row a previous run left
        # behind and the dispatch would fail for the wrong reason.
        return ProviderResult(
            accepted=True,
            provider_message_id=f"msg_{SUFFIX}_{len(sends)}",
        )

    try:
        _cleanup(Session)          # defensive: clear any crashed prior run
        _seed(Session, now=now)

        # The booking is committed and visible to any new connection —
        # prove that before sweeping, so a later assertion failure can't
        # be blamed on invisible setup.
        with Session() as s:
            assert s.query(EventBooking).filter(
                EventBooking.id == BOOKING_ID,
            ).one().status == BookingStatus.confirmed

        # ── Sweep 1: a fresh session, as the cron process would open ──
        with patch.object(ResendProvider, "send", _fake_send):
            with Session() as sweep_session:
                first = sweep_due_reminders(sweep_session, now=now)

        assert first.considered == 1
        assert first.emitted == 1
        assert first.deduped == 0

        # The pipeline ran all the way to the provider boundary.
        assert len(sends) == 1
        assert "Morning Sit" in sends[0].subject

        # ── State persisted, seen from yet another connection ─────────
        with Session() as s:
            events = s.query(CommunicationEvent).filter(
                CommunicationEvent.dedupe_key == DEDUPE_KEY,
            ).all()
            assert len(events) == 1
            assert events[0].event_type == EVENT_TYPE
            assert events[0].payload["gathering_title"] == "Morning Sit"
            # Rendered in the Collective's zone, not the stored UTC
            # value. Computed independently here rather than trusting
            # the production helper to check itself.
            from zoneinfo import ZoneInfo
            starts_at = s.query(Event).filter(Event.id == EVENT_ID).one().starts_at
            local = (
                starts_at.replace(tzinfo=UTC)
                .astimezone(ZoneInfo("Australia/Melbourne"))
            )
            expected_when = (
                local.strftime("%A %-d %B at %-I:%M%p")
                .replace("AM", "am").replace("PM", "pm")
            )
            assert events[0].payload["gathering_when"] == expected_when
            # And it genuinely differs from a naive UTC rendering.
            utc_when = (
                starts_at.strftime("%A %-d %B at %-I:%M%p")
                .replace("AM", "am").replace("PM", "pm")
            )
            assert expected_when != utc_when

            intents = s.query(CommunicationIntent).filter(
                CommunicationIntent.event_id == events[0].id,
            ).all()
            email_intents = [
                i for i in intents
                if i.channel == CHANNEL_EMAIL_TRANSACTIONAL
            ]
            assert len(email_intents) == 1
            intent = email_intents[0]
            assert intent.state == "sent"
            assert intent.recipient_address == f"reminder-{SUFFIX}@example.test"
            assert intent.template_key == f"{EVENT_TYPE}.email_transactional"

            deliveries = s.query(CommunicationDelivery).filter(
                CommunicationDelivery.intent_id == intent.id,
            ).all()
            assert len(deliveries) == 1
            assert deliveries[0].status == "accepted"
            assert deliveries[0].provider_key == "resend"

        # ── Sweep 2: another fresh session, 15 minutes later ──────────
        # The overlapping window re-presents the same booking; the
        # dedupe key is what stops a second email.
        with patch.object(ResendProvider, "send", _fake_send):
            with Session() as sweep_session:
                second = sweep_due_reminders(
                    sweep_session, now=now + timedelta(minutes=15),
                )

        assert second.considered == 1      # still in the window
        assert second.emitted == 0
        assert second.deduped == 1
        assert len(sends) == 1             # no second send attempt

        with Session() as s:
            assert s.query(CommunicationEvent).filter(
                CommunicationEvent.dedupe_key == DEDUPE_KEY,
            ).count() == 1
            assert s.query(CommunicationIntent).join(
                CommunicationEvent,
                CommunicationEvent.id == CommunicationIntent.event_id,
            ).filter(
                CommunicationEvent.dedupe_key == DEDUPE_KEY,
                CommunicationIntent.channel == CHANNEL_EMAIL_TRANSACTIONAL,
            ).count() == 1
    finally:
        _cleanup(Session)
