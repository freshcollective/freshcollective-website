"""Hiding the remaining-places count, without hiding availability.

A creator can withhold the count on the public Gathering page. What
must survive that choice:

  * capacity is still enforced,
  * holds still occupy seats,
  * "Sold out" is still said out loud,
  * Creator Studio still reports the real numbers.

The trap this file exists to catch is the one that makes the feature
dangerous rather than merely wrong: ``spots_remaining`` and
``can_book`` were derived from the same variable, so nulling the
display number for privacy would have reported every full Gathering as
bookable. The numbers are therefore withheld at the response boundary,
after every decision has been made from the true count, and these
tests assert that ordering rather than trusting it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.platform import (
    BookingStatus,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import gathering_tickets as gt


def _hold(db, event_id, user_id, txn_id=None, minutes_ahead=20):
    row = EventBooking(
        id=f"bk_h_{user_id[-10:]}",
        event_id=event_id,
        user_id=user_id,
        status=BookingStatus.pending_payment,
        source="ticket_purchase",
        hold_expires_at=datetime.utcnow() + timedelta(minutes=minutes_ahead),
        payment_transaction_id=txn_id,
    )
    db.add(row)
    db.flush()
    return row


def _confirmed(db, event_id, user_id):
    row = EventBooking(
        id=f"bk_c_{user_id[-10:]}",
        event_id=event_id,
        user_id=user_id,
        status=BookingStatus.confirmed,
        source="ticket_purchase",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def viewer(make_user):
    return make_user()


@pytest.fixture
def client(db, viewer):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user, get_optional_user
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: viewer
    app.dependency_overrides[get_current_user] = lambda: viewer
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def join(db):
    def _join(space, user):
        db.add(SpaceMembership(
            id=f"sm_{user.id[-10:]}",
            user_id=user.id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
    return _join


def _row(client, event):
    rows = client.get(f"/api/spaces/{event.space.slug}/events").json()
    assert isinstance(rows, list), rows
    match = [r for r in rows if r["id"] == event.id]
    assert match, f"gathering missing from list: {rows}"
    return match[0]


def _detail(client, event):
    r = client.get(f"/api/spaces/{event.space.slug}/events/{event.id}")
    assert r.status_code == 200, r.text
    return r.json()


class TestTheDefaultIsUnchanged:
    """Existing Gatherings must behave exactly as they did."""

    def test_column_defaults_to_true(self, db, make_event):
        event = make_event()
        db.commit()
        assert event.show_remaining_publicly is True

    def test_an_omitted_field_does_not_hide_anything(
        self, client, db, make_event, make_user, join, viewer,
    ):
        """A Gathering created without mentioning the setting — which is
        every Gathering that already exists — still publishes its
        count."""
        event = make_event(capacity=5)
        join(event.space, viewer)
        _confirmed(db, event.id, make_user().id)
        db.commit()

        payload = _detail(client, event)
        assert payload["show_remaining_publicly"] is True
        assert payload["capacity"] == 5
        assert payload["spots_remaining"] == 4


class TestShowing:
    def test_count_is_published_when_on(
        self, client, db, make_event, make_user, join, viewer,
    ):
        event = make_event(capacity=5, show_remaining_publicly=True)
        join(event.space, viewer)
        _confirmed(db, event.id, make_user().id)
        db.commit()

        row = _row(client, event)
        detail = _detail(client, event)
        assert row["capacity"] == 5
        assert row["spots_remaining"] == 4
        assert row["show_remaining_publicly"] is True
        assert detail["spots_remaining"] == 4
        assert detail["capacity"] == 5


class TestHiding:
    @pytest.fixture
    def hidden(self, db, make_event, make_user, join, viewer, make_pending_txn):
        """Capacity 4, one confirmed and one hold → 2 genuinely left."""
        event = make_event(capacity=4, show_remaining_publicly=False)
        join(event.space, viewer)
        _confirmed(db, event.id, make_user().id)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _hold(db, event.id, payer.id, txn_id=txn.id)
        db.commit()
        return event

    def test_no_number_reaches_the_member(self, client, hidden):
        for payload in (_row(client, hidden), _detail(client, hidden)):
            assert payload["spots_remaining"] is None
            assert payload["capacity"] is None
            assert payload["booked_count"] == 0
            assert payload["show_remaining_publicly"] is False

    def test_the_addends_are_withheld_too(self, client, hidden):
        """capacity and booked_count reconstruct the remainder.

        Publishing "4 total, 2 taken" while withholding "2 left" would
        hide nothing at all.
        """
        detail = _detail(client, hidden)
        assert detail["capacity"] is None and detail["booked_count"] == 0

    def test_capacity_is_still_enforced_underneath(self, db, hidden):
        assert gt.capacity_used(db, hidden.id) == 2
        assert hidden.capacity == 4

    def test_booking_is_still_offered_while_seats_remain(
        self, client, db, make_event, make_user, join, viewer,
    ):
        """On a *free* Gathering, because `can_book` is deliberately
        False for `paid_separately` whatever the capacity — purchase is
        the path there, not the booking button. Asserting `can_book` on
        a paid Gathering would pass without testing anything.
        """
        event = make_event(
            capacity=4, show_remaining_publicly=False,
            booking_access_type="free", ticket_price_cents=None,
        )
        join(event.space, viewer)
        _confirmed(db, event.id, make_user().id)
        db.commit()

        detail = _detail(client, event)
        assert detail["spots_remaining"] is None, "still hidden"
        assert detail["can_book"] is True, "and still bookable"
        assert detail["is_sold_out"] is False


class TestSoldOutSurvivesHiding:
    """The dangerous case: hiding the number must not hide the refusal."""

    @pytest.fixture
    def full(self, db, make_event, make_user, join, viewer):
        event = make_event(capacity=2, show_remaining_publicly=False)
        join(event.space, viewer)
        for _ in range(2):
            _confirmed(db, event.id, make_user().id)
        db.commit()
        return event

    def test_sold_out_is_reported_without_numbers(self, client, full):
        for payload in (_row(client, full), _detail(client, full)):
            assert payload["is_sold_out"] is True
            assert payload["spots_remaining"] is None

    def test_a_full_hidden_free_gathering_is_not_bookable(
        self, client, db, make_event, make_user, join, viewer,
    ):
        """The regression that matters: if the display number were
        nulled *before* `can_book` was derived, a full Gathering would
        report itself bookable and the member would reach a booking
        that cannot succeed.

        Free again, for the reason given above — on a paid Gathering
        `can_book` is already False and this assertion would hold even
        if the ordering were wrong.
        """
        event = make_event(
            capacity=2, show_remaining_publicly=False,
            booking_access_type="free", ticket_price_cents=None,
        )
        join(event.space, viewer)
        for _ in range(2):
            _confirmed(db, event.id, make_user().id)
        db.commit()

        for payload in (_row(client, event), _detail(client, event)):
            assert payload["spots_remaining"] is None
            assert payload["is_sold_out"] is True
            assert payload["can_book"] is False

    def test_a_full_hidden_paid_gathering_refuses_at_the_gate(
        self, db, full,
    ):
        """And the paid equivalent, asserted where it actually bites:
        the allocation gate, not `can_book`."""
        from app.services import gathering_tickets as _gt

        assert _gt.capacity_used(db, full.id) == full.capacity

    def test_holds_alone_sell_it_out(
        self, db, make_event, join, viewer, make_pending_txn, client,
    ):
        """No confirmed bookings — every seat inside Stripe Checkout."""
        event = make_event(capacity=2, show_remaining_publicly=False)
        join(event.space, viewer)
        for _ in range(2):
            txn, payer = make_pending_txn(space=event.space, event=event)
            _hold(db, event.id, payer.id, txn_id=txn.id)
        db.commit()

        detail = _detail(client, event)
        assert detail["is_sold_out"] is True
        assert detail["can_book"] is False
        assert detail["spots_remaining"] is None


class TestCreatorStudioStillSeesEverything:
    """The creator's own numbers are never withheld."""

    def test_summary_reports_real_figures_when_hidden(
        self, db, make_event, make_user, make_pending_txn,
    ):
        from app.services import ticket_summary as ts

        event = make_event(capacity=4, show_remaining_publicly=False)
        _confirmed(db, event.id, make_user().id)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _hold(db, event.id, payer.id, txn_id=txn.id)
        db.commit()

        summary = ts.ticket_summary_for(db, event)
        assert summary.confirmed_booking_count == 1
        assert summary.active_hold_count == 1
        assert summary.remaining_capacity == 2

    def test_summary_is_identical_either_way(
        self, db, make_event, make_user,
    ):
        """The flag is presentation. It must not touch the numbers."""
        from app.services import ticket_summary as ts

        shown = make_event(capacity=3, show_remaining_publicly=True)
        hidden = make_event(capacity=3, show_remaining_publicly=False)
        for ev in (shown, hidden):
            _confirmed(db, ev.id, make_user().id)
        db.commit()

        a = ts.ticket_summary_for(db, shown)
        b = ts.ticket_summary_for(db, hidden)
        assert a.remaining_capacity == b.remaining_capacity == 2
        assert a.status == b.status


