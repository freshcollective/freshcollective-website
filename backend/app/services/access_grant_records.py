"""FIP3 — grants log helpers.

Every successful fulfilment writes at least one row to
``access_grant_records`` describing one (user, target, source)
event. FIP3 lifecycle operations (suspend on grace expiry, revoke
on unrecovered failure, reinstate on late recovery) consult this
log to answer "does the user still have access from another
source?" before touching the entitlement/pass row.

Contract
--------
* :func:`record_grant` is idempotent on the natural key
  ``(user_id, grant_kind, target_pathway_id, target_series_id,
  source_type, source_purchase_plan_id, source_payment_transaction_id)``.
  A duplicate call (e.g. a webhook redelivery reclaiming a stale
  lease) is a no-op: it does NOT create a second row and does NOT
  extend the ``granted_at`` timestamp.
* :func:`user_has_other_active_grant_for_pathway` returns True iff
  there's at least one active grant record for this user + pathway
  that is NOT this plan.
* :func:`revoke_records_for_plan` marks all active records owned
  by a plan as revoked with a reason string.
* :func:`reinstate_records_for_plan` clears the revoked_at/reason
  on this plan's records when the plan recovers from suspension.

The reader never joins this log to check "does user X have access
to pathway Y" — that stays with ``PathwayEntitlement`` /
``AccessPass``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.access_grant_record import (
    AccessGrantRecord,
    GRANT_KIND_PATHWAY,
    GRANT_KIND_SERIES,
    SOURCE_ADMIN_GRANT,
    SOURCE_FREE,
    SOURCE_MANUAL,
    SOURCE_PAY_IN_FULL,
    SOURCE_PLAN_PAYMENT,
    SOURCE_SUBSCRIPTION,
)


logger = logging.getLogger(__name__)


__all__ = [
    "record_grant",
    "record_pathway_grant",
    "record_series_grant",
    "user_has_other_active_grant_for_pathway",
    "user_has_other_active_grant_for_series",
    "revoke_records_for_plan",
    "reinstate_records_for_plan",
    "GRANT_KIND_PATHWAY",
    "GRANT_KIND_SERIES",
    "SOURCE_ADMIN_GRANT",
    "SOURCE_FREE",
    "SOURCE_MANUAL",
    "SOURCE_PAY_IN_FULL",
    "SOURCE_PLAN_PAYMENT",
    "SOURCE_SUBSCRIPTION",
]


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def record_grant(
    db: Session,
    *,
    user_id: str,
    grant_kind: str,
    target_pathway_id: str | None,
    target_series_id: str | None,
    source_type: str,
    source_purchase_plan_id: str | None = None,
    source_payment_transaction_id: str | None = None,
    source_note: str | None = None,
    granted_at: datetime,
) -> AccessGrantRecord:
    """Insert or return the existing matching grant record.

    Idempotent on the full natural key. Never mutates an existing
    row's ``granted_at`` / ``revoked_at`` — plan reinstatement
    calls :func:`reinstate_records_for_plan` explicitly.
    """
    if (target_pathway_id is None) == (target_series_id is None):
        raise ValueError(
            "record_grant: exactly one of target_pathway_id / target_series_id "
            "must be set"
        )

    existing = (
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.user_id == user_id,
            AccessGrantRecord.grant_kind == grant_kind,
            AccessGrantRecord.target_pathway_id == target_pathway_id,
            AccessGrantRecord.target_series_id == target_series_id,
            AccessGrantRecord.source_type == source_type,
            AccessGrantRecord.source_purchase_plan_id == source_purchase_plan_id,
            AccessGrantRecord.source_payment_transaction_id == source_payment_transaction_id,
        )
        .first()
    )
    if existing is not None:
        # If it was revoked and we're re-granting from the same source,
        # clear the revoke so the log reflects current reality.
        if existing.revoked_at is not None:
            existing.revoked_at = None
            existing.revoked_reason = None
            existing.updated_at = granted_at
            logger.info(
                "access_grant_records: cleared revoked_at on re-grant "
                "record=%s user=%s target=%s source=%s",
                existing.id, user_id,
                target_pathway_id or target_series_id, source_type,
            )
        return existing

    row = AccessGrantRecord(
        id=f"agr_{uuid.uuid4().hex[:24]}",
        user_id=user_id,
        grant_kind=grant_kind,
        target_pathway_id=target_pathway_id,
        target_series_id=target_series_id,
        source_type=source_type,
        source_purchase_plan_id=source_purchase_plan_id,
        source_payment_transaction_id=source_payment_transaction_id,
        source_note=source_note,
        granted_at=granted_at,
        created_at=granted_at,
        updated_at=granted_at,
    )
    db.add(row)
    db.flush()
    logger.info(
        "access_grant_records: recorded grant %s user=%s kind=%s target=%s "
        "source=%s plan=%s txn=%s",
        row.id, user_id, grant_kind,
        target_pathway_id or target_series_id, source_type,
        source_purchase_plan_id, source_payment_transaction_id,
    )
    return row


def record_pathway_grant(
    db: Session, *,
    user_id: str,
    pathway_id: str,
    source_type: str,
    source_purchase_plan_id: str | None = None,
    source_payment_transaction_id: str | None = None,
    source_note: str | None = None,
    granted_at: datetime,
) -> AccessGrantRecord:
    return record_grant(
        db,
        user_id=user_id,
        grant_kind=GRANT_KIND_PATHWAY,
        target_pathway_id=pathway_id,
        target_series_id=None,
        source_type=source_type,
        source_purchase_plan_id=source_purchase_plan_id,
        source_payment_transaction_id=source_payment_transaction_id,
        source_note=source_note,
        granted_at=granted_at,
    )


def record_series_grant(
    db: Session, *,
    user_id: str,
    series_id: str,
    source_type: str,
    source_purchase_plan_id: str | None = None,
    source_payment_transaction_id: str | None = None,
    source_note: str | None = None,
    granted_at: datetime,
) -> AccessGrantRecord:
    return record_grant(
        db,
        user_id=user_id,
        grant_kind=GRANT_KIND_SERIES,
        target_pathway_id=None,
        target_series_id=series_id,
        source_type=source_type,
        source_purchase_plan_id=source_purchase_plan_id,
        source_payment_transaction_id=source_payment_transaction_id,
        source_note=source_note,
        granted_at=granted_at,
    )


# ---------------------------------------------------------------------------
# Overlap queries — used by FIP3 lifecycle to decide whether to touch
# the entitlement/pass row.
# ---------------------------------------------------------------------------


def user_has_other_active_grant_for_pathway(
    db: Session, *,
    user_id: str,
    pathway_id: str,
    excluding_purchase_plan_id: str,
) -> bool:
    """Any active grant for this (user, pathway) not owned by this plan?

    Answers the "would suspending this plan strand the user" question
    at the pathway level. Considers records with a different
    ``source_purchase_plan_id`` (another plan) OR
    ``source_purchase_plan_id IS NULL`` (admin/manual/pay_in_full/free).
    """
    return db.query(
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.user_id == user_id,
            AccessGrantRecord.target_pathway_id == pathway_id,
            AccessGrantRecord.revoked_at.is_(None),
            or_(
                AccessGrantRecord.source_purchase_plan_id.is_(None),
                AccessGrantRecord.source_purchase_plan_id != excluding_purchase_plan_id,
            ),
        )
        .exists()
    ).scalar() is True


def user_has_other_active_grant_for_series(
    db: Session, *,
    user_id: str,
    series_id: str,
    excluding_purchase_plan_id: str,
) -> bool:
    """Series-scoped variant of the overlap check."""
    return db.query(
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.user_id == user_id,
            AccessGrantRecord.target_series_id == series_id,
            AccessGrantRecord.revoked_at.is_(None),
            or_(
                AccessGrantRecord.source_purchase_plan_id.is_(None),
                AccessGrantRecord.source_purchase_plan_id != excluding_purchase_plan_id,
            ),
        )
        .exists()
    ).scalar() is True


# ---------------------------------------------------------------------------
# Plan lifecycle write helpers
# ---------------------------------------------------------------------------


def revoke_records_for_plan(
    db: Session, *,
    purchase_plan_id: str,
    reason: str,
    now: datetime,
) -> list[AccessGrantRecord]:
    """Mark every active grant record owned by this plan as revoked.

    Idempotent: rows already revoked are left alone. Returns the
    rows that were transitioned in this call.
    """
    rows = (
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.source_purchase_plan_id == purchase_plan_id,
            AccessGrantRecord.revoked_at.is_(None),
        )
        .all()
    )
    for r in rows:
        r.revoked_at = now
        r.revoked_reason = reason
        r.updated_at = now
    if rows:
        db.flush()
        logger.info(
            "access_grant_records: revoked %d record(s) for plan=%s reason=%s",
            len(rows), purchase_plan_id, reason,
        )
    return rows


def reinstate_records_for_plan(
    db: Session, *,
    purchase_plan_id: str,
    now: datetime,
) -> list[AccessGrantRecord]:
    """Undo the most recent :func:`revoke_records_for_plan` for a plan.

    Only clears records whose ``revoked_reason`` matches a
    plan-lifecycle reason so we can't accidentally un-revoke a
    manually-revoked record.
    """
    plan_lifecycle_reasons = (
        "plan_suspended",
        "plan_failed",
        "plan_cancelled",
    )
    rows = (
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.source_purchase_plan_id == purchase_plan_id,
            AccessGrantRecord.revoked_at.is_not(None),
            AccessGrantRecord.revoked_reason.in_(plan_lifecycle_reasons),
        )
        .all()
    )
    for r in rows:
        r.revoked_at = None
        r.revoked_reason = None
        r.updated_at = now
    if rows:
        db.flush()
        logger.info(
            "access_grant_records: reinstated %d record(s) for plan=%s",
            len(rows), purchase_plan_id,
        )
    return rows
