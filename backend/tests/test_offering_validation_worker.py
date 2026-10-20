"""Offerings Phase B5 — the validation worker's claim, retry and retention.

Drives the worker's real unit of work: the same ``claim_next`` with its
``FOR UPDATE SKIP LOCKED``, the same two short writes, the same
``validate_path``. Nothing here simulates the worker.

Storage is in filesystem mode, so ``download_to_fileobj`` reads real
bytes off real disk and the pass/reject outcomes are produced by the
actual inspection code rather than by a stubbed verdict.

Cross-connection duplicate prevention needs two genuine PostgreSQL
sessions and lives in ``test_concurrent_offering_uploads.py``; the
single-session tests here cover the lease, the backoff and the bounds.
"""

from __future__ import annotations

import io
import logging
import os
import pathlib
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core import storage
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingStatus,
)
from app.services import offering_files as of
from app.services import offering_file_validation_service as svc
from app.services import offering_validation as ov
from app.services import offering_validation_worker as worker

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "offerings"
MB = 1024 * 1024



class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def _captured():
    """Collect records from the two loggers that decide Sentry escalation.

    An explicit handler rather than ``caplog``, and it re-enables the
    loggers, because of something worth knowing about this suite:
    ``alembic/env.py`` calls ``logging.config.fileConfig`` when the
    session-scoped ``engine`` fixture runs migrations, and ``fileConfig``
    defaults to ``disable_existing_loggers=True``. Every ``app.*`` logger
    created before that point therefore has ``disabled = True`` for the
    rest of the run, and ``logger.info(...)`` becomes a silent no-op.

    So a test that asserted on log output without this would pass
    vacuously — it would see no ERROR record because it sees no record at
    all. Clearing ``disabled`` here is what makes the assertion mean
    something. (The underlying ``fileConfig`` call is pre-existing and
    out of scope for this phase; it is noted in the B5 report.)
    """
    handler = _ListHandler()
    names = (
        "app.services.offering_validation_worker",
        "app.services.offering_file_validation_service",
    )
    loggers = [logging.getLogger(n) for n in names]
    previous = [(lg, lg.level, lg.disabled) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
        lg.disabled = False
    try:
        yield handler.records
    finally:
        for lg, level, disabled in previous:
            lg.removeHandler(handler)
            lg.setLevel(level)
            lg.disabled = disabled


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


class _KeepOpen:
    """Session proxy whose ``close()`` is a no-op. See the twin helper in
    ``test_offering_file_management.py`` for why this is needed."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture
def sf(db):
    """A session factory handing the worker the test's transaction."""
    return lambda: _KeepOpen(db)


@pytest.fixture
def offering(db, make_space):
    def _make(**kw) -> Offering:
        space = make_space()
        d = dict(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"g-{uuid.uuid4().hex[:8]}", title="A Gentle Guide",
            status=OfferingStatus.draft.value,
        )
        d.update(kw)
        row = Offering(**d)
        db.add(row)
        db.flush()
        return row
    return _make


@pytest.fixture(autouse=True)
def clean_storage():
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX
    before = {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()
    yield
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p not in before:
                p.unlink()
        # Prune the per-Offering directories too. Without this a full
        # suite run leaves several hundred empty directories under
        # ``uploads/`` — harmless and gitignored, but the kind of litter
        # that makes a real leftover file hard to notice.
        for d in sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts), reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass   # not empty — something was deliberately kept


def _store(off: Offering, name: str, data: bytes) -> str:
    """Put real bytes where the worker will look for them."""
    key = of.build_storage_key(offering_id=off.id, filename=name)
    storage.upload_stream(key, io.BytesIO(data), "application/octet-stream")
    return key


def _pending(db, off, *, name, data, content_type, **kw) -> OfferingFile:
    key = _store(off, name, data)
    d = dict(
        id=_uid("ofl"), offering_id=off.id, storage_key=key,
        original_filename=name, content_type=content_type,
        byte_size=len(data), validation_status=FVS.pending.value,
    )
    d.update(kw)
    row = OfferingFile(**d)
    db.add(row)
    db.flush()
    return row


def _pdf(size: int = 2048) -> bytes:
    body = b"%PDF-1.4\n" + b"x" * max(0, size - 24) + b"\ntrailer\n%%EOF\n"
    return body[:size] if size >= 24 else body


def _good_zip(n: int = 3) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(n):
            zf.writestr(f"page-{i}.txt", b"a gentle note\n")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class TestOutcomes:

    def test_pending_becomes_passed(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        assert worker.validate_once(session_factory=sf) == FVS.passed.value
        db.refresh(row)
        assert row.validation_status == FVS.passed.value
        assert row.validated_at is not None
        assert row.validation_attempts == 1
        assert row.validation_policy_version == ov.VALIDATION_POLICY_VERSION
        assert row.is_downloadable is True

    def test_a_genuine_office_document_passes(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="genuine.docx",
            data=(FIXTURES / "genuine.docx").read_bytes(),
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        )
        assert worker.validate_once(session_factory=sf) == FVS.passed.value
        db.refresh(row)
        assert row.validation_status == FVS.passed.value

    def test_a_legitimate_zip_bundle_passes(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="bundle.zip", data=_good_zip(4),
            content_type="application/zip", resource_count=4,
        )
        assert worker.validate_once(session_factory=sf) == FVS.passed.value
        db.refresh(row)
        assert row.validation_status == FVS.passed.value

    def test_pending_becomes_rejected(self, db, offering, sf):
        """A CSV whose first cell is a formula. A real rejection, from the
        real inspection code."""
        off = offering()
        row = _pending(
            db, off, name="rates.csv",
            data=b"name,amount\n=cmd|'/c calc'!A1,5\n",
            content_type="text/csv",
        )
        assert worker.validate_once(session_factory=sf) == FVS.rejected.value
        db.refresh(row)
        assert row.validation_status == FVS.rejected.value
        assert row.validation_reason
        assert row.is_downloadable is False

    def test_a_rejected_file_records_what_actually_ran(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="book.docx", data=b"not an office file at all",
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        )
        worker.validate_once(session_factory=sf)
        db.refresh(row)
        ids = {c["id"] for c in row.checks_performed}
        assert ids, "no checks were recorded"
        # And nothing claims a check that did not run.
        assert "malware" not in ids
        assert not any("scan" in i for i in ids)

    def test_an_unreachable_store_is_inconclusive_not_a_rejection(
        self, db, offering, sf, monkeypatch,
    ):
        off = offering()
        row = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )

        def unreachable(*a, **kw):
            raise OSError("R2 unreachable")

        monkeypatch.setattr(storage, "download_to_fileobj", unreachable)
        assert worker.validate_once(session_factory=sf) == FVS.error.value
        db.refresh(row)
        assert row.validation_status == FVS.error.value
        assert row.validation_reason == "inconclusive"
        assert row.validation_attempts == 1
        # Crucially: not rejected. The file was never judged.
        assert row.validation_status != FVS.rejected.value

    def test_a_crash_inside_inspection_is_inconclusive(
        self, db, offering, sf, monkeypatch,
    ):
        """A bug in our inspector must not become a finding about the
        creator's file."""
        off = offering()
        row = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )

        def boom(**kw):
            raise RuntimeError("inspector bug")

        monkeypatch.setattr(worker, "validate_path", boom)
        assert worker.validate_once(session_factory=sf) == FVS.error.value
        db.refresh(row)
        assert row.validation_status == FVS.error.value

    def test_the_worker_cannot_approve_when_a_required_check_is_missing(
        self, db, offering, sf, monkeypatch,
    ):
        """The registry decides the status, not reaching the end of the
        function. Adding a required check nothing implements must leave
        the file unapproved rather than silently passing it."""
        off = offering()
        row = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        # A check nothing implements yet.
        extra = ov.Check("future_check", 1)
        monkeypatch.setattr(
            ov, "REQUIRED_CHECKS", ov.REQUIRED_CHECKS + (extra,),
        )
        monkeypatch.setattr(
            svc, "missing_required",
            lambda performed: frozenset({"future_check"})
            - {p["id"] for p in performed},
        )
        result = worker.validate_once(session_factory=sf)
        assert result != FVS.passed.value
        db.refresh(row)
        assert row.validation_status == FVS.error.value
        assert row.validation_reason == "checks_incomplete"
        assert row.is_downloadable is False


