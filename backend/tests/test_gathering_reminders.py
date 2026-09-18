"""24-hour gathering reminders — sweep eligibility, idempotency, copy.

The sweep is the whole mechanism, so most of these tests drive
``sweep_due_reminders`` against real rows and assert on the
``CommunicationEvent`` table rather than on delivery. Routing is
stubbed throughout; nothing reaches a provider.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import get_template_for
from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    Space,
    SpaceMemberNotificationPrefs,
)
from app.services.gathering_reminders import (
    LOOKBACK,
    REMINDER_LEAD,
    find_due_bookings,
    format_local_start,
    sweep_due_reminders,
)


EVENT_TYPE = "gathering.reminder.24h"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 18, 9, 0, 0)


def _space(db, *, timezone_name: str = "Australia/Melbourne") -> Space:
    space = Space(
        id=_uid("sp"), slug=_uid("slug"), name="Still Water",
        timezone=timezone_name,
    )
    db.add(space)
    db.flush()
    return space


def _event(
    db, space, *, starts_at: datetime,
    status: str = "active", is_published: bool = True,
    title: str = "Morning Sit",
) -> Event:
    event = Event(
        id=_uid("ev"), space_id=space.id, title=title,
        starts_at=starts_at, status=status, is_published=is_published,
        requires_booking=True,
    )
    db.add(event)
    db.flush()
    return event


def _booking(
    db, event, user, *,
    status: BookingStatus = BookingStatus.confirmed,
    booked_at: datetime | None = None,
) -> EventBooking:
    booking = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id, status=status,
        booked_at=booked_at or (event.starts_at - timedelta(days=10)),
    )
    db.add(booking)
    db.flush()
    return booking


def _pref(db, user, space, *, enabled: bool) -> None:
    row = SpaceMemberNotificationPrefs(
        id=_uid("pref"), user_id=user.id, space_id=space.id,
        gathering_reminder_email=enabled,
    )
    db.add(row)
    db.flush()


def _reminders(db, booking_id: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == EVENT_TYPE,
            CommunicationEvent.subject_id == booking_id,
        )
        .all()
    )


def _due_event_start(now: datetime) -> datetime:
    """A start time squarely inside the sweep window at ``now``."""
    return now + REMINDER_LEAD - timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestReminderIsSent:
    def test_confirmed_booking_in_window_is_reminded_once(
        self, db, make_user, now,
    ):
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(db, event, user)
        db.flush()

        outcome = sweep_due_reminders(db, now=now)
        assert outcome.emitted == 1
        evs = _reminders(db, booking.id)
        assert len(evs) == 1
        payload = evs[0].payload
        assert payload["gathering_title"] == "Morning Sit"
        assert payload["recipient_user_id"] == user.id
        assert payload["collective_name"] == "Still Water"
        assert f"/spaces/{space.slug}/events/{event.id}" in payload["gathering_url"]

    def test_overlapping_sweeps_do_not_duplicate(self, db, make_user, now):
        """The dedupe key is what makes the overlapping window safe."""
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(db, event, user)
        db.flush()

        first = sweep_due_reminders(db, now=now)
        second = sweep_due_reminders(db, now=now + timedelta(minutes=15))
        third = sweep_due_reminders(db, now=now + timedelta(minutes=15))

        assert first.emitted == 1
        assert second.emitted == 0 and second.deduped == 1
        assert third.emitted == 0
        assert len(_reminders(db, booking.id)) == 1

    def test_a_missed_run_is_recovered_by_the_overlap_window(
        self, db, make_user, now,
    ):
        """Runs are every 15 minutes. If one is skipped, the next run's
        35-minute lookback must still cover the reminder point."""
        user = make_user()
        space = _space(db)
        # Reminder point falls just after the sweep that never ran.
        event = _event(
            db, space, starts_at=now + REMINDER_LEAD - timedelta(minutes=1),
        )
        booking = _booking(db, event, user)
        db.flush()

        # The run at `now` would have caught it — pretend it never
        # happened, and let the run 30 minutes later (one missed cycle)
        # do the work.
        recovered = sweep_due_reminders(db, now=now + timedelta(minutes=30))
        assert recovered.emitted == 1
        assert len(_reminders(db, booking.id)) == 1

    def test_lookback_spans_two_cron_cadences(self):
        """Guards the arithmetic the self-healing depends on: a
        15-minute cadence needs >= 30 minutes of lookback to survive one
        missed run."""
        assert LOOKBACK >= timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


class TestReminderIsSkipped:
    def test_cancelled_gathering(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        event = _event(
            db, space, starts_at=_due_event_start(now), status="cancelled",
        )
        booking = _booking(db, event, user)
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 0
        assert _reminders(db, booking.id) == []

    def test_unpublished_gathering(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        event = _event(
            db, space, starts_at=_due_event_start(now), is_published=False,
        )
        booking = _booking(db, event, user)
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 0
        assert _reminders(db, booking.id) == []

    @pytest.mark.parametrize("status", [
        BookingStatus.cancelled,
        BookingStatus.pending_payment,
    ])
    def test_non_confirmed_booking(self, db, make_user, now, status):
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(db, event, user, status=status)
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 0
        assert _reminders(db, booking.id) == []

    def test_booking_made_inside_the_final_24_hours(self, db, make_user, now):
        """Decision 1 — they just booked and already have a
        confirmation. A reminder now would land moments after it."""
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(
            db, event, user,
            # Booked after the reminder point had already passed.
            booked_at=event.starts_at - timedelta(hours=2),
        )
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 0
        assert _reminders(db, booking.id) == []

    def test_booking_made_just_before_the_reminder_point_is_still_sent(
        self, db, make_user, now,
    ):
        """The boundary the previous test guards — one minute earlier
        and the reminder is genuinely useful."""
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        _booking(
            db, event, user,
            booked_at=event.starts_at - REMINDER_LEAD - timedelta(minutes=1),
        )
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 1

    def test_gathering_outside_the_window(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        # Well beyond the window — not due for days.
        far = _event(db, space, starts_at=now + timedelta(days=5))
        _booking(db, far, user)
        # Already started — long past its reminder point.
        past = _event(db, space, starts_at=now + timedelta(hours=1))
        _booking(db, past, user)
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 0


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


class TestReminderPreferences:
    def test_preference_off_is_skipped(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(db, event, user)
        _pref(db, user, space, enabled=False)
        db.flush()

        outcome = sweep_due_reminders(db, now=now)
        assert outcome.emitted == 0
        assert outcome.skipped_preference == 1
        assert _reminders(db, booking.id) == []

    def test_preference_explicitly_on_is_sent(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        _booking(db, event, user)
        _pref(db, user, space, enabled=True)
        db.flush()
        assert sweep_due_reminders(db, now=now).emitted == 1

    def test_default_with_no_prefs_row_is_on(self, db, make_user, now):
        """Must match the shared resolver's default, not a local one."""
        from app.services.notification_service import _get_notification_pref
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=_due_event_start(now))
        _booking(db, event, user)
        db.flush()
        # The shared helper is the source of truth for the default.
        assert _get_notification_pref(
            db, user.id, space.id, "gathering_reminder_email",
        ) is True
        assert sweep_due_reminders(db, now=now).emitted == 1


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


