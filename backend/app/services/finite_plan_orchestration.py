"""FIP2 — orchestration for starting a finite payment plan.

The pay-in-full path in ``checkout_orchestration.py`` is untouched.
This module adds a parallel path for
``schedule_type='recurring_installments'`` schedules:

    unified /api/checkout entry
      → resolve schedule (must be recurring_installments, published)
      → duplicate-plan guard (Rule D)
      → resolve + snapshot the FulfilmentIntent from current DB
      → create PurchasePlan in ``pending_setup``
      → create Stripe Checkout Session in ``mode='setup'``
      → persist ``provider_setup_session_id`` on the plan
      → return session URL to the caller

Explicitly NOT here:
  * Stripe SubscriptionSchedule creation — that happens in the
    ``checkout.session.completed`` webhook handler for the setup
    session (once the payment method is on file).
  * First-invoice fulfilment — that happens in the
    ``invoice.payment_succeeded`` handler.
  * Cancellation, grace, later-payment reconciliation — FIP3.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

import stripe
from fastapi import HTTPException
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Space
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services.checkout_orchestration import (
    FeeContext,
    resolve_fee_context,
)
from app.services.purchase_fulfilment import (
    apply_intent,   # noqa: F401 — for tests / future callers of this module
    resolve_intent_for_option,
    serialise_intent,
    validate_intent,
)
from app.services.schedule_validation import (
    validate_recurring_installments_row,
    ScheduleValidationError,
)
from app.services import stripe_finite_plan


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class ResolvedRecurringOption:
    """The recurring-schedule counterpart of ``ResolvedOption``.

    Kept separate so pay-in-full and finite-plan callers cannot
    accidentally mix contract types.
    """

    payment_option: PaymentOption
    payment_schedule: PaymentOptionSchedule
    space: Space
    currency: str


# ---------------------------------------------------------------------------
# Resolvers + guards
# ---------------------------------------------------------------------------


def resolve_option_and_schedule_for_plan(
    db: Session, *,
    payment_option_id: str,
    payment_option_schedule_id: str,
) -> ResolvedRecurringOption:
    """Load + validate the Option and Schedule for a finite plan.

    Symmetrical to ``resolve_option_and_schedule`` for pay-in-full,
    but the schedule MUST be ``recurring_installments`` +
    ``published`` and MUST pass the finite-plan cross-field
    validator. HTTPException on any failure.
    """
    payment_option: PaymentOption | None = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == payment_option_id)
        .first()
    )
    if payment_option is None:
        raise HTTPException(status_code=404, detail="Payment option not found.")

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
                "This payment plan is not currently available. "
                "Please contact support."
            ),
        )
    if payment_schedule.schedule_type != "recurring_installments":
        raise HTTPException(
            status_code=400,
            detail=(
                "This schedule is not a payment plan. Use the "
                "pay-in-full path instead."
            ),
        )

    try:
        validate_recurring_installments_row(payment_schedule)
    except ScheduleValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Payment plan schedule is not valid for checkout.",
                "errors": str(exc).split("; "),
            },
        )

    space = db.query(Space).filter(Space.id == payment_option.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Collective not found.")

    currency = (
        payment_schedule.currency
        or payment_option.currency
        or "AUD"
    ).upper()

    return ResolvedRecurringOption(
        payment_option=payment_option,
        payment_schedule=payment_schedule,
        space=space,
        currency=currency,
    )


def check_no_active_plan(
    db: Session, *,
    user: User,
    payment_option: PaymentOption,
) -> None:
    """FIP1 Rule D — refuse to start a second plan for the same option
    while the previous plan is still active-ish.

    Blocks: ``pending_setup``, ``active``, ``payment_problem``.
    Does NOT block: ``completed``, ``cancelled``, ``failed``.

    Uses a raw text() query on the enum so the caller does not need
    to load the enum class into scope for a one-line check.
    """
    existing = db.execute(
        text(
            "SELECT id, status FROM purchase_plans "
            "WHERE member_user_id = :uid "
            "AND payment_option_id = :oid "
            "AND status IN ('pending_setup', 'active', 'payment_problem') "
            "LIMIT 1"
        ),
        {"uid": user.id, "oid": payment_option.id},
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already have a payment plan in progress for this "
                "Payment Option. Contact support if you need to change it."
            ),
        )


# ---------------------------------------------------------------------------
# Plan creation + setup Session
# ---------------------------------------------------------------------------


@dataclass
class FinitePlanStartOutcome:
    plan: PurchasePlan
    session: object  # the Stripe Session
    checkout_url: str


def start_finite_plan_setup(
    db: Session, *,
    resolved: ResolvedRecurringOption,
    payer: User,
    success_url: str,
    cancel_url: str,
    now: datetime,
    override_customer_id: str | None = None,
) -> FinitePlanStartOutcome:
    """Snapshot the plan + open a Stripe setup Session.

    Order:
      1. Resolve + validate the grants intent from current DB.
      2. Compute the fee snapshot.
      3. Insert a ``pending_setup`` PurchasePlan (with intent snapshot).
      4. Create the Stripe Session (metadata + Customer via helper).
      5. UPDATE the plan with ``provider_setup_session_id`` (+
         ``provider_customer_id`` if we reused an existing one).

    Ordering rationale: we insert the plan BEFORE calling Stripe so
    a Stripe failure doesn't create a Session that nothing owns.
    The plan row exists briefly with no session id — that's fine,
    it's ``pending_setup`` and no webhook can find it yet. If Stripe
    then fails, the plan is left in ``pending_setup`` with a NULL
    session id and effectively abandoned; a future cleanup pass can
    sweep it.

    An in-flight Stripe SubscriptionSchedule is NOT created here.
    That happens after the member completes the setup Session and
    the ``checkout.session.completed`` webhook fires.
    """
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured on this server.",
        )

    # ── Snapshot the grants intent from current DB ─────────────────
    resolution = resolve_intent_for_option(
        db,
        payment_option=resolved.payment_option,
        metadata_pathway_id=None,
        now=now,
    )
    if resolution.fatal_error:
        # The option refers to something the resolver cannot honour
        # (deleted Pathway / Series). Same failure mode as pay-in-full.
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Payment Option cannot be fulfilled.",
                "error": resolution.fatal_error,
            },
        )
    validation = validate_intent(db, resolution.intent)
    if not validation.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Payment Option's grants are not currently valid.",
                "errors": list(validation.errors),
            },
        )

    # ── Fee snapshot ───────────────────────────────────────────────
    fee_context: FeeContext = resolve_fee_context(resolved.space, db)

    # ── Insert plan row ───────────────────────────────────────────
    schedule = resolved.payment_schedule
    total_expected = schedule.installment_amount_cents * schedule.installment_count

    plan = PurchasePlan(
        id=f"pplan_{uuid.uuid4().hex[:24]}",
        member_user_id=payer.id,
        payment_option_id=resolved.payment_option.id,
        payment_option_schedule_id=schedule.id,
        space_id=resolved.space.id,
        creator_user_id=fee_context.creator_id,
        status=PurchasePlanStatus.pending_setup,
        currency=resolved.currency,
        installment_amount_cents=schedule.installment_amount_cents,
        installments_expected=schedule.installment_count,
        installments_paid=0,
        total_expected_cents=total_expected,
        platform_fee_basis_points=fee_context.fee_bps,
        creator_plan_id=fee_context.creator_plan_id,
        stripe_interval=schedule.stripe_interval,
        stripe_interval_count=schedule.stripe_interval_count,
        stripe_mode=settings.stripe_mode,
        snapshot_grants_json=serialise_intent(resolution.intent),
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    # ── Stripe Session ────────────────────────────────────────────
    # ``override_customer_id`` is an OPERATOR-ONLY escape hatch used
    # by FIP3 test-clock harnesses (``scripts/fip3_test_acceleration.py``)
    # so a Customer that was created against a Stripe Test Clock —
    # which Stripe requires at Customer-creation time — can enter
    # the normal setup Session flow. NEVER pass this from an HTTP
    # request context; there is no public code path that forwards
    # it. When not provided, the normal reuse lookup runs.
    if override_customer_id is not None:
        reuse_customer_id = override_customer_id
    else:
        reuse_customer_id = stripe_finite_plan.find_reusable_customer_id(
            db, payer.id,
        )
    try:
        session = stripe_finite_plan.create_setup_session(
            plan=plan,
            # The disclosure composer uses this to name the plan on
            # the Stripe-hosted setup page. Taken from the Payment
            # Option row loaded during resolution — server-controlled,
            # not client-supplied.
            option_name=resolved.payment_option.name,
            member_email=payer.email,
            success_url=success_url,
            cancel_url=cancel_url,
            reuse_customer_id=reuse_customer_id,
        )
    except stripe.StripeError as exc:
        logger.error(
            "Stripe setup Session creation failed for plan=%s user=%s: %s",
            plan.id, payer.id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to open payment plan setup. Please try again.",
        )

    plan.provider_setup_session_id = session.id
    if reuse_customer_id is not None:
        # We passed a reused Customer id; record it on this plan too
        # so later reconciliation doesn't depend on cross-plan lookups.
        plan.provider_customer_id = reuse_customer_id
    plan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)

    logger.info(
        "FIP2 start: plan=%s session=%s option=%s schedule=%s user=%s "
        "amount=%d/currency=%s count=%d cadence=%s×%d",
        plan.id, session.id,
        plan.payment_option_id, plan.payment_option_schedule_id,
        payer.id, plan.installment_amount_cents, plan.currency,
        plan.installments_expected,
        plan.stripe_interval, plan.stripe_interval_count,
    )

    return FinitePlanStartOutcome(
        plan=plan,
        session=session,
        checkout_url=session.url,
    )
