"""
Expired-hold retry — the UNIQUE(event_id, user_id) trap.

Scenario:
  1. User A opens Stripe Checkout for a paid Gathering → we insert a
     `pending_payment` booking row with hold_expires_at = NOW() + 30m.
  2. User A closes the tab. 45 minutes pass. hold_expires_at is in the
     past; capacity math (see test_capacity_with_holds.py) already
     ignores this row.
  3. User A comes back and clicks Buy again.

Without an explicit reuse path, the INSERT for the new hold would fail
with a UNIQUE(event_id, user_id) violation and the retry would be
silently broken. This test proves the correct reuse/update pattern:

  UPDATE event_bookings
  SET status = 'pending_payment',
      hold_expires_at = NOW() + INTERVAL '30 minutes',
      payment_transaction_id = :new_txn,
      cancelled_at = NULL
  WHERE event_id = :e AND user_id = :u
    AND status = 'pending_payment'
    AND hold_expires_at <= NOW()

The reuse-or-insert helper the checkout endpoint uses in Stage 2B
must obey the invariant asserted here: exactly one booking row per
(event, user) at any time, whichever transition path was used.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models.platform import BookingStatus, EventBooking


class TestExpiredHoldRetry:
    def test_same_user_reuses_expired_hold_row(
        self, db, make_event, make_user, make_pending_txn,
    ):
        event = make_event()
        buyer = make_user()

        # 1. First attempt: create a hold. Then time it out.
        txn_1, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        hold_1 = EventBooking(
            id="bk_first_" + "x" * 8,
            event_id=event.id,
            user_id=buyer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() - timedelta(minutes=5),  # already expired
            payment_transaction_id=txn_1.id,
        )
        db.add(hold_1)
        db.flush()

        # 2. Second attempt: reuse the same row via UPDATE keyed on the
        #    UNIQUE (event_id, user_id). This is the pattern the Stage 2B
        #    endpoint must implement.
        txn_2, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        result = db.execute(
            text("""
                UPDATE event_bookings
                SET status = :new_status,
                    hold_expires_at = :new_expiry,
                    payment_transaction_id = :new_txn,
                    cancelled_at = NULL,
                    updated_at = NOW()
                WHERE event_id = :event_id
                  AND user_id = :user_id
                  AND status = 'pending_payment'
                  AND (hold_expires_at IS NULL OR hold_expires_at <= timezone('UTC', NOW()))
                RETURNING id
            """),
            {
                "new_status": "pending_payment",
                "new_expiry": datetime.utcnow() + timedelta(minutes=30),
                "new_txn": txn_2.id,
                "event_id": event.id,
                "user_id": buyer.id,
            },
        ).all()
        assert len(result) == 1, "expected exactly one row to be reused"
        db.flush()

        # 3. Invariant: exactly one booking row for (event, user), and it
        #    points at the NEW transaction.
        rows = db.execute(
            text("SELECT id, status, payment_transaction_id, hold_expires_at "
                 "FROM event_bookings WHERE event_id=:e AND user_id=:u"),
            {"e": event.id, "u": buyer.id},
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "pending_payment"
        assert row.payment_transaction_id == txn_2.id
        assert row.hold_expires_at > datetime.utcnow()
        # And it's the same row id — no orphan
        assert row.id == hold_1.id

    def test_reuse_does_not_race_active_hold(
        self, db, make_event, make_user, make_pending_txn,
    ):
        """Reuse UPDATE is scoped to expired holds only. If a user has a
        still-active hold and tries to buy again, the UPDATE must MATCH
        ZERO ROWS — the caller then sees the active hold and can either
        redirect to its stored provider_checkout_url or refuse.

        This test proves the WHERE clause guards against clobbering a
        live hold with a new transaction id.
        """
        event = make_event()
        buyer = make_user()

        txn_active, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        active = EventBooking(
            id="bk_live_" + "x" * 8,
            event_id=event.id,
            user_id=buyer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=25),  # STILL VALID
            payment_transaction_id=txn_active.id,
        )
        db.add(active)
        db.flush()

        txn_new, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        result = db.execute(
            text("""
                UPDATE event_bookings
                SET status = :s, hold_expires_at = :h, payment_transaction_id = :t
                WHERE event_id = :e AND user_id = :u
                  AND status = 'pending_payment'
                  AND (hold_expires_at IS NULL OR hold_expires_at <= timezone('UTC', NOW()))
                RETURNING id
            """),
            {
                "s": "pending_payment",
                "h": datetime.utcnow() + timedelta(minutes=30),
                "t": txn_new.id,
                "e": event.id,
                "u": buyer.id,
            },
        ).all()
        assert len(result) == 0, "must NOT clobber an active hold"

        # Confirm the active row is untouched
        row = db.execute(
            text("SELECT payment_transaction_id FROM event_bookings "
                 "WHERE event_id=:e AND user_id=:u"),
            {"e": event.id, "u": buyer.id},
        ).scalar_one()
        assert row == txn_active.id

    def test_reuse_does_not_replace_confirmed_booking(
        self, db, make_event, make_user,
    ):
        """A user with a CONFIRMED booking must never have that row silently
        turned back into a hold. The reuse UPDATE is scoped to
        pending_payment only."""
        event = make_event()
        buyer = make_user()
        db.add(EventBooking(
            id="bk_done_" + "x" * 8,
            event_id=event.id,
            user_id=buyer.id,
            status=BookingStatus.confirmed,
            source="ticket_purchase",
        ))
        db.flush()

        result = db.execute(
            text("""
                UPDATE event_bookings
                SET status = 'pending_payment',
                    hold_expires_at = NOW() + INTERVAL '30 minutes'
                WHERE event_id = :e AND user_id = :u
                  AND status = 'pending_payment'
                  AND (hold_expires_at IS NULL OR hold_expires_at <= timezone('UTC', NOW()))
                RETURNING id
            """),
            {"e": event.id, "u": buyer.id},
        ).all()
        assert len(result) == 0

        row = db.execute(
            text("SELECT status FROM event_bookings WHERE event_id=:e AND user_id=:u"),
            {"e": event.id, "u": buyer.id},
        ).scalar_one()
        assert row == "confirmed"
