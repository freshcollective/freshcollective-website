"""Reserve your regular sessions.

A member with a term pass for a weekly Series should not have to book
twenty Mondays one at a time. They tell us which slots are theirs —
"Mondays at 6", "Thursdays at 6" — and we reserve every remaining
occurrence that matches.

What this is not
----------------
It is not a new kind of booking. Every reservation this module makes is
an ordinary ``EventBooking``, indistinguishable from one made on the
Gathering page, so attendance marking, capacity, the attendance
dashboard, reminder emails and "cancel this one session" all keep
working with no knowledge that a bulk action happened. The member can
cancel a single Monday and the rest stand.

It is also not an access path. Selecting a pattern grants nothing and
charges nothing: every occurrence is put through
``services.gathering_booking_rules`` — the same decisions
``book_event`` applies to a single session — and an occurrence the
member could not have booked individually is reported as unavailable
rather than reserved.

Grouping, and why the timezone matters
--------------------------------------
Occurrences are grouped by their **local** weekday and wall-clock time
in the Collective's configured timezone. That is the whole point: a
member thinks "Mondays at 6pm", and across a daylight-saving boundary
that is two different UTC instants. Grouping on the stored naive-UTC
value would split one weekly slot into two patterns in late spring and
quietly offer the member half their sessions.

Honesty about what will happen
------------------------------
The preview and the confirmation run the same evaluation. The preview
reports, for every occurrence the selection matches, whether it will be
reserved, is already booked, or is unavailable and why — never a silent
skip. The confirmation re-runs all of it against freshly locked rows,
so a seat taken in the intervening seconds is reported rather than
assumed, and tells the caller which of the occurrences it previewed did
not survive.

In-flight allowance
-------------------
A pass allowing two sessions a week, and a member selecting Monday and
Thursday, spends both of that week's credits in one action. Neither
decision can see the other in the database, so this module threads its
own pending consumption through ``evaluate_pass_for_event``. Without
that the preview would promise sessions the pass cannot pay for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    EventSeries,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.event_permissions import can_book
from app.services.gathering_booking_rules import (
    Denial,
    capacity_denial,
    confirmed_booking_count,
    evaluate_pass_for_event,
    event_week_bounds,
    occurrence_timing_denial,
)

#: Used when a Collective has no timezone set. Matches the column
#: default on ``spaces.timezone`` rather than inventing a second one.
FALLBACK_TIMEZONE = "Australia/Melbourne"

WEEKDAY_PLURALS = (
    "Mondays", "Tuesdays", "Wednesdays", "Thursdays",
    "Fridays", "Saturdays", "Sundays",
)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass
class Occurrence:
    """One session, with the local clock reading the member sees."""

    event: Event
    local_start: datetime
    local_end: datetime | None

    @property
    def id(self) -> str:
        return self.event.id


@dataclass
class SchedulePattern:
    """A weekly slot a member can claim as one of their regulars."""

    key: str
    weekday: int                    # 0 = Monday, Python's convention
    weekday_label: str              # "Mondays"
    time_label: str                 # "6:00–7:00 pm"
    label: str                      # "Mondays — 6:00–7:00 pm"
    start_time: str                 # "18:00", local
    end_time: str | None            # "19:00", local
    occurrences: list[Occurrence] = field(default_factory=list)
    #: True when this weekday carries more than one slot, so the UI
    #: knows the time is doing the distinguishing rather than decorating.
    shares_weekday: bool = False


@dataclass
class OccurrenceOutcome:
    """What will happen — or did happen — to one occurrence."""

    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None
    pattern_key: str
    reason: str | None = None
    message: str | None = None


@dataclass
class ReservationPlan:
    """The evaluated consequence of a selection."""

    timezone: str
    selected_keys: list[str]
    will_reserve: list[OccurrenceOutcome] = field(default_factory=list)
    already_booked: list[OccurrenceOutcome] = field(default_factory=list)
    unavailable: list[OccurrenceOutcome] = field(default_factory=list)

    @property
    def new_reservation_count(self) -> int:
        return len(self.will_reserve)


class SeriesClosedError(Exception):
    """The Collective cannot accept bookings at all right now."""

    def __init__(self, message: str, http_status: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Timezone + labels
# ---------------------------------------------------------------------------


def series_timezone(space: Space) -> str:
    """The timezone a Series' schedule is read in.

    The Collective's. There is no per-Series timezone column, and
    inventing one here would be a second source of truth for the same
    fact — a Series runs where its Collective runs.
    """
    name = getattr(space, "timezone", None) or FALLBACK_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return FALLBACK_TIMEZONE
    return name


def to_local(moment: datetime, tz: ZoneInfo) -> datetime:
    """Read a stored naive-UTC instant in the Collective's zone.

    ``Event.starts_at`` is naive and UTC by convention throughout this
    codebase. Attaching UTC before converting is what makes daylight
    saving come out right; treating the naive value as local would
    shift every session by the offset.
    """
    return moment.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)


def _format_clock(moment: datetime) -> tuple[str, str]:
    """``(6:00, pm)`` — hour without a leading zero, lowercase meridiem."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}", "am" if moment.hour < 12 else "pm"


