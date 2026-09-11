"""Creator-authorised finite payment plan cancellation.

``POST /api/creator/purchase-plans/{plan_id}/cancel``

Parallel to the admin endpoint at
``POST /api/admin/purchase-plans/{plan_id}/cancel``. Both endpoints
delegate to the same coordinated orchestrator,
:func:`app.services.finite_plan_lifecycle.cancel_plan_by_admin`.

Authorization: creator-owner-of-plan.space_id OR admin. Cross-Collective
attempts return 404 (existence not leaked).

Refunds are intentionally separate — cancellation stops future
instalments and suspends plan-owned access + future bookings, but
does NOT refund past instalments. Members needing a refund of a paid
instalment go through the refund endpoint.
"""

from __future__ import annotations

import logging
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.models.purchase_plan import PurchasePlan
from app.models.user import User
from app.services import finite_plan_lifecycle as fpl


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/creator", tags=["creator", "purchase-plans"])


class CancelPlanRequest(BaseModel):
    reason: str = Field(default="creator_cancelled", max_length=120)
    note: str | None = Field(default=None, max_length=250)


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


def _can_creator_act_on_space(user: User, space_id: str, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role != "creator":
        return False
    owned = db.execute(
        text("SELECT 1 FROM spaces WHERE id = :sid AND creator_id = :uid"),
        {"sid": space_id, "uid": user.id},
    ).first()
    return owned is not None


@router.post(
    "/purchase-plans/{plan_id}/cancel",
    response_model=CancelPlanResponse,
)
def creator_cancel_purchase_plan(
    plan_id: str,
    body: CancelPlanRequest,
    current_user: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> CancelPlanResponse:
    plan: PurchasePlan | None = (
        db.query(PurchasePlan)
        .filter(PurchasePlan.id == plan_id)
        .with_for_update()
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Payment plan not found.")

    if not _can_creator_act_on_space(current_user, plan.space_id, db):
        # Cross-Collective — 404 not 403 (existence not leaked).
        raise HTTPException(status_code=404, detail="Payment plan not found.")

    now = datetime.utcnow()
    try:
        outcome = fpl.cancel_plan_by_admin(
            db,
            plan=plan,
            admin_user_id=current_user.id,
            reason=(body.reason or "creator_cancelled").strip() or "creator_cancelled",
            note=(body.note or None),
            now=now,
        )
    except stripe.StripeError as exc:
        logger.error(
            "creator cancel plan: Stripe error plan=%s actor=%s: %s",
            plan.id, current_user.id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Stripe schedule cancel failed; retry the request.",
        )

    db.commit()

    if outcome.comms_event is not None:
        from app.comms.rollout import schedule_routing_if_needed
        schedule_routing_if_needed(
            None, outcome.comms_event, "access.suspended",
        )

    logger.info(
        "creator cancel plan: plan=%s actor=%s role=%s reason=%r "
        "transitioned=%s cancelled_bookings=%d agr_revoked=%d",
        plan.id, current_user.id, current_user.role,
        body.reason, outcome.plan_transitioned,
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
