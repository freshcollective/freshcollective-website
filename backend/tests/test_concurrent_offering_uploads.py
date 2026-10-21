"""Concurrency: uploads racing for the last slot, and workers racing for work.

Three races, each against the **production handler** on genuinely
independent PostgreSQL connections:

  1. Two uploads contending for a Community creator's single file slot.
  2. Two uploads contending for the last few megabytes of a Creator
     bundle's 75 MB allowance.
  3. Two validation workers contending for one pending file.
  4. Two replacements contending for one approved file.

Why real threads and real connections
-------------------------------------

The shared ``db`` fixture runs inside one SAVEPOINT, so it cannot express
two concurrent transactions contending for a row lock — its commits are
nested and invisible to other connections. Each worker therefore gets its
own ``Session`` bound to its own connection, and the fixtures are seeded
through a real committed transaction so the workers can see them. This is
the discipline ``test_concurrent_offering_quota`` and
``test_concurrent_last_seat`` established.

Each race calls the real handler, never a restatement of it.
``test_concurrent_last_seat`` records why that matters: it once restated
the capacity query and so kept certifying a rule the application had
stopped using. Here the threads call ``files_api.upload_offering_file``
and ``worker.claim_next``, so the lock, the measurement, the allowance
lookup and the insert are all the real ones.

Deliberately hostile
--------------------

No test relies on a unique constraint to save it. Storage keys contain a
fresh uuid per upload, so two racing uploads never collide on
``offering_files_storage_key_unique`` — if the row lock does not work,
both inserts land and the assertions fail.
"""

from __future__ import annotations

import io
import threading
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers

from app.core import storage
from app.creator import _offering_file_routes as files_api
from app.creator.plan_config import PLANS_BY_SLUG
from app.models.offering import OfferingFileValidationStatus as FVS
from app.models.user import User
from app.services import offering_files as of
from app.services import offering_validation_worker as worker

MB = 1024 * 1024


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


def _pdf(size: int = 2048) -> bytes:
    body = b"%PDF-1.4\n" + b"x" * max(0, size - 24) + b"\ntrailer\n%%EOF\n"
    return body[:size] if size >= 24 else body


