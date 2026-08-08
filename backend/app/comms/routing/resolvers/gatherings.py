"""Resolvers for gathering events.

M5b coverage: ``gathering.booking.confirmed`` — the single-recipient
immediate-priority example. The booker is the recipient.
"""

from __future__ import annotations

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
                },
            ),
        ]
