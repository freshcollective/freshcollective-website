"""
Stage 2 — Purchase-checkout HTTP routes.

Deliberately small: one endpoint that atomically creates a
``PurchaseIntent`` for a Creator subscription and its Stripe Checkout
Session. Business logic lives in ``app.purchases.checkout`` — this
file is pure HTTP glue.

Ordering invariant
------------------

The following order is enforced at the route layer and is essential
to the "no orphan intents" guarantee:

    1. Validate the request body (plan slug schema).
    2. Confirm Stripe SDK is configured for this environment.
    3. Confirm the Stripe Price ID for the requested plan is set.
    4. Only then: create + persist the PurchaseIntent.
    5. Create the Stripe Checkout Session.
    6. Save the Checkout Session ID onto the intent.
    7. Commit.

If any of steps 1–3 fail, the response is a structured 503 (or 422
for schema errors) and no PurchaseIntent row is written. If step 5
fails, the DB transaction is rolled back explicitly so the pending
intent from step 4 does not persist as an orphan.

What this file explicitly does NOT do (belongs to later stages):
  * consume PurchaseIntents
  * process Stripe webhooks
  * create accounts
  * grant Creator capability / entitlements
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.checkout.stripe_client import StripeNotConfiguredError, is_configured
from app.core.database import get_db
from app.models.user import User
from app.purchases.checkout import (
    InvalidIntentStateError,
    MissingPricingError,
    UnknownPlanError,
    create_checkout_session_for_intent,
    create_creator_subscription_intent,
    missing_env_var_for_creator_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/purchases", tags=["purchases"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreatorSubscriptionCheckoutRequest(BaseModel):
    """Body of ``POST /api/purchases/creator-subscription``.

    Only the plan slug is accepted — pricing, currency, fee rate and
    Stripe Price ID are all resolved server-side from the intent and
    the plan configuration. The client cannot influence what will be
    charged.
    """
    plan_slug: Literal["creator", "pro"] = Field(
        ...,
        description=(
            "Backend plan slug. `community` is free and has its own "
            "activation path — not accepted here. `pro` corresponds to "
            "the public 'Creator Portfolio' plan."
        ),
    )


class CheckoutSessionCreatedResponse(BaseModel):
    """Success payload for a created Session."""
    checkout_url: str = Field(
        ..., description="Stripe-hosted URL. Redirect the browser here."
    )
    purchase_intent_id: str
    provider_checkout_session_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/creator-subscription",
    response_model=CheckoutSessionCreatedResponse,
)
def create_creator_subscription_checkout(
    body: CreatorSubscriptionCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
) -> CheckoutSessionCreatedResponse:
    """Create a PurchaseIntent for a Creator plan and return the
    Stripe Checkout Session URL.

    * Auth is optional — brand-new visitors can purchase before an
      account exists (the account is created in a later stage after
      the webhook confirms payment).
    * Returns a structured 503 (see :func:`_unavailable_response`)
      when Stripe is not wired for this environment or the requested
      plan has no Price ID configured. No PurchaseIntent is created
      in either case.
    * Returns 502 on any Stripe SDK error after preflight; the
      pending PurchaseIntent that was written before the SDK call is
      explicitly rolled back so no orphan row is left behind.
    """
    # Preflight step 1: Stripe SDK configured at all?
    # Body is *only* a structured reason code. Frontend owns copy so
    # no operator-authored English leaks to the visitor.
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "stripe_not_configured",
                "would_create": {
                    "kind": "creator_subscription",
                    "plan_slug": body.plan_slug,
                },
            },
        )

    # Preflight step 2: Stripe Price ID present for the requested plan?
    # ``missing_env_var_for_creator_plan`` is a pure function — no DB
    # touch — so a missing configuration cannot leave a PurchaseIntent
    # row behind.
    missing_var = missing_env_var_for_creator_plan(body.plan_slug)
    if missing_var is not None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "price_id_not_configured",
                # Included so the frontend can render a dev-mode
                # supplementary line ("Missing STRIPE_PRICE_ID_CREATOR").
                # Production frontends hide this field entirely.
                "missing_env_var": missing_var,
                "would_create": {
                    "kind": "creator_subscription",
                    "plan_slug": body.plan_slug,
                },
            },
        )

    # From here on, we begin touching the database. Any failure below
    # must roll back to avoid an orphan pending intent.
    payer_user_id = current_user.id if current_user else None
    customer_email = current_user.email if current_user else None

    try:
        intent = create_creator_subscription_intent(
            db, plan_slug=body.plan_slug, payer_user_id=payer_user_id
        )
        result = create_checkout_session_for_intent(
            db, intent, customer_email=customer_email
        )
    except UnknownPlanError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingPricingError as exc:
        # Defensive: preflight above should have caught this. If a race
        # cleared the env var between preflight and here, we still
        # rollback and surface the same structured 503.
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "price_id_not_configured",
                "missing_env_var": missing_env_var_for_creator_plan(body.plan_slug),
                "would_create": {
                    "kind": "creator_subscription",
                    "plan_slug": body.plan_slug,
                },
            },
        ) from exc
    except InvalidIntentStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StripeNotConfiguredError as exc:
        # Defensive belt-and-braces (preflight should have handled it).
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "stripe_not_configured",
                "would_create": {
                    "kind": "creator_subscription",
                    "plan_slug": body.plan_slug,
                },
            },
        ) from exc
    except stripe.StripeError as exc:
        # Explicit rollback so the PurchaseIntent that was persisted
        # in ``create_creator_subscription_intent`` above does not
        # survive as an orphaned pending row.
        db.rollback()
        logger.exception(
            "Stripe Session creation failed (plan=%s user=%s): %s",
            body.plan_slug,
            payer_user_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Stripe rejected the Checkout Session request.",
        ) from exc

    # Persist the intent + session ID together.
    db.commit()

    logger.info(
        "Creator subscription checkout session created "
        "intent=%s session=%s plan=%s user=%s",
        result.purchase_intent_id,
        result.provider_checkout_session_id,
        body.plan_slug,
        payer_user_id,
    )
    return CheckoutSessionCreatedResponse(
        checkout_url=result.checkout_url,
        purchase_intent_id=result.purchase_intent_id,
        provider_checkout_session_id=result.provider_checkout_session_id,
    )
