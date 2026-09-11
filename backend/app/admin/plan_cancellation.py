"""Admin plan-cancellation endpoint for finite payment plans.

Wraps :func:`app.services.finite_plan_lifecycle.cancel_plan_by_admin`
in a thin HTTP layer:

* admin-only via ``get_admin_user``;
* row-locks the plan under ``SELECT … FOR UPDATE``;
* propagates Stripe-side transient errors as 502 so the operator can
  retry rather than seeing a false 200;
* returns the ``PlanCancellationOutcome`` fields so the caller can
  distinguish "we transitioned the plan" from "we converged an already-
  cancelled plan".

Refunds are intentionally NOT triggered. The cancel stops future
instalments and revokes plan-owned access + future bookings; refunds
of already-paid instalments flow through the operator's Stripe
Dashboard action and the ``charge.refunded`` webhook.
"""

from __future__ import annotations

import logging
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.purchase_plan import PurchasePlan
from app.models.user import User
from app.services import finite_plan_lifecycle as fpl


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CancelPlanRequest(BaseModel):
    reason: str = Field(
        default="admin_cancelled",
        max_length=120,
        description="Short slug/label — stored on plan.cancelled_reason.",
    )
    note: str | None = Field(
        default=None,
        max_length=250,
        description="Optional free-text note appended to plan.cancelled_reason.",
    )


class CancelPlanResponse(BaseModel):
    purchase_plan_id: str
    plan_status: str
    plan_transitioned: bool
    suspended_entitlement_ids: list[str]
    suspended_access_pass_ids: list[str]
    preserved_entitlement_ids: list[str]
    preserved_access_pass_ids: list[str]
    cancelled_booking_ids: list[str]
    grant_records_revoked: int


@router.post(
    "/purchase-plans/{plan_id}/cancel",
    response_model=CancelPlanResponse,
)
def cancel_purchase_plan_admin(
    plan_id: str,
    body: CancelPlanRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CancelPlanResponse:
    """Cancel a finite payment plan.

    * Stops future Stripe instalments (SubscriptionSchedule cancel).
    * Marks the plan cancelled with admin actor + reason.
    * Suspends plan-owned access (source-aware — overlapping active
      access from another source is preserved).
    * Releases future confirmed plan-dependent bookings; per-booking
      overlap check preserves bookings still authorised by another
      qualifying pass without restoring the plan-pass credit.
    * Idempotent: a second call on an already-cancelled plan still
      converges any incomplete access/booking/AGR cleanup left by a
      prior partial run.

    Errors:
      * 404 — no such plan.
      * 502 — Stripe transient error during schedule cancel; retry.
    """
    plan: PurchasePlan | None = (
        db.query(PurchasePlan)
        .filter(PurchasePlan.id == plan_id)
        .with_for_update()
        .first()
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase plan not found.",
        )

    now = datetime.utcnow()
    try:
        outcome = fpl.cancel_plan_by_admin(
            db,
            plan=plan,
            admin_user_id=admin.id,
            reason=(body.reason or "admin_cancelled").strip() or "admin_cancelled",
            note=(body.note or None),
            now=now,
        )
    except stripe.StripeError as exc:
        # Provider-side transient — surface as 502 so the operator
        # retries. The local DB is untouched because
        # ``cancel_finite_subscription_schedule`` runs first and any
        # error propagates before we mutate plan/access/bookings.
        logger.error(
            "admin cancel plan: Stripe error plan=%s admin=%s: %s",
            plan.id, admin.id, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe schedule cancel failed; retry the request.",
        )

    db.commit()

    # R3 — dispatch "access paused" comms after commit when the call
    # genuinely suspended access. On a convergence call that produced
    # no state change, no email is sent.
    if outcome.comms_event is not None:
        from app.comms.rollout import schedule_routing_if_needed
        schedule_routing_if_needed(
            None, outcome.comms_event, "access.suspended",
        )

    logger.info(
        "admin cancel plan: plan=%s admin=%s reason=%r transitioned=%s "
        "cancelled_bookings=%d agr_revoked=%d",
        plan.id, admin.id, body.reason, outcome.plan_transitioned,
        len(outcome.cancelled_booking_ids),
        outcome.grant_records_revoked,
    )

    return CancelPlanResponse(
        purchase_plan_id=plan.id,
        plan_status=plan.status.value,
        plan_transitioned=outcome.plan_transitioned,
        suspended_entitlement_ids=outcome.suspended_entitlement_ids,
        suspended_access_pass_ids=outcome.suspended_access_pass_ids,
        preserved_entitlement_ids=outcome.preserved_entitlement_ids,
        preserved_access_pass_ids=outcome.preserved_access_pass_ids,
        cancelled_booking_ids=outcome.cancelled_booking_ids,
        grant_records_revoked=outcome.grant_records_revoked,
    )
