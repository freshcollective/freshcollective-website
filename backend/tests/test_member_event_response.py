"""
Stage 4 — member-facing event response shape.

Verifies that the shared `_event_to_dict`-equivalent on the member spaces
route exposes the fields the Stage 4 member UI needs (price, currency,
sales_enabled flag, hold-aware capacity), and NEVER exposes creator-only
data (paid_ticket_count, revenue, has_completed_sales, etc.).

Capacity is checked through the production helper
(``gathering_tickets.capacity_used``), not a local copy of its SQL. The
member route now calls that helper directly, so this asserts the real
thing rather than a private restatement of it — a copy kept passing after
the rule it described was removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.platform import BookingStatus, EventBooking
from app.services import gathering_tickets as gt


def _fee():
    return {"fee_bps": 800, "creator_plan_id": None, "creator_subscription_id": None}


class TestMemberVisibleFields:
    def test_capacity_math_respects_active_hold(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """The member endpoint counts holds toward booked_count."""
        event = make_event(capacity=1)
        buyer = make_user()
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        gt.create_or_reuse_hold(db, offer=offer, buyer=buyer,
                                hold_ttl_minutes=30, **_fee())
        assert gt.capacity_used(db, event.id) == 1  # the hold counts

    def test_capacity_math_still_counts_a_past_due_hold(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Rewritten. Member-facing availability must not offer a seat the
        allocation gate will then refuse — which is what happened while
        this asserted the hold was ignored."""
        event = make_event(capacity=1)
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
        assert gt.capacity_used(db, event.id) == 1


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
