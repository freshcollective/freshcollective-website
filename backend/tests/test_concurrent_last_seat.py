"""
Concurrency: two callers race to hold the LAST seat on a paid Gathering.

Only one should succeed. The other must see 'sold out' and back off.

The safety recipe under test:

    BEGIN;
    SELECT id FROM events WHERE id = :event_id FOR UPDATE;
    SELECT COUNT(*) FROM event_bookings
      WHERE event_id = :event_id
        AND (
          status = 'confirmed'
          OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
        );
    -- if count < capacity: INSERT hold row
    COMMIT;

The SELECT ... FOR UPDATE on the Event row is the serialisation point;
without it, both workers see count < capacity, both insert, and only
the UNIQUE(event_id, user_id) constraint saves us — and that only helps
if the two workers are the SAME user, which is not the case here.

This test is intentionally hostile: two DIFFERENT users on a capacity=1
event, real threads, real connections, no coordination. If the row lock
doesn't work, both holds land and the test fails.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.platform import BookingStatus, Event, EventBooking


CAPACITY_SQL = """
    SELECT COUNT(*)
    FROM event_bookings
    WHERE event_id = :event_id
      AND (
        status = 'confirmed'
        OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
      )
"""


def _try_hold_last_seat(
    engine, event_id: str, user_id: str, ready: threading.Event, barrier: threading.Barrier
) -> str:
    """Emulate the checkout-endpoint hold acquisition path.

    Returns 'held' on success, 'sold_out' if capacity was already taken,
    'unique_violation' if the UNIQUE constraint intercepted, or an error
    string.

    Uses its own SQLAlchemy Session bound to a fresh connection so the
    two callers are genuinely concurrent from Postgres' point of view.
    """
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session: Session = SessionLocal()
    try:
        # Wait until both threads are ready to start together
        ready.set()
        barrier.wait(timeout=10)

        session.begin()
        # Lock the Event row — this is the whole game
        session.execute(text("SELECT id FROM events WHERE id = :id FOR UPDATE"), {"id": event_id})
        # Recheck capacity under lock
        event = session.get(Event, event_id)
        used = session.execute(text(CAPACITY_SQL), {"event_id": event_id}).scalar_one()
        if event.capacity is not None and used >= event.capacity:
            session.rollback()
            return "sold_out"

        # Insert the hold
        session.add(EventBooking(
            id="bk_race_" + uuid.uuid4().hex[:10],
            event_id=event_id,
            user_id=user_id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
        ))
        session.commit()
        return "held"
    except Exception as exc:  # noqa: BLE001 — inspect message classifier
        session.rollback()
        # Two shapes of DB-integrity error we intentionally distinguish
        msg = str(exc).lower()
        if "unique" in msg or "uq_event_bookings_event_user" in msg:
            return "unique_violation"
        return f"error: {exc}"
    finally:
        session.close()


def _seed_concurrency_fixtures(engine, capacity: int) -> dict:
    """
    Seed fixtures via a real committed connection so worker threads on
    independent connections can actually SEE them. Returns a dict of ids
    for later cleanup.

    Cannot use the SAVEPOINT-wrapped `db` fixture here — that session's
    commits are nested and never reach other connections until the
    outer test transaction rolls back at teardown.
    """
    ids = {
        "creator": f"u_creator_{uuid.uuid4().hex[:10]}",
        "space":   f"s_race_{uuid.uuid4().hex[:10]}",
        "event":   f"e_race_{uuid.uuid4().hex[:10]}",
        "buyers":  [],
    }
    with engine.begin() as c:
        # Creator user (needed for space FK)
        c.execute(text("""
            INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
            VALUES (:id, :email, 'Race Creator', '$2b$12$0'||repeat('0',52),
                    'creator', timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["creator"], "email": f"race-c-{uuid.uuid4().hex[:8]}@example.test"})
        # Space
        c.execute(text("""
            INSERT INTO spaces (id, slug, name, status, creator_id,
                                created_at, updated_at)
            VALUES (:id, :slug, 'Race Space', 'active', :cid,
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["space"], "slug": f"race-{uuid.uuid4().hex[:8]}",
               "cid": ids["creator"]})
        # Event — paid_separately, published, given capacity
        c.execute(text("""
            INSERT INTO events (id, space_id, created_by_id, title,
                                starts_at, ends_at, location_type,
                                is_published, status, requires_booking,
                                capacity, booking_access_type,
                                gathering_type, attendance_format,
                                ticket_price_cents, ticket_currency,
                                is_public, created_at, updated_at)
            VALUES (:id, :sid, :cid, 'Race Event',
                    timezone('UTC', NOW()) + INTERVAL '7 days',
                    timezone('UTC', NOW()) + INTERVAL '7 days 1 hour',
                    'zoom', TRUE, 'active', TRUE,
                    :cap, 'paid_separately',
                    'workshop', 'online',
                    2500, 'AUD',
                    FALSE, timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["event"], "sid": ids["space"],
               "cid": ids["creator"], "cap": capacity})
    return ids


def _seed_buyer(engine, ids: dict) -> str:
    """Seed one buyer user (committed) and append to ids['buyers']."""
    buyer_id = f"u_buy_{uuid.uuid4().hex[:10]}"
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
            VALUES (:id, :email, 'Race Buyer', '$2b$12$0'||repeat('0',52),
                    'user', timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": buyer_id, "email": f"race-b-{uuid.uuid4().hex[:8]}@example.test"})
    ids["buyers"].append(buyer_id)
    return buyer_id


def _cleanup_concurrency_fixtures(engine, ids: dict) -> None:
    """Best-effort teardown, always runs even after assertion failure."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM event_bookings WHERE event_id = :e"), {"e": ids["event"]})
        c.execute(text("DELETE FROM events WHERE id = :e"), {"e": ids["event"]})
        c.execute(text("DELETE FROM spaces WHERE id = :s"), {"s": ids["space"]})
        user_ids = [ids["creator"], *ids["buyers"]]
        c.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})


@pytest.mark.concurrency
class TestConcurrentLastSeat:
    def test_two_workers_last_seat_only_one_wins(self, engine):
        """Two distinct buyers race for the last seat on a capacity=1
        event. The SELECT ... FOR UPDATE on the Event row must serialise
        them: exactly one hold, exactly one sold_out."""
        ids = _seed_concurrency_fixtures(engine, capacity=1)
        buyer_a = _seed_buyer(engine, ids)
        buyer_b = _seed_buyer(engine, ids)

        try:
            ready_a, ready_b = threading.Event(), threading.Event()
            barrier = threading.Barrier(2)
            results: dict[str, str] = {}

            def worker(tag: str, user_id: str, ready: threading.Event):
                results[tag] = _try_hold_last_seat(engine, ids["event"], user_id, ready, barrier)

            t_a = threading.Thread(target=worker, args=("A", buyer_a, ready_a))
            t_b = threading.Thread(target=worker, args=("B", buyer_b, ready_b))
            t_a.start(); t_b.start()
            ready_a.wait(timeout=5); ready_b.wait(timeout=5)
            t_a.join(timeout=15); t_b.join(timeout=15)

            winners = [k for k, v in results.items() if v == "held"]
            losers = [k for k, v in results.items() if v == "sold_out"]
            assert len(winners) == 1, f"expected one winner, got results={results}"
            assert len(losers) == 1, f"expected one sold_out, got results={results}"
        finally:
            _cleanup_concurrency_fixtures(engine, ids)

    def test_same_user_two_attempts_second_hits_unique_constraint(self, engine):
        """Same user double-clicks on Buy. Capacity is not the bottleneck;
        the UNIQUE(event_id, user_id) constraint is. Exactly one hold row
        must exist afterwards."""
        ids = _seed_concurrency_fixtures(engine, capacity=10)
        buyer = _seed_buyer(engine, ids)

        try:
            ready_a, ready_b = threading.Event(), threading.Event()
            barrier = threading.Barrier(2)
            results: dict[str, str] = {}

            def worker(tag: str, ready: threading.Event):
                results[tag] = _try_hold_last_seat(engine, ids["event"], buyer, ready, barrier)

            t_a = threading.Thread(target=worker, args=("A", ready_a))
            t_b = threading.Thread(target=worker, args=("B", ready_b))
            t_a.start(); t_b.start()
            ready_a.wait(timeout=5); ready_b.wait(timeout=5)
            t_a.join(timeout=15); t_b.join(timeout=15)

            held = [k for k, v in results.items() if v == "held"]
            assert len(held) == 1, (
                f"expected exactly one hold from same-user race; got results={results}"
            )
            other = next(v for k, v in results.items() if k != held[0])
            assert other in ("unique_violation", "sold_out"), other
        finally:
            _cleanup_concurrency_fixtures(engine, ids)
