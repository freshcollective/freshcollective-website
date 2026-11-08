"""Stage 3E — the confirmation email names what was bought.

The reported gap: Sophie's email identified "Test Gathering
Experience", said her access was active, and offered one button that
went to the dashboard. It never mentioned the Gathering on the Sunday
or the Pathway she could start immediately — and a Payment Option has
no page of its own, so "Open Test Gathering Experience" had nowhere
honest to go.

These tests are about *where the lines come from* as much as what they
say. Built from the fulfilment outcome rather than the Option, because
a creator may edit the Option afterwards and because a member may
already have owned one of the included Pathways.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.platform import (
    BookingStatus, Event, EventBooking, EventSeries, Pathway, PathwayType,
)
from app.services.purchase_included_summary import build_included_summary


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def space(make_space):
    return make_space()


def _pathway(db, space, *, title="New Pathway for Moonlit Circle"):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy", currency="AUD",
    )
    db.add(p); db.flush()
    return p


def _event(db, space, *, title="Test Gathering — Payment Options", days=14):
    e = Event(
        id=_uid("ev"), space_id=space.id, created_by_id=space.creator_id,
        title=title, starts_at=datetime.utcnow() + timedelta(days=days),
        ends_at=datetime.utcnow() + timedelta(days=days, hours=2),
        is_published=True, status="active", requires_booking=True,
        capacity=10, gathering_type="circle", attendance_format="online",
        is_public=True,
    )
    db.add(e); db.flush()
    return e


def _booking(db, event, user, *, status=BookingStatus.confirmed):
    b = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id, status=status,
        booked_at=datetime.utcnow(), source="payment_option",
    )
    db.add(b); db.flush()
    return b


def _result(**kw):
    """The shape ``apply_intent`` returns, as far as this reads it."""
    return SimpleNamespace(
        entitlements=kw.get("entitlements", []),
        access_passes=kw.get("access_passes", []),
        bookings=kw.get("bookings", []),
        offering_entitlements=kw.get("offering_entitlements", []),
        now=kw.get("now"),
    )


class TestItDescribesWhatWasActuallyGranted:
    def test_a_gathering_is_named_with_its_date(
        self, db, space, make_user,
    ):
        """A Gathering is identified by when it is as much as by its
        name — "Leadership Call" says nothing when a programme has
        three."""
        buyer = make_user()
        ev = _event(db, space)
        booking = _booking(db, ev, buyer)

        summary = build_included_summary(
            db, result=_result(bookings=[booking]), payer_user_id=buyer.id,
        )
        [item] = summary.items
        assert item.kind == "gathering"
        assert item.title == "Test Gathering — Payment Options"
        assert item.starts_at is not None
        assert item.status == "Your place is confirmed"
        assert f"/spaces/{space.slug}/events/{ev.id}" == item.url

    def test_a_pending_place_is_not_called_confirmed(
        self, db, space, make_user,
    ):
        """§8: do not claim a booking is confirmed while it is
        pending."""
        buyer = make_user()
        ev = _event(db, space)
        booking = _booking(
            db, ev, buyer, status=BookingStatus.pending_payment,
        )
        [item] = build_included_summary(
            db, result=_result(bookings=[booking]), payer_user_id=buyer.id,
        ).items
        assert item.status != "Your place is confirmed"
        assert "being confirmed" in item.status

    def test_a_pathway_is_named_and_linked(self, db, space, make_user):
        from app.models.platform import PathwayEntitlement, EntitlementStatus

        buyer = make_user()
        pw = _pathway(db, space)
        ent = PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="one_time_purchase",
            status=EntitlementStatus.active,
        )
        db.add(ent); db.flush()

        [item] = build_included_summary(
            db, result=_result(entitlements=[ent]), payer_user_id=buyer.id,
        ).items
        assert item.kind == "pathway"
        assert item.title == "New Pathway for Moonlit Circle"
        assert item.url == f"/spaces/{space.slug}/pathways/{pw.slug}"
        assert item.status == "Your access is now available"

    def test_a_mixed_bundle_lists_both(self, db, space, make_user):
        """Sophie's purchase, exactly."""
        from app.models.platform import PathwayEntitlement, EntitlementStatus

        buyer = make_user()
        ev = _event(db, space)
        booking = _booking(db, ev, buyer)
        pw = _pathway(db, space)
        ent = PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        )
        db.add(ent); db.flush()

        items = build_included_summary(
            db, result=_result(entitlements=[ent], bookings=[booking]),
            payer_user_id=buyer.id,
        ).items
        kinds = {i.kind for i in items}
        assert kinds == {"pathway", "gathering"}

    def test_a_series_pass_is_eligibility_not_a_booking(
        self, db, space, make_user,
    ):
        """§6: do not claim a confirmed booking for every session."""
        buyer = make_user()
        series = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="Term 4 2026",
            starts_at=datetime.utcnow() + timedelta(days=7),
            ends_at=datetime.utcnow() + timedelta(days=70),
            status="published",
        )
        db.add(series); db.flush()
        ap = SimpleNamespace(eligible_series_id=series.id)

        [item] = build_included_summary(
            db, result=_result(access_passes=[ap]), payer_user_id=buyer.id,
        ).items
        assert item.kind == "event_series"
        assert "book" in item.status.lower()
        assert "confirmed" not in item.status.lower()

    def test_nothing_granted_yields_no_lines(self, db, space, make_user):
        summary = build_included_summary(
            db, result=_result(), payer_user_id=make_user().id,
        )
        assert summary.items == []

    def test_a_missing_row_is_skipped_rather_than_raising(
        self, db, space, make_user,
    ):
        """A confirmation that fails to send because one title could
        not be looked up is worse than one listing a little less."""
        buyer = make_user()
        ghost = SimpleNamespace(pathway_id="does-not-exist")
        summary = build_included_summary(
            db, result=_result(entitlements=[ghost]),
            payer_user_id=buyer.id,
        )
        assert summary.items == []


