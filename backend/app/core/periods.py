"""
Reusable period boundaries for the Commerce section.

**Design invariants:**

- Every boundary is a **half-open interval**: ``starts_at`` is inclusive,
  ``ends_at`` is exclusive. This is the only shape that composes without
  arithmetic hazards near midnight, month rollover, or DST transitions.

- All boundary computation is done in the platform's configured local
  timezone (:attr:`Settings.platform_timezone`, default
  ``Australia/Sydney``). The resulting UTC datetimes are **naive** — they
  match the DB storage of ``PaymentTransaction.created_at``
  (``DateTime(timezone=False)``, storing UTC without an offset).

- The Australian financial year runs 1 July → 30 June in the platform
  timezone. Notation is ``FY 2025-26``, meaning the FY that begins
  1 July 2025 and ends 30 June 2026.

- ``all_time`` is the only period that returns no comparison window —
  ``previous_bounds`` is ``None``, never a fabricated zero.

- ``resolve_period`` accepts a ``now`` override so the whole module is
  deterministically testable.

**Comparison-period semantics:**

- ``this_month``  — MTD, month start → now.  Comparison is same
  day-count on the previous month (so on 15 July, MTD covers 1–15 July
  and the comparison covers 1–15 June).
- ``last_month``  — the full prior calendar month.  Comparison is the
  full month before that.
- ``this_fy``     — FYTD, 1 July → now.  Comparison is same day-of-year
  on the prior FY.
- ``all_time``    — unbounded, no comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from app.core.config import settings

PeriodKey = Literal["this_month", "last_month", "this_fy", "all_time"]

VALID_PERIODS: tuple[PeriodKey, ...] = get_args(PeriodKey)


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PeriodBounds:
    """A half-open UTC window plus a human-facing label.

    ``starts_at`` inclusive; ``ends_at`` exclusive. ``None`` on either
    side means the interval is open on that end (only used for
    ``all_time``). Values are naive datetimes representing UTC — this
    matches the DB storage of ``PaymentTransaction.created_at``.
    """

    label: str
    starts_at: datetime | None
    ends_at: datetime | None


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------


def platform_tz() -> ZoneInfo:
    """Return the ``ZoneInfo`` for the configured platform timezone."""
    return ZoneInfo(settings.platform_timezone)


def _to_aware(dt: datetime) -> datetime:
    """Naive datetime → UTC-aware; aware datetime → returned untouched.

    Naive datetimes in this codebase always represent UTC (the DB storage
    convention), so that's how we lift them.
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _to_local(dt: datetime) -> datetime:
    """Return ``dt`` as a timezone-aware datetime in ``platform_tz()``."""
    return _to_aware(dt).astimezone(platform_tz())


def _to_utc_naive(local_dt: datetime) -> datetime:
    """Convert a timezone-aware local datetime to naive UTC (DB shape)."""
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fiscal-year helpers
# ---------------------------------------------------------------------------


def fiscal_year_start_year(dt: datetime) -> int:
    """Return the *start* calendar year of the AU FY containing ``dt``.

    ``dt`` is interpreted in the platform timezone. A datetime whose
    local component is 1 July belongs to the FY that begins on that day.
    """
    local = _to_local(dt)
    return local.year if local.month >= 7 else local.year - 1


def fiscal_year_label(start_year: int) -> str:
    """Return the ``FY 2025-26`` style label for an FY starting in ``start_year``."""
    end_two = (start_year + 1) % 100
    return f"FY {start_year}-{end_two:02d}"


def fiscal_year_bounds(start_year: int) -> PeriodBounds:
    """Return half-open UTC bounds for the full AU FY starting ``start_year``."""
    tz = platform_tz()
    start_local = datetime(start_year, 7, 1, 0, 0, 0, tzinfo=tz)
    end_local = datetime(start_year + 1, 7, 1, 0, 0, 0, tzinfo=tz)
    return PeriodBounds(
        label=fiscal_year_label(start_year),
        starts_at=_to_utc_naive(start_local),
        ends_at=_to_utc_naive(end_local),
    )


