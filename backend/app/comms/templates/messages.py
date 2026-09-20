"""Templates for direct-message events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for


_EVENT_DM_SENT = "dm.message.sent"


@template_for(_EVENT_DM_SENT, CHANNEL_IN_APP)
class DirectMessageInAppTemplate:
    key = "dm.message.sent.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        sender = recipient.template_context.get("sender_name") or "A member"
        excerpt = (recipient.template_context.get("excerpt") or "").strip()
        return RenderedPayload(
            to="",
            subject=f"{sender} sent you a message",
            body_text=excerpt or "You have a new message.",
            metadata={
                "notification_type": "direct_message",
                "thread_id": recipient.template_context.get("thread_id"),
            },
        )


@template_for(_EVENT_DM_SENT, CHANNEL_EMAIL_TRANSACTIONAL)
class DirectMessageEmailTemplate:
    key = "dm.message.sent.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        sender = recipient.template_context.get("sender_name") or "A member"
        excerpt = (recipient.template_context.get("excerpt") or "").strip()
        r = resolver_for(db, self.key, recipient.template_context)
        subject = r.text("subject")
        opening = r.text("body.opening")
        closing = r.text("body.closing")
        body_text = (
            f"{opening}\n\n"
            + (excerpt + "\n\n" if excerpt else "")
            + closing
        )
        # No CTA: this event's template_context carries no thread URL.
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, excerpt, closing],
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={
                "notification_type": "direct_message",
                "thread_id": recipient.template_context.get("thread_id"),
            },
        )