def format_time_range(local_start: datetime, local_end: datetime | None) -> str:
    """"6:00–7:00 pm", or "11:30 am–1:00 pm" when the half changes."""
    start_clock, start_meridiem = _format_clock(local_start)
    if local_end is None:
        return f"{start_clock} {start_meridiem}"
    end_clock, end_meridiem = _format_clock(local_end)
    if start_meridiem == end_meridiem:
        return f"{start_clock}–{end_clock} {end_meridiem}"
    return f"{start_clock} {start_meridiem}–{end_clock} {end_meridiem}"


def pattern_key_for(local_start: datetime, local_end: datetime | None) -> str:
    """Stable identity for a weekly slot: weekday plus local clock.

    Local, not UTC — that is what keeps one slot one pattern across a
    daylight-saving change.
    """
    end = local_end.strftime("%H:%M") if local_end is not None else ""
    return f"{local_start.weekday()}-{local_start.strftime('%H:%M')}-{end}"


# ---------------------------------------------------------------------------
# Occurrence selection
# ---------------------------------------------------------------------------


def remaining_occurrences(
    db: Session, series: EventSeries, space: Space, now: datetime,
    *, lock: bool = False,
) -> list[Event]:
    """The sessions still ahead that a member could reserve.

    Published, bookable, active, and in the future. ``status='active'``
    excludes both cancelled and archived occurrences, which is why
    there is no separate filter for them.

    ``lock`` takes a row lock on each occurrence, ordered by id so two
    concurrent reservations covering overlapping sets cannot deadlock.
    Used on confirmation; never on preview, which must not hold locks
    while a member reads.
    """
    query = (
        db.query(Event)
        .filter(
            Event.space_id == space.id,
            Event.series_id == series.id,
            Event.is_published.is_(True),
            Event.requires_booking.is_(True),
            Event.status == "active",
            Event.starts_at > now,
        )
    )
    if lock:
        return query.order_by(Event.id).with_for_update().all()
    return query.order_by(Event.starts_at).all()


