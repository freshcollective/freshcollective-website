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
from uuid import uuid4

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
from app.services.member_identity import optional_display_name
from app.services.member_image import MemberCardArtwork, MemberImagePayload
from app.ways_to_connect.schemas import (
    SayHelloResponse,
    CollectiveRef,
    PersonRef,
    SharedGatheringRef,
    SharedPathwayRef,
    WaysToConnectResponse,
)
from app.creator.plan_guards import is_platform_owner
from app.ways_to_connect.hello_service import (
    HelloState,
    hello_states,
    incoming_hello_senders,
    say_hello,
)
from app.ways_to_connect.selection import (
    MAX_PEOPLE,
    is_eligible_pair,
    select_people,
)

router = APIRouter(prefix="/api/ways-to-connect", tags=["ways-to-connect"])


#: Safety bound on how many people one response carries. Not
#: pagination — there is no second page and no cursor. A member with
#: more recognisable people than this has an unusual amount of
#: overlap; the surface features three of them either way, and the
#: tail exists only to feed the in-context lines.
MAX_PEOPLE_IN_PAYLOAD = 60


def ways_to_connect_available(user: User) -> bool:
    """May this caller use Ways to Connect at all?

    The launch flag, or Platform Owner — the one private-preview
    exception, so Lindsey can test the real production experience
    before the flag is flipped for everybody.

    ``is_platform_owner`` is reused rather than re-derived: it is the
    documented single source of truth for the owner identity, so there
    is no email comparison, no hard-coded user id, and no query-string
    or cookie back door anywhere in this gate.

    Scope is deliberately one thing — the **launch flag**. Platform
    Owner bypasses nothing else: eligibility, the mutual-hello
    requirement, thread participation and the block rules all still
    apply to the owner exactly as they apply to a member, because none
    of them consult this function. Once the flag is on this returns
    True for everyone and the owner has no remaining difference.

    Removing the preview is deleting the second clause.
    """
    return settings.ways_to_connect_enabled or is_platform_owner(user)


def _ensure_available(user: User) -> None:
    """Refuse unless the caller may use Ways to Connect.

    The 503 and its wording are unchanged, so an ordinary member — and
    an unauthenticated visitor, who never reaches here — sees exactly
    what they saw before the preview existed.
    """
    if not ways_to_connect_available(user):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ways to Connect is not yet enabled on this deployment.",
        )


def _display_name(user: User, cp: CreatorProfile | None) -> str | None:
    """What to call someone on this surface, or None.

    Ways to Connect is the surface that may say nothing, so it takes the
    optional end of the shared naming ladder rather than the neutral one.
    A person with no name is dropped from the cards entirely (see the
    ``nameable`` filter below): returning "Member" for everyone unnamed
    reads as three strangers called Member the moment there are three of
    them, where null says "there is no name here" and lets the frontend
    say something true about the group instead.

    Neither end of the ladder falls back to the local part of the email
    address any more — ``member_identity`` explains why.
    """
    return optional_display_name(user, cp)


def _people_index(
    db: Session, user_ids: set[str]
) -> dict[str, tuple[str | None, CreatorProfile | None]]:
    """(display_name, profile) for people the service already returned.

    Presentation only. The ids come from ``RecognitionService``, which
    has already applied every eligibility and visibility rule; nothing
    here widens that set. The profile row travels with the name so
    ``member_image`` can resolve the picture — this route does not
    decide what a member looks like.
    """
    if not user_ids:
        return {}

    users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()

    # Filtered on ``is_public`` because a private profile must not
    # supply a display name here either — long-standing behaviour on
    # every member surface, unchanged. ``visible_photo_url`` applies the
    # same rule again inside the resolver, so a row reaching it
    # unfiltered would still be handled correctly.
    profiles = {
        cp.user_id: cp
        for cp in db.execute(
            select(CreatorProfile).where(
                CreatorProfile.user_id.in_(user_ids),
                CreatorProfile.is_public.is_(True),
            )
        ).scalars().all()
    }

    return {u.id: (_display_name(u, profiles.get(u.id)), profiles.get(u.id)) for u in users}