# ---------------------------------------------------------------------------
# Claiming, leases and restarts
# ---------------------------------------------------------------------------


class TestClaiming:

    def test_claiming_stamps_the_lease(self, db, offering):
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        got = worker.claim_next(db, worker_id="worker-a")
        assert got == row.id
        db.refresh(row)
        assert row.validation_claimed_at is not None
        assert row.validation_claimed_by == "worker-a"

    def test_a_claimed_file_is_not_claimed_again(self, db, offering):
        """Duplicate validation prevention, within the lease."""
        off = offering()
        _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        assert worker.claim_next(db, worker_id="worker-a") is not None
        assert worker.claim_next(db, worker_id="worker-b") is None

    def test_an_expired_lease_is_reclaimable(self, db, offering):
        """Recovery after a process restart, without an operator."""
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        row.validation_claimed_at = datetime.utcnow() - timedelta(
            seconds=worker.LEASE_SECONDS + 60,
        )
        row.validation_claimed_by = "worker-that-died"
        db.flush()
        got = worker.claim_next(db, worker_id="worker-new")
        assert got == row.id
        db.refresh(row)
        assert row.validation_claimed_by == "worker-new"

    def test_a_restart_mid_validation_resumes_and_completes(
        self, db, offering, sf,
    ):
        """The whole recovery story, end to end: a worker claims, dies
        before writing, and a later worker finishes the job."""
        off = offering()
        row = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        # Worker A claims, then the process dies — no result written.
        assert worker.claim_next(db, worker_id="worker-a") == row.id
        db.refresh(row)
        assert row.validation_status == FVS.pending.value

        # Nothing can be claimed while the lease is live.
        assert worker.validate_once(session_factory=sf) is None

        # The lease expires.
        row.validation_claimed_at = datetime.utcnow() - timedelta(
            seconds=worker.LEASE_SECONDS + 1,
        )
        db.flush()

        assert worker.validate_once(session_factory=sf) == FVS.passed.value
        db.refresh(row)
        assert row.validation_status == FVS.passed.value
        assert row.validation_claimed_at is None, "the claim was not released"

    def test_a_successful_run_releases_the_claim(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        worker.validate_once(session_factory=sf)
        db.refresh(row)
        assert row.validation_claimed_at is None
        assert row.validation_claimed_by is None

    def test_a_superseded_file_is_not_claimed(self, db, offering):
        """No point pulling bytes out of R2 to judge a file nobody can
        download."""
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        row.superseded_at = datetime.utcnow()
        db.flush()
        assert worker.claim_next(db) is None

    def test_a_passed_file_is_not_reclaimed(self, db, offering):
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        row.validation_status = FVS.passed.value
        db.flush()
        assert worker.claim_next(db) is None

    def test_a_quarantined_file_is_not_reclaimed(self, db, offering):
        """Quarantine is a withdrawal of approval, not a queue state. A
        re-run must not be able to quietly restore it."""
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        row.validation_status = FVS.quarantined.value
        row.quarantined_at = datetime.utcnow()
        db.flush()
        assert worker.claim_next(db) is None

    def test_a_quarantined_file_is_not_downloadable_by_anyone(
        self, db, offering, make_user,
    ):
        """Quarantine withdraws access from a file that was previously
        approved — including from a purchaser who had already downloaded
        it, and from the creator and an admin."""
        from app.uploads.authorization import authorize_upload
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=off.space_id, source="one_time_purchase", status="active",
        ))
        row.validation_status = FVS.passed.value
        db.flush()
        authorize_upload(row.storage_key, buyer, db)   # fine while approved

        svc.quarantine_file(db, file=row, reason="operator_withdrawal")
        db.flush()

        from app.models.user import User as _U
        owner = db.query(_U).filter(_U.id == off.created_by_user_id).one()
        admin = make_user(role="admin")
        for who in (buyer, owner, admin):
            with pytest.raises(HTTPException) as exc:
                authorize_upload(row.storage_key, who, db)
            assert exc.value.status_code == 403, who.id

    def test_a_file_whose_content_is_gone_is_not_claimed(self, db, offering):
        off = offering()
        row = _pending(
            db, off, name="a.csv", data=b"=1+1\n", content_type="text/csv",
        )
        row.validation_status = FVS.rejected.value
        row.content_deleted_at = datetime.utcnow()
        db.flush()
        assert worker.claim_next(db) is None


