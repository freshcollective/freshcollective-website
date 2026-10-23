"""The Collective's welcome email — one emitter, every joining path.

Membership is created in nine places in this codebase, each with its own
``db.add(SpaceMembership(...))``. There is no single lifecycle function
to hook, so rather than let each route grow its own mail trigger — which
is how the paths drift apart — every one of them calls this.

What makes that safe is not discipline, it is the database. The partial
unique index on ``(event_type, dedupe_key)`` over
``communication_events`` means::

    collective_welcome:{space_id}:{user_id}

can exist at most once, ever. A second emit for the same person and
Collective is a no-op no matter which route attempts it, how many times
Stripe redelivers a webhook, or whether the member later leaves and
rejoins. Five separate product requirements therefore hold structurally
rather than by argument:

* idempotent sending;
* no duplicates from webhook retries;
* no welcome when an existing active member buys something else;
* no welcome when a removed member is reactivated;
* no need for the call sites to coordinate with each other.

A sixth call site added in a year's time inherits all of it.

What this does NOT do
---------------------

It does not decide whether somebody is a member, and it never writes
membership state. The caller establishes that a first-time active
membership was really created and passes it in; this only decides
whether that fact deserves an email.

Nothing retrospective is possible. The event is written at the moment of
joining and only then, so a Collective that switches welcomes on later
has no backlog to release — there is no event for members who joined
while it was off, and there never will be.

Sending is not done here either. This writes the event row inside the
caller's transaction; routing is scheduled by the caller *after commit*,
so no email can escape describing a membership that then rolled back.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

    from app.comms.models import CommunicationEvent
    from app.models.platform import Space
    from app.models.user import User

logger = logging.getLogger(__name__)

EVENT_TYPE = "collective.membership.welcome"

#: Membership origins that are not a person joining a Collective, and so
#: never produce a welcome. ``creator_owner`` is the creator's own
#: Collective — they built it, they are not a guest in it. ``auto_role``
#: is platform-computed membership (World Builders), granted and revoked
#: by eligibility rather than by any choice the member made.
EXCLUDED_SOURCES: frozenset[str] = frozenset({"creator_owner", "auto_role"})


def dedupe_key_for(space_id: str, user_id: str) -> str:
    """The one key that makes this exactly-once, forever.

    Deliberately carries no timestamp, transaction id or join source —
    those would all make a *second* welcome possible for the same person
    in the same Collective, which is the single thing this must prevent.
    """
    return f"collective_welcome:{space_id}:{user_id}"


def _never_breaks_fulfilment(fn):
    """A welcome email must never take down a payment.

    This runs inside the webhook's fulfilment transaction, beside the
    two purchase emits — and those are guarded for the same reason
    (``purchase_lifecycle_emit._safe_emit``: "a comms failure never
    propagates out to the payment/access lifecycle"). Without this, an
    exception here rolls the transaction back, Stripe retries, and a
    member who has paid is left without their access because a greeting
    could not be written.

    Returns ``None`` on failure, which every caller already handles —
    it is the same answer as "no welcome was due".
    """
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "collective_welcome: emit raised; the welcome is skipped and "
                "payment/membership are unaffected.",
            )
            return None
    _wrapped.__name__ = fn.__name__
    _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
    return _wrapped


@_never_breaks_fulfilment
def emit_collective_welcome(
    db: "Session",
    *,
    space: "Space",
    member: "User",
    join_source: str | None,
) -> "CommunicationEvent | None":
    """Write the welcome event, or decline with a reason in the log.

    Returns the event when one was written, ``None`` otherwise. The
    caller schedules routing for a non-``None`` return **after commit**.

    Declines, in order:

    1. the Collective has welcomes switched off;
    2. the membership origin is not a person joining (see
       ``EXCLUDED_SOURCES``);
    3. the member is the Collective's own creator;
    4. a welcome already exists for this pair — enforced by the unique
       index, so this check is a courtesy that keeps the log honest
       rather than the thing that holds the line.
    """
    from app.comms import Source, emit as comms_emit

    if not getattr(space, "welcome_email_enabled", True):
        logger.info(
            "collective_welcome: skipped space=%s user=%s reason=disabled",
            space.id, member.id,
        )
        return None

    if (join_source or "") in EXCLUDED_SOURCES:
        logger.info(
            "collective_welcome: skipped space=%s user=%s reason=source_%s",
            space.id, member.id, join_source,
        )
        return None

    # A creator does not need welcoming to their own Collective even if
    # their membership row happens to carry another source.
    if space.creator_id and space.creator_id == member.id:
        logger.info(
            "collective_welcome: skipped space=%s user=%s reason=is_creator",
            space.id, member.id,
        )
        return None

    payload = {
        "space_id":          space.id,
        "collective_name":   space.name or "",
        "member_first_name": _first_name(member),
        "creator_name":      _creator_name(db, space),
        "collective_url":    collective_url(space),
        "join_source":       join_source or "",
    }
    event = comms_emit(
        db,
        event_type=EVENT_TYPE,
        source_type=Source.COLLECTIVE,
        source_id=space.id,
        actor_user_id=member.id,
        subject_type="space",
        subject_id=space.id,
        context={"space_id": space.id},
        payload=payload,
        dedupe_key=dedupe_key_for(space.id, member.id),
    )
    if event is None:
        # The unique index refused it: this person has been welcomed to
        # this Collective before. Expected on reactivation and on a
        # redelivered webhook, so it is information, not a fault.
        logger.info(
            "collective_welcome: already sent space=%s user=%s — no second "
            "welcome", space.id, member.id,
        )
    return event


def collective_url(space: "Space") -> str:
    """Where the button goes. Generated, never creator-supplied.

    A creator may rename the button through the ``cta_label`` slot but
    has no field through which to change its destination — the same
    structural stance the editable-copy system takes everywhere: a slot
    exists for voice, never for a link.
    """
    from app.core.public_url import public_app_url

    return public_app_url(f"/spaces/{space.slug}")


def _first_name(member: "User") -> str:
    """First name only, and never an email local part.

    Falls back to an empty string; the template turns that into
    "there", so a greeting is never addressed to a blank.
    """
    from app.services.member_identity import display_name

    name = (display_name(member) or "").strip()
    if not name or "@" in name:
        return ""
    return name.split()[0]


def _creator_name(db: "Session", space: "Space") -> str:
    """Who runs this Collective. Empty for a platform-owned one."""
    if not space.creator_id:
        return ""
    from app.models.user import User
    from app.services.member_identity import display_name

    owner = db.query(User).filter(User.id == space.creator_id).first()
    return (display_name(owner) or "").strip() if owner else ""


def schedule_welcome(event: "CommunicationEvent | None") -> None:
    """Hand a welcome event to routing. Call **after** ``db.commit()``.

    A no-op for ``None``, so a call site can pass the emitter's result
    straight through without branching. The event-type string lives
    here rather than being retyped at each call site, because a typo
    there would route nothing and look exactly like "no welcome was
    due".
    """
    if event is None:
        return
    from app.comms.rollout import schedule_routing_if_needed

    schedule_routing_if_needed(None, event, EVENT_TYPE)
