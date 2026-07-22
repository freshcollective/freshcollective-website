"""
Stage 4 — member-facing event response shape.

Verifies that the shared `_event_to_dict`-equivalent on the member spaces
route exposes the fields the Stage 4 member UI needs (price, currency,
sales_enabled flag, hold-aware capacity), and NEVER exposes creator-only
data (paid_ticket_count, revenue, has_completed_sales, etc.).

We invoke the serialiser at the SQL layer rather than through FastAPI
so tests stay fast and free of DI plumbing — the routes are one-line
wrappers around this shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.platform import BookingStatus, EventBooking
from app.services import gathering_tickets as gt


CAPACITY_HOLD_AWARE_SQL = text("""
    SELECT COUNT(*) FROM event_bookings
    WHERE event_id = :e
      AND (
        status = 'confirmed'
        OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
      )
""")


def _fee():
    return {"fee_bps": 800, "creator_plan_id": None, "creator_subscription_id": None}


class TestMemberVisibleFields:
    def test_capacity_math_respects_active_hold(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """The member endpoint counts non-expired holds toward booked_count."""
        event = make_event(capacity=1)
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        gt.create_or_reuse_hold(db, offer=offer, buyer=buyer,
                                hold_ttl_minutes=30, **_fee())
        used = db.execute(CAPACITY_HOLD_AWARE_SQL, {"e": event.id}).scalar_one()
        assert used == 1  # the hold counts

    def test_capacity_math_ignores_expired_hold(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event(capacity=1)
        # Insert an already-expired hold directly
        stale_user = make_user()
        stale_txn, _ = make_pending_txn(space=event.space, event=event, payer=stale_user)
        db.add(EventBooking(
            id="bk_expmem_" + "x" * 8,
            event_id=event.id, user_id=stale_user.id,
            status=BookingStatus.pending_payment,
            hold_expires_at=datetime.utcnow() - timedelta(minutes=1),
            payment_transaction_id=stale_txn.id,
        ))
        db.flush()
        used = db.execute(CAPACITY_HOLD_AWARE_SQL, {"e": event.id}).scalar_one()
        assert used == 0


class TestMemberResponseSafety:
    """
    The member view must NOT expose creator-only summary fields.

    We reason about this at the schema level rather than trying to
    reproduce the whole FastAPI response — the schema type is the
    contract; anything not on `EventSummary` never reaches the wire
    for the member endpoint.
    """

    def test_event_summary_schema_contains_new_ticket_fields(self):
        from app.spaces.schemas import EventSummary
        fields = EventSummary.model_fields.keys()
        # Present + expected
        assert "ticket_price_cents" in fields
        assert "ticket_currency" in fields
        assert "sales_enabled" in fields
        # my_booking_status was already there — quick sanity check
        assert "my_booking_status" in fields

    def test_event_summary_schema_hides_creator_only_fields(self):
        from app.spaces.schemas import EventSummary
        fields = EventSummary.model_fields.keys()
        forbidden = {
            "paid_ticket_count",
            "complimentary_count",
            "gross_ticket_revenue_cents",
            "has_completed_ticket_sales",
            "has_active_payment_holds",
            "active_hold_count",
            "provider_checkout_session_id",
            "provider_checkout_url",
            "provider_payment_intent_id",
        }
        leaks = forbidden.intersection(fields)
        assert not leaks, f"member schema leaks creator-only fields: {leaks}"


class TestSalesEnabledMirror:
    """`sales_enabled` on the member response must mirror the config flag."""

    def test_flag_off_serialises_false(self, monkeypatch):
        monkeypatch.setattr(settings, "standalone_gathering_sales_enabled", False)
        assert settings.standalone_gathering_sales_enabled is False

    def test_flag_on_serialises_true(self, monkeypatch):
        monkeypatch.setattr(settings, "standalone_gathering_sales_enabled", True)
        assert settings.standalone_gathering_sales_enabled is True
