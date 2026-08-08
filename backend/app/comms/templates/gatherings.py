"""Templates for gathering category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT_BOOKING_CONFIRMED = "gathering.booking.confirmed"


def _title(recipient: ResolvedRecipient) -> str:
    return (recipient.template_context.get("gathering_title") or "your gathering").strip()


@template_for(_EVENT_BOOKING_CONFIRMED, CHANNEL_IN_APP)
class BookingConfirmedInAppTemplate:
    key = "gathering.booking.confirmed.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        return RenderedPayload(
            to="",
            subject=f"Booked: {_title(recipient)}",
            body_text="You're booked. We'll remind you closer to the time.",
            metadata={
                "notification_type": "booking_confirmed",
                "gathering_id": recipient.template_context.get("gathering_id"),
            },
        )


@template_for(_EVENT_BOOKING_CONFIRMED, CHANNEL_EMAIL_TRANSACTIONAL)
class BookingConfirmedEmailTemplate:
    key = "gathering.booking.confirmed.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        title = _title(recipient)
        starts_at = recipient.template_context.get("gathering_starts_at") or "the scheduled time"
        collective = recipient.template_context.get("collective_name") or "the collective"
        subject = f"Booked: {title}"
        body_text = (
            f"You're booked for {title} in {collective}, starting {starts_at}.\n\n"
            "We'll send a reminder closer to the time."
        )
        body_html = (
            f"<p>You're booked for <strong>{title}</strong> in {collective}, "
            f"starting {starts_at}.</p>"
            "<p>We'll send a reminder closer to the time.</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={
                "notification_type": "booking_confirmed",
                "gathering_id": recipient.template_context.get("gathering_id"),
            },
        )
