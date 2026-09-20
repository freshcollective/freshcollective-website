"""Templates for community category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
from app.comms.templates.registry import template_for


_EVENT_NEW_POST = "community.post.published"
_EVENT_COMMENT_CREATED = "community.comment.created"


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
        r = resolver_for(db, self.key, recipient.template_context)
        subject = r.text("subject")
        opening = r.text("body.opening")
        closing = r.text("body.closing")
        body_text = (
            f"{opening}\n\n"
            + (excerpt + "\n\n" if excerpt else "")
            + closing
        )
        # No CTA: this event's template_context carries no post URL.
        # An empty excerpt is dropped by the shell.
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
            metadata={"notification_type": "new_post"},
        )


@template_for(_EVENT_COMMENT_CREATED, CHANNEL_IN_APP)
class CommentCreatedInAppTemplate:
    key = "community.comment.created.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        commenter = ctx.get("commenter_name") or "Someone"
        post_title = ctx.get("post_title") or "your post"
        subject = "New reply on your post"
        body = f'{commenter} replied to "{post_title}".'
        return RenderedPayload(
            to="",
            subject=subject,
            body_text=body,
            metadata={
                "notification_type": "comment_reply",
                # Preserved so the in-app row's click-through matches
                # the legacy trigger's URL exactly.
                "url": ctx.get("view_url"),
                "post_id": ctx.get("post_id"),
                "comment_id": ctx.get("comment_id"),
                "space_id": ctx.get("space_id"),
            },
        )


@template_for(_EVENT_COMMENT_CREATED, CHANNEL_EMAIL_TRANSACTIONAL)
class CommentCreatedEmailTemplate:
    key = "community.comment.created.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        commenter = ctx.get("commenter_name") or "Someone"
        post_title = ctx.get("post_title") or "your post"
        view_url = ctx.get("view_url") or ""

        r = resolver_for(db, self.key, ctx)
        subject = r.text("subject")
        opening = r.text("body.opening")
        cta = r.text("cta_label")
        body_text = (
            f"{opening}\n\n"
            "Open the conversation to read and respond:\n"
            f"{view_url}"
        )
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening],
            action=(cta, view_url),
        )
        return RenderedPayload(
            to="",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "comment_reply"},
        )