def _upload_file(data: bytes, name: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data), filename=name,
        headers=Headers({"content-type": "application/pdf"}),
    )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _seed(engine, *, plan_slug: str, seed_files=()) -> dict:
    """An owner on ``plan_slug``, a Collective, an Offering, and files.

    ``seed_files`` is a list of ``(byte_size, resource_count, status)``.
    These are **rows only** — no stored object — because what they exist
    to do is occupy allowance, and writing hundreds of megabytes of real
    bytes to test an arithmetic race would be a slower test that proves
    the same thing. The racing uploads themselves write real bytes.
    """
    ids = {
        "owner": f"u_own_{uuid.uuid4().hex[:10]}",
        "space": f"s_up_{uuid.uuid4().hex[:10]}",
        "slug": f"up-{uuid.uuid4().hex[:8]}",
        "offering": f"off_{uuid.uuid4().hex[:10]}",
        "offering_slug": f"o-{uuid.uuid4().hex[:8]}",
        "sub": f"sub_{uuid.uuid4().hex[:10]}",
        "plan": f"plan_{uuid.uuid4().hex[:8]}",
        "files": [],
    }
    cap = PLANS_BY_SLUG[plan_slug]
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO users (id, email, name, password_hash, role,
                               email_verified_at, created_at, updated_at)
            VALUES (:id, :email, 'Upload Owner', '$2b$12$0'||repeat('0',52),
                    'creator', timezone('UTC', NOW()),
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["owner"],
               "email": f"up-{uuid.uuid4().hex[:8]}@example.test"})

        c.execute(text("""
            INSERT INTO spaces (id, slug, name, status, creator_id,
                                created_at, updated_at)
            VALUES (:id, :slug, 'Upload Space', 'active', :cid,
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["space"], "slug": ids["slug"], "cid": ids["owner"]})

        existing = c.execute(
            text("SELECT id FROM creator_plans WHERE slug = :s"),
            {"s": plan_slug},
        ).first()
        if existing:
            ids["plan"] = existing[0]
            ids["plan_created"] = False
        else:
            c.execute(text("""
                INSERT INTO creator_plans
                    (id, slug, name, monthly_price_cents, currency,
                     transaction_fee_basis_points, collective_limit,
                     pathway_limit, is_active, created_at, updated_at)
                VALUES (:id, :slug, :name, :price, 'AUD', 800, 1, NULL, TRUE,
                        timezone('UTC', NOW()), timezone('UTC', NOW()))
            """), {"id": ids["plan"], "slug": plan_slug,
                   "name": cap.display_name,
                   "price": cap.monthly_price_cents or 0})
            ids["plan_created"] = True

        c.execute(text("""
            INSERT INTO creator_subscriptions
                (id, user_id, creator_plan_id, status, source, starts_at,
                 created_at, updated_at)
            VALUES (:id, :uid, :pid, 'active', 'manual_grant',
                    timezone('UTC', NOW()),
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["sub"], "uid": ids["owner"], "pid": ids["plan"]})

        c.execute(text("""
            INSERT INTO offerings
                (id, space_id, created_by_user_id, slug, title, status,
                 fulfilment_kind, created_at, updated_at)
            VALUES (:id, :sid, :uid, :slug, 'Race Offering', 'draft',
                    'digital_download',
                    timezone('UTC', NOW()), timezone('UTC', NOW()))
        """), {"id": ids["offering"], "sid": ids["space"],
               "uid": ids["owner"], "slug": ids["offering_slug"]})

        for i, (size, resources, status) in enumerate(seed_files):
            fid = f"ofl_seed_{uuid.uuid4().hex[:10]}"
            c.execute(text("""
                INSERT INTO offering_files
                    (id, offering_id, storage_key, original_filename,
                     content_type, byte_size, resource_count, sort_order,
                     validation_status, checks_performed, created_at)
                VALUES (:id, :oid, :key, :name, 'application/pdf', :size,
                        :res, :pos, :status, '[]'::jsonb,
                        timezone('UTC', NOW()))
            """), {
                "id": fid, "oid": ids["offering"],
                "key": of.build_storage_key(
                    offering_id=ids["offering"], filename=f"seed-{i}.pdf",
                ),
                "name": f"seed-{i}.pdf", "size": size, "res": resources,
                "pos": i, "status": status,
            })
            ids["files"].append(fid)
    return ids


def _cleanup(engine, ids: dict) -> None:
    """Best-effort teardown; always runs, even after an assertion fails."""
    with engine.begin() as c:
        keys = [
            r[0] for r in c.execute(
                text("SELECT storage_key FROM offering_files "
                     "WHERE offering_id = :o"),
                {"o": ids["offering"]},
            ).all()
        ]
        c.execute(
            text("UPDATE offering_files SET superseded_by_id = NULL, "
                 "replaces_file_id = NULL WHERE offering_id = :o"),
            {"o": ids["offering"]},
        )
        c.execute(text("DELETE FROM offering_files WHERE offering_id = :o"),
                  {"o": ids["offering"]})
        c.execute(text("DELETE FROM offerings WHERE id = :o"),
                  {"o": ids["offering"]})
        c.execute(text("DELETE FROM creator_subscriptions WHERE id = :i"),
                  {"i": ids["sub"]})
        c.execute(text("DELETE FROM spaces WHERE id = :s"), {"s": ids["space"]})
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": ids["owner"]})
        if ids.get("plan_created"):
            c.execute(text("DELETE FROM creator_plans WHERE id = :p"),
                      {"p": ids["plan"]})
    for key in keys:
        storage.delete_file(key)
    # And the now-empty per-Offering directory, so a suite run does not
    # leave litter that makes a real leftover object hard to spot.
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX / ids["offering"]
    try:
        root.rmdir()
    except OSError:
        pass   # not empty — something was deliberately kept


def _session(engine) -> Session:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _current_rows(engine, offering_id: str):
    with engine.begin() as c:
        return c.execute(text("""
            SELECT id, byte_size, resource_count, validation_status,
                   replaces_file_id, superseded_at, storage_key
              FROM offering_files
             WHERE offering_id = :o AND superseded_at IS NULL
        """), {"o": offering_id}).all()


def _all_keys(engine, offering_id: str) -> set[str]:
    with engine.begin() as c:
        return {
            r[0] for r in c.execute(
                text("SELECT storage_key FROM offering_files "
                     "WHERE offering_id = :o"),
                {"o": offering_id},
            ).all()
        }


def _objects_on_disk(offering_id: str) -> set[str]:
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX / offering_id
    if not root.exists():
        return set()
    return {
        str(p.relative_to(storage.UPLOAD_DIR))
        for p in root.rglob("*") if p.is_file()
    }


# ---------------------------------------------------------------------------
# Race 1 + 2 — uploads
# ---------------------------------------------------------------------------


def _try_upload(
    engine, ids: dict, data: bytes, name: str, barrier: threading.Barrier,
) -> str:
    """Call the real upload handler on an independent connection."""
    session = _session(engine)
    try:
        owner = session.get(User, ids["owner"])
        barrier.wait(timeout=20)
        files_api.upload_offering_file(
            slug=ids["slug"], offering_slug=ids["offering_slug"],
            file=_upload_file(data, name), description=None,
            db=session, current_user=owner,
        )
        return "created"
    except HTTPException as exc:
        if exc.status_code in (413, 422):
            return "refused"
        if exc.status_code == 429:
            return "shed"
        return f"http_{exc.status_code}"
    except Exception as exc:   # pragma: no cover — diagnostic
        return f"error: {type(exc).__name__}: {exc}"
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _race(engine, ids, payloads) -> dict[str, str]:
    barrier = threading.Barrier(len(payloads))
    results: dict[str, str] = {}

    def run(name: str, data: bytes) -> None:
        results[name] = _try_upload(engine, ids, data, f"{name}.pdf", barrier)

    threads = [
        threading.Thread(target=run, args=(n, d), daemon=True)
        for n, d in payloads
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


@pytest.mark.concurrency
class TestConcurrentUploads:

    def test_two_uploads_cannot_both_take_the_single_community_slot(
        self, engine,
    ):
        """Community's allowance is one file. Two simultaneous uploads
        must not both land, or the plan limit means nothing under the
        only conditions that matter."""
        assert PLANS_BY_SLUG["community"].offering_files_max == 1
        ids = _seed(engine, plan_slug="community")
        try:
            results = _race(
                engine, ids, [("a", _pdf(4096)), ("b", _pdf(4096))],
            )
            assert sorted(results.values()) == ["created", "refused"], results

            rows = _current_rows(engine, ids["offering"])
            assert len(rows) == 1, (
                f"the single slot took {len(rows)} files: {rows}"
            )
        finally:
            _cleanup(engine, ids)

    def test_the_byte_allowance_holds_under_a_race(self, engine):
        """Creator's bundle allowance is 75 MB. Seeded at 66 MB, two
        5 MB uploads race: 71 MB fits, 76 MB does not."""
        assert PLANS_BY_SLUG["creator"].offering_bundle_max_bytes == 75 * MB
        ids = _seed(
            engine, plan_slug="creator",
            seed_files=[(66 * MB, 1, FVS.passed.value)],
        )
        try:
            results = _race(
                engine, ids, [("a", _pdf(5 * MB)), ("b", _pdf(5 * MB))],
            )
            assert sorted(results.values()) == ["created", "refused"], results

            total = sum(r[1] for r in _current_rows(engine, ids["offering"]))
            assert total == 71 * MB, (
                f"bundle ended at {total / MB:.0f} MB, over the 75 MB "
                "allowance" if total > 75 * MB else f"unexpected {total}"
            )
        finally:
            _cleanup(engine, ids)

    def test_a_refused_racing_upload_leaves_no_orphaned_object(self, engine):
        """The loser transferred its bytes before losing the lock race.
        The compensating delete must remove them."""
        ids = _seed(engine, plan_slug="community")
        try:
            results = _race(
                engine, ids, [("a", _pdf(4096)), ("b", _pdf(4096))],
            )
            assert sorted(results.values()) == ["created", "refused"], results

            on_disk = _objects_on_disk(ids["offering"])
            referenced = _all_keys(engine, ids["offering"])
            assert on_disk - referenced == set(), (
                f"orphaned objects left in storage: {on_disk - referenced}"
            )
            assert len(on_disk) == 1
        finally:
            _cleanup(engine, ids)

    def test_the_winner_is_pending_and_not_downloadable(self, engine):
        ids = _seed(engine, plan_slug="community")
        try:
            _race(engine, ids, [("a", _pdf(4096)), ("b", _pdf(4096))])
            rows = _current_rows(engine, ids["offering"])
            assert len(rows) == 1
            assert rows[0][3] == FVS.pending.value
        finally:
            _cleanup(engine, ids)


# ---------------------------------------------------------------------------
# Race 3 — two workers, one file
# ---------------------------------------------------------------------------


@pytest.mark.concurrency
class TestConcurrentValidationWorkers:

    def test_two_workers_cannot_claim_the_same_file(self, engine):
        """``FOR UPDATE SKIP LOCKED``: the second claimer skips the locked
        row instead of blocking on it, so one file is never handed to two
        inspections. Without ``SKIP LOCKED`` this test would deadlock or
        both would claim."""
        ids = _seed(
            engine, plan_slug="creator",
            seed_files=[(2048, 1, FVS.pending.value)],
        )
        try:
            barrier = threading.Barrier(2)
            claims: dict[str, str | None] = {}

            def claimer(name: str) -> None:
                session = _session(engine)
                try:
                    barrier.wait(timeout=20)
                    claims[name] = worker.claim_next(session, worker_id=name)
                except Exception as exc:   # pragma: no cover — diagnostic
                    claims[name] = f"error: {exc}"
                finally:
                    try:
                        session.rollback()
                    finally:
                        session.close()

            threads = [
                threading.Thread(target=claimer, args=(n,), daemon=True)
                for n in ("worker-a", "worker-b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            got = [v for v in claims.values() if v]
            assert len(got) == 1, (
                f"the same file was claimed twice: {claims}"
            )
            assert got[0] == ids["files"][0]

            # And exactly one worker's identity is recorded on the row.
            with engine.begin() as c:
                owner_of_claim = c.execute(
                    text("SELECT validation_claimed_by FROM offering_files "
                         "WHERE id = :i"),
                    {"i": ids["files"][0]},
                ).scalar_one()
            assert owner_of_claim in ("worker-a", "worker-b")
        finally:
            _cleanup(engine, ids)

    def test_two_workers_with_two_files_take_one_each(self, engine):
        """The positive control: ``SKIP LOCKED`` must not serialise work
        that could proceed in parallel."""
        ids = _seed(
            engine, plan_slug="creator",
            seed_files=[
                (2048, 1, FVS.pending.value),
                (2048, 1, FVS.pending.value),
            ],
        )
        try:
            barrier = threading.Barrier(2)
            claims: dict[str, str | None] = {}

            def claimer(name: str) -> None:
                session = _session(engine)
                try:
                    barrier.wait(timeout=20)
                    claims[name] = worker.claim_next(session, worker_id=name)
                finally:
                    try:
                        session.rollback()
                    finally:
                        session.close()

            threads = [
                threading.Thread(target=claimer, args=(n,), daemon=True)
                for n in ("worker-a", "worker-b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            got = [v for v in claims.values() if v]
            assert len(got) == 2, claims
            assert len(set(got)) == 2, f"both workers took the same file: {got}"
        finally:
            _cleanup(engine, ids)


# ---------------------------------------------------------------------------
# Race 4 — two replacements, one file
# ---------------------------------------------------------------------------


@pytest.mark.concurrency
class TestConcurrentReplacement:

    def test_two_replacements_for_one_file_do_not_both_land(self, engine):
        """One slot, one live replacement. The second must be refused
        rather than creating a second pending row that would supersede an
        already-superseded original."""
        ids = _seed(
            engine, plan_slug="creator",
            seed_files=[(2048, 1, FVS.passed.value)],
        )
        target = ids["files"][0]
        try:
            barrier = threading.Barrier(2)
            results: dict[str, str] = {}

            def replacer(name: str) -> None:
                session = _session(engine)
                try:
                    owner = session.get(User, ids["owner"])
                    barrier.wait(timeout=20)
                    files_api.replace_offering_file(
                        slug=ids["slug"],
                        offering_slug=ids["offering_slug"],
                        file_id=target,
                        file=_upload_file(_pdf(3000), f"{name}.pdf"),
                        description=None, db=session, current_user=owner,
                    )
                    results[name] = "created"
                except HTTPException as exc:
                    results[name] = (
                        "refused" if exc.status_code in (409, 422)
                        else f"http_{exc.status_code}"
                    )
                except Exception as exc:
                    # An IntegrityError from the partial unique index is
                    # also a correct refusal — the database is the
                    # backstop behind the application check.
                    results[name] = (
                        "refused" if "unique" in str(exc).lower()
                        else f"error: {type(exc).__name__}: {exc}"
                    )
                finally:
                    try:
                        session.rollback()
                    finally:
                        session.close()

            threads = [
                threading.Thread(target=replacer, args=(n,), daemon=True)
                for n in ("a", "b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            assert sorted(results.values()) == ["created", "refused"], results

            with engine.begin() as c:
                pending = c.execute(text("""
                    SELECT COUNT(*) FROM offering_files
                     WHERE offering_id = :o AND replaces_file_id = :t
                       AND superseded_at IS NULL
                """), {"o": ids["offering"], "t": target}).scalar_one()
            assert pending == 1, f"{pending} live replacements for one file"

            # The original is untouched and still downloadable.
            with engine.begin() as c:
                status, superseded = c.execute(
                    text("SELECT validation_status, superseded_at "
                         "FROM offering_files WHERE id = :i"),
                    {"i": target},
                ).one()
            assert status == FVS.passed.value
            assert superseded is None
        finally:
            _cleanup(engine, ids)

    def test_a_refused_replacement_leaves_no_orphaned_object(self, engine):
        ids = _seed(
            engine, plan_slug="creator",
            seed_files=[(2048, 1, FVS.passed.value)],
        )
        target = ids["files"][0]
        try:
            barrier = threading.Barrier(2)
            results: dict[str, str] = {}

            def replacer(name: str) -> None:
                session = _session(engine)
                try:
                    owner = session.get(User, ids["owner"])
                    barrier.wait(timeout=20)
                    files_api.replace_offering_file(
                        slug=ids["slug"],
                        offering_slug=ids["offering_slug"],
                        file_id=target,
                        file=_upload_file(_pdf(3000), f"{name}.pdf"),
                        description=None, db=session, current_user=owner,
                    )
                    results[name] = "created"
                except Exception:
                    results[name] = "refused"
                finally:
                    try:
                        session.rollback()
                    finally:
                        session.close()

            threads = [
                threading.Thread(target=replacer, args=(n,), daemon=True)
                for n in ("a", "b")
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            on_disk = _objects_on_disk(ids["offering"])
            referenced = _all_keys(engine, ids["offering"])
            assert on_disk - referenced == set(), (
                f"orphaned objects: {on_disk - referenced}"
            )
        finally:
            _cleanup(engine, ids)
