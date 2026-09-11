"""Creator/admin-initiated refund endpoint.

``POST /api/creator/payments/{txn_id}/refund``

Authorization: admin OR creator-owner-of-txn.space_id. Cross-Collective
attempts return 404 (existence not leaked).

Payout-state gate:
* ``payout_status = pending`` → creator may refund.
* ``payout_status IN (paid, held)`` → creator refused (409). Admin
  may still refund but the RefundOperation is stamped with a
  ``payout_advisory`` flag for operational follow-up.
* ``payout_status = cancelled`` → transaction reverted to pending
  via batch cancellation; treat as ``pending``.
* ``payout_status = not_applicable`` → never applies to refundable
  member payments.

One-refund-in-flight rule: before submitting a new refund, opportunistically
reconcile any stale ``in_flight`` operations. If any RefundOperation for
this transaction remains ``in_flight``/``accepted`` after reconciliation,
refuse with 409.

Ledger writes to PaymentTransaction refund columns stay
webhook-authoritative — this endpoint only inserts the RefundOperation
and calls Stripe. The ``charge.refunded`` webhook handler is the only
writer of ``refunded_amount_cents`` / ``refunded_platform_fee_cents``
/ ``refunded_creator_amount_cents`` / ``last_refunded_at``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PayoutStatus,
)
from app.models.platform import Space
from app.models.refund_operation import (
    ACTIVE_REFUND_STATUSES,
    RefundOperation,
    RefundOperationReason,
    RefundOperationTerminalStatus,
    StripeIdentifierKind,
)
from app.models.user import User
from app.services import (
    refund_reconciliation as _reconcile,
    stripe_refund_orchestration as _stripe_refund,
)


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/creator", tags=["creator", "refunds"])


class RefundRequest(BaseModel):
    amount_cents: int = Field(..., gt=0, le=1_000_000_000)
    reason: str = Field(..., min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=250)


class RefundResponse(BaseModel):
    refund_operation_id: str
    payment_transaction_id: str
    requested_amount_cents: int
    stripe_refund_id: str | None
    terminal_status: str
    message: str
    refundable_before_cents: int
    refundable_after_cents: int
    payout_advisory: str | None = None


def _can_creator_act_on_space(user: User, space_id: str, db: Session) -> bool:
    """Admin passes always. Creator passes iff they own the Space."""
    if user.role == "admin":
        return True
    if user.role != "creator":
        return False
    owned = db.execute(
        text("SELECT 1 FROM spaces WHERE id = :sid AND creator_id = :uid"),
        {"sid": space_id, "uid": user.id},
    ).first()
    return owned is not None


def _payout_gate_action(
    *, txn: PaymentTransaction, actor_is_admin: bool,
) -> tuple[bool, str | None]:
    """Returns (allowed, payout_advisory_if_admin_override).

    Non-admin actors are refused for paid/held rows.
    Admin actors are always allowed; a payout_advisory flag is set on
    the RefundOperation so operations can track post-payout recovery.
    """
    ps = txn.payout_status
    if ps == PayoutStatus.pending or ps == PayoutStatus.cancelled:
        return True, None
    if ps == PayoutStatus.not_applicable:
        # Shouldn't apply to refundable member payments; refuse defensively.
        return False, None
    if ps == PayoutStatus.paid:
        if actor_is_admin:
            return True, "post_payout_manual_recovery_required"
        return False, None
    if ps == PayoutStatus.held:
        if actor_is_admin:
            return True, "post_hold_manual_review_required"
        return False, None
    return False, None


@router.post(
    "/payments/{txn_id}/refund",
    response_model=RefundResponse,
)
def creator_refund_payment(
    txn_id: str,
    body: RefundRequest,
    current_user: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> RefundResponse:
    # Step 1 — row-lock the PaymentTransaction. Serialises against
    # concurrent refunds AND concurrent payout batch creation on the
    # same row.
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == txn_id)
        .with_for_update()
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Payment not found.")

    # Cross-Collective authorization — 404 not 403 (existence not leaked).
    if txn.space_id is None or not _can_creator_act_on_space(
        current_user, txn.space_id, db,
    ):
        raise HTTPException(status_code=404, detail="Payment not found.")

    if txn.payment_provider != PaymentProvider.stripe:
        raise HTTPException(
            status_code=409,
            detail="Only Stripe-processed payments can be refunded here.",
        )
    if txn.status not in (
        PaymentTransactionStatus.succeeded,
        PaymentTransactionStatus.partially_refunded,
    ):
        raise HTTPException(
            status_code=409,
            detail="This payment is not in a refundable state.",
        )

    # Reason must be a known enum value; note is free-text.
    try:
        reason_enum = RefundOperationReason(body.reason)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown refund reason.")

    # Payout-state gate.
    actor_is_admin = current_user.role == "admin"
    allowed, payout_advisory = _payout_gate_action(
        txn=txn, actor_is_admin=actor_is_admin,
    )
    if not allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                "This payment has already been paid out to the creator. "
                "Contact the platform owner to arrange manual recovery."
            ),
        )

    # Step 2 — in-flight gate. Opportunistically reconcile any stale
    # in_flight ops before rejecting a new refund.
    blocking = _reconcile.get_blocking_operations(
        db, payment_transaction_id=txn.id,
    )
    for op in blocking:
        if op.terminal_status != RefundOperationTerminalStatus.in_flight.value:
            continue
        age = (datetime.utcnow() - op.created_at).total_seconds()
        if age > _reconcile.STALE_IN_FLIGHT_SECONDS:
            _reconcile.reconcile_in_flight(db, op)
    # Also reconcile stale accepted ops (webhook lost).
    for op in blocking:
        if op.terminal_status != RefundOperationTerminalStatus.accepted.value:
            continue
        age = (datetime.utcnow() - op.updated_at).total_seconds()
        if age > _reconcile.STALE_ACCEPTED_SECONDS:
            _reconcile.reconcile_accepted(db, op)

    # Re-check after any reconciliation.
    blocking = _reconcile.get_blocking_operations(
        db, payment_transaction_id=txn.id,
    )
    if blocking:
        raise HTTPException(
            status_code=409,
            detail=(
                "A refund is already being processed for this payment. "
                "Please wait for it to complete before requesting another."
            ),
        )

    # Step 3 — refundable balance + over-refund guard (ledger-side check).
    refundable_before = txn.gross_amount_cents - txn.refunded_amount_cents
    if refundable_before <= 0:
        raise HTTPException(
            status_code=409,
            detail="This payment has already been fully refunded.",
        )
    if body.amount_cents > refundable_before:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Refund amount exceeds the remaining refundable balance "
                f"of {refundable_before}."
            ),
        )

    # Step 4 — Stripe identifier resolution. Prefer charge id; fall
    # back to payment_intent id for pay-in-full rows pre-backfill.
    if txn.provider_charge_id:
        identifier_kind = StripeIdentifierKind.charge.value
        identifier_value = txn.provider_charge_id
    elif txn.provider_payment_intent_id:
        identifier_kind = StripeIdentifierKind.payment_intent.value
        identifier_value = txn.provider_payment_intent_id
    else:
        raise HTTPException(
            status_code=409,
            detail=(
                "This payment has no Stripe charge or payment intent "
                "identifier; contact the platform owner."
            ),
        )

    # Step 5 — insert RefundOperation as ``in_flight``. Commit + release
    # the row lock so the Stripe call runs outside the DB txn boundary
    # (network calls under row locks are risky — deadlock territory).
    op_id = f"refop_{uuid.uuid4().hex[:24]}"
    now = datetime.utcnow()
    op = RefundOperation(
        id=op_id,
        payment_transaction_id=txn.id,
        requested_by_user_id=current_user.id,
        requested_at=now,
        reason=reason_enum.value,
        note=(body.note.strip() if body.note else None) or None,
        requested_amount_cents=body.amount_cents,
        expected_cumulative_refunded_amount_cents=(
            txn.refunded_amount_cents + body.amount_cents
        ),
        stripe_identifier_kind=identifier_kind,
        stripe_identifier_value=identifier_value,
        stripe_refund_id=None,
        terminal_status=RefundOperationTerminalStatus.in_flight.value,
        payout_advisory=payout_advisory,
        created_at=now,
        updated_at=now,
    )
    db.add(op)
    db.commit()

    # Step 6 — Stripe API call. No DB lock held.
    stripe_refund_id: str | None = None
    api_error_message: str | None = None
    final_status = RefundOperationTerminalStatus.in_flight.value
    try:
        refund = _stripe_refund.create_refund(
            refund_operation_id=op_id,
            payment_transaction_id=txn.id,
            initiator_user_id=current_user.id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
            amount_cents=body.amount_cents,
            reason=reason_enum.value,
        )
        stripe_refund_id = refund.id
        final_status = RefundOperationTerminalStatus.accepted.value
    except stripe.InvalidRequestError as exc:
        api_error_message = str(exc)[:2000]
        final_status = RefundOperationTerminalStatus.refused.value
    except stripe.StripeError as exc:
        api_error_message = str(exc)[:2000]
        final_status = RefundOperationTerminalStatus.failed.value

    # Step 7 — conditional UPDATE. Guarded on ``terminal_status='in_flight'``
    # so we never regress a ``webhook_confirmed`` set by a webhook that
    # arrived while we were talking to Stripe (Correction 1).
    set_clauses = [
        "terminal_status = :to_status",
        "updated_at = NOW()",
    ]
    params: dict = {
        "op_id": op_id,
        "from_status": RefundOperationTerminalStatus.in_flight.value,
        "to_status": final_status,
    }
    if stripe_refund_id is not None:
        set_clauses.append("stripe_refund_id = :stripe_refund_id")
        params["stripe_refund_id"] = stripe_refund_id
    if api_error_message is not None:
        set_clauses.append("api_error_message = :api_err")
        params["api_err"] = api_error_message

    result = db.execute(
        text(
            f"UPDATE refund_operations SET {', '.join(set_clauses)} "
            f"WHERE id = :op_id AND terminal_status = :from_status"
        ),
        params,
    )
    db.commit()

    if result.rowcount == 0:
        # Webhook won the race — correlator already transitioned us to
        # webhook_confirmed. Verify stripe_refund_id matches.
        current = db.query(RefundOperation).filter(RefundOperation.id == op_id).first()
        if current and stripe_refund_id and current.stripe_refund_id != stripe_refund_id:
            logger.error(
                "creator refund: post-Stripe update: op %s already terminal "
                "(%s) but stored stripe_refund_id=%s != returned=%s",
                op_id, current.terminal_status, current.stripe_refund_id,
                stripe_refund_id,
            )
        if current:
            final_status = current.terminal_status
            stripe_refund_id = current.stripe_refund_id or stripe_refund_id

    # Response — the ledger has NOT been updated yet (webhook-authoritative).
    # Compute the projected refundable-after for UX.
    projected_refunded = txn.refunded_amount_cents
    if final_status in (
        RefundOperationTerminalStatus.accepted.value,
        RefundOperationTerminalStatus.webhook_confirmed.value,
    ):
        projected_refunded = txn.refunded_amount_cents + body.amount_cents

    if final_status == RefundOperationTerminalStatus.refused.value:
        message = f"Stripe refused this refund: {api_error_message}"
    elif final_status == RefundOperationTerminalStatus.failed.value:
        message = (
            "The refund could not be submitted due to a temporary error. "
            "Please try again shortly."
        )
    elif final_status == RefundOperationTerminalStatus.webhook_confirmed.value:
        message = "Refund confirmed by Stripe."
    else:
        message = "Refund initiated. Awaiting confirmation from Stripe."

    logger.info(
        "creator refund: op=%s txn=%s actor=%s amount=%d final_status=%s "
        "stripe_refund_id=%s",
        op_id, txn.id, current_user.id, body.amount_cents,
        final_status, stripe_refund_id,
    )

    http_status = 200
    if final_status == RefundOperationTerminalStatus.refused.value:
        # Communicate the operational failure cleanly. 409 = Stripe
        # refused for domain reasons (over-refund, already refunded,
        # etc.). The RefundOperation record captures the audit.
        raise HTTPException(status_code=409, detail=message)
    if final_status == RefundOperationTerminalStatus.failed.value:
        raise HTTPException(status_code=502, detail=message)

    return RefundResponse(
        refund_operation_id=op_id,
        payment_transaction_id=txn.id,
        requested_amount_cents=body.amount_cents,
        stripe_refund_id=stripe_refund_id,
        terminal_status=final_status,
        message=message,
        refundable_before_cents=refundable_before,
        refundable_after_cents=max(0, txn.gross_amount_cents - projected_refunded),
        payout_advisory=payout_advisory,
    )