class TestRetries:

    def _errored(self, db, off, *, attempts: int, age_seconds: int):
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        row.validation_status = FVS.error.value
        row.validation_reason = "inconclusive"
        row.validation_attempts = attempts
        row.validated_at = datetime.utcnow() - timedelta(seconds=age_seconds)
        db.flush()
        return row

    def test_a_retry_waits_for_the_backoff(self, db, offering):
        off = offering()
        self._errored(db, off, attempts=1, age_seconds=5)
        assert worker.claim_next(db) is None

    def test_a_retry_is_claimed_once_the_backoff_has_passed(self, db, offering):
        off = offering()
        row = self._errored(
            db, off, attempts=1,
            age_seconds=worker.RETRY_BACKOFF_SECONDS + 10,
        )
        assert worker.claim_next(db) == row.id

    def test_the_backoff_lengthens_with_each_attempt(self, db, offering):
        """Attempt 2 waits twice as long as attempt 1."""
        off = offering()
        row = self._errored(
            db, off, attempts=2,
            age_seconds=worker.RETRY_BACKOFF_SECONDS + 10,
        )
        assert worker.claim_next(db) is None, "second retry fired too early"
        row.validated_at = datetime.utcnow() - timedelta(
            seconds=worker.RETRY_BACKOFF_SECONDS * 2 + 10,
        )
        db.flush()
        assert worker.claim_next(db) == row.id

    def test_retries_are_exhausted_and_then_left_alone(self, db, offering):
        off = offering()
        self._errored(
            db, off, attempts=svc.MAX_VALIDATION_ATTEMPTS,
            age_seconds=99_999,
        )
        assert worker.claim_next(db) is None

    def test_exhaustion_leaves_the_file_on_hold_and_undownloadable(
        self, db, offering, sf, monkeypatch,
    ):
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        monkeypatch.setattr(
            storage, "download_to_fileobj",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("gone")),
        )
        for attempt in range(svc.MAX_VALIDATION_ATTEMPTS):
            assert worker.validate_once(session_factory=sf) == FVS.error.value
            db.refresh(row)
            row.validated_at = datetime.utcnow() - timedelta(
                seconds=worker.RETRY_BACKOFF_SECONDS
                * (row.validation_attempts + 1)
                + 10,
            )
            db.flush()

        db.refresh(row)
        assert row.validation_attempts == svc.MAX_VALIDATION_ATTEMPTS
        assert row.validation_status == FVS.error.value
        assert row.is_downloadable is False
        # Nothing more is attempted.
        assert worker.validate_once(session_factory=sf) is None

    def test_only_exhaustion_is_logged_as_an_error(
        self, db, offering, sf, monkeypatch,
    ):
        """Approved: persistent failures go to Sentry, ordinary ones do
        not. ``LoggingIntegration`` turns an ERROR log into an event, so
        the log **level** is the Sentry decision, and that is what this
        asserts.
        """
        off = offering()
        row = _pending(
            db, off, name="a.pdf", data=_pdf(), content_type="application/pdf",
        )
        monkeypatch.setattr(
            storage, "download_to_fileobj",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("gone")),
        )

        with _captured() as records:
            worker.validate_once(session_factory=sf)
        levels = {r.levelno for r in records}
        assert logging.ERROR not in levels, "a first attempt was escalated"
        assert logging.WARNING in levels, "the attempt was not logged at all"

        db.refresh(row)
        row.validation_attempts = svc.MAX_VALIDATION_ATTEMPTS - 1
        row.validated_at = datetime.utcnow() - timedelta(seconds=99_999)
        db.flush()

        with _captured() as records:
            worker.validate_once(session_factory=sf)
        assert logging.ERROR in {r.levelno for r in records}, (
            "giving up on a file was not escalated"
        )

    def test_an_ordinary_rejection_is_not_logged_as_an_error(
        self, db, offering, sf,
    ):
        off = offering()
        _pending(
            db, off, name="rates.csv", data=b"a\n=1+1\n",
            content_type="text/csv",
        )
        with _captured() as records:
            assert worker.validate_once(session_factory=sf) == FVS.rejected.value
        assert logging.ERROR not in {r.levelno for r in records}
        assert records, "the rejection was not logged anywhere"


