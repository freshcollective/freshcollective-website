"""Templates for community category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT_NEW_POST = "community.post.published"


@template_for(_EVENT_NEW_POST, CHANNEL_IN_APP)
class NewPostInAppTemplate:
    key = "community.post.published.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        collective = recipient.template_context.get("collective_name") or "your collective"
        excerpt = (recipient.template_context.get("excerpt") or "").strip()
        subject = f"New conversation in {collective}"
        body = excerpt or "A member has started a new conversation."
        return RenderedPayload(
            to="",
            subject=subject,
            body_text=body,
            metadata={
                "notification_type": "new_post",
                "post_id": recipient.template_context.get("post_id"),
                "space_id": recipient.template_context.get("space_id"),
            },
        )


@template_for(_EVENT_NEW_POST, CHANNEL_EMAIL_TRANSACTIONAL)
class NewPostEmailTemplate:
    key = "community.post.published.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        collective = recipient.template_context.get("collective_name") or "your collective"
        excerpt = (recipient.template_context.get("excerpt") or "").strip()
        subject = f"New conversation in {collective}"
        body_text = (
            f"Someone started a new conversation in {collective}.\n\n"
            + (excerpt + "\n\n" if excerpt else "")
            + "Open Fresh Collective to read and reply."
        )
        body_html = (
            f"<p>Someone started a new conversation in <strong>{collective}</strong>.</p>"
            + (f"<blockquote>{excerpt}</blockquote>" if excerpt else "")
            + "<p>Open Fresh Collective to read and reply.</p>"
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "new_post"},
        )