def _to_person(
    recognition: Recognition,
    name: str | None,
    profile: CreatorProfile | None,
    artwork: MemberCardArtwork,
    relationship: HelloState = HelloState.NONE,
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

    image = MemberImagePayload.resolve(
        display_name=name, profile=profile, artwork=artwork
    )
    return PersonRef(
        id=recognition.other_user_id,
        display_name=name,
        avatar_url=image.url if image.kind == "photo" else None,
        image=image,
        relationship=relationship.value,
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
    _ensure_available(current_user)

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
    artwork = MemberCardArtwork.load(db)
    featured = select_people(nameable, now=now, limit=MAX_PEOPLE)
    featured_ids = [r.other_user_id for r in featured]
    featured_set = set(featured_ids)

    # Somebody greeting you should not be buried because that day's
    # rotation put them outside the featured few. Incoming hellos are
    # lifted to the front of the featured block — they are the one thing
    # on this page that is waiting on the viewer rather than offered to
    # them. Only nameable people can be lifted, for the same reason only
    # nameable people can be featured: a card introduces somebody.
    incoming = incoming_hello_senders(db, current_user.id)
    waiting = [
        r for r in nameable
        if r.other_user_id in incoming and r.other_user_id not in featured_set
    ]
    ordered = waiting + featured + [
        r for r in recognitions
        if r.other_user_id not in featured_set
        and r.other_user_id not in {w.other_user_id for w in waiting}
    ]
    truncated = len(ordered) > MAX_PEOPLE_IN_PAYLOAD
    ordered = ordered[:MAX_PEOPLE_IN_PAYLOAD]

    # One query for the whole page rather than one per card.
    states = hello_states(
        db, current_user.id, {r.other_user_id for r in ordered},
    )

    people = [
        _to_person(
            r, *index.get(r.other_user_id, (None, None)), artwork,
            states.get(r.other_user_id, HelloState.NONE),
        )
        for r in ordered
    ]

    return WaysToConnectResponse(
        people=people,
        # The frontend slices the first ``featured_count`` people as the
        # cards, so lifting incoming hellos to the front has to count
        # them too — otherwise the slice would cut the featured people
        # off the end by exactly the number of hellos waiting.
        #
        # A waiting person is carded whether or not they are still
        # eligible: evidence can lapse after a hello, and a greeting
        # already sent is not withdrawn because an upcoming Gathering
        # has since passed.
        featured_count=len(waiting) + len(featured_ids),
        truncated=truncated,
    )


def _viewer_display_name(db: Session, user: User) -> str | None:
    """The greeter's own name, for the notification the other side reads."""
    profile = (
        db.query(CreatorProfile)
        .filter(CreatorProfile.user_id == user.id)
        .first()
    )
    return _display_name(user, profile)


def _notify(
    db: Session, recipient_id: str, notification_type: str,
    title: str, message: str,
) -> None:
    """Queue one in-app notification inside the caller's transaction.

    Written directly rather than through
    ``notification_service.create_notification``, which commits — the
    hello and its notification must land together, so the route keeps
    the transaction boundary.
    """
    from app.models.notification import Notification

    db.add(Notification(
        id=str(uuid4()),
        user_id=recipient_id,
        notification_type=notification_type,
        title=title,
        message=message,
        url="/ways-to-connect",
        is_read=False,
    ))

#: In-app notification types for the two moments worth telling someone
#: about. Deliberately no evidence in the text: "you were both at X"
#: would publish a shared history into a notification surface that the
#: card already states in context and with consent of the page.
NOTIFY_HELLO_RECEIVED = "ways_to_connect_hello_received"
NOTIFY_CONNECTED = "ways_to_connect_connected"


def _first_name(name: str | None) -> str:
    """The part of a display name a greeting should use."""
    if not name:
        return "Someone"
    return name.strip().split()[0] or "Someone"


@router.post("/{user_id}/hello", response_model=SayHelloResponse)
def post_say_hello(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SayHelloResponse:
    """Say hello to someone the viewer currently shares enough with.

    Authorisation reuses the canonical rule rather than restating it:
    ``RecognitionService.for_user`` derives what the pair shares (and
    silently excludes anyone who has switched off their own
    participation), and ``is_eligible_pair`` applies the same
    two-signals-one-realised threshold ``select_people`` uses for
    display. Knowing a user id is not sufficient and never becomes
    sufficient.

    404 for every refusal that is about *who* the target is — ineligible,
    unnameable, nonexistent, opted out. A distinct 403 for "you may not
    greet this person" would answer the question the 404 exists to
    refuse, turning the endpoint into a probe for who shares what with
    whom. Self-hello is a 400 because it reveals nothing.

    Already-sent is a success with the current state, not a conflict:
    the card is optimistic, and a retry or a double click should agree
    with the first answer rather than surface an error.
    """
    _ensure_available(current_user)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot say hello to yourself.",
        )

    now = datetime.utcnow()
    recognitions = RecognitionService.for_user(db, current_user.id, now=now)

    # Nameable for the same reason a card requires it: a greeting
    # addresses a person, and we do not introduce someone we cannot name.
    index = _people_index(db, {user_id})
    name, _profile = index.get(user_id, (None, None))
    if not name or not is_eligible_pair(recognitions, user_id, now=now):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That person is not available to greet right now.",
        )

    state, created = say_hello(db, current_user.id, user_id)
    mutual = state is HelloState.MUTUAL
    # The *transition*, not the state: true only on the request that
    # completed the pair, so a reload or a double click does not make
    # the client celebrate twice.
    became_mutual = mutual and created

    # Notify only on a genuine transition. ``say_hello`` is idempotent,
    # so a repeat click reaches here with the state unchanged; keying the
    # notification on whether a row was actually created is what keeps a
    # double click, a retry and a reload from each announcing themselves.
    if created:
        viewer_name = _first_name(_viewer_display_name(db, current_user))
        if mutual:
            # Both sides hear about a connection; only the second
            # greeter's request knows it happened.
            for recipient, other in (
                (user_id, viewer_name),
                (current_user.id, _first_name(name)),
            ):
                _notify(
                    db, recipient, NOTIFY_CONNECTED,
                    "You have both said hello",
                    f"You and {other} have both said hello \U0001F44B",
                )
        else:
            _notify(
                db, user_id, NOTIFY_HELLO_RECEIVED,
                f"{viewer_name} said hello",
                f"{viewer_name} said hello \U0001F44B — you can say hello back.",
            )

    db.commit()
    return SayHelloResponse(relationship=state.value, became_mutual=became_mutual)