# ---------------------------------------------------------------------------
# No long transactions
# ---------------------------------------------------------------------------


class TestTransactionDiscipline:

    def test_no_session_is_held_while_a_file_is_inspected(
        self, db, offering, monkeypatch,
    ):
        """The requirement, proved rather than asserted in prose: at the
        moment ``validate_path`` runs, every session the worker opened
        has been closed."""
        off = offering()
        _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )

        state = {"open": 0, "open_during_inspection": None}

        class Tracked:
            def __init__(self, session):
                self._session = session
                self._closed = False
                state["open"] += 1

            def __getattr__(self, name):
                return getattr(self._session, name)

            def close(self):
                if not self._closed:
                    self._closed = True
                    state["open"] -= 1

        real = worker.validate_path

        def watched(**kw):
            state["open_during_inspection"] = state["open"]
            return real(**kw)

        monkeypatch.setattr(worker, "validate_path", watched)
        worker.validate_once(session_factory=lambda: Tracked(db))

        assert state["open_during_inspection"] == 0, (
            "a database session was held open across the download and "
            "inspection"
        )

    def test_the_loop_runs_inspection_off_the_event_loop(self):
        """Source contract: the tick must not call the blocking unit of
        work directly, or a 50 MB inspection would stall every request."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(worker._loop))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert "to_thread" in calls


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


class TestRetention:

    def _rejected(self, db, off, *, age_hours: float) -> OfferingFile:
        row = _pending(
            db, off, name="bad.csv", data=b"a\n=1+1\n",
            content_type="text/csv",
        )
        row.validation_status = FVS.rejected.value
        row.validation_reason = "formula_injection"
        row.checks_performed = [
            {"id": "csv_formula", "version": 1, "outcome": "fail"},
        ]
        row.validated_at = datetime.utcnow() - timedelta(hours=age_hours)
        db.flush()
        return row

    def _exists(self, key: str) -> bool:
        return (storage.UPLOAD_DIR / key).is_file()

    def test_rejected_contents_go_after_twenty_four_hours(
        self, db, offering, sf,
    ):
        off = offering()
        row = self._rejected(db, off, age_hours=25)
        assert self._exists(row.storage_key)

        assert worker.cleanup_once(session_factory=sf) == 1
        db.refresh(row)
        assert not self._exists(row.storage_key)
        assert row.content_deleted_at is not None

    def test_the_validation_record_survives_the_deletion(
        self, db, offering, sf,
    ):
        """Approved: contents go, troubleshooting data stays."""
        off = offering()
        row = self._rejected(db, off, age_hours=25)
        worker.cleanup_once(session_factory=sf)
        db.refresh(row)
        assert row.validation_status == FVS.rejected.value
        assert row.validation_reason == "formula_injection"
        assert row.checks_performed
        assert row.validated_at is not None
        assert row.original_filename == "bad.csv"

    def test_a_recently_rejected_file_is_left_alone(self, db, offering, sf):
        off = offering()
        row = self._rejected(db, off, age_hours=1)
        assert worker.cleanup_once(session_factory=sf) == 0
        assert self._exists(row.storage_key)
        db.refresh(row)
        assert row.content_deleted_at is None

    def test_a_passed_file_is_never_touched(self, db, offering, sf):
        off = offering()
        row = _pending(
            db, off, name="good.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        row.validation_status = FVS.passed.value
        row.validated_at = datetime.utcnow() - timedelta(days=30)
        db.flush()
        assert worker.cleanup_once(session_factory=sf) == 0
        assert self._exists(row.storage_key)

    def test_an_errored_file_keeps_its_contents(self, db, offering, sf):
        """Its bytes are the evidence for a problem nobody has diagnosed."""
        off = offering()
        row = _pending(
            db, off, name="odd.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        row.validation_status = FVS.error.value
        row.validated_at = datetime.utcnow() - timedelta(days=30)
        db.flush()
        assert worker.cleanup_once(session_factory=sf) == 0
        assert self._exists(row.storage_key)

    def test_a_file_with_a_live_claim_is_left_alone(self, db, offering, sf):
        """Never delete bytes an inspection is reading."""
        off = offering()
        row = self._rejected(db, off, age_hours=48)
        row.validation_claimed_at = datetime.utcnow()
        row.validation_claimed_by = "worker-busy"
        db.flush()
        assert worker.cleanup_once(session_factory=sf) == 0
        assert self._exists(row.storage_key)

    def test_the_database_refuses_to_mark_a_passed_file_deleted(
        self, db, offering,
    ):
        """"Never automatically delete a valid current file" is enforced by
        the schema, not only by the sweep's WHERE clause."""
        from sqlalchemy.exc import IntegrityError
        off = offering()
        row = _pending(
            db, off, name="good.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        row.validation_status = FVS.passed.value
        db.flush()
        row.content_deleted_at = datetime.utcnow()
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_a_deleted_rejected_file_is_still_not_downloadable(
        self, db, offering, sf, make_user,
    ):
        from app.uploads.authorization import authorize_upload
        off = offering()
        row = self._rejected(db, off, age_hours=25)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=off.space_id, source="free", status="active",
        ))
        db.flush()
        worker.cleanup_once(session_factory=sf)
        with pytest.raises(HTTPException) as exc:
            authorize_upload(row.storage_key, buyer, db)
        assert exc.value.status_code == 403

    def test_a_sweep_tick_does_both_jobs(self, db, offering, sf):
        off = offering()
        self._rejected(db, off, age_hours=25)
        fresh = _pending(
            db, off, name="guide.pdf", data=_pdf(),
            content_type="application/pdf",
        )
        validated, removed = worker.sweep_once(session_factory=sf)
        assert validated == FVS.passed.value
        assert removed == 1
        db.refresh(fresh)
        assert fresh.validation_status == FVS.passed.value


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class TestMemoryProfile:
    """Large files must not pass through the Python heap in one piece.

    These measure *Python allocations* with ``tracemalloc``, which is the
    thing that would exhaust a 512 MB instance. They establish an upper
    bound on this machine; they are **not** a claim about production
    throughput, which only a real Render instance can answer. See the
    report's memory findings.
    """

    def test_validating_a_large_file_does_not_load_it_into_memory(
        self, db, offering, sf,
    ):
        import tracemalloc
        size = 24 * MB
        off = offering()
        row = _pending(
            db, off, name="big.pdf", data=_pdf(size),
            content_type="application/pdf",
        )

        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
            assert worker.validate_once(session_factory=sf) == FVS.passed.value
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        growth = peak - before
        # Generous: a tenth of the file. The point is that the bound does
        # not scale with the file, not the exact number.
        assert growth < size // 10, (
            f"validation allocated {growth / MB:.1f} MB for a "
            f"{size / MB:.0f} MB file"
        )
        db.refresh(row)
        assert row.validation_status == FVS.passed.value

    def test_the_memory_bound_does_not_grow_with_the_file(
        self, db, offering, sf,
    ):
        """The real property: 8 MB and 24 MB cost about the same."""
        import tracemalloc

        def peak_for(size: int) -> int:
            off = offering()
            _pending(
                db, off, name="x.pdf", data=_pdf(size),
                content_type="application/pdf",
            )
            tracemalloc.start()
            try:
                tracemalloc.reset_peak()
                base = tracemalloc.get_traced_memory()[0]
                worker.validate_once(session_factory=sf)
                return tracemalloc.get_traced_memory()[1] - base
            finally:
                tracemalloc.stop()

        small = peak_for(8 * MB)
        large = peak_for(24 * MB)
        # Tripling the file must not triple the memory.
        assert large < small + (4 * MB), (small, large)

    def test_the_transfer_chunk_size_bounds_the_inspection_buffer(self):
        cfg = storage._offering_transfer_config()
        assert cfg.multipart_chunksize == 8 * MB
        assert cfg.max_request_concurrency == 3
        # Worst case in-flight per transfer, well inside 512 MB alongside
        # two concurrent uploads.
        assert cfg.multipart_chunksize * cfg.max_request_concurrency < 32 * MB