class TestTheEmailCopy:
    def test_a_gathering_line_carries_its_date_and_link(self):
        from app.comms.templates.purchases import _included_lines

        [line] = _included_lines([{
            "title": "Test Gathering — Payment Options",
            "status": "Your place is confirmed",
            "starts_at": "2026-11-22T08:45:00",
            "url": "/spaces/moonlit/events/e1",
        }], "https://freshcollective.au")
        assert "Sunday 22 November 2026" in line
        assert "8:45 am" in line
        assert "Your place is confirmed" in line
        assert "https://freshcollective.au/spaces/moonlit/events/e1" in line

    def test_a_long_programme_is_summarised_not_truncated(self):
        """§6: keep the email readable, but the member must still be
        able to tell there is more."""
        from app.comms.templates.purchases import _included_lines

        items = [
            {"title": f"Pathway {i}", "status": "Ready", "url": f"/p/{i}"}
            for i in range(12)
        ]
        lines = _included_lines(items, "https://x")
        assert len(lines) == 9, "8 shown plus the remainder line"
        assert "4 more" in lines[-1]

    def test_an_instalment_states_the_whole_arrangement(self):
        """§7: a first payment must not read as the programme being
        paid for."""
        from app.comms.templates.purchases import _plan_arrangement_line

        line = _plan_arrangement_line({
            "installments_paid": 1, "installments_expected": 2,
            "installment_amount_cents": 4500,
            "total_expected_cents": 9000,
            "interval": "month", "currency": "AUD",
        })
        assert "2 monthly payments" in line
        # The email module's own money format — ISO code plus amount.
        # Deliberately not the web surfaces' "A$45": changing it here
        # would restyle every purchase email, and consistency within
        # the email is what matters to the person reading one.
        assert "AUD 45.00" in line
        assert "AUD 90.00 total" in line
        assert "1 payment remaining" in line

    def test_it_says_nothing_rather_than_guessing(self):
        from app.comms.templates.purchases import _plan_arrangement_line

        assert _plan_arrangement_line({"currency": "AUD"}) is None

    def test_an_unreadable_date_is_omitted_not_invented(self):
        from app.comms.templates.purchases import _fmt_gathering_when

        assert _fmt_gathering_when(None) == ""
        assert _fmt_gathering_when("not-a-date") == ""
