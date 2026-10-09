"""The rules that decide whether one member may reserve one gathering.

Extracted from ``spaces.routes.book_event``, which had grown to hold
every booking rule inline: the access gate, term-pass matching, weekly
and total allowance caps, the privilege nuances, and the timing checks.
That was fine while one endpoint needed them. "Reserve your regular
sessions" needs the same decisions for twenty occurrences at once, and
a second copy of a hundred and twenty lines of allowance arithmetic
would drift from the first within a release.

So the decisions live here and both callers use them. ``book_event``
behaves exactly as before — the messages and status codes below are its
messages and status codes, moved rather than rewritten.

What is deliberately *not* here
-------------------------------
Nothing in this module writes. It answers "may this happen, and what
would it consume"; the caller commits. That split is what lets the
preview in "Reserve your regular sessions" be honest: it runs the same
decisions the confirmation will run, and the only thing that can change
between them is the world, not the rules.

In-flight consumption
---------------------
One subtlety the single-booking path never had to think about. A term
pass with ``credits_per_week=2`` and a member selecting Monday and
Thursday of the same week spends two of that week's allowance in a
single action — but the second decision cannot see the first in the
database, because nothing is committed yet. So the caller may pass
``pending_weekly`` / ``pending_total`` and the caps are evaluated
against database usage *plus* what this operation has already decided
to spend. Without that, a bulk reserve would promise more sessions than
the pass can pay for and the last ones would fail at commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
)
from app.models.user import User
from app.services.gathering_types import normalise_access_type


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Denial:
    """Why a booking may not happen.

    ``reason`` is the machine-readable code the API surfaces so the
    frontend can group unavailable dates without parsing prose.
    ``http_status`` is what ``book_event`` returned for this case
    before the extraction, preserved exactly.
    """

    reason: str
    message: str
    http_status: int


@dataclass(frozen=True)
class PassDecision:
    """The pass this booking would consume, or why it cannot proceed.

    ``charge`` is the ``AccessPass`` whose ``used_credits`` the caller
    must increment on commit, or ``None`` when the booking proceeds
    without consuming an entitlement — which is a real and distinct
    outcome, not an absence of one. It happens for ``free`` and
    ``included_with_collective`` gatherings, for the legacy
    pathway-gated fallback, and for a caretaker attending outside their
    allowance.
    """

    charge: AccessPass | None = None
    denial: Denial | None = None

    @property
    def allowed(self) -> bool:
        return self.denial is None


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def occurrence_timing_denial(event: Event, now: datetime) -> Denial | None:
    """Status and timing checks: cancelled, started, booking closed.

    ``book_event`` raised 400 for each of these, and still does.
    """
    if getattr(event, "status", "active") == "cancelled":
        return Denial(
            "cancelled", "This gathering has been cancelled.", 400,
        )
    if getattr(event, "status", "active") == "archived":
        return Denial(
            "archived", "This gathering is no longer available.", 400,
        )
    if event.starts_at <= now:
        return Denial(
            "already_started", "This gathering has already started.", 400,
        )
    if event.booking_closes_at and event.booking_closes_at <= now:
        return Denial(
            "booking_closed", "Booking has closed for this gathering.", 400,
        )
    return None


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


def confirmed_booking_count(db: Session, event_id: str) -> int:
    """Confirmed bookings on one occurrence."""
    return (
        db.query(func.count(EventBooking.id))
        .filter(
            EventBooking.event_id == event_id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .scalar()
    ) or 0


def capacity_denial(
    event: Event, confirmed: int, *, pending: int = 0,
) -> Denial | None:
    """Whether this occurrence has room.

    ``pending`` lets a bulk caller account for a seat it has already
    decided to take in this same operation — relevant only in the
    pathological case of the same occurrence appearing twice, but free
    to carry and one less thing to reason about.
    """
    if event.capacity is None:
        return None
    if confirmed + pending >= event.capacity:
        return Denial("full", "This gathering is fully booked.", 400)
    return None


# ---------------------------------------------------------------------------
# Term-pass matching and allowance
# ---------------------------------------------------------------------------


def event_week_bounds(event: Event) -> tuple[datetime, datetime]:
    """The calendar week the weekly allowance is counted in.

    The EVENT's week, not the booking's. That is what lets a member
    book the same weekday across six future weeks while still being
    held to one session inside any single week.
    """
    weekday = event.starts_at.weekday()  # 0 = Monday
    start = (event.starts_at - timedelta(days=weekday)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return start, start + timedelta(days=7)


def weekly_usage_on_pass(
    db: Session, pass_id: str, week_start: datetime, week_end: datetime,
) -> int:
    """Confirmed bookings charged to this pass inside one event-week."""
    return (
        db.query(func.count(EventBooking.id))
        .join(Event, EventBooking.event_id == Event.id)
        .filter(
            EventBooking.access_pass_id == pass_id,
            EventBooking.status == BookingStatus.confirmed,
            Event.starts_at >= week_start,
            Event.starts_at < week_end,
        )
        .scalar()
    ) or 0


def find_candidate_pass(
    db: Session,
    *,
    user: User,
    event: Event,
    is_pathway_gated: bool,
    is_series_gated: bool,
) -> AccessPass | None:
    """The pass that would authorise this booking, if the member holds one.

    The validity window is tested against ``event.starts_at``, not
    against now: a pass covers a session when the session falls inside
    the window, which is what lets someone buy next term today.
    """
    conditions = []
    if is_pathway_gated:
        conditions.append(
            AccessPass.eligible_pathway_id == event.booking_required_pathway_id
        )
    if is_series_gated and getattr(event, "series_id", None) is not None:
        conditions.append(AccessPass.eligible_series_id == event.series_id)
    if not conditions:
        return None
    return (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.status == AccessPassStatus.active,
            or_(*conditions),
            AccessPass.valid_from <= event.starts_at,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > event.starts_at,
            ),
        )
        .order_by(AccessPass.created_at.desc())
        .first()
    )


def evaluate_pass_for_event(
    db: Session,
    *,
    user: User,
    event: Event,
    is_privileged: bool,
    pending_weekly: dict[datetime, int] | None = None,
    pending_total: int = 0,
) -> PassDecision:
    """Decide which entitlement, if any, this booking consumes.

    The logic is ``book_event``'s, unchanged:

    * The credit check applies only to ``included_with_pathway`` and
      ``included_with_series`` gatherings — not to any gathering that
      merely belongs to a Series. A Series can exist purely to group
      free sessions.
    * No matching pass: a strictly series-gated gathering is refused
      for an ordinary member, because "I never bought a pass" and
      "this session is outside my pass window" are both denials.
      Pathway-gated keeps its lenient fallback for members holding a
      manual entitlement, and caretakers are never refused.
    * Privilege bypasses refusal, never consumption. A caretaker who
      holds a pass with headroom spends it like anyone else, so their
      accounting stays true; past the caps they attend without
      charging it, because privilege must not invent entitlement.
    """
    access = normalise_access_type(getattr(event, "booking_access_type", None))
    required_pathway_id = getattr(event, "booking_required_pathway_id", None)
    is_series_gated = access == "included_with_series"
    is_pathway_gated = access == "included_with_pathway" and bool(required_pathway_id)

    if not (is_series_gated or is_pathway_gated):
        return PassDecision()

    candidate = find_candidate_pass(
        db,
        user=user,
        event=event,
        is_pathway_gated=is_pathway_gated,
        is_series_gated=is_series_gated,
    )

    if candidate is None:
        if is_series_gated and not is_pathway_gated and not is_privileged:
            return PassDecision(
                denial=Denial(
                    "series_pass_required",
                    "This session is part of a term. You need an active term "
                    "pass whose validity window covers this session's date.",
                    403,
                )
            )
        return PassDecision()

    exceeds_total = (
        candidate.total_credits is not None
        and candidate.used_credits + pending_total >= candidate.total_credits
    )

    exceeds_weekly = False
    if candidate.credits_per_week is not None:
        week_start, week_end = event_week_bounds(event)
        used = weekly_usage_on_pass(db, candidate.id, week_start, week_end)
        used += (pending_weekly or {}).get(week_start, 0)
        exceeds_weekly = used >= candidate.credits_per_week

    if exceeds_total:
        if not is_privileged:
            return PassDecision(
                denial=Denial(
                    "no_remaining_sessions",
                    "You have no remaining sessions on your current pass.",
                    409,
                )
            )
        return PassDecision()

    if exceeds_weekly:
        if not is_privileged:
            return PassDecision(
                denial=Denial(
                    "weekly_limit_reached",
                    f"You have reached your weekly limit of "
                    f"{candidate.credits_per_week} session(s).",
                    409,
                )
            )
        return PassDecision()

    return PassDecision(charge=candidate)


__all__ = [
    "Denial",
    "PassDecision",
    "capacity_denial",
    "confirmed_booking_count",
    "evaluate_pass_for_event",
    "event_week_bounds",
    "find_candidate_pass",
    "occurrence_timing_denial",
    "weekly_usage_on_pass",
]
