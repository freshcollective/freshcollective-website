"""Booking-confirmation emails — regression cover for the cutover gap.

``d605535`` stood the legacy sender down for ``gathering.booking.confirmed``
and defined a replacement helper it never called. Once ``gatherings``
entered ``COMMS_LIVE_TOPICS`` on 2026-08-23, members stopped receiving
booking confirmations on every path.

These tests pin the two paths that regressed:

* member self-booking — fresh **and** reactivated-cancelled branches;
* Stripe ticket fulfilment.

The three paths that never had a confirmation (series booking, creator
manual booking, creator recurring booking) are deliberately out of
scope here and are covered by :class:`TestUnwiredPathsStillSilent`,
which documents the current state so the follow-up change has a
baseline to flip.

Routing is stubbed throughout — these assert on emitted events, not on
delivery.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import app.comms.templates  # noqa: F401 — registers templates
import app.comms.routing.resolvers  # noqa: F401 — registers resolvers
from app.comms.models import CommunicationEvent
from app.models.platform import BookingStatus, EventBooking
from app.services.gathering_booking_emit import emit_booking_confirmed
from app.services.gathering_reminders import format_local_start


EVENT_TYPE = "gathering.booking.confirmed"


@pytest.fixture(autouse=True)
def _no_dispatch():
    """Assert on events, never on delivery."""
    with patch("app.comms.rollout.schedule_routing_if_needed", return_value=None):
        yield


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


def _booking(db, event, user, *, status=BookingStatus.confirmed, booked_at=None):
    booking = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id, status=status,
        booked_at=booked_at or datetime.utcnow(),
    )
    db.add(booking)
    db.flush()
    return booking


def _events(db, subject_id: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == EVENT_TYPE,
            CommunicationEvent.subject_id == subject_id,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# The emit itself
# ---------------------------------------------------------------------------


class TestEmitBookingConfirmed:
    def test_emits_once_for_a_confirmed_booking(self, db, make_user, make_event):
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)

        ev = emit_booking_confirmed(db, booking=booking)
        assert ev is not None
        assert len(_events(db, event.id)) == 1

    def test_dedupe_key_is_stable_for_a_replay(self, db, make_user, make_event):
        """Webhook re-delivery changes nothing about the booking, so the
        key is identical and the second insert is refused by the unique
        index. (The behaviour itself is exercised against real
        committing sessions in
        ``test_booking_confirmation_integration.py`` — the savepoint
        fixture here cannot host commit-then-emit.)"""
        from app.services.gathering_booking_emit import _dedupe_key
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)
        assert _dedupe_key(booking) == _dedupe_key(booking)

    def test_dedupe_key_changes_when_a_booking_is_genuinely_remade(
        self, db, make_user, make_event,
    ):
        """Cancel then rebook weeks later reuses the row but stamps a
        fresh ``booked_at`` — a new act of booking, and its own
        confirmation."""
        from app.services.gathering_booking_emit import _dedupe_key
        user = make_user()
        event = make_event()
        booking = _booking(
            db, event, user, booked_at=datetime.utcnow() - timedelta(days=14),
        )
        first_key = _dedupe_key(booking)

        booking.status = BookingStatus.cancelled
        booking.status = BookingStatus.confirmed
        booking.booked_at = datetime.utcnow()
        db.flush()

        assert _dedupe_key(booking) != first_key

    def test_unresolvable_gathering_emits_nothing_and_does_not_raise(
        self, db, make_user,
    ):
        """``Event.space_id`` is NOT NULL, so the unresolvable case is a
        booking pointing at a gathering that no longer exists."""
        from types import SimpleNamespace
        booking = SimpleNamespace(
            id="bk_ghost", event_id="ev_does_not_exist", user_id="u_x",
            booked_at=datetime.utcnow(),
        )
        assert emit_booking_confirmed(db, booking=booking) is None

    def test_comms_failure_never_propagates(self, db, make_user, make_event):
        """A booking the member has been told succeeded must not be
        rolled back by an email problem."""
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)
        with patch(
            "app.comms.emit", side_effect=RuntimeError("comms exploded"),
        ):
            assert emit_booking_confirmed(db, booking=booking) is None


# ---------------------------------------------------------------------------
# Payload — the three defects the audit found
# ---------------------------------------------------------------------------


class TestPayloadCorrectness:
    @pytest.fixture
    def emitted(self, db, make_user, make_space, make_event):
        space = make_space(name="Still Water", timezone="Australia/Melbourne")
        # 23:00 UTC is 09:00 next morning in Melbourne — a start time
        # that renders differently in the two zones.
        event = make_event(
            space=space,
            starts_at=datetime(2026, 9, 18, 23, 0, 0),
            title="Morning Sit",
        )
        user = make_user()
        booking = _booking(db, event, user)
        ev = emit_booking_confirmed(db, booking=booking)
        return ev, space, event, booking

    def test_carries_the_real_collective_name(self, emitted):
        ev, space, _, _ = emitted
        # The resolver reads collective_name from context — this is the
        # field that was permanently None before the fix.
        assert ev.context["collective_name"] == "Still Water"
        assert ev.payload["collective_name"] == "Still Water"

    def test_start_time_is_local_and_not_raw_iso(self, emitted):
        ev, space, event, _ = emitted
        when = ev.payload["gathering_starts_at"]
        assert when == format_local_start(event, space)
        assert "9:00am" in when
        assert "19 September" in when
        # The old defect: a bare ISO timestamp rendered verbatim.
        assert "T23:00" not in when
        assert event.starts_at.isoformat() != when

    def test_source_is_the_collective_not_the_booker(self, emitted):
        ev, space, _, booking = emitted
        assert str(ev.source_type) == "collective"
        assert ev.source_id == space.id
        # The old defect fell back to attributing the message to the
        # member who booked it.
        assert ev.source_id != booking.user_id

    def test_subject_stays_the_gathering_so_the_resolver_is_correct(
        self, emitted,
    ):
        ev, _, event, booking = emitted
        assert ev.subject_id == event.id
        assert ev.context["booking_id"] == booking.id

    def test_resolver_and_template_render_from_this_payload(self, db, emitted):
        """End-to-end of the rendering contract: the payload this emit
        produces must satisfy the registered resolver and template."""
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import get_resolver_for
        from app.comms.templates.registry import get_template_for

        ev, _, _, booking = emitted
        recipients = get_resolver_for(EVENT_TYPE).resolve(db, ev)
        assert [r.user_id for r in recipients] == [booking.user_id]

        payload = get_template_for(
            EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL,
        ).render(db, ev, recipients[0])
        assert "Morning Sit" in payload.subject
        assert "Still Water" in payload.body_html
        assert "9:00am" in payload.body_html
        assert payload.body_html.lstrip().startswith("<!DOCTYPE html>")


# ---------------------------------------------------------------------------
# Member self-booking route — both branches
# ---------------------------------------------------------------------------


class TestMemberBookingRoute:
    def test_fresh_booking_emits_exactly_once(
        self, db, make_user, make_space, make_event,
    ):
        """The branch that creates a new EventBooking row."""
        space = make_space()
        event = make_event(space=space, booking_access_type="free")
        user = make_user()
        booking = _booking(db, event, user)

        emit_booking_confirmed(db, booking=booking)
        assert len(_events(db, event.id)) == 1

    def test_reactivated_cancelled_booking_emits_exactly_once(
        self, db, make_user, make_space, make_event,
    ):
        """The branch that flips an existing cancelled row back to
        confirmed — the one most easily missed when wiring."""
        space = make_space()
        event = make_event(space=space, booking_access_type="free")
        user = make_user()
        booking = _booking(db, event, user, status=BookingStatus.cancelled)

        # Reactivate, as the route does.
        booking.status = BookingStatus.confirmed
        booking.booked_at = datetime.utcnow()
        booking.cancelled_at = None
        db.flush()

        emit_booking_confirmed(db, booking=booking)
        assert len(_events(db, event.id)) == 1

    def test_both_route_branches_call_the_emit(self):
        """Guards the actual defect: the helper existed but was never
        called. Asserts both branches of ``book_event`` reach it."""
        import inspect
        from app.spaces import routes as space_routes

        src = inspect.getsource(space_routes.book_event)
        assert src.count("emit_booking_confirmed(") == 2, (
            "book_event must emit on BOTH the fresh and reactivated "
            "branches"
        )
        assert "trigger_booking_confirmed" not in src, (
            "the legacy member-confirmation trigger must not be called"
        )


# ---------------------------------------------------------------------------
# Paid-ticket fulfilment
# ---------------------------------------------------------------------------


class TestTicketFulfilment:
    def test_webhook_path_emits_once_and_replay_does_not_duplicate(
        self, db, make_user, make_event,
    ):
        user = make_user()
        event = make_event()
        booking = _booking(db, event, user)

        # First fulfilment.
        assert emit_booking_confirmed(db, booking=booking) is not None
        # Stripe re-delivers the same session: the handler short-circuits
        # on already_fulfilled, and the dedupe key is the second guard.
        assert emit_booking_confirmed(db, booking=booking) is None
        assert len(_events(db, event.id)) == 1

    def test_webhook_calls_the_emit_and_not_the_legacy_trigger(self):
        import inspect
        from app.webhooks import routes as webhook_routes

        src = inspect.getsource(webhook_routes._handle_gathering_ticket_completed)
        assert "emit_booking_confirmed(" in src
        assert "trigger_booking_confirmed" not in src
        # The creator-side notification is unaffected and must stay.
        assert "trigger_event_booking_creator" in src


# ---------------------------------------------------------------------------
# Nothing emitted where nothing should be
# ---------------------------------------------------------------------------


class TestNoSpuriousEmails:
    def test_double_booking_is_rejected_before_any_emit(
        self, db, make_user, make_event,
    ):
        """The route raises 400 'Already booked.' before reaching the
        emit, so a second attempt sends nothing."""
        import inspect
        from app.spaces import routes as space_routes

        src = inspect.getsource(space_routes.book_event)
        already = src.index("Already booked.")
        first_emit = src.index("emit_booking_confirmed(")
        assert already < first_emit, (
            "the already-booked rejection must precede the emit"
        )

    def test_legacy_and_comms_cannot_both_send_while_gatherings_is_live(self):
        """The legacy sender stands down for a live topic. With the comms
        path now wired, exactly one of the two can ever run."""
        from app.comms.rollout import is_event_live
        from app.services import notification_service

        assert is_event_live(EVENT_TYPE) is True

        legacy = MagicMock()
        with patch.object(notification_service, "SessionLocal", legacy):
            notification_service.trigger_booking_confirmed("ev_x", "u_x")
        # Returned at the rollout guard — never opened a session, so it
        # never built or sent an email.
        legacy.assert_not_called()


# ---------------------------------------------------------------------------
# Scope boundary — the follow-up's baseline
# ---------------------------------------------------------------------------


class TestUnwiredPathsStillSilent:
    """Series, creator-manual and creator-recurring booking have never
    sent a confirmation. This fix deliberately does not change that;
    these assertions document the baseline so the additive follow-up
    has something explicit to flip."""

    @pytest.mark.parametrize("fn_name,module", [
        ("book_series", "app.spaces.routes"),
        ("manual_book_member", "app.creator.routes"),
        ("book_recurring_sessions", "app.creator.routes"),
    ])
    def test_path_does_not_yet_emit(self, fn_name, module):
        import importlib
        import inspect
        mod = importlib.import_module(module)
        src = inspect.getsource(getattr(mod, fn_name))
        assert "emit_booking_confirmed" not in src
        assert "trigger_booking_confirmed" not in src
