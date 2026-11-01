"""Reporting dates at the edges, on frozen clocks.

Why this file exists
--------------------
Four reporting tests failed for a week and none of them was about
reporting. Each had quietly assumed something about today's date — that
three consecutive days share a month, that a UTC month start is an
Australian one, that last month is comfortably in the past — and each
was correct on roughly twenty-seven days in thirty. The suite was
reporting a defect that did not exist and hiding the fact that these
boundaries had no deliberate coverage at all.

So the boundaries are pinned here, on explicit instants. Every
function under test already accepts ``now`` or a date; nothing is
monkeypatched, and nothing depends on when the suite runs.

The cases are the ones that actually bit, plus the ones next to them:
the first, middle and last day of a month; a three-month window
grouped monthly; a part-finished period; and both Australian
daylight-saving transitions, where a day is 23 or 25 hours long and a
24-hour assumption silently loses or double-counts an hour.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.periods import (
    completed_reporting_date,
    fiscal_year_start_year,
    group_buckets,
    platform_tz,
    reporting_date_bounds,
    resolve_history_range,
    resolve_period,
    resolve_reporting_period,
)

#: Sydney daylight saving in 2026: forward on 4 October, back on 5 April.
DST_STARTS = date(2026, 10, 4)
DST_ENDS = date(2026, 4, 5)


def syd(y, m, d, hh=12, mm=0) -> datetime:
    """A local Australian instant, as the platform reckons time."""
    return datetime(y, m, d, hh, mm, tzinfo=platform_tz())


class TestTheLastCompletedDay:
    """Every range ends here, so every range inherits its edges."""

    @pytest.mark.parametrize(
        "moment,expected",
        [
            # Mid-month, unremarkable.
            (syd(2026, 10, 15), date(2026, 10, 14)),
            # The first of a month: yesterday is in the month before.
            (syd(2026, 11, 1, 0, 30), date(2026, 10, 31)),
            # The last of a month.
            (syd(2026, 10, 31, 23, 30), date(2026, 10, 30)),
            # The first of a financial year.
            (syd(2026, 7, 1, 9), date(2026, 6, 30)),
        ],
    )
    def test_it_is_yesterday_in_australia(self, moment, expected):
        assert completed_reporting_date(moment) == expected

    def test_a_utc_instant_can_be_a_different_australian_day(self):
        """The assumption behind two of the failures.

        Late on 1 November in UTC is already 2 November in Sydney, so
        a UTC month start is not an Australian one and arithmetic that
        mixes them lands a day out.
        """
        utc_evening = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)
        assert completed_reporting_date(utc_evening) == date(2026, 11, 1)
        assert utc_evening.date() == date(2026, 11, 1)
        # Same instant, different local day — which is the whole point.
        assert utc_evening.astimezone(platform_tz()).date() == date(2026, 11, 2)


class TestADayIsNotAlwaysTwentyFourHours:
    """Australian daylight saving, which a timedelta cannot model."""

    def test_the_spring_forward_day_is_twenty_three_hours(self):
        starts_at, ends_at = reporting_date_bounds(DST_STARTS)
        assert (ends_at - starts_at) == timedelta(hours=23)

    def test_the_autumn_day_is_twenty_five_hours(self):
        starts_at, ends_at = reporting_date_bounds(DST_ENDS)
        assert (ends_at - starts_at) == timedelta(hours=25)

    def test_an_ordinary_day_is_twenty_four(self):
        starts_at, ends_at = reporting_date_bounds(date(2026, 10, 15))
        assert (ends_at - starts_at) == timedelta(hours=24)

    def test_consecutive_days_never_overlap_or_leave_a_gap(self):
        """Across both transitions, the bounds must tile exactly.

        An hour in neither day, or in both, is how activity goes
        missing or gets counted twice on one day a year.
        """
        for transition in (DST_STARTS, DST_ENDS):
            for offset in range(-2, 3):
                day = transition + timedelta(days=offset)
                _, ends_at = reporting_date_bounds(day)
                next_starts_at, _ = reporting_date_bounds(day + timedelta(days=1))
                assert ends_at == next_starts_at, day

    def test_a_thirty_day_window_over_the_change_is_not_thirty_times_24(self):
        """The invariant a test asserted wrongly and failed on.

        Thirty Australian days spanning the spring transition are 30
        days *minus an hour* in absolute time. Both facts are true;
        only one of them is "thirty days".
        """
        current, previous = resolve_reporting_period(
            "last_30_days", syd(2026, 11, 2),
        )
        assert previous is not None
        span = current.ends_at - current.starts_at
        assert span == timedelta(days=30) - timedelta(hours=1)
        # And the comparison window sits immediately before it.
        assert previous.ends_at == current.starts_at


class TestThreeMonthsGroupedMonthly:
    """The grouping that broke, pinned on every edge of a month."""

    def _buckets(self, now):
        span = resolve_history_range("last_3_months", now)
        return group_buckets(span, "monthly", completed_reporting_date(now))

    @pytest.mark.parametrize(
        "now,label",
        [
            (syd(2026, 11, 1, 9), "the first of a month"),
            (syd(2026, 11, 2, 9), "the second"),
            (syd(2026, 11, 15, 9), "mid-month"),
            (syd(2026, 11, 30, 9), "the last of a month"),
        ],
    )
    def test_the_buckets_cover_the_span_without_gaps(self, now, label):
        buckets = self._buckets(now)
        assert buckets, label
        for earlier, later in zip(buckets, buckets[1:]):
            assert later.starts_on == earlier.ends_on + timedelta(days=1), label

    @pytest.mark.parametrize(
        "now", [syd(2026, 11, 1, 9), syd(2026, 11, 2, 9), syd(2026, 11, 15, 9)],
    )
    def test_the_range_never_reaches_outside_itself(self, now):
        span = resolve_history_range("last_3_months", now)
        buckets = self._buckets(now)
        assert buckets[0].starts_on == span.starts_on
        assert buckets[-1].ends_on == span.ends_on

    def test_a_first_of_month_run_still_has_a_final_bucket(self):
        """On the 1st, the range ends on the last day of the month
        before, so the final bucket is a whole month and nothing is
        in progress. On any other day the final bucket is partial.
        """
        on_the_first = self._buckets(syd(2026, 11, 1, 9))
        assert on_the_first[-1].ends_on == date(2026, 10, 31)

        mid_month = self._buckets(syd(2026, 11, 15, 9))
        assert mid_month[-1].ends_on == date(2026, 11, 14)

    def test_a_clipped_first_bucket_is_marked_rather_than_drawn_full(self):
        """Three months back from mid-November starts mid-August, so
        August's column holds half a month and must say so — thirty-one
        days of activity beside sixteen reads as a collapse."""
        first = self._buckets(syd(2026, 11, 15, 9))[0]
        assert first.clipped is True

    def test_three_consecutive_days_can_straddle_two_buckets(self):
        """Exactly the assumption that failed.

        On the 2nd, the last three completed days are 30 and 31
        October and 1 November — two monthly buckets, not one. A flow
        sums the days *within* a bucket, which is correct; a test that
        reads only the final bucket sees one day's worth.
        """
        now = syd(2026, 11, 2, 9)
        last = completed_reporting_date(now)
        days = [last - timedelta(days=i) for i in range(3)]
        buckets = self._buckets(now)
        holding = {
            next(
                b.label for b in buckets if b.starts_on <= d <= b.ends_on
            )
            for d in days
        }
        assert len(holding) == 2, holding


class TestPartialPeriods:
    def test_a_month_in_progress_is_not_complete(self):
        now = syd(2026, 11, 15, 9)
        span = resolve_history_range("this_fy", now)
        buckets = group_buckets(span, "monthly", completed_reporting_date(now))
        assert buckets[-1].complete is False

    def test_a_finished_month_is_complete(self):
        now = syd(2026, 11, 15, 9)
        span = resolve_history_range("this_fy", now)
        buckets = group_buckets(span, "monthly", completed_reporting_date(now))
        # July through October have all finished.
        assert all(b.complete for b in buckets[:-1])

    def test_today_is_never_included(self):
        """Every range ends on the last completed day. A part-day
        climbing all morning makes every trend look like it is falling
        off a cliff by lunchtime."""
        for key in ("last_30_days", "last_3_months", "last_12_months", "this_fy"):
            span = resolve_history_range(key, syd(2026, 11, 15, 9))
            assert span.ends_on == date(2026, 11, 14), key


class TestAustralianFinancialYears:
    @pytest.mark.parametrize(
        "moment,start_year",
        [
            (syd(2026, 6, 30, 23), 2025),   # the last day of FY2025-26
            (syd(2026, 7, 1, 0, 1), 2026),  # the first day of FY2026-27
            (syd(2026, 11, 15), 2026),
        ],
    )
    def test_the_year_turns_on_the_first_of_july(self, moment, start_year):
        assert fiscal_year_start_year(moment) == start_year

    def test_a_financial_year_beginning_today_does_not_invert(self):
        """On 1 July the FY starts after the last completed day. The
        range clamps rather than running backwards."""
        span = resolve_history_range("this_fy", syd(2026, 7, 1, 9))
        assert span.starts_on <= span.ends_on


class TestTheTwoPeriodVocabulariesAgree:
    @pytest.mark.parametrize(
        "now",
        [syd(2026, 11, 1, 9), syd(2026, 11, 2, 9), syd(2026, 11, 15, 9),
         syd(2026, 11, 30, 9), syd(2026, 7, 1, 9)],
    )
    def test_a_named_period_resolves_identically_through_both(self, now):
        for key in ("this_month", "last_month", "this_fy", "all_time"):
            assert resolve_reporting_period(key, now) == resolve_period(key, now)

    @pytest.mark.parametrize(
        "now", [syd(2026, 11, 1, 9), syd(2026, 11, 15, 9), syd(2026, 4, 6, 9)],
    )
    def test_a_rolling_range_compares_against_the_span_before_it(self, now):
        for key in ("last_30_days", "last_3_months", "last_12_months"):
            current, previous = resolve_reporting_period(key, now)
            assert previous is not None, key
            assert previous.ends_at == current.starts_at, key
            # Equal in *days*, which is the claim — not in hours, which
            # daylight saving makes false twice a year.
            span = resolve_history_range(key, now)
            days = (span.ends_on - span.starts_on).days + 1
            hours = (current.ends_at - current.starts_at).total_seconds() / 3600
            assert abs(hours - days * 24) <= 1, key

    def test_this_month_on_the_first_is_a_part_day_not_a_whole_month(self):
        """A reader opening the dashboard on 1 November sees November
        so far, which is a few hours — not October."""
        current, _ = resolve_period("this_month", syd(2026, 11, 1, 9))
        assert current.starts_at == reporting_date_bounds(date(2026, 11, 1))[0]
