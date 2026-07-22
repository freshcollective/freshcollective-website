"""
Hold lifecycle: create, expire, confirm-via-fulfilment, cancel.

These tests exercise the raw DB model — the capacity-hold service
lives in Stage 2B and will be tested separately. The point here is:
the schema supports the four hold states cleanly and the
UNIQUE(event_id, user_id) constraint doubles as our double-hold
guard for free.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.platform import BookingStatus, EventBooking


class TestHoldLifecycle:
    def test_create_pending_hold(self, db, make_event, make_pending_txn):
        event = make_event()
        txn, payer = make_pending_txn(space=event.space, event=event)
        hold = EventBooking(
            id="bk_" + "x" * 12,
            event_id=event.id,
            user_id=payer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
            payment_transaction_id=txn.id,
        )
        db.add(hold)
        db.flush()
        assert hold.status == BookingStatus.pending_payment
        assert hold.hold_expires_at is not None
        assert hold.payment_transaction_id == txn.id

    def test_confirm_hold_clears_expiry(self, db, make_event, make_pending_txn):
        event = make_event()
        txn, payer = make_pending_txn(space=event.space, event=event)
        hold = EventBooking(
            id="bk_" + "x" * 12,
            event_id=event.id,
            user_id=payer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
            payment_transaction_id=txn.id,
        )
        db.add(hold)
        db.flush()

        # Simulate webhook fulfilment
        hold.status = BookingStatus.confirmed
        hold.hold_expires_at = None
        db.flush()

        assert hold.status == BookingStatus.confirmed
        assert hold.hold_expires_at is None
        # payment_transaction_id is preserved — it's the audit trail
        assert hold.payment_transaction_id == txn.id

    def test_cancel_hold_keeps_row(self, db, make_event, make_pending_txn):
        """A cancelled hold stays in the table as an audit trail — the row
        is not deleted, and its cancelled_at is populated."""
        event = make_event()
        txn, payer = make_pending_txn(space=event.space, event=event)
        hold = EventBooking(
            id="bk_" + "x" * 12,
            event_id=event.id,
            user_id=payer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
            payment_transaction_id=txn.id,
        )
        db.add(hold)
        db.flush()

        hold.status = BookingStatus.cancelled
        hold.cancelled_at = datetime.utcnow()
        db.flush()

        found = db.get(EventBooking, hold.id)
        assert found is not None
        assert found.status == BookingStatus.cancelled
        assert found.cancelled_at is not None


class TestHoldUniqueness:
    def test_cannot_create_two_holds_same_user_same_event(
        self, db, make_event, make_pending_txn, make_user,
    ):
        """UNIQUE(event_id, user_id) already prevents double-hold naturally."""
        event = make_event()
        txn, payer = make_pending_txn(space=event.space, event=event)
        db.add(EventBooking(
            id="bk_" + "a" * 12,
            event_id=event.id,
            user_id=payer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
            payment_transaction_id=txn.id,
        ))
        db.flush()

        db.add(EventBooking(
            id="bk_" + "b" * 12,
            event_id=event.id,
            user_id=payer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_cannot_confirm_a_second_booking_when_one_confirmed(
        self, db, make_event, make_user,
    ):
        event = make_event()
        u = make_user()
        db.add(EventBooking(
            id="bk_" + "c" * 12,
            event_id=event.id,
            user_id=u.id,
            status=BookingStatus.confirmed,
            source="ticket_purchase",
        ))
        db.flush()

        db.add(EventBooking(
            id="bk_" + "d" * 12,
            event_id=event.id,
            user_id=u.id,
            status=BookingStatus.confirmed,
            source="ticket_purchase",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
