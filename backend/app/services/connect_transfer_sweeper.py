"""Retry the Connect transfers that are owed and unsent.

Exists because sending money is a network call that can fail for reasons
that clear on their own. The most common is not an outage at all: a transfer
tied to a charge that has not settled yet is refused for insufficient
balance, and the identical call succeeds a little later. Verified against
real Stripe behaviour in Phase 0.

What it looks at, and nothing else
----------------------------------
``payout_model = 'connect' AND connect_transfer_status = 'pending'``.

* ``manual`` and ``not_applicable`` rows are none of its business — their
  creator share is paid by batch, or there is no share at all.
* ``awaiting_payment`` rows are deliberately excluded. A transfer applies to
  them but is not yet due, and an abandoned Checkout Session sits there
  forever. Sweeping them would mean sending FC's money before the customer's
  arrived.
* ``sent`` rows are finished, and ``failed`` rows are terminal by
  classification rather than by exhaustion.

There is no permanent give-up. A row whose transfer keeps failing for a
retryable reason stays ``pending`` and keeps being tried; once its attempt
count passes :data:`connect_transfers.ATTENTION_ATTEMPTS` it is reported as
needing a look. A row marked done would be money quietly never sent, which
is the one outcome worth engineering against.

Missing fees
------------
A row can be ``pending`` with no processing fee — the webhook could not read
it, or a delayed payment settled after fulfilment. The sweeper resolves that
from Stripe before attempting, because the transfer amount depends on it and
guessing is not an option.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import stripe
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.checkout.stripe_client import get_stripe
from app.models.payment import (
    ConnectTransferStatus,
    PaymentTransaction,
    PayoutModel,
)
from app.services import connect_transfers

logger = logging.getLogger(__name__)

#: Transactions considered per run. Bounded so one invocation cannot run
#: unboundedly long; anything left over is picked up by the next run.
DEFAULT_BATCH_SIZE = 50


@dataclass
class SweepReport:
    considered: int = 0
    sent: int = 0
    still_pending: int = 0
    failed: int = 0
    skipped: int = 0
    fee_resolved: int = 0
    fee_unavailable: int = 0
    #: Rows whose attempt count has passed the attention threshold. Reported
    #: rather than written off.
    needs_attention: list[str] = field(default_factory=list)

    def as_log_fields(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "sent": self.sent,
            "still_pending": self.still_pending,
            "failed": self.failed,
            "skipped": self.skipped,
            "fee_resolved": self.fee_resolved,
            "fee_unavailable": self.fee_unavailable,
            "needs_attention": len(self.needs_attention),
        }


def _claim_ids(db: Session, *, limit: int) -> list[str]:
    """The owed-and-unsent transfers, oldest first.

    Ids only, and read without locking: each is re-read under its own row
    lock inside :func:`connect_transfers.execute_transfer`, which is where
    two workers racing on the same row resolve to one transfer. Selecting a
    row here that another worker takes first is harmless — the loser's
    attempt returns ``skipped``.
    """
    rows = db.execute(
        text(
            """
            SELECT id
            FROM payment_transactions
            WHERE payout_model = 'connect'
              AND connect_transfer_status = 'pending'
              AND provider_transfer_id IS NULL
            ORDER BY created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()
    return [row[0] for row in rows]


def _resolve_missing_fee(db: Session, txn: PaymentTransaction) -> bool:
    """Fetch the actual processing fee for a row that lacks one.

    Returns True when the row now has a fee. Never estimates: a failure to
    read leaves the row alone, still owed, for the next run.
    """
    if txn.processing_fee_cents is not None:
        return True
    if not txn.provider_payment_intent_id:
        logger.warning(
            "connect sweeper: txn=%s has no payment intent to read a fee from",
            txn.id,
        )
        return False

    api = get_stripe()
    try:
        pi = api.PaymentIntent.retrieve(
            txn.provider_payment_intent_id,
            expand=["latest_charge.balance_transaction"],
        )
    except Exception as exc:  # noqa: BLE001 — logged, retried next run
        logger.warning(
            "connect sweeper: txn=%s could not read its payment: %s", txn.id, exc,
        )
        return False

    if getattr(pi, "status", None) != "succeeded":
        # Should not happen for a ``pending`` row, but if it does, the money
        # is not in and nothing should be sent.
        logger.error(
            "connect sweeper: txn=%s is owed a transfer but its payment status "
            "is %r — not sending", txn.id, getattr(pi, "status", None),
        )
        return False

    charge = getattr(pi, "latest_charge", None)
    fee: int | None = None
    if charge is not None and not isinstance(charge, str):
        cid = getattr(charge, "id", None)
        if cid and not txn.provider_charge_id:
            txn.provider_charge_id = cid
        bt = getattr(charge, "balance_transaction", None)
        if bt is not None and hasattr(bt, "fee"):
            fee = int(bt.fee)

    if fee is None:
        logger.warning(
            "connect sweeper: txn=%s payment succeeded but its balance "
            "transaction carries no fee yet", txn.id,
        )
        db.commit()   # keep any charge id we did learn
        return False

    txn.processing_fee_cents = fee
    db.commit()
    logger.info("connect sweeper: txn=%s processing fee resolved as %s", txn.id, fee)
    return True


def sweep_pending_transfers(
    db: Session, *, limit: int = DEFAULT_BATCH_SIZE, now: datetime | None = None,
) -> SweepReport:
    """One bounded pass over the owed transfers."""
    report = SweepReport()
    ids = _claim_ids(db, limit=limit)
    report.considered = len(ids)
    if not ids:
        return report

    logger.info("connect sweeper: %s transfer(s) owed", len(ids))

    for txn_id in ids:
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == txn_id)
            .first()
        )
        if txn is None:
            report.skipped += 1
            continue

        # Re-checked rather than trusted from the claim query: another
        # worker may have finished this row since.
        if (
            txn.payout_model != PayoutModel.connect.value
            or txn.connect_transfer_status != ConnectTransferStatus.pending.value
            or txn.provider_transfer_id
        ):
            report.skipped += 1
            continue

        if txn.processing_fee_cents is None:
            if not _resolve_missing_fee(db, txn):
                report.fee_unavailable += 1
                report.still_pending += 1
                continue
            report.fee_resolved += 1

        outcome = connect_transfers.execute_transfer(
            db, payment_transaction_id=txn_id, now=now,
        )

        if outcome.status == ConnectTransferStatus.sent.value:
            report.sent += 1
        elif outcome.status == ConnectTransferStatus.failed.value:
            report.failed += 1
        elif outcome.status == ConnectTransferStatus.pending.value:
            report.still_pending += 1
        else:
            report.skipped += 1

        db.refresh(txn)
        if (
            txn.connect_transfer_status == ConnectTransferStatus.pending.value
            and (txn.transfer_attempt_count or 0) >= connect_transfers.ATTENTION_ATTEMPTS
        ):
            report.needs_attention.append(txn.id)

    if report.needs_attention:
        # Loud, and never mistaken for resolved: these are still owed.
        logger.error(
            "connect sweeper: %s transfer(s) still owed after %s+ attempts: %s",
            len(report.needs_attention),
            connect_transfers.ATTENTION_ATTEMPTS,
            ", ".join(report.needs_attention),
        )

    logger.info("connect sweeper: finished %s", report.as_log_fields())
    return report
