"""The background worker that validates uploaded Offering files.

Phase B5. The checks themselves already existed
(``offering_file_validation_service``); this module is what picks work
up, and the approved architecture for it is deliberately the cheapest
one that is still correct: a third in-process asyncio loop in fc-api's
FastAPI lifespan, ticking about every 20 seconds, validating one file at
a time.

Why in-process rather than a Render cron
----------------------------------------

Render crons are **not** free — $1/month minimum per service, billed per
second beyond it — and fc-api already runs two in-process lifespan loops
(``scheduled_publisher``, ``finite_plan_reconciler``) on exactly this
pattern. A third costs nothing, starts work within 20 seconds instead of
within a cron's minute granularity, and adds no new service to deploy,
monitor or pay for. The B5 assessment recommended it and it is what is
built here.

The trade-off is honest: this loop dies when the process dies. Every
mechanism below is built so that that is survivable rather than
surprising.

Scheduling is not the architecture
----------------------------------

:func:`validate_once` and :func:`cleanup_once` are plain synchronous
functions that need no event loop and no arguments. The asyncio loop at
the bottom of this module is one caller; a Render cron, a queue consumer
or a test are others. Moving to a queue later means calling the same two
functions from somewhere else — nothing about the claim, the lease or the
retry policy changes.

Their one optional argument, ``session_factory``, is the seam that makes
that true: it defaults to ``SessionLocal`` so the loop needs nothing, and
a different caller — a test driving the unit of work against the
transaction its fixtures wrote, or a consumer with its own pooling — can
supply its own.

Four properties, and the mechanism behind each
----------------------------------------------

**Validation runs outside the request event loop.** The loop calls
``asyncio.to_thread(validate_once)``, so inspection — which is CPU-bound
zip and CSV walking — happens on a worker thread and never blocks the
event loop that is serving API requests.

**No long transaction, no long row lock.** Claiming is its own short
committed transaction: it takes ``FOR UPDATE SKIP LOCKED``, stamps the
lease, commits, and closes. The expensive part — downloading tens of
megabytes from R2 and walking an archive — then runs with **no open
transaction at all**, and a second short transaction writes the result.
A 50 MB file therefore never holds a lock for the minute it takes to
inspect.

**Duplicate validation is impossible, and recoverable.** ``SKIP LOCKED``
means two instances claiming at once take different rows rather than
blocking. The lease (``validation_claimed_at``) is what makes it
recoverable: a worker killed mid-flight leaves a claim behind, and after
:data:`LEASE_SECONDS` another worker may take it. A crash costs one
lease interval, not a stuck file.

**Retries are bounded and backed off.** An inconclusive attempt is
counted; the next attempt waits ``RETRY_BACKOFF_SECONDS × attempts``;
after ``MAX_VALIDATION_ATTEMPTS`` the file is left in ``error`` and
logged at ERROR *once*, which is the only thing here that becomes a
Sentry event. An ordinary rejection — a macro document, a password-
protected ZIP, a formula-injected CSV — is logged at INFO, because it is
the system working.

What this worker cannot do
--------------------------

It cannot mark a file ``passed`` on its own judgement. The status comes
from :func:`offering_file_validation_service.validate_path`, which
derives it from ``REQUIRED_CHECKS`` and returns ``error`` rather than
``passed`` if any required check did not run. This module only persists
what that returns.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import tempfile
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import storage
from app.core.database import SessionLocal
from app.models.offering import (
    OfferingFile,
    OfferingFileValidationStatus as FVS,
)
from app.services.offering_file_validation_service import (
    MAX_VALIDATION_ATTEMPTS,
    apply_report,
    record_inconclusive,
    validate_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: How long a claim is honoured before another worker may take the row.
#:
#: Ten minutes: comfortably longer than the slowest legitimate
#: inspection (a 50 MB archive against a 60-second inspection budget,
#: plus the R2 download), and short enough that a killed worker's files
#: resume within one deploy cycle rather than needing an operator.
LEASE_SECONDS = 600

#: Multiplied by the attempt count, so retries spread out: ~2 minutes,
#: then ~4, then stop. Bounded by ``MAX_VALIDATION_ATTEMPTS``.
RETRY_BACKOFF_SECONDS = 120

#: Rejected file *contents* are removed from R2 after this long; the
#: validation record stays indefinitely. The approved retention rule.
REJECTED_CONTENT_TTL = timedelta(hours=24)

#: The loop's tick. ~20 seconds, per the approved architecture: fast
#: enough that a creator watching the Files tab sees a result while they
#: are still looking at it, and one indexed query against a partial
#: index when there is nothing to do.
_TICK_SECONDS = 20

#: Identifies which process holds a lease. Host and pid, so a stuck
#: claim in the database can be traced to a specific Render instance.
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"[:80]


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def claim_next(
    db: Session, *, worker_id: str = WORKER_ID, now: datetime | None = None,
) -> str | None:
    """Claim one file for validation, or return None if there is none.

    A short, committed transaction. ``FOR UPDATE SKIP LOCKED`` is what
    makes this safe across instances: a concurrent claimer skips the row
    this one has locked instead of waiting for it, so two workers never
    hand the same file to two inspections.

    Eligible rows, and why each clause is there:

      * ``validation_status IN ('pending', 'error')`` — awaiting a first
        attempt, or a retryable one.
      * ``validation_attempts < MAX`` — retries are bounded; an
        exhausted file is left alone rather than looped on.
      * ``content_deleted_at IS NULL`` — there are no bytes to inspect.
      * ``superseded_at IS NULL`` — the row is still in the bundle. A
        file the creator has since removed is not worth pulling 50 MB
        out of R2 to judge, and its verdict could not change anything: a
        superseded row is not downloadable whatever its status. A pending
        *replacement* is not superseded, so this clause never starves
        one.
      * unclaimed, **or** claimed longer than the lease ago — the
        recovery clause. Without it a worker killed between claiming and
        writing would strand the row forever.
      * for a retry, ``validated_at`` older than the backoff — so a file
        that fails for a transient reason is not retried three times in
        sixty seconds and exhausted on one bad minute.

    Oldest first, so a queue drains in the order creators uploaded.
    """
    now = now or datetime.utcnow()
    lease_cutoff = now - timedelta(seconds=LEASE_SECONDS)

    row = db.execute(
        text(
            """
            SELECT id
              FROM offering_files
             WHERE validation_status IN ('pending', 'error')
               AND validation_attempts < :max_attempts
               AND content_deleted_at IS NULL
               AND superseded_at IS NULL
               AND (
                     validation_claimed_at IS NULL
                  OR validation_claimed_at < :lease_cutoff
                   )
               AND (
                     validation_status = 'pending'
                  OR validated_at IS NULL
                  OR validated_at < :retry_cutoff
                   )
             ORDER BY created_at
             LIMIT 1
               FOR UPDATE SKIP LOCKED
            """
        ),
        {
            "max_attempts": MAX_VALIDATION_ATTEMPTS,
            "lease_cutoff": lease_cutoff,
            # Backoff scales with attempts already made. Expressed
            # against the *maximum* backoff here and refined per-row
            # below, because the per-row multiplier cannot be written in
            # one comparison without a correlated expression.
            "retry_cutoff": now - timedelta(seconds=RETRY_BACKOFF_SECONDS),
        },
    ).first()

    if row is None:
        return None

    file_id = row[0]
    target = (
        db.query(OfferingFile).filter(OfferingFile.id == file_id).first()
    )
    if target is None:   # pragma: no cover — selected under lock
        return None

    # Per-row backoff: the SQL above used the single-interval cutoff, so
    # a row on its second or third attempt is re-checked here against its
    # own multiplier and released untouched if it is not due yet.
    attempts = target.validation_attempts or 0
    if (
        target.validation_status == FVS.error.value
        and target.validated_at is not None
        and target.validated_at
        > now - timedelta(seconds=RETRY_BACKOFF_SECONDS * max(1, attempts))
    ):
        # Not due yet. Return without claiming and **without rolling
        # back**: the row lock is released when the caller ends its
        # transaction, which ``validate_once`` does immediately by
        # closing the session. Calling ``rollback()`` here would reach
        # out of this function and discard whatever else the caller's
        # transaction held — harmless for the loop, which owns a fresh
        # session, and wrong for any other caller.
        return None

    target.validation_claimed_at = now
    target.validation_claimed_by = worker_id
    db.commit()
    return file_id


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


def process_claimed(file_id: str, *, session_factory=None) -> str:
    """Download, inspect and record one claimed file. Returns its status.

    Opens and closes a session three times on purpose, and the middle gap
    is the point: the download and the inspection — the slow, memory-
    sensitive part — happen with no database session held at all.

      1. Read the row's storage key and declared type. Close.
      2. Stream the object to a local temporary file and inspect it.
         No session, no transaction, no lock.
      3. Write the outcome. Close.

    Any failure in step 2 is **inconclusive**, never a verdict: an
    unreachable store or a killed download says nothing about the file,
    and recording it as a rejection would refuse a creator's work for a
    platform problem.

    ``session_factory`` defaults to ``SessionLocal`` and exists so the
    worker's unit of work can be driven against a caller-supplied
    session. That is what lets the test suite exercise this function on
    the same transaction the fixtures wrote — and it is the same seam a
    future queue consumer would use.
    """
    sf = session_factory or SessionLocal
    db = sf()
    try:
        row = db.query(OfferingFile).filter(OfferingFile.id == file_id).first()
        if row is None:
            return "missing"
        storage_key = row.storage_key
        filename = row.original_filename
        declared_type = row.content_type
    finally:
        db.close()

    fd, tmp_path = tempfile.mkstemp(prefix="fc-validate-", suffix=".bin")
    try:
        try:
            with os.fdopen(fd, "wb") as out:
                storage.download_to_fileobj(storage_key, out)
        except Exception as exc:
            # Could not fetch the bytes. Inconclusive.
            return _record_failure(
                file_id, f"download failed: {exc!r}", session_factory=sf,
            )

        try:
            report = validate_path(
                path=tmp_path,
                filename=filename,
                declared_type=declared_type,
            )
        except Exception as exc:
            # A crash inside inspection. Also inconclusive — and
            # deliberately not a rejection, because a bug in our own
            # inspector must not be recorded as a finding about the
            # creator's file.
            logger.exception(
                "offering validation crashed: file=%s", file_id,
            )
            return _record_failure(
                file_id, f"inspection crashed: {exc!r}", session_factory=sf,
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:   # pragma: no cover — already gone
            pass

    return _record_report(file_id, report, session_factory=sf)


def _record_report(file_id: str, report, *, session_factory=None) -> str:
    """Persist a completed report, and promote a passing replacement."""
    db = (session_factory or SessionLocal)()
    try:
        row = db.query(OfferingFile).filter(OfferingFile.id == file_id).first()
        if row is None:   # pragma: no cover — deleted mid-flight
            return "missing"

        apply_report(db, file=row, report=report)
        row.validation_claimed_at = None
        row.validation_claimed_by = None

        if report.status == FVS.passed.value and row.replaces_file_id:
            _promote_replacement(db, replacement=row)

        db.commit()

        if report.status == FVS.passed.value:
            logger.info(
                "offering file validated: file=%s offering=%s",
                row.id, row.offering_id,
            )
        else:
            # An ordinary rejection is not an application error. INFO
            # keeps it out of Sentry while leaving it in the logs, which
            # is where "why was my file refused?" is answered.
            logger.info(
                "offering file not accepted: file=%s offering=%s reason=%s",
                row.id, row.offering_id, report.reason,
            )
        return report.status
    finally:
        db.close()


def _promote_replacement(db: Session, *, replacement: OfferingFile) -> None:
    """Supersede the file this replacement was uploaded to replace.

    Called only when the replacement has **passed**, which is the whole
    guarantee behind "a failed replacement never leaves purchasers
    without access": until this line runs, the original is still
    ``superseded_at IS NULL`` and still ``passed``, so download
    authorisation keeps serving it. If validation fails, this is never
    reached and the original simply remains current.

    The target is taken ``FOR UPDATE`` first. Two replacements cannot
    both promote against one target — the partial unique index already
    forbids two live pending replacements — but the lock also serialises
    this against a concurrent creator action on the same row, so the
    supersede and the pointer are written from a consistent read.
    """
    target_id = replacement.replaces_file_id
    db.execute(
        text("SELECT id FROM offering_files WHERE id = :id FOR UPDATE"),
        {"id": target_id},
    )
    target = (
        db.query(OfferingFile).filter(OfferingFile.id == target_id).first()
    )
    if target is None or target.superseded_at is not None:
        # Already gone or already superseded. The replacement stands on
        # its own; nothing to do. Not an error — a creator may have
        # removed the original while its replacement was being checked.
        return

    now = datetime.utcnow()
    target.superseded_at = now
    target.superseded_by_id = replacement.id
    # Inherit the slot's position so the bundle's order does not jump
    # when a file is replaced.
    replacement.sort_order = target.sort_order
    logger.info(
        "offering file replaced: old=%s new=%s offering=%s",
        target.id, replacement.id, replacement.offering_id,
    )


def _record_failure(
    file_id: str, detail: str, *, session_factory=None,
) -> str:
    """Record an inconclusive attempt and release the claim."""
    db = (session_factory or SessionLocal)()
    try:
        row = db.query(OfferingFile).filter(OfferingFile.id == file_id).first()
        if row is None:   # pragma: no cover
            return "missing"
        record_inconclusive(db, file=row, detail=detail)
        row.validation_claimed_at = None
        row.validation_claimed_by = None
        attempts = row.validation_attempts or 0
        db.commit()

        if attempts >= MAX_VALIDATION_ATTEMPTS:
            # Retries exhausted. This is the one thing in this module
            # that is a genuine application error and belongs in Sentry:
            # a file a creator uploaded that we have given up checking.
            logger.error(
                "offering validation gave up after %s attempts: file=%s "
                "offering=%s detail=%s — the file stays on hold and is "
                "not downloadable.",
                attempts, row.id, row.offering_id, detail,
            )
        else:
            logger.warning(
                "offering validation inconclusive (attempt %s of %s): "
                "file=%s detail=%s",
                attempts, MAX_VALIDATION_ATTEMPTS, row.id, detail,
            )
        return FVS.error.value
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The two unit-of-work entry points
# ---------------------------------------------------------------------------


def validate_once(*, session_factory=None) -> str | None:
    """Claim and process at most one file. Returns its status, or None.

    One file per call — the approved concurrency. On a 0.5-CPU instance
    inspecting two archives at once would contend for the only CPU and
    make ordinary API requests slower, which is the thing this design is
    most careful to avoid.
    """
    sf = session_factory or SessionLocal
    db = sf()
    try:
        file_id = claim_next(db)
    finally:
        db.close()

    if file_id is None:
        return None
    return process_claimed(file_id, session_factory=sf)


def cleanup_once(
    now: datetime | None = None, *, session_factory=None,
) -> int:
    """Remove the stored contents of files rejected over 24 hours ago.

    The approved retention rule, and the three things it is careful not
    to do:

      * It never touches a ``passed`` file. The CHECK constraint
        ``ck_offering_files_content_deleted_shape`` refuses
        ``content_deleted_at`` on one, so this is enforced by the schema
        and not only by this query.
      * It never touches a file with a live claim — the
        ``validation_claimed_at`` clause — so a file being inspected
        right now cannot have its bytes pulled out from under the
        inspection.
      * It never deletes the validation **record**. Only
        ``storage_key``'s object goes; ``checks_performed``,
        ``validation_reason`` and the timestamps stay, which is what
        keeps "why was this refused three weeks ago?" answerable.

    ``error`` files are deliberately left alone. Their contents are the
    evidence for a problem nobody has diagnosed yet.

    Returns the number of objects removed.
    """
    now = now or datetime.utcnow()
    cutoff = now - REJECTED_CONTENT_TTL
    lease_cutoff = now - timedelta(seconds=LEASE_SECONDS)

    db = (session_factory or SessionLocal)()
    removed = 0
    try:
        rows = (
            db.query(OfferingFile)
            .filter(
                OfferingFile.validation_status == FVS.rejected.value,
                OfferingFile.content_deleted_at.is_(None),
                OfferingFile.validated_at.isnot(None),
                OfferingFile.validated_at < cutoff,
            )
            .limit(100)
            .all()
        )
        for row in rows:
            if (
                row.validation_claimed_at is not None
                and row.validation_claimed_at > lease_cutoff
            ):
                continue   # a live claim; leave the bytes alone
            try:
                storage.delete_file(row.storage_key)
            except Exception:
                logger.exception(
                    "offering rejected-content delete failed: file=%s", row.id,
                )
                continue
            row.content_deleted_at = now
            removed += 1
        if removed:
            db.commit()
            logger.info(
                "offering cleanup: removed contents of %s rejected file(s)",
                removed,
            )
        return removed
    finally:
        db.close()


def sweep_once(*, session_factory=None) -> tuple[str | None, int]:
    """One tick's work: validate one file, then run the retention sweep."""
    status_ = validate_once(session_factory=session_factory)
    return status_, cleanup_once(session_factory=session_factory)


