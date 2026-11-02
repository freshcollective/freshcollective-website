"""Resolvers for community events.

M5b coverage: ``community.post.published`` — the one-to-many
category example. Every active member of the space (except the
author) is a recipient with role ``member_of_collective``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("community.post.published")
class NewPostResolver:
    event_type = "community.post.published"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        space_id = (event.context or {}).get("space_id")
        collective_name = (event.context or {}).get("collective_name")
        author_id = event.actor_user_id
        if not space_id:
            return []

        # Local imports so the resolvers package doesn't drag the
        # whole domain graph in at comms import time.
        from app.models.platform import Space, SpaceMembership

        space = db.get(Space, space_id)
        display_name = collective_name or (space.name if space else "your collective")

        rows = db.execute(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == "active",
            )
        ).scalars().all()

        # Scope to the channel's audience. "Every active member" is
        # right for the Common Room and wrong for everything else: a
        # post in a private or linked channel was reaching the whole
        # Collective, excerpt included, because this resolver never
        # looked at which channel the post was in.
        allowed: set[str] | None = None
        channel_id = (event.context or {}).get("channel_id")
        if channel_id and space is not None:
            from app.models.platform import ConversationChannel
            from app.services.channel_permissions import (
                accessible_user_ids_for_channel,
            )

            channel = db.get(ConversationChannel, channel_id)
            if channel is not None and channel.channel_type not in (
                "start_here", "general", "open",
            ):
                allowed = accessible_user_ids_for_channel(channel, space, db)

        out: list[ResolvedRecipient] = []
        for row in rows:
            if author_id and row.user_id == author_id:
                continue
            if allowed is not None and row.user_id not in allowed:
                continue
            out.append(
                ResolvedRecipient(
                    user_id=row.user_id,
                    role_in_event="member_of_collective",
                    human_reason=f"You're a member of {display_name}.",
                    template_context={
                        "collective_name": display_name,
                        "space_id": space_id,
                        "post_id": (event.payload or {}).get("post_id"),
                        "excerpt": (event.payload or {}).get("excerpt"),
                    },
                )
            )
        return out


@resolver_for("community.comment.created")
class CommentCreatedResolver:
    """R2A — single-recipient resolver: only the post author is
    notified (the comment reply is theirs to read).

    Self-notification defence in depth: even though the community
    routes emit site already skips the event when the commenter is
    the post author (see the ``if post.author_id != current_user.id``
    guard in ``community/routes.py``), the resolver still filters
    ``event.actor_user_id == payload.post_author_id`` so a future
    emit site — or a test harness — cannot accidentally cause a
    self-notification. Matches ``NewPostResolver``'s "skip the
    author" pattern.
    """

    event_type = "community.comment.created"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        author_id = payload.get("post_author_id")
        if not isinstance(author_id, str) or not author_id:
            return []
        # Defence in depth: never notify the commenter about their
        # own comment.
        if event.actor_user_id and event.actor_user_id == author_id:
            return []
        return [
            ResolvedRecipient(
                user_id=author_id,
                role_in_event="post_author",
                human_reason="Someone replied to a conversation you started.",
                template_context={
                    "commenter_name": payload.get("commenter_name") or "Someone",
                    "post_title":     payload.get("post_title") or "your post",
                    "view_url":       payload.get("view_url") or "",
                    "post_id":        payload.get("post_id"),
                    "comment_id":     payload.get("comment_id"),
                    "space_id":       (event.context or {}).get("space_id"),
                },
            ),
        ]
