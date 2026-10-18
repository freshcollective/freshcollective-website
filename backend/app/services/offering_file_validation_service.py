"""Running the checks, and recording honestly what ran.

This is the only place that decides an Offering file's
``validation_status``. Three rules shape it, and each comes from an
approved refinement:

  1. **Never approve on a partial result.** A check that could not
     complete is a rejection or an error, never a pass. The record
     distinguishes the two.
  2. **Never claim a check that did not run.** ``checks_performed``
     holds only outcomes that actually happened, with the policy
     version in force at the time, so "was this scanned for malware?"
     is answered from data — and today the honest answer is no.
  3. **Previously approved files keep access when policy grows, but
     not when revalidation finds a real problem.** Those are different
     events and they get different outcomes; see
     :func:`revalidate_file`.

Nothing here is a malware scanner.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.offering import (
    OfferingFile,
    OfferingFileValidationStatus as VS,
)
from app.services.offering_files import (
    OfferingFileRejected,
    validate_offering_upload,
)
from app.services.offering_validation import (
    VALIDATION_POLICY_VERSION,
    BudgetExceeded,
    CheckOutcome,
    InspectionBudget,
    ValidationFailure,
    all_extensions,
    check_csv,
    check_signature,
    check_structure,
    inspect_zip_family,
    missing_required,
)

logger = logging.getLogger(__name__)

#: Attempts before a file is left alone in ``error``. Bounded so an
#: unreadable file does not loop forever.
MAX_VALIDATION_ATTEMPTS = 3

_ZIP_FAMILY = {".zip", ".docx", ".xlsx", ".pptx"}


@dataclass
class ValidationReport:
    """What happened, in a form the caller can persist verbatim."""

    status: str
    policy_version: int
    checks: list[CheckOutcome] = field(default_factory=list)
    #: Creator-facing. Safe to show as-is; never names a detection
    #: technique or a scanner.
    message: str | None = None
    #: Machine-readable failing-check reason, for the UI to branch on.
    reason: str | None = None

    @property
    def records(self) -> list[dict]:
        return [c.as_record() for c in self.checks]


def validate_bytes(
    *,
    filename: str,
    declared_type: str | None,
    data: bytes,
    existing_bundle_bytes: int = 0,
    existing_bundle_count: int = 0,
    budget: InspectionBudget | None = None,
) -> ValidationReport:
    """Run every required check over one file's bytes.

    Pure: no database, no storage, no network. That is what makes the
    whole policy testable against genuine fixtures without standing
    anything up, and it is why this returns a report rather than
    writing one.
    """
    budget = budget or InspectionBudget()
    budget.restart_clock()
    checks: list[CheckOutcome] = []

    def fail(check: str, ver: int, exc: ValidationFailure) -> ValidationReport:
        checks.append(CheckOutcome(
            check, ver, "fail", reason=exc.reason, detail=exc.detail,
        ))
        return ValidationReport(
            status=VS.rejected.value,
            policy_version=VALIDATION_POLICY_VERSION,
            checks=checks,
            message=exc.message,
            reason=exc.reason,
        )

    # ── declared ────────────────────────────────────────────────────
    # Phase A's rules, now actually wired up.
    try:
        validate_offering_upload(
            filename=filename,
            content_type=declared_type,
            byte_size=len(data),
            existing_bundle_bytes=existing_bundle_bytes,
            existing_bundle_count=existing_bundle_count,
        )
    except OfferingFileRejected as exc:
        return fail("declared", 1, ValidationFailure(exc.reason, exc.message))
    checks.append(CheckOutcome("declared", 1, "pass"))

    stream = io.BytesIO(data)
    head = data[:512]

    # ── signature ───────────────────────────────────────────────────
    try:
        ident = check_signature(
            filename=filename, declared_type=declared_type or "", head=head,
        )
    except ValidationFailure as exc:
        return fail("signature", 1, exc)
    checks.append(CheckOutcome("signature", 1, "pass", detail=ident.fmt))

    # ── structure ───────────────────────────────────────────────────
    try:
        check_structure(
            filename=filename, ident=ident, stream=stream, budget=budget,
        )
    except ValidationFailure as exc:
        return fail("structure", 1, exc)
    except BudgetExceeded as exc:
        return _budget_rejection(checks, "structure", exc)
    checks.append(CheckOutcome("structure", 1, "pass"))

    ext = all_extensions(filename)[-1]

    # ── zip_contents ────────────────────────────────────────────────
    # Recorded as a pass with ``not_applicable`` detail rather than
    # omitted, so the record shows the check ran and had nothing to do.
    # An omitted entry would look like a check that never happened.
    if ext in _ZIP_FAMILY:
        stream.seek(0)
        try:
            summary = inspect_zip_family(
                filename=filename, stream=stream, budget=budget,
            )
        except ValidationFailure as exc:
            return fail("zip_contents", 1, exc)
        except BudgetExceeded as exc:
            return _budget_rejection(checks, "zip_contents", exc)
        checks.append(CheckOutcome(
            "zip_contents", 1, "pass", detail=str(summary),
        ))
    else:
        checks.append(CheckOutcome(
            "zip_contents", 1, "pass", detail="not_applicable",
        ))

    # ── csv_formula ─────────────────────────────────────────────────
    if ext == ".csv":
        stream.seek(0)
        try:
            summary = check_csv(stream=stream, budget=budget)
        except ValidationFailure as exc:
            return fail("csv_formula", 1, exc)
        except BudgetExceeded as exc:
            return _budget_rejection(checks, "csv_formula", exc)
        checks.append(CheckOutcome(
            "csv_formula", 1, "pass", detail=str(summary),
        ))
    else:
        checks.append(CheckOutcome(
            "csv_formula", 1, "pass", detail="not_applicable",
        ))

    # Belt and braces: the status is derived from the registry, not
    # from having reached the end of this function. If a check were
    # added to REQUIRED_CHECKS and not wired in here, this refuses to
    # pass the file rather than silently approving it.
    gaps = missing_required([c.as_record() for c in checks])
    if gaps:
        logger.error(
            "offering validation: required checks not implemented: %s",
            sorted(gaps),
        )
        return ValidationReport(
            status=VS.error.value,
            policy_version=VALIDATION_POLICY_VERSION,
            checks=checks,
            message=_UNAVAILABLE_MSG,
            reason="checks_incomplete",
        )

    return ValidationReport(
        status=VS.passed.value,
        policy_version=VALIDATION_POLICY_VERSION,
        checks=checks,
    )


_UNAVAILABLE_MSG = (
    "We can't finish checking this file right now, so it's on hold. "
    "Nothing is lost — we'll complete the checks shortly and let you know. "
    "You can keep working on this Offering."
)


def _budget_rejection(
    checks: list[CheckOutcome], check: str, exc: BudgetExceeded,
) -> ValidationReport:
    """A file we cannot finish inspecting is rejected, not approved.

    Rejected rather than left in ``error``, because the cause is a
    property of the file — too complex to inspect within policy — and
    an indefinite pending state would be a worse answer for a creator
    than a clear one.
    """
    checks.append(CheckOutcome(
        check, 1, "fail", reason="inspection_budget_exceeded", detail=exc.limit,
    ))
    return ValidationReport(
        status=VS.rejected.value,
        policy_version=VALIDATION_POLICY_VERSION,
        checks=checks,
        message=(
            "This file is too complex for us to check fully. Please "
            "simplify it or split it into smaller downloads."
        ),
        reason="inspection_budget_exceeded",
    )


# ---------------------------------------------------------------------------
# Persisting a result
# ---------------------------------------------------------------------------


def apply_report(
    db: Session, *, file: OfferingFile, report: ValidationReport,
    now: datetime | None = None,
) -> OfferingFile:
    """Write a report onto a file row. Does not commit."""
    now = now or datetime.utcnow()
    file.validation_status = report.status
    file.checks_performed = report.records
    file.validation_policy_version = report.policy_version
    file.validation_reason = report.reason
    file.validated_at = now
    file.validation_attempts = (file.validation_attempts or 0) + 1
    return file


def record_inconclusive(
    db: Session, *, file: OfferingFile, detail: str,
    now: datetime | None = None,
) -> OfferingFile:
    """An attempt that neither passed nor rejected the file.

    A worker crash, an OOM, an unreachable store. Status becomes
    ``error`` — **never** ``passed`` — and the attempt is counted so
    retries are bounded.
    """
    now = now or datetime.utcnow()
    file.validation_status = VS.error.value
    file.validation_reason = "inconclusive"
    file.validated_at = now
    file.validation_attempts = (file.validation_attempts or 0) + 1
    logger.error(
        "offering validation inconclusive: file=%s attempt=%s detail=%s",
        file.id, file.validation_attempts, detail,
    )
    return file


def should_retry(file: OfferingFile) -> bool:
    return (
        file.validation_status == VS.error.value
        and (file.validation_attempts or 0) < MAX_VALIDATION_ATTEMPTS
    )


# ---------------------------------------------------------------------------
# Policy growth and revalidation
# ---------------------------------------------------------------------------


def needs_revalidation(file: OfferingFile) -> bool:
    """Has this file missed a check that is required now?

    True for a file approved under an older policy. It stays
    ``passed`` — purchasers keep the access they paid for, which is an
    approved product decision — and this flags it for a background
    re-run rather than taking anything away.
    """
    if file.validation_status != VS.passed.value:
        return False
    return bool(missing_required(file.checks_performed or []))


def revalidate_file(
    db: Session, *, file: OfferingFile, report: ValidationReport,
    now: datetime | None = None,
) -> str:
    """Apply a revalidation result to an already-approved file.

    The distinction the refinement asks for, and the reason this is not
    just ``apply_report``:

      * The new checks **pass** → the record is upgraded and the file
        stays available. Nothing visible happens, which is correct.
      * A new check **fails** → this is a credible problem found in a
        file that was previously approved, and it is *not* ignored
        because of that approval. The file moves to ``quarantined``,
        access stops, and it is logged at ERROR so a person sees it.

    Returns the resulting status.
    """
    now = now or datetime.utcnow()
    merged = {r["id"]: r for r in (file.checks_performed or [])}
    for rec in report.records:
        merged[rec["id"]] = rec
    file.checks_performed = list(merged.values())
    file.validation_policy_version = report.policy_version
    file.validated_at = now

    if report.status == VS.passed.value:
        file.validation_status = VS.passed.value
        file.validation_reason = None
        return VS.passed.value

    # A failure on revalidation outranks the earlier approval.
    file.validation_status = VS.quarantined.value
    file.validation_reason = report.reason or "revalidation_failed"
    file.quarantined_at = now
    logger.error(
        "offering file quarantined by revalidation: file=%s offering=%s "
        "reason=%s — previously approved, access withdrawn.",
        file.id, file.offering_id, file.validation_reason,
    )
    return VS.quarantined.value


def quarantine_file(
    db: Session, *, file: OfferingFile, reason: str,
    now: datetime | None = None,
) -> OfferingFile:
    """Operator action: withdraw a file for a genuine security problem.

    The explicit control the refinement requires. Separate from
    ``rejected`` on purpose — that means "failed its checks at upload",
    while this means "was approved, and something has since been
    discovered". Keeping them apart keeps the history truthful.
    """
    now = now or datetime.utcnow()
    file.validation_status = VS.quarantined.value
    file.validation_reason = reason
    file.quarantined_at = now
    logger.error(
        "offering file quarantined by operator: file=%s offering=%s reason=%s",
        file.id, file.offering_id, reason,
    )
    return file


__all__ = [
    "MAX_VALIDATION_ATTEMPTS",
    "ValidationReport",
    "validate_bytes",
    "apply_report",
    "record_inconclusive",
    "should_retry",
    "needs_revalidation",
    "revalidate_file",
    "quarantine_file",
]
