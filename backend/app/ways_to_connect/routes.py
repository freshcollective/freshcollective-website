"""Ways to Connect — the member's own Recognition, read-only.

One endpoint:

  * ``GET /api/ways-to-connect`` — what the signed-in member
    currently shares with other people, grouped by the shared thing.

Gated by ``settings.ways_to_connect_enabled``. While that is off every
call returns 503, matching the convention set by Community Care and
followed by ``/api/places`` — a half-built surface should not be
discoverable by accident. Deliberately *not* ``discovery_pillar_enabled``:
Discover Places and Ways to Connect are separate pillars now and are
not ready at the same time.

``RecognitionService`` is the only authority on who appears here. This
module does not query memberships, bookings, enrolments or attendance,
and it does not decide who is eligible. It asks the service what the
viewer shares, then reads display names for the people the service
already returned. Any future edit that reaches past the service and
into the substrate would silently bypass the member's own
``ways_to_connect_enabled`` setting, the suspended/cancelled guards,
the Collective visibility gate, and every evidence rule at once.

The response inverts the service's shape on purpose. Internally
Recognition is person-oriented, because "what do these two share?" is
the question the rules answer. The API is experience-oriented, because
"who else was at Thursday's circle?" is the question a member is
actually asking, and because a person-keyed API is a directory
wearing a different hat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.platform import CreatorProfile
from app.models.user import User
from app.services.recognition_service import (
    Recognition,
    RecognitionService,
    SharedGatheringBasis,
)
from app.ways_to_connect.schemas import (
    CollectiveRef,
    GatheringContext,
    PathwayContext,
    PersonRef,
    WaysToConnectResponse,
)

router = APIRouter(prefix="/api/ways-to-connect", tags=["ways-to-connect"])


#: Safety bound on how many shared contexts one response carries.
#: Not pagination — there is no second page and no cursor. A member
#: with more shared experiences than this has an unusual amount of
#: overlap, and the surface is meant to be readable rather than
#: exhaustive. The cut is deterministic (see ``_ordered`` below), so
#: the same state always yields the same response.
MAX_CONTEXTS = 60


def _ensure_flag_on() -> None:
    """Refuse while Ways to Connect is not enabled on this deployment."""
    if not settings.ways_to_connect_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ways to Connect is not yet enabled on this deployment.",
        )


def _display_name(user: User, cp: CreatorProfile | None) -> str:
    """What to call someone on this surface.

    Deliberately *not* ``app.members.routes._display_name``, which
    falls back to the local part of the email address. That is a
    reasonable-looking fallback and it leaks half of somebody's email
    to anyone who shares a Collective with them. A member who has set
    no name is simply "Member" here; the shared context is what
    carries the meaning, not the label.
    """
    if cp and cp.display_name:
        return cp.display_name
    return user.name or "Member"


def _people_index(db: Session, user_ids: set[str]) -> dict[str, PersonRef]:
    """Names and avatars for people the service already returned.

    Presentation only. The ids come from ``RecognitionService``, which
    has already applied every eligibility and visibility rule; nothing
    here widens that set, and passing an id the service did not
    produce would simply render a person the caller already had.
    """
    if not user_ids:
        return {}

    users = db.execute(
        select(User).where(User.id.in_(user_ids))
    ).scalars().all()

    # Avatars come from a public CreatorProfile or not at all — the
    # same rule the public profile endpoint applies. Most members have
    # neither, which is the ordinary case.
    profiles = {
        cp.user_id: cp
        for cp in db.execute(
            select(CreatorProfile).where(
                CreatorProfile.user_id.in_(user_ids),
                CreatorProfile.is_public.is_(True),
            )
        ).scalars().all()
    }

    return {
        u.id: PersonRef(
            id=u.id,
            display_name=_display_name(u, profiles.get(u.id)),
            avatar_url=profiles[u.id].avatar_url if u.id in profiles else None,
        )
        for u in users
    }


def _to_contexts(
    recognitions: list[Recognition],
    people: dict[str, PersonRef],
) -> list[GatheringContext | PathwayContext]:
    """Turn person-keyed Recognitions inside out into shared contexts.

    One person may legitimately appear in several contexts — the same
    people tend to show up at the same circle and on the same Pathway,
    and collapsing that would lose the thing worth saying. What never
    happens is the reverse: a person without a context.
    """
    collectives: dict[str, CollectiveRef] = {}
    gatherings: dict[str, dict] = {}
    pathways: dict[str, dict] = {}

    for recog in recognitions:
        person = people.get(recog.other_user_id)
        if person is None:
            # The row vanished between derivation and hydration.
            # Dropping is correct: we will not render someone we
            # cannot name.
            continue

        for c in recog.collectives:
            collectives.setdefault(
                c.collective_id,
                CollectiveRef(id=c.collective_id, slug=c.slug, name=c.name),
            )

        for g in recog.gatherings:
            entry = gatherings.setdefault(
                g.gathering_id,
                {
                    "id": g.gathering_id,
                    "title": g.title,
                    "starts_at": g.starts_at,
                    "basis": (
                        "upcoming"
                        if g.basis is SharedGatheringBasis.UPCOMING
                        else "attended"
                    ),
                    "collective_id": g.collective_id,
                    "people": {},
                },
            )
            entry["people"][person.id] = person

        for p in recog.pathways:
            entry = pathways.setdefault(
                p.pathway_id,
                {
                    "id": p.pathway_id,
                    "slug": p.slug,
                    "title": p.title,
                    "collective_id": p.collective_id,
                    "people": {},
                },
            )
            entry["people"][person.id] = person

    def _sorted_people(entry) -> list[PersonRef]:
        return sorted(
            entry["people"].values(), key=lambda r: (r.display_name, r.id)
        )

    upcoming = [
        GatheringContext(
            id=e["id"], title=e["title"], starts_at=e["starts_at"],
            basis="upcoming", collective=collectives[e["collective_id"]],
            people=_sorted_people(e),
        )
        for e in gatherings.values()
        if e["basis"] == "upcoming" and e["collective_id"] in collectives
    ]
    attended = [
        GatheringContext(
            id=e["id"], title=e["title"], starts_at=e["starts_at"],
            basis="attended", collective=collectives[e["collective_id"]],
            people=_sorted_people(e),
        )
        for e in gatherings.values()
        if e["basis"] == "attended" and e["collective_id"] in collectives
    ]
    walked = [
        PathwayContext(
            id=e["id"], slug=e["slug"], title=e["title"],
            collective=collectives[e["collective_id"]],
            people=_sorted_people(e),
        )
        for e in pathways.values()
        if e["collective_id"] in collectives
    ]

    # Nearest to now first, then the things being walked, then what
    # has already happened. Every tie is broken by id so the order is
    # total and the same state always serialises identically.
    upcoming.sort(key=lambda c: (c.starts_at, c.id))
    attended.sort(key=lambda c: (c.starts_at, c.id), reverse=True)
    walked.sort(key=lambda c: (c.title, c.id))

    return [*upcoming, *walked, *attended]


@router.get("", response_model=WaysToConnectResponse)
def get_ways_to_connect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WaysToConnectResponse:
    """What the signed-in member currently shares with other people.

    The subject is the caller, always. There is no path, query or body
    parameter naming a member, so reading somebody else's Ways to
    Connect has no request shape to express.

    Returns an empty list — not a 403 — when the member has switched
    off ``ways_to_connect_enabled``. Their own setting is not an
    authorisation failure, and the service already answers "nothing"
    for them; the route does not need to know why.
    """
    _ensure_flag_on()

    recognitions = RecognitionService.for_user(db, current_user.id)
    people = _people_index(
        db, {r.other_user_id for r in recognitions}
    )
    contexts = _to_contexts(recognitions, people)

    truncated = len(contexts) > MAX_CONTEXTS
    return WaysToConnectResponse(
        contexts=contexts[:MAX_CONTEXTS],
        truncated=truncated,
    )
