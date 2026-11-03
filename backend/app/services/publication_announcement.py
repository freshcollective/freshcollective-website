"""When a Gathering or a Series first becomes available — and only then.

Deliberately shaped like ``pathway_announcement``, which solved this
problem first. Same questions in the same order, same idempotency
mechanism, same refusal to let a notification failure break a
publication. Reading the two side by side should be boring.

The rule
--------
Announce on the transition into "members can see this", once, and
never again. Expressed as a question about the present rather than a
stored before-state:

    publicly live now  AND  never announced  AND  the creator said yes

"Never announced" is the comms layer's partial unique index on
``(event_type, dedupe_key)`` — there is no new column and no boolean
to keep in step. Returning a Gathering to draft and publishing it
again is therefore a no-op, which is what §1 asks for.

One announcement per experience
-------------------------------
A Series of thirty sessions must produce one email, not thirty. That
is enforced in two places, because either alone would be fragile:

  * the Series gets its own event and its own dedupe key, so
    publishing it announces the Series as a whole;
  * a Gathering that belongs to a Series is refused here outright —
    see ``_belongs_to_series``. Generating occurrences, regenerating
    them, moving dates, editing one: none of it can announce, because
    the occurrence is never an announceable thing in the first place.

The second is the load-bearing one. The first only decides what the
Series announcement says.

What this module does not do
----------------------------
It does not send. It records the event inside the caller's
transaction, so a rollback in the route takes the announcement with
it — there is no announcement without the publication that caused it —
and the caller commits and then schedules routing. Recipients,
preferences, suppression and delivery all belong to the comms
pipeline.
"""

from __future__ import annotations

from app.services.rich_text import rich_text_to_plain

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.models.platform import Event, EventSeries, Space, SpaceStatus

logger = logging.getLogger(__name__)

GATHERING_EVENT = "gathering.published"
SERIES_EVENT = "series.published"


# ---------------------------------------------------------------------------
# Dedupe keys
# ---------------------------------------------------------------------------


def _friendly_when(gathering: Event, space: Space | None) -> str | None:
    """The start time in the Collective's zone, or None.

    Reuses ``gathering_reminders.format_local_start`` rather than
    formatting again here: a member should not see one wording in an
    announcement and another in the reminder for the same Gathering.
    A dateless draft cannot be published, but the column is nullable,
    so the guard is real rather than defensive.
    """
    if gathering.starts_at is None:
        return None
    try:
        from app.services.gathering_reminders import format_local_start

        return format_local_start(gathering, space)
    except Exception:  # pragma: no cover - formatting must never block
        logger.exception(
            "publication_announcement: could not format start time for "
            "gathering %s", gathering.id,
        )
        return None


def gathering_dedupe_key(gathering_id: str, space_id: str) -> str:
    return f"{gathering_id}:{space_id}"


def series_dedupe_key(series_id: str, space_id: str) -> str:
    return f"{series_id}:{space_id}"


def _already_announced(db: Session, event_type: str, key: str) -> bool:
    return db.scalar(
        select(CommunicationEvent.id)
        .where(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.dedupe_key == key,
        )
        .limit(1)
    ) is not None


# ---------------------------------------------------------------------------
# Is the Collective itself open for business?
# ---------------------------------------------------------------------------


def _collective_is_live(db: Session, space_id: str | None) -> bool:
    """Shared by both experiences.

    An experience inside a draft, archived or closed Collective is not
    reachable by its members, so it is not announced — the same rule
    ``pathway_announcement`` applies, for the same reason.
    """
    if not space_id:
        return False
    space = db.get(Space, space_id)
    if space is None:
        return False
    status = getattr(space.status, "value", space.status)
    if status != SpaceStatus.active.value:
        return False
    try:
        from app.community_care.shared import is_space_closed

        if is_space_closed(space):
            return False
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "publication_announcement: could not evaluate collective "
            "closure for space %s; treating as not announceable", space_id,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Gatherings
# ---------------------------------------------------------------------------


def _belongs_to_series(gathering: Event) -> bool:
    """A session inside something larger is not its own announcement.

    Covers both links a generated occurrence can carry:
    ``series_id`` (attached to an EventSeries) and
    ``recurrence_series_id`` (the low-level UUID stamped on every row
    of a bulk recurrence). Either one means the member will hear about
    the Series instead, so this is checked before anything else —
    including before the creator's ``notify_members`` choice, because
    the choice is about the Series in that case and is read there.
    """
    return bool(
        getattr(gathering, "series_id", None)
        or getattr(gathering, "recurrence_series_id", None)
    )


def gathering_is_member_visible(db: Session, gathering: Event) -> bool:
    """Can members of the Collective see this Gathering now?

    ``is_published`` is the Gathering's own gate, and a cancelled one
    is not an invitation. Area policy is deliberately NOT consulted:
    Gatherings can be configured members-only or public per Collective,
    and either way the audience here is the Collective's own members,
    who reach it under both policies.
    """
    if not gathering.is_published:
        return False
    status = getattr(gathering, "status", "active") or "active"
    if status == "cancelled":
        return False
    return _collective_is_live(db, gathering.space_id)


