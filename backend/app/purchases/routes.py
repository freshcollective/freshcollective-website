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

Stage 3 additions:

  * ``GET /api/purchases/by-token`` — public read-only summary of an
    intent, keyed by the raw claim token. Used by ``/checkout/complete``
    to render the correct state without exposing internal IDs.
  * ``POST /api/purchases/claim`` — activates a paid intent for the
    currently-authenticated user. Requires a valid session cookie.
  * ``POST /api/purchases/claim-with-signup`` — creates a new account
    against the intent's ``claim_email`` and activates in the same
    transaction. Sets the session cookie on success.

All three claim endpoints delegate business logic to
``app.purchases.claim`` (kind-agnostic orchestration) and
``app.creator.plan_activation`` (Creator-plan-specific domain).
Webhook processing lives in ``app.webhooks.routes`` — this file
never receives Stripe events directly.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user, get_verified_current_user
from app.auth.routes import set_session_cookie
from app.auth import service as auth_service
from app.checkout.stripe_client import StripeNotConfiguredError, is_configured
from app.core.database import get_db
from app.creator.plan_activation import (
    ActivationConflictError,
    CreatorPlanActivationError,
)
from app.models.creator_billing import CreatorPlan
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.models.user import User
from app.purchases.checkout import (
    InvalidIntentStateError,
    MissingPricingError,
    UnknownPlanError,
    create_checkout_session_for_intent,
    create_creator_subscription_intent,
    missing_env_var_for_creator_plan,
)
from app.purchases.claim import (
    ClaimTokenExpiredError,
    IntentAlreadyConsumedByOtherUserError,
    IntentEmailMismatchError,
    IntentNotPaidError,
    InvalidClaimTokenError,
    UnsupportedIntentKindError,
    claim_intent,
    fetch_intent_by_raw_token,
    is_claim_token_expired,
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
# Shared helpers
# ---------------------------------------------------------------------------


def _schedule_activation_event_routing(
    background_tasks: BackgroundTasks,
    activation_event,
) -> None:
    """Wire the routing background task for a ``creator.plan_activated``
    event produced by ``claim_intent``. ``activation_event`` is ``None``
    when the claim was an idempotent replay (already-active on same
    plan) — nothing to route in that case.
    """
    if activation_event is None:
        return
    from app.comms.rollout import schedule_routing_if_needed
    schedule_routing_if_needed(
        background_tasks, activation_event, "creator.plan_activated",
    )


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


# ═══════════════════════════════════════════════════════════════════
# Stage 3 — Claim endpoints
# ═══════════════════════════════════════════════════════════════════


class PurchaseByTokenResponse(BaseModel):
    """Public, safe summary of an intent — sized to what the
    /checkout/complete page needs to decide which state to render.
    Does not expose ``payer_user_id`` or provider IDs."""
    status: str = Field(..., description="pending | paid | consumed | expired | cancelled | refunded")
    kind: str
    plan_slug: str | None = None
    plan_display_name: str | None = None
    claim_email: str | None = None
    claim_email_has_account: bool = False
    payer_bound: bool = Field(
        ...,
        description=(
            "True if the intent was created while a user was logged in "
            "(so activation should happen automatically via webhook, "
            "not via a claim flow)."
        ),
    )
    claim_token_expired: bool
    consumed_by_current_user: bool = False


class ClaimResponse(BaseModel):
    purchase_intent_id: str
    status: str
    next_url: str = Field(..., description="Where the frontend should send the visitor now.")


class ClaimTokenBody(BaseModel):
    token: str = Field(..., min_length=32)


class ClaimWithSignupBody(BaseModel):
    token: str = Field(..., min_length=32)
    name: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


_NEXT_URL_CREATOR_STUDIO = "/creator-studio"
_NEXT_URL_CREATOR_ONBOARDING = "/creator-onboarding"


def _resolve_next_url(intent: PurchaseIntent, user: User) -> str:
    """Decide where the frontend should send the visitor after
    activation, based on intent kind + this user's onboarding state.

    Keeping the decision server-side means adding new intent kinds
    (paid Pathway / Gathering / Collective membership in later
    stages) is a one-file edit rather than requiring every consumer
    to re-implement the routing.
    """
    if intent.kind == PurchaseIntentKind.creator_subscription:
        # Fresh Creators (and existing Members who just became
        # Creators) go through the short Creator welcome once.
        # Existing Creators — either those backfilled by migration
        # 096 or those who've already completed it — skip straight
        # to Creator Studio.
        if user.creator_onboarded_at is None:
            return _NEXT_URL_CREATOR_ONBOARDING
        return _NEXT_URL_CREATOR_STUDIO
    # Future kinds (Stage 5+): collective_membership → /spaces/{slug},
    # pathway → /spaces/{slug}/pathways/{slug}, gathering →
    # /spaces/{slug}/events/{id}. Until then, a safe fallback.
    return _NEXT_URL_CREATOR_STUDIO


@router.get(
    "/by-token",
    response_model=PurchaseByTokenResponse,
)
def get_purchase_by_token(
    token: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> PurchaseByTokenResponse:
    """Return a safe summary of the intent identified by ``token``.
    Public — no session required. Used by the /checkout/complete
    server component to pick the correct rendered state.

    Returns 404 for unknown tokens. Never reveals internal IDs.
    """
    try:
        intent = fetch_intent_by_raw_token(db, token)
    except InvalidClaimTokenError:
        raise HTTPException(status_code=404, detail="Unknown claim token.")

    plan_display_name: str | None = None
    if intent.plan_slug:
        plan = (
            db.query(CreatorPlan)
            .filter(CreatorPlan.slug == intent.plan_slug)
            .first()
        )
        if plan is not None:
            plan_display_name = plan.name

    claim_email_has_account = False
    if intent.claim_email:
        existing = auth_service.get_user_by_email(db, intent.claim_email)
        claim_email_has_account = existing is not None

    consumed_by_current_user = bool(
        current_user
        and intent.status == PurchaseIntentStatus.consumed
        and intent.consumed_by_user_id == current_user.id
    )

    return PurchaseByTokenResponse(
        status=intent.status.value,
        kind=intent.kind.value,
        plan_slug=intent.plan_slug,
        plan_display_name=plan_display_name,
        claim_email=intent.claim_email,
        claim_email_has_account=claim_email_has_account,
        payer_bound=intent.payer_user_id is not None,
        claim_token_expired=is_claim_token_expired(intent),
        consumed_by_current_user=consumed_by_current_user,
    )


@router.post("/claim", response_model=ClaimResponse)
def claim_purchase(
    body: ClaimTokenBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
) -> ClaimResponse:
    """Activate the intent for the currently-authenticated user.

    Preconditions enforced by the shared claim orchestrator:
      * token resolves to an intent (else 404)
      * intent is ``paid`` (else 409)
      * intent's claim_email matches the current user's email
        (else 403)

    Idempotent: replaying the request for the same user after
    activation returns the same success payload without side effects.
    """
    try:
        intent = fetch_intent_by_raw_token(db, body.token, for_update=True)
    except InvalidClaimTokenError:
        raise HTTPException(status_code=404, detail="Unknown claim token.")

    if is_claim_token_expired(intent) and intent.status != PurchaseIntentStatus.consumed:
        # Elapsed-and-not-yet-consumed. Intent stays ``paid`` per
        # Stage 1 invariant — this is a support-recoverable state.
        raise HTTPException(
            status_code=410,
            detail="Claim link has expired. Please contact support.",
        )

    try:
        claim_result = claim_intent(db, intent, current_user)
    except IntentNotPaidError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntentAlreadyConsumedByOtherUserError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntentEmailMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UnsupportedIntentKindError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ActivationConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CreatorPlanActivationError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.commit()
    _schedule_activation_event_routing(background_tasks, claim_result.activation_event)
    return ClaimResponse(
        purchase_intent_id=intent.id,
        status=intent.status.value,
        next_url=_resolve_next_url(intent, current_user),
    )


@router.post("/claim-with-signup", response_model=ClaimResponse)
def claim_with_signup(
    body: ClaimWithSignupBody,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> ClaimResponse:
    """Create a Fresh Collective account against the intent's
    ``claim_email`` and activate the intent in the same transaction.
    Sets the ``fc_session`` cookie on success.

    * Refuses when a session is already active — returning visitors
      use ``POST /claim`` instead.
    * Refuses when no ``claim_email`` is set on the intent (webhook
      hasn't fired yet; the frontend should render 'waiting').
    * Refuses when an account already exists for ``claim_email``
      (the frontend should redirect the visitor to sign in and then
      call /claim).
    * Refuses when the claim token has expired.

    Idempotency: a repeat POST for the *same* email after the account
    exists will return 409; the frontend then flips to the "sign in"
    state. There is no window where an orphan account could be
    created — user creation and activation share a transaction, and
    any activation failure rolls the User row back.
    """
    if current_user is not None:
        raise HTTPException(
            status_code=409,
            detail="You are already signed in. Use POST /claim instead.",
        )

    try:
        intent = fetch_intent_by_raw_token(db, body.token, for_update=True)
    except InvalidClaimTokenError:
        raise HTTPException(status_code=404, detail="Unknown claim token.")

    if is_claim_token_expired(intent):
        raise HTTPException(
            status_code=410,
            detail="Claim link has expired. Please contact support.",
        )
    if intent.status != PurchaseIntentStatus.paid:
        raise HTTPException(
            status_code=409,
            detail=(
                "This purchase is not yet confirmed as paid. Please "
                "wait a moment and try again."
            ),
        )
    if not intent.claim_email:
        raise HTTPException(
            status_code=409,
            detail=(
                "Payment has been received but Stripe has not yet "
                "delivered the payer's email. Please wait a moment "
                "and try again."
            ),
        )

    email = intent.claim_email.strip().lower()
    if auth_service.get_user_by_email(db, email) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "An account already exists for this email. Please sign "
                "in and try again."
            ),
        )

    # `create_user` commits the account. Any activation failure below
    # therefore leaves the User row in place — that's pre-existing
    # behaviour, not introduced by R2B.
    new_user = auth_service.create_user(db, body.name, email, body.password)

    # SEC-009 — new account starts unverified. Send the single
    # verification/welcome email; the existing welcome-after-signup
    # fires post-verify (in the /verify-email route), matching the
    # standalone signup lifecycle so purchase-path accounts don't get
    # two consecutive greetings.
    raw = auth_service.create_email_verification_token(db, new_user)
    if raw:
        auth_service.emit_email_verification_requested(
            db, new_user, raw, background_tasks=background_tasks,
        )
    else:
        db.commit()

    try:
        claim_result = claim_intent(db, intent, new_user)
    except (
        IntentNotPaidError,
        IntentAlreadyConsumedByOtherUserError,
        IntentEmailMismatchError,
        UnsupportedIntentKindError,
        ActivationConflictError,
        CreatorPlanActivationError,
    ) as exc:
        db.rollback()  # rolls back the claim work; the User row from
        # ``create_user`` stayed committed (its own transaction).
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    _schedule_activation_event_routing(background_tasks, claim_result.activation_event)

    # Open a session for the freshly-created account.
    token = auth_service.create_session_token(new_user)
    set_session_cookie(response, token)

    return ClaimResponse(
        purchase_intent_id=intent.id,
        status=intent.status.value,
        next_url=_resolve_next_url(intent, new_user),
    )