class TestTimezoneFormatting:
    def test_start_is_rendered_in_the_collective_timezone(self, db):
        space = _space(db, timezone_name="Australia/Melbourne")
        # 23:00 UTC on 18 Sep is 09:00 on 19 Sep in Melbourne (AEST+10).
        event = _event(
            db, space, starts_at=datetime(2026, 9, 18, 23, 0, 0),
        )
        rendered = format_local_start(event, space)
        assert "9:00am" in rendered
        assert "19 September" in rendered
        assert "Saturday" in rendered

    def test_different_zones_render_different_local_times(self, db):
        melb = _space(db, timezone_name="Australia/Melbourne")
        london = _space(db, timezone_name="Europe/London")
        starts = datetime(2026, 9, 18, 23, 0, 0)
        e1 = _event(db, melb, starts_at=starts)
        e2 = _event(db, london, starts_at=starts)
        assert format_local_start(e1, melb) != format_local_start(e2, london)
        assert "12:00am" in format_local_start(e2, london)  # BST = UTC+1

    def test_unknown_timezone_falls_back_without_raising(self, db):
        space = _space(db, timezone_name="Not/AZone")
        event = _event(db, space, starts_at=datetime(2026, 9, 18, 23, 0, 0))
        assert "11:00pm" in format_local_start(event, space)

    def test_missing_space_falls_back_without_raising(self, db):
        space = _space(db)
        event = _event(db, space, starts_at=datetime(2026, 9, 18, 23, 0, 0))
        assert format_local_start(event, None)

    def test_emitted_payload_carries_the_local_time(self, db, make_user, now):
        user = make_user()
        space = _space(db, timezone_name="Australia/Melbourne")
        event = _event(db, space, starts_at=_due_event_start(now))
        booking = _booking(db, event, user)
        db.flush()
        sweep_due_reminders(db, now=now)
        payload = _reminders(db, booking.id)[0].payload
        assert payload["gathering_when"] == format_local_start(event, space)


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def _render(**ctx):
    t = get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL)
    return t.render(None, None, ResolvedRecipient(
        user_id="u", role_in_event="attendee", human_reason="h",
        template_context=ctx,
    ))


