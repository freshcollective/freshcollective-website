"""
Capacity math: unified count of confirmed + non-expired holds.

The service-layer helper lives in Stage 2B; these tests drive the SQL
directly so we can assert the fundamental invariant regardless of how
callers eventually wrap it. Anything the ticket flow does to check
capacity MUST match this shape.

    SELECT COUNT(*) FROM event_bookings
    WHERE event_id = :event_id
      AND (
        status = 'confirmed'
        OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
      )
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models.platform import BookingStatus, EventBooking


CAPACITY_SQL = text("""
    SELECT COUNT(*)
    FROM event_bookings
    WHERE event_id = :event_id
      AND (
        status = 'confirmed'
        OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
      )
""")


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
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 0

    def test_confirmed_booking_counts(self, db, make_event, make_user):
        event = make_event(capacity=10)
        _add_confirmed(db, event.id, make_user().id)
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 1

    def test_active_hold_counts(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event(capacity=10)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=30, txn_id=txn.id)
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 1

    def test_expired_hold_does_not_count(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event(capacity=10)
        txn, payer = make_pending_txn(space=event.space, event=event)
        _add_hold(db, event.id, payer.id, minutes_ahead=-5, txn_id=txn.id)
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 0

    def test_cancelled_booking_does_not_count(
        self, db, make_event, make_user,
    ):
        event = make_event(capacity=10)
        u = make_user()
        row = _add_confirmed(db, event.id, u.id)
        row.status = BookingStatus.cancelled
        row.cancelled_at = datetime.utcnow()
        db.flush()
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 0

    def test_mixed_confirmed_hold_and_expired(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """3 confirmed + 2 active holds + 5 expired holds → capacity used = 5."""
        event = make_event(capacity=10)
        # 3 confirmed
        for _ in range(3):
            _add_confirmed(db, event.id, make_user().id)
        # 2 active holds (still valid)
        for _ in range(2):
            u = make_user()
            txn, _ = make_pending_txn(space=event.space, event=event, payer=u)
            _add_hold(db, event.id, u.id, minutes_ahead=15, txn_id=txn.id)
        # 5 expired holds — must be ignored
        for _ in range(5):
            u = make_user()
            txn, _ = make_pending_txn(space=event.space, event=event, payer=u)
            _add_hold(db, event.id, u.id, minutes_ahead=-1, txn_id=txn.id)

        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n == 5

    def test_active_hold_blocks_last_seat(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """capacity=1, one active hold present → capacity is fully used
        even before the buyer completes payment."""
        event = make_event(capacity=1)
        u = make_user()
        txn, _ = make_pending_txn(space=event.space, event=event, payer=u)
        _add_hold(db, event.id, u.id, minutes_ahead=30, txn_id=txn.id)
        n = db.execute(CAPACITY_SQL, {"event_id": event.id}).scalar_one()
        assert n >= event.capacity
