"""Ways to Connect — the people the member shares something with.

One endpoint:

  * ``GET /api/ways-to-connect`` — who the signed-in member has
    genuinely crossed paths with, and what they share.

Gated by ``settings.ways_to_connect_enabled``. While that is off every
call returns 503, matching the convention set by Community Care and
followed by ``/api/places`` — a half-built surface should not be
discoverable by accident. Deliberately *not* ``discovery_pillar_enabled``:
Discover Places and Ways to Connect are separate pillars now and are
not ready at the same time.

``RecognitionService`` is the only authority on who may appear here.
This module does not query memberships, bookings, enrolments or
attendance, and it does not decide who is eligible. It asks the
service what the viewer shares, reads display names for the people
the service already returned, and chooses which few to feature. Any
future edit that reached past the service and into the substrate
would silently bypass the member's own ``ways_to_connect_enabled``
setting, the suspended/cancelled guards, the Collective visibility
gate, and every evidence rule at once.

The response is person-shaped because the question is. Internally a
``Recognition`` is already keyed by person — the service has never
been anything but person-first — so this route mostly gets out of its
way. What it adds is the selection: at most three, and only people
with two or more shared things between them. See
``ways_to_connect/selection.py`` for why one is not enough and how the
few are chosen without ranking anybody.
"""

from __future__ import annotations

from datetime import datetime

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
    PersonRef,
    SharedGatheringRef,
    SharedPathwayRef,
    WaysToConnectResponse,
)
from app.ways_to_connect.selection import MAX_PEOPLE, select_people

router = APIRouter(prefix="/api/ways-to-connect", tags=["ways-to-connect"])


#: Safety bound on how many people one response carries. Not
#: pagination — there is no second page and no cursor. A member with
#: more recognisable people than this has an unusual amount of
#: overlap; the surface features three of them either way, and the
#: tail exists only to feed the in-context lines.
MAX_PEOPLE_IN_PAYLOAD = 60


def _ensure_flag_on() -> None:
    """Refuse while Ways to Connect is not enabled on this deployment."""
    if not settings.ways_to_connect_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ways to Connect is not yet enabled on this deployment.",
        )


def _display_name(user: User, cp: CreatorProfile | None) -> str | None:
    """What to call someone on this surface, or None.

    A public CreatorProfile display name, else the member's own name,
    else nothing. Two things this deliberately does not do.

    It does not fall back to the local part of the email address, the
    way ``app.members.routes._display_name`` does — that hands out
    half of somebody's address to anyone sharing a Collective with
    them. (Separate surface, separate fix; not changed here.)

    And it does not invent a placeholder. Returning "Member" for
    everyone unnamed reads as three strangers called Member the moment
    there are three of them. Null says "there is no name here" and
    lets the frontend say something true about the group instead.
    """
    if cp and cp.display_name:
        return cp.display_name
    return user.name or None


def _people_index(
    db: Session, user_ids: set[str]
) -> dict[str, tuple[str | None, str | None]]:
    """(display_name, avatar_url) for people the service already returned.

    Presentation only. The ids come from ``RecognitionService``, which
    has already applied every eligibility and visibility rule; nothing
    here widens that set.
    """
    if not user_ids:
        return {}

    users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()

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

    out: dict[str, tuple[str | None, str | None]] = {}
    for u in users:
        cp = profiles.get(u.id)
        out[u.id] = (
            _display_name(u, cp),
            cp.avatar_url if cp else None,
        )
    return out


def _to_person(
    recognition: Recognition,
    name: str | None,
    avatar_url: str | None,
) -> PersonRef:
    """One Recognition as the person it has always been about."""
    shared: list[SharedGatheringRef | SharedPathwayRef] = []

    # Nearest to now first, in both directions: the soonest thing
    # ahead, then the most recent thing behind. A single ascending sort
    # would list the oldest attended Gathering first, which reads as a
    # history rather than "you were just in a room together".
    def _nearness(g):
        upcoming = g.basis is SharedGatheringBasis.UPCOMING
        stamp = g.starts_at.timestamp()
        return (not upcoming, stamp if upcoming else -stamp)

    for g in sorted(recognition.gatherings, key=_nearness):
        shared.append(
            SharedGatheringRef(
                id=g.gathering_id,
                title=g.title,
                starts_at=g.starts_at,
                basis=(
                    "upcoming"
                    if g.basis is SharedGatheringBasis.UPCOMING
                    else "attended"
                ),
                collective_id=g.collective_id,
            )
        )

    for p in recognition.pathways:
        shared.append(
            SharedPathwayRef(
                id=p.pathway_id,
                slug=p.slug,
                title=p.title,
                collective_id=p.collective_id,
                crossing_at=p.crossing_at,
            )
        )

    return PersonRef(
        id=recognition.other_user_id,
        display_name=name,
        avatar_url=avatar_url,
        collectives=[
            CollectiveRef(
                id=c.collective_id, slug=c.slug, name=c.name, timezone=c.timezone
            )
            for c in recognition.collectives
        ],
        shared=shared,
    )


@router.get("", response_model=WaysToConnectResponse)
def get_ways_to_connect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WaysToConnectResponse:
    """Who the signed-in member currently shares something with.

    The subject is the caller, always. There is no path, query or body
    parameter naming a member, so reading somebody else's Ways to
    Connect has no request shape to express — and since the featured
    few are chosen here rather than asked for, there is no way to
    request a particular person either.

    Returns an empty list — not a 403 — when the member has switched
    off ``ways_to_connect_enabled``. Their own setting is not an
    authorisation failure, and the service already answers "nothing"
    for them; the route does not need to know why.
    """
    _ensure_flag_on()

    now = datetime.utcnow()
    recognitions = RecognitionService.for_user(db, current_user.id, now=now)
    index = _people_index(db, {r.other_user_id for r in recognitions})

    # Only people we can name may be featured — a card introduces
    # somebody. Everyone else stays in the payload for the in-context
    # lines, which count them rather than naming them.
    #
    # ``select_people`` then applies the two-signal threshold, so
    # ``featured_count`` is routinely smaller than ``len(people)`` and
    # is often zero while the payload is not: a viewer who has been in
    # one room with three different people has three recognisable
    # people and nobody worth introducing. The in-context lines still
    # name them where they are; the destination stays quiet.
    nameable = [r for r in recognitions if index.get(r.other_user_id, (None, None))[0]]
    featured = select_people(nameable, now=now, limit=MAX_PEOPLE)
    featured_ids = [r.other_user_id for r in featured]
    featured_set = set(featured_ids)

    ordered = featured + [
        r for r in recognitions if r.other_user_id not in featured_set
    ]
    truncated = len(ordered) > MAX_PEOPLE_IN_PAYLOAD
    ordered = ordered[:MAX_PEOPLE_IN_PAYLOAD]

    people = [
        _to_person(r, *index.get(r.other_user_id, (None, None))) for r in ordered
    ]

    return WaysToConnectResponse(
        people=people,
        featured_count=len(featured_ids),
        truncated=truncated,
    )
