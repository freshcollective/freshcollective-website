"""When a Gathering, a schedule or a Series first becomes available.

Three kinds of publication, one rule, one idempotency mechanism:

  * a **standalone Gathering** — ``gathering.published``;
  * a **recurring schedule** generated together and not attached to a
    formal Series — ``gathering.recurrence.published``, one for the
    batch;
  * a formal **Gathering Series** — ``series.published``, one for the
    term.

``announce_if_newly_published`` is the entry point; it decides which of
the three a Gathering's publication means, so the routes do not.

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
Thirty sessions must produce one email, not thirty. That is enforced in
two places, because either alone would be fragile:

  * the batch gets its own event and its own dedupe key — the Series'
    id for a formal Series, the ``recurrence_series_id`` for a
    schedule — so publishing announces the thing as a whole;
  * a Gathering that belongs to either is refused as *an individual
    announcement* — see ``_belongs_to_series``. Generating occurrences,
    regenerating them, moving dates, editing one: none of it can
    produce a per-occurrence email, because the occurrence is never an
    announceable thing in the first place.

The second is the load-bearing one. The first only decides what the
batch announcement says.

A batch can carry both links. When it does the Series wins and the
recurrence is silent, so the two can never both fire for the same
Gatherings — see ``announce_if_newly_published``.

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
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.models.platform import Event, EventSeries, Space, SpaceStatus

logger = logging.getLogger(__name__)

GATHERING_EVENT = "gathering.published"
SERIES_EVENT = "series.published"
RECURRENCE_EVENT = "gathering.recurrence.published"


class Announcement(NamedTuple):
    """What :func:`announce_if_newly_published` decided.

    Carries the ``event_type`` beside the event because the caller
    needs it for ``schedule_routing_if_needed``, and which of the
    three it is depends on the Gathering — which is a question this
    module already answers and the routes should not have to.
    """

    event: CommunicationEvent
    event_type: str


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


def recurrence_dedupe_key(recurrence_series_id: str, space_id: str) -> str:
    """Keyed to the batch, never to an occurrence.

    This is what makes a later edit silent without any extra
    bookkeeping: the recurrence tag is stamped when the batch is
    generated and is never rewritten afterwards, so
    editing an occurrence's title, moving one date, returning one to
    draft, or replaying the request all resolve to the same key and the
    unique index refuses the second insert.
    """
    return f"{recurrence_series_id}:{space_id}"


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
    of a bulk recurrence). Either one means the member hears about the
    batch instead — the Series when there is one, the schedule when
    there is not — so this is checked before anything else, including
    before the creator's ``notify_members`` choice, because the choice
    is about the batch in that case and is read there.

    Unchanged by FC-209, deliberately. This function's job is still
    "may this single row announce itself", and the answer is still no.
    What changed is that ``announce_if_newly_published`` now routes a
    recurrence row to the batch announcement rather than dropping it.
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


# ---------------------------------------------------------------------------
# Recurring schedules — a run of Gatherings with no formal Series
# ---------------------------------------------------------------------------
#
# The third kind of publication, and the one that used to announce
# nothing. A creator schedules twelve monthly circles; the occurrences
# are refused individually by ``_belongs_to_series`` (correctly — twelve
# emails for one decision is a flood), and without a batch-level
# announcement nobody was told at all.
#
# What a recurrence is NOT. A formal ``EventSeries`` is a connected
# experience: its own page, its own lifecycle, its own payment options,
# bought as a whole. A recurrence is a set of *independent* Gatherings
# that happen to share a title and a rhythm — each booked separately and
# paid for separately. The two concepts stay apart here as they do in
# the model, and the copy is written so a member is never told they must
# buy a package.
#
# Which means a batch carrying a ``series_id`` is refused outright: the
# Series announces it. That refusal is what guarantees §B — the two can
# never both fire for the same Gatherings.


class RecurrenceFacts(NamedTuple):
    """What a member needs to know about a schedule, not its full
    timetable.

    Deliberately aggregate. A ``repeat_until`` three years out can
    generate hundreds of occurrences, so the count, the first date and
    the last come from one aggregate query and only the earliest
    occurrence is loaded — for the title, the public attendance line
    and the creator's notify choice, all of which every row in a batch
    shares by construction (see ``services/gathering_fields``).
    """

    recurrence_series_id: str
    count: int
    first_starts_at: datetime | None
    last_starts_at: datetime | None
    first: Event


def _visible_occurrences(space_id: str, recurrence_series_id: str):
    """The occurrences of one batch a member could open right now.

    ``is_published`` and a non-cancelled status, scoped to the Space so
    a recurrence tag can never reach across Collectives. Returned as a
    filter list so the aggregate and the row load share one definition.
    """
    return [
        Event.space_id == space_id,
        Event.recurrence_series_id == recurrence_series_id,
        Event.is_published.is_(True),
        Event.status != "cancelled",
        # A dateless row cannot be published (``update_event`` refuses
        # it), but the column is nullable, so the guard is real.
        Event.starts_at.isnot(None),
    ]


def recurrence_facts(
    db: Session, space_id: str, recurrence_series_id: str,
) -> RecurrenceFacts | None:
    """Aggregate the batch, or None when nothing in it is visible."""
    where = _visible_occurrences(space_id, recurrence_series_id)
    count, first_at, last_at = db.execute(
        select(
            func.count(Event.id),
            func.min(Event.starts_at),
            func.max(Event.starts_at),
        ).where(*where)
    ).one()
    if not count:
        return None
    first = db.execute(
        select(Event).where(*where).order_by(Event.starts_at.asc()).limit(1)
    ).scalars().first()
    if first is None:  # pragma: no cover — count > 0 implies a row
        return None
    return RecurrenceFacts(
        recurrence_series_id=recurrence_series_id,
        count=int(count),
        first_starts_at=first_at,
        last_starts_at=last_at,
        first=first,
    )


def recurrence_is_member_visible(
    db: Session, space_id: str, recurrence_series_id: str,
) -> bool:
    """Can members see any of this schedule now?

    One visible occurrence is enough — a creator who published eleven
    of twelve has published the schedule. Mirrors
    ``gathering_is_member_visible`` otherwise, including the deliberate
    silence about area policy: the audience is the Collective's own
    members, who reach Gatherings under either policy.
    """
    if not _collective_is_live(db, space_id):
        return False
    return (
        db.scalar(
            select(Event.id)
            .where(*_visible_occurrences(space_id, recurrence_series_id))
            .limit(1)
        )
        is not None
    )


def should_announce_recurrence(
    db: Session, space_id: str, recurrence_series_id: str,
    *, notify_members: bool,
) -> bool:
    """Same three questions as the single-Gathering rule, asked of the
    batch: the creator said yes, members can see it now, and it has
    never been announced."""
    if not notify_members:
        return False
    if not recurrence_is_member_visible(db, space_id, recurrence_series_id):
        return False
    return not _already_announced(
        db, RECURRENCE_EVENT,
        recurrence_dedupe_key(recurrence_series_id, space_id),
    )


def announce_recurrence_if_newly_published(
    db: Session, *, space_id: str, recurrence_series_id: str,
    actor_user_id: str, notify_members: bool,
) -> CommunicationEvent | None:
    """Record the first publication of a recurring schedule.

    One event for the batch. Returns the event, or None when the
    schedule is not announceable or has already been announced.
    """
    if not should_announce_recurrence(
        db, space_id, recurrence_series_id, notify_members=notify_members,
    ):
        return None

    facts = recurrence_facts(db, space_id, recurrence_series_id)
    if facts is None:  # pragma: no cover — visibility implies facts
        return None

    space = db.get(Space, space_id)
    first = facts.first
    from app.comms import Source, emit as comms_emit

    # Never fails the publication, for the reason stated beside the
    # single-Gathering emitter: a creator pressing Publish is entitled
    # to, and losing a notification is the smaller harm.
    try:
        return comms_emit(
            db,
            event_type=RECURRENCE_EVENT,
            source_type=Source.CREATOR,
            source_id=actor_user_id,
            actor_user_id=actor_user_id,
            subject_type="recurrence",
            subject_id=recurrence_series_id,
            context={
                "space_id": space_id,
                "collective_name": space.name if space else None,
            },
            payload={
                "recurrence_series_id": recurrence_series_id,
                # What members see as the group label on each card. The
                # creator's own name for the schedule when they gave
                # one, the Gathering's title when they did not — so
                # this is never empty, and the template never has to
                # cope with a blank heading.
                "schedule_name": (
                    (first.recurrence_label or "").strip()
                    or first.title
                ),
                "gathering_title": first.title,
                "recurrence_label": first.recurrence_label,
                "occurrence_count": facts.count,
                "first_starts_at": (
                    facts.first_starts_at.isoformat()
                    if facts.first_starts_at else None
                ),
                "last_starts_at": (
                    facts.last_starts_at.isoformat()
                    if facts.last_starts_at else None
                ),
                # The first date in the Collective's own zone, through
                # the formatter the reminders and the single-Gathering
                # announcement already use.
                "first_when": _friendly_when(first, space),
                "location_type": getattr(
                    first.location_type, "value", first.location_type,
                ),
                "attendance_format": getattr(first, "attendance_format", None),
                # Member-safe locality only — never the street address
                # and never the joining link. An announcement goes to
                # people who have not booked.
                "venue_locality": getattr(first, "venue_locality", None),
                "description": rich_text_to_plain(
                    first.description, limit=280,
                ) or None,
                "is_paid": (
                    getattr(first, "booking_access_type", None)
                    == "paid_separately"
                ),
            },
            dedupe_key=recurrence_dedupe_key(
                recurrence_series_id, space_id,
            ),
        )
    except Exception:
        logger.exception(
            "publication_announcement: could not record first publication "
            "for recurrence %s in space %s; the gatherings are published "
            "either way", recurrence_series_id, space_id,
        )
        return None


# ---------------------------------------------------------------------------
# The one entry point the routes call
# ---------------------------------------------------------------------------


def announce_if_newly_published(
    db: Session, gathering: Event, *, actor_user_id: str,
) -> Announcement | None:
    """Announce whatever this Gathering's publication means.

    Three outcomes, in this order, because the order is the rule:

    1. **It belongs to a formal Series** → nothing. The Series is the
       offering members are told about, and it announces itself when it
       is published. This arm is what prevents a duplicate between a
       recurrence and its Series.
    2. **It was generated as part of a recurring batch** → one
       announcement for the schedule, deduped on the recurrence tag.
       The eleven siblings reaching this function produce nothing
       further.
    3. **It stands alone** → the single-Gathering announcement,
       unchanged.

    Returning an :class:`Announcement` rather than a bare event means a
    route does not have to know which of the three it got in order to
    schedule routing.
    """
    series_id = getattr(gathering, "series_id", None)
    if series_id:
        return None

    recurrence_series_id = getattr(gathering, "recurrence_series_id", None)
    if recurrence_series_id:
        if not gathering.space_id:  # pragma: no cover — NOT NULL column
            return None
        ev = announce_recurrence_if_newly_published(
            db,
            space_id=gathering.space_id,
            recurrence_series_id=recurrence_series_id,
            actor_user_id=actor_user_id,
            # Every row in a batch carries the creator's one choice —
            # see ``services/gathering_fields`` — so reading it off the
            # occurrence in hand is reading the batch's own setting.
            notify_members=bool(
                getattr(gathering, "notify_members", True)
            ),
        )
        return Announcement(ev, RECURRENCE_EVENT) if ev is not None else None

    ev = announce_gathering_if_newly_published(
        db, gathering, actor_user_id=actor_user_id,
    )
    return Announcement(ev, GATHERING_EVENT) if ev is not None else None