# ---------------------------------------------------------------------------
# Scheduling — one caller of the functions above
# ---------------------------------------------------------------------------

_task: asyncio.Task | None = None


async def _loop() -> None:
    logger.info(
        "offering_validation_worker loop starting (tick=%ss worker=%s)",
        _TICK_SECONDS, WORKER_ID,
    )
    while True:
        try:
            # ``to_thread`` is what keeps inspection off the event loop.
            # Everything inside is synchronous and blocking by design.
            await asyncio.to_thread(sweep_once)
        except Exception:
            logger.exception("offering_validation_worker iteration failed")
        await asyncio.sleep(_TICK_SECONDS)


def start_offering_validation_worker() -> None:
    """Fire-and-forget task launcher used from the app lifespan.

    Started unconditionally, **not** gated on
    ``settings.offerings_enabled``. Two reasons: when the flag is off the
    claim query matches nothing against a partial index and costs
    essentially nothing, and a file left mid-validation when the flag was
    switched off still deserves to be finished. The flag governs new
    Offering *activity*, not housekeeping of what already exists.
    """
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="offering_validation_worker")


async def stop_offering_validation_worker() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None


__all__ = [
    "LEASE_SECONDS",
    "RETRY_BACKOFF_SECONDS",
    "REJECTED_CONTENT_TTL",
    "WORKER_ID",
    "claim_next",
    "process_claimed",
    "validate_once",
    "cleanup_once",
    "sweep_once",
    "start_offering_validation_worker",
    "stop_offering_validation_worker",
]
