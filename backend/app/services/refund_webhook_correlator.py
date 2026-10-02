"""Correlate ``charge.refunded`` webhook payloads to RefundOperation
rows for state transition.

Metadata-first (Correction 1 — webhook-before-API-persist race):
the correlator matches on the Refund's ``metadata.refund_operation_id``
so it can transition an ``in_flight`` op whose API path has not yet
written back ``accepted`` / ``stripe_refund_id``.

Truncation-safe (Correction 3): absence of a RefundOperation's
``stripe_refund_id`` in the embedded ``charge.refunds.data[]`` is
NEVER treated as proof of non-match. Fast path matches by iterating
the embedded list; misses fall through to a verified retrieve, and
anything still unmatched after that is left in ``accepted`` for
reconciliation to heal.

Verified retrieve (Correction 4): the embedded list can arrive empty.
Production ``charge.refunded`` payloads have been seen carrying
``refunds.data == []`` for a charge that really does have a succeeded
refund — the ledger updated, the transfer reversed and the member was
emailed, while the RefundOperation sat at ``accepted`` forever because
the correlator returned on the empty list before looking at anything
else. So when an active op already knows its ``stripe_refund_id``, that
Refund is read back from Stripe and checked before any transition.

What "verified" means here matters. The op is NOT confirmed because it
is the only accepted one, or because the charge was refunded — either
would be inference, and this ledger is webhook-authoritative. It is
confirmed only when the retrieved Refund agrees on all four facts: the
id, ``metadata.refund_operation_id``, ``metadata.payment_transaction_id``
and a ``succeeded`` status. Anything less leaves the row alone.

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

    # Anything the embedded list did not account for — because it was
    # empty, or truncated, or simply did not include this refund — gets
    # one verified read each. No-op when every op is already settled,
    # so an ordinary Dashboard refund makes no Stripe call at all.
    transitioned.extend(
        _confirm_by_verified_retrieve(
            db, txn=txn, stamp=stamp, now=now,
            webhook_event_row_id=webhook_event_row_id,
            already=set(transitioned),
        )
    )

    if transitioned:
        db.flush()
    return transitioned


def _sfield(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a Stripe object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _confirm_by_verified_retrieve(
    db: Session, *,
    txn: PaymentTransaction,
    stamp: datetime,
    now: datetime,
    webhook_event_row_id: str | None,
    already: set[str],
) -> list[str]:
    """Confirm still-active ops by reading their Refund back from Stripe.

    Only ops that already carry a ``stripe_refund_id`` are eligible: the
    API path wrote that id when Stripe accepted the refund, so it is a
    fact this system recorded rather than one being guessed at now. An op
    with no id has nothing to verify against and is left for
    reconciliation.

    Never raises. A failed retrieve leaves the op ``accepted``, which is
    exactly where the existing reconciliation path expects to find it —
    and the customer's refund has already been written by the caller, so
    nothing about it may depend on Stripe answering this second call.
    """
    candidates = (
        db.query(RefundOperation)
        .filter(
            RefundOperation.payment_transaction_id == txn.id,
            RefundOperation.stripe_refund_id.isnot(None),
            RefundOperation.terminal_status.in_(
                (
                    RefundOperationTerminalStatus.in_flight.value,
                    RefundOperationTerminalStatus.accepted.value,
                )
            ),
        )
        .with_for_update()
        .all()
    )
    candidates = [op for op in candidates if op.id not in already]
    if not candidates:
        return []

    from app.checkout.stripe_client import get_stripe

    transitioned: list[str] = []
    for op in candidates:
        try:
            api = get_stripe()
            refund = api.Refund.retrieve(op.stripe_refund_id)
        except Exception as exc:  # noqa: BLE001 — logged; op stays accepted
            logger.warning(
                "correlator: could not read refund %s for op %s (%s) — leaving "
                "accepted for reconciliation",
                op.stripe_refund_id, op.id, exc,
            )
            continue

        metadata = _sfield(refund, "metadata") or {}
        checks = {
            "id": _sfield(refund, "id") == op.stripe_refund_id,
            "refund_operation_id": _sfield(metadata, "refund_operation_id") == op.id,
            "payment_transaction_id": (
                _sfield(metadata, "payment_transaction_id") == txn.id
            ),
            "status": _sfield(refund, "status") == "succeeded",
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            logger.error(
                "correlator: retrieved refund %s does not verify for op %s "
                "(mismatched: %s) — no transition",
                op.stripe_refund_id, op.id, ", ".join(failed),
            )
            continue

        op.terminal_status = RefundOperationTerminalStatus.webhook_confirmed.value
        op.confirmed_at = stamp
        op.confirming_webhook_event_id = webhook_event_row_id
        op.updated_at = now
        transitioned.append(op.id)
        logger.info(
            "correlator: transitioned op %s → webhook_confirmed by verified "
            "retrieve (stripe_refund_id=%s, webhook_event=%s)",
            op.id, op.stripe_refund_id, webhook_event_row_id,
        )

    return transitioned
