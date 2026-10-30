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

import calendar as _calendar
from dataclasses import dataclass
from datetime import date as _date_cls
from datetime import datetime, timezone
from datetime import timedelta as _timedelta_cls
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


def reporting_date_bounds(local_date) -> tuple[datetime, datetime]:
    """The naive-UTC half-open bounds of one Australian calendar day.

    ``local_date`` is a ``date`` in the platform timezone, and the pair
    returned is ``[starts_at, ends_at)`` in naive UTC, matching how every
    timestamp in this database is stored.

    Computed by localising midnight on each of the two calendar days
    rather than by adding 24 hours, because a daylight-saving day is 23
    or 25 hours long. On the Sydney spring-forward day a 24-hour
    assumption would leave an hour of activity in neither day; on the
    autumn day it would count an hour twice.
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    tz = platform_tz()
    start_local = _dt.combine(local_date, _dt.min.time()).replace(tzinfo=tz)
    end_local = _dt.combine(local_date + _td(days=1), _dt.min.time()).replace(tzinfo=tz)
    return _to_utc_naive(start_local), _to_utc_naive(end_local)


def completed_reporting_date(moment: datetime):
    """The most recent Australian calendar day that has fully finished.

    The nightly job rebuilds this day. Taking "yesterday in the platform
    timezone" rather than "yesterday in UTC" is what makes a figure
    labelled 30 October cover the Australian 30 October — which is the
    day the person reading the dashboard means.
    """
    from datetime import timedelta as _td

    return (_to_local(moment) - _td(days=1)).date()


def local_day_start_utc(moment: datetime) -> datetime:
    """Midnight of ``moment``'s *local* day, returned as naive UTC.

    Added for BI-2. "Revenue today" on an Australian business's dashboard
    means the Australian day; a UTC midnight boundary silently folds ten
    or eleven hours of yesterday evening into today's figure, and the
    error is largest exactly when somebody checks the dashboard in the
    morning.

    Takes and returns naive UTC, matching how every timestamp in this
    database is stored.
    """
    local = _to_local(moment)
    midnight_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _to_utc_naive(midnight_local)


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


# ---------------------------------------------------------------------------
# Historical ranges and grouping
# ---------------------------------------------------------------------------
#
# Added for the World Insights history charts. Two deliberate departures
# from everything above.
#
# **These work in local dates, not UTC datetimes.** A stored daily figure
# is keyed by ``metric_daily.reporting_date``, which already *is* an
# Australian calendar day — the DST correctness was settled when that row
# was written, by ``reporting_date_bounds``. Doing the bucket arithmetic
# on ``date`` objects therefore cannot reintroduce a DST error: there is
# no hour to lose or double-count in "which week does 5 October fall in".
# Converting back to UTC instants, where DST does bite, stays the job of
# ``reporting_date_bounds`` and happens one layer down.
#
# **A bucket knows whether it finished.** An incomplete week is not a
# week that fell by 60% — it is three days being compared against seven,
# and a chart that draws it like any other column is actively
# misleading. So completeness travels with the bucket rather than being
# inferred by the reader.

HistoryRangeKey = Literal[
    "last_30_days", "last_3_months", "last_12_months", "this_fy", "all_time"
]

VALID_HISTORY_RANGES: tuple[HistoryRangeKey, ...] = get_args(HistoryRangeKey)

#: Human labels, so the API and the control never drift apart.
HISTORY_RANGE_LABELS: dict[str, str] = {
    "last_30_days": "Last 30 days",
    "last_3_months": "Last 3 months",
    "last_12_months": "Last 12 months",
    "this_fy": "This financial year",
    "all_time": "All time",
}

Grouping = Literal["daily", "weekly", "monthly"]

VALID_GROUPINGS: tuple[Grouping, ...] = get_args(Grouping)


@dataclass(frozen=True)
class DateRange:
    """An inclusive span of Australian calendar days.

    Inclusive on both ends, unlike :class:`PeriodBounds`. A stored daily
    row is identified by its date rather than by an instant, and
    ``[1 Oct, 31 Oct]`` is how somebody describes October — a half-open
    range here would mean writing 1 November to mean October, which is
    the kind of off-by-one that only shows up in a month-end figure.
    """

    label: str
    starts_on: _date_cls
    ends_on: _date_cls

    @property
    def days(self) -> int:
        return (self.ends_on - self.starts_on).days + 1


@dataclass(frozen=True)
class Bucket:
    """One point on a chart: a span of days, and whether it is finished."""

    label: str
    starts_on: _date_cls
    ends_on: _date_cls
    #: False when the bucket extends past the last completed day — a
    #: partial week or month in progress. The chart renders these
    #: differently and the API says so rather than leaving it implied.
    complete: bool = True
    #: True when the range cut this bucket short of its natural span —
    #: typically the first week or month of a range that does not begin
    #: on a Monday or the 1st. Separate from ``complete`` because the
    #: cause is different and only one of them is about time passing,
    #: but a column chart must soften both: three days drawn at full
    #: strength beside thirty-one reads as a collapse in activity.
    clipped: bool = False

    @property
    def partial(self) -> bool:
        """Whether this bucket covers fewer days than its natural span."""
        return self.clipped or not self.complete

    @property
    def days(self) -> int:
        return (self.ends_on - self.starts_on).days + 1

    def contains(self, day: _date_cls) -> bool:
        return self.starts_on <= day <= self.ends_on


def resolve_history_range(
    key: str,
    now: datetime | None = None,
    earliest: _date_cls | None = None,
) -> DateRange:
    """Inclusive local-date bounds for a named historical range.

    Every range ends on the last *completed* Australian day. Today is
    deliberately excluded: it is still happening, the nightly job has not
    recorded it, and a final data point that climbs all day makes every
    trend look like it is falling off a cliff by morning.

    ``all_time`` needs a floor from somewhere, since an unbounded start
    cannot be turned into buckets. ``earliest`` supplies it — normally
    the oldest stored reporting date — and in the absence of any data at
    all the range collapses to the single last completed day rather than
    raising, so an empty platform renders an empty chart instead of an
    error.
    """
    if key not in VALID_HISTORY_RANGES:
        raise ValueError(
            f"Unknown history range: {key!r}. Valid: {list(VALID_HISTORY_RANGES)}"
        )

    moment = now if now is not None else datetime.now(platform_tz())
    last = completed_reporting_date(moment)
    label = HISTORY_RANGE_LABELS[key]

    if key == "last_30_days":
        return DateRange(label, last - _timedelta_cls(days=29), last)

    if key == "last_12_months":
        # Calendar months back, not 365 days: "last 12 months" on
        # 15 March means 16 March to 15 March, and a leap year must not
        # shift that by a day.
        return DateRange(label, _shift_months(last, -12) + _timedelta_cls(days=1), last)

    if key == "last_3_months":
        return DateRange(label, _shift_months(last, -3) + _timedelta_cls(days=1), last)

    if key == "this_fy":
        start_year = fiscal_year_start_year(_to_local(moment))
        fy_start = _date_cls(start_year, 7, 1)
        return DateRange(
            fiscal_year_label(start_year),
            # A brand-new financial year can begin after the last
            # completed day, which would invert the range. Clamp rather
            # than return something nonsensical on 1 July.
            min(fy_start, last),
            last,
        )

    # all_time
    floor = earliest if earliest is not None and earliest <= last else last
    return DateRange(label, floor, last)


def _shift_months(day: _date_cls, months: int) -> _date_cls:
    """Move a date by whole months, clamping to the month's last day.

    31 January minus one month is 31 December, but plus one month is
    28 or 29 February rather than a date that does not exist.
    """
    total = (day.year * 12 + (day.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = _calendar.monthrange(year, month)[1]
    return _date_cls(year, month, min(day.day, last_day))


def _iso_week_start(day: _date_cls) -> _date_cls:
    """The Monday of ``day``'s week.

    Monday-start weeks, matching the ISO convention and the Australian
    working week. Stated rather than assumed because a Sunday-start week
    would silently reassign every weekend figure.
    """
    return day - _timedelta_cls(days=day.weekday())


def group_buckets(
    span: DateRange,
    grouping: str,
    last_completed: _date_cls | None = None,
) -> list[Bucket]:
    """Split a range into chart buckets, oldest first.

    The first and last buckets of a weekly or monthly grouping are
    **clipped to the range** rather than extended beyond it. A chart of
    the last 30 days grouped by month must not reach back to the 1st of
    a month it was never asked about — the column would include days
    outside the range the heading promises.

    ``complete`` is false for any bucket whose natural end falls after
    the last completed day. For a clipped first bucket that is not in
    question: the days before the range exist and were simply not asked
    for, so it is marked complete and the reader is told by the label.
    """
    if grouping not in VALID_GROUPINGS:
        raise ValueError(
            f"Unknown grouping: {grouping!r}. Valid: {list(VALID_GROUPINGS)}"
        )
    if span.ends_on < span.starts_on:
        return []

    end_of_record = last_completed if last_completed is not None else span.ends_on
    out: list[Bucket] = []
    cursor = span.starts_on

    while cursor <= span.ends_on:
        if grouping == "daily":
            natural_start = natural_end = cursor
            label = cursor.isoformat()
            nxt = cursor + _timedelta_cls(days=1)
        elif grouping == "weekly":
            natural_start = _iso_week_start(cursor)
            natural_end = natural_start + _timedelta_cls(days=6)
            label = f"w/c {natural_start.isoformat()}"
            nxt = natural_end + _timedelta_cls(days=1)
        else:  # monthly
            last_day = _calendar.monthrange(cursor.year, cursor.month)[1]
            natural_start = _date_cls(cursor.year, cursor.month, 1)
            natural_end = _date_cls(cursor.year, cursor.month, last_day)
            label = f"{_MONTH_ABBR[cursor.month]} {cursor.year}"
            nxt = natural_end + _timedelta_cls(days=1)

        out.append(Bucket(
            label=label,
            starts_on=cursor,
            # Clipped to the range the caller asked for.
            ends_on=min(natural_end, span.ends_on),
            # Judged on the *natural* end, not the clipped one. A month
            # clipped by the range end is still an unfinished month if
            # its real last day has not happened yet.
            complete=natural_end <= end_of_record,
            clipped=natural_start < span.starts_on or natural_end > span.ends_on,
        ))
        cursor = nxt

    return out


_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