# ---------------------------------------------------------------------------
# Month helpers
# ---------------------------------------------------------------------------

_MONTH_LABELS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _local_first_of_month(year: int, month: int) -> datetime:
    """00:00 on the 1st of ``month`` in the platform timezone."""
    return datetime(year, month, 1, 0, 0, 0, tzinfo=platform_tz())


def _add_months(first_of_month: datetime, n: int) -> datetime:
    """Add ``n`` months to a first-of-month local datetime.

    Preserves timezone. Handles negative deltas and year rollover.
    """
    total = first_of_month.month - 1 + n
    year = first_of_month.year + total // 12
    month = total % 12 + 1
    return datetime(year, month, 1, 0, 0, 0, tzinfo=first_of_month.tzinfo)


def _month_label(local_first: datetime) -> str:
    return f"{_MONTH_LABELS[local_first.month - 1]} {local_first.year}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_period(
    period: PeriodKey,
    now: datetime | None = None,
) -> tuple[PeriodBounds, PeriodBounds | None]:
    """Return ``(current, previous)`` bounds for the named period.

    ``previous`` is ``None`` for ``all_time`` and never fabricated. All
    returned datetimes are naive UTC. ``now`` accepts either a
    timezone-aware or a naive (UTC) datetime; callers should pass
    ``None`` outside tests.
    """
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Unknown period: {period!r}. Valid: {list(VALID_PERIODS)}"
        )

    now_local = _to_local(now) if now is not None else datetime.now(platform_tz())
    now_utc = _to_utc_naive(now_local)

    if period == "all_time":
        return (
            PeriodBounds(label="All time", starts_at=None, ends_at=None),
            None,
        )

    if period == "this_month":
        month_start_local = _local_first_of_month(now_local.year, now_local.month)
        prev_start_local = _add_months(month_start_local, -1)
        # MTD delta: from month start to now, translated onto previous month.
        elapsed = now_local - month_start_local
        return (
            PeriodBounds(
                label="This month",
                starts_at=_to_utc_naive(month_start_local),
                ends_at=now_utc,
            ),
            PeriodBounds(
                label=f"{_month_label(prev_start_local)} (same span)",
                starts_at=_to_utc_naive(prev_start_local),
                ends_at=_to_utc_naive(prev_start_local + elapsed),
            ),
        )

    if period == "last_month":
        this_start_local = _local_first_of_month(now_local.year, now_local.month)
        last_start_local = _add_months(this_start_local, -1)
        before_last_start_local = _add_months(this_start_local, -2)
        return (
            PeriodBounds(
                label=_month_label(last_start_local),
                starts_at=_to_utc_naive(last_start_local),
                ends_at=_to_utc_naive(this_start_local),
            ),
            PeriodBounds(
                label=_month_label(before_last_start_local),
                starts_at=_to_utc_naive(before_last_start_local),
                ends_at=_to_utc_naive(last_start_local),
            ),
        )

    if period == "this_fy":
        fy_start = fiscal_year_start_year(now_local)
        fy_start_local = datetime(fy_start, 7, 1, 0, 0, 0, tzinfo=platform_tz())
        prev_fy_start_local = datetime(fy_start - 1, 7, 1, 0, 0, 0, tzinfo=platform_tz())
        elapsed = now_local - fy_start_local
        return (
            PeriodBounds(
                label=fiscal_year_label(fy_start),
                starts_at=_to_utc_naive(fy_start_local),
                ends_at=now_utc,
            ),
            PeriodBounds(
                label=f"{fiscal_year_label(fy_start - 1)} (same span)",
                starts_at=_to_utc_naive(prev_fy_start_local),
                ends_at=_to_utc_naive(prev_fy_start_local + elapsed),
            ),
        )

    # Exhaustive — mypy would flag any missing PeriodKey branch.
    raise AssertionError(f"unreachable period branch: {period}")  # pragma: no cover
