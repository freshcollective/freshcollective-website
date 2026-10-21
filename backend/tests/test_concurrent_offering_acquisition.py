"""Two people — or one person twice — acquiring the same Offering at once.

Real threads, real connections, real committed transactions. The
savepoint-wrapped ``db`` fixture cannot express this: everything in it
is one transaction, so the interleaving that matters never happens.

What is being proved
--------------------

**One active entitlement, whatever the timing.** Two simultaneous
requests from the same member must leave exactly one row. The
guarantee is ``ux_offering_entitlements_active``, a partial unique
index over ``(user_id, offering_id) WHERE status='active'`` — so the
database refuses the second row rather than the application being
trusted to notice.

**And the loser must not see a 500.** When the index refuses an insert,
``acquire_offering`` rolls back and runs the acquisition once more; the
retry's own already-owned read finds the committed winner and reports
``already_owned``. A member who double-clicks gets "already in Your
Collection", not an error. That retry only exists because of this test:
an in-transaction simulation of the race passes without it.

**One membership, not two.** The two requests also both try to join the
Collective. ``SpaceMembership`` has its own uniqueness, and the point
here is that a double acquisition does not produce a duplicate or
leave the member half-joined.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.services import offering_covers as covers
from app.spaces import _offering_member_routes as member_api


def _session(engine) -> Session:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _seed(engine) -> dict:
    """A published free Offering with one approved file, plus a taker.

    Committed, so the racing threads can see it on their own
    connections. Rows only — no stored object — because what is being
    raced is the entitlement write, not the bytes.
    """
    ids = {
        "owner": f"u_own_{uuid.uuid4().hex[:10]}",
        "taker": f"u_tak_{uuid.uuid4().hex[:10]}",
        "taker2": f"u_tk2_{uuid.uuid4().hex[:10]}",
        "space": f"s_acq_{uuid.uuid4().hex[:10]}",
        "slug": f"acq-{uuid.uuid4().hex[:8]}",
        "offering": f"off_{uuid.uuid4().hex[:10]}",
        "offering_slug": f"o-{uuid.uuid4().hex[:8]}",
        "file": f"of_{uuid.uuid4().hex[:10]}",
    }
    with engine.begin() as c:
        for key, role in (
            ("owner", "creator"), ("taker", "user"), ("taker2", "user"),
        ):
            c.execute(text("""
                INSERT INTO users (id, email, name, password_hash, role,
                                   email_verified_at, created_at, updated_at)
                VALUES (:id, :email, 'Acq Tester',
                        '$2b$12$0'||repeat('0',52), :role,
                        timezone('UTC', NOW()),
                        timezone('UTC', NOW()), timezone('UTC', NOW()))
            """), {
                "id": ids[key],
                "email": f"acq-{uuid.uuid4().hex[:8]}@example.test",
                "role": role,
            })
        c.execute(text("""
            INSERT INTO spaces (id, slug, name, status, creator_id,
                                created_at, updated_at)
            VALUES (:id, :slug, 'Acquisition Collective', 'active', :owner,
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["space"], "slug": ids["slug"], "owner": ids["owner"]})
        c.execute(text("""
            INSERT INTO offerings (id, space_id, created_by_user_id, slug,
                                   title, summary, cover_image_url, status,
                                   fulfilment_kind, pricing_kind,
                                   published_at, created_at, updated_at)
            VALUES (:id, :space, :owner, :slug, 'Raced Workbook',
                    'One file, two clicks.', :cover, 'published',
                    'digital_download', 'free',
                    timezone('UTC', NOW()),
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {
            "id": ids["offering"], "space": ids["space"],
            "owner": ids["owner"], "slug": ids["offering_slug"],
            "cover": covers.DEFAULT_COVERS[0].url,
        })
        c.execute(text("""
            INSERT INTO offering_files (id, offering_id, storage_key,
                                        original_filename, content_type,
                                        byte_size, sort_order, resource_count,
                                        validation_status, validated_at,
                                        checks_performed, created_at)
            VALUES (:id, :off, :key, 'workbook.pdf', 'application/pdf',
                    8192, 0, 1, 'passed', timezone('UTC', NOW()),
                    '[]'::jsonb, timezone('UTC', NOW()))
        """), {
            "id": ids["file"], "off": ids["offering"],
            "key": f"offering-files/{ids['offering']}/{uuid.uuid4().hex}_w.pdf",
        })
    return ids


def _cleanup(engine, ids: dict) -> None:
    """Best-effort teardown; always runs, even after an assertion fails."""
    with engine.begin() as c:
        c.execute(
            text("DELETE FROM offering_entitlements WHERE offering_id = :o"),
            {"o": ids["offering"]},
        )
        c.execute(text("DELETE FROM offering_files WHERE offering_id = :o"),
                  {"o": ids["offering"]})
        c.execute(text("DELETE FROM offerings WHERE id = :o"),
                  {"o": ids["offering"]})
        c.execute(text("DELETE FROM space_memberships WHERE space_id = :s"),
                  {"s": ids["space"]})
        c.execute(text("DELETE FROM spaces WHERE id = :s"), {"s": ids["space"]})
        for key in ("owner", "taker", "taker2"):
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": ids[key]})


def _try_acquire(engine, ids, user_key: str, barrier) -> str:
    session = _session(engine)
    try:
        user = session.get(User, ids[user_key])
        barrier.wait(timeout=20)
        out = member_api.acquire_offering(
            ids["slug"], ids["offering_slug"],
            db=session, current_user=user,
        )
        return "already_owned" if out["already_owned"] else "created"
    except HTTPException as exc:
        return f"http_{exc.status_code}"
    except Exception as exc:                       # pragma: no cover
        return f"error: {type(exc).__name__}: {exc}"
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _race(engine, ids, user_keys: tuple[str, ...]) -> dict[str, str]:
    barrier = threading.Barrier(len(user_keys))
    results: dict[str, str] = {}

    def run(label: str, key: str) -> None:
        results[label] = _try_acquire(engine, ids, key, barrier)

    threads = [
        threading.Thread(target=run, args=(f"t{i}", k), daemon=True)
        for i, k in enumerate(user_keys)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def _entitlement_rows(engine, offering_id: str, user_id: str) -> list[tuple]:
    with engine.begin() as c:
        return [
            tuple(r) for r in c.execute(
                text("SELECT id, status, source FROM offering_entitlements "
                     "WHERE offering_id = :o AND user_id = :u"),
                {"o": offering_id, "u": user_id},
            ).all()
        ]


def _membership_rows(engine, space_id: str, user_id: str) -> list[tuple]:
    with engine.begin() as c:
        return [
            tuple(r) for r in c.execute(
                text("SELECT id, status FROM space_memberships "
                     "WHERE space_id = :s AND user_id = :u"),
                {"s": space_id, "u": user_id},
            ).all()
        ]


@pytest.mark.concurrency
class TestOneMemberTwice:

    def test_two_simultaneous_clicks_leave_one_entitlement(
        self, engine, offerings_enabled,
    ):
        ids = _seed(engine)
        try:
            results = _race(engine, ids, ("taker", "taker"))

            # One created it; the other either lost the race and
            # recovered ("already_owned") or arrived after the commit
            # and read it ("already_owned"). Neither may be an error.
            assert sorted(results.values()) in (
                ["already_owned", "created"],
            ), results

            rows = _entitlement_rows(engine, ids["offering"], ids["taker"])
            assert len(rows) == 1, rows
            assert rows[0][1] == "active"
            assert rows[0][2] == "free"
        finally:
            _cleanup(engine, ids)

    def test_two_simultaneous_clicks_leave_one_membership(
        self, engine, offerings_enabled,
    ):
        ids = _seed(engine)
        try:
            _race(engine, ids, ("taker", "taker"))
            rows = _membership_rows(engine, ids["space"], ids["taker"])
            assert len(rows) == 1, rows
            assert rows[0][1] == "active"
        finally:
            _cleanup(engine, ids)

    def test_four_simultaneous_clicks_still_leave_one(
        self, engine, offerings_enabled,
    ):
        """More contention, same answer. Four is enough to make the
        loser path run more than once in the same instant."""
        ids = _seed(engine)
        try:
            results = _race(engine, ids, ("taker",) * 4)
            assert all(
                v in ("created", "already_owned") for v in results.values()
            ), results
            assert sum(1 for v in results.values() if v == "created") == 1, results
            rows = _entitlement_rows(engine, ids["offering"], ids["taker"])
            assert len(rows) == 1, rows
        finally:
            _cleanup(engine, ids)


@pytest.mark.concurrency
class TestTwoDifferentMembers:

    def test_both_get_their_own_entitlement(self, engine, offerings_enabled):
        """The index is per ``(user, offering)``, so two different people
        acquiring at the same instant must both succeed — a global
        unique constraint would have made this a refusal."""
        ids = _seed(engine)
        try:
            results = _race(engine, ids, ("taker", "taker2"))
            assert sorted(results.values()) == ["created", "created"], results
            assert len(_entitlement_rows(
                engine, ids["offering"], ids["taker"],
            )) == 1
            assert len(_entitlement_rows(
                engine, ids["offering"], ids["taker2"],
            )) == 1
        finally:
            _cleanup(engine, ids)
