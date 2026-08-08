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

        out: list[ResolvedRecipient] = []
        for row in rows:
            if author_id and row.user_id == author_id:
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
