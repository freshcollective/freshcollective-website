"""24-hour gathering reminders.

One reminder per confirmed booking, roughly 24 hours before the
gathering starts. Driven by a cron sweep rather than scheduled at
booking time: the comms layer supports ``scheduled_for`` but nothing
drains that queue today (dispatch is inline, see ``comms/rollout.py``),
and a pre-scheduled intent would go stale whenever a gathering is
moved or cancelled. A sweep reads current state every time, so a
cancelled or rescheduled gathering simply stops matching.

The window
----------

The reminder point for a gathering is ``starts_at - 24h``. A sweep at
time ``now`` picks up every booking whose reminder point falls in
``(now - LOOKBACK, now]`` — a **backward**-looking window, so reminders
are never sent early, only on time or slightly late.

``LOOKBACK`` is 35 minutes against a 15-minute cadence. That is
deliberate: covering one missed run needs the window to span two
cadences (30 minutes) plus margin. A 20-minute window — the figure in
the original design sketch — would leave a 10-minute hole whenever a
run was skipped, so it is corrected here.

Staleness is bounded on purpose. If the job is down for hours, the
affected reminders are dropped rather than delivered at, say, six
hours' notice under a subject line promising 24.

Eligibility
-----------

A booking is reminded when all of these hold:

* the booking is ``confirmed``;
* the gathering is not ``cancelled`` and is published;
* the booking was made **before** the reminder point — someone who
  books inside the last 24 hours already has their confirmation and
  does not need an immediate "reminder";
* the member has not turned ``gathering_reminder_email`` off, resolved
  through the same helper the rest of the notification system uses so
  default behaviour cannot drift.

Idempotency is the ``CommunicationEvent`` dedupe key
``gathering_reminder_24h:{booking_id}`` — one per booking for all time,
enforced by the database, so overlapping sweeps cannot double-send and
no new table is needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    Space,
)


logger = logging.getLogger(__name__)


# How far ahead of a gathering the reminder is aimed.
REMINDER_LEAD = timedelta(hours=24)

# How far back a single sweep looks for reminder points that have come
# due. Must span two cron cadences so one missed run self-heals; see
# the module docstring.
LOOKBACK = timedelta(minutes=35)

_PREF_KEY = "gathering_reminder_email"
_EVENT_TYPE = "gathering.reminder.24h"


class ReminderOutcome(NamedTuple):
    """What one sweep did. ``emitted`` counts genuine new reminders;
    ``deduped`` counts bookings already reminded by an earlier run."""

    considered: int
    emitted: int
    deduped: int
    skipped_preference: int


def format_local_start(event: Event, space: Space | None) -> str:
    """Gathering start in the Collective's own timezone.

    ``Event.starts_at`` is stored naive UTC; ``Space.timezone`` is the
    Collective's display zone. Falls back to rendering the stored UTC
    value if the zone is missing or unknown — never raises.
    """
    dt = event.starts_at
    tz_name = getattr(space, "timezone", None) if space is not None else None
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
        except Exception:
            logger.warning(
                "gathering_reminders: unknown timezone %r on space %s — "
                "falling back to UTC",
                tz_name, getattr(space, "id", None),
            )
            dt = event.starts_at
    return (
        dt.strftime("%A %-d %B at %-I:%M%p")
        .replace("AM", "am")
        .replace("PM", "pm")
    )


def _gathering_url(space: Space | None, event: Event) -> str:
    """Existing member-facing gathering page. No new route is
    introduced for the email — this is the same URL the booking
    confirmation already links to."""
    if space is None or not getattr(space, "slug", None):
        return ""
    base = settings.frontend_origin.rstrip("/")
    return f"{base}/spaces/{space.slug}/events/{event.id}"


def find_due_bookings(
    db: Session, *, now: datetime,
) -> list[tuple[EventBooking, Event, Space | None]]:
    """Confirmed bookings on published, non-cancelled gatherings whose
    reminder point has just come due.

    Expressed as a window on ``starts_at`` so the database can use the
    index: reminder point in ``(now - LOOKBACK, now]`` is exactly
    ``starts_at`` in ``(now + LEAD - LOOKBACK, now + LEAD]``.
    """
    upper = now + REMINDER_LEAD
    lower = upper - LOOKBACK

    rows = (
        db.query(EventBooking, Event, Space)
        .join(Event, Event.id == EventBooking.event_id)
        .outerjoin(Space, Space.id == Event.space_id)
        .filter(
            EventBooking.status == BookingStatus.confirmed,
            Event.starts_at > lower,
            Event.starts_at <= upper,
            Event.status != "cancelled",
            Event.is_published.is_(True),
        )
        .all()
    )

    due: list[tuple[EventBooking, Event, Space | None]] = []
    for booking, event, space in rows:
        # Booked inside the final 24 hours — the confirmation they just
        # received is the reminder. Sending one now would arrive
        # moments after it.
        reminder_point = event.starts_at - REMINDER_LEAD
        if booking.booked_at is not None and booking.booked_at > reminder_point:
            continue
        due.append((booking, event, space))
    return due


def _dedupe_key(booking_id: str) -> str:
    return f"gathering_reminder_24h:{booking_id}"


def already_reminded(db: Session, booking_ids: list[str]) -> set[str]:
    """Booking ids that already have a reminder event.

    A single batch lookup, rather than letting every already-reminded
    booking take ``emit``'s IntegrityError path. Correctness still rests
    on the unique index — this is the fast path, not the guarantee — but
    it means a steady state of reminded bookings costs one SELECT per
    sweep instead of an INSERT-and-rollback each.
    """
    if not booking_ids:
        return set()
    from app.comms.models import CommunicationEvent
    keys = {_dedupe_key(b): b for b in booking_ids}
    rows = (
        db.query(CommunicationEvent.dedupe_key)
        .filter(
            CommunicationEvent.event_type == _EVENT_TYPE,
            CommunicationEvent.dedupe_key.in_(list(keys)),
        )
        .all()
    )
    return {keys[r[0]] for r in rows if r[0] in keys}


def _preference_allows(db: Session, booking: EventBooking, event: Event) -> bool:
    """Resolved through the shared notification-preference helper so
    the default (True, when no prefs row exists) stays identical to
    every other gathering notification."""
    if not event.space_id:
        return True
    from app.services.notification_service import _get_notification_pref
    return _get_notification_pref(db, booking.user_id, event.space_id, _PREF_KEY)


def _emit_reminder(
    db: Session, *, booking: EventBooking, event: Event, space: Space | None,
):
    from app.comms import Source, emit as comms_emit

    return comms_emit(
        db,
        event_type=_EVENT_TYPE,
        source_type=Source.COLLECTIVE if space is not None else Source.FRESH_COLLECTIVE,
        source_id=space.id if space is not None else None,
        actor_user_id=booking.user_id,
        subject_type="event_booking",
        subject_id=booking.id,
        context={
            "space_id": event.space_id,
            "event_id": event.id,
        },
        payload={
            "gathering_title":    event.title,
            "gathering_when":     format_local_start(event, space),
            "collective_name":    getattr(space, "name", "") or "",
            "gathering_url":      _gathering_url(space, event),
            "recipient_user_id":  booking.user_id,
        },
        # One reminder per booking, for all time. The partial unique
        # index on dedupe_key is what makes overlapping sweeps safe.
        dedupe_key=_dedupe_key(booking.id),
    )


def sweep_due_reminders(
    db: Session, *, now: datetime | None = None,
) -> ReminderOutcome:
    """Emit 24-hour reminders for every booking that has come due.

    Emits the whole batch, commits once, then schedules routing for
    each new event. ``emit`` already wraps its dedupe insert in its own
    SAVEPOINT, so a collision rolls back only that attempt — no
    per-reminder commit is needed, and interleaving commits with that
    savepoint is what would break the caller's transaction.

    Returns counts for the cron's log line. A single-booking failure is
    logged and skipped rather than losing the sweep.
    """
    check_at = now or datetime.utcnow()
    due = find_due_bookings(db, now=check_at)

    seen = already_reminded(db, [b.id for b, _, _ in due])

    pending = []
    deduped = skipped_pref = 0
    for booking, event, space in due:
        try:
            if booking.id in seen:
                # Reminded by an earlier sweep — the overlapping window
                # re-presents the same bookings by design.
                deduped += 1
                continue
            if not _preference_allows(db, booking, event):
                skipped_pref += 1
                continue
            comms_event = _emit_reminder(
                db, booking=booking, event=event, space=space,
            )
            if comms_event is None:
                # Dedupe key already present — an earlier sweep (or the
                # overlapping half of this one) already reminded them.
                deduped += 1
                continue
            pending.append(comms_event)
        except Exception:
            logger.exception(
                "gathering_reminders: reminder failed for booking %s "
                "(event %s) — continuing",
                booking.id, event.id,
            )

    db.commit()

    # Routing opens its own session, so it must run after the commit.
    from app.comms.rollout import schedule_routing_if_needed
    for comms_event in pending:
        try:
            schedule_routing_if_needed(None, comms_event, _EVENT_TYPE)
        except Exception:
            logger.exception(
                "gathering_reminders: routing failed for event %s — the "
                "reminder stays recorded and will not be re-sent",
                comms_event.id,
            )

    return ReminderOutcome(
        considered=len(due),
        emitted=len(pending),
        deduped=deduped,
        skipped_preference=skipped_pref,
    )


__all__ = [
    "LOOKBACK",
    "REMINDER_LEAD",
    "ReminderOutcome",
    "already_reminded",
    "find_due_bookings",
    "format_local_start",
    "sweep_due_reminders",
]
