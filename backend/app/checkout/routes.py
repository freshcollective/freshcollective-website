"""
POST /api/checkout/pathway — create a Stripe Checkout Session for a paid pathway.

Flow:
  1. Validate pathway exists, is active, is one_time, has a price.
  2. Check the member does not already have an active entitlement.
  3. Resolve the creator's platform fee rate from their active plan.
  4. Pre-generate a transaction UUID.
  5. Create the Stripe Checkout Session (no DB writes yet, so nothing to undo on failure).
  6. Create the pending PaymentTransaction with provider_checkout_session_id already
     set — single atomic commit.
  7. Return the Stripe-hosted checkout_url for the frontend to redirect to.

Access is NOT granted here — it is granted by the webhook handler when
Stripe confirms the payment via checkout.session.completed.
"""

import logging
from datetime import datetime
from uuid import uuid4

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.checkout.schemas import PathwayCheckoutRequest, PathwayCheckoutResponse
from app.core.config import settings
from app.core.database import get_db
from app.models.creator_billing import CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    Space,
    SpaceMembership,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkout", tags=["checkout"])

# Default fee rate (Basic plan 8%) used when creator has no active subscription
_DEFAULT_FEE_BPS = 800


def _resolve_fee_bps(creator_id: str | None, db: Session) -> tuple[int, str | None, str | None]:
    """
    Return (fee_bps, creator_plan_id, creator_subscription_id) for the creator.

    Uses the creator's active CreatorSubscription → CreatorPlan.
    Falls back to the cheapest active plan, then to the hardcoded default (800 = 8%).
    """
    if not creator_id:
        return _DEFAULT_FEE_BPS, None, None

    sub = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == creator_id,
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
            ]),
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if sub:
        plan = db.query(CreatorPlan).filter(CreatorPlan.id == sub.creator_plan_id).first()
        if plan:
            return plan.transaction_fee_basis_points, plan.id, sub.id

    # Creator has no active plan — use the cheapest active plan's rate as fallback
    fallback = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    if fallback:
        return fallback.transaction_fee_basis_points, None, None

    return _DEFAULT_FEE_BPS, None, None


@router.post("/pathway", response_model=PathwayCheckoutResponse)
def create_pathway_checkout_session(
    body: PathwayCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PathwayCheckoutResponse:
    """
    Create a Stripe Checkout Session for a one-time pathway purchase.

    Returns { checkout_url } for the frontend to redirect to.
    Access is granted by the webhook after payment confirmation.
    """
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured on this server.",
        )

    stripe.api_key = settings.stripe_secret_key

    # --- Pathway validation --------------------------------------------------
    pathway = db.query(Pathway).filter(Pathway.id == body.pathway_id).first()
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")

    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    if p_status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Pathway is not available for purchase (status: {p_status}).",
        )

    access_type = (
        pathway.access_type.value
        if hasattr(pathway.access_type, "value")
        else str(pathway.access_type or "free")
    )
    if access_type != "one_time":
        raise HTTPException(
            status_code=400,
            detail="Only one-time purchase pathways can be checked out via this endpoint.",
        )

    if not pathway.price_cents or pathway.price_cents <= 0:
        raise HTTPException(status_code=400, detail="Pathway has no valid price.")

    # --- Space ---------------------------------------------------------------
    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Collective not found.")

    # --- Duplicate entitlement guard ----------------------------------------
    existing = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == current_user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="You already have access to this pathway.",
        )

    # --- Resolve creator and fee rate ----------------------------------------
    creator_id: str | None = space.creator_id
    if creator_id is None:
        mem = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.role == "creator",
                SpaceMembership.status == "active",
            )
            .first()
        )
        creator_id = mem.user_id if mem else None

    fee_bps, creator_plan_id, creator_sub_id = _resolve_fee_bps(creator_id, db)

    # --- Fee calculation (all calculations done before any Stripe call) ------
    gross = pathway.price_cents
    currency = (pathway.currency or "AUD").upper()
    platform_fee = round(gross * fee_bps / 10000)
    net_creator = gross - platform_fee

    # --- Pre-generate transaction ID -----------------------------------------
    # We generate the ID here so it can be embedded in Stripe metadata before
    # the DB row is created. This allows the webhook to find the transaction
    # even if the DB commit races with the Stripe call.
    txn_id = str(uuid4())

    # --- Create Stripe Checkout Session (no DB writes yet) -------------------
    # Creating the session before any DB writes means there is nothing to roll
    # back if Stripe fails. If Stripe succeeds but the DB commit fails below,
    # the session will exist in Stripe but have no corresponding record here —
    # this is logged and the webhook will handle it gracefully by logging an
    # error (no duplicate entitlements, no money moved until paid).
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {
                            "name": pathway.title,
                            "description": f"{space.name} — Fresh Collective",
                        },
                        "unit_amount": gross,
                    },
                    "quantity": 1,
                }
            ],
            # Metadata on the Checkout Session — used by checkout.session.completed
            metadata={
                "transaction_id": txn_id,
                "pathway_id": pathway.id,
                "space_id": space.id,
                "payer_user_id": current_user.id,
                "creator_user_id": creator_id or "",
                "platform_fee_bps": str(fee_bps),
                "creator_plan_id": creator_plan_id or "",
            },
            # Metadata mirrored onto the PaymentIntent — used by payment_intent.payment_failed
            payment_intent_data={
                "metadata": {
                    "transaction_id": txn_id,
                    "pathway_id": pathway.id,
                    "payer_user_id": current_user.id,
                }
            },
            customer_email=current_user.email,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except stripe.StripeError as exc:
        logger.error("Stripe session creation failed for pathway=%s user=%s: %s", pathway.id, current_user.id, exc)
        raise HTTPException(
            status_code=502,
            detail="Failed to create checkout session. Please try again.",
        )

    # --- Create pending PaymentTransaction with session ID already set -------
    # Single atomic commit: the transaction row is complete from the start.
    # The unique index on provider_checkout_session_id prevents duplicates.
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=txn_id,
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.pending,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=current_user.id,
        creator_user_id=creator_id,
        space_id=space.id,
        pathway_id=pathway.id,
        creator_plan_id=creator_plan_id,
        creator_subscription_id=creator_sub_id,
        currency=currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=platform_fee,
        provider_checkout_session_id=session.id,
        payout_status=PayoutStatus.pending,
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.commit()

    logger.info(
        "Checkout session created: txn=%s session=%s pathway=%s user=%s fee_bps=%s",
        txn_id, session.id, pathway.id, current_user.id, fee_bps,
    )

    return PathwayCheckoutResponse(checkout_url=session.url)
