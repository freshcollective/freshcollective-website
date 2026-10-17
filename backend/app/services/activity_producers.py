"""Shared Collective activity — the five producers.

Notifications 2.0, Phase 1. Each function records that a piece of
Collective content became available to members, once, as a single
shared ``activities`` row. Nothing here targets a person: who may see
the row is decided when it is read, from the permissions that already
govern the content.

Three rules hold for every producer in this module, and the tests
enforce all three.

**Nothing is produced for content members cannot reach.** Availability
is not re-litigated here — Pathways go through
``pathway_announcement.is_member_visible``, which already encodes the
stricter "available now" rule (``active``, not ``coming_soon``, and the
Collective itself reachable). That rule exists because draft steps were
once announced to everybody with links they could not open; writing a
second opinion about what "published" means is how that recurs.

**Nothing here can send an email.** This module imports no comms
dispatcher, and a source-contract test asserts it never will. General
Collective activity is a quiet signal, not a message, and the cheapest
way to guarantee that is to make the capability absent rather than
merely unused.

**Nothing here raises.** A failure to record activity must never fail
the publish that triggered it. Every producer is called for its effect
and swallows its own errors into a log line.

Deferred, deliberately
----------------------
Steps whose release is per member — ``days_after_enrollment``,
``after_previous``, ``manual`` — produce nothing. They open at a
different moment for each member, so a shared row cannot describe them,
and emitting one at publish time would count content the member cannot
open.

``fixed_date`` is deferred for the same practical reason: the step
becomes available when the clock passes ``release_at``, and no existing
scheduler watches for that. Detecting it needs a new scheduled service,
which is a product decision rather than an implementation detail.

Both are recorded in the Notifications 2.0 roadmap as a later phase.
``Activity.recipient_user_id`` stays nullable precisely so that phase
can write per-recipient rows into this same table.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.activity import ActivityType
from app.models.platform import (
    CommunityPost,
    Event,
    EventSeries,
    Pathway,
    PathwayStep,
    Space,
)
from app.services.activity_service import ActivityService

logger = logging.getLogger(__name__)

#: Release types whose availability is the same moment for everyone.
#: Only these can be described by a shared row. See the module
#: docstring for why ``fixed_date`` is not among them yet.
GLOBAL_RELEASE_TYPES = frozenset({"immediate"})


# ---------------------------------------------------------------------------
# Dedupe keys — one per piece of content.
#
# Steps key on the step, not the Pathway, so publishing a further step
# into a live Pathway produces new activity. A Series keys on the
# Series, so twenty occurrences can never become twenty rows.
# ---------------------------------------------------------------------------

def pathway_key(pathway_id: str, space_id: str) -> str:
    return f"pathway.published:{pathway_id}:{space_id}"


def step_key(step_id: str) -> str:
    return f"pathway.step:{step_id}"


def thread_key(post_id: str) -> str:
    return f"conversation.created:{post_id}"


def gathering_key(event_id: str) -> str:
    return f"gathering.created:{event_id}"


def series_key(series_id: str) -> str:
    return f"gathering.series:{series_id}"


def _space_of(db: Session, space_id: str) -> Space | None:
    return db.query(Space).filter(Space.id == space_id).first()


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------

def record_pathway_published(
    db: Session, pathway: Pathway, *, actor_user_id: str | None = None,
) -> None:
    """A Pathway became available to members of its Collective."""
    try:
        from app.services.pathway_announcement import is_member_visible

        if not is_member_visible(db, pathway):
            return
        space = _space_of(db, pathway.space_id)
        if space is None:
            return
        ActivityService.create_shared(
            db,
            event_type=ActivityType.pathway_published,
            dedupe_key=pathway_key(pathway.id, pathway.space_id),
            collective_id=pathway.space_id,
            actor_user_id=actor_user_id,
            pathway_id=pathway.id,
            payload={
                "title": pathway.title,
                "url": f"/spaces/{space.slug}/pathways/{pathway.slug}",
            },
        )
    except Exception:
        logger.exception(
            "activity: pathway_published failed for %s", getattr(pathway, "id", "?"),
        )


def record_step_published(
    db: Session, step: PathwayStep, *, actor_user_id: str | None = None,
) -> None:
    """A step became available inside an already-available Pathway.

    Silent unless the step opens for everyone at once. A drip step is a
    per-member event and is deferred; see the module docstring.
    """
    try:
        from app.services.pathway_announcement import is_member_visible

        if (step.release_type or "immediate") not in GLOBAL_RELEASE_TYPES:
            return
        pathway = db.query(Pathway).filter(Pathway.id == step.pathway_id).first()
        if pathway is None or not is_member_visible(db, pathway):
            return
        space = _space_of(db, pathway.space_id)
        if space is None:
            return
        ActivityService.create_shared(
            db,
            event_type=ActivityType.pathway_step_released,
            dedupe_key=step_key(step.id),
            collective_id=pathway.space_id,
            actor_user_id=actor_user_id,
            pathway_id=pathway.id,
            payload={
                "title": step.title,
                "pathway_title": pathway.title,
                "url": f"/spaces/{space.slug}/pathways/{pathway.slug}/{step.slug}",
            },
        )
    except Exception:
        logger.exception(
            "activity: pathway_step_released failed for %s", getattr(step, "id", "?"),
        )


def record_thread_created(
    db: Session, post: CommunityPost, *, actor_user_id: str | None = None,
) -> None:
    """A discussion thread was published into a Conversations channel.

    Scheduled posts reach this through the same call when they are
    published, so a post written days earlier produces activity at the
    moment it appears, not when it was drafted.
    """
    try:
        if getattr(post, "publication_status", "published") != "published":
            return
        space = _space_of(db, post.space_id)
        if space is None or space.status != "active":
            return
        ActivityService.create_shared(
            db,
            event_type=ActivityType.conversation_created,
            dedupe_key=thread_key(post.id),
            collective_id=post.space_id,
            actor_user_id=actor_user_id or getattr(post, "author_id", None),
            conversation_id=post.id,
            payload={
                # Last-resort wording only. An untitled discussion is
                # given its opening line on read instead — see
                # ``ActivityService.display_titles`` — so this is what
                # shows when a post has neither a title nor any text.
                # Deliberately not removed: the payload must still say
                # something if the read-time resolver ever cannot.
                "title": (getattr(post, "title", None) or "New conversation"),
                "url": f"/spaces/{space.slug}/community/{post.id}",
            },
        )
    except Exception:
        logger.exception(
            "activity: conversation_created failed for %s", getattr(post, "id", "?"),
        )


def record_gathering_published(
    db: Session, event: Event, *, actor_user_id: str | None = None,
) -> None:
    """A single Gathering was published.

    An occurrence belonging to a Series produces nothing: the Series is
    the offering members are told about, and counting both would make
    one offering look like twenty.
    """
    try:
        if getattr(event, "series_id", None):
            return
        if not event.is_published or event.status != "active":
            return
        space = _space_of(db, event.space_id)
        if space is None or space.status != "active":
            return
        ActivityService.create_shared(
            db,
            event_type=ActivityType.gathering_created,
            dedupe_key=gathering_key(event.id),
            collective_id=event.space_id,
            actor_user_id=actor_user_id,
            gathering_id=event.id,
            payload={
                "title": event.title,
                "url": f"/spaces/{space.slug}/events/{event.id}",
            },
        )
    except Exception:
        logger.exception(
            "activity: gathering_created failed for %s", getattr(event, "id", "?"),
        )


def record_series_published(
    db: Session, series: EventSeries, *, actor_user_id: str | None = None,
) -> None:
    """A Gathering Series was published — one row for the whole term."""
    try:
        if series.status != "published":
            return
        space = _space_of(db, series.space_id)
        if space is None or space.status != "active":
            return
        ActivityService.create_shared(
            db,
            event_type=ActivityType.gathering_created,
            dedupe_key=series_key(series.id),
            collective_id=series.space_id,
            actor_user_id=actor_user_id,
            series_id=series.id,
            payload={
                "title": series.title,
                "url": f"/spaces/{space.slug}/gathering-series/{series.slug}",
            },
        )
    except Exception:
        logger.exception(
            "activity: series published failed for %s", getattr(series, "id", "?"),
        )
