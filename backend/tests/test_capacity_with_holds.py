"""Capacity math: confirmed bookings plus every unresolved hold.

These drive the real production helper, ``gathering_tickets.capacity_used``.
They used to embed their own copy of the capacity SQL, which meant they
certified a rule the application had stopped using — and kept passing
after the rule that oversold seats was removed. A test with its own copy of
the logic tests the copy.

The rule (invariant I2 in ``services/gathering_tickets``): a
``pending_payment`` booking occupies its seat until something positively
resolves it. No clock appears in the count. A buyer can pay at 10:59:59
against a hold nominally expiring at 11:00 and have the webhook arrive at
11:01; freeing the seat at 11:00 sells it twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.platform import BookingStatus, EventBooking
from app.services import gathering_tickets as gt


def _add_hold(db, event_id, user_id, minutes_ahead: int, txn_id=None):
    hold = EventBooking(
        id=f"bk_{user_id[-8:]}_{minutes_ahead}",
        event_id=event_id,
        user_id=user_id,
        status=BookingStatus.pending_payment,
        source="ticket_purchase",
        hold_expires_at=datetime.utcnow() + timedelta(minutes=minutes_ahead),
        payment_transaction_id=txn_id,
    )
    db.add(hold)
    db.flush()
    return hold


def _add_confirmed(db, event_id, user_id):
    row = EventBooking(
        id=f"bk_{user_id[-8:]}_confirmed",
        event_id=event_id,
        user_id=user_id,
        status=BookingStatus.confirmed,
        source="ticket_purchase",
    )
    db.add(row)
    db.flush()
    return row


class TestCapacityCounting:
    def test_empty_event_has_zero_used(self, db, make_event):
        event = make_event(capacity=10)
        assert gt.capacity_used(db, event.id) == 0

    def test_confirmed_booking_counts(self, db, make_event, make_user):
        event = make_event(capacity=10)
        _add_confirmed(db, event.id, make_user().id)
        assert gt.capacity_used(db, event.id) == 1

    def test_a_live_hold_counts(self, db, make_event, make_user, make_pending_txn):
        event = make_event(capacity=10)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=30, txn_id=txn.id)
        assert gt.capacity_used(db, event.id) == 1

    def test_a_past_due_hold_also_counts(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Rewritten: this asserted the opposite, and the opposite is the
        oversell. Past due means "ask Stripe", not "seat is free"."""
        event = make_event(capacity=10)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=-5, txn_id=txn.id)
        assert gt.capacity_used(db, event.id) == 1

    def test_cancelled_booking_does_not_count(self, db, make_event, make_user):
        """Cancelled is the resolved state, and the only thing that frees a
        seat. Reaching it requires positive knowledge."""
        event = make_event(capacity=10)
        row = _add_confirmed(db, event.id, make_user().id)
        row.status = BookingStatus.cancelled
        row.cancelled_at = datetime.utcnow()
        db.flush()
        assert gt.capacity_used(db, event.id) == 0

    def test_a_resolved_hold_stops_counting_everywhere(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """The seat comes back once Stripe has confirmed the checkout is
        dead — and it comes back in every surface at once, because they all
        read the same helper."""
        from app.services import ticket_summary as ts

        event = make_event(capacity=3)
        txn, payer = make_pending_txn(space=event.space, event=event)
        hold = _add_hold(db, event.id, payer.id, minutes_ahead=-5, txn_id=txn.id)
        db.commit()

        assert gt.capacity_used(db, event.id) == 1
        assert ts.ticket_summary_for(db, event).remaining_capacity == 2

        gt._cancel_hold(db, booking=hold, txn=txn,
                        reason=gt.CANCEL_VERIFIED_EXPIRED)

        assert gt.capacity_used(db, event.id) == 0
        assert ts.ticket_summary_for(db, event).remaining_capacity == 3

    def test_mixed_confirmed_live_and_past_due(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """3 confirmed + 2 live holds + 5 past-due holds → 10 used, not 5.
        Every one of those ten people may still turn up with a seat."""
        event = make_event(capacity=20)
        for _ in range(3):
            _add_confirmed(db, event.id, make_user().id)
        for minutes in (15, 15, -1, -1, -1, -1, -1):
            u = make_user()
            txn, _ = make_pending_txn(space=event.space, event=event, payer=u)
            _add_hold(db, event.id, u.id, minutes_ahead=minutes, txn_id=txn.id)

        assert gt.capacity_used(db, event.id) == 10

    def test_a_hold_blocks_the_last_seat(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event(capacity=1)
        u = make_user()
        txn, _ = make_pending_txn(space=event.space, event=event, payer=u)
        _add_hold(db, event.id, u.id, minutes_ahead=30, txn_id=txn.id)
        assert gt.capacity_used(db, event.id) >= event.capacity


class TestTheOldRuleCannotComeBack:
    """The regression that protects the rewrite.

    If ``capacity_used`` is reverted to ``hold_expires_at > now``, these
    fail. That is the whole reason this file no longer keeps its own copy
    of the SQL: a private copy would have gone on passing.
    """

    def test_the_helper_sql_has_no_clock_in_it(self):
        sql = str(gt.CAPACITY_USED_SQL)
        assert "hold_expires_at" not in sql, (
            "a time comparison here is the oversell — see invariant I2"
        )
        assert "NOW" not in sql.upper()
        assert "pending_payment" in sql and "confirmed" in sql

    def test_the_old_rule_would_change_the_answer(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Demonstrates the difference rather than asserting it abstractly:
        the same data, counted the old way, loses a seat that is still
        occupied."""
        from sqlalchemy import text

        event = make_event(capacity=5)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=-5, txn_id=txn.id)
        db.flush()

        old_rule = int(db.execute(text("""
            SELECT COUNT(*) FROM event_bookings
            WHERE event_id = :e
              AND (status = 'confirmed'
                   OR (status = 'pending_payment'
                       AND hold_expires_at > timezone('UTC', NOW())))
        """), {"e": event.id}).scalar_one())

        assert old_rule == 0, "the old rule frees the seat…"
        assert gt.capacity_used(db, event.id) == 1, "…and the current rule does not"

    def test_every_capacity_surface_agrees(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """The gap this file exists to close: four copies of one predicate
        had drifted apart. Member-facing availability, creator reporting
        and the allocation gate must give one answer."""
        from app.services import ticket_summary as ts

        event = make_event(capacity=4)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=-5, txn_id=txn.id)
        _add_confirmed(db, event.id, make_user().id)
        db.commit()

        authoritative = gt.capacity_used(db, event.id)
        summary = ts.ticket_summary_for(db, event)

        assert authoritative == 2
        assert summary.confirmed_booking_count + summary.active_hold_count == authoritative
        assert summary.remaining_capacity == event.capacity - authoritative
