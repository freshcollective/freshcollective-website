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
        ctx = dict(recipient.template_context)
        excerpt = (ctx.get("excerpt") or "").strip()
        view_url = ctx.get("view_url") or ""

        # A post by somebody who is not a caretaker of this Collective
        # is not a creator announcement, so it is not framed as one.
        # ``is_creator_post`` is decided at the emit site with
        # ``is_caretaker_here``, which is why a platform administrator
        # posting in somebody else's Collective reads as a member.
        if not ctx.get("is_creator_post"):
            ctx["author_name"] = ctx.get("author_name") or "Someone"
        # Channel name is used in the default copy, so it must never
        # render as an empty gap in a sentence.
        if not ctx.get("channel_name"):
            ctx["channel_name"] = "the conversation"

        r = resolver_for(db, self.key, ctx)
        subject = r.text("subject")
        opening = r.text("body.opening")
        closing = r.text("body.closing")
        cta = r.text("cta_label")

        text_parts = [opening]
        if excerpt:
            text_parts.append(excerpt)
        text_parts.append(closing)
        if view_url:
            text_parts.append(view_url)
        body_text = "\n\n".join(text_parts)

        # An empty excerpt is dropped by the shell. The action is
        # omitted rather than rendered as a dead button when no URL
        # reached us — which is what the old template had to do for
        # every send, because nothing put one in the payload.
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, excerpt, closing],
            action=(cta, view_url) if view_url else None,
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
