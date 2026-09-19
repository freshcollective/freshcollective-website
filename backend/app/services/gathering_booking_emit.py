"""Comms emit for gathering booking confirmations.

Replaces the half-finished cutover left by ``d605535``: that commit
added the ``_rollout_is_live`` guard to
``notification_service.trigger_booking_confirmed`` and defined a
``_emit_booking_confirmed`` helper in ``spaces/routes.py``, but never
wired the call. Once ``gatherings`` entered ``COMMS_LIVE_TOPICS``
(2026-08-23) the legacy sender stood down and nothing replaced it, so
members stopped receiving booking confirmations entirely.

Lives in ``services/`` rather than in ``spaces/routes.py`` because two
call sites need it — the member booking route and the Stripe
ticket-fulfilment webhook — and importing a route module into the
webhook module invites an import cycle.

Three payload defects from the original dead helper are fixed here:

* **Source attribution.** The original read ``event.creator_id``.
  ``Event`` has no such column (it lives on ``Space``), so the
  ``getattr`` silently yielded ``None`` and fell back to attributing
  the message to the *booker*. A gathering belongs to its Collective,
  so the source is ``collective`` / ``space.id`` — matching
  ``gathering.cancelled`` and ``gathering.reminder.24h``.
* **Collective name.** The original read ``event.collective_name``,
  another attribute that does not exist, so the email would have read
  "in the collective". Resolved from the ``Space`` row.
* **Start time.** The original passed a raw ISO timestamp, which the
  template renders verbatim — members would have seen
  ``2026-09-20T09:00:00``. Formatted through the same timezone-aware
  helper the reminder and cancellation emails use.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models.platform import Event, EventBooking, Space

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent


logger = logging.getLogger(__name__)


_EVENT_TYPE = "gathering.booking.confirmed"


def _dedupe_key(booking: EventBooking) -> str:
    """One confirmation per *act of booking*.

    Keyed on the booking id plus ``booked_at`` rather than the id alone.
    A reactivated booking reuses its row and stamps a fresh
    ``booked_at``, so someone who cancels and genuinely rebooks later is
    confirmed again — while a webhook re-delivery, which changes
    neither, is collapsed.
    """
    stamp = booking.booked_at.isoformat() if booking.booked_at else "none"
    return f"booking_confirmed:{booking.id}:{stamp}"


def emit_booking_confirmed(
    db: Session,
    *,
    booking: EventBooking,
    added_by_creator: bool = False,
    background_tasks: Any = None,
) -> "CommunicationEvent | None":
    """Emit ``gathering.booking.confirmed`` for a confirmed booking.

    Commits the emit and schedules routing, mirroring the other
    gathering emit sites. Never raises — a comms failure must not roll
    back a booking the member has already been told succeeded, nor
    block Stripe ticket fulfilment.

    Returns the event, or ``None`` when nothing was emitted (deduped,
    or the underlying rows could not be resolved).
    """
    try:
        from app.comms import Source, emit as comms_emit
        from app.comms.rollout import schedule_routing_if_needed
        from app.services.gathering_reminders import format_local_start

        event = db.query(Event).filter(Event.id == booking.event_id).first()
        if event is None:
            logger.warning(
                "booking_confirmed emit: event %s missing for booking %s",
                booking.event_id, booking.id,
            )
            return None

        space = (
            db.query(Space).filter(Space.id == event.space_id).first()
            if event.space_id else None
        )
        if space is None:
            logger.warning(
                "booking_confirmed emit: space %s missing for booking %s",
                event.space_id, booking.id,
            )
            return None

        ev = comms_emit(
            db,
            event_type=_EVENT_TYPE,
            source_type=Source.COLLECTIVE,
            source_id=space.id,
            actor_user_id=booking.user_id,
            # Subject stays the gathering, not the booking: the
            # registered resolver reads ``gathering_id`` straight off
            # ``event.subject_id``, so pointing it at the booking would
            # feed the wrong id into the in-app notification metadata.
            # The booking id travels in ``context`` instead.
            subject_type="gathering",
            subject_id=event.id,
            context={
                "space_id":        space.id,
                "booking_id":      booking.id,
                # The resolver reads collective_name from context, not
                # payload — this is the field that was always None.
                "collective_name": space.name,
            },
            payload={
                "booker_id":           booking.user_id,
                "gathering_title":     event.title,
                "gathering_starts_at": format_local_start(event, space),
                "collective_name":     space.name,
                "gathering_id":        event.id,
                "gathering_url":       _gathering_url(space, event),
                # True when a creator added this member rather than the
                # member reserving a place themselves. The template
                # changes one sentence; it must never tell someone they
                # booked something they did not.
                "added_by_creator":    added_by_creator,
            },
            dedupe_key=_dedupe_key(booking),
        )
        db.commit()
        schedule_routing_if_needed(background_tasks, ev, _EVENT_TYPE)
        return ev
    except Exception:
        logger.exception(
            "booking_confirmed emit failed for booking %s — the booking "
            "itself is unaffected",
            getattr(booking, "id", None),
        )
        return None


def _gathering_url(space: Space, event: Event) -> str:
    """Existing member-facing gathering page — no new route is added
    for the email."""
    from app.core.config import settings
    if not getattr(space, "slug", None):
        return ""
    base = settings.frontend_origin.rstrip("/")
    return f"{base}/spaces/{space.slug}/events/{event.id}"


def _series_url(space: Space, series: Any) -> str:
    """Existing member-facing Series page, when the bookings belong to
    a real ``EventSeries``."""
    from app.core.config import settings
    if series is None or not getattr(series, "slug", None):
        return ""
    if not getattr(space, "slug", None):
        return ""
    base = settings.frontend_origin.rstrip("/")
    return f"{base}/spaces/{space.slug}/gathering-series/{series.slug}"


def _multi_dedupe_key(user_id: str, scope: str, operation_at) -> str:
    """One email per booking *operation*, not per child booking.

    ``operation_at`` is the single ``now`` the route stamped on every
    booking it created, so the whole batch collapses to one key. A
    genuinely separate later operation carries a different timestamp
    and earns its own summary.
    """
    stamp = operation_at.isoformat() if operation_at else "none"
    return f"multi_booking:{user_id}:{scope}:{stamp}"


def emit_multi_booking_confirmed(
    db: Session,
    *,
    user_id: str,
    bookings: list[EventBooking],
    space: Space,
    scope: str,
    operation_at: Any,
    series: Any = None,
    added_by_creator: bool = False,
    background_tasks: Any = None,
) -> "CommunicationEvent | None":
    """One summary confirmation for a batch of gatherings booked by a
    single action.

    Used by member Series booking and by creator recurring booking.
    Callers pass only the bookings they actually created or
    reactivated — already-booked and skipped occurrences are not the
    member's news.

    ``scope`` is a stable identifier for what was booked (a series id,
    or a digest of the booking ids) and feeds the dedupe key.
    """
    try:
        if not bookings:
            return None

        from app.comms import Source, emit as comms_emit
        from app.comms.rollout import schedule_routing_if_needed
        from app.services.gathering_reminders import format_local_start

        events = (
            db.query(Event)
            .filter(Event.id.in_([b.event_id for b in bookings]))
            .order_by(Event.starts_at)
            .all()
        )
        if not events:
            return None

        # A short schedule extract, not the whole run — three lines is
        # enough to recognise what was booked without the email
        # becoming a timetable.
        preview = [
            {"title": e.title, "when": format_local_start(e, space)}
            for e in events[:3]
        ]

        series_title = (
            getattr(series, "title", None)
            or next((e.recurrence_label for e in events if e.recurrence_label), None)
            or ""
        )
        cta_url = _series_url(space, series) or _gathering_url(space, events[0])

        ev = comms_emit(
            db,
            event_type="gathering.multi_booking.confirmed",
            source_type=Source.COLLECTIVE,
            source_id=space.id,
            actor_user_id=user_id,
            subject_type="gathering_series" if series is not None else "space",
            subject_id=getattr(series, "id", None) or space.id,
            context={
                "space_id":        space.id,
                "collective_name": space.name,
                "booking_ids":     [b.id for b in bookings],
            },
            payload={
                "booker_id":        user_id,
                "collective_name":  space.name,
                "series_title":     series_title,
                "session_count":    len(events),
                "first_starts_at":  format_local_start(events[0], space),
                "last_starts_at":   format_local_start(events[-1], space),
                "schedule_preview": preview,
                "cta_url":          cta_url,
                "added_by_creator": added_by_creator,
            },
            dedupe_key=_multi_dedupe_key(user_id, scope, operation_at),
        )
        db.commit()
        schedule_routing_if_needed(
            background_tasks, ev, "gathering.multi_booking.confirmed",
        )
        return ev
    except Exception:
        logger.exception(
            "multi_booking_confirmed emit failed for user %s (%d bookings) "
            "— the bookings themselves are unaffected",
            user_id, len(bookings or []),
        )
        return None


__all__ = ["emit_booking_confirmed", "emit_multi_booking_confirmed"]
