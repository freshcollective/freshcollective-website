"""Resolvers for gathering events.

M5b coverage: ``gathering.booking.confirmed`` — the single-recipient
immediate-priority example. The booker is the recipient.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("gathering.booking.confirmed")
class BookingConfirmedResolver:
    event_type = "gathering.booking.confirmed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        booker_id = payload.get("booker_id") or event.actor_user_id
        if not booker_id:
            return []
        return [
            ResolvedRecipient(
                user_id=booker_id,
                role_in_event="booker",
                human_reason="You booked this gathering.",
                template_context={
                    "gathering_title": payload.get("gathering_title"),
                    "gathering_starts_at": payload.get("gathering_starts_at"),
                    "collective_name": (event.context or {}).get("collective_name"),
                    "gathering_id": event.subject_id,
                    "gathering_url": payload.get("gathering_url") or "",
                    "added_by_creator": bool(payload.get("added_by_creator")),
                },
            ),
        ]


@resolver_for("gathering.cancelled")
class GatheringCancelledResolver:
    """Creator cancelled the whole gathering.

    Recipients are the attendees whose confirmed bookings were released,
    captured in the payload at emit time — by the time routing runs the
    booking rows are already ``cancelled``, so they cannot be re-queried.
    The cancelling creator is excluded at the emit site.
    """

    event_type = "gathering.cancelled"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        recipient_ids = payload.get("recipient_user_ids") or []
        ctx = {
            "gathering_title":     payload.get("gathering_title") or "",
            "gathering_starts_at": payload.get("gathering_starts_at") or "",
            "collective_name":     payload.get("collective_name") or "",
            "was_ticketed":        bool(payload.get("was_ticketed")),
        }
        return [
            ResolvedRecipient(
                user_id=uid,
                role_in_event="attendee",
                human_reason="You had a place booked at this gathering.",
                template_context=dict(ctx),
            )
            for uid in recipient_ids
            if uid
        ]


@resolver_for("gathering.reminder.24h")
class GatheringReminder24hResolver:
    """Single recipient — the member whose booking is being reminded.

    The sweep resolves every member-facing fact (local start time,
    collective name, gathering URL) at emit time, so nothing here needs
    to re-read the domain graph.
    """

    event_type = "gathering.reminder.24h"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        user_id = payload.get("recipient_user_id") or event.actor_user_id
        if not user_id:
            return []
        return [
            ResolvedRecipient(
                user_id=user_id,
                role_in_event="attendee",
                human_reason="You have a place booked at this gathering.",
                template_context={
                    "gathering_title": payload.get("gathering_title") or "",
                    "gathering_when":  payload.get("gathering_when") or "",
                    "collective_name": payload.get("collective_name") or "",
                    "gathering_url":   payload.get("gathering_url") or "",
                },
            ),
        ]


@resolver_for("gathering.multi_booking.confirmed")
class MultiBookingConfirmedResolver:
    """Single recipient — the member whose bookings were created. One
    summary per booking action, never one per occurrence."""

    event_type = "gathering.multi_booking.confirmed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        user_id = payload.get("booker_id") or event.actor_user_id
        if not user_id:
            return []
        added_by_creator = bool(payload.get("added_by_creator"))
        return [
            ResolvedRecipient(
                user_id=user_id,
                role_in_event="attendee",
                human_reason=(
                    "A caretaker booked these gatherings for you."
                    if added_by_creator else
                    "You booked these gatherings."
                ),
                template_context={
                    "collective_name":  payload.get("collective_name") or "",
                    "series_title":     payload.get("series_title") or "",
                    "session_count":    payload.get("session_count") or 0,
                    "first_starts_at":  payload.get("first_starts_at") or "",
                    "last_starts_at":   payload.get("last_starts_at") or "",
                    "schedule_preview": payload.get("schedule_preview") or [],
                    "cta_url":          payload.get("cta_url") or "",
                    "added_by_creator": added_by_creator,
                },
            ),
        ]


@resolver_for("gathering.published")
class GatheringPublishedResolver:
    """Everyone in the Collective, bar the creator who published it.

    Re-checks visibility here as well as at emit time. Routing runs in
    a background task after the response, so the Gathering can be
    unpublished, cancelled, or its Collective closed in the gap, and
    nobody should be emailed an invitation to something that has since
    gone. The same reasoning as the Pathway resolver beside it.
    """
    event_type = "gathering.published"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        from app.models.platform import Event, Space, SpaceMembership
        from app.services.publication_announcement import (
            gathering_is_member_visible,
        )

        context = event.context or {}
        payload = event.payload or {}
        space_id = context.get("space_id")
        if not space_id:
            return []

        space = db.get(Space, space_id)
        gathering_id = payload.get("gathering_id") or event.subject_id
        gathering = db.get(Event, gathering_id) if gathering_id else None
        if gathering is None or not gathering_is_member_visible(db, gathering):
            return []

        collective_name = (
            context.get("collective_name")
            or (space.name if space else "your collective")
        )
        # The member-facing page. Tickets are bought there for a paid
        # Gathering and the booking CTA lives there for a free one, so
        # one destination serves both — and neither grants anything by
        # being linked.
        gathering_url = (
            f"/spaces/{space.slug}/events/{gathering.id}" if space else None
        )

        rows = db.execute(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == "active",
            )
        ).scalars().all()

        out: list[ResolvedRecipient] = []
        for row in rows:
            # The creator published it; they do not need telling.
            if event.actor_user_id and row.user_id == event.actor_user_id:
                continue
            out.append(
                ResolvedRecipient(
                    user_id=row.user_id,
                    role_in_event="member_of_collective",
                    human_reason=f"You're a member of {collective_name}.",
                    template_context={
                        "collective_name": collective_name,
                        "gathering_id": gathering.id,
                        "gathering_title": payload.get("gathering_title"),
                        "starts_at": payload.get("starts_at"),
                        "ends_at": payload.get("ends_at"),
                        "location_type": payload.get("location_type"),
                        "attendance_format": payload.get("attendance_format"),
                        "venue_locality": payload.get("venue_locality"),
                        "description": payload.get("description"),
                        "is_paid": payload.get("is_paid"),
                        "gathering_url": gathering_url,
                        "space_id": space_id,
                    },
                )
            )
        return out


@resolver_for("series.published")
class SeriesPublishedResolver:
    """One announcement for the Series, to the whole Collective.

    The occurrences never reach this point — a Gathering carrying a
    ``series_id`` is refused by ``should_announce_gathering`` before an
    event is written — so there is no de-duplication to do here
    between a Series and its sessions.
    """
    event_type = "series.published"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        from app.models.platform import EventSeries, Space, SpaceMembership
        from app.services.publication_announcement import (
            series_is_member_visible,
        )

        context = event.context or {}
        payload = event.payload or {}
        space_id = context.get("space_id")
        if not space_id:
            return []

        space = db.get(Space, space_id)
        series_id = payload.get("series_id") or event.subject_id
        series = db.get(EventSeries, series_id) if series_id else None
        if series is None or not series_is_member_visible(db, series):
            return []

        collective_name = (
            context.get("collective_name")
            or (space.name if space else "your collective")
        )
        series_url = (
            f"/spaces/{space.slug}/gathering-series/{series.slug}"
            if space else None
        )

        rows = db.execute(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == "active",
            )
        ).scalars().all()

        out: list[ResolvedRecipient] = []
        for row in rows:
            if event.actor_user_id and row.user_id == event.actor_user_id:
                continue
            out.append(
                ResolvedRecipient(
                    user_id=row.user_id,
                    role_in_event="member_of_collective",
                    human_reason=f"You're a member of {collective_name}.",
                    template_context={
                        "collective_name": collective_name,
                        "series_id": series.id,
                        "series_title": payload.get("series_title"),
                        "starts_at": payload.get("starts_at"),
                        "ends_at": payload.get("ends_at"),
                        "session_count": payload.get("session_count"),
                        "description": payload.get("description"),
                        "series_url": series_url,
                        "space_id": space_id,
                    },
                )
            )
        return out


@resolver_for("gathering.recurrence.published")
class RecurrencePublishedResolver:
    """One announcement for a recurring schedule, to the whole
    Collective, bar the creator who published it.

    The same shape as ``GatheringPublishedResolver`` beside it, with
    one difference: the subject is a batch, so visibility is re-checked
    against the batch rather than a row. Routing runs in a background
    task after the response, so every occurrence can be unpublished or
    cancelled in the gap — and nobody should be emailed an invitation
    to a schedule that has since gone.

    The occurrences themselves never reach this point: a Gathering
    carrying a ``recurrence_series_id`` is refused by
    ``should_announce_gathering``, and one carrying a ``series_id`` is
    refused before this event is even written. So there is no
    de-duplication to do here between a schedule and its sessions, or
    between a schedule and a Series.
    """

    event_type = "gathering.recurrence.published"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        from app.models.platform import Space, SpaceMembership
        from app.services.publication_announcement import (
            recurrence_is_member_visible,
        )

        context = event.context or {}
        payload = event.payload or {}
        space_id = context.get("space_id")
        recurrence_series_id = (
            payload.get("recurrence_series_id") or event.subject_id
        )
        if not space_id or not recurrence_series_id:
            return []

        if not recurrence_is_member_visible(
            db, space_id, recurrence_series_id,
        ):
            return []

        space = db.get(Space, space_id)
        collective_name = (
            context.get("collective_name")
            or (space.name if space else "your collective")
        )
        # The Gatherings list, not an occurrence. It is where every date
        # in the schedule appears and where each one is booked, it is
        # not keyed to any single Gathering so editing or cancelling one
        # cannot break it, and it describes nothing as a package.
        gatherings_url = f"/spaces/{space.slug}/events" if space else None

        rows = db.execute(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == "active",
            )
        ).scalars().all()

        out: list[ResolvedRecipient] = []
        for row in rows:
            # The creator published it; they do not need telling.
            if event.actor_user_id and row.user_id == event.actor_user_id:
                continue
            out.append(
                ResolvedRecipient(
                    user_id=row.user_id,
                    role_in_event="member_of_collective",
                    human_reason=f"You're a member of {collective_name}.",
                    template_context={
                        "collective_name": collective_name,
                        "recurrence_series_id": recurrence_series_id,
                        "schedule_name": payload.get("schedule_name"),
                        "gathering_title": payload.get("gathering_title"),
                        "occurrence_count": payload.get("occurrence_count"),
                        "first_starts_at": payload.get("first_starts_at"),
                        "last_starts_at": payload.get("last_starts_at"),
                        "first_when": payload.get("first_when"),
                        "location_type": payload.get("location_type"),
                        "attendance_format": payload.get("attendance_format"),
                        "venue_locality": payload.get("venue_locality"),
                        "description": payload.get("description"),
                        "is_paid": payload.get("is_paid"),
                        "gatherings_url": gatherings_url,
                        "space_id": space_id,
                    },
                )
            )
        return out
