"""Shared checkout orchestration.

Consolidates the plumbing every checkout endpoint needs:

  * PaymentOption + Schedule resolution and validation.
  * Fee-context resolution (platform fee bps / plan id /
    subscription id / platform-owned flag).
  * Stripe Checkout Session + PaymentTransaction creation as a
    single atomic write (no DB writes before Stripe, so a Stripe
    failure has nothing to undo).
  * Free-purchase short-circuit: bypass Stripe entirely, apply
    the option's grants through the hardened fulfilment service,
    and commit a ``succeeded`` / ``applied`` transaction atomically.
  * Pre-checkout safety: refuse to take payment when the
    fulfilment layer already knows it cannot apply the bundle
    (e.g. Gathering-grant options; options carrying Series-style
    fields the current grant model can't represent).

Used by:

  * ``POST /api/checkout`` — the unified, kind-agnostic entry
    point (B4B).
  * ``POST /api/checkout/pathway`` — legacy compat wrapper.
  * ``POST /api/checkout/gathering-series`` — legacy compat wrapper.

Legacy wrappers layer their kind-specific extra validation on
top (e.g. Pathway existence + status; Series existence + status;
single-experience duplicate-purchase guards). Everything below
those extras is shared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import stripe
from fastapi import HTTPException
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_GATHERING,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EntitlementStatus, PathwayEntitlement, Space
from app.models.user import User
from app.services.purchase_fulfilment import (
    FulfilmentResult,
    apply_intent,
    option_grant_readiness,
    resolve_intent_for_option,
    validate_intent,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fee resolution — creator plan → transaction fee rate
# ---------------------------------------------------------------------------


# Default fee rate (Basic plan 8%) used when creator has no active subscription
_DEFAULT_FEE_BPS = 800


@dataclass(frozen=True)
class FeeContext:
    fee_bps: int
    creator_plan_id: str | None
    creator_subscription_id: str | None
    is_platform_owned: bool
    creator_id: str | None


def resolve_fee_context(space: Space, db: Session) -> FeeContext:
    """Return the fee context for a purchase against ``space``.

    Platform-owned spaces (creator_id IS NULL = Fresh Collective
    owns the space) pay zero platform fee and require no payout —
    the money stays directly with FC.
    """
    if space.creator_id is None:
        return FeeContext(
            fee_bps=0,
            creator_plan_id=None,
            creator_subscription_id=None,
            is_platform_owned=True,
            creator_id=None,
        )
    fee_bps, plan_id, sub_id = _resolve_fee_bps_for_creator(space.creator_id, db)
    return FeeContext(
        fee_bps=fee_bps,
        creator_plan_id=plan_id,
        creator_subscription_id=sub_id,
        is_platform_owned=False,
        creator_id=space.creator_id,
    )


def _resolve_fee_bps_for_creator(
    creator_id: str, db: Session,
) -> tuple[int, str | None, str | None]:
    """Return ``(fee_bps, creator_plan_id, creator_subscription_id)``.

    Uses the creator's active CreatorSubscription → CreatorPlan.
    Falls back to the cheapest active plan, then to the hardcoded
    default (800 = 8%).
    """
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
        plan = (
            db.query(CreatorPlan)
            .filter(CreatorPlan.id == sub.creator_plan_id)
            .first()
        )
        if plan:
            return plan.transaction_fee_basis_points, plan.id, sub.id
    fallback = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    if fallback:
        return fallback.transaction_fee_basis_points, None, None
    return _DEFAULT_FEE_BPS, None, None


# ---------------------------------------------------------------------------
# Option + Schedule resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedOption:
    """Result of validating a checkout request's option +
    schedule + price."""

    payment_option: PaymentOption
    payment_schedule: PaymentOptionSchedule
    price_cents: int
    currency: str
    space: Space


def resolve_option_and_schedule(
    db: Session, *,
    payment_option_id: str,
    payment_option_schedule_id: str,
) -> ResolvedOption:
    """Look up + validate the Option and Schedule referenced by a
    checkout request. Raises HTTPException with the right code
    for every failure mode.

    * Option must exist and be ``status='published'``.
    * Schedule must exist and belong to the Option.
    * Schedule must be ``status='published'``.
    * Schedule type must be ``pay_in_full`` — this endpoint
      does not yet handle recurring/manual (503 for recurring;
      400 otherwise).
    * Price must be present. Zero prices are allowed (free
      option; caller detects and short-circuits Stripe).
    """
    payment_option: PaymentOption | None = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == payment_option_id)
        .first()
    )
    if payment_option is None:
        raise HTTPException(
            status_code=404, detail="Payment option not found.",
        )
    option_status = (
        payment_option.status.value
        if hasattr(payment_option.status, "value")
        else str(payment_option.status)
    )
    if option_status != "published":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Payment option is not available for purchase "
                f"(status: {option_status})."
            ),
        )

    payment_schedule: PaymentOptionSchedule | None = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.id == payment_option_schedule_id,
            PaymentOptionSchedule.payment_option_id == payment_option.id,
        )
        .first()
    )
    if payment_schedule is None:
        raise HTTPException(
            status_code=404,
            detail="Payment schedule not found or not available for this option.",
        )
    if payment_schedule.status != "published":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Payment schedule is not available for purchase "
                f"(status: {payment_schedule.status})."
            ),
        )
    if payment_schedule.schedule_type == "recurring_installments":
        raise HTTPException(
            status_code=503,
            detail=(
                "Recurring instalment payment plans are not yet available "
                "for checkout. Please choose 'Pay in full' or contact support."
            ),
        )
    if payment_schedule.schedule_type != "pay_in_full":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Payment schedule type {payment_schedule.schedule_type!r} "
                f"is not supported by this endpoint. Only 'pay_in_full' "
                f"schedules can be checked out here."
            ),
        )

    # Pay-in-full schedules take the price from
    # ``schedule.total_amount_cents``. A price of zero is legitimate
    # (free option) — the caller distinguishes and skips Stripe.
    price_cents = (
        payment_schedule.total_amount_cents
        if payment_schedule.total_amount_cents is not None else 0
    )
    if price_cents < 0:
        raise HTTPException(
            status_code=400, detail="Payment schedule has an invalid price.",
        )

    space = db.query(Space).filter(Space.id == payment_option.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Collective not found.")

    currency = (
        payment_schedule.currency
        or payment_option.currency
        or "AUD"
    ).upper()

    return ResolvedOption(
        payment_option=payment_option,
        payment_schedule=payment_schedule,
        price_cents=price_cents,
        currency=currency,
        space=space,
    )


# ---------------------------------------------------------------------------
# Pre-checkout fulfilment safety
# ---------------------------------------------------------------------------


def check_same_option_not_active(
    db: Session, *,
    user: User,
    payment_option: PaymentOption,
    now: datetime,
) -> None:
    """Refuse to charge the same buyer for a PaymentOption they
    already actively hold.

    Scope of the guard (deliberately narrow — same option only)
    -----------------------------------------------------------
    Blocks: repurchase of the **exact same** PaymentOption while
    at least one grant it produced is still actively providing
    access.

    Does NOT block:

    * Different-option purchases from the same buyer (e.g. an
      Awaken holder upgrading to Empower). Bundle-aware upgrade
      policy is not in scope for B4B.
    * Repurchase after every access grant produced by the previous
      purchase has expired (``valid_until`` / ``ends_at`` in the
      past) or been revoked / cancelled — the buyer no longer
      "actively holds" the option, so a fresh purchase is
      legitimate.
    * Repurchase after a prior transaction ended in ``failed`` /
      ``cancelled`` / stayed ``pending`` and was cleaned up — no
      access rows were ever written, so nothing here matches.
    * Repurchase against a ``blocked`` fulfilment (payment
      succeeded but the shared fulfilment service refused to
      write). No AccessPass / PathwayEntitlement rows exist for a
      blocked fulfilment, so the guard is silent — recovery flows
      (webhook replay after data fix) don't need to defeat it.

    Reliability by option shape
    ---------------------------
    * Any option with a Series grant → **reliable**.
      ``AccessPass.payment_option_id`` is populated by the shared
      fulfilment service on every Series-grant materialisation,
      so Rule A catches it.
    * Any option purchased via paid checkout (unified or legacy
      wrapper) → **reliable**. The resulting
      ``PathwayEntitlement.stripe_checkout_session_id`` matches
      the ledger row's ``provider_checkout_session_id``, giving
      Rule B a reliable join back to the option id.
    * Single-Pathway option purchased free via unified endpoint
      → **reliable**. ``PaymentTransaction.entitlement_id`` is
      populated by ``_link_singular_entitlement`` when exactly
      one entitlement was produced, so Rule C catches it.
    * Multi-Pathway option purchased **free** via unified endpoint
      → **not caught**. No Stripe session id (free path) and
      ``txn.entitlement_id`` stays null when >1 entitlements are
      produced. Duplicate free multi-Pathway purchases will
      succeed — no charge, but they will produce duplicate
      no-op entitlement writes (the entitlement applier is
      idempotent, so the second call re-activates the existing
      row rather than creating a second). Low priority: no
      double-charge risk on the free path.

    Raises HTTPException(409) with a member-facing message when
    the guard fires.
    """
    # Rule A — AccessPass table: covers every Series-including
    # option (Series-only, Series+bundled Pathway, multi-Series,
    # legacy Series-attached term_pass). Also covers legacy
    # pathway-attached term_pass options whose AccessPass carries
    # ``payment_option_id``.
    active_pass = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.payment_option_id == payment_option.id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .first()
    )
    if active_pass is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already hold an active pass from this Payment "
                "Option. If you need to change your plan, contact "
                "support."
            ),
        )

    # Rule B — Paid path: join via provider_checkout_session_id.
    # Covers Pathway-only and multi-Pathway options paid through
    # Stripe (unified or legacy pathway wrapper). Skipped for
    # options whose only historic purchase by this user was free
    # (no session id).
    ent_via_session = (
        db.query(PathwayEntitlement.id)
        .join(
            PaymentTransaction,
            PaymentTransaction.provider_checkout_session_id
            == PathwayEntitlement.stripe_checkout_session_id,
        )
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            or_(
                PathwayEntitlement.ends_at.is_(None),
                PathwayEntitlement.ends_at > now,
            ),
            PaymentTransaction.payer_user_id == user.id,
            PaymentTransaction.payment_option_id == payment_option.id,
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.provider_checkout_session_id.isnot(None),
        )
        .first()
    )
    if ent_via_session is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already have active access from this Payment "
                "Option. If you need to change your plan, contact "
                "support."
            ),
        )

    # Rule C — Free single-Pathway path: join via the ledger's
    # singular entitlement pointer, which the applier populates
    # only when exactly one entitlement was produced.
    ent_via_singular_ptr = (
        db.query(PathwayEntitlement.id)
        .join(
            PaymentTransaction,
            PaymentTransaction.entitlement_id == PathwayEntitlement.id,
        )
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            or_(
                PathwayEntitlement.ends_at.is_(None),
                PathwayEntitlement.ends_at > now,
            ),
            PaymentTransaction.payer_user_id == user.id,
            PaymentTransaction.payment_option_id == payment_option.id,
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
        )
        .first()
    )
    if ent_via_singular_ptr is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already have active access from this Payment "
                "Option. If you need to change your plan, contact "
                "support."
            ),
        )

    # Rule D — active finite-plan agreement. Blocks a second start
    # of the same Payment Option while the previous plan is still
    # "active-ish" (pending_setup / active / payment_problem). Does
    # NOT block completed / cancelled / failed plans, so a legitimate
    # future-term repurchase or retry after abandonment is allowed.
    # Applies to BOTH pay-in-full and finite-plan checkout callers so
    # a member on an active $20/week × 10 plan cannot separately buy
    # the $200 once schedule of the same option.
    active_plan = db.execute(
        text(
            "SELECT id FROM purchase_plans "
            "WHERE member_user_id = :uid "
            "AND payment_option_id = :oid "
            "AND status IN ('pending_setup', 'active', 'payment_problem') "
            "LIMIT 1"
        ),
        {"uid": user.id, "oid": payment_option.id},
    ).first()
    if active_plan is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already have a payment plan in progress for this "
                "Payment Option. Contact support if you need to change it."
            ),
        )


def check_option_fulfillable_or_raise(payment_option: PaymentOption) -> None:
    """Refuse to take payment for options the fulfilment layer
    cannot honour under the current grant-first rules.

    Specifically: an option carrying any ``grant_kind='gathering'``
    grant blocks — standalone Gathering PaymentOption fulfilment
    is not yet activated, and the existing paid-Gathering
    ticket-hold flow remains authoritative. Charging the member
    would create a bundle we already know we can't apply.

    We deliberately do NOT block on "grant-ready = False" here.
    Non-grant-ready options (e.g. the pathway-attached term_pass
    EMBODY duplicates) still fulfil correctly through the legacy
    resolver — the dispatcher routes them there automatically.
    Blocking them here would break existing legacy purchases.
    """
    if any(
        g.grant_kind == GRANT_KIND_GATHERING
        for g in payment_option.grants
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "This Payment Option grants a Gathering. Standalone "
                "Gathering purchases still flow through the existing "
                "ticket-hold system; PaymentOption-based fulfilment "
                "for Gatherings is not yet available."
            ),
        )


# ---------------------------------------------------------------------------
# Stripe session + PaymentTransaction — kind-agnostic
# ---------------------------------------------------------------------------


def _pick_transaction_type(
    payment_option: PaymentOption,
) -> PaymentTransactionType:
    """Choose a ``PaymentTransactionType`` for the ledger row.

    Categorisation only — the source of truth for what was
    granted lives on ``payment_option_grants`` / the AccessPass
    / the PathwayEntitlement rows the webhook writes.

    Prefer grants (grant kinds are the target architecture). Fall
    back to the legacy ``attaches_to_kind`` for options that have
    not yet been backfilled — this preserves pre-B4B behaviour
    for the legacy Gathering-Series wrapper, whose fixtures do
    not create grant rows.
    """
    for g in payment_option.grants:
        if g.grant_kind == GRANT_KIND_EVENT_SERIES:
            return PaymentTransactionType.member_series_pass_purchase
    # Legacy fallback.
    if payment_option.attaches_to_kind == "event_series":
        return PaymentTransactionType.member_series_pass_purchase
    return PaymentTransactionType.member_pathway_purchase


def _build_stripe_line_items(
    *,
    product_name: str, product_description: str,
    currency: str, unit_amount: int,
) -> list[dict]:
    return [{
        "price_data": {
            "currency": currency.lower(),
            "product_data": {
                "name": product_name,
                "description": product_description,
            },
            "unit_amount": unit_amount,
        },
        "quantity": 1,
    }]


def _create_stripe_session_and_txn(
    db: Session, *,
    resolved: ResolvedOption,
    payer: User,
    fee_context: FeeContext,
    metadata: dict[str, str],
    payment_intent_metadata: dict[str, str],
    product_name: str,
    product_description: str,
    success_url: str,
    cancel_url: str,
    txn_transaction_type: PaymentTransactionType,
    txn_pathway_id: str | None,
    now: datetime,
) -> tuple[PaymentTransaction, "stripe.checkout.Session"]:
    """Create the Stripe Checkout Session and the matching pending
    ``PaymentTransaction`` row in a single atomic write.

    Mirrors the pre-B4B pattern: Session first (no DB writes to
    undo on Stripe failure), then insert the txn with
    ``provider_checkout_session_id`` already populated. The
    partial unique index on that column prevents duplicates.
    """
    txn_id = str(uuid4())

    # Populate transaction_id in metadata now that we have it,
    # if caller didn't already.
    metadata = {**metadata, "transaction_id": txn_id}
    payment_intent_metadata = {**payment_intent_metadata, "transaction_id": txn_id}

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=_build_stripe_line_items(
                product_name=product_name,
                product_description=product_description,
                currency=resolved.currency, unit_amount=resolved.price_cents,
            ),
            metadata=metadata,
            payment_intent_data={"metadata": payment_intent_metadata},
            customer_email=payer.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except stripe.StripeError as exc:
        logger.error(
            "Stripe session creation failed for option=%s user=%s: %s",
            resolved.payment_option.id, payer.id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to create checkout session. Please try again.",
        )

    gross = resolved.price_cents
    platform_fee = round(gross * fee_context.fee_bps / 10000)
    net_creator = gross - platform_fee

    txn = PaymentTransaction(
        id=txn_id,
        transaction_type=txn_transaction_type,
        status=PaymentTransactionStatus.pending,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=fee_context.creator_id,
        space_id=resolved.space.id,
        pathway_id=txn_pathway_id,
        creator_plan_id=fee_context.creator_plan_id,
        creator_subscription_id=fee_context.creator_subscription_id,
        currency=resolved.currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_context.fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=platform_fee,
        provider_checkout_session_id=session.id,
        payment_option_id=resolved.payment_option.id,
        payment_option_schedule_id=resolved.payment_schedule.id,
        payout_status=(
            PayoutStatus.not_applicable if fee_context.is_platform_owned
            else PayoutStatus.pending
        ),
        stripe_mode=settings.stripe_mode,
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.commit()
    return txn, session


# ---------------------------------------------------------------------------
# Unified paid-checkout entry
# ---------------------------------------------------------------------------


def orchestrate_paid_checkout(
    db: Session, *,
    resolved: ResolvedOption,
    payer: User,
    success_url: str,
    cancel_url: str,
    now: datetime,
    # Legacy wrappers may inject extra metadata (pathway_id /
    # series_id) alongside the shared metadata below. The unified
    # endpoint passes ``{}`` — grants alone tell the webhook what
    # to fulfil.
    extra_metadata: dict[str, str] | None = None,
    extra_payment_intent_metadata: dict[str, str] | None = None,
    # Legacy pathway wrapper writes the singular pathway_id on
    # ``PaymentTransaction`` for continuity with older reporting.
    # Unified checkout leaves it null unless the option has
    # exactly one Pathway grant (deferred — not part of B4B).
    txn_pathway_id: str | None = None,
    # Legacy wrappers can pass their own product name (e.g. the
    # Pathway title or "{series} — {tier}"). The unified endpoint
    # defaults to the option's name.
    product_name: str | None = None,
    # Unified endpoint pins the ledger row to the generic
    # ``member_payment_option_purchase`` type; legacy wrappers
    # leave this None so the picker falls back to their kind-
    # specific classifications (member_pathway_purchase /
    # member_series_pass_purchase) for reporting continuity.
    txn_transaction_type_override: PaymentTransactionType | None = None,
) -> tuple[PaymentTransaction, "stripe.checkout.Session"]:
    """Create the Stripe Checkout Session + PaymentTransaction for
    a paid PaymentOption purchase. Assumes ``resolved`` has
    passed ``resolve_option_and_schedule`` (schedule is pay_in_full,
    price > 0).

    Free options must NOT reach this function — the caller
    detects zero-price and calls :func:`orchestrate_free_checkout`
    instead.

    Ordering / failure modes
    ------------------------
    The orchestration deliberately calls Stripe **before** any DB
    write. Two failure modes to consider:

    * Stripe rejects the request → HTTPException(502) is raised
      and nothing hits the DB. No orphan rows.
    * Stripe succeeds, DB insert then fails → the Stripe Session
      is orphaned (a live Checkout URL exists but no ledger row
      backs it). Because ``PaymentTransaction`` is inserted in
      one shot with ``provider_checkout_session_id`` already
      populated (and covered by a partial unique index), the only
      way to hit this branch today is a hard driver failure or a
      duplicate-session collision. Orphan Sessions auto-expire in
      24h on Stripe's side; the webhook is defensive: it looks up
      the txn by ``metadata.transaction_id`` and no-ops when the
      row is missing (see ``app/webhooks/routes.py``). No refund
      cleanup is needed because no ``PaymentIntent`` is created
      until the buyer completes the hosted checkout, which cannot
      happen for an orphan session that the buyer was never
      redirected to.
    """
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured on this server.",
        )
    if resolved.price_cents <= 0:  # pragma: no cover — caller must route to free path
        raise HTTPException(
            status_code=500,
            detail="Free option reached paid-checkout path — dispatcher bug.",
        )

    stripe.api_key = settings.stripe_secret_key
    fee_context = resolve_fee_context(resolved.space, db)

    base_metadata: dict[str, str] = {
        "payment_option_id": resolved.payment_option.id,
        "payment_option_schedule_id": resolved.payment_schedule.id,
        "space_id": resolved.space.id,
        "payer_user_id": payer.id,
        "creator_user_id": fee_context.creator_id or "",
        "platform_fee_bps": str(fee_context.fee_bps),
        "creator_plan_id": fee_context.creator_plan_id or "",
    }
    if extra_metadata:
        base_metadata.update(extra_metadata)

    base_pi_metadata: dict[str, str] = {
        "payer_user_id": payer.id,
    }
    if extra_payment_intent_metadata:
        base_pi_metadata.update(extra_payment_intent_metadata)

    product_name = product_name or resolved.payment_option.name
    product_description = f"{resolved.space.name} — Fresh Collective"

    txn_transaction_type = (
        txn_transaction_type_override
        if txn_transaction_type_override is not None
        else _pick_transaction_type(resolved.payment_option)
    )

    return _create_stripe_session_and_txn(
        db,
        resolved=resolved,
        payer=payer,
        fee_context=fee_context,
        metadata=base_metadata,
        payment_intent_metadata=base_pi_metadata,
        product_name=product_name,
        product_description=product_description,
        success_url=success_url,
        cancel_url=cancel_url,
        txn_transaction_type=txn_transaction_type,
        txn_pathway_id=txn_pathway_id,
        now=now,
    )


# ---------------------------------------------------------------------------
# Free-option entry — bypass Stripe entirely
# ---------------------------------------------------------------------------


@dataclass
class FreeCheckoutOutcome:
    transaction: PaymentTransaction
    result: FulfilmentResult


def orchestrate_free_checkout(
    db: Session, *,
    resolved: ResolvedOption,
    payer: User,
    now: datetime,
    txn_transaction_type_override: PaymentTransactionType | None = None,
) -> FreeCheckoutOutcome:
    """Fulfil a zero-price PaymentOption purchase without Stripe.

    Preflight
        Resolve the option's intent through the shared dispatcher
        (grant-first when grant-ready, legacy fallback otherwise)
        and validate it. If either step reports a fatal error,
        raise HTTPException(400) before creating any rows — no
        row survives a rejected free purchase.

    Write
        Insert a ``PaymentTransaction`` with
        ``payment_provider='manual'`` (Stripe was never called),
        ``status='succeeded'``, gross/net/fees all zero, then
        apply the intent through the hardened fulfilment service.
        On successful apply, set ``fulfilment_status='applied'``
        and commit — one atomic transaction. On apply-time
        exception, roll back and re-raise (nothing survives).

    Returned outcome carries the txn + apply result so callers
    can log or return the transaction id.
    """
    # Preflight (before any writes).
    resolution = resolve_intent_for_option(
        db,
        payment_option=resolved.payment_option,
        metadata_pathway_id=None,
        now=now,
    )
    if resolution.fatal_error:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot fulfil this Payment Option as a free "
                f"purchase: {resolution.fatal_error}"
            ),
        )
    validation = validate_intent(db, resolution.intent)
    if not validation.ok:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot fulfil this Payment Option as a free "
                "purchase: " + "; ".join(validation.errors)
            ),
        )

    fee_context = resolve_fee_context(resolved.space, db)
    txn_transaction_type = (
        txn_transaction_type_override
        if txn_transaction_type_override is not None
        else _pick_transaction_type(resolved.payment_option)
    )
    txn_id = str(uuid4())
    txn = PaymentTransaction(
        id=txn_id,
        transaction_type=txn_transaction_type,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.manual,
        payer_user_id=payer.id,
        creator_user_id=fee_context.creator_id,
        space_id=resolved.space.id,
        pathway_id=None,
        creator_plan_id=fee_context.creator_plan_id,
        creator_subscription_id=fee_context.creator_subscription_id,
        currency=resolved.currency,
        gross_amount_cents=0,
        platform_fee_basis_points=fee_context.fee_bps,
        platform_fee_cents=0,
        net_creator_amount_cents=0,
        net_platform_amount_cents=0,
        provider_checkout_session_id=None,
        payment_option_id=resolved.payment_option.id,
        payment_option_schedule_id=resolved.payment_schedule.id,
        payout_status=PayoutStatus.not_applicable,
        stripe_mode=settings.stripe_mode,
        fulfilment_status=PaymentFulfilmentStatus.pending,
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.flush()

    try:
        result = apply_intent(
            db,
            intent=resolution.intent,
            txn=txn,
            payer_user_id=payer.id,
            space_id=resolved.space.id,
            payment_option_id=resolved.payment_option.id,
            payment_option_schedule_id=resolved.payment_schedule.id,
            session_id=None,
            payment_intent_id=None,
            now=now,
        )
        txn.fulfilment_status = PaymentFulfilmentStatus.applied
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "orchestrate_free_checkout: apply raised for option=%s user=%s — "
            "rolling back", resolved.payment_option.id, payer.id,
        )
        raise

    logger.info(
        "Free purchase applied: txn=%s option=%s user=%s ents=%d passes=%d",
        txn.id, resolved.payment_option.id, payer.id,
        len(result.entitlements), len(result.access_passes),
    )
    return FreeCheckoutOutcome(transaction=txn, result=result)


# ---------------------------------------------------------------------------
# Convenience — grant readiness signal (re-export for wrappers)
# ---------------------------------------------------------------------------


__all__ = [
    "FeeContext",
    "FreeCheckoutOutcome",
    "ResolvedOption",
    "check_option_fulfillable_or_raise",
    "check_same_option_not_active",
    "option_grant_readiness",   # re-exported for wrappers/tests
    "orchestrate_free_checkout",
    "orchestrate_paid_checkout",
    "resolve_fee_context",
    "resolve_option_and_schedule",
]
