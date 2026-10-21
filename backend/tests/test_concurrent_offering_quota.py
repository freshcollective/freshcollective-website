"""Concurrency: two callers race to create the fifth Community Offering.

Only one should succeed. The other must see 403 and back off.

The recipe under test, in ``_offering_routes.create_offering``:

    BEGIN;
    SELECT id FROM spaces WHERE id = :space_id FOR UPDATE;
    guard_offering_limit(...)        -- counts Offerings for this Space
    -- if count < allowance: INSERT the Offering
    COMMIT;

**The production handler is called directly**, not an emulation of it.
``test_concurrent_last_seat`` records why that matters: it used to
restate the capacity query, and so kept certifying the old clock-based
rule after the application had stopped using it. A locking test that
counts by a different rule than production tests the wrong recipe. Here
the thread calls ``api.create_offering``, so the lock, the count, the
allowance lookup and the insert are all the real ones.

Why real threads and real connections
-------------------------------------

The shared ``db`` fixture runs inside one SAVEPOINT, so it cannot
express two genuinely concurrent transactions contending for a row
lock — its commits are nested and invisible to other connections. Each
worker therefore gets its own ``Session`` bound to its own connection,
and the fixtures are seeded through a real committed transaction so the
workers can see them.

Deliberately hostile
--------------------

Community's allowance is five. The Collective is seeded with **four**
Offerings, so exactly one of the two racing creates may legally
succeed. Both threads are released by a barrier, neither coordinates
with the other, and both are the same owner — because Offerings are
owner-only, so a same-owner race is the realistic one (two browser tabs,
or a double-submit). There is no unique constraint that would save us
here: ``offerings`` is unique on ``(space_id, slug)``, and
``_unique_slug`` deliberately generates *different* slugs for the same
title. So if the row lock does not work, both inserts land, the
Collective ends with six, and this test fails.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.creator import _offering_routes as api
from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.schemas_offerings import OfferingCreateRequest
from app.models.user import User

#: The allowance under test, read from the plan rather than written
#: down, so a change to the product rule reaches this test.
COMMUNITY_ALLOWANCE = PLANS_BY_SLUG["community"].offerings_max_per_collective


@pytest.fixture(autouse=True)
def _offerings_available(offerings_enabled):
    """Offerings fully available for every test in this module.

    These call creator handlers **directly**, so they never meet the
    route's ``require_offerings_enabled`` dependency — but Offerings
    Phase C/D's pilot allow-list is enforced inside
    ``_get_owned_space``, which every creator handler resolves through.
    Without this, each test gets the production answer for a Collective
    outside the pilot: 404.

    ``offerings_enabled`` opens both switches. Scope itself is the
    subject of ``test_offering_pilot_allowlist.py``, not of these.
    """


def _seed(engine) -> dict:
    """Seed an owner on the Community plan, a Collective, and four
    Offerings — one short of the allowance.

    Committed through a real transaction so the worker threads, on
    independent connections, can actually see it. The SAVEPOINT-wrapped
    ``db`` fixture cannot be used for this.
    """
    ids = {
        "owner": f"u_own_{uuid.uuid4().hex[:10]}",
        "space": f"s_quota_{uuid.uuid4().hex[:10]}",
        "slug": f"quota-{uuid.uuid4().hex[:8]}",
        "plan": f"plan_comm_{uuid.uuid4().hex[:8]}",
        "sub": f"sub_{uuid.uuid4().hex[:10]}",
        "offerings": [],
    }
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO users (id, email, name, password_hash, role,
                               email_verified_at, created_at, updated_at)
            VALUES (:id, :email, 'Quota Owner', '$2b$12$0'||repeat('0',52),
                    'creator', timezone('UTC', NOW()),
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["owner"],
               "email": f"quota-{uuid.uuid4().hex[:8]}@example.test"})

        c.execute(text("""
            INSERT INTO spaces (id, slug, name, status, creator_id,
                                created_at, updated_at)
            VALUES (:id, :slug, 'Quota Space', 'active', :cid,
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["space"], "slug": ids["slug"],
               "cid": ids["owner"]})

        # The Community plan row, so ``resolve_creator_plan`` finds a
        # plan and the guard reads an allowance rather than falling
        # through to "uncapped".
        existing = c.execute(
            text("SELECT id FROM creator_plans WHERE slug = 'community'")
        ).first()
        if existing:
            ids["plan"] = existing[0]
            ids["plan_created"] = False
        else:
            cap = PLANS_BY_SLUG["community"]
            c.execute(text("""
                INSERT INTO creator_plans
                    (id, slug, name, monthly_price_cents, currency,
                     transaction_fee_basis_points, collective_limit,
                     pathway_limit, is_active, created_at, updated_at)
                VALUES (:id, 'community', :name, 0, 'AUD', 800, 1, 5, TRUE,
                        timezone('UTC', NOW()), timezone('UTC', NOW()))
            """), {"id": ids["plan"], "name": cap.display_name})
            ids["plan_created"] = True

        c.execute(text("""
            INSERT INTO creator_subscriptions
                (id, user_id, creator_plan_id, status, source, starts_at,
                 created_at, updated_at)
            VALUES (:id, :uid, :pid, 'active', 'manual_grant',
                    timezone('UTC', NOW()),
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["sub"], "uid": ids["owner"], "pid": ids["plan"]})

        # One short of the allowance.
        for i in range(COMMUNITY_ALLOWANCE - 1):
            oid = f"off_seed_{uuid.uuid4().hex[:10]}"
            c.execute(text("""
                INSERT INTO offerings
                    (id, space_id, created_by_user_id, slug, title, status,
                     fulfilment_kind, created_at, updated_at)
                VALUES (:id, :sid, :uid, :slug, :title, 'draft',
                        'digital_download',
                        timezone('UTC', NOW()), timezone('UTC', NOW()))
            """), {"id": oid, "sid": ids["space"], "uid": ids["owner"],
                   "slug": f"seeded-{i}-{uuid.uuid4().hex[:6]}",
                   "title": f"Seeded {i}"})
            ids["offerings"].append(oid)
    return ids


def _cleanup(engine, ids: dict) -> None:
    """Best-effort teardown; always runs, even after an assertion fails."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM offerings WHERE space_id = :s"),
                  {"s": ids["space"]})
        c.execute(text("DELETE FROM creator_subscriptions WHERE id = :i"),
                  {"i": ids["sub"]})
        c.execute(text("DELETE FROM spaces WHERE id = :s"), {"s": ids["space"]})
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": ids["owner"]})
        if ids.get("plan_created"):
            c.execute(text("DELETE FROM creator_plans WHERE id = :p"),
                      {"p": ids["plan"]})


