"""Disputes, and reversals FC did not make.

Two events, both about a Connect-routed purchase losing its funds after the
creator's share has been sent.

Disputes
--------
Stripe debits a disputed amount from the platform's balance, so Fresh
Collective is liable for the whole charge whatever happened to the creator's
share. What differs is whether that share has already left:

* nothing sent yet → do not send it. The transfer stays owed but is held out
  of the sweeper's queue while the charge is contested, because paying a
  creator for money FC may be about to lose is the one outcome worth
  preventing outright.
* already sent → try to take it back now, by the same reversal discipline a
  refund uses. If the creator's balance cannot cover it, the outstanding
  amount is recorded rather than assumed recovered.

``charge.dispute.closed`` is handled too, and not as scope creep: without it a
dispute FC *wins* would leave the hold in place forever and the creator would
never be paid. Won releases the hold; lost leaves the recovery outstanding,
which is the truth.

``payout_status`` is deliberately untouched — including ``held``, which means
"a manual payout is on hold" and travels with the manual batch machinery. A
Connect row's manual payout status is ``not_applicable`` and stays that way;
``connect_dispute_opened_at`` and ``connect_recovery_state`` carry the Connect
facts instead.

External reversals
------------------
A transfer can be reversed from the Stripe Dashboard or by Stripe itself.
``transfer.reversed`` is how FC's ledger catches up rather than continuing to
claim ``sent``. The transfer is re-fetched before anything is persisted,
because the live object's ``amount_reversed`` is the authoritative cumulative
figure.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment import (
    ConnectRecoveryState,
    ConnectTransferStatus,
    PaymentTransaction,
    PayoutModel,
)
from app.services import connect_reversals

logger = logging.getLogger(__name__)


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _find_connect_txn(db: Session, *, charge_id: str | None, payment_intent: str | None):
    """The Connect-routed transaction behind a disputed charge, if any."""
    if charge_id:
        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_charge_id == charge_id)
            .first()
        )
        if row is not None:
            return row
    if payment_intent:
        return (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_payment_intent_id == payment_intent)
            .first()
        )
    return None


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


def handle_dispute_created(
    dispute: dict, db: Session, *, now: datetime | None = None,
) -> None:
    """``charge.dispute.created`` — the customer is contesting the charge."""
    now = now or datetime.utcnow()
    charge_id = _field(dispute, "charge")
    payment_intent = _field(dispute, "payment_intent")

    txn = _find_connect_txn(
        db, charge_id=charge_id, payment_intent=payment_intent,
    )
    if txn is None:
        logger.warning(
            "charge.dispute.created: no transaction for charge=%s", charge_id,
        )
        return
    if txn.payout_model != PayoutModel.connect.value:
        # Manual rows already have a route for this: the refund gate refuses
        # a creator and flags an admin. Nothing Connect-specific to do.
        logger.info(
            "charge.dispute.created: txn=%s is %s-routed; no Connect action",
            txn.id, txn.payout_model,
        )
        return

    txn.connect_dispute_opened_at = now
    db.commit()

    if not txn.provider_transfer_id:
        # Held rather than cancelled: the transfer is still owed in principle,
        # and the dispute may be won. The sweeper skips it meanwhile.
        logger.error(
            "charge.dispute.created: txn=%s disputed before its transfer was "
            "sent — holding the creator transfer (status=%s) until the dispute "
            "closes", txn.id, txn.connect_transfer_status,
        )
        return

    # Money is already with the creator. FC is liable for the whole charge, so
    # the whole transfer is owed back — not a proportion of a refund that has
    # not happened. ``current_recovery_target`` reads that from
    # ``connect_dispute_opened_at``, which was just set, so the rule lives in
    # one place and a later sweep derives the same figure.
    outcome = connect_reversals.reverse_to_target(
        db, payment_transaction_id=txn.id, now=now,
    )
    logger.error(
        "charge.dispute.created: txn=%s creator recovery → %s "
        "(reversed_now=%s, cumulative=%s, unrecovered=%s)",
        txn.id, outcome.status, outcome.reversed_now,
        outcome.cumulative_reversed, outcome.unrecovered,
    )


def handle_dispute_closed(
    dispute: dict, db: Session, *, now: datetime | None = None,
) -> None:
    """``charge.dispute.closed`` — released if won, still owed if lost.

    Handled because the alternative leaves state permanently wrong: a dispute
    FC wins would otherwise hold the creator's transfer forever.
    """
    now = now or datetime.utcnow()
    charge_id = _field(dispute, "charge")
    status = _field(dispute, "status")

    txn = _find_connect_txn(
        db, charge_id=charge_id, payment_intent=_field(dispute, "payment_intent"),
    )
    if txn is None or txn.payout_model != PayoutModel.connect.value:
        return

    if status == "won":
        # FC kept the money, so the creator's share is owed again. Releasing
        # the hold lets the sweeper pick it up if it was never sent.
        txn.connect_dispute_opened_at = None
        if (
            txn.connect_recovery_state == ConnectRecoveryState.required.value
            and (txn.connect_unrecovered_amount_cents or 0) == 0
        ):
            txn.connect_recovery_state = ConnectRecoveryState.none.value
        db.commit()
        logger.info(
            "charge.dispute.closed: txn=%s dispute won — creator transfer "
            "released (status=%s)", txn.id, txn.connect_transfer_status,
        )
        return

    # Lost, or any other terminal status: FC is out the charge. Whatever could
    # not be reversed stays outstanding, and the hold stays on an unsent
    # transfer because it is no longer owed.
    logger.error(
        "charge.dispute.closed: txn=%s dispute status=%r — %s still outstanding "
        "from the creator", txn.id, status, txn.connect_unrecovered_amount_cents,
    )


# ---------------------------------------------------------------------------
# Reversals FC did not make
# ---------------------------------------------------------------------------


def handle_transfer_reversed(transfer: dict, db: Session) -> None:
    """``transfer.reversed`` — reconcile a reversal from outside FC."""
    transfer_id = _field(transfer, "id")
    if not transfer_id:
        logger.warning("transfer.reversed: event carries no transfer id")
        return

    outcome = connect_reversals.reconcile_from_stripe(
        db, transfer_id=str(transfer_id),
    )
    if outcome.status == connect_reversals.SKIPPED:
        # A transfer FC did not create, or one whose transaction is gone.
        logger.info("transfer.reversed: %s — %s", transfer_id, outcome.detail)
        return

    logger.info(
        "transfer.reversed: %s reconciled → status=%s cumulative=%s unrecovered=%s",
        transfer_id, outcome.status, outcome.cumulative_reversed,
        outcome.unrecovered,
    )


__all__ = [
    "ConnectTransferStatus",
    "handle_dispute_created",
    "handle_dispute_closed",
    "handle_transfer_reversed",
]
