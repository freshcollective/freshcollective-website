"""
Shared pytest fixtures for the Fresh Collective backend test suite.

The scaffold is intentionally minimal and scoped to the standalone
Gathering ticket flow. It does not attempt to be a general test
harness for the whole app.

Key design choices:

- Real PostgreSQL (via `TEST_DATABASE_URL` or a derived URL). Row
  locking, CHECK constraints, ENUM ADD VALUE, timestamps and
  serialisable behaviour all matter for this feature and none can
  be faithfully faked by SQLite.
- Session-scoped engine + per-session schema (alembic migrations run
  once at collection time via `_ensure_schema()`).
- Per-test transaction wrapping via SAVEPOINT + rollback — leaves the
  test DB in a clean state without a full re-migrate.
- Explicit factory functions rather than a factory library, to keep
  the surface area tiny and readable.

Environment expected:

    TEST_DATABASE_URL   full PostgreSQL URL to the local fc_test database.
                        Never inline credentials in documentation, source,
                        or shell command examples — pass via the operator
                        environment only.

If unset, we derive the URL from the app's DATABASE_URL by swapping
the database name to `fc_test` — this only works when the app URL is
localhost and the operator has permission to create/alter fc_test.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Make backend importable regardless of pytest invocation cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Load .env so app.core.config resolves cleanly. Then override with test URL.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_ROOT / ".env")


def _resolve_test_url() -> str:
    """Prefer TEST_DATABASE_URL. Fall back to app URL with DB name → fc_test."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    app_url = os.environ.get("DATABASE_URL", "")
    if not app_url:
        raise RuntimeError(
            "Neither TEST_DATABASE_URL nor DATABASE_URL set. Cannot resolve "
            "a test database URL."
        )
    # Swap final path component to fc_test.
    for safe in ("localhost", "127.0.0.1", "::1"):
        if safe in app_url:
            base, _, _ = app_url.rpartition("/")
            return f"{base}/fc_test"
    raise RuntimeError(
        "DATABASE_URL does not point to localhost. Refusing to derive a test "
        "URL from it (would risk hitting a shared or production database). "
        "Set TEST_DATABASE_URL explicitly."
    )


TEST_URL = _resolve_test_url()
# Point the app config at the test DB *before* any app imports touch the engine.
os.environ["DATABASE_URL"] = TEST_URL


# ---------------------------------------------------------------------------
# Engine + schema management (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine() -> Engine:
    """One engine per test session. Migrations run once, on first use."""
    eng = create_engine(TEST_URL, future=True, pool_pre_ping=True)
    _ensure_schema(eng)
    return eng


def _ensure_schema(eng: Engine) -> None:
    """Run alembic upgrade head against the test DB.

    Two guard rails:
      1. Only ever touch a DB whose name ends in `_test`.
      2. Only ever touch a localhost DB.

    The alembic migration chain assumes the initial `users` table
    already exists (migration 001 is `add role column to users`).
    Empty databases must therefore be bootstrapped from prod's schema
    first — see `scripts/bootstrap_test_db.py`. This helper checks
    that the bootstrap has been done and raises a clear, actionable
    error otherwise. On subsequent runs, `alembic upgrade head` is a
    normal forward walk from whatever revision the bootstrap loaded.
    """
    with eng.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar_one()
        host = conn.execute(text("SELECT inet_server_addr()")).scalar()  # NULL for socket
        if not db_name.endswith("_test"):
            raise RuntimeError(
                f"Refusing to run migrations on '{db_name}' — test DB name must end in '_test'."
            )
        if host is not None and str(host) not in ("127.0.0.1", "::1"):
            raise RuntimeError(
                f"Refusing to run migrations on non-localhost host '{host}'."
            )

        alembic_present = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='alembic_version'"
        )).scalar()
        if not alembic_present:
            raise RuntimeError(
                f"'{db_name}' is empty (no alembic_version table). Bootstrap it "
                f"from prod's schema first:\n"
                f"    cd backend && .venv/bin/python3 scripts/bootstrap_test_db.py"
            )

    # Programmatic alembic upgrade so we don't require a subprocess.
    from alembic.config import Config
    from alembic import command

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # env.py reads DATABASE_URL from os.environ; already pointed at TEST_URL above.
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# Per-test transactional session
# ---------------------------------------------------------------------------

