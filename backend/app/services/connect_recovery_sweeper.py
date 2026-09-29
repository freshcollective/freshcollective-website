"""Retry the creator recoveries that are still outstanding.

The counterpart to the transfer sweeper. That one sends money FC owes; this
one gets money back that FC is owed after a refund or a dispute, where the
reversal did not complete at the time.

All of the arithmetic lives in :mod:`connect_reversals` and none of it is
repeated here. Each row is handed to ``reverse_to_target``, which re-reads it
under a row lock, recomputes the cumulative target from stored refund and
dispute state, and reverses only the remaining delta. The sweeper's job is
choosing *which* rows and *when* — nothing about how much.

Backoff rather than hammering
-----------------------------
The common reason a reversal fails is that the creator's balance cannot cover
it, and that does not change on a timescale worth retrying against. So attempts
are spaced out exponentially from ``reversal_attempted_at`` and
``reversal_attempt_count``: a transient blip is retried within minutes, while a
genuinely empty balance is asked again once a day rather than continuously.

No new state is needed for that distinction, and deliberately so. Whether FC is
still owed money is one fact (``connect_recovery_state`` plus
``connect_unrecovered_amount_cents``); *why* the last attempt failed is
another (``reversal_last_error``); and how hard to keep trying follows from the
attempt count. Adding a fourth column to encode "this one is hopeless" would be
a place for the system to give up, which is exactly what it should not have.

Nothing is ever written off. Past :data:`ATTENTION_ATTEMPTS` a row is reported
as needing a person, and it stays in the queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.payment import (
    ConnectRecoveryState,
    ConnectTransferStatus,
    PaymentTransaction,
    PayoutModel,
)
from app.services import connect_reversals

logger = logging.getLogger(__name__)

#: Rows considered per run. Anything left over is picked up next time.
DEFAULT_BATCH_SIZE = 50

#: First retry lands a quarter of an hour after a failure; each subsequent
#: attempt doubles the wait, up to a day.
BASE_COOLDOWN_SECONDS = 15 * 60
MAX_COOLDOWN_SECONDS = 24 * 60 * 60

#: Attempts after which a row is reported as needing a person. Not a limit —
#: it keeps being retried.
ATTENTION_ATTEMPTS = 5


@dataclass
class RecoverySweepReport:
    attempted: int = 0
    reversed: int = 0
    still_retryable: int = 0
    recovery_required: int = 0
    skipped: int = 0
    #: Eligible, but not due for another attempt yet.
    cooling_off: int = 0
    #: Still outstanding after repeated attempts. Reported, never written off.
    needs_attention: list[str] = field(default_factory=list)
    #: Total still owed back across everything this run looked at.
    outstanding_cents: int = 0

    def as_log_fields(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "reversed": self.reversed,
            "still_retryable": self.still_retryable,
            "recovery_required": self.recovery_required,
            "skipped": self.skipped,
            "cooling_off": self.cooling_off,
            "needs_attention": len(self.needs_attention),
            "outstanding_cents": self.outstanding_cents,
        }


def cooldown_for(attempts: int) -> timedelta:
    """How long to wait before trying a row again.

    Exponential from the attempt count, capped. Keeps a transient failure
    moving quickly while an empty creator balance is asked about once a day
    instead of continuously.
    """
    if attempts <= 0:
        return timedelta(0)
    seconds = min(
        BASE_COOLDOWN_SECONDS * (2 ** (attempts - 1)), MAX_COOLDOWN_SECONDS,
    )
    return timedelta(seconds=seconds)


def _due(txn: PaymentTransaction, *, now: datetime) -> bool:
    """Whether this row's backoff has elapsed."""
    if txn.reversal_attempted_at is None:
        return True
    return now - txn.reversal_attempted_at >= cooldown_for(
        txn.reversal_attempt_count or 0,
    )


def _claim_ids(db: Session, *, limit: int) -> list[str]:
    """Connect rows where money was transferred and is still owed back.

    Oldest attempt first, so a row that has been waiting longest gets the next
    slot rather than being starved by newer arrivals.

    Fully reversed rows fall out three ways over — by
    ``connect_recovery_state``, by the outstanding amount, and by the transfer
    status — because this is the query that decides whether FC asks Stripe for
    money again.
    """
    rows = db.execute(
        text(
            """
            SELECT id
            FROM payment_transactions
            WHERE payout_model = 'connect'
              AND provider_transfer_id IS NOT NULL
              AND connect_recovery_state = 'required'
              AND connect_unrecovered_amount_cents > 0
              AND connect_transfer_status <> 'reversed'
            ORDER BY reversal_attempted_at ASC NULLS FIRST, created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()
    return [row[0] for row in rows]


def sweep_pending_recoveries(
    db: Session, *, limit: int = DEFAULT_BATCH_SIZE, now: datetime | None = None,
) -> RecoverySweepReport:
    """One bounded pass over the outstanding creator recoveries."""
    now = now or datetime.utcnow()
    report = RecoverySweepReport()

    ids = _claim_ids(db, limit=limit)
    if not ids:
        return report

    logger.info("connect recovery sweeper: %s row(s) still owed back", len(ids))

    for txn_id in ids:
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == txn_id)
            .first()
        )
        if txn is None:
            report.skipped += 1
            continue

        # Re-checked rather than trusted from the claim query: another worker,
        # a refund webhook, or an external reversal may have settled this row
        # since. ``reverse_to_target`` checks again under its lock; this just
        # avoids the call.
        if (
            txn.payout_model != PayoutModel.connect.value
            or not txn.provider_transfer_id
            or txn.connect_transfer_status == ConnectTransferStatus.reversed.value
            or (txn.connect_unrecovered_amount_cents or 0) <= 0
            or txn.connect_recovery_state != ConnectRecoveryState.required.value
        ):
            report.skipped += 1
            continue

        if not _due(txn, now=now):
            report.cooling_off += 1
            report.outstanding_cents += txn.connect_unrecovered_amount_cents or 0
            continue

        report.attempted += 1
        outcome = connect_reversals.reverse_to_target(
            db, payment_transaction_id=txn_id, now=now,
        )

        if outcome.status in (
            ConnectTransferStatus.reversed.value,
            ConnectTransferStatus.partially_reversed.value,
        ):
            report.reversed += 1
        elif outcome.status == "retryable":
            report.still_retryable += 1
        elif outcome.status == ConnectRecoveryState.required.value:
            report.recovery_required += 1
        else:
            # NOOP or SKIPPED — the target was already met, or the row stopped
            # being eligible between the claim and the lock.
            report.skipped += 1

        db.refresh(txn)
        outstanding = txn.connect_unrecovered_amount_cents or 0
        report.outstanding_cents += outstanding
        if outstanding > 0 and (txn.reversal_attempt_count or 0) >= ATTENTION_ATTEMPTS:
            report.needs_attention.append(txn.id)

    if report.needs_attention:
        # Loud, and never mistaken for resolved: FC is still owed this.
        logger.error(
            "connect recovery sweeper: %s row(s) still owed after %s+ attempts "
            "and needing a person: %s",
            len(report.needs_attention), ATTENTION_ATTEMPTS,
            ", ".join(report.needs_attention),
        )

    logger.info("connect recovery sweeper: finished %s", report.as_log_fields())
    return report