def build_patterns(
    events: list[Event], tz_name: str,
) -> tuple[list[SchedulePattern], str]:
    """Group occurrences into the weekly slots a member recognises."""
    tz = ZoneInfo(tz_name)
    grouped: dict[str, SchedulePattern] = {}
    for event in sorted(events, key=lambda e: e.starts_at):
        local_start = to_local(event.starts_at, tz)
        local_end = to_local(event.ends_at, tz) if event.ends_at else None
        key = pattern_key_for(local_start, local_end)
        pattern = grouped.get(key)
        if pattern is None:
            time_label = format_time_range(local_start, local_end)
            weekday_label = WEEKDAY_PLURALS[local_start.weekday()]
            pattern = SchedulePattern(
                key=key,
                weekday=local_start.weekday(),
                weekday_label=weekday_label,
                time_label=time_label,
                label=f"{weekday_label} — {time_label}",
                start_time=local_start.strftime("%H:%M"),
                end_time=local_end.strftime("%H:%M") if local_end else None,
            )
            grouped[key] = pattern
        pattern.occurrences.append(
            Occurrence(event=event, local_start=local_start, local_end=local_end)
        )

    patterns = sorted(grouped.values(), key=lambda p: (p.weekday, p.start_time))
    weekday_counts: dict[int, int] = {}
    for pattern in patterns:
        weekday_counts[pattern.weekday] = weekday_counts.get(pattern.weekday, 0) + 1
    for pattern in patterns:
        pattern.shares_weekday = weekday_counts[pattern.weekday] > 1
    return patterns, tz_name


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _membership_or_none(
    db: Session, user: User, space: Space,
) -> SpaceMembership | None:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )


def _guard_collective_open(space: Space) -> None:
    """A closed or paused Collective accepts no bookings, bulk or single."""
    from app.community_care.shared import is_space_closed, is_space_frozen

    if is_space_closed(space):
        raise SeriesClosedError("This collective has been closed.")
    if is_space_frozen(space):
        raise SeriesClosedError(
            "This collective is temporarily paused by Fresh Collective."
        )


def _outcome(
    occurrence: Occurrence, pattern_key: str, denial: Denial | None = None,
) -> OccurrenceOutcome:
    return OccurrenceOutcome(
        event_id=occurrence.event.id,
        title=occurrence.event.title,
        starts_at=occurrence.event.starts_at,
        ends_at=occurrence.event.ends_at,
        pattern_key=pattern_key,
        reason=denial.reason if denial else None,
        message=denial.message if denial else None,
    )


def evaluate_selection(
    db: Session,
    *,
    user: User,
    space: Space,
    series: EventSeries,
    pattern_keys: list[str],
    now: datetime,
    lock: bool = False,
) -> tuple[ReservationPlan, dict[str, Occurrence], dict[str, object]]:
    """Decide what a selection would do, without doing any of it.

    Returns the plan, the occurrences keyed by event id (so a caller
    committing does not re-query), and the pass charges it decided on.

    The same function serves the preview and the confirmation; the only
    difference is ``lock``. That is deliberate — a preview that ran
    different code from the commit would be a preview of nothing.
    """
    _guard_collective_open(space)

    tz_name = series_timezone(space)
    events = remaining_occurrences(db, series, space, now, lock=lock)
    patterns, _ = build_patterns(events, tz_name)

    selected = [p for p in patterns if p.key in set(pattern_keys)]
    plan = ReservationPlan(timezone=tz_name, selected_keys=list(pattern_keys))

    membership = _membership_or_none(db, user, space)
    is_privileged = getattr(membership, "role", None) in (
        SpaceRole.creator, SpaceRole.moderator,
    )
    if user.role == "admin" or space.creator_id == user.id:
        is_privileged = True

    chosen: list[tuple[SchedulePattern, Occurrence]] = [
        (pattern, occurrence)
        for pattern in selected
        for occurrence in pattern.occurrences
    ]
    chosen.sort(key=lambda pair: pair[1].event.starts_at)

    if not chosen:
        return plan, {}, {}

    event_ids = [occurrence.event.id for _, occurrence in chosen]
    existing_rows = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id.in_(event_ids),
            EventBooking.user_id == user.id,
        )
        .all()
    )
    existing = {row.event_id: row for row in existing_rows}

    occurrences_by_id: dict[str, Occurrence] = {}
    charges: dict[str, object] = {}
    pending_weekly: dict[datetime, int] = {}
    pending_total = 0
    pending_seats: dict[str, int] = {}

    for pattern, occurrence in chosen:
        event = occurrence.event
        occurrences_by_id[event.id] = occurrence

        booking = existing.get(event.id)
        if booking is not None and booking.status == BookingStatus.confirmed:
            plan.already_booked.append(_outcome(occurrence, pattern.key))
            continue

        timing = occurrence_timing_denial(event, now)
        if timing is not None:
            plan.unavailable.append(_outcome(occurrence, pattern.key, timing))
            continue

        gate = can_book(user, event, space, db)
        if not gate.allowed:
            plan.unavailable.append(
                _outcome(
                    occurrence,
                    pattern.key,
                    Denial(gate.reason or "not_allowed", gate.message, 403),
                )
            )
            continue

        seats_taken = pending_seats.get(event.id, 0)
        full = capacity_denial(
            event, confirmed_booking_count(db, event.id), pending=seats_taken,
        )
        if full is not None:
            plan.unavailable.append(_outcome(occurrence, pattern.key, full))
            continue

        decision = evaluate_pass_for_event(
            db,
            user=user,
            event=event,
            is_privileged=is_privileged,
            pending_weekly=pending_weekly,
            pending_total=pending_total,
        )
        if decision.denial is not None:
            plan.unavailable.append(
                _outcome(occurrence, pattern.key, decision.denial)
            )
            continue

        plan.will_reserve.append(_outcome(occurrence, pattern.key))
        pending_seats[event.id] = seats_taken + 1
        if decision.charge is not None:
            charges[event.id] = decision.charge
            week_start, _ = event_week_bounds(event)
            pending_weekly[week_start] = pending_weekly.get(week_start, 0) + 1
            pending_total += 1

    return plan, occurrences_by_id, charges




# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


@dataclass
class ReservationOutcome:
    """What actually happened, reported per occurrence."""

    timezone: str
    reserved: list[OccurrenceOutcome] = field(default_factory=list)
    already_booked: list[OccurrenceOutcome] = field(default_factory=list)
    unavailable: list[OccurrenceOutcome] = field(default_factory=list)
    #: Occurrences the caller previewed as reservable that did not make
    #: it — a seat taken, a session cancelled, an allowance spent
    #: elsewhere in the seconds between the two requests. Reported
    #: rather than silently absent, because the member was shown a
    #: number and is owed an explanation when it changes.
    changed_since_preview: list[OccurrenceOutcome] = field(default_factory=list)

    @property
    def reserved_count(self) -> int:
        return len(self.reserved)


def _vanished_outcome(
    db: Session, event_id: str, now: datetime,
) -> OccurrenceOutcome:
    """Describe an occurrence that left the reservable set.

    Its own status is the explanation, so it is read back rather than
    guessed at: cancelled reads as cancelled, unpublished as withdrawn.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        return OccurrenceOutcome(
            event_id=event_id,
            title="This session",
            starts_at=now,
            ends_at=None,
            pattern_key="",
            reason="removed",
            message="This session is no longer in the series.",
        )

    denial = occurrence_timing_denial(event, now)
    if denial is None:
        if not event.is_published or not event.requires_booking:
            denial = Denial(
                "withdrawn",
                "This session is no longer open for reservations.",
                409,
            )
        else:
            denial = Denial(
                "no_longer_matching",
                "This session is no longer part of the selected schedule.",
                409,
            )
    return OccurrenceOutcome(
        event_id=event.id,
        title=event.title,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        pattern_key="",
        reason=denial.reason,
        message=denial.message,
    )


def commit_reservations(
    db: Session,
    *,
    user: User,
    space: Space,
    series: EventSeries,
    pattern_keys: list[str],
    now: datetime,
    expected_event_ids: list[str] | None = None,
    background_tasks: object | None = None,
) -> ReservationOutcome:
    """Reserve the selected patterns, and report the result honestly.

    Everything is re-decided here against locked rows. The preview is
    information, never a promise: between a member reading it and
    pressing the button, a session can fill, be cancelled, or have its
    booking close.

    Idempotent by construction. An occurrence the member already holds
    is reported as already booked rather than failing, so a double
    click, a retried request after a dropped connection, or a refresh
    all converge on the same state. The unique constraint on
    ``(event_id, user_id)`` is the backstop underneath that: if a
    concurrent request wins the race between our evaluation and our
    insert, the integrity error is caught and the occurrence is
    reported as already booked — which is the truth.
    """
    from sqlalchemy.exc import IntegrityError

    plan, occurrences, charges = evaluate_selection(
        db,
        user=user,
        space=space,
        series=series,
        pattern_keys=pattern_keys,
        now=now,
        lock=True,
    )

    outcome = ReservationOutcome(
        timezone=plan.timezone,
        already_booked=list(plan.already_booked),
        unavailable=list(plan.unavailable),
    )

    created: list[EventBooking] = []
    for planned in plan.will_reserve:
        occurrence = occurrences[planned.event_id]
        charge = charges.get(planned.event_id)
        existing = (
            db.query(EventBooking)
            .filter(
                EventBooking.event_id == planned.event_id,
                EventBooking.user_id == user.id,
            )
            .first()
        )

        savepoint = db.begin_nested()
        try:
            if existing is not None:
                # A cancelled booking is reactivated rather than
                # duplicated — the same thing ``book_event`` does, and
                # what the unique constraint requires.
                existing.status = BookingStatus.confirmed
                existing.booked_at = now
                existing.cancelled_at = None
                existing.access_pass_id = charge.id if charge else None
                existing.credits_used = 1 if charge else 0
                booking = existing
            else:
                import uuid as _uuid

                booking = EventBooking(
                    id=str(_uuid.uuid4()),
                    event_id=planned.event_id,
                    user_id=user.id,
                    status=BookingStatus.confirmed,
                    booked_at=now,
                    access_pass_id=charge.id if charge else None,
                    credits_used=1 if charge else 0,
                )
                db.add(booking)
            if charge is not None:
                charge.used_credits += 1
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            outcome.already_booked.append(planned)
            continue

        created.append(booking)
        outcome.reserved.append(planned)

    db.commit()

    reserved_ids = {o.event_id for o in outcome.reserved}
    for event_id in expected_event_ids or []:
        if event_id in reserved_ids:
            continue
        match = next(
            (
                o for o in outcome.unavailable + outcome.already_booked
                if o.event_id == event_id
            ),
            None,
        )
        if match is not None:
            outcome.changed_since_preview.append(match)
            continue
        if event_id in occurrences:
            outcome.changed_since_preview.append(
                _outcome(
                    occurrences[event_id],
                    "",
                    Denial(
                        "no_longer_matching",
                        "This session is no longer part of the selected schedule.",
                        409,
                    ),
                )
            )
            continue
        # Gone from the candidate set altogether — cancelled or
        # archived by the Creator while the member was reading, which
        # removes it from ``remaining_occurrences`` and so from every
        # bucket above. Read the row directly rather than leaving the
        # member with a number that silently got smaller.
        outcome.changed_since_preview.append(
            _vanished_outcome(db, event_id, now)
        )

    # One summary email for the whole action, reusing the emitter the
    # existing Series booking uses. Only the bookings actually created
    # are reported: already-booked occurrences are not news, and
    # twenty separate confirmations for one click would be.
    if created:
        from app.services.gathering_booking_emit import emit_multi_booking_confirmed

        emit_multi_booking_confirmed(
            db,
            user_id=user.id,
            bookings=created,
            space=space,
            scope=f"regular-sessions:{series.id}",
            operation_at=now,
            series=series,
            added_by_creator=False,
            background_tasks=background_tasks,
        )

    return outcome


__all__ = [
    "FALLBACK_TIMEZONE",
    "Occurrence",
    "OccurrenceOutcome",
    "ReservationPlan",
    "ReservationOutcome",
    "SchedulePattern",
    "SeriesClosedError",
    "build_patterns",
    "commit_reservations",
    "evaluate_selection",
    "format_time_range",
    "pattern_key_for",
    "remaining_occurrences",
    "series_timezone",
    "to_local",
]