def _try_create(
    engine, slug: str, owner_id: str, title: str, barrier: threading.Barrier,
) -> str:
    """Call the real creation handler on an independent connection.

    Returns ``'created'``, ``'refused'`` (the 403 the guard raises), or
    an error string. Each worker owns its Session, so the two are
    genuinely concurrent from PostgreSQL's point of view.
    """
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session: Session = SessionLocal()
    try:
        owner = session.get(User, owner_id)
        barrier.wait(timeout=15)
        api.create_offering(
            slug,
            OfferingCreateRequest(title=title),
            db=session,
            current_user=owner,
        )
        return "created"
    except HTTPException as exc:
        if exc.status_code == 403:
            return "refused"
        return f"http_{exc.status_code}"
    except Exception as exc:  # pragma: no cover - diagnostic
        return f"error: {type(exc).__name__}: {exc}"
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _count(engine, space_id: str) -> int:
    with engine.begin() as c:
        return c.execute(
            text("SELECT COUNT(*) FROM offerings WHERE space_id = :s"),
            {"s": space_id},
        ).scalar_one()


@pytest.mark.concurrency
class TestConcurrentOfferingQuota:
    def test_two_simultaneous_creates_cannot_exceed_the_allowance(self, engine):
        """The headline check.

        Four Offerings seeded, allowance five, two threads racing to
        create. Exactly one must succeed; the Collective must end at
        five, never six.
        """
        ids = _seed(engine)
        try:
            assert _count(engine, ids["space"]) == COMMUNITY_ALLOWANCE - 1

            barrier = threading.Barrier(2)
            results: dict[str, str] = {}

            def worker(name: str) -> None:
                results[name] = _try_create(
                    engine, ids["slug"], ids["owner"], f"Race {name}", barrier,
                )

            threads = [
                threading.Thread(target=worker, args=(n,), daemon=True)
                for n in ("a", "b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
                assert not t.is_alive(), "worker deadlocked"

            outcomes = sorted(results.values())
            final = _count(engine, ids["space"])

            assert outcomes == ["created", "refused"], (
                f"expected one of each, got {results}"
            )
            assert final == COMMUNITY_ALLOWANCE, (
                f"allowance is {COMMUNITY_ALLOWANCE}; Collective ended at "
                f"{final} — the row lock did not serialise the creates"
            )
        finally:
            _cleanup(engine, ids)

    def test_the_race_is_real_without_the_lock(self, engine):
        """The control that gives the test above its meaning.

        The same two-thread race, but each worker counts and inserts
        **without** taking the Collective row lock. This is what the
        production path would do if the lock were removed, and it is
        expected to overshoot — at which point the first test is shown
        to be detecting something rather than passing for free.

        Written as a tolerant assertion rather than a strict one: a race
        is not guaranteed to interleave on every run, so overshooting is
        allowed and *not* overshooting is not a failure. What would be a
        failure is the locked path overshooting, and that is the test
        above.
        """
        ids = _seed(engine)
        try:
            barrier = threading.Barrier(2)
            results: list[str] = []
            lock = threading.Lock()

            def unlocked_worker(name: str) -> None:
                SessionLocal = sessionmaker(
                    bind=engine, future=True, expire_on_commit=False,
                )
                session: Session = SessionLocal()
                try:
                    barrier.wait(timeout=15)
                    # No SELECT ... FOR UPDATE — the whole point.
                    current = session.execute(
                        text("SELECT COUNT(*) FROM offerings "
                             "WHERE space_id = :s"),
                        {"s": ids["space"]},
                    ).scalar_one()
                    if current >= COMMUNITY_ALLOWANCE:
                        with lock:
                            results.append("refused")
                        return
                    session.execute(
                        text("""
                            INSERT INTO offerings
                                (id, space_id, created_by_user_id, slug,
                                 title, status, fulfilment_kind,
                                 created_at, updated_at)
                            VALUES (:id, :sid, :uid, :slug, :title, 'draft',
                                    'digital_download',
                                    timezone('UTC', NOW()),
                                    timezone('UTC', NOW()))
                        """),
                        {"id": f"off_race_{uuid.uuid4().hex[:10]}",
                         "sid": ids["space"], "uid": ids["owner"],
                         "slug": f"race-{name}-{uuid.uuid4().hex[:6]}",
                         "title": f"Unlocked {name}"},
                    )
                    session.commit()
                    with lock:
                        results.append("created")
                finally:
                    session.close()

            threads = [
                threading.Thread(target=unlocked_worker, args=(n,), daemon=True)
                for n in ("a", "b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            final = _count(engine, ids["space"])
            # Informational: on an interleaved run this is ALLOWANCE + 1.
            assert final >= COMMUNITY_ALLOWANCE, final
            print(
                f"\n  unlocked control: outcomes={sorted(results)} "
                f"final={final} (allowance {COMMUNITY_ALLOWANCE}; "
                f"{'overshot — race demonstrated' if final > COMMUNITY_ALLOWANCE else 'did not interleave this run'})"
            )
        finally:
            _cleanup(engine, ids)

    def test_the_lock_precedes_the_count_in_the_production_path(self):
        """Ordering, pinned in source.

        A lock taken *after* counting would serialise nothing. The
        concurrency test above would still catch that, but only
        probabilistically; this catches it deterministically.
        """
        import inspect
        src = inspect.getsource(api.create_offering)
        assert "FOR UPDATE" in src
        assert src.index("FOR UPDATE") < src.index("guard_offering_limit")
