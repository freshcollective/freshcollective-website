"""FIP4B2 — member repair endpoint for a finite payment plan.

Deliberately small: one authenticated POST that opens a Stripe
Checkout Session in ``mode='setup'`` bound to the plan's existing
Customer. The completion webhook does the domain work (swap the
default PaymentMethod on all three surfaces, retry the overdue
invoice, let the existing FIP3 ``invoice.payment_succeeded``
pipeline restore access).

Ownership guarantee
-------------------
The caller passes a ``plan_id``. The endpoint re-loads that plan
under the authenticated user session and refuses if:

* the plan does not exist
* the plan belongs to a different member
* the plan is not in a recoverable state (payment_problem / suspended)
* the plan has no provider identifiers to repair
  (Customer / SubscriptionSchedule / Subscription / last_failed_invoice_id)

The webhook completion handler ALSO re-validates ownership + state
using metadata sent from the server — never trusting the metadata
in isolation. See :mod:`app.webhooks.finite_plan_handlers`.
"""

from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services import finite_plan_repair


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/finite-plan", tags=["finite-plan"])


class RepairSessionRequest(BaseModel):
    """Body of ``POST /api/finite-plan/repair-session``."""

    plan_id: str = Field(
        ...,
        description=(
            "PurchasePlan id (from ``MemberPlanState.id``). "
            "Backend re-validates the authenticated member owns this "
            "plan and that the plan is in a recoverable state."
        ),
        min_length=1,
        max_length=64,
    )


class RepairSessionResponse(BaseModel):
    checkout_url: str = Field(
        ..., description="Stripe-hosted URL. Redirect the browser here."
    )
    session_id: str


_RECOVERABLE = (
    PurchasePlanStatus.payment_problem,
    PurchasePlanStatus.suspended,
)


@router.post("/repair-session", response_model=RepairSessionResponse)
def create_repair_session(
    body: RepairSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RepairSessionResponse:
    """Open a Stripe repair setup Session for a plan the caller owns."""
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured on this server.",
        )

    plan = (
        db.query(PurchasePlan)
        .filter(PurchasePlan.id == body.plan_id)
        .one_or_none()
    )

    # Do NOT distinguish "not found" from "not yours" — a stable 404
    # regardless of which case denies the caller information about
    # plan ids they don't own.
    if plan is None or plan.member_user_id != current_user.id:
        raise HTTPException(
            status_code=404,
            detail="Payment plan not found.",
        )

    if plan.status not in _RECOVERABLE:
        raise HTTPException(
            status_code=409,
            detail=(
                "This payment plan does not need attention right now. "
                "Please refresh and try again."
            ),
        )

    # These provider identifiers are all populated by the FIP2 setup
    # webhook long before a plan can reach payment_problem/suspended,
    # but we assert them here as a hard precondition so a repair
    # attempt against a genuinely incomplete plan raises a 409
    # rather than a 500 from deep inside Stripe.
    if not plan.provider_customer_id:
        raise HTTPException(
            status_code=409,
            detail="Payment plan is not ready to be repaired.",
        )
    if not plan.provider_subscription_id or not plan.provider_subscription_schedule_id:
        raise HTTPException(
            status_code=409,
            detail="Payment plan is not ready to be repaired.",
        )
    if not plan.last_failed_invoice_id:
        # A suspended / payment_problem plan without a
        # last_failed_invoice_id is a data invariant violation
        # (FIP3 always populates it on the failure that opens the
        # window). Refuse rather than silently opening a repair
        # Session with nothing to retry.
        logger.error(
            "FIP4B2 repair: plan=%s in status=%s but last_failed_invoice_id "
            "is NULL — refusing repair.",
            plan.id, plan.status.value,
        )
        raise HTTPException(
            status_code=409,
            detail="Payment plan is not ready to be repaired.",
        )

    frontend = settings.frontend_origin.rstrip("/")
    success_url = f"{frontend}/checkout/repair-return?plan_id={plan.id}"
    cancel_url = f"{frontend}/dashboard"

    try:
        session = finite_plan_repair.create_repair_setup_session(
            plan=plan,
            member_email=current_user.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except stripe.StripeError as exc:
        logger.error(
            "FIP4B2 repair: Stripe setup Session creation failed for "
            "plan=%s user=%s: %s",
            plan.id, current_user.id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "We couldn't open the payment repair flow right now. "
                "Please try again in a moment."
            ),
        )

    logger.info(
        "FIP4B2 repair: opened setup Session=%s for plan=%s user=%s status=%s",
        session.id, plan.id, current_user.id, plan.status.value,
    )
    return RepairSessionResponse(
        checkout_url=session.url,
        session_id=session.id,
    )
