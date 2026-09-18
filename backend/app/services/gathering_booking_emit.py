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


__all__ = ["emit_booking_confirmed"]