class TestReminderCopy:
    def test_uses_the_shared_branded_shell(self):
        html = _render(
            gathering_title="Morning Sit",
            gathering_when="Friday 19 September at 9:00am",
        ).body_html
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "Fresh Collective" in html
        assert "#F5F0E8" in html

    def test_has_no_eyebrow_treatment(self):
        html = _render(gathering_title="Morning Sit").body_html
        assert "text-transform:uppercase" not in html

    def test_contains_name_time_and_collective(self):
        p = _render(
            gathering_title="Morning Sit",
            gathering_when="Friday 19 September at 9:00am",
            collective_name="Still Water",
        )
        assert p.subject == "Tomorrow: Morning Sit"
        assert "Morning Sit" in p.body_html
        assert "Friday 19 September at 9:00am" in p.body_html
        assert "Still Water" in p.body_html

    def test_cta_points_at_the_existing_gathering_page(self):
        url = "https://fc.test/spaces/still-water/events/ev_1"
        html = _render(gathering_title="G", gathering_url=url).body_html
        m = re.search(
            r'<a href="([^"]+)"\s+style="[^"]*border-radius:999px[^"]*">'
            r'\s*(.*?)\s*</a>', html, re.S,
        )
        assert m is not None
        assert m.group(1) == url
        assert m.group(2).strip() == "View the gathering"

    def test_no_cta_when_no_url_is_available(self):
        html = _render(gathering_title="G", gathering_url="").body_html
        assert "or copy this link:" not in html

    def test_offers_a_preferences_link(self):
        """Gatherings is an unlocked category — this reminder really can
        be switched off, so the footer says so."""
        html = _render(gathering_title="G").body_html
        assert "Manage your Stay Connected preferences" in html

    def test_escapes_user_supplied_titles(self):
        html = _render(
            gathering_title='<img src=x onerror="alert(1)">',
        ).body_html
        assert "<img" not in html
        assert "&lt;img src=x" in html


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestOnlyOneReminderExists:
    def test_no_one_hour_reminder_template_is_registered(self):
        """MVP sends exactly one reminder. The 1h event stays registered
        but deliberately unrendered."""
        assert get_template_for(
            "gathering.reminder.1h", CHANNEL_EMAIL_TRANSACTIONAL,
        ) is None

    def test_sweep_never_emits_a_one_hour_reminder(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        # One hour out — inside any 1h reminder window, outside the 24h one.
        event = _event(db, space, starts_at=now + timedelta(hours=1))
        _booking(db, event, user)
        db.flush()
        sweep_due_reminders(db, now=now)
        assert db.query(CommunicationEvent).filter(
            CommunicationEvent.event_type == "gathering.reminder.1h",
        ).count() == 0


# ---------------------------------------------------------------------------
# Window helper
# ---------------------------------------------------------------------------


class TestFindDueBookings:
    def test_window_is_backward_looking_so_nothing_is_sent_early(
        self, db, make_user, now,
    ):
        """A gathering whose reminder point is still in the future must
        not be picked up — reminders are never premature."""
        user = make_user()
        space = _space(db)
        event = _event(
            db, space,
            starts_at=now + REMINDER_LEAD + timedelta(minutes=10),
        )
        _booking(db, event, user)
        db.flush()
        assert find_due_bookings(db, now=now) == []

    def test_window_upper_bound_is_inclusive(self, db, make_user, now):
        user = make_user()
        space = _space(db)
        event = _event(db, space, starts_at=now + REMINDER_LEAD)
        _booking(db, event, user)
        db.flush()
        assert len(find_due_bookings(db, now=now)) == 1

    def test_reminder_points_older_than_the_lookback_are_dropped(
        self, db, make_user, now,
    ):
        """Bounded staleness — a long outage drops reminders rather than
        sending a '24 hour' notice at six hours' warning."""
        user = make_user()
        space = _space(db)
        event = _event(
            db, space,
            starts_at=now + REMINDER_LEAD - LOOKBACK - timedelta(minutes=1),
        )
        _booking(db, event, user)
        db.flush()
        assert find_due_bookings(db, now=now) == []
