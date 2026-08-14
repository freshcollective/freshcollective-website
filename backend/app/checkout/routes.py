"""Checkout endpoints.

Three routes today, all built on top of the shared checkout
orchestration in ``app/services/checkout_orchestration.py``:

  * ``POST /api/checkout``               — unified, kind-agnostic (B4B).
  * ``POST /api/checkout/pathway``        — legacy compat wrapper.
  * ``POST /api/checkout/gathering-series`` — legacy compat wrapper.

Everything that was inline in the pre-B4B endpoints — fee
resolution, Stripe Checkout Session creation, PaymentTransaction
row insertion, error handling — lives in the shared service now.
Wrappers layer kind-specific extra validation on top (Pathway /
Series existence + status checks; single-experience duplicate
guards) and inject their legacy metadata (``pathway_id`` /
``series_id``) so the webhook's older metadata expectations keep
working for their in-flight sessions.

Access is NOT granted here — it is granted by the webhook when
Stripe confirms the payment via ``checkout.session.completed``.
The one exception is the unified endpoint's free-option path,
which bypasses Stripe and applies the option's grants directly
through the hardened fulfilment service.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.checkout.schemas import (
    GatheringSeriesCheckoutRequest,
    GatheringSeriesCheckoutResponse,
    PathwayCheckoutRequest,
    PathwayCheckoutResponse,
    UnifiedCheckoutRequest,
    UnifiedCheckoutResponse,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import PaymentTransactionType
from app.models.payment_option import PaymentOption
from app.models.platform import (
    EntitlementStatus,
    EventSeries,
    Pathway,
    PathwayEntitlement,
)
from app.models.user import User
from app.services.checkout_orchestration import (
    _resolve_fee_bps_for_creator,
    check_option_fulfillable_or_raise,
    check_same_option_not_active,
    orchestrate_free_checkout,
    orchestrate_paid_checkout,
    resolve_option_and_schedule,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


def _resolve_fee_bps(
    creator_id: str | None, db: Session,
) -> tuple[int, str | None, str | None]:
    """Back-compat shim for pre-B4B callers (``spaces/routes.py``
    for standalone-Gathering ticket fees, plus one route test).
    The implementation lives in
    ``app.services.checkout_orchestration._resolve_fee_bps_for_creator``.
    """
    if not creator_id:
        # Platform-owned or missing creator → zero fee, no plan.
        return 0, None, None
    return _resolve_fee_bps_for_creator(creator_id, db)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
def checkout_status(
    _: User = Depends(get_current_user),
) -> dict:
    """Return platform payment configuration status.
    Used by Admin and Creator Studio to show accurate Stripe
    setup state."""
    test_mode = bool(
        settings.stripe_secret_key
        and settings.stripe_secret_key.startswith("sk_test_")
    )
    return {
        "stripe_enabled": settings.stripe_enabled,
        "stripe_test_mode": test_mode,
    }


# ---------------------------------------------------------------------------
# Unified checkout (B4B)
# ---------------------------------------------------------------------------


@router.post("", response_model=UnifiedCheckoutResponse)
def create_unified_checkout_session(
    body: UnifiedCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnifiedCheckoutResponse:
    """Kind-agnostic Payment Option checkout.

    Request never names a Pathway / Series / Gathering. The
    experiences purchased are derived at fulfilment time from
    the option's grants. Frontend redirects the browser to the
    returned ``checkout_url`` — a Stripe-hosted URL for paid
    options, or the request's ``success_url`` for free options
    (which are already fulfilled at return time).

    Pre-checkout guards:
      * Option / schedule must resolve, be published, and be
        ``pay_in_full``.
      * Options carrying Gathering grants are refused before
        payment (the paid-Gathering ticket-hold flow is still
        authoritative for those).
      * Same-option duplicate guard — refuses when the buyer
        already actively holds access from the same PaymentOption
        (see ``check_same_option_not_active`` for the reliability
        matrix). Different-option purchases (upgrades, sibling
        tiers) are NOT blocked here; bundle-aware upgrade policy
        is out of scope for B4B.

    The legacy ``/api/checkout/pathway`` wrapper preserves its
    own broader single-Pathway 409 (blocks any active
    entitlement, regardless of option) for backwards compatibility
    with the current member UI.
    """
    now = datetime.utcnow()

    resolved = resolve_option_and_schedule(
        db,
        payment_option_id=body.payment_option_id,
        payment_option_schedule_id=body.payment_option_schedule_id,
    )
    check_option_fulfillable_or_raise(resolved.payment_option)
    check_same_option_not_active(
        db, user=current_user,
        payment_option=resolved.payment_option, now=now,
    )

    # ── Free path: skip Stripe, apply grants directly ─────────────
    if resolved.price_cents == 0:
        outcome = orchestrate_free_checkout(
            db, resolved=resolved, payer=current_user, now=now,
            txn_transaction_type_override=(
                PaymentTransactionType.member_payment_option_purchase
            ),
        )
        return UnifiedCheckoutResponse(
            checkout_url=body.success_url,
            transaction_id=outcome.transaction.id,
            free=True,
        )

    # ── Paid path: Stripe Checkout Session ────────────────────────
    txn, session = orchestrate_paid_checkout(
        db,
        resolved=resolved,
        payer=current_user,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        now=now,
        txn_transaction_type_override=(
            PaymentTransactionType.member_payment_option_purchase
        ),
    )
    logger.info(
        "Unified checkout: txn=%s session=%s option=%s user=%s",
        txn.id, session.id, resolved.payment_option.id, current_user.id,
    )
    return UnifiedCheckoutResponse(
        checkout_url=session.url,
        transaction_id=txn.id,
        free=False,
    )


# ---------------------------------------------------------------------------
# Legacy compat: POST /api/checkout/pathway
# ---------------------------------------------------------------------------


@router.post("/pathway", response_model=PathwayCheckoutResponse)
def create_pathway_checkout_session(
    body: PathwayCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PathwayCheckoutResponse:
    """Legacy pathway-purchase entry point.

    Preserved during the transition for the current member UI.
    Delegates the shared work to
    ``app.services.checkout_orchestration``; the extra
    Pathway-specific validation + single-Pathway duplicate guard
    + legacy Stripe metadata (``pathway_id``) live here.

    New integrations should call ``POST /api/checkout`` instead.
    Access is granted by the webhook after payment confirmation.
    """
    now = datetime.utcnow()

    # ── Pathway must exist + be active ────────────────────────────
    pathway = db.query(Pathway).filter(Pathway.id == body.pathway_id).first()
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")
    p_status = (
        pathway.status.value if hasattr(pathway.status, "value")
        else str(pathway.status)
    )
    if p_status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Pathway is not available for purchase (status: {p_status}).",
        )

    # ── Duplicate-Pathway guard (legacy single-experience policy) ──
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

    # ── Two request shapes ────────────────────────────────────────
    # (a) With PaymentOption + Schedule → resolve via shared service.
    # (b) Legacy option-less shape → keep the pathway.price_cents
    #     fast path so R.E.A.L. Journey and other pre-PaymentOptions
    #     pathways still purchase.
    if body.payment_option_id:
        if not body.payment_option_schedule_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Payment schedule is required when a payment option "
                    "is selected."
                ),
            )

        # The shared resolver validates option status + schedule +
        # price. For the legacy wrapper we ALSO require the option
        # to be pathway-attached to this pathway.
        pre_option = (
            db.query(PaymentOption)
            .filter(PaymentOption.id == body.payment_option_id)
            .first()
        )
        if pre_option is None or pre_option.pathway_id != pathway.id:
            raise HTTPException(
                status_code=404,
                detail="Payment option not found or not available for this pathway.",
            )

        resolved = resolve_option_and_schedule(
            db,
            payment_option_id=body.payment_option_id,
            payment_option_schedule_id=body.payment_option_schedule_id,
        )
        if resolved.price_cents <= 0:
            raise HTTPException(
                status_code=400,
                detail="Payment option has no valid price.",
            )

        # Legacy metadata continuity: include ``pathway_id`` on the
        # Stripe Session + payment_intent, and populate
        # ``PaymentTransaction.pathway_id`` for downstream reporting.
        _txn, session = orchestrate_paid_checkout(
            db,
            resolved=resolved,
            payer=current_user,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            now=now,
            extra_metadata={"pathway_id": pathway.id},
            extra_payment_intent_metadata={"pathway_id": pathway.id},
            txn_pathway_id=pathway.id,
            product_name=pathway.title,
        )
        return PathwayCheckoutResponse(checkout_url=session.url)

    # ── Option-less legacy path (pathway.price_cents source) ──────
    pathway_pricing_mode = getattr(pathway, "pricing_mode", "legacy") or "legacy"
    if pathway_pricing_mode == "payment_options":
        raise HTTPException(
            status_code=400,
            detail=(
                "This pathway requires selecting a payment option. Please "
                "choose one and try again."
            ),
        )
    access_type = (
        pathway.access_type.value if hasattr(pathway.access_type, "value")
        else str(pathway.access_type or "free")
    )
    if access_type != "one_time":
        raise HTTPException(
            status_code=400,
            detail="Only one-time purchase pathways can be checked out via this endpoint.",
        )
    if not pathway.price_cents or pathway.price_cents <= 0:
        raise HTTPException(status_code=400, detail="Pathway has no valid price.")

    session = _legacy_pathway_price_stripe_session(
        db, pathway=pathway, payer=current_user,
        success_url=body.success_url, cancel_url=body.cancel_url, now=now,
    )
    return PathwayCheckoutResponse(checkout_url=session.url)


def _legacy_pathway_price_stripe_session(
    db: Session, *, pathway: Pathway, payer: User,
    success_url: str, cancel_url: str, now: datetime,
):
    """Option-less pathway-purchase path — reads price directly
    from ``pathway.price_cents``. Preserved verbatim for the
    R.E.A.L. Journey shape and other pre-PaymentOptions pathways
    still in use. Not exported for reuse; the shared orchestration
    is grants/option-based only."""
    import stripe as _stripe
    from uuid import uuid4 as _uuid4

    from app.models.payment import (
        PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
        PaymentTransactionType, PayoutStatus,
    )
    from app.services.checkout_orchestration import (
        resolve_fee_context as _resolve_fee_context,
    )
    from app.models.platform import Space

    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured on this server.",
        )
    _stripe.api_key = settings.stripe_secret_key

    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Collective not found.")

    fee_context = _resolve_fee_context(space, db)
    gross = pathway.price_cents
    currency = (pathway.currency or "AUD").upper()
    platform_fee = round(gross * fee_context.fee_bps / 10000)
    net_creator = gross - platform_fee
    txn_id = str(_uuid4())

    try:
        session = _stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": currency.lower(),
                    "product_data": {
                        "name": pathway.title,
                        "description": f"{space.name} — Fresh Collective",
                    },
                    "unit_amount": gross,
                },
                "quantity": 1,
            }],
            metadata={
                "transaction_id": txn_id,
                "pathway_id": pathway.id,
                "space_id": space.id,
                "payer_user_id": payer.id,
                "creator_user_id": fee_context.creator_id or "",
                "platform_fee_bps": str(fee_context.fee_bps),
                "creator_plan_id": fee_context.creator_plan_id or "",
                "payment_option_id": "",
                "payment_option_schedule_id": "",
            },
            payment_intent_data={
                "metadata": {
                    "transaction_id": txn_id,
                    "pathway_id": pathway.id,
                    "payer_user_id": payer.id,
                }
            },
            customer_email=payer.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except _stripe.StripeError as exc:
        logger.error(
            "Stripe session creation failed for pathway=%s user=%s: %s",
            pathway.id, payer.id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to create checkout session. Please try again.",
        )

    txn = PaymentTransaction(
        id=txn_id,
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.pending,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=fee_context.creator_id,
        space_id=space.id,
        pathway_id=pathway.id,
        creator_plan_id=fee_context.creator_plan_id,
        creator_subscription_id=fee_context.creator_subscription_id,
        currency=currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_context.fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=platform_fee,
        provider_checkout_session_id=session.id,
        payment_option_id=None,
        payment_option_schedule_id=None,
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
    logger.info(
        "Legacy pathway checkout: txn=%s session=%s pathway=%s user=%s",
        txn_id, session.id, pathway.id, payer.id,
    )
    return session


# ---------------------------------------------------------------------------
# Legacy compat: POST /api/checkout/gathering-series
# ---------------------------------------------------------------------------


@router.post("/gathering-series", response_model=GatheringSeriesCheckoutResponse)
def create_gathering_series_checkout_session(
    body: GatheringSeriesCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GatheringSeriesCheckoutResponse:
    """Legacy Gathering-Series-purchase entry point.

    Preserved during the transition for the current member UI.
    Extra kind-specific validation + duplicate-pass guard +
    legacy ``series_id`` Stripe metadata live here; shared
    plumbing delegates to
    ``app.services.checkout_orchestration``.

    New integrations should call ``POST /api/checkout`` instead.
    """
    now = datetime.utcnow()

    # ── Series validation ─────────────────────────────────────────
    series = db.query(EventSeries).filter(EventSeries.id == body.series_id).first()
    if not series:
        raise HTTPException(status_code=404, detail="Gathering Series not found.")
    if series.status != "published":
        raise HTTPException(
            status_code=400,
            detail=f"Series is not available for purchase (status: {series.status}).",
        )

    # ── Option must be attached to this specific Series ───────────
    pre_option = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == body.payment_option_id)
        .first()
    )
    if (
        pre_option is None
        or pre_option.attaches_to_kind != "event_series"
        or pre_option.attaches_to_id != series.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Payment option not found or not available for this Series.",
        )

    # ── Duplicate-pass guard (legacy single-Series policy) ────────
    existing_pass = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == current_user.id,
            AccessPass.eligible_series_id == series.id,
            AccessPass.status == AccessPassStatus.active,
            AccessPass.valid_from <= now,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .first()
    )
    if existing_pass:
        raise HTTPException(
            status_code=409,
            detail="You already have an active pass for this Series.",
        )

    resolved = resolve_option_and_schedule(
        db,
        payment_option_id=body.payment_option_id,
        payment_option_schedule_id=body.payment_option_schedule_id,
    )
    if resolved.price_cents <= 0:
        raise HTTPException(status_code=400, detail="Schedule has no valid price.")

    # Legacy metadata: include ``series_id`` on the Session +
    # payment_intent so any downstream tooling that inspected it
    # continues to see it. ``pathway_id`` is deliberately absent
    # (matches the pre-B4B series endpoint).
    _txn, session = orchestrate_paid_checkout(
        db,
        resolved=resolved,
        payer=current_user,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        now=now,
        extra_metadata={"series_id": series.id},
        extra_payment_intent_metadata={"series_id": series.id},
        # ``PaymentTransaction.pathway_id`` legacy pointer: the
        # pre-B4B series endpoint set this to the option's
        # ``grants_pathway_id`` when set (bundled Pathway continuity).
        # Preserve that.
        txn_pathway_id=(
            resolved.payment_option.grants_pathway_id
            if resolved.payment_option.grants_pathway_id
            else None
        ),
        product_name=f"{series.title} — {resolved.payment_option.name}",
    )
    return GatheringSeriesCheckoutResponse(checkout_url=session.url)
