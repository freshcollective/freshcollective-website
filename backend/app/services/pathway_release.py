"""Pathway drip scheduling — read-time availability engine.

One pure function (`compute_availability`) decides whether a step is
available to a given member right now, and if not, what to tell them
about when / why it will open. The server is always authoritative;
the frontend just renders what it's told.

Foundational infrastructure — every future release-driven experience
(challenges, cohorts, journeys, annual programs) should hydrate its
gating through this same engine rather than growing a parallel one.

Only `pathway_release.compute_availability(...)` is a public API. The
`Availability` result type is a small dataclass so callers can serialise
it into whatever payload shape they need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Discriminator values kept in sync with pathway_steps.release_type.
IMMEDIATE = "immediate"
DAYS_AFTER_ENROLLMENT = "days_after_enrollment"
FIXED_DATE = "fixed_date"
AFTER_PREVIOUS = "after_previous"
MANUAL = "manual"

RELEASE_TYPES: tuple[str, ...] = (
    IMMEDIATE, DAYS_AFTER_ENROLLMENT, FIXED_DATE, AFTER_PREVIOUS, MANUAL,
)


@dataclass(frozen=True)
class Availability:
    """Everything a caller needs to render a step's lock state.

    Fields:
      is_locked  — True if the current member cannot open the step.
      reason     — matches release_type when locked; None when open.
      unlocks_at — UTC datetime the step becomes available, when known.
                   Days-after-enrollment and fixed-date supply this;
                   after-previous and manual leave it None.
      message    — a short, human-facing lock explanation like
                   "Available in 5 days" or "Waiting for your facilitator".
                   Callers may substitute their own copy if they prefer.
    """
    is_locked: bool
    reason: str | None
    unlocks_at: datetime | None
    message: str | None


_OPEN = Availability(is_locked=False, reason=None, unlocks_at=None, message=None)


# ---------------------------------------------------------------------------
# Small inputs — plain dicts so callers don't have to import ORM types.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRule:
    """The release configuration for one step."""
    release_type: str
    release_offset_days: int | None
    release_at: datetime | None
    release_timezone: str | None
    release_previous_state: str  # 'completed' | 'started'


@dataclass(frozen=True)
class PreviousStepState:
    """Just enough about the immediately previous step to gate on it."""
    completed_at: datetime | None
    has_progress_record: bool  # 'started' == any StepProgress row exists


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_availability(
    *,
    rule: StepRule,
    enrolled_at: datetime | None,
    previous: PreviousStepState | None,
    manually_released: bool,
    now: datetime,
) -> Availability:
    """Return the current availability for a single step + member pair.

    Preconditions the caller is responsible for:
      * `enrolled_at`, `previous`, and `manually_released` should reflect
        the *specific member*.
      * `now` is a naive UTC datetime (matches DB storage convention).

    The order of checks matters:
      1. A manual release is a whitelist — it always wins so a caretaker
         can override a stuck time/prerequisite rule.
      2. Otherwise the step's own rule decides.
    """
    if manually_released:
        return _OPEN

    rt = rule.release_type or IMMEDIATE

    if rt == IMMEDIATE:
        return _OPEN

    if rt == DAYS_AFTER_ENROLLMENT:
        if enrolled_at is None or rule.release_offset_days is None:
            # Missing config → treat as immediate. Better to open than
            # to strand a member because a creator saved a broken rule.
            return _OPEN
        unlocks = enrolled_at + timedelta(days=max(0, rule.release_offset_days))
        if now >= unlocks:
            return _OPEN
        days = _days_until(now, unlocks)
        return Availability(
            is_locked=True,
            reason=DAYS_AFTER_ENROLLMENT,
            unlocks_at=unlocks,
            message=("Available tomorrow" if days == 1
                     else f"Available in {days} days"),
        )

    if rt == FIXED_DATE:
        if rule.release_at is None:
            return _OPEN
        if now >= rule.release_at:
            return _OPEN
        return Availability(
            is_locked=True,
            reason=FIXED_DATE,
            unlocks_at=rule.release_at,
            message=f"Opens on {_human_date(rule.release_at)}",
        )

    if rt == AFTER_PREVIOUS:
        if previous is None:
            # No previous step exists (first step in the pathway). Open
            # so a creator can safely apply the same rule everywhere.
            return _OPEN
        want = rule.release_previous_state or "completed"
        if want == "started":
            open_now = previous.has_progress_record or previous.completed_at is not None
        else:
            open_now = previous.completed_at is not None
        if open_now:
            return _OPEN
        return Availability(
            is_locked=True,
            reason=AFTER_PREVIOUS,
            unlocks_at=None,
            message="Complete the previous step first",
        )

    if rt == MANUAL:
        return Availability(
            is_locked=True,
            reason=MANUAL,
            unlocks_at=None,
            message="Waiting for your facilitator",
        )

    # Unknown discriminator — treat as immediate so a future release
    # type doesn't accidentally strand old clients.
    return _OPEN


# ---------------------------------------------------------------------------
# Small format helpers
# ---------------------------------------------------------------------------

def _days_until(now: datetime, target: datetime) -> int:
    """Ceiling number of days between now and target (>=1)."""
    seconds = (target - now).total_seconds()
    days = int(seconds // 86400)
    remainder = seconds - days * 86400
    return max(1, days + (1 if remainder > 0 else 0))


def _human_date(when: datetime) -> str:
    """Server-side friendly rendering; frontend may re-format in the
    member's timezone. Uses %-d on POSIX; falls back gracefully on Windows."""
    try:
        return when.strftime("%-d %B")
    except ValueError:
        return when.strftime("%d %B").lstrip("0")
