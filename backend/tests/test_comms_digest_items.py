"""Tests for the M5a digest-item write path."""

from __future__ import annotations

from datetime import UTC, datetime, time as dtime, timedelta

import pytest
from zoneinfo import ZoneInfo

from app.comms.categories import CATEGORY_COMMUNITY, Source
from app.comms.digest import (
    ALL_CADENCES,
    CADENCE_DAILY,
    CADENCE_WEEKLY,
    UnknownCadenceError,
    compute_next_window,
    insert_digest_item,
)
from app.comms.models import CommunicationDigestItem, CommunicationMemberSettings


class TestComputeNextWindow:
    def test_daily_default_utc_send_time(self, db, make_user):
        u = make_user()
        # Anchor "now" so the test is deterministic. Default digest
        # arrival is 08:00 in the member's TZ; with no settings row
        # TZ defaults to UTC.
        now = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)  # 05:00 UTC
        start, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_DAILY, now=now,
        )
        # Next 08:00 UTC is today.
        assert end == datetime(2026, 8, 8, 8, 0)
        assert start == datetime(2026, 8, 7, 8, 0)

    def test_daily_after_send_time_rolls_to_tomorrow(self, db, make_user):
        u = make_user()
        now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)  # after 08:00
        _, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_DAILY, now=now,
        )
        assert end == datetime(2026, 8, 9, 8, 0)

    def test_respects_member_timezone(self, db, make_user):
        u = make_user()
        settings_row = CommunicationMemberSettings(
            user_id=u.id, timezone="Australia/Sydney",
        )
        db.add(settings_row)
        db.flush()

        # 5 August 2026 22:00 UTC is 6 August 08:00 AEST → matches
        # daily 08:00 exactly, so it rolls to next day 08:00 AEST.
        now = datetime(2026, 8, 5, 22, 0, tzinfo=UTC)
        _, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_DAILY, now=now,
        )
        # End is Sydney 08:00 on 7 Aug 2026 (which is UTC 21 Aug 5 22:00 UTC ... let's compute).
        expected_end_sydney = datetime(2026, 8, 7, 8, 0, tzinfo=ZoneInfo("Australia/Sydney"))
        expected_end_utc = expected_end_sydney.astimezone(UTC).replace(tzinfo=None)
        assert end == expected_end_utc

    def test_weekly_default_sunday(self, db, make_user):
        u = make_user()
        # 8 August 2026 is a Saturday. Default weekly send is Sunday 09:00 UTC.
        now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
        start, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_WEEKLY, now=now,
        )
        # Next Sunday 09:00 = 9 August 09:00 UTC.
        assert end == datetime(2026, 8, 9, 9, 0)
        # Window start is the previous Sunday.
        assert start == datetime(2026, 8, 2, 9, 0)

    def test_weekly_on_scheduled_day_after_time_rolls_next_week(self, db, make_user):
        u = make_user()
        # 9 August 2026 12:00 UTC is a Sunday, after 09:00 send time.
        now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
        _, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_WEEKLY, now=now,
        )
        # Rolls to the following Sunday.
        assert end == datetime(2026, 8, 16, 9, 0)

    def test_bad_timezone_falls_back_to_utc(self, db, make_user):
        u = make_user()
        settings_row = CommunicationMemberSettings(
            user_id=u.id, timezone="Not/A/Real/Zone",
        )
        db.add(settings_row)
        db.flush()

        now = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
        _, end = compute_next_window(
            db, user_id=u.id, cadence=CADENCE_DAILY, now=now,
        )
        # Falls back to UTC → next 08:00 UTC same day.
        assert end == datetime(2026, 8, 8, 8, 0)

    def test_unknown_cadence_rejected(self, db, make_user):
        u = make_user()
        with pytest.raises(UnknownCadenceError):
            compute_next_window(db, user_id=u.id, cadence="monthly")  # type: ignore[arg-type]


class TestInsertDigestItem:
    def test_creates_row_with_window(self, db, make_user):
        u = make_user()
        item = insert_digest_item(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            cadence=CADENCE_DAILY,
            source_type=Source.COLLECTIVE,
            source_id="s_abc",
            human_reason="You're a member of River Weaving Collective.",
            item_payload={"post_id": "p_1", "title": "A quiet Sunday"},
        )
        assert item.id.startswith("cdi_")
        assert item.user_id == u.id
        assert item.category_key == CATEGORY_COMMUNITY
        assert item.cadence == CADENCE_DAILY
        assert item.consumed_at is None
        assert item.consumed_by_intent_id is None
        assert item.scheduled_window_end > item.scheduled_window_start
        assert item.item_payload["post_id"] == "p_1"

    def test_missing_user_id_rejected(self, db):
        with pytest.raises(ValueError):
            insert_digest_item(
                db,
                user_id="",
                category_key=CATEGORY_COMMUNITY,
                cadence=CADENCE_DAILY,
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                human_reason="anything",
            )

    def test_missing_reason_rejected(self, db, make_user):
        u = make_user()
        with pytest.raises(ValueError):
            insert_digest_item(
                db,
                user_id=u.id,
                category_key=CATEGORY_COMMUNITY,
                cadence=CADENCE_DAILY,
                source_type=Source.FRESH_COLLECTIVE,
                source_id=None,
                human_reason="",
            )

    def test_second_item_within_same_window_shares_window(self, db, make_user):
        """Two items inserted seconds apart should land in the same
        digest window — validates the deterministic computation.
        """
        u = make_user()
        now = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
        i1 = insert_digest_item(
            db, user_id=u.id, category_key=CATEGORY_COMMUNITY,
            cadence=CADENCE_DAILY,
            source_type=Source.FRESH_COLLECTIVE, source_id=None,
            human_reason="reason 1", now=now,
        )
        i2 = insert_digest_item(
            db, user_id=u.id, category_key=CATEGORY_COMMUNITY,
            cadence=CADENCE_DAILY,
            source_type=Source.FRESH_COLLECTIVE, source_id=None,
            human_reason="reason 2", now=now + timedelta(seconds=30),
        )
        assert i1.scheduled_window_end == i2.scheduled_window_end
        assert i1.scheduled_window_start == i2.scheduled_window_start

    def test_preference_change_only_affects_new_items(self, db, make_user):
        """Refinement 2: existing queued digest items keep their
        original window when the member changes their digest arrival.
        We simulate the change by re-inserting after a settings mutation
        and confirming the first item's persisted window did not shift.
        """
        u = make_user()
        now = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
        # Initial: default 08:00 UTC daily.
        first = insert_digest_item(
            db, user_id=u.id, category_key=CATEGORY_COMMUNITY,
            cadence=CADENCE_DAILY,
            source_type=Source.FRESH_COLLECTIVE, source_id=None,
            human_reason="pre-change", now=now,
        )
        first_end_before = first.scheduled_window_end

        # Member changes their daily arrival to 14:00 UTC.
        settings_row = CommunicationMemberSettings(
            user_id=u.id, daily_digest_send_local_time=dtime(14, 0),
        )
        db.add(settings_row)
        db.flush()

        # Second item picks up the new time...
        second = insert_digest_item(
            db, user_id=u.id, category_key=CATEGORY_COMMUNITY,
            cadence=CADENCE_DAILY,
            source_type=Source.FRESH_COLLECTIVE, source_id=None,
            human_reason="post-change", now=now,
        )
        assert second.scheduled_window_end == datetime(2026, 8, 8, 14, 0)

        # ...but the first item's window is unchanged.
        db.refresh(first)
        assert first.scheduled_window_end == first_end_before
