"""Templates for pathway category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for


_EVENT_PATHWAY_PUBLISHED = "pathway.published"


@template_for(_EVENT_PATHWAY_PUBLISHED, CHANNEL_IN_APP)
class PathwayPublishedInAppTemplate:
    key = "pathway.published.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        collective = recipient.template_context.get("collective_name") or "your collective"
        pathway = recipient.template_context.get("pathway_title") or "a new pathway"
        return RenderedPayload(
            to="",
            subject=f"New pathway in {collective}",
            body_text=f"{pathway} is available in {collective}.",
            metadata={
                "notification_type": "new_pathway",
                "pathway_id": recipient.template_context.get("pathway_id"),
                "space_id": recipient.template_context.get("space_id"),
            },
        )


@template_for(_EVENT_PATHWAY_PUBLISHED, CHANNEL_EMAIL_TRANSACTIONAL)
class PathwayPublishedEmailTemplate:
    key = "pathway.published.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        collective = recipient.template_context.get("collective_name") or "your collective"
        pathway = recipient.template_context.get("pathway_title") or "a new pathway"
        r = resolver_for(db, self.key, recipient.template_context)
        subject = r.text("subject")
        opening = r.text("body.opening")
        closing = r.text("body.closing")
        body_text = (
            f"{opening}\n\n"
            f"{closing}"
        )
        # No CTA: this event's template_context carries no pathway URL.
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, closing],
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "new_pathway"},
        )
