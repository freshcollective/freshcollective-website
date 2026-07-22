"""
Tests for ``app.core.periods``.

Every period boundary is checked at the days that historically break
period arithmetic: month-end, year-end, 1 July (AU FY boundary), and
29 February on a leap year.

All tests pass a fixed ``now`` so the assertions are deterministic
regardless of when the suite is run. Values returned by the helper are
naive UTC (matching the DB column type). Sydney is UTC+10 in June/July
(no DST) and UTC+11 in December/January (AEDT), which the assertions
account for explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.periods import (
    PeriodBounds,
    VALID_PERIODS,
    fiscal_year_bounds,
    fiscal_year_label,
    fiscal_year_start_year,
    resolve_period,
)

# ---------------------------------------------------------------------------
# Fiscal-year helper
# ---------------------------------------------------------------------------


class TestFiscalYearLabel:
    def test_current_century(self):
        assert fiscal_year_label(2025) == "FY 2025-26"
        assert fiscal_year_label(2026) == "FY 2026-27"

    def test_century_rollover_pads(self):
        # 1999 → 2000 → the "end" digits pad to "00"
        assert fiscal_year_label(1999) == "FY 1999-00"


class TestFiscalYearStartYear:
    def _sydney(self, year: int, month: int, day: int, hour: int = 12):
        # Build a naive UTC datetime such that its Sydney-local component
        # is (year, month, day, hour). Sydney is UTC+10 in June (AEST).
        # For the values here it's enough to subtract 10 hours from local.
        return datetime(year, month, day, hour - 10, 0, 0)

    def test_before_july_belongs_to_previous_fy(self):
        # 30 June 2026 local → FY 2025-26 (start year 2025)
        naive_utc = self._sydney(2026, 6, 30, 12)
        assert fiscal_year_start_year(naive_utc) == 2025

    def test_first_of_july_belongs_to_new_fy(self):
        # 1 July 2026 12:00 local → FY 2026-27 (start year 2026)
        naive_utc = self._sydney(2026, 7, 1, 12)
        assert fiscal_year_start_year(naive_utc) == 2026

    def test_december_belongs_to_current_fy(self):
        # Dec 2025 local → FY 2025-26 (start year 2025)
        naive_utc = self._sydney(2025, 12, 15, 12)
        assert fiscal_year_start_year(naive_utc) == 2025

    def test_utc_midnight_1_july_is_still_previous_fy_in_sydney(self):
        # 00:00 UTC on 1 July 2026 is 10:00 on 1 July in Sydney → new FY.
        # But 22:00 UTC on 30 June 2026 is 08:00 on 1 July in Sydney →
        # also new FY. Prove that UTC midnight is NOT the boundary — the
        # local wall clock is.
        # 15:00 UTC 30 June 2026 = 01:00 1 July local (Sydney) → FY 2026-27
        early_local_1_jul = datetime(2026, 6, 30, 15, 0, 0)  # 1 Jul 01:00 local
        assert fiscal_year_start_year(early_local_1_jul) == 2026
        # 13:00 UTC 30 June 2026 = 23:00 30 June local → still FY 2025-26
        late_local_30_jun = datetime(2026, 6, 30, 13, 0, 0)  # 30 Jun 23:00 local
        assert fiscal_year_start_year(late_local_30_jun) == 2025


class TestFiscalYearBounds:
    def test_bounds_are_half_open_and_naive_utc(self):
        b = fiscal_year_bounds(2025)
        assert b.label == "FY 2025-26"
        # 1 July 2025 00:00 Sydney (AEST, +10) = 30 June 2025 14:00 UTC
        assert b.starts_at == datetime(2025, 6, 30, 14, 0, 0)
        # 1 July 2026 00:00 Sydney = 30 June 2026 14:00 UTC
        assert b.ends_at == datetime(2026, 6, 30, 14, 0, 0)
        assert b.starts_at.tzinfo is None
        assert b.ends_at.tzinfo is None


# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------


def _sydney_utc(year, month, day, hour=12, minute=0):
    """Aware UTC datetime whose Sydney-local component is
    (year, month, day, hour, minute). Only correct outside DST (AEST +10)."""
    return datetime(year, month, day, hour - 10, minute, 0, tzinfo=timezone.utc)


class TestAllTime:
    def test_all_time_has_no_bounds_and_no_comparison(self):
        current, previous = resolve_period("all_time", now=_sydney_utc(2026, 7, 18, 13))
        assert current == PeriodBounds(label="All time", starts_at=None, ends_at=None)
        assert previous is None


class TestThisMonth:
    def test_mid_month(self):
        # 18 July 2026 13:30 local (AEST +10) = 03:30 UTC
        now = datetime(2026, 7, 18, 3, 30, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_month", now=now)
        # Current: 1 Jul 2026 local (30 Jun 14:00 UTC) → now
        assert current.starts_at == datetime(2026, 6, 30, 14, 0, 0)
        assert current.ends_at == datetime(2026, 7, 18, 3, 30, 0)
        # Previous: same span on June: 1 Jun 2026 local (31 May 14:00 UTC) → 18 Jun 03:30 UTC
        assert previous is not None
        assert previous.starts_at == datetime(2026, 5, 31, 14, 0, 0)
        assert previous.ends_at == datetime(2026, 6, 18, 3, 30, 0)
        assert previous.label.startswith("June 2026")

    def test_first_of_month_gives_zero_span_current(self):
        # 00:00 1 July local = 14:00 30 Jun UTC
        now = datetime(2026, 6, 30, 14, 0, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_month", now=now)
        assert current.starts_at == current.ends_at  # zero-width MTD
        assert previous is not None
        assert previous.starts_at == previous.ends_at  # zero-width comparison

    def test_year_boundary_january(self):
        # 15 Jan 2026 12:00 Sydney (AEDT +11) → 01:00 UTC
        now = datetime(2026, 1, 15, 1, 0, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_month", now=now)
        # Prev month = December 2025. 1 Dec 2025 00:00 Sydney (AEDT +11)
        # = 30 Nov 2025 13:00 UTC.
        assert previous is not None
        assert previous.starts_at == datetime(2025, 11, 30, 13, 0, 0)
        assert previous.label.startswith("December 2025")


class TestLastMonth:
    def test_full_prior_month(self):
        # Any moment in July 2026 → last_month = full June 2026
        now = datetime(2026, 7, 18, 3, 30, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("last_month", now=now)
        # Current is full June 2026: [1 Jun local, 1 Jul local)
        assert current.starts_at == datetime(2026, 5, 31, 14, 0, 0)
        assert current.ends_at == datetime(2026, 6, 30, 14, 0, 0)
        assert current.label == "June 2026"
        # Previous is full May 2026: [1 May local, 1 Jun local)
        assert previous is not None
        assert previous.starts_at == datetime(2026, 4, 30, 14, 0, 0)
        assert previous.ends_at == datetime(2026, 5, 31, 14, 0, 0)
        assert previous.label == "May 2026"

    def test_year_boundary(self):
        # Mid-January → last_month = full December of prior year
        now = datetime(2026, 1, 15, 1, 0, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("last_month", now=now)
        assert current.label == "December 2025"
        assert previous is not None
        assert previous.label == "November 2025"

    def test_leap_february_full_month(self):
        # March 2024: last_month = February 2024 (leap year — 29 days)
        # Any time in March 2024 works. Use 5 March 12:00 local.
        # AEDT: +11. Local 5 Mar 12:00 = UTC 5 Mar 01:00.
        now = datetime(2024, 3, 5, 1, 0, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("last_month", now=now)
        # Feb 2024: [1 Feb local, 1 Mar local)
        # 1 Feb 2024 AEDT = 31 Jan 2024 13:00 UTC
        # 1 Mar 2024 AEDT = 29 Feb 2024 13:00 UTC (leap day)
        assert current.starts_at == datetime(2024, 1, 31, 13, 0, 0)
        assert current.ends_at == datetime(2024, 2, 29, 13, 0, 0)
        span_days = (current.ends_at - current.starts_at).days
        assert span_days == 29


class TestThisFy:
    def test_july_start_of_new_fy(self):
        # 18 July 2026 13:30 local → FY 2026-27, 18 days in
        now = datetime(2026, 7, 18, 3, 30, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_fy", now=now)
        assert current.label == "FY 2026-27"
        assert current.starts_at == datetime(2026, 6, 30, 14, 0, 0)  # 1 Jul local
        assert current.ends_at == datetime(2026, 7, 18, 3, 30, 0)
        assert previous is not None
        # FY 2025-26 same span: [1 Jul 2025 local, 18 Jul 2025 03:30 UTC)
        assert previous.starts_at == datetime(2025, 6, 30, 14, 0, 0)
        assert previous.ends_at == datetime(2025, 7, 18, 3, 30, 0)
        assert previous.label.startswith("FY 2025-26")

    def test_before_july_still_in_previous_fy(self):
        # 15 Feb 2026 12:00 local → FY 2025-26 (started 1 Jul 2025)
        now = datetime(2026, 2, 15, 1, 0, 0, tzinfo=timezone.utc)  # AEDT +11
        current, previous = resolve_period("this_fy", now=now)
        assert current.label == "FY 2025-26"
        assert current.starts_at == datetime(2025, 6, 30, 14, 0, 0)  # 1 Jul 2025 local
        assert previous is not None
        assert previous.label.startswith("FY 2024-25")

    def test_1_july_at_midnight_is_start_of_new_fy(self):
        # 00:00 1 July 2026 Sydney local = 14:00 30 June 2026 UTC
        now = datetime(2026, 6, 30, 14, 0, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_fy", now=now)
        assert current.label == "FY 2026-27"
        # Zero-width current (just started)
        assert current.starts_at == current.ends_at

    def test_just_before_1_july_is_still_prior_fy(self):
        # 23:59 30 June 2026 Sydney local = 13:59 30 June UTC
        now = datetime(2026, 6, 30, 13, 59, 0, tzinfo=timezone.utc)
        current, previous = resolve_period("this_fy", now=now)
        assert current.label == "FY 2025-26"


class TestEmptyAndInvalid:
    def test_valid_periods_exposes_all_four(self):
        assert set(VALID_PERIODS) == {"this_month", "last_month", "this_fy", "all_time"}

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            resolve_period("last_quarter", now=_sydney_utc(2026, 7, 18))  # type: ignore[arg-type]

    def test_naive_now_treated_as_utc(self):
        naive = datetime(2026, 7, 18, 3, 30)  # naive; interpreted as UTC
        aware = datetime(2026, 7, 18, 3, 30, tzinfo=timezone.utc)
        assert resolve_period("this_fy", now=naive) == resolve_period("this_fy", now=aware)
