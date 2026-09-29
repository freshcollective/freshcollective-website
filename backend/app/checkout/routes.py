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

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_verified_current_user
from app.checkout.schemas import (
    DiscountPreviewRequest,
    DiscountPreviewResponse,
    GatheringSeriesCheckoutRequest,
    GatheringSeriesCheckoutResponse,
    PathwayCheckoutRequest,
    PathwayCheckoutResponse,
    UnifiedCheckoutRequest,
    UnifiedCheckoutResponse,
)
from app.core.config import settings
from app.core.database import get_db
from app.services.connect_payout_model import (
    resolve_payout_model as _resolve_payout_model,
)
from app.core.rate_limit import client_ip_for_rate_limit
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
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.services.discount_application import find_code, resolve_discount
from app.services.discount_reservations import attach_session, release
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountError,
    DiscountRejection,
    normalise_code,
)
from app.services.checkout_orchestration import (
    _resolve_fee_bps_for_creator,
    check_option_fulfillable_or_raise,
    check_same_option_not_active,
    orchestrate_free_checkout,
    orchestrate_paid_checkout,
    resolve_option_and_schedule,
)
from app.services.finite_plan_orchestration import (
    resolve_option_and_schedule_for_plan,
    start_finite_plan_setup,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkout", tags=["checkout"])

#: Trying codes is cheap and a Collective's codes are guessable by
#: design — they are meant to be typed by people. Verified sign-in
#: already puts a name against every attempt; this caps how fast one
#: account can sweep a namespace.
limiter = Limiter(key_func=client_ip_for_rate_limit)


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


def _persist_session_params(db: Session, reservation, params: dict) -> None:
    """Store the exact Stripe kwargs before the call is made.

    This runs microseconds before the network request, and it is the only
    reason a crash between creating a Session and recording its id is
    recoverable: without the params, the reservation looks like one that
    never reached Stripe, and releasing it would free a slot a member may
    already have paid for.
    """
    from app.services.discount_reservations import _jsonable

    reservation.session_create_params_json = _jsonable(params)
    db.commit()


def _resolve_and_reserve(
    db: Session, *, raw_code, resolved, user, now,
):
    """Price the code and hold a slot, sweeping stale holds once if the
    code looks full.

    Both steps live behind one sweep because either can be the thing that
    reports a full code: ``resolve_discount`` refuses when the slot count
    has reached the limit, and ``reserve_or_reuse`` refuses again under
    the row lock. A stale hold — one whose checkout window elapsed but
    which nothing has verified — makes both refuse for a reason that may
    not be true any more.

    So on the first ``LIMIT_REACHED`` from either step, the stale holds
    for that code are verified against Stripe, OUTSIDE the row lock, and
    the pair is attempted once more. One retry only: if the second
    attempt still refuses, the holds are genuinely live or genuinely
    unverifiable, and looping would spend more time reaching the same
    answer.

    Returns ``(applied, ReservationOutcome)``.
    """
    from app.services.discount_reservations import (
        reserve_or_reuse, sweep_stale_reservations,
    )

    own_attempt = (
        user.id, resolved.payment_option.id, resolved.payment_schedule.id,
    )

    def attempt():
        applied = resolve_discount(
            db,
            raw_code=raw_code,
            space_id=resolved.space.id,
            payment_option_id=resolved.payment_option.id,
            original_cents=resolved.price_cents,
            currency=resolved.currency,
            now=now,
            own_attempt=own_attempt,
        )
        code_row = find_code(db, raw_code=raw_code, space_id=resolved.space.id)
        outcome = reserve_or_reuse(
            db, applied=applied, code=code_row, user_id=user.id,
            payment_option_id=resolved.payment_option.id,
            payment_option_schedule_id=resolved.payment_schedule.id, now=now,
        )
        return applied, outcome

    try:
        return attempt()
    except DiscountError as first:
        if first.reason is not DiscountRejection.LIMIT_REACHED:
            raise
        code_row = find_code(db, raw_code=raw_code, space_id=resolved.space.id)
        if code_row is None:
            raise
        if not sweep_stale_reservations(db, discount_code_id=code_row.id, now=now):
            raise
        logger.info(
            "Discount slot freed by verification sweep: code=%s user=%s",
            code_row.id, user.id,
        )
        return attempt()


@router.post("/discount-preview", response_model=DiscountPreviewResponse)
@limiter.limit("20/minute")
def preview_discount_code(
    request: Request,
    body: DiscountPreviewRequest,
    current_user: User = Depends(get_verified_current_user),
    db: Session = Depends(get_db),
) -> DiscountPreviewResponse:
    """What this code would do to this offer's price.

    Answers, it does not reserve. Nothing is written, no code is
    consumed, and a member may preview the same code as often as they
    like — the figure is only a statement about right now, and checkout
    works it out again from scratch.

    The price comes from ``resolve_option_and_schedule``, the same
    resolver checkout uses, so the number being discounted is the number
    that would be charged. Anything else and preview would be a second
    opinion rather than a preview.

    Invalid codes come back 200 with ``valid: false`` and a reason. See
    ``DiscountPreviewResponse`` for why that is not an error.
    """
    resolved = resolve_option_and_schedule(
        db,
        payment_option_id=body.payment_option_id,
        payment_option_schedule_id=body.payment_option_schedule_id,
    )

    if resolved.price_cents <= 0:
        return DiscountPreviewResponse(
            valid=False,
            code=normalise_code(body.code),
            reason=DiscountRejection.NOT_PURCHASABLE.value,
            message="This offer is already free — no code is needed.",
        )

    try:
        applied = resolve_discount(
            db,
            raw_code=body.code,
            space_id=resolved.space.id,
            payment_option_id=resolved.payment_option.id,
            original_cents=resolved.price_cents,
            currency=resolved.currency,
            now=datetime.utcnow(),
            # Their own hold must not count against them. Without this a
            # member who reserved the last slot reloads the page and is
            # told the code is fully used — by themselves.
            own_attempt=(
                current_user.id,
                resolved.payment_option.id,
                resolved.payment_schedule.id,
            ),
        )
    except DiscountError as exc:
        # Logged at debug: a member mistyping a code is ordinary, and a
        # wrong code is not an incident.
        logger.debug(
            "Discount preview refused: reason=%s option=%s user=%s",
            exc.reason.value, resolved.payment_option.id, current_user.id,
        )
        return DiscountPreviewResponse(
            valid=False,
            code=normalise_code(body.code),
            reason=exc.reason.value,
            message=exc.message,
        )

    return DiscountPreviewResponse(
        valid=True,
        code=applied.code,
        original_amount_cents=applied.amounts.original_cents,
        discount_amount_cents=applied.amounts.discount_cents,
        final_amount_cents=applied.amounts.final_cents,
        currency=applied.amounts.currency,
    )


@router.post("", response_model=UnifiedCheckoutResponse)
def create_unified_checkout_session(
    body: UnifiedCheckoutRequest,
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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

    # ── Dispatch on schedule type ─────────────────────────────────
    # A quick per-schedule peek so we can route to the right resolver.
    # The full resolver in each branch re-loads and validates
    # everything (ownership, publish status, etc.). This peek only
    # exists so the finite-plan (recurring_installments) path does
    # not fall through the pay-in-full resolver's 503 guard, and so
    # pay-in-full callers don't accidentally hit the finite-plan
    # resolver's plan-specific validation.
    schedule_type_row = (
        db.query(PaymentOptionSchedule.schedule_type)
        .filter(PaymentOptionSchedule.id == body.payment_option_schedule_id)
        .first()
    )
    if schedule_type_row is None:
        raise HTTPException(
            status_code=404,
            detail="Payment schedule not found or not available for this option.",
        )
    is_recurring = (schedule_type_row[0] == "recurring_installments")

    if is_recurring:
        if body.discount_code:
            # Settled product scope, not an unfinished edge: discount
            # codes are a pay-in-full feature. A creator wanting a
            # reduced payment plan publishes a separate Payment Option
            # at that price, which keeps one price per schedule and
            # leaves the finite-plan billing machinery alone.
            #
            # Refused rather than ignored, because accepting the code
            # and charging the full plan would tell the member something
            # untrue at the moment they commit. The frontend already
            # hides the field here; this is the guard for anything that
            # posts directly.
            raise HTTPException(
                status_code=400,
                detail=(
                    "Discount codes apply to pay-in-full purchases only. "
                    "Please choose 'Pay in full' to use a code."
                ),
            )
        # FIP2 — finite payment plan path. Setup Session collects
        # payment method; SubscriptionSchedule is created in the
        # webhook once setup completes.
        recurring_resolved = resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=body.payment_option_id,
            payment_option_schedule_id=body.payment_option_schedule_id,
        )
        check_option_fulfillable_or_raise(recurring_resolved.payment_option)
        check_same_option_not_active(
            db, user=current_user,
            payment_option=recurring_resolved.payment_option, now=now,
        )
        outcome = start_finite_plan_setup(
            db,
            resolved=recurring_resolved,
            payer=current_user,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            now=now,
        )
        logger.info(
            "FIP2 finite-plan start: plan=%s session=%s user=%s",
            outcome.plan.id, outcome.session.id, current_user.id,
        )
        return UnifiedCheckoutResponse(
            checkout_url=outcome.checkout_url,
            transaction_id=outcome.plan.id,
            free=False,
        )

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
        if body.discount_code:
            raise HTTPException(
                status_code=409,
                detail="This offer is already free — no code is needed.",
            )
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

    # ── Discount: revalidated here, independently of any preview ──
    # The preview the member saw is not evidence. It was a statement
    # about an earlier moment, it is not signed, and the code may have
    # expired or filled up since. So the code is resolved again from
    # scratch, against a price read again from the Payment Option.
    applied: AppliedDiscount | None = None
    reservation = None
    if body.discount_code:
        try:
            applied, outcome = _resolve_and_reserve(
                db, raw_code=body.discount_code, resolved=resolved,
                user=current_user, now=now,
            )
        except DiscountError as exc:
            # 409, not 422: the request was well formed and was valid when
            # the member saw the preview. What changed is the world.
            raise HTTPException(status_code=409, detail=exc.message) from exc
        reservation = outcome.reservation

        if (
            outcome.reused
            and reservation.provider_checkout_session_id
            and now < reservation.session_expires_at
        ):
            # This member already has a live payment page for exactly this
            # purchase. Hand back the same one: a new Session would be a
            # second charge waiting to happen, and a new reservation would
            # spend a slot they already hold.
            existing_url = reservation.provider_checkout_session_url
            if existing_url:
                logger.info(
                    "Unified checkout: reusing reservation=%s session=%s user=%s",
                    reservation.id, reservation.provider_checkout_session_id,
                    current_user.id,
                )
                return UnifiedCheckoutResponse(
                    checkout_url=existing_url,
                    transaction_id=(
                        reservation.payment_transaction_id
                        or reservation.intended_payment_transaction_id
                        or reservation.id
                    ),
                    free=False,
                )

        if outcome.reused and now >= reservation.session_expires_at:
            # Their own hold is past its window. Whether it is dead is a
            # question for Stripe, not for this request — opening a second
            # Session before knowing could charge them twice.
            from app.services.discount_reservations import verify_stale_reservation
            verdict = verify_stale_reservation(db, reservation=reservation, now=now)
            raise HTTPException(
                status_code=409,
                detail=(
                    "That checkout has already been completed."
                    if verdict == "completed" else
                    "Your previous checkout for this offer timed out. "
                    "Please start again."
                ),
            )

    # ── Paid path: Stripe Checkout Session ────────────────────────
    try:
        txn, session = orchestrate_paid_checkout(
            db,
            resolved=resolved,
            payer=current_user,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            now=now,
            applied_discount=applied,
            txn_id_override=(
                reservation.intended_payment_transaction_id if reservation else None
            ),
            session_expires_at=reservation.session_expires_at if reservation else None,
            session_idempotency_key=(
                reservation.session_idempotency_key if reservation else None
            ),
            on_session_params=(
                (lambda params: _persist_session_params(db, reservation, params))
                if reservation else None
            ),
            txn_transaction_type_override=(
                PaymentTransactionType.member_payment_option_purchase
            ),
        )
    except Exception:
        # Stripe refused, or the ledger write failed. Either way no
        # payment page exists for this attempt, so the slot must go back
        # immediately rather than waiting out its window — this is the one
        # release that needs no verification, because we are the party who
        # knows the request failed.
        #
        # Guarded on the params never having been persisted: if they WERE
        # persisted, a Session may exist despite the error, and releasing
        # would be a guess. Those fall to the verification ladder.
        if reservation is not None:
            db.rollback()
            db.refresh(reservation)
            if reservation.session_create_params_json is None:
                release(
                    db, reservation=reservation,
                    reason="session_create_failed", now=now,
                )
            else:
                logger.warning(
                    "Discount reservation %s left held after a failed checkout: "
                    "Stripe params were already sent, so a Session may exist. "
                    "Verification will decide.",
                    reservation.id,
                )
        raise
    if reservation is not None:
        reservation.provider_checkout_session_url = session.url
        attach_session(
            db,
            reservation=reservation,
            session_id=session.id,
            session_params=reservation.session_create_params_json or {},
            payment_transaction_id=txn.id,
            now=now,
        )
    logger.info(
        "Unified checkout: txn=%s session=%s option=%s user=%s discount=%s",
        txn.id, session.id, resolved.payment_option.id, current_user.id,
        applied.code if applied else "-",
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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

        # ── FIP4A — finite payment plan branch ────────────────────
        # Peek at schedule_type so recurring_installments routes to
        # the FIP2 setup path instead of the pay-in-full resolver's
        # 503 guard. Mirrors the branching in the unified
        # ``/api/checkout`` endpoint. The public-safety gate
        # (``FINITE_PLAN_MEMBER_CHECKOUT_ENABLED``) is consulted
        # authoritatively via ``_schedule_is_member_checkoutable``
        # applied to the row we peeked at — same rule the
        # frontend consumed to decide whether to show the choice.
        schedule_type_row = (
            db.query(PaymentOptionSchedule.schedule_type)
            .filter(PaymentOptionSchedule.id == body.payment_option_schedule_id)
            .first()
        )
        if schedule_type_row is None:
            raise HTTPException(
                status_code=404,
                detail="Payment schedule not found or not available for this option.",
            )
        is_recurring = (schedule_type_row[0] == "recurring_installments")

        if is_recurring:
            # Verify eligibility using the SAME helper that decides
            # what the member surface advertises. If the flag is OFF,
            # or the schedule is draft / invalid / bundled with an
            # unsupported grant, refuse cleanly. The 503 message
            # matches the unified path so error copy stays
            # consistent.
            from app.spaces.routes import _schedule_is_member_checkoutable
            full_schedule = (
                db.query(PaymentOptionSchedule)
                .filter(PaymentOptionSchedule.id == body.payment_option_schedule_id)
                .first()
            )
            if not _schedule_is_member_checkoutable(full_schedule, pre_option):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "This payment plan is not available for member "
                        "checkout right now."
                    ),
                )

            recurring_resolved = resolve_option_and_schedule_for_plan(
                db,
                payment_option_id=body.payment_option_id,
                payment_option_schedule_id=body.payment_option_schedule_id,
            )
            check_option_fulfillable_or_raise(recurring_resolved.payment_option)
            check_same_option_not_active(
                db, user=current_user,
                payment_option=recurring_resolved.payment_option, now=now,
            )
            outcome = start_finite_plan_setup(
                db,
                resolved=recurring_resolved,
                payer=current_user,
                success_url=body.success_url,
                cancel_url=body.cancel_url,
                now=now,
            )
            logger.info(
                "FIP4A pathway finite-plan start: plan=%s session=%s user=%s pathway=%s",
                outcome.plan.id, outcome.session.id, current_user.id, pathway.id,
            )
            return PathwayCheckoutResponse(checkout_url=outcome.checkout_url)

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
        NoActiveCreatorPlanError as _NoActiveCreatorPlanError,
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

    try:
        fee_context = _resolve_fee_context(space, db)
    except _NoActiveCreatorPlanError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Fresh Collective commercial terms have not been "
                "configured for this Collective. Paid checkout is "
                "unavailable until an admin assigns a Creator Plan."
            ),
        ) from exc
    if not fee_context.permits_paid_offers:
        raise HTTPException(
            status_code=403,
            detail=(
                "This Collective's Fresh Collective plan does not "
                "include paid offers. The creator's plan must be "
                "upgraded to Creator or higher to enable commercial "
                "checkout."
            ),
        )
    gross = pathway.price_cents
    currency = (pathway.currency or "AUD").upper()
    platform_fee = round(gross * fee_context.fee_bps / 10000)
    net_creator = gross - platform_fee
    # Same snapshot rule as every other purchase path: decided here, frozen
    # on the row, never re-derived from the creator's later Connect state.
    payout = _resolve_payout_model(
        db,
        creator_user_id=fee_context.creator_id,
        is_platform_owned=fee_context.is_platform_owned,
    )
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
        payout_model=payout.payout_model,
        connect_destination_account_id=payout.destination_account_id,
        connect_transfer_status=payout.initial_transfer_status,
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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
    # Series-level ownership check — active + not-yet-expired. No
    # ``valid_from`` filter: a member who has purchased a *future*
    # Series (e.g. Term 4 in September with ``valid_from`` in
    # October) already owns the seat and must not be able to
    # double-buy the same overlap simply because today is before
    # the window opens.
    existing_pass = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == current_user.id,
            AccessPass.eligible_series_id == series.id,
            AccessPass.status == AccessPassStatus.active,
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