@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """
    Give each test a fresh SQLAlchemy Session wrapped in a savepoint that is
    rolled back at the end of the test. No committed writes escape the test.

    Nested transactions via SAVEPOINT let production code call `.commit()`
    freely without breaking isolation.
    """
    connection = engine.connect()
    outer = connection.begin()
    SessionLocal = sessionmaker(bind=connection, expire_on_commit=False, future=True)
    session = SessionLocal()

    # Start a SAVEPOINT that survives child `.commit()` calls.
    session.begin_nested()

    from sqlalchemy import event as sa_event

    @sa_event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


@pytest.fixture
def raw_connection(engine: Engine):
    """
    A raw connection with autocommit for tests that legitimately need
    to observe row locks / concurrency across sessions. Callers are
    responsible for their own cleanup.
    """
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Small factories — enough to build the objects the ticket tests need
# ---------------------------------------------------------------------------

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def make_user(db: Session):
    """Create a minimal User row. Password hash is a bcrypt placeholder."""
    from app.models.user import User  # local import so app modules load post-env-swap

    def _factory(**overrides) -> "User":
        # Top-level users.role CHECK allows only 'user' | 'creator' | 'admin'.
        # (SpaceMembership.role is different — 'learner' | 'moderator' | 'creator'.)
        # SEC-009: default to verified so pre-SEC-009 tests (which
        # weren't exercising verification) continue to hit the
        # trust-action gates cleanly. New SEC-009 tests explicitly
        # pass ``email_verified_at=None`` to test the unverified
        # branch.
        defaults = dict(
            id=_uid("u"),
            email=f"test-{uuid.uuid4().hex[:8]}@example.test",
            name="Test User",
            role="user",
            password_hash="$2b$12$0000000000000000000000000000000000000000000000000000",
            email_verified_at=datetime.utcnow(),
        )
        defaults.update(overrides)
        u = User(**defaults)
        db.add(u)
        db.flush()
        return u

    return _factory


@pytest.fixture
def make_space(db: Session, make_user):
    """Create a Space (Collective). Owned by a fresh creator user by default."""
    from app.models.platform import Space

    def _factory(**overrides) -> "Space":
        creator = overrides.pop("creator", None) or make_user(role="creator")
        defaults = dict(
            id=_uid("s"),
            slug=f"test-space-{uuid.uuid4().hex[:8]}",
            name="Test Space",
            status="active",
            creator_id=creator.id,
        )
        defaults.update(overrides)
        s = Space(**defaults)
        db.add(s)
        db.flush()
        return s

    return _factory


@pytest.fixture
def make_event(db: Session, make_space):
    """Create an Event. Defaults to a paid_separately, published, capacity-10 gathering."""
    from app.models.platform import Event

    def _factory(**overrides) -> "Event":
        space = overrides.pop("space", None) or make_space()
        defaults = dict(
            id=_uid("e"),
            space_id=space.id,
            created_by_id=space.creator_id,
            title="Test Gathering",
            starts_at=datetime.utcnow() + timedelta(days=7),
            ends_at=datetime.utcnow() + timedelta(days=7, hours=1),
            location_type="zoom",
            is_published=True,
            status="active",
            requires_booking=True,
            capacity=10,
            booking_access_type="paid_separately",
            gathering_type="workshop",
            attendance_format="online",
            ticket_price_cents=2500,
            ticket_currency="AUD",
        )
        defaults.update(overrides)
        e = Event(**defaults)
        db.add(e)
        db.flush()
        return e

    return _factory


@pytest.fixture
def make_pending_txn(db: Session, make_user):
    """Create a pending PaymentTransaction for a gathering ticket."""
    from app.models.payment import (
        PaymentTransaction,
        PaymentTransactionType,
        PaymentTransactionStatus,
        PaymentProvider,
        PayoutStatus,
    )

    def _factory(*, payer=None, space, event, gross_cents=2500, currency="AUD", **overrides):
        payer = payer or make_user()
        defaults = dict(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.gathering_ticket_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=payer.id,
            creator_user_id=space.creator_id,
            space_id=space.id,
            currency=currency,
            gross_amount_cents=gross_cents,
            platform_fee_basis_points=800,
            platform_fee_cents=int(gross_cents * 0.08),
            net_creator_amount_cents=gross_cents - int(gross_cents * 0.08),
            stripe_mode="test",
            payout_status=PayoutStatus.pending,
        )
        defaults.update(overrides)
        txn = PaymentTransaction(**defaults)
        db.add(txn)
        db.flush()
        return txn, payer

    return _factory
