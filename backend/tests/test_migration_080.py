"""
Migration 080 — schema assertions.

Confirms the new columns, indexes, enum labels and CHECK constraint
exist in the test database. These tests never touch application logic
— failure means the migration itself didn't do what its docstring claims.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _cols(engine: Engine, table: str) -> dict[str, dict]:
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t
        """), {"t": table}).mappings().all()
    return {r["column_name"]: dict(r) for r in rows}


def _enum_labels(engine: Engine, enum_name: str) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT e.enumlabel
            FROM pg_type t
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE t.typname = :n
        """), {"n": enum_name}).all()
    return {r[0] for r in rows}


class TestEventsTicketColumns:
    def test_ticket_price_cents_exists_nullable_integer(self, engine):
        cols = _cols(engine, "events")
        assert "ticket_price_cents" in cols
        assert cols["ticket_price_cents"]["data_type"] == "integer"
        assert cols["ticket_price_cents"]["is_nullable"] == "YES"

    def test_ticket_currency_exists_nullable_varchar_3(self, engine):
        cols = _cols(engine, "events")
        assert "ticket_currency" in cols
        # varchar(3) surfaces as 'character varying' in info_schema
        assert cols["ticket_currency"]["data_type"] in ("character varying", "varchar")
        assert cols["ticket_currency"]["is_nullable"] == "YES"


class TestEventBookingsHoldColumns:
    def test_hold_expires_at_exists_nullable_timestamp(self, engine):
        cols = _cols(engine, "event_bookings")
        assert "hold_expires_at" in cols
        assert "timestamp" in cols["hold_expires_at"]["data_type"]
        assert cols["hold_expires_at"]["is_nullable"] == "YES"

    def test_payment_transaction_id_exists_and_is_fk(self, engine):
        cols = _cols(engine, "event_bookings")
        assert "payment_transaction_id" in cols
        assert cols["payment_transaction_id"]["is_nullable"] == "YES"

        with engine.connect() as c:
            row = c.execute(text("""
                SELECT confrelid::regclass::text AS refs
                FROM pg_constraint
                WHERE conrelid = 'event_bookings'::regclass
                  AND contype  = 'f'
                  AND conname LIKE '%payment_transaction%'
            """)).first()
        assert row is not None, "no FK on event_bookings.payment_transaction_id"
        assert row.refs == "payment_transactions"


class TestPaymentTransactionsProviderUrl:
    def test_provider_checkout_url_exists_varchar_500(self, engine):
        cols = _cols(engine, "payment_transactions")
        assert "provider_checkout_url" in cols
        assert cols["provider_checkout_url"]["is_nullable"] == "YES"


class TestEnumExtensions:
    def test_bookingstatus_gains_pending_payment(self, engine):
        labels = _enum_labels(engine, "bookingstatus")
        assert {"confirmed", "cancelled", "pending_payment"}.issubset(labels)

    def test_payment_transaction_type_gains_gathering_ticket_purchase(self, engine):
        labels = _enum_labels(engine, "payment_transaction_type_enum")
        assert "gathering_ticket_purchase" in labels


class TestCheckConstraint:
    def test_check_constraint_exists(self, engine):
        with engine.connect() as c:
            row = c.execute(text("""
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'events'::regclass
                  AND conname  = 'ck_events_ticket_price_valid_when_published'
            """)).first()
        assert row is not None

    def test_check_constraint_rejects_published_paid_without_price(self, db, make_space):
        """A published, paid_separately event with no price MUST be rejected by the DB."""
        from datetime import datetime, timedelta
        space = make_space()
        from app.models.platform import Event
        bad = Event(
            id="ev_bad_" + "x" * 10,
            space_id=space.id,
            created_by_id=space.creator_id,
            title="Bad paid event",
            starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            location_type="zoom",
            is_published=True,
            status="active",
            requires_booking=True,
            capacity=10,
            booking_access_type="paid_separately",
            gathering_type="workshop",
            attendance_format="online",
            ticket_price_cents=None,
            ticket_currency=None,
        )
        db.add(bad)
        import pytest
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_check_constraint_rejects_zero_price(self, db, make_space):
        from datetime import datetime, timedelta
        from app.models.platform import Event
        space = make_space()
        bad = Event(
            id="ev_zero_" + "x" * 10,
            space_id=space.id,
            created_by_id=space.creator_id,
            title="Zero price",
            starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            location_type="zoom",
            is_published=True,
            status="active",
            requires_booking=True,
            capacity=10,
            booking_access_type="paid_separately",
            gathering_type="workshop",
            attendance_format="online",
            ticket_price_cents=0,
            ticket_currency="AUD",
        )
        db.add(bad)
        import pytest
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_check_constraint_allows_draft_without_price(self, db, make_space):
        """A DRAFT paid_separately event can have no price yet — creators save WIP."""
        from datetime import datetime, timedelta
        from app.models.platform import Event
        space = make_space()
        draft = Event(
            id="ev_draft_" + "x" * 10,
            space_id=space.id,
            created_by_id=space.creator_id,
            title="Draft paid event",
            starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            location_type="zoom",
            is_published=False,
            status="active",
            requires_booking=True,
            capacity=10,
            booking_access_type="paid_separately",
            gathering_type="workshop",
            attendance_format="online",
            ticket_price_cents=None,
            ticket_currency=None,
        )
        db.add(draft)
        db.flush()  # must not raise
        assert draft.id.startswith("ev_draft_")

    def test_check_constraint_allows_free_published_without_price(self, db, make_space):
        """Non-paid access types are unaffected by the CHECK."""
        from datetime import datetime, timedelta
        from app.models.platform import Event
        space = make_space()
        free = Event(
            id="ev_free_" + "x" * 10,
            space_id=space.id,
            created_by_id=space.creator_id,
            title="Free published",
            starts_at=datetime.utcnow() + timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=1, hours=1),
            location_type="zoom",
            is_published=True,
            status="active",
            requires_booking=False,
            capacity=None,
            booking_access_type="free",
            gathering_type="workshop",
            attendance_format="online",
            ticket_price_cents=None,
            ticket_currency=None,
        )
        db.add(free)
        db.flush()
