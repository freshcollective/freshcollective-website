"""
Stage 2 — Purchase-checkout service.

Turns a ``PurchaseIntent`` into a Stripe Checkout Session and records
the resulting Session ID on the intent. Business logic *only* — no
route wiring lives here; no consumption, no webhook handling, no
entitlement grants. Later stages consume the intent when Stripe
confirms payment via the webhook.

Design invariants
-----------------

  * The intent is the *source of truth* for what is being purchased.
    Nothing about the plan / space / pathway / event is taken from URL
    parameters at Session-creation time — only from the intent row.
  * The intent's ``status`` stays ``pending`` throughout this stage.
    Only the eventual webhook may promote it to ``paid``.
  * The claim token is generated *before* Stripe Checkout Session
    creation so it can be embedded in ``success_url``. We store only
    the SHA-256 hash; the raw token appears once, in the URL.
  * If Stripe is not configured we raise
    ``StripeNotConfiguredError`` — never a fake success.

Exposed API (used by the route module in the same package):

  * ``create_creator_subscription_intent`` — builds + persists a
    pending intent for a Creator plan.
  * ``create_collective_membership_intent`` — same for a paid
    Collective (Stage 5 will wire the frontend; Stage 2 leaves the
    scaffold in place so we don't have to re-plumb the service later).
  * ``create_checkout_session_for_intent`` — validates a pending
    intent, snapshots pricing, generates a claim token, calls Stripe,
    persists the resulting Session / Customer IDs on the intent, and
    returns the hosted checkout URL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import stripe
from sqlalchemy.orm import Session

from app.checkout.stripe_client import StripeNotConfiguredError, get_stripe
from app.core.config import settings
from app.models.creator_billing import CreatorPlan
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.purchases.service import (
    build_intent,
    generate_claim_token,
    hash_claim_token,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config: how long a claim token stays valid after payment
# ---------------------------------------------------------------------------
# Kept module-level (not a settings.env var) because it is a UX-of-recovery
# choice, not an environment-specific secret. 24 hours gives a fresh
# purchaser a full day to reach the account-creation screen without
# forcing them to request a support-mediated re-issue.
CLAIM_TOKEN_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PurchaseCheckoutError(RuntimeError):
    """Base class for user-facing purchase-checkout failures. Routes
    translate concrete subclasses into their own HTTP status."""


class InvalidIntentStateError(PurchaseCheckoutError):
    """The intent is not in a state that permits Session creation."""


class MissingPricingError(PurchaseCheckoutError):
    """The Stripe configuration doesn't have a Price ID for this
    subject (e.g. STRIPE_PRICE_ID_CREATOR is unset)."""


class UnknownPlanError(PurchaseCheckoutError):
    """Requested plan slug is not one of the recognised backend slugs."""


# ---------------------------------------------------------------------------
# Plan → Stripe Price ID resolution
# ---------------------------------------------------------------------------
# Only recurring plans are resolvable here. The `community` plan is free
# and has its own Stage-3 activation path — it never reaches Stripe.
_RECURRING_PLAN_SLUGS: set[str] = {"creator", "pro"}


def _resolve_creator_plan_price_id(plan_slug: str) -> str:
    """Return the configured Stripe Price ID for a billable plan.

    Callers should prefer :func:`missing_env_var_for_creator_plan` for
    preflight (to avoid touching the DB before Stripe is known to be
    fully configured). This function is retained for defensive checks
    inside the Session-creation path.
    """
    if plan_slug == "creator":
        price_id = settings.stripe_price_id_creator
    elif plan_slug == "pro":
        price_id = settings.stripe_price_id_pro
    else:
        raise UnknownPlanError(
            f"No Stripe Price is configured for plan '{plan_slug}'. "
            "Only 'creator' and 'pro' are billable via Stripe today."
        )
    if not price_id:
        # Detail text kept operator-oriented — callers translate to a
        # user-facing message. The route preflight normally returns a
        # structured 503 before this code is reached.
        raise MissingPricingError(
            f"Stripe Price ID for plan '{plan_slug}' is not set."
        )
    return price_id


# Pure preflight helper: no DB, no Stripe call. Used by the route to
# check that the requested plan is fully configured *before* any
# PurchaseIntent row is written. Returns the missing env-var name so
# the frontend can surface it in development mode; returns None when
# fully configured.
def missing_env_var_for_creator_plan(plan_slug: str) -> str | None:
    if plan_slug == "creator":
        return None if settings.stripe_price_id_creator else "STRIPE_PRICE_ID_CREATOR"
    if plan_slug == "pro":
        return None if settings.stripe_price_id_pro else "STRIPE_PRICE_ID_PRO"
    return None


def _load_creator_plan(db: Session, plan_slug: str) -> CreatorPlan:
    """Look up the CreatorPlan by slug for the fee-basis-points snapshot.
    The plan row is a small, cached-in-DB source of truth; it does not
    hold Stripe IDs."""
    plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.slug == plan_slug, CreatorPlan.is_active.is_(True))
        .first()
    )
    if plan is None:
        raise UnknownPlanError(
            f"CreatorPlan '{plan_slug}' is not present or not active."
        )
    return plan


# ---------------------------------------------------------------------------
# Intent construction (Stage 2 entry points from the route layer)
# ---------------------------------------------------------------------------


def create_creator_subscription_intent(
    db: Session,
    *,
    plan_slug: str,
    payer_user_id: str | None,
) -> PurchaseIntent:
    """Create + persist a pending PurchaseIntent for a Creator
    subscription. Does not touch Stripe."""
    if plan_slug not in _RECURRING_PLAN_SLUGS:
        raise UnknownPlanError(
            f"Plan '{plan_slug}' is not a recurring Stripe-billable plan."
        )
    intent = build_intent(
        kind=PurchaseIntentKind.creator_subscription,
        plan_slug=plan_slug,
        payer_user_id=payer_user_id,
    )
    db.add(intent)
    db.flush()
    return intent


def create_collective_membership_intent(
    db: Session,
    *,
    space_id: str,
    payer_user_id: str | None,
) -> PurchaseIntent:
    """Create + persist a pending PurchaseIntent for a paid Collective
    membership. Scaffolded now so the one-time Session code path exists
    end-to-end; the frontend wiring lands in a later stage."""
    intent = build_intent(
        kind=PurchaseIntentKind.collective_membership,
        space_id=space_id,
        payer_user_id=payer_user_id,
    )
    db.add(intent)
    db.flush()
    return intent


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckoutSessionResult:
    """What the route hands back to the caller. Kept as a dataclass
    (not a Pydantic model) because the schema is defined in
    ``purchases/schemas.py`` and this dataclass is the internal
    boundary between service and route."""
    checkout_url: str
    provider_checkout_session_id: str
    purchase_intent_id: str


def create_checkout_session_for_intent(
    db: Session,
    intent: PurchaseIntent,
    *,
    customer_email: str | None = None,
) -> CheckoutSessionResult:
    """Validate the intent, generate a claim token, create the Stripe
    Checkout Session, and persist provider IDs on the intent.

    Raises:
      * :class:`StripeNotConfiguredError`  — Stripe not wired here.
      * :class:`InvalidIntentStateError`   — intent is not pending / has
                                            already been used.
      * :class:`MissingPricingError`       — Stripe Price ID unset.
      * :class:`UnknownPlanError`          — unrecognised plan slug.
      * ``stripe.StripeError``             — the SDK failed.

    Returns the hosted Checkout URL, the Stripe Session ID (also stored
    on the intent), and the PurchaseIntent ID for the caller's own logs
    or response body.
    """
    _validate_pending_intent(intent)

    # Discipline: refuse to re-use a Session already generated for
    # this intent. If the caller wants to retry, cancel the old intent
    # and create a new one (Stage 3 territory).
    if intent.provider_checkout_session_id:
        raise InvalidIntentStateError(
            "This purchase already has a Checkout Session — refusing "
            "to overwrite it."
        )

    # Sets ``stripe.api_key`` for the request. The service uses the
    # module-level ``stripe`` symbol imported at the top of this file
    # (so ``except stripe.StripeError`` binds to the real SDK
    # exception class rather than any monkeypatched replacement).
    get_stripe()  # may raise StripeNotConfiguredError

    session_args = _build_session_args(db, intent)

    # Claim token: raw once, hash persisted. Success URL embeds the
    # raw token so the future /checkout/complete handler can locate
    # the intent without exposing an internal ID.
    raw_token = generate_claim_token()
    token_hash = hash_claim_token(raw_token)
    intent.claim_token_hash = token_hash
    intent.claim_token_expires_at = datetime.utcnow() + timedelta(
        hours=CLAIM_TOKEN_TTL_HOURS
    )

    # Bake URLs after token generation so they contain the raw token.
    session_args["success_url"] = _build_success_url(raw_token)
    session_args["cancel_url"] = _build_cancel_url(intent)
    if customer_email:
        session_args["customer_email"] = customer_email

    # Idempotency key: seed with the intent id so an accidental retry
    # of the same POST doesn't create a second Session for the same
    # purchase journey.
    idem_key = f"purchase_intent:{intent.id}:session:v1"

    try:
        session = stripe.checkout.Session.create(
            **session_args,
            idempotency_key=idem_key,
        )
    except stripe.StripeError:
        # Do not persist provider IDs on the intent — leave the token
        # hash set so a subsequent retry can regenerate a fresh token
        # without racing this one. The caller (route) surfaces a 502.
        logger.exception(
            "Stripe Session creation failed for intent=%s kind=%s",
            intent.id, intent.kind.value,
        )
        raise

    intent.provider_checkout_session_id = session.id
    # Stripe may not have created a Customer for us — subscription
    # mode does; payment mode with `customer_email` does not. Persist
    # whichever we got.
    intent.provider_customer_id = getattr(session, "customer", None)
    db.flush()

    return CheckoutSessionResult(
        checkout_url=session.url,
        provider_checkout_session_id=session.id,
        purchase_intent_id=intent.id,
    )


# ---------------------------------------------------------------------------
# Session-args builder — subscription vs one-time
# ---------------------------------------------------------------------------


def _build_session_args(db: Session, intent: PurchaseIntent) -> dict:
    """Assemble the kwargs for ``stripe.checkout.Session.create``.

    Snapshots ``platform_fee_bps`` (and, for one-time flows, the
    subject's currency/amount) onto the intent row so the price
    committed to the buyer is a fixed record. Line items themselves
    are always resolved from a Stripe Price ID (subscription) or from
    server-loaded DB values (one-time) — never from client input.
    """
    metadata = _base_metadata(intent)

    if intent.kind == PurchaseIntentKind.creator_subscription:
        assert intent.plan_slug is not None  # validated on intent build
        plan = _load_creator_plan(db, intent.plan_slug)
        price_id = _resolve_creator_plan_price_id(intent.plan_slug)

        # Snapshot the fee rate on the intent. The gross amount lives
        # on the Stripe Price and is verified by the webhook later.
        intent.platform_fee_bps = plan.transaction_fee_basis_points
        intent.currency = "AUD"  # Stripe Price is authoritative; this
                                 # is a UI-side snapshot only.

        return {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            # No `payment_intent_data.metadata` in subscription mode —
            # Stripe rejects that field. Recurring invoices carry the
            # subscription metadata forward.
        }

    if intent.kind == PurchaseIntentKind.collective_membership:
        # Scaffolded for future wiring. Frontend for member purchases
        # is not part of Stage 2, but the code path must exist end-to-
        # end so Stage 5 does not have to re-plumb the service.
        # Deliberately raises a clear error until the space-priced
        # Session code path is wired.
        raise MissingPricingError(
            "collective_membership Checkout Sessions are not wired in "
            "Stage 2. Add pricing resolution + line items when "
            "implementing the paid-Collective join flow."
        )

    # Other kinds (pathway, gathering) — existing production paths in
    # app/checkout/routes.py + app/spaces/routes.py still handle those
    # directly. Deliberately unimplemented here; will be folded into
    # this service in Stage 5+.
    raise InvalidIntentStateError(
        f"kind={intent.kind.value} is not supported by "
        "create_checkout_session_for_intent in Stage 2."
    )


def _base_metadata(intent: PurchaseIntent) -> dict[str, str]:
    """Metadata attached to every Stripe object. Kept minimal —
    ``purchase_intent_id`` is the anchor the webhook will use to route
    events; everything else is a convenience for operator debugging.
    ``claim_email`` is included only if we already know it (logged-in
    payer). Anonymous flows leave it out; Stripe fills
    ``customer_details.email`` during Checkout and the webhook uses
    that to populate ``PurchaseIntent.claim_email``.
    """
    md: dict[str, str] = {
        "purchase_intent_id": intent.id,
        "kind": intent.kind.value,
    }
    if intent.plan_slug:
        md["plan_slug"] = intent.plan_slug
    if intent.space_id:
        md["space_id"] = intent.space_id
    if intent.pathway_id:
        md["pathway_id"] = intent.pathway_id
    if intent.event_id:
        md["event_id"] = intent.event_id
    if intent.claim_email:
        md["claim_email"] = intent.claim_email
    return md


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def _build_success_url(raw_claim_token: str) -> str:
    """Success returns to /checkout/complete with the raw claim token
    in the query string. Stage 2 does not implement /checkout/complete;
    Stage 3 will. Until then a return to the URL is harmless — the
    prototype holding screen at /checkout/next is still available and
    /checkout/complete itself would just render a 404 or a placeholder.
    """
    return f"{settings.resolved_public_app_url}/checkout/complete?token={raw_claim_token}"


def _build_cancel_url(intent: PurchaseIntent) -> str:
    """Cancel returns the buyer to the originating flow. Kind-specific
    so a cancelled Creator checkout lands back on /for-creators, and a
    cancelled Collective checkout lands back on the Collective's about
    page."""
    base = settings.resolved_public_app_url
    if intent.kind == PurchaseIntentKind.creator_subscription:
        return f"{base}/for-creators#plans"
    if intent.kind == PurchaseIntentKind.collective_membership and intent.space_id:
        # Slug is unknown here without a DB roundtrip; land the buyer
        # on the Collectives directory instead, which is always safe.
        return f"{base}/spaces"
    return f"{base}/"


# ---------------------------------------------------------------------------
# Intent state validation
# ---------------------------------------------------------------------------


def _validate_pending_intent(intent: PurchaseIntent) -> None:
    if intent.status != PurchaseIntentStatus.pending:
        raise InvalidIntentStateError(
            f"Intent {intent.id} is in status "
            f"'{intent.status.value}'; Checkout Session creation "
            "requires 'pending'."
        )
    if intent.consumed_at is not None:
        raise InvalidIntentStateError(
            f"Intent {intent.id} has already been consumed."
        )
    # `expired` is a terminal status; consumed is a terminal status.
    # Both are caught by the status check above, but consumed_at is
    # additionally verified so a data-integrity bug can't slip through.