class TestUnlimitedIsNotConfusedWithHidden:
    """``spots_remaining=None`` already meant "unlimited"."""

    def test_unlimited_capacity_still_reads_as_showing(
        self, client, db, make_event, join, viewer,
    ):
        event = make_event(capacity=None, show_remaining_publicly=True)
        join(event.space, viewer)
        db.commit()

        payload = _detail(client, event)
        assert payload["spots_remaining"] is None
        assert payload["capacity"] is None
        # The flag is what distinguishes the two states, which is why
        # clients must not infer hiding from the nulls.
        assert payload["show_remaining_publicly"] is True
        assert payload["is_sold_out"] is False


class TestItPersistsThroughTheCreatorApi:
    """Saving and reopening the editor.

    The editor reads its initial toggle state from the Gathering it is
    editing, so a field that writes but does not read back shows the
    creator their setting silently reverting the next time they open
    the form.
    """

    @pytest.fixture
    def creator(self, make_user):
        return make_user(role="creator")

    @pytest.fixture
    def space(self, make_space, creator):
        return make_space(creator=creator)

    @pytest.fixture
    def creator_client(self, db, creator):
        from fastapi.testclient import TestClient

        from app.auth.dependencies import (
            get_current_user,
            get_verified_creator_user,
        )
        from app.db.session import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: creator
        app.dependency_overrides[get_verified_creator_user] = lambda: creator
        yield TestClient(app)
        app.dependency_overrides.clear()

    def _patch(self, client, space, event, body):
        r = client.patch(
            f"/api/creator/spaces/{space.slug}/events/{event.id}", json=body,
        )
        assert r.status_code == 200, r.text
        return r.json()

    def _get(self, client, space, event):
        r = client.get(f"/api/creator/spaces/{space.slug}/events/{event.id}")
        assert r.status_code == 200, r.text
        return r.json()

    def test_hiding_it_round_trips(
        self, creator_client, db, space, make_event,
    ):
        event = make_event(space=space, capacity=6)
        db.commit()

        body = self._patch(
            creator_client, space, event, {"show_remaining_publicly": False},
        )
        assert body["show_remaining_publicly"] is False
        # Re-read, because the response could be echoing the request.
        assert self._get(creator_client, space, event)[
            "show_remaining_publicly"
        ] is False

    def test_showing_it_again_round_trips(
        self, creator_client, db, space, make_event,
    ):
        event = make_event(space=space, capacity=6, show_remaining_publicly=False)
        db.commit()

        self._patch(creator_client, space, event, {"show_remaining_publicly": True})
        assert self._get(creator_client, space, event)[
            "show_remaining_publicly"
        ] is True

    def test_an_unrelated_patch_does_not_re_reveal_it(
        self, creator_client, db, space, make_event,
    ):
        """A PATCH that never mentions the field must leave it alone.

        The update loop applies any value that is not None, so a schema
        default of True here — rather than None — would have turned
        every unrelated edit into an unhide.
        """
        event = make_event(space=space, capacity=6, show_remaining_publicly=False)
        db.commit()

        self._patch(creator_client, space, event, {"title": "Renamed"})
        after = self._get(creator_client, space, event)
        assert after["title"] == "Renamed"
        assert after["show_remaining_publicly"] is False
