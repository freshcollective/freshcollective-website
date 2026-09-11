"""Atomic creation + cancellation of manual creator payout batches.

Payout eligibility:

* creator + currency scope (cross-Collective; no per-Space filter);
* PaymentTransaction status ∈ (succeeded, partially_refunded);
* payout_status = 'pending';
* payment_provider = 'stripe';
* retained creator amount > 0
  (net_creator_amount_cents - refunded_creator_amount_cents);
* no active RefundOperation for the transaction
  (terminal_status IN (in_flight, accepted)).

The eligibility SELECT runs with ``FOR UPDATE OF pt`` so concurrent
refund submissions serialise behind the batch and either observe
``payout_status='paid'`` (refuse per creator-refund policy) or land
BEFORE the batch acquires locks (batch's NOT EXISTS excludes them).

BatchItem rows are IMMUTABLE — batch cancellation with
``revert_transactions=True`` may revert PaymentTransaction rows to
``payout_status='pending'`` and clear the convenience
``payout_batch_id`` pointer, but BatchItems stay as historical
evidence.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.creator_payout_batch import (
    CreatorPayoutBatch,
    CreatorPayoutBatchItem,
    CreatorPayoutBatchStatus,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PayoutStatus,
)
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationTerminalStatus,
)
from app.models.user import User


logger = logging.getLogger(__name__)


@dataclass
class PayoutBatchOutcome:
    batch_id: str
    creator_user_id: str
    currency: str
    total_amount_cents: int
    transaction_count: int
    included_transaction_ids: list[str] = field(default_factory=list)
    # Transactions filtered out with reason.
    excluded_transaction_ids: list[str] = field(default_factory=list)
    excluded_reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class PayoutBatchCancelOutcome:
    batch_id: str
    already_cancelled: bool
    reverted_transaction_ids: list[str] = field(default_factory=list)


class PayoutBatchStalenessError(Exception):
    """Submitted_total does not match snapshot — a refund or another
    batch attempt changed the payable set between load and submit."""


class PayoutBatchNoEligibleError(Exception):
    """Nothing to batch — payable set is empty at snapshot time."""


def create_payout_batch(
    db: Session, *,
    creator: User,
    currency: str,
    reference: str,
    paid_at: datetime,
    submitted_total_cents: int,
    note: str | None,
    created_by: User,
) -> PayoutBatchOutcome:
    """Create a manual payout batch for a creator.

    Atomically:

    1. Row-locks all eligible PaymentTransactions matching the
       eligibility filter above.
    2. Verifies the submitted total matches the snapshot total —
       staleness protection against refunds/batches racing between
       admin's page load and submit.
    3. Inserts the CreatorPayoutBatch with IMMUTABLE snapshot fields.
    4. Inserts one CreatorPayoutBatchItem per eligible transaction.
    5. Updates each transaction: payout_status='paid',
       payout_batch_id, payout_marked_at, payout_reference.

    Raises:

    * ``PayoutBatchStalenessError`` if the recomputed snapshot total
      differs from ``submitted_total_cents``.
    * ``PayoutBatchNoEligibleError`` if the eligibility set is empty.
    """
    if currency and currency != currency.upper():
        currency = currency.upper()

    # Row-locked eligibility query. NOT EXISTS subquery filters out
    # transactions with any active RefundOperation (in_flight /
    # accepted) — Correction 2 rule.
    rows = db.execute(
        text(
            """
            SELECT pt.id,
                   pt.net_creator_amount_cents,
                   pt.refunded_creator_amount_cents,
                   pt.currency
            FROM payment_transactions pt
            WHERE pt.creator_user_id = :creator_id
              AND pt.currency = :currency
              AND pt.payout_status = 'pending'
              AND pt.status IN ('succeeded', 'partially_refunded')
              AND pt.payment_provider = 'stripe'
              AND (pt.net_creator_amount_cents
                   - pt.refunded_creator_amount_cents) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM refund_operations ro
                  WHERE ro.payment_transaction_id = pt.id
                    AND ro.terminal_status IN ('in_flight', 'accepted')
              )
            ORDER BY pt.created_at
            FOR UPDATE OF pt
            """
        ),
        {"creator_id": creator.id, "currency": currency},
    ).fetchall()

    if not rows:
        raise PayoutBatchNoEligibleError(
            f"no eligible transactions for creator={creator.id} "
            f"currency={currency}"
        )

    included_ids: list[str] = []
    per_txn_retained: dict[str, tuple[int, int]] = {}  # id → (retained, refunded_creator)
    snapshot_total = 0
    for row in rows:
        txn_id = row[0]
        net = int(row[1] or 0)
        refunded_creator = int(row[2] or 0)
        retained = net - refunded_creator
        if retained <= 0:
            # Defensive — already filtered by SQL, but double-check.
            continue
        included_ids.append(txn_id)
        per_txn_retained[txn_id] = (retained, refunded_creator)
        snapshot_total += retained

    if snapshot_total != submitted_total_cents:
        raise PayoutBatchStalenessError(
            f"snapshot total {snapshot_total} != submitted "
            f"{submitted_total_cents}"
        )

    batch_id = f"cpb_{uuid.uuid4().hex[:24]}"
    now = datetime.utcnow()

    batch = CreatorPayoutBatch(
        id=batch_id,
        creator_user_id=creator.id,
        currency=currency,
        total_amount_cents=snapshot_total,
        transaction_count=len(included_ids),
        reference=reference.strip(),
        note=(note.strip() if note else None) or None,
        status=CreatorPayoutBatchStatus.paid,
        created_by_user_id=created_by.id,
        created_at=now,
        paid_at=paid_at,
    )
    db.add(batch)
    db.flush()

    for txn_id in included_ids:
        retained, refunded_creator = per_txn_retained[txn_id]
        db.add(CreatorPayoutBatchItem(
            id=f"cpbi_{uuid.uuid4().hex[:24]}",
            payout_batch_id=batch_id,
            payment_transaction_id=txn_id,
            creator_amount_cents_at_payout=retained,
            refunded_creator_amount_cents_at_payout=refunded_creator,
        ))

    # Denormalised convenience pointers on the transaction rows.
    db.execute(
        text(
            """
            UPDATE payment_transactions
            SET payout_status = 'paid',
                payout_batch_id = :batch_id,
                payout_marked_at = :paid_at,
                payout_reference = :ref,
                updated_at = NOW()
            WHERE id = ANY(:ids)
            """
        ),
        {
            "batch_id": batch_id,
            "paid_at": paid_at,
            "ref": batch.reference,
            "ids": included_ids,
        },
    )

    db.commit()

    logger.info(
        "payout batch created: id=%s creator=%s currency=%s total=%d txns=%d "
        "created_by=%s reference=%r",
        batch_id, creator.id, currency, snapshot_total,
        len(included_ids), created_by.id, batch.reference,
    )
    return PayoutBatchOutcome(
        batch_id=batch_id,
        creator_user_id=creator.id,
        currency=currency,
        total_amount_cents=snapshot_total,
        transaction_count=len(included_ids),
        included_transaction_ids=included_ids,
    )


def cancel_payout_batch(
    db: Session, *,
    batch: CreatorPayoutBatch,
    cancelled_by: User,
    cancellation_reason: str,
    revert_transactions: bool,
) -> PayoutBatchCancelOutcome:
    """Cancel a payout batch record. Correction of Fresh Collective's
    internal record only — does NOT reverse a bank transfer.

    * BatchItem rows are NEVER deleted.
    * With ``revert_transactions=True``: linked PaymentTransactions
      revert to ``payout_status='pending'``, clearing the convenience
      pointer and reference. Historical BatchItem membership remains.
    * Idempotent: re-cancelling an already-cancelled batch is a no-op
      (returns ``already_cancelled=True``).
    """
    reason = cancellation_reason.strip()
    if not reason:
        raise ValueError("cancellation_reason is required")

    if batch.status == CreatorPayoutBatchStatus.cancelled:
        return PayoutBatchCancelOutcome(
            batch_id=batch.id,
            already_cancelled=True,
            reverted_transaction_ids=[],
        )

    now = datetime.utcnow()
    batch.status = CreatorPayoutBatchStatus.cancelled
    batch.cancelled_at = now
    batch.cancelled_by_user_id = cancelled_by.id
    batch.cancellation_reason = reason
    db.flush()

    reverted_ids: list[str] = []
    if revert_transactions:
        # Row-lock all currently-pointed transactions before revert.
        rows = db.execute(
            text(
                """
                SELECT id FROM payment_transactions
                WHERE payout_batch_id = :batch_id
                FOR UPDATE
                """
            ),
            {"batch_id": batch.id},
        ).fetchall()
        reverted_ids = [r[0] for r in rows]
        if reverted_ids:
            db.execute(
                text(
                    """
                    UPDATE payment_transactions
                    SET payout_status = 'pending',
                        payout_batch_id = NULL,
                        payout_marked_at = NULL,
                        payout_reference = NULL,
                        updated_at = NOW()
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": reverted_ids},
            )

    db.commit()
    logger.info(
        "payout batch cancelled: id=%s cancelled_by=%s revert=%s "
        "reverted_count=%d reason=%r",
        batch.id, cancelled_by.id, revert_transactions,
        len(reverted_ids), reason,
    )
    return PayoutBatchCancelOutcome(
        batch_id=batch.id,
        already_cancelled=False,
        reverted_transaction_ids=reverted_ids,
    )


def compute_payable_summary(
    db: Session, *,
    creator_user_id: str,
    currency: str,
) -> dict:
    """Non-locking read of payable balance + transaction count for
    admin UI display before batch submission."""
    row = db.execute(
        text(
            """
            SELECT COALESCE(
                     SUM(pt.net_creator_amount_cents
                         - pt.refunded_creator_amount_cents), 0
                   ) AS payable,
                   COUNT(pt.id) AS txn_count
            FROM payment_transactions pt
            WHERE pt.creator_user_id = :creator_id
              AND pt.currency = :currency
              AND pt.payout_status = 'pending'
              AND pt.status IN ('succeeded', 'partially_refunded')
              AND pt.payment_provider = 'stripe'
              AND (pt.net_creator_amount_cents
                   - pt.refunded_creator_amount_cents) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM refund_operations ro
                  WHERE ro.payment_transaction_id = pt.id
                    AND ro.terminal_status IN ('in_flight', 'accepted')
              )
            """
        ),
        {"creator_id": creator_user_id, "currency": currency.upper()},
    ).first()
    return {
        "payable_cents": int(row[0] or 0),
        "transaction_count": int(row[1] or 0),
    }
