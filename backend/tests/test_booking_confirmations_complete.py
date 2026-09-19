"""Booking confirmations: transactional lock + the three remaining paths.

Four things are pinned here.

* **The transactional lock.** ``gathering.booking.confirmed`` and
  ``gathering.multi_booking.confirmed`` ignore the member's *Gatherings*
  category preference, because a receipt for something you just booked
  is not optional community noise. Everything else in that category —
  reminders above all — must keep obeying it, and suppression must keep
  applying to all of them.
* **Series booking**, which creates one EventBooking per occurrence and
  must produce exactly one email.
* **Creator manual booking**, which must say the member was *added*
  rather than implying they reserved a place themselves.
* **Creator recurring booking**, which must summarise rather than send
  one email per session.

Routing is stubbed; these assert on emitted events and decision
outcomes, not on delivery.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.categories import (
    CATEGORY_GATHERINGS,
    CHANNEL_EMAIL_TRANSACTIONAL,
    Priority,
)
from app.comms.intents import DELIVERY_MODE_LIVE, STATE_RECORDED
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.preferences import set_preference
from app.comms.registry import TRANSACTIONAL_EVENT_TYPES, is_transactional_event
from app.comms.routing.decision import process_one
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.suppressions import record_suppression
from app.comms.templates.registry import get_template_for
from app.models.platform import BookingStatus, EventBooking
from app.services.gathering_booking_emit import (
    emit_booking_confirmed,
    emit_multi_booking_confirmed,
)


SINGLE = "gathering.booking.confirmed"
MULTI = "gathering.multi_booking.confirmed"
REMINDER = "gathering.reminder.24h"


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def _booking(db, event, user, *, booked_at=None, status=BookingStatus.confirmed):
    b = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id, status=status,
        booked_at=booked_at or datetime.utcnow(),
    )
    db.add(b)
    db.flush()
    return b


def _events_of(db, event_type: str) -> list[CommunicationEvent]:
    return db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == event_type,
    ).all()


def _render(event_type: str, **ctx):
    return get_template_for(event_type, CHANNEL_EMAIL_TRANSACTIONAL).render(
        None, None,
        ResolvedRecipient(
            user_id="u", role_in_event="attendee", human_reason="h",
            template_context=ctx,
        ),
    )


def _paragraphs(html: str) -> list[str]:
    return [
        p.strip() for p in re.findall(
            r'<p style="margin:0;font-size:15\.5px[^"]*">\s*(.*?)\s*</p>',
            html, re.S,
        )
    ]


# ===========================================================================
# 1. The transactional lock
# ===========================================================================


def _comms_event(db, user, event_type: str, **payload) -> CommunicationEvent:
    from app.comms import Source, emit as comms_emit
    ev = comms_emit(
        db,
        event_type=event_type,
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="gathering",
        subject_id=_uid("g"),
        context={"collective_name": "Still Water"},
        payload=payload,
    )
    db.flush()
    return ev


def _recipient(user) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id=user.id, role_in_event="attendee",
        human_reason="You booked this gathering.",
        template_context={
            "gathering_title": "Morning Sit",
            "gathering_starts_at": "Friday 19 September at 9:00am",
            "collective_name": "Still Water",
        },
    )


class TestTransactionalLock:
    def test_only_booking_confirmations_are_locked(self):
        """Scope guard — reminders, cancellations and community events
        must never be dragged in."""
        assert TRANSACTIONAL_EVENT_TYPES == {SINGLE, MULTI}
        assert is_transactional_event(SINGLE)
        assert is_transactional_event(MULTI)
        for other in (
            REMINDER, "gathering.reminder.1h", "gathering.cancelled",
            "community.post.published", "pathway.published",
        ):
            assert not is_transactional_event(other), other

    @pytest.mark.parametrize("event_type", [SINGLE, MULTI])
    def test_silencing_gatherings_cannot_suppress_a_confirmation(
        self, db, make_user, event_type,
    ):
        """The defect this prevents: a member quietens Gatherings and
        stops getting receipts for things they booked."""
        user = make_user()
        set_preference(
            db, user_id=user.id, category_key=CATEGORY_GATHERINGS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=Priority.SILENT,
        )
        db.flush()
        ev = _comms_event(db, user, event_type, booker_id=user.id)

        outcome = process_one(
            db, event=ev, recipient=_recipient(user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_LIVE,
        )
        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent is not None
        assert intent.state != STATE_RECORDED, (
            "a silenced category must not swallow a booking confirmation"
        )
        assert outcome.suppression_reason is None

    def test_the_same_silence_still_suppresses_a_reminder(self, db, make_user):
        """The other half of the scope guard: the member's preference is
        still fully honoured for everything that is not a receipt."""
        user = make_user()
        set_preference(
            db, user_id=user.id, category_key=CATEGORY_GATHERINGS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=Priority.SILENT,
        )
        db.flush()
        ev = _comms_event(
            db, user, REMINDER,
            recipient_user_id=user.id, gathering_title="Morning Sit",
        )
        outcome = process_one(
            db, event=ev, recipient=_recipient(user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_LIVE,
        )
        intent = db.get(CommunicationIntent, outcome.intent_id)
        assert intent is not None
        assert intent.state == STATE_RECORDED, (
            "gathering reminders must still be silenceable"
        )

    def test_digest_preference_does_not_defer_a_receipt(self, db, make_user):
        """Gatherings is not a locked category, so a member may set a
        digest cadence. A receipt deferred to tomorrow is not a
        receipt."""
        user = make_user()
        set_preference(
            db, user_id=user.id, category_key=CATEGORY_GATHERINGS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        db.flush()
        ev = _comms_event(db, user, SINGLE, booker_id=user.id)
        outcome = process_one(
            db, event=ev, recipient=_recipient(user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_LIVE,
        )
        assert outcome.digest_item_id is None
        assert outcome.intent_id is not None

    @pytest.mark.parametrize("reason", ["bounced", "complained"])
    def test_hard_bounce_and_complaint_still_suppress_a_confirmation(
        self, db, make_user, reason,
    ):
        """The lock must not become a way around deliverability safety.
        Suppression runs after the preference gate and still wins."""
        user = make_user()
        record_suppression(
            db, address_type="email", address=user.email,
            reason=reason, source_provider="resend",
        )
        db.flush()
        ev = _comms_event(db, user, SINGLE, booker_id=user.id)
        outcome = process_one(
            db, event=ev, recipient=_recipient(user),
            channel=CHANNEL_EMAIL_TRANSACTIONAL,
            delivery_mode=DELIVERY_MODE_LIVE,
        )
        assert outcome.suppression_reason == reason

    def test_the_category_itself_stays_member_controllable(self, db, make_user):
        """Locking the event must not lock the category — the member can
        still set a Gatherings preference at all."""
        user = make_user()
        pref = set_preference(
            db, user_id=user.id, category_key=CATEGORY_GATHERINGS,
            channel=CHANNEL_EMAIL_TRANSACTIONAL, priority=Priority.SILENT,
        )
        assert pref is not None


# ===========================================================================
# 2. Series booking — one action, one email
# ===========================================================================


class TestSeriesBooking:
    def test_booking_eight_sessions_sends_one_email(
        self, db, make_user, make_space, make_event,
    ):
        space = make_space(name="Still Water", timezone="Australia/Melbourne")
        user = make_user()
        base = datetime(2026, 9, 18, 23, 0, 0)
        bookings = []
        for i in range(8):
            ev = make_event(
                space=space, title=f"Week {i + 1}",
                starts_at=base + timedelta(days=7 * i),
            )
            bookings.append(_booking(db, ev, user, booked_at=base))

        emitted = emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=bookings, space=space,
            scope="series:s1", operation_at=base,
        )
        assert emitted is not None
        assert len(_events_of(db, MULTI)) == 1
        # And emphatically not one per occurrence.
        assert len(_events_of(db, SINGLE)) == 0
        assert emitted.payload["session_count"] == 8

    def test_payload_carries_series_collective_and_local_schedule(
        self, db, make_user, make_space, make_event,
    ):
        space = make_space(name="Still Water", timezone="Australia/Melbourne")
        user = make_user()
        base = datetime(2026, 9, 18, 23, 0, 0)   # 09:00 next day in Melbourne
        bookings = [
            _booking(
                db,
                make_event(space=space, title="Week 1", starts_at=base),
                user, booked_at=base,
            ),
            _booking(
                db,
                make_event(
                    space=space, title="Week 2",
                    starts_at=base + timedelta(days=7),
                ),
                user, booked_at=base,
            ),
        ]
        series = type("S", (), {"id": "s1", "title": "Spring Term", "slug": "spring-term"})()

        ev = emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=bookings, space=space,
            scope="series:s1", operation_at=base, series=series,
        )
        p = ev.payload
        assert p["series_title"] == "Spring Term"
        assert p["collective_name"] == "Still Water"
        assert "9:00am" in p["first_starts_at"]
        assert "19 September" in p["first_starts_at"]
        assert "T23:00" not in p["first_starts_at"]      # never raw ISO
        assert "/gathering-series/spring-term" in p["cta_url"]
        assert len(p["schedule_preview"]) == 2

    def test_schedule_preview_is_capped_so_the_email_stays_short(
        self, db, make_user, make_space, make_event,
    ):
        space = make_space()
        user = make_user()
        base = datetime(2026, 9, 18, 23, 0, 0)
        bookings = [
            _booking(
                db,
                make_event(
                    space=space, title=f"Week {i}",
                    starts_at=base + timedelta(days=7 * i),
                ),
                user, booked_at=base,
            )
            for i in range(20)
        ]
        ev = emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=bookings, space=space,
            scope="series:big", operation_at=base,
        )
        assert ev.payload["session_count"] == 20
        assert len(ev.payload["schedule_preview"]) == 3

    def test_replaying_the_same_operation_yields_the_same_dedupe_key(self):
        """Behaviour against real committing sessions lives in
        ``test_booking_confirmations_integration.py`` — the savepoint
        fixture cannot host emit-commit-emit."""
        from app.services.gathering_booking_emit import _multi_dedupe_key
        base = datetime(2026, 9, 18, 23, 0, 0)
        assert (
            _multi_dedupe_key("u1", "series:s1", base)
            == _multi_dedupe_key("u1", "series:s1", base)
        )

    def test_no_bookings_means_no_email(self, db, make_user, make_space):
        """Booking a series where every session was already booked is
        not news."""
        space = make_space()
        user = make_user()
        assert emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=[], space=space,
            scope="series:s1", operation_at=datetime.utcnow(),
        ) is None
        assert _events_of(db, MULTI) == []

    def test_route_emits_one_summary_and_never_per_occurrence(self):
        import inspect
        from app.spaces import routes as space_routes
        src = inspect.getsource(space_routes.book_series)
        assert src.count("emit_multi_booking_confirmed(") == 1
        assert "emit_booking_confirmed(" not in src.replace(
            "emit_multi_booking_confirmed(", "",
        )


# ===========================================================================
# 3. Creator manual booking — one gathering, added by someone else
# ===========================================================================


class TestCreatorManualBooking:
    def test_member_gets_one_confirmation(self, db, make_user, make_event):
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)
        assert emit_booking_confirmed(
            db, booking=booking, added_by_creator=True,
        ) is not None
        assert len(_events_of(db, SINGLE)) == 1

    def test_copy_says_added_not_self_booked(self):
        html = _render(
            SINGLE, gathering_title="Morning Sit",
            gathering_starts_at="Friday 19 September at 9:00am",
            collective_name="Still Water", added_by_creator=True,
        ).body_html
        assert "You've been added to Morning Sit" in html
        assert "You're booked for" not in html

    def test_self_booked_copy_is_unchanged(self):
        html = _render(
            SINGLE, gathering_title="Morning Sit",
            gathering_starts_at="Friday 19 September at 9:00am",
            collective_name="Still Water", added_by_creator=False,
        ).body_html
        assert "You're booked for Morning Sit" in html
        assert "been added" not in html

    def test_payload_flags_the_attribution(self, db, make_user, make_event):
        user = make_user()
        event = make_event()
        ev = emit_booking_confirmed(
            db, booking=_booking(db, event, user), added_by_creator=True,
        )
        assert ev.payload["added_by_creator"] is True

    def test_replay_does_not_duplicate(self, db, make_user, make_event):
        from app.services.gathering_booking_emit import _dedupe_key
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)
        assert _dedupe_key(booking) == _dedupe_key(booking)

    def test_route_emits_with_creator_attribution(self):
        import inspect
        from app.creator import routes as creator_routes
        src = inspect.getsource(creator_routes.manual_book_member)
        assert "emit_booking_confirmed(" in src
        assert "added_by_creator=True" in src


# ===========================================================================
# 4. Creator recurring booking — summarise, never storm
# ===========================================================================


class TestCreatorRecurringBooking:
    def test_many_sessions_produce_one_summary(
        self, db, make_user, make_space, make_event,
    ):
        space = make_space()
        user = make_user()
        base = datetime(2026, 9, 18, 23, 0, 0)
        bookings = [
            _booking(
                db,
                make_event(
                    space=space, title="Morning Sit",
                    starts_at=base + timedelta(days=7 * i),
                ),
                user, booked_at=base,
            )
            for i in range(6)
        ]
        ev = emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=bookings, space=space,
            scope="recurring:abc", operation_at=base, added_by_creator=True,
        )
        assert ev is not None
        assert len(_events_of(db, MULTI)) == 1
        assert len(_events_of(db, SINGLE)) == 0     # no per-session storm
        assert ev.payload["session_count"] == 6
        assert ev.payload["added_by_creator"] is True

    def test_summary_shows_the_date_range(
        self, db, make_user, make_space, make_event,
    ):
        space = make_space(timezone="Australia/Melbourne")
        user = make_user()
        base = datetime(2026, 9, 18, 23, 0, 0)
        bookings = [
            _booking(
                db,
                make_event(space=space, starts_at=base + timedelta(days=7 * i)),
                user, booked_at=base,
            )
            for i in range(3)
        ]
        ev = emit_multi_booking_confirmed(
            db, user_id=user.id, bookings=bookings, space=space,
            scope="recurring:abc", operation_at=base, added_by_creator=True,
        )
        assert "19 September" in ev.payload["first_starts_at"]
        assert "3 October" in ev.payload["last_starts_at"]

        html = _render(MULTI, **ev.payload).body_html
        assert "Running from" in html
        assert "You've been added to" in html

    def test_single_session_falls_back_to_the_ordinary_confirmation(self):
        """A recurring action that books exactly one session reads
        better as a normal 'you've been added' confirmation than as a
        one-line summary."""
        import inspect
        from app.creator import routes as creator_routes
        src = inspect.getsource(creator_routes.book_recurring_sessions)
        assert "len(created) == 1" in src
        assert "emit_booking_confirmed(" in src
        assert "emit_multi_booking_confirmed(" in src

    def test_dedupe_key_is_the_operation_not_each_child_booking(self):
        """One key per action. The child booking ids do not appear in
        it, so a four-session batch cannot become four emails."""
        from app.services.gathering_booking_emit import _multi_dedupe_key
        base = datetime(2026, 9, 18, 23, 0, 0)
        key = _multi_dedupe_key("u1", "recurring:abc", base)
        assert key == _multi_dedupe_key("u1", "recurring:abc", base)
        assert "bk_" not in key

    def test_a_later_separate_operation_gets_its_own_key(self):
        from app.services.gathering_booking_emit import _multi_dedupe_key
        base = datetime(2026, 9, 18, 23, 0, 0)
        later = base + timedelta(days=1)
        assert (
            _multi_dedupe_key("u1", "recurring:abc", base)
            != _multi_dedupe_key("u1", "recurring:def", later)
        )


# ===========================================================================
# 5. Shell + safety for the new template
# ===========================================================================


class TestMultiBookingCopy:
    def test_uses_the_shared_branded_shell_without_eyebrows(self):
        html = _render(
            MULTI, collective_name="Still Water", series_title="Spring Term",
            session_count=4, first_starts_at="Friday 19 September at 9:00am",
            last_starts_at="Friday 10 October at 9:00am",
        ).body_html
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "#F5F0E8" in html
        assert "text-transform:uppercase" not in html

    def test_singular_wording_for_one_session(self):
        p = _render(
            MULTI, collective_name="Still Water", session_count=1,
            first_starts_at="Friday 19 September at 9:00am",
        )
        assert "1 session in total" in p.body_html
        assert "sessions in total" not in p.body_html

    def test_user_content_is_escaped(self):
        html = _render(
            MULTI, collective_name='<img src=x onerror="alert(1)">',
            series_title="Spring", session_count=2,
        ).body_html
        assert "<img" not in html
        assert "&lt;img src=x" in html

    def test_cta_url_is_intact(self):
        url = "https://fc.test/spaces/sw/gathering-series/spring-term"
        html = _render(
            MULTI, collective_name="Still Water", series_title="Spring Term",
            session_count=3, cta_url=url,
        ).body_html
        m = re.search(
            r'<a href="([^"]+)"\s+style="[^"]*border-radius:999px[^"]*">'
            r'\s*(.*?)\s*</a>', html, re.S,
        )
        assert m and m.group(1) == url
        assert m.group(2).strip() == "View the schedule"
