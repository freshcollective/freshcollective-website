"""Recover stranded RefundOperations by consulting Stripe.

Two scenarios covered:

**In-flight recovery** (server crashed after inserting ``in_flight``
but before persisting the Stripe outcome):

  * Phase A (<= 24h since insert): replay ``stripe.Refund.create``
    with the SAME idempotency-key derived from the RefundOperation.id.
    Stripe's idempotency cache returns the cached outcome — either
    the previously-created Refund (op becomes ``accepted``), or the
    previously-cached 4xx (op becomes ``refused``). If Stripe truly
    never received the original call, the replay creates the refund
    now — still safe because the caller has already reserved this
    slot with the in-flight row.
  * Phase B (> 24h): idempotency cache expired. Search Stripe for
    a Refund carrying ``metadata.refund_operation_id == op.id``.
    If found, adopt it (op becomes ``accepted``). If exhaustive
    pagination finds nothing, transition to ``failed`` — Stripe
    has no record of the refund, so it is safe to free the
    PaymentTransaction for a new refund attempt.

**Accepted recovery** (webhook was lost after Stripe accepted the
refund):

  * ``stripe.Refund.retrieve(op.stripe_refund_id)``. If
    ``status='succeeded'``, force-sync the ledger via
    ``handle_charge_refunded``-equivalent path (monotonic guards
    protect us against a late webhook double-write), then transition
    to ``webhook_confirmed``. If ``status='failed'`` / ``'canceled'``,
    transition to ``failed``.

Both flows are used by the refund endpoint (lazy reconciliation on
new-refund attempt) and by the ``fc-refund-reconciler`` cron.

**Never creates a new RefundOperation and never generates a fresh
idempotency-key.** The whole point of reconciliation is to resolve
the STALE row, not to bypass it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import stripe
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.refund_operation import (
    RefundOperation,
    RefundOperationTerminalStatus,
    StripeIdentifierKind,
)
from app.services import stripe_refund_orchestration as _stripe_refund


logger = logging.getLogger(__name__)


# Phase A cutoff — Stripe's idempotency-key cache is documented as
# 24 hours. Give ourselves a small safety margin.
IDEMPOTENCY_CACHE_SECONDS = 23 * 60 * 60

# How long we allow ``accepted`` ops to sit without webhook
# confirmation before we start reconciling. The webhook usually
# arrives within seconds, so 10 minutes is a comfortable margin.
STALE_ACCEPTED_SECONDS = 600

# How long we allow ``in_flight`` ops to sit before the refund
# endpoint's lazy-reconcile kicks in. Kept short — a healthy Stripe
# call takes seconds; > 60 seconds strongly suggests a crash.
STALE_IN_FLIGHT_SECONDS = 60


def reconcile_in_flight(db: Session, op: RefundOperation) -> str:
    """Recover a stranded ``in_flight`` RefundOperation.

    Phase A (<= 24h since created_at): replay with same idempotency-key.
    Phase B (> 24h): metadata search via Refund.list.

    Returns the resulting ``terminal_status`` (may still be
    ``in_flight`` if Stripe was transiently unavailable — caller
    should refuse the new refund and let the operator retry).
    """
    if op.terminal_status != RefundOperationTerminalStatus.in_flight.value:
        return op.terminal_status  # already resolved by a race

    age = datetime.utcnow() - op.created_at
    if age.total_seconds() <= IDEMPOTENCY_CACHE_SECONDS:
        return _reconcile_in_flight_phase_a(db, op)
    return _reconcile_in_flight_phase_b(db, op)


def _reconcile_in_flight_phase_a(db: Session, op: RefundOperation) -> str:
    """Phase A — replay with same idempotency key. Stripe returns
    cached success/failure if the original call reached it, or
    creates the refund now if it did not."""
    try:
        refund = _stripe_refund.create_refund(
            refund_operation_id=op.id,
            payment_transaction_id=op.payment_transaction_id,
            initiator_user_id=op.requested_by_user_id,
            identifier_kind=op.stripe_identifier_kind,
            identifier_value=op.stripe_identifier_value,
            amount_cents=op.requested_amount_cents,
            reason=op.reason,
        )
    except stripe.InvalidRequestError as exc:
        # Cached 4xx (over-refund, already-refunded) OR fresh 4xx.
        return _finalise_conditional(
            db,
            op_id=op.id,
            from_status=RefundOperationTerminalStatus.in_flight.value,
            to_status=RefundOperationTerminalStatus.refused.value,
            api_error_message=f"reconcile_phase_a: {exc}"[:2000],
            stripe_refund_id=None,
        )
    except stripe.StripeError as exc:
        # Transient — leave in_flight; caller retries later.
        logger.warning(
            "reconcile in_flight: transient stripe error op=%s: %s",
            op.id, exc,
        )
        _stamp_error_only(
            db, op_id=op.id,
            api_error_message=f"reconcile_phase_a_transient: {exc}"[:2000],
        )
        return RefundOperationTerminalStatus.in_flight.value

    new_status = _finalise_conditional(
        db,
        op_id=op.id,
        from_status=RefundOperationTerminalStatus.in_flight.value,
        to_status=RefundOperationTerminalStatus.accepted.value,
        api_error_message=None,
        stripe_refund_id=refund.id,
    )
    return new_status


def _reconcile_in_flight_phase_b(db: Session, op: RefundOperation) -> str:
    """Phase B — idempotency cache expired. Search Stripe for a
    Refund carrying our metadata. If found, adopt. If not, mark
    failed — safe abandon.

    Only handles ``charge``-identified rows. A ``payment_intent``
    row would require an intermediate step (fetch the PI, get
    latest_charge). For MVP the vast majority of ops have
    charge ids by the time reconciliation kicks in (backfilled by
    the refund handler), so Phase B on PI-only ops leaves the row
    as in_flight for operator review.
    """
    if op.stripe_identifier_kind != StripeIdentifierKind.charge.value:
        logger.warning(
            "reconcile in_flight phase B: op %s uses payment_intent "
            "identifier; not implemented, leaving in_flight for operator",
            op.id,
        )
        _stamp_error_only(
            db, op_id=op.id,
            api_error_message=(
                "reconcile_phase_b_pi_not_supported"
            ),
        )
        return RefundOperationTerminalStatus.in_flight.value

    try:
        for refund in _stripe_refund.list_refunds_for_charge(
            op.stripe_identifier_value
        ):
            metadata = getattr(refund, "metadata", None) or {}
            if metadata.get("refund_operation_id") == op.id:
                return _finalise_conditional(
                    db,
                    op_id=op.id,
                    from_status=RefundOperationTerminalStatus.in_flight.value,
                    to_status=RefundOperationTerminalStatus.accepted.value,
                    api_error_message=None,
                    stripe_refund_id=refund.id,
                )
    except stripe.StripeError as exc:
        logger.warning(
            "reconcile in_flight phase B: stripe error op=%s: %s",
            op.id, exc,
        )
        _stamp_error_only(
            db, op_id=op.id,
            api_error_message=f"reconcile_phase_b_transient: {exc}"[:2000],
        )
        return RefundOperationTerminalStatus.in_flight.value

    # Exhausted — no Refund exists for this op. Safe abandon.
    return _finalise_conditional(
        db,
        op_id=op.id,
        from_status=RefundOperationTerminalStatus.in_flight.value,
        to_status=RefundOperationTerminalStatus.failed.value,
        api_error_message="reconcile_phase_b_no_stripe_refund",
        stripe_refund_id=None,
    )


def reconcile_accepted(db: Session, op: RefundOperation) -> str:
    """Recover a stranded ``accepted`` RefundOperation whose
    ``charge.refunded`` webhook never arrived.

    Uses ``stripe.Refund.retrieve(op.stripe_refund_id)`` to check
    the refund's current Stripe status. If succeeded, force-syncs
    the ledger via ``handle_charge_refunded``-equivalent path
    (monotonic guards protect against a late webhook double-write).
    """
    if op.terminal_status != RefundOperationTerminalStatus.accepted.value:
        return op.terminal_status
    if not op.stripe_refund_id:
        logger.error(
            "reconcile accepted: op %s has no stripe_refund_id — "
            "corrupt state; leaving for operator review",
            op.id,
        )
        return op.terminal_status

    try:
        refund = _stripe_refund.retrieve_refund(op.stripe_refund_id)
    except stripe.InvalidRequestError as exc:
        logger.error(
            "reconcile accepted: op %s stripe_refund_id=%s not found: %s",
            op.id, op.stripe_refund_id, exc,
        )
        _stamp_error_only(
            db, op_id=op.id,
            api_error_message=f"reconcile_accepted_not_found: {exc}"[:2000],
        )
        return op.terminal_status
    except stripe.StripeError as exc:
        logger.warning(
            "reconcile accepted: transient stripe error op=%s: %s",
            op.id, exc,
        )
        _stamp_error_only(
            db, op_id=op.id,
            api_error_message=f"reconcile_accepted_transient: {exc}"[:2000],
        )
        return op.terminal_status

    status = getattr(refund, "status", None)
    if status == "succeeded":
        # Force-sync the ledger. The refund handler is the authoritative
        # writer — call it directly with the current Stripe Charge state.
        # Monotonic guards make this safe even if a late webhook arrives.
        _force_sync_ledger_from_stripe(db, op, refund)
        return _finalise_conditional(
            db,
            op_id=op.id,
            from_status=RefundOperationTerminalStatus.accepted.value,
            to_status=RefundOperationTerminalStatus.webhook_confirmed.value,
            api_error_message=None,
            stripe_refund_id=None,  # already set
            set_confirmed=True,
        )
    if status in ("failed", "canceled"):
        return _finalise_conditional(
            db,
            op_id=op.id,
            from_status=RefundOperationTerminalStatus.accepted.value,
            to_status=RefundOperationTerminalStatus.failed.value,
            api_error_message=f"reconciled_stripe_status={status}",
            stripe_refund_id=None,
        )
    # 'pending' or another non-terminal — leave as accepted, retry.
    return op.terminal_status


def _force_sync_ledger_from_stripe(
    db: Session, op: RefundOperation, refund,
) -> None:
    """Refetch the Charge and apply the refund handler's cumulative
    update. Monotonic guards ensure safety if a webhook eventually
    arrives with the same or higher cumulative value."""
    charge_id = getattr(refund, "charge", None)
    if not charge_id:
        return
    try:
        charge = _stripe_refund.retrieve_charge(charge_id)
    except stripe.StripeError as exc:
        logger.warning(
            "reconcile accepted: could not fetch charge %s for op %s: %s",
            charge_id, op.id, exc,
        )
        return
    # Convert to plain dict so refund_handlers._do_charge_refunded
    # sees the same shape it gets from a real webhook payload.
    charge_dict = (
        charge.to_dict_recursive() if hasattr(charge, "to_dict_recursive")
        else dict(charge)
    )
    from app.webhooks.refund_handlers import _do_charge_refunded
    _do_charge_refunded(
        db, charge=charge_dict, event_created=None,
        provider_event_id=None,
        webhook_event_row_id=None,
    )


def _finalise_conditional(
    db: Session, *,
    op_id: str,
    from_status: str,
    to_status: str,
    api_error_message: str | None,
    stripe_refund_id: str | None,
    set_confirmed: bool = False,
) -> str:
    """Conditional UPDATE guarded on ``terminal_status = from_status``.
    Never regresses; if the row has already moved on (e.g. correlator
    won a race), this is a no-op."""
    params: dict = {
        "op_id": op_id,
        "from_status": from_status,
        "to_status": to_status,
        "api_err": api_error_message,
    }
    set_clauses = [
        "terminal_status = :to_status",
        "reconciled_at = NOW()",
        "updated_at = NOW()",
    ]
    if api_error_message is not None:
        set_clauses.append("api_error_message = :api_err")
    if stripe_refund_id is not None:
        set_clauses.append("stripe_refund_id = :stripe_refund_id")
        params["stripe_refund_id"] = stripe_refund_id
    if set_confirmed:
        set_clauses.append("confirmed_at = COALESCE(confirmed_at, NOW())")

    result = db.execute(
        text(
            f"UPDATE refund_operations SET {', '.join(set_clauses)} "
            f"WHERE id = :op_id AND terminal_status = :from_status"
        ),
        params,
    )
    db.commit()
    if result.rowcount == 0:
        logger.info(
            "reconcile: op %s already moved past %s — no state change",
            op_id, from_status,
        )
        # Re-fetch to return the actual current status.
        row = db.execute(
            text(
                "SELECT terminal_status FROM refund_operations WHERE id = :op_id"
            ),
            {"op_id": op_id},
        ).first()
        return row[0] if row else from_status
    return to_status


def _stamp_error_only(db: Session, *, op_id: str, api_error_message: str) -> None:
    """Attach an error message without changing state — used to leave
    a breadcrumb after a transient reconciliation failure."""
    db.execute(
        text(
            "UPDATE refund_operations "
            "SET api_error_message = :msg, updated_at = NOW() "
            "WHERE id = :op_id"
        ),
        {"op_id": op_id, "msg": api_error_message[:2000]},
    )
    db.commit()


def get_blocking_operations(
    db: Session, *, payment_transaction_id: str,
) -> list[RefundOperation]:
    """Return RefundOperations that would block a new refund on the
    given PaymentTransaction. Ignores in_flight rows younger than
    ``STALE_IN_FLIGHT_SECONDS`` — the actual endpoint code triggers
    reconciliation on stale in_flight rows before this returns."""
    return (
        db.query(RefundOperation)
        .filter(
            RefundOperation.payment_transaction_id == payment_transaction_id,
            RefundOperation.terminal_status.in_(
                (
                    RefundOperationTerminalStatus.in_flight.value,
                    RefundOperationTerminalStatus.accepted.value,
                )
            ),
        )
        .all()
    )


def sweep_stale_operations(
    db: Session, *,
    now: datetime | None = None,
    max_operations: int = 100,
) -> dict:
    """Cron entry point. Reconcile in_flight and accepted ops that
    have exceeded their staleness threshold.

    Returns a summary dict with counts per outcome.
    """
    now = now or datetime.utcnow()
    stale_in_flight_cutoff = now - timedelta(seconds=STALE_IN_FLIGHT_SECONDS)
    stale_accepted_cutoff = now - timedelta(seconds=STALE_ACCEPTED_SECONDS)

    summary: dict = {
        "in_flight_reconciled": 0,
        "in_flight_transient": 0,
        "accepted_reconciled": 0,
        "accepted_transient": 0,
    }

    # In-flight sweep.
    in_flight = (
        db.query(RefundOperation)
        .filter(
            RefundOperation.terminal_status
            == RefundOperationTerminalStatus.in_flight.value,
            RefundOperation.created_at < stale_in_flight_cutoff,
        )
        .order_by(RefundOperation.created_at)
        .limit(max_operations)
        .all()
    )
    for op in in_flight:
        new_status = reconcile_in_flight(db, op)
        if new_status == RefundOperationTerminalStatus.in_flight.value:
            summary["in_flight_transient"] += 1
        else:
            summary["in_flight_reconciled"] += 1

    # Accepted sweep.
    accepted = (
        db.query(RefundOperation)
        .filter(
            RefundOperation.terminal_status
            == RefundOperationTerminalStatus.accepted.value,
            RefundOperation.updated_at < stale_accepted_cutoff,
        )
        .order_by(RefundOperation.updated_at)
        .limit(max_operations)
        .all()
    )
    for op in accepted:
        new_status = reconcile_accepted(db, op)
        if new_status == RefundOperationTerminalStatus.accepted.value:
            summary["accepted_transient"] += 1
        else:
            summary["accepted_reconciled"] += 1

    return summary
