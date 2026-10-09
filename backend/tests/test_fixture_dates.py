"""The self-advancing fixture dates stay correct as they advance.

``tests/test_series_advance_booking.py`` pins a term to a specific
calendar because its subject is week boundaries and allowance windows.
On 2026-10-09 all 19 of its booking tests were failing with "This
gathering has already started" — the fixtures had aged past real
``utcnow()``, so a file whose entire purpose is guarding weekly and
total credit caps had been silently inert for some time. Nobody had
touched the booking code; the calendar had moved.

Re-pinning to a later year would reset the same fuse, so the dates now
shift forward by whole 52-week periods. That trades one failure mode
for a subtler one: a shift that *runs* but quietly breaks the
relationships the scenario depends on — two sessions no longer in the
same ISO week, a Saturday that becomes a Sunday, a December date that
lands in a different daylight-saving season. Those would not fail
loudly. They would just stop testing what they claim to.

So this file asserts the invariants directly, across many future shift
periods rather than only today's.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.test_series_advance_booking import (
    BASE_TERM_START,
    DATE_SHIFT,
    _date_shift,
)

MELBOURNE = ZoneInfo("Australia/Melbourne")
UTC = ZoneInfo("UTC")

SOURCE = Path(__file__).resolve().parent / "test_series_advance_booking.py"

# The scenario's original calendar, as written.
BASE_SAME_WEEK = datetime(2026, 10, 8, 7, 0, 0)    # Thu, same ISO week
BASE_TERM_END = datetime(2026, 12, 12, 12, 0, 0)   # Sat
BASE_NEAR_END = datetime(2026, 12, 11, 22, 0, 0)   # Fri 22:00Z = Sat 9am AEDT
BASE_PAST_START = datetime(2025, 7, 1, 7, 0, 0)    # a term already over

# Twenty years of shifts, so an invariant that only holds for the next
# one or two periods is caught now rather than by a future developer.
SIMULATED_NOWS = [
    datetime(2026, 10, 9, 12, 0, 0) + timedelta(days=364 * n) for n in range(20)
]


def _shift_for(now: datetime) -> timedelta:
    return _date_shift(now)


class TestTheTermIsAlwaysInTheFuture:
    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_term_start_stays_ahead_of_now(self, now):
        # The original failure, asserted directly: whatever "now" is,
        # the term has not started yet.
        assert BASE_TERM_START + _shift_for(now) > now

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_there_is_enough_lead_time_to_run_the_suite(self, now):
        # A term starting in an hour would make the suite's result
        # depend on how long it takes to run.
        lead = (BASE_TERM_START + _shift_for(now)) - now
        assert lead >= timedelta(days=29), lead

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_already_finished_term_stays_finished(self, now):
        # One scenario needs a term that is genuinely over. If the shift
        # ever carried it into the future, that test would start
        # asserting the opposite of its name.
        assert BASE_PAST_START + _shift_for(now) < now

    def test_todays_shift_is_what_the_module_actually_uses(self):
        # Guards against the invariants being proven for a recomputed
        # shift while the fixtures use a different one.
        assert DATE_SHIFT == _date_shift(datetime.utcnow())


class TestRelationshipsSurviveTheShift:
    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_shift_is_a_whole_number_of_weeks(self, now):
        # This is what preserves every weekday, and with it every
        # "same week" relationship in the file.
        shift = _shift_for(now)
        assert shift.days % 7 == 0, shift
        assert shift.seconds == 0

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_weekdays_are_preserved(self, now):
        shift = _shift_for(now)
        for base in (
            BASE_TERM_START, BASE_SAME_WEEK, BASE_TERM_END,
            BASE_NEAR_END, BASE_PAST_START,
        ):
            assert (base + shift).weekday() == base.weekday(), base

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_two_same_week_sessions_remain_in_one_iso_week(self, now):
        # The weekly-cap tests are meaningless if these drift apart:
        # the cap would never be reached and the test would pass for
        # the wrong reason.
        shift = _shift_for(now)
        start = (BASE_TERM_START + shift).isocalendar()[:2]
        same = (BASE_SAME_WEEK + shift).isocalendar()[:2]
        assert start == same, (start, same)

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_term_end_stays_after_the_term_start(self, now):
        shift = _shift_for(now)
        assert BASE_TERM_END + shift > BASE_TERM_START + shift

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_gap_between_every_date_is_unchanged(self, now):
        # A uniform shift is the only thing that keeps the scenario's
        # arithmetic — "3 days after end", "25 days before start" —
        # true without each one being restated here.
        shift = _shift_for(now)
        for a, b in (
            (BASE_TERM_START, BASE_SAME_WEEK),
            (BASE_TERM_START, BASE_TERM_END),
            (BASE_NEAR_END, BASE_TERM_END),
        ):
            assert (b + shift) - (a + shift) == b - a


class TestDaylightSavingSeasonIsPreserved:
    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_near_end_session_stays_9am_melbourne(self, now):
        # ``starts_at=…22:00`` carries the comment "Sat 12 Dec 9am
        # AEDT". That reading depends on Melbourne being on daylight
        # saving at that point in the year. 364-day periods drift the
        # calendar date by about a day each time, which keeps December
        # in December — but only an assertion makes that a guarantee.
        shifted = BASE_NEAR_END + _shift_for(now)
        local = shifted.replace(tzinfo=UTC).astimezone(MELBOURNE)
        assert (local.hour, local.minute) == (9, 0), local
        assert local.strftime("%A") == "Saturday", local
        # +11:00 is AEDT; +10:00 would mean the date had slipped out of
        # the daylight-saving window.
        assert local.utcoffset() == timedelta(hours=11), local.utcoffset()

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_same_week_pair_always_shares_one_utc_offset(self, now):
        # 364-day periods drift the calendar date by about 1.25 days a
        # year, so from roughly four periods out the term start crosses
        # from AEDT into AEST. That is harmless — but only while both
        # sessions cross *together*. If one moved and the other did not,
        # their local times would separate by an hour and a Monday/
        # Thursday pair could land in different local weeks, quietly
        # defeating the weekly-cap tests.
        #
        # (An earlier version of this test asserted the term start
        # stayed in October. That is not actually required by anything,
        # and it fails from period 3 — asserting it would have forced a
        # pointless redesign of the shift.)
        shift = _shift_for(now)
        start = (BASE_TERM_START + shift).replace(tzinfo=UTC).astimezone(MELBOURNE)
        same = (BASE_SAME_WEEK + shift).replace(tzinfo=UTC).astimezone(MELBOURNE)
        assert start.utcoffset() == same.utcoffset(), (start, same)

    @pytest.mark.parametrize("now", SIMULATED_NOWS)
    def test_the_same_week_pair_shares_a_melbourne_week_too(self, now):
        # The allowance bucket is a calendar week. Asserting it in UTC
        # alone would miss a pair that straddles a local week boundary.
        shift = _shift_for(now)
        start = (BASE_TERM_START + shift).replace(tzinfo=UTC).astimezone(MELBOURNE)
        same = (BASE_SAME_WEEK + shift).replace(tzinfo=UTC).astimezone(MELBOURNE)
        assert start.isocalendar()[:2] == same.isocalendar()[:2], (start, same)


class TestNoNewLiteralDatesCreepBackIn:
    def test_every_fixture_date_goes_through_the_shift(self):
        # A new ``datetime(2027, …)`` added by hand would not move with
        # the others and would re-introduce the original bug for one
        # test. The anchor is the single permitted exception, and it is
        # matched on its own line rather than by name anywhere.
        source = SOURCE.read_text()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if re.search(r"\bdatetime\(20\d\d,", line)
            and not line.strip().startswith("#")
            and "BASE_TERM_START = datetime(" not in line
        ]
        assert offenders == [], offenders

    def test_the_anchor_is_still_a_plain_datetime(self):
        # If the anchor itself were shifted, the shift would compound
        # every run and the dates would run away into the future.
        assert isinstance(BASE_TERM_START, datetime)
        assert BASE_TERM_START == datetime(2026, 10, 5, 7, 0, 0)
