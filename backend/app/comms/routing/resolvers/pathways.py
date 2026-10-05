"""Resolvers for pathway events.

M5b coverage: ``pathway.published`` — every active space member is a
recipient. Structurally similar to ``community.post.published``; kept
separate so future pathway-specific logic (e.g. only members enrolled
in adjacent pathways) can live here without disturbing community
routing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("pathway.published")
class PathwayPublishedResolver:
    event_type = "pathway.published"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        space_id = (event.context or {}).get("space_id")
        if not space_id:
            return []
        from app.models.platform import Space, SpaceMembership

        space = db.get(Space, space_id)
        collective_name = (event.context or {}).get("collective_name") or (
            space.name if space else "your collective"
        )
        pathway_title = (event.payload or {}).get("pathway_title") or "a new pathway"

        # Re-check availability at routing time, not just at emit time.
        #
        # Routing runs in a background task after the response, so the
        # Pathway can be returned to draft, archived, or its Collective
        # closed in the gap. Nobody should be emailed a link to content
        # they cannot open — the same rule the emit applied, applied
        # again at the moment recipients are chosen.
        from app.models.platform import Pathway
        from app.services.pathway_announcement import is_member_visible

        pathway_id = (event.payload or {}).get("pathway_id") or event.subject_id
        pathway = db.get(Pathway, pathway_id) if pathway_id else None
        if pathway is None or not is_member_visible(db, pathway):
            return []

        # The CTA destination. Previously absent, which left the email
        # with nothing to click — see the template.
        pathway_url = (
            f"/spaces/{space.slug}/pathways/{pathway.slug}" if space else None
        )

        rows = db.execute(
            select(SpaceMembership).where(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == "active",
            )
        ).scalars().all()

        out: list[ResolvedRecipient] = []
        for row in rows:
            out.append(
                ResolvedRecipient(
                    user_id=row.user_id,
                    role_in_event="member_of_collective",
                    human_reason=f"You're a member of {collective_name}.",
                    template_context={
                        "collective_name": collective_name,
                        "pathway_id": event.subject_id,
                        "pathway_title": pathway_title,
                        "space_id": space_id,
                        "pathway_url": pathway_url,
                    },
                )
            )
        return out
