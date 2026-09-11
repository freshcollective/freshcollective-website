"""Correlate ``charge.refunded`` webhook payloads to RefundOperation
rows for state transition.

Metadata-first (Correction 1 — webhook-before-API-persist race):
the correlator matches on the Refund's ``metadata.refund_operation_id``
so it can transition an ``in_flight`` op whose API path has not yet
written back ``accepted`` / ``stripe_refund_id``.

Truncation-safe (Correction 3): absence of a RefundOperation's
``stripe_refund_id`` in the embedded ``charge.refunds.data[]`` is
NEVER treated as proof of non-match. Fast path matches by iterating
the embedded list; misses simply leave the op in ``accepted`` for a
subsequent webhook or reconciliation to heal.

Ledger updates are NOT performed here — they happen in the caller
(``_do_charge_refunded``) before this correlator is invoked. This
module only advances the RefundOperation state machine.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationTerminalStatus,
)


logger = logging.getLogger(__name__)


def correlate_refund_operations(
    db: Session, *,
    txn: PaymentTransaction,
    charge: dict,
    event_created: datetime | None,
    webhook_event_row_id: str | None,
) -> list[str]:
    """Transition RefundOperation rows matched by this webhook.

    Returns the list of transitioned RefundOperation ids (empty if
    none matched — e.g., pure Dashboard refund with no metadata).
    """
    refunds_container = charge.get("refunds") or {}
    refund_dicts = refunds_container.get("data") or []
    if not refund_dicts:
        return []

    now = datetime.utcnow()
    stamp = event_created or now
    transitioned: list[str] = []

    for refund_dict in refund_dicts:
        metadata = refund_dict.get("metadata") or {}
        refund_op_id = metadata.get("refund_operation_id")
        stripe_refund_id = refund_dict.get("id")

        if refund_op_id:
            # Metadata match — the authoritative correlation path.
            op = (
                db.query(RefundOperation)
                .filter(
                    RefundOperation.id == refund_op_id,
                    RefundOperation.payment_transaction_id == txn.id,
                )
                .with_for_update()
                .first()
            )
            if op is None:
                logger.warning(
                    "correlator: refund %s carries refund_operation_id=%s "
                    "but no matching op for txn %s — skipping",
                    stripe_refund_id, refund_op_id, txn.id,
                )
                continue
        else:
            # No metadata (Dashboard refund or legacy). Fall back to
            # matching by stripe_refund_id if any accepted op happens
            # to already know this id. Absence is not a transition.
            op = (
                db.query(RefundOperation)
                .filter(
                    RefundOperation.payment_transaction_id == txn.id,
                    RefundOperation.stripe_refund_id == stripe_refund_id,
                    RefundOperation.terminal_status.in_(
                        (
                            RefundOperationTerminalStatus.in_flight.value,
                            RefundOperationTerminalStatus.accepted.value,
                        )
                    ),
                )
                .with_for_update()
                .first()
            )
            if op is None:
                # Dashboard / external refund — ledger already handled.
                continue

        if op.terminal_status == RefundOperationTerminalStatus.webhook_confirmed.value:
            continue  # idempotent replay
        if op.terminal_status in (
            RefundOperationTerminalStatus.refused.value,
            RefundOperationTerminalStatus.failed.value,
        ):
            logger.error(
                "correlator: refund %s points at op %s in terminal-fail "
                "state=%s — refusing to overwrite",
                stripe_refund_id, op.id, op.terminal_status,
            )
            continue

        # in_flight or accepted → webhook_confirmed.
        if op.stripe_refund_id is None:
            op.stripe_refund_id = stripe_refund_id
        elif op.stripe_refund_id != stripe_refund_id:
            logger.error(
                "correlator: op %s already stored stripe_refund_id=%s "
                "but webhook carries id=%s — leaving as-is",
                op.id, op.stripe_refund_id, stripe_refund_id,
            )
            continue

        op.terminal_status = RefundOperationTerminalStatus.webhook_confirmed.value
        op.confirmed_at = stamp
        op.confirming_webhook_event_id = webhook_event_row_id
        op.updated_at = now
        transitioned.append(op.id)
        logger.info(
            "correlator: transitioned op %s → webhook_confirmed "
            "(stripe_refund_id=%s, webhook_event=%s)",
            op.id, op.stripe_refund_id, webhook_event_row_id,
        )

    if transitioned:
        db.flush()
    return transitioned