def should_announce_gathering(db: Session, gathering: Event) -> bool:
    if _belongs_to_series(gathering):
        return False
    if not getattr(gathering, "notify_members", True):
        return False
    if not gathering_is_member_visible(db, gathering):
        return False
    return not _already_announced(
        db, GATHERING_EVENT,
        gathering_dedupe_key(gathering.id, gathering.space_id),
    )


def announce_gathering_if_newly_published(
    db: Session, gathering: Event, *, actor_user_id: str,
) -> CommunicationEvent | None:
    """Record first publication. Returns the event, or None."""
    if not should_announce_gathering(db, gathering):
        return None

    space = db.get(Space, gathering.space_id)
    from app.comms import Source, emit as comms_emit

    # The announcement must never fail the publication. A creator
    # pressing Publish is entitled to; losing a notification is a
    # smaller harm than a 500 that leaves them unsure whether it
    # worked. Idempotency does not depend on this succeeding —
    # ``_already_announced`` is the guard and the unique index is the
    # race guard.
    try:
        return comms_emit(
            db,
            event_type=GATHERING_EVENT,
            source_type=Source.CREATOR,
            source_id=actor_user_id,
            actor_user_id=actor_user_id,
            subject_type="gathering",
            subject_id=gathering.id,
            context={
                "space_id": gathering.space_id,
                "collective_name": space.name if space else None,
            },
            payload={
                "gathering_id": gathering.id,
                "gathering_title": gathering.title,
                "starts_at": (
                    gathering.starts_at.isoformat()
                    if gathering.starts_at else None
                ),
                "ends_at": (
                    gathering.ends_at.isoformat()
                    if gathering.ends_at else None
                ),
                "location_type": getattr(
                    gathering.location_type, "value",
                    gathering.location_type,
                ),
                "attendance_format": getattr(
                    gathering, "attendance_format", None,
                ),
                # Member-safe locality only — never the street address.
                # The same rule the public Gathering page applies.
                "venue_locality": getattr(gathering, "venue_locality", None),
                # The Collective's own display zone, via the formatter
                # the Gathering reminders already use — so "Friday 19
                # September at 9:00am" reads the same in an
                # announcement as in the reminder that follows it.
                "gathering_when": _friendly_when(gathering, space),
                # Plain text, truncated. A description is formatted
                # HTML now, and ``render_email_shell`` escapes
                # everything it is handed — so a slice of raw markup
                # would put "<strong>" in front of a member rather
                # than bolding anything. Slicing HTML could also cut
                # mid-tag or mid-entity.
                "description": rich_text_to_plain(
                    gathering.description, limit=280,
                ) or None,
                "is_paid": (
                    getattr(gathering, "booking_access_type", None)
                    == "paid_separately"
                ),
                "ticket_price_cents": getattr(
                    gathering, "ticket_price_cents", None,
                ),
                "ticket_currency": getattr(
                    gathering, "ticket_currency", None,
                ),
            },
            dedupe_key=gathering_dedupe_key(
                gathering.id, gathering.space_id,
            ),
        )
    except Exception:
        logger.exception(
            "publication_announcement: could not record first publication "
            "for gathering %s in space %s; the gathering is published "
            "either way", gathering.id, gathering.space_id,
        )
        return None


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


def series_is_member_visible(db: Session, series: EventSeries) -> bool:
    status = getattr(series, "status", None)
    status = getattr(status, "value", status)
    if status != "published":
        return False
    return _collective_is_live(db, series.space_id)


def should_announce_series(db: Session, series: EventSeries) -> bool:
    if not getattr(series, "notify_members", True):
        return False
    if not series_is_member_visible(db, series):
        return False
    return not _already_announced(
        db, SERIES_EVENT, series_dedupe_key(series.id, series.space_id),
    )


def announce_series_if_newly_published(
    db: Session, series: EventSeries, *, actor_user_id: str,
) -> CommunicationEvent | None:
    """Record first publication of the Series as a whole."""
    if not should_announce_series(db, series):
        return None

    space = db.get(Space, series.space_id)
    from app.comms import Source, emit as comms_emit

    # The schedule, described rather than enumerated. Thirty dates in
    # an email is a wall; "12 sessions, March to June" is the useful
    # shape of the thing, and the page has the detail.
    occurrence_count = db.scalar(
        select(Event.id).where(Event.series_id == series.id).limit(1)
    )
    count = (
        db.query(Event).filter(Event.series_id == series.id).count()
        if occurrence_count else 0
    )

    try:
        return comms_emit(
            db,
            event_type=SERIES_EVENT,
            source_type=Source.CREATOR,
            source_id=actor_user_id,
            actor_user_id=actor_user_id,
            subject_type="series",
            subject_id=series.id,
            context={
                "space_id": series.space_id,
                "collective_name": space.name if space else None,
            },
            payload={
                "series_id": series.id,
                "series_slug": series.slug,
                "series_title": series.title,
                "starts_at": (
                    series.starts_at.isoformat() if series.starts_at else None
                ),
                "ends_at": (
                    series.ends_at.isoformat() if series.ends_at else None
                ),
                "session_count": count,
                "description": rich_text_to_plain(
                    series.description, limit=280,
                ) or None,
            },
            dedupe_key=series_dedupe_key(series.id, series.space_id),
        )
    except Exception:
        logger.exception(
            "publication_announcement: could not record first publication "
            "for series %s in space %s; the series is published either "
            "way", series.id, series.space_id,
        )
        return None
