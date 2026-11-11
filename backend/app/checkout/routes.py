"""Checkout endpoints.

Four routes today, all built on top of the shared checkout
orchestration in ``app/services/checkout_orchestration.py``:

  * ``POST /api/checkout``               — unified, kind-agnostic (B4B).
  * ``POST /api/checkout/pathway``        — legacy compat wrapper.
  * ``POST /api/checkout/gathering-series`` — legacy compat wrapper.
  * ``POST /api/checkout/offering``       — one paid Offering (C/D).

The Offering route is a wrapper over the unified endpoint rather than
a parallel implementation: it resolves the Offering's Payment Option
from slugs, applies the Offering-specific acquisition rules, and then
delegates. Nothing about charging a card is reimplemented there.

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
from dataclasses import dataclass
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.auth.dependencies import get_current_user, get_verified_current_user
from app.checkout.schemas import (
    DiscountPreviewRequest,
    DiscountPreviewResponse,
    GatheringSeriesCheckoutRequest,
    GatheringSeriesCheckoutResponse,
    OfferingCheckoutRequest,
    OfferingCheckoutResponse,
    PathwayCheckoutRequest,
    PathwayCheckoutResponse,
    UnifiedCheckoutRequest,
    UnifiedCheckoutResponse,
)
from app.core.config import settings
from app.services import pathway_direct_offer as _direct_offer
from app.core.database import get_db
from app.services.connect_payout_model import (
    resolve_payout_model as _resolve_payout_model,
)
from app.core.rate_limit import client_ip_for_rate_limit
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import PaymentTransaction, PaymentTransactionType
from app.models.payment_option import PaymentOption
from app.models.platform import (
    EntitlementStatus,
    Event,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    Space,
)
from app.models.user import User
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.services import discount_checkout_hold as _hold
from app.services import discount_reservations as _reservations
from app.services.discount_application import (
    find_code, resolve_discount, resolve_plan_discount,
)
from app.services.discount_reservations import attach_session, release
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountError,
    DiscountRejection,
    normalise_code,
)
from app.services import pathway_payment_options as pathway_options
from app.services import checkout_supersession as _supersession
from app.services import pathway_commerce as _pathway_commerce
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
#: The one Offerings feature gate, imported rather than re-implemented
#: so the structural "every Offering route is gated" test keeps matching
#: on a single name.
from app.creator._offering_routes import (
    require_offerings_enabled as _require_offerings_enabled,
)
from app.services import offering_acquisition as _offering_acq


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


STAGE4_OFF_DETAIL = (
    "Discount codes aren't available for this purchase yet."
)


def _refuse_code_while_stage4_off(raw_code: str | None) -> None:
    """Refuse a code on a door Stage 4 has not opened yet.

    Refused rather than ignored. Accepting the code and charging the full
    price would tell the member something untrue at the moment they
    commit, which is the one outcome §10 rules out — and a 400 they can
    read beats a silent overcharge they discover on their statement.
    """
    if raw_code and not settings.universal_discount_codes_enabled:
        raise HTTPException(status_code=400, detail=STAGE4_OFF_DETAIL)


def _hold_for_pay_in_full(db: Session, *, raw_code, resolved, user, now):
    """Open a hold for a pay-in-full Payment Option purchase."""
    return _hold.open_hold(
        db,
        raw_code=raw_code,
        space_id=resolved.space.id,
        attempt=_reservations.ReservationAttempt.for_payment_option(
            user_id=user.id,
            payment_option_id=resolved.payment_option.id,
            payment_option_schedule_id=resolved.payment_schedule.id,
        ),
        price=lambda own: resolve_discount(
            db,
            raw_code=raw_code,
            space_id=resolved.space.id,
            payment_option_id=resolved.payment_option.id,
            original_cents=resolved.price_cents,
            currency=resolved.currency,
            now=now,
            own_attempt=own,
        ),
        now=now,
    )


def _hold_for_plan(db: Session, *, raw_code, resolved, user, now):
    """Open a hold for a finite instalment plan.

    The attempt names the plan's own schedule, so a member who prices a
    code against pay-in-full and then switches to instalments correctly
    takes a second slot rather than reusing the first — they are
    different purchases, and the earlier hold is swept or released on its
    own terms.
    """
    schedule = resolved.payment_schedule
    return _hold.open_hold(
        db,
        raw_code=raw_code,
        space_id=resolved.space.id,
        attempt=_reservations.ReservationAttempt.for_payment_option(
            user_id=user.id,
            payment_option_id=resolved.payment_option.id,
            payment_option_schedule_id=schedule.id,
        ),
        price=lambda own: resolve_plan_discount(
            db,
            raw_code=raw_code,
            space_id=resolved.space.id,
            payment_option_id=resolved.payment_option.id,
            installment_amount_cents=schedule.installment_amount_cents,
            installment_count=schedule.installment_count,
            currency=resolved.currency,
            now=now,
            own_attempt=own,
        ),
        now=now,
    )


def _hold_for_direct(
    db: Session, *, raw_code, space_id, kind, target_id, user, price_cents,
    currency, now,
):
    """Open a hold for a direct purchase — one with no Payment Option.

    ``payment_option_id`` is deliberately absent from the resolver call
    rather than defaulted: ``validate_code`` refuses a Payment
    Option-scoped code when no option is named, which is what keeps a
    code restricted to one Option off a standalone purchase of an
    experience that Option happens to include.
    """
    return _hold.open_hold(
        db,
        raw_code=raw_code,
        space_id=space_id,
        attempt=_reservations.ReservationAttempt.for_direct(
            user_id=user.id, kind=kind, target_id=target_id,
        ),
        price=lambda own: resolve_discount(
            db,
            raw_code=raw_code,
            space_id=space_id,
            original_cents=price_cents,
            currency=currency,
            now=now,
            own_attempt=own,
        ),
        now=now,
    )


@router.post("/discount-preview", response_model=DiscountPreviewResponse)
@limiter.limit("20/minute")
def preview_discount_code(
    request: Request,
    body: DiscountPreviewRequest,
    current_user: User = Depends(get_verified_current_user),
    db: Session = Depends(get_db),
) -> DiscountPreviewResponse:
    """What this code would do to this purchase's price.

    Answers, it does not reserve. Nothing is written, no code is
    consumed, and a member may preview the same code as often as they
    like — the figure is only a statement about right now, and checkout
    works it out again from scratch.

    Three arrangements, one endpoint, because what a member wants to know
    is the same question in each case:

    * **Payment Option, pay in full** — one price, one discounted total.
    * **Payment Option, finite instalments** — the commitment is
      discounted and the answer carries the per-payment schedule, because
      §7 requires the member to see the ACTUAL instalments before
      agreeing to them. A browser dividing a total by four would be
      guessing at the remainder.
    * **Direct Pathway or Gathering** — priced from the experience's own
      price, with no Payment Option named. That is what keeps a code
      scoped to one Option off a standalone purchase of something that
      Option includes.

    Every price comes from the same resolver the matching checkout uses,
    so the number being discounted is the number that would be charged.
    Anything else and preview would be a second opinion rather than a
    preview.

    Invalid codes come back 200 with ``valid: false`` and a reason. See
    ``DiscountPreviewResponse`` for why that is not an error.
    """
    now = datetime.utcnow()
    named_option = bool(body.payment_option_id and body.payment_option_schedule_id)
    named_direct = bool(body.direct_kind and body.direct_id)
    named_offering = bool(body.offering_space_slug and body.offering_slug)

    if named_offering and not (named_option or named_direct):
        # An Offering names a resource; the Option behind it is resolved
        # here, exactly as its checkout door resolves it. From that point
        # this is an ordinary Payment Option preview — which is what it
        # is, and what lets a code scoped to that Option apply.
        option, schedule = _resolve_offering_option(
            db,
            space_slug=body.offering_space_slug,
            offering_slug=body.offering_slug,
            user=current_user,
        )
        named_option = True
        body = body.model_copy(update={
            "payment_option_id": option.id,
            "payment_option_schedule_id": schedule.id,
        })

    if named_option == named_direct:
        # Neither, or both. Neither cannot be priced; both would leave it
        # ambiguous which price the answer described, and an answer about
        # the wrong price is worse than no answer.
        raise HTTPException(
            status_code=422,
            detail=(
                "Name either a payment option and schedule, or a direct "
                "experience — not both and not neither."
            ),
        )

    if named_direct:
        _refuse_code_while_stage4_off(body.code)
        target = _resolve_direct_preview_target(
            db, kind=body.direct_kind, target_id=body.direct_id,
        )
        if target.price_cents <= 0:
            return DiscountPreviewResponse(
                valid=False,
                code=normalise_code(body.code),
                reason=DiscountRejection.NOT_PURCHASABLE.value,
                message="This is already free — no code is needed.",
            )
        try:
            applied = resolve_discount(
                db,
                raw_code=body.code,
                space_id=target.space_id,
                original_cents=target.price_cents,
                currency=target.currency,
                now=now,
                own_attempt=_reservations.ReservationAttempt.for_direct(
                    user_id=current_user.id,
                    kind=body.direct_kind,
                    target_id=body.direct_id,
                ),
            )
        except DiscountError as exc:
            logger.debug(
                "Discount preview refused: reason=%s %s=%s user=%s",
                exc.reason.value, body.direct_kind, body.direct_id,
                current_user.id,
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
            payment_mode="single",
        )

    # ── Payment Option ────────────────────────────────────────────
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

    if schedule_type_row[0] == "recurring_installments":
        _refuse_code_while_stage4_off(body.code)
        resolved_plan = resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=body.payment_option_id,
            payment_option_schedule_id=body.payment_option_schedule_id,
        )
        schedule = resolved_plan.payment_schedule
        try:
            quote = resolve_plan_discount(
                db,
                raw_code=body.code,
                space_id=resolved_plan.space.id,
                payment_option_id=resolved_plan.payment_option.id,
                installment_amount_cents=schedule.installment_amount_cents,
                installment_count=schedule.installment_count,
                currency=resolved_plan.currency,
                now=now,
                own_attempt=_reservations.ReservationAttempt.for_payment_option(
                    user_id=current_user.id,
                    payment_option_id=resolved_plan.payment_option.id,
                    payment_option_schedule_id=schedule.id,
                ),
            )
        except DiscountError as exc:
            logger.debug(
                "Discount preview refused (plan): reason=%s option=%s user=%s",
                exc.reason.value, resolved_plan.payment_option.id,
                current_user.id,
            )
            return DiscountPreviewResponse(
                valid=False,
                code=normalise_code(body.code),
                reason=exc.reason.value,
                message=exc.message,
            )
        instalments = quote.instalments
        return DiscountPreviewResponse(
            valid=True,
            code=quote.applied.code,
            # The commitment, not one payment — which is what the
            # discount was applied to.
            original_amount_cents=instalments.amounts.original_cents,
            discount_amount_cents=instalments.amounts.discount_cents,
            final_amount_cents=instalments.amounts.final_cents,
            currency=instalments.currency,
            payment_mode="plan",
            installment_count=instalments.installment_count,
            installment_amount_cents=instalments.base_cents,
            # Sent even when it equals the base amount, so a client
            # renders the schedule accurately without having to work out
            # whether a remainder exists.
            final_installment_amount_cents=instalments.final_cents,
        )

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
            now=now,
            # Their own hold must not count against them. Without this a
            # member who reserved the last slot reloads the page and is
            # told the code is fully used — by themselves.
            own_attempt=_reservations.ReservationAttempt.for_payment_option(
                user_id=current_user.id,
                payment_option_id=resolved.payment_option.id,
                payment_option_schedule_id=resolved.payment_schedule.id,
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
        payment_mode="single",
    )


def _resolve_offering_option(
    db: Session, *, space_slug: str, offering_slug: str, user: User,
):
    """The Payment Option and pay-in-full schedule behind one Offering.

    The same two helpers its checkout door uses, in the same order, and
    behind the same acquisition guard — so a preview cannot quote a price
    for an Offering the till would refuse. Resolving server-side also
    means a client cannot name an option that sells something else.
    """
    from app.models.offering import Offering, OfferingPricingKind, OfferingStatus
    from app.services import offering_acquisition as acq
    from app.services import offering_commerce
    from app.spaces import area_access, area_policies
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(space_slug, db, user)
    area_access.require_area(db, space, user, area_policies.AREA_OFFERINGS)
    offering = (
        db.query(Offering)
        .filter(Offering.space_id == space.id, Offering.slug == offering_slug)
        .first()
    )
    # A draft is a 404 here as everywhere else, managers included — the
    # same rule the checkout door applies, for the same reason.
    if offering is None or offering.status == OfferingStatus.draft.value:
        raise HTTPException(status_code=404, detail="Offering not found.")

    try:
        acq.guard_acquirable(
            db, offering=offering, space=space, user=user,
            for_pricing=OfferingPricingKind.one_time.value,
        )
    except acq.AcquisitionRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": exc.reason, "message": exc.message},
        ) from exc

    # ``guard_acquirable`` has already established that these resolve and
    # are sellable at the Offering's stated price, so neither is None.
    option = offering_commerce.find_option(db, offering)
    schedule = offering_commerce.pay_in_full_schedule(db, option)
    return option, schedule


@dataclass(frozen=True)
class _DirectPreviewTarget:
    """What a direct purchase would cost, for preview only.

    Deliberately thin. Whether *this member* may buy — already owns it,
    is banned, the Gathering is full — belongs to the guards that own
    those questions and is answered at the till. A preview that
    duplicated them would be a second set of rules to keep in step, and
    getting a price for something you turn out not to be able to buy is
    a far smaller harm than being refused a code you can.
    """

    space_id: str
    price_cents: int
    currency: str


def _resolve_direct_preview_target(
    db: Session, *, kind: str, target_id: str,
) -> _DirectPreviewTarget:
    """The price a direct door would charge, resolved server-side.

    Server-side because the member sends an id, never a price — the same
    rule the whole discount feature rests on.

    The offer must actually be open. For a Pathway that is
    ``pathway_direct_offer``, the one place the direct door's rule lives,
    so a preview cannot quote a price the till would refuse. For a
    Gathering it is ``gathering_tickets.load_and_validate_offer``, which
    is the ticket door's own trusted-offer loader.
    """
    if kind == "pathway":
        pathway = db.query(Pathway).filter(Pathway.id == target_id).first()
        if pathway is None:
            raise HTTPException(status_code=404, detail="Pathway not found.")
        if _direct_offer.direct_purchase_block_reason(pathway) is not None:
            raise HTTPException(
                status_code=400,
                detail="This pathway is not sold individually.",
            )
        return _DirectPreviewTarget(
            space_id=pathway.space_id,
            price_cents=pathway.price_cents or 0,
            currency=(pathway.currency or "AUD").upper(),
        )

    if kind == "gathering":
        from app.services import gathering_tickets as _gt

        event = db.query(Event).filter(Event.id == target_id).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Gathering not found.")
        space = db.query(Space).filter(Space.id == event.space_id).first()
        if space is None:  # pragma: no cover — FK guarantees it
            raise HTTPException(status_code=404, detail="Collective not found.")
        try:
            offer = _gt.load_and_validate_offer(db, space.slug, event.id)
        except _gt.TicketCheckoutError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return _DirectPreviewTarget(
            space_id=offer.space.id,
            price_cents=offer.price_cents,
            currency=offer.currency,
        )

    raise HTTPException(
        status_code=422,
        detail="direct_kind must be 'pathway' or 'gathering'.",
    )


def _run_checkout_shadow(db, *, resolved, recurring: bool, discounted: bool) -> None:
    """Stage 1B.3 — compare the decision just made against the resolver.

    Called after every guard has passed and before Stripe is
    contacted. Reads, compares, logs; changes nothing. Off by default.

    The flag is checked before any work, so with it off this costs a
    boolean and no query.

    A discounted purchase is recorded as ``not_comparable`` rather than
    compared: the resolver prices the *arrangement*, and a discount
    changes what Stripe charges without changing the arrangement. A
    naive comparison would report a disagreement on every discounted
    checkout and bury the real ones.

    Scoped to Gathering Series by asking the Option which Series it
    grants — the unified endpoint is kind-agnostic, so a request never
    names one. An Option granting no Series is simply not this stage's
    business and is skipped before any comparison is built.
    """
    if not settings.purchase_arrangements_checkout_shadow:
        return
    try:
        from app.services import checkout_arrangement_shadow as _ccs

        series_id = _ccs.series_id_for_option(db, resolved.payment_option.id)
        if series_id is None:
            return
        if recurring:
            authoritative = _ccs.authoritative_from_finite_plan(
                series_id=series_id, resolved=resolved,
            )
        else:
            authoritative = _ccs.authoritative_from_pay_in_full(
                series_id=series_id, resolved=resolved,
            )
        if discounted:
            _ccs.not_comparable(authoritative, "discount_applied").log()
            return
        _ccs.compare_checkout_quietly(db, authoritative=authoritative)
    except Exception:  # noqa: BLE001
        # Even assembling the comparison must not disturb a checkout
        # that has already been accepted.
        logger.warning(
            "purchase_arrangements_checkout_shadow verdict=shadow_error "
            "option=%s", getattr(
                getattr(resolved, "payment_option", None), "id", "-",
            ),
            exc_info=True,
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

    # ── Let a member change their payment preference ──────────────
    # A plan row is written before Stripe is contacted, so an
    # abandoned weekly checkout leaves a ``pending_setup`` plan that
    # ``check_same_option_not_active`` reads as an agreement in
    # progress — sealing every payment method on the option, pay in
    # full included. This releases a genuinely abandoned setup first,
    # so the guard below then sees a clean slate and needs no change.
    # Plans that are ``active`` or ``payment_problem``, or that carry
    # a paid instalment or a Stripe arrangement, are left alone and
    # still refused by that guard.
    #
    # The lock is taken before the read so two requests arriving
    # together cannot both decide there is nothing in progress and
    # both create a plan.
    _supersession.lock_member_option(
        db, user_id=current_user.id, payment_option_id=body.payment_option_id,
    )
    _pending = _supersession.resolve_pending_setup(
        db,
        user=current_user,
        payment_option_id=body.payment_option_id,
        requested_schedule_id=body.payment_option_schedule_id,
        # Stage 4A — so that reusing a live Stripe page cannot re-offer a
        # price the member is no longer being quoted. The code is not
        # validated or priced here; it is resolved from scratch below,
        # after this returns. Passing it only narrows which pending
        # setups count as "the same purchase, retried".
        requested_discount_code=body.discount_code,
        now=now,
    )
    if _pending.kind == "reused" and _pending.checkout_url:
        # Same payment method, and their Stripe page is still live.
        # Opening a second one would be a second way to pay once.
        logger.info(
            "Unified checkout: reusing live plan setup=%s plan=%s user=%s",
            _pending.plan.provider_setup_session_id if _pending.plan else "-",
            _pending.plan.id if _pending.plan else "-", current_user.id,
        )
        return UnifiedCheckoutResponse(
            checkout_url=_pending.checkout_url,
            transaction_id=_pending.plan.id if _pending.plan else "",
            free=False,
        )

    if is_recurring:
        if body.discount_code and not settings.universal_discount_codes_enabled:
            # Stage 4 is not switched on, so this is still the pay-in-full
            # feature it has been since v1 — same refusal, same wording.
            #
            # Refused rather than ignored, because accepting the code and
            # charging the full plan would tell the member something
            # untrue at the moment they commit. The frontend hides the
            # field here while the flag is off; this is the guard for
            # anything that posts directly.
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
        _pathway_commerce.check_sellable_or_raise(
            db, recurring_resolved.payment_option,
        )
        check_same_option_not_active(
            db, user=current_user,
            payment_option=recurring_resolved.payment_option, now=now,
        )
        _run_checkout_shadow(
            db, resolved=recurring_resolved, recurring=True,
            discounted=bool(body.discount_code),
        )

        # ── Discount: revalidated here, independently of any preview ──
        # Same discipline as pay-in-full below. The preview the member
        # saw is not evidence: it described an earlier moment, it is not
        # signed, and the code may have expired or filled up since. So
        # the code is resolved again from scratch against the schedule's
        # own figures, and the slot is held before Stripe is contacted.
        #
        # The discount applies to the WHOLE commitment, not to one
        # instalment — see ``resolve_plan_discount``.
        plan_hold = None
        try:
            plan_hold = _hold_for_plan(
                db, raw_code=body.discount_code,
                resolved=recurring_resolved, user=current_user, now=now,
            )
        except DiscountError as exc:
            # 409, not 422: the request was well formed and was valid
            # when the member saw the preview. What changed is the
            # world.
            raise HTTPException(status_code=409, detail=exc.message) from exc
        except _hold.LiveSessionExists as live:
            return UnifiedCheckoutResponse(
                checkout_url=live.checkout_url,
                transaction_id=live.transaction_id,
                free=False,
            )

        outcome = start_finite_plan_setup(
            db,
            resolved=recurring_resolved,
            payer=current_user,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            now=now,
            discounted=plan_hold,
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
    # Archiving a Pathway has to stop new purchases of it. Enforced at
    # the door rather than by archiving the creator's Payment Options
    # behind their back — ``pathway_commerce.unsellable_reason`` sets
    # out why, and what a bundle deliberately keeps selling. Sits
    # before the free path below, so a $0 archived Pathway is refused
    # too.
    _pathway_commerce.check_sellable_or_raise(db, resolved.payment_option)
    check_same_option_not_active(
        db, user=current_user,
        payment_option=resolved.payment_option, now=now,
    )
    # Offerings carry rules the two guards above do not know about —
    # retired, nothing downloadable, already owned, the creator's plan
    # no longer permits paid selling. ``POST /api/checkout/offering``
    # checks all of them before delegating here; this is the same check
    # at this entrance, so the rules belong to the purchase rather than
    # to whichever door was used.
    #
    # A no-op for every Pathway and Gathering option — it returns
    # immediately unless ``attaches_to_kind == 'offering'``.
    try:
        _offering_acq.guard_option_purchase(
            db, payment_option=resolved.payment_option, user=current_user,
        )
    except _offering_acq.AcquisitionRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": exc.reason, "message": exc.message},
        ) from exc

    _run_checkout_shadow(
        db, resolved=resolved, recurring=False,
        discounted=bool(body.discount_code),
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
    #
    # The hold protocol — reserve before Stripe, hand back a live page,
    # verify a stale one, persist parameters, release only on knowledge —
    # lives in ``discount_checkout_hold`` and is shared with the direct
    # purchase doors. See that module for why it is one implementation.
    hold = None
    try:
        hold = _hold_for_pay_in_full(
            db, raw_code=body.discount_code, resolved=resolved,
            user=current_user, now=now,
        )
    except DiscountError as exc:
        # 409, not 422: the request was well formed and was valid when
        # the member saw the preview. What changed is the world.
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except _hold.LiveSessionExists as live:
        return UnifiedCheckoutResponse(
            checkout_url=live.checkout_url,
            transaction_id=live.transaction_id,
            free=False,
        )
    applied: AppliedDiscount | None = hold.applied if hold else None

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
            txn_id_override=hold.txn_id if hold else None,
            session_expires_at=hold.session_expires_at if hold else None,
            session_idempotency_key=hold.idempotency_key if hold else None,
            on_session_params=hold.persist_params if hold else None,
            txn_transaction_type_override=(
                PaymentTransactionType.member_payment_option_purchase
            ),
        )
    except Exception:
        # Stripe refused, or the ledger write failed. Either way the slot
        # may need to go back — ``abandon`` decides, and only releases
        # when it knows no payment page exists.
        if hold is not None:
            hold.abandon(now=now)
        raise
    if hold is not None:
        hold.attach(
            session_id=session.id, session_url=session.url,
            txn_id=txn.id, now=now,
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
        # Grant or legacy column — a grants-first Option has no
        # ``pathway_id``, and comparing it to the Pathway's id refused
        # the very Option the member had just been shown.
        if not pathway_options.option_sells_pathway(
            db, option=pre_option, pathway_id=pathway.id,
        ):
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

        # Same payment-preference release as the unified endpoint. This
        # wrapper is still live — ``PaymentOptionSelector`` drives it
        # through ``CheckoutButton``, including for recurring schedules —
        # so an abandoned plan would otherwise still seal this route even
        # though /api/checkout had been fixed.
        _supersession.lock_member_option(
            db, user_id=current_user.id,
            payment_option_id=body.payment_option_id,
        )
        _pending = _supersession.resolve_pending_setup(
            db,
            user=current_user,
            payment_option_id=body.payment_option_id,
            requested_schedule_id=body.payment_option_schedule_id,
            # Stage 4A — this wrapper establishes discounted plans too
            # (``_hold_for_plan`` below), so it carried the same defect:
            # reusing a live page priced without the code. Same argument
            # as the unified endpoint.
            requested_discount_code=body.discount_code,
            now=now,
        )
        if _pending.kind == "reused" and _pending.checkout_url:
            logger.info(
                "FIP4A pathway: reusing live plan setup plan=%s user=%s",
                _pending.plan.id if _pending.plan else "-", current_user.id,
            )
            return PathwayCheckoutResponse(checkout_url=_pending.checkout_url)

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
            _refuse_code_while_stage4_off(body.discount_code)
            try:
                plan_hold = _hold_for_plan(
                    db, raw_code=body.discount_code,
                    resolved=recurring_resolved, user=current_user, now=now,
                )
            except DiscountError as exc:
                raise HTTPException(
                    status_code=409, detail=exc.message,
                ) from exc
            except _hold.LiveSessionExists as live:
                return PathwayCheckoutResponse(checkout_url=live.checkout_url)
            outcome = start_finite_plan_setup(
                db,
                resolved=recurring_resolved,
                payer=current_user,
                success_url=body.success_url,
                cancel_url=body.cancel_url,
                now=now,
                discounted=plan_hold,
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

        _refuse_code_while_stage4_off(body.discount_code)
        try:
            option_hold = _hold_for_pay_in_full(
                db, raw_code=body.discount_code, resolved=resolved,
                user=current_user, now=now,
            )
        except DiscountError as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc
        except _hold.LiveSessionExists as live:
            return PathwayCheckoutResponse(checkout_url=live.checkout_url)

        # Legacy metadata continuity: include ``pathway_id`` on the
        # Stripe Session + payment_intent, and populate
        # ``PaymentTransaction.pathway_id`` for downstream reporting.
        try:
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
                applied_discount=(
                    option_hold.applied if option_hold else None
                ),
                txn_id_override=option_hold.txn_id if option_hold else None,
                session_expires_at=(
                    option_hold.session_expires_at if option_hold else None
                ),
                session_idempotency_key=(
                    option_hold.idempotency_key if option_hold else None
                ),
                on_session_params=(
                    option_hold.persist_params if option_hold else None
                ),
            )
        except Exception:
            if option_hold is not None:
                option_hold.abandon(now=now)
            raise
        if option_hold is not None:
            option_hold.attach(
                session_id=session.id, session_url=session.url,
                txn_id=_txn.id, now=now,
            )
        return PathwayCheckoutResponse(checkout_url=session.url)

    # ── Option-less direct path (pathway.price_cents source) ──────
    #
    # The member did not name a Payment Option, so this request is a
    # direct purchase and nothing else. It is priced from
    # ``pathway.price_cents`` and can never reach an Option's price —
    # the two doors are separate requests with separate identifiers,
    # which is why "charge the arrangement the member selected" needs
    # no arbitration here.
    #
    # What *is* decided here is whether the direct door is open at all,
    # and the Stage 2B gate changes which column answers that:
    #
    #   Gate shut (today) — ``pricing_mode``. A Pathway moved to
    #     ``payment_options`` refuses, because that mode means "an
    #     Option prices this now" and the stale ``price_cents`` beside
    #     it is dormant by design.
    #
    #   Gate open — ``direct_purchase_enabled``. A mode cannot describe
    #     two simultaneous doors, so the question becomes a property of
    #     this door alone. Still an explicit refusal, and still refused
    #     by default: migration 183 switched the column on only for the
    #     Pathways this door already sold, so opening the gate puts
    #     nothing new on sale by itself.
    #
    # Neither branch infers an offer from the presence of a price.
    #
    # The rule itself lives in ``pathway_direct_offer`` because the
    # member payload must reach the same answer — a price shown and
    # then refused, or a live offer rendered invisible, are the two
    # failures that matter here. The wording stays local: these
    # messages are the till's, and are more specific than a shared
    # reason code could be.
    block = _direct_offer.direct_purchase_block_reason(
        pathway, check_status=False,  # already refused above, for every shape
    )
    if block == _direct_offer.REASON_REQUIRES_OPTION:
        raise HTTPException(
            status_code=400,
            detail=(
                "This pathway requires selecting a payment option. Please "
                "choose one and try again."
            ),
        )
    if block == _direct_offer.REASON_NOT_OFFERED:
        raise HTTPException(
            status_code=400,
            detail=(
                "This pathway is not sold individually. Please choose one "
                "of its payment options and try again."
            ),
        )
    if block == _direct_offer.REASON_NOT_ONE_TIME:
        raise HTTPException(
            status_code=400,
            detail="Only one-time purchase pathways can be checked out via this endpoint.",
        )
    if block == _direct_offer.REASON_NO_PRICE:
        raise HTTPException(status_code=400, detail="Pathway has no valid price.")

    # Rule F — the legacy single-Pathway door. It does not go through
    # the PaymentOption orchestrators, so it needs the ban guard of its
    # own or it is a way past one. Rule E is deliberately NOT applied:
    # this endpoint only ever sells ``one_time`` access, whose gate
    # reads the entitlement and never asks about membership.
    from app.services.checkout_orchestration import check_not_banned_or_raise

    check_not_banned_or_raise(db, user=current_user, space=pathway.space)

    # ── Stage 4 — a Collective-wide code on the direct door ───────
    # The code is resolved against the Pathway's OWN price, because that
    # is what this door charges. No Payment Option is named, and that is
    # the point: ``validate_code`` refuses a code scoped to one Payment
    # Option when no option is named, so a code restricted to
    # "EMBODY Term 4" cannot be spent here on a Pathway that Option
    # happens to include. §4's scope integrity, enforced by the rule
    # that already existed rather than by a new one.
    _refuse_code_while_stage4_off(body.discount_code)
    try:
        direct_hold = _hold_for_direct(
            db, raw_code=body.discount_code,
            space_id=pathway.space_id, kind="pathway", target_id=pathway.id,
            user=current_user, price_cents=pathway.price_cents,
            currency=(pathway.currency or "AUD").upper(), now=now,
        )
    except DiscountError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except _hold.LiveSessionExists as live:
        return PathwayCheckoutResponse(checkout_url=live.checkout_url)

    try:
        session = _legacy_pathway_price_stripe_session(
            db, pathway=pathway, payer=current_user,
            success_url=body.success_url, cancel_url=body.cancel_url, now=now,
            hold=direct_hold,
        )
    except Exception:
        if direct_hold is not None:
            direct_hold.abandon(now=now)
        raise
    return PathwayCheckoutResponse(checkout_url=session.url)


def _legacy_pathway_price_stripe_session(
    db: Session, *, pathway: Pathway, payer: User,
    success_url: str, cancel_url: str, now: datetime,
    hold: Any = None,
):
    """Option-less pathway-purchase path — reads price directly
    from ``pathway.price_cents``. Preserved for the R.E.A.L. Journey
    shape and other pre-PaymentOptions pathways still in use. Not
    exported for reuse; the shared orchestration is grants/option-based
    only.

    ``hold`` is a Stage 4 ``DiscountHold`` or ``None``. When present the
    Session and the ledger row carry the DISCOUNTED amount, the
    transaction id the reservation already set aside, and the Session
    expiry and idempotency key the reservation pinned down — so a replay
    recovers this request rather than making a second one. With no hold
    every line below is exactly what it was."""
    import stripe as _stripe
    from uuid import uuid4 as _uuid4

    from app.models.payment import (
        PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
        PaymentTransactionType, PayoutStatus,
    )
    from app.services.checkout_orchestration import (
        NO_ACTIVE_CREATOR_PLAN_DETAIL,
        PLAN_FORBIDS_PAID_OFFERS_DETAIL,
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
            detail=NO_ACTIVE_CREATOR_PLAN_DETAIL,
        ) from exc
    if not fee_context.permits_paid_offers:
        raise HTTPException(
            status_code=403,
            detail=PLAN_FORBIDS_PAID_OFFERS_DETAIL,
        )
    currency = (pathway.currency or "AUD").upper()
    # What is actually charged. The platform fee follows the discounted
    # amount, not the list price — §12, and the same rule
    # ``checkout_orchestration`` already applies on the Option doors.
    # Nothing is recomputed here: the figure comes from the reservation,
    # which froze it when the slot was taken.
    gross = (
        hold.applied.amounts.final_cents if hold is not None
        else pathway.price_cents
    )
    platform_fee = round(gross * fee_context.fee_bps / 10000)
    net_creator = gross - platform_fee
    # Same snapshot rule as every other purchase path: decided here, frozen
    # on the row, never re-derived from the creator's later Connect state.
    payout = _resolve_payout_model(
        db,
        creator_user_id=fee_context.creator_id,
        is_platform_owned=fee_context.is_platform_owned,
    )
    # The reservation set aside a transaction id before Stripe was
    # called, so a recovery replay identifies this same purchase instead
    # of creating a second one.
    txn_id = (
        hold.txn_id if hold is not None and hold.txn_id else str(_uuid4())
    )

    # Built as a dict rather than passed inline so a discount hold can
    # persist the EXACT request before it is sent. Without that, a crash
    # between the call and recording its id leaves a reservation that
    # looks like it never reached Stripe — and releasing it would free a
    # slot the member may already have paid for.
    session_params: dict[str, Any] = {
        "mode": "payment",
        "line_items": [{
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
        "metadata": {
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
        "payment_intent_data": {
            "metadata": {
                "transaction_id": txn_id,
                "pathway_id": pathway.id,
                "payer_user_id": payer.id,
            }
        },
        "customer_email": payer.email,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if hold is not None:
        # The same instant the reservation is judged stale against, so
        # "past expiry" cannot mean two different things on the two sides
        # of the boundary. Set before the params are persisted, because a
        # replay must re-send this absolute value rather than a freshly
        # derived one.
        session_params["expires_at"] = hold.expires_at_unix
        hold.persist_params(session_params)

    try:
        session = _stripe.checkout.Session.create(
            **session_params,
            **(
                {"idempotency_key": hold.idempotency_key}
                if hold is not None else {}
            ),
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
            PayoutStatus.pending if payout.manual_payout_applies
            else PayoutStatus.not_applicable
        ),
        payout_model=payout.payout_model,
        connect_destination_account_id=payout.destination_account_id,
        connect_transfer_status=payout.initial_transfer_status,
        stripe_mode=settings.stripe_mode,
        # The immutable record of how this charge was reached. Read by
        # the creator's payment views and by the member's confirmation,
        # so a discounted purchase stays explicable after the code is
        # edited or deleted.
        discount_snapshot_json=(
            hold.applied.snapshot if hold is not None else None
        ),
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.commit()
    if hold is not None:
        hold.attach(
            session_id=session.id, session_url=session.url,
            txn_id=txn_id, now=now,
        )
    logger.info(
        "Legacy pathway checkout: txn=%s session=%s pathway=%s user=%s "
        "discount=%s amount=%d",
        txn_id, session.id, pathway.id, payer.id,
        hold.applied.code if hold is not None else "-", gross,
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

    # ── Stage 4 — a code on the Series door ───────────────────────
    # §15: Series purchasing stays on the existing arrangement model, so
    # this is a Payment Option purchase and the code is resolved against
    # the Option exactly as it is at ``POST /api/checkout``. A code
    # scoped to THIS Option applies; one scoped to another does not.
    _refuse_code_while_stage4_off(body.discount_code)
    try:
        series_hold = _hold_for_pay_in_full(
            db, raw_code=body.discount_code, resolved=resolved,
            user=current_user, now=now,
        )
    except DiscountError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except _hold.LiveSessionExists as live:
        return GatheringSeriesCheckoutResponse(checkout_url=live.checkout_url)

    # Legacy metadata: include ``series_id`` on the Session +
    # payment_intent so any downstream tooling that inspected it
    # continues to see it. ``pathway_id`` is deliberately absent
    # (matches the pre-B4B series endpoint).
    try:
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
            applied_discount=series_hold.applied if series_hold else None,
            txn_id_override=series_hold.txn_id if series_hold else None,
            session_expires_at=(
                series_hold.session_expires_at if series_hold else None
            ),
            session_idempotency_key=(
                series_hold.idempotency_key if series_hold else None
            ),
            on_session_params=(
                series_hold.persist_params if series_hold else None
            ),
        )
    except Exception:
        if series_hold is not None:
            series_hold.abandon(now=now)
        raise
    if series_hold is not None:
        series_hold.attach(
            session_id=session.id, session_url=session.url,
            txn_id=_txn.id, now=now,
        )
    return GatheringSeriesCheckoutResponse(checkout_url=session.url)


# ---------------------------------------------------------------------------
# Offerings: POST /api/checkout/offering
# ---------------------------------------------------------------------------


@router.post(
    "/offering",
    response_model=OfferingCheckoutResponse,
    # Declared as a route dependency, not called in the body. The
    # structural guard in ``test_offering_creator_api`` requires every
    # Offering route to carry the gate where the router can see it, and
    # it is right to: a dependency cannot be skipped by an early return
    # and shows up in the route table, where an in-body call is
    # invisible to anything auditing which routes are flagged.
    #
    # Per-route rather than router-level, because this router also
    # serves Pathway and Gathering checkout, which must keep working
    # while Offerings is off.
    dependencies=[Depends(_require_offerings_enabled)],
)
def create_offering_checkout_session(
    body: OfferingCheckoutRequest,
    current_user: User = Depends(get_verified_current_user),  # SEC-009
    db: Session = Depends(get_db),
) -> OfferingCheckoutResponse:
    """Buy one paid Offering.

    A thin wrapper, and thin on purpose. Everything that charges money
    — the discount revalidation and slot reservation, the fee basis
    points, the Connect payout model, the mandatory fulfilment
    snapshot, the Stripe Session, the ledger row, the idempotency keys
    — is the unified endpoint's, unchanged. This function does three
    things the unified endpoint cannot do for itself and then hands
    over:

      1. **Resolves the Offering from its slugs.** The member knows
         which resource they want; they have never heard of a Payment
         Option. Resolving server-side also means a client cannot name
         an option that sells something else.

      2. **Applies the Offering's own acquisition rules**, through the
         same ``check_acquirable`` the free path and the detail page
         use: published, not retired, has files a buyer could actually
         download, the creator's plan permits paid selling, and the
         commerce rows can take a payment at the price the page
         stated.

      3. **Refuses a repurchase of something already owned.**
         ``check_same_option_not_active`` cannot see this: it looks for
         an active AccessPass or PathwayEntitlement, and an Offering
         purchase produces neither. Without this guard a member could
         be charged twice for the same file.

    Access is not granted here. It is granted when Stripe confirms the
    payment, by ``checkout.session.completed`` → the shared fulfilment
    service → the option's ``grant_kind='offering'`` grant. Starting
    checkout grants nothing: no entitlement, no Collective membership.
    An abandoned or failed payment therefore leaves no trace beyond a
    ``pending`` ledger row, which is what Stripe's own expiry and the
    existing reconciliation sweeps already handle.
    """
    from app.services import offering_acquisition as acq
    from app.services import offering_commerce
    from app.models.offering import Offering, OfferingPricingKind, OfferingStatus
    from app.spaces import area_access, area_policies
    from app.spaces.routes import _get_space_visible_to

    space = _get_space_visible_to(body.space_slug, db, current_user)
    area_access.require_area(
        db, space, current_user, area_policies.AREA_OFFERINGS,
    )
    offering = (
        db.query(Offering)
        .filter(
            Offering.space_id == space.id,
            Offering.slug == body.offering_slug,
        )
        .first()
    )
    # A draft is a 404 here as everywhere else, managers included:
    # previewing an unreleased Offering must not be able to produce a
    # real charge in real purchase history.
    if offering is None or offering.status == OfferingStatus.draft.value:
        raise HTTPException(status_code=404, detail="Offering not found.")

    # Already theirs. 409 with the reason, so the client can switch the
    # button to "Open in Your Collection" rather than showing an error.
    if acq.already_owns(
        db, user_id=current_user.id, offering_id=offering.id,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "already_owned",
                "message": "This Offering is already in Your Collection.",
            },
        )

    try:
        acq.guard_acquirable(
            db, offering=offering, space=space, user=current_user,
            for_pricing=OfferingPricingKind.one_time.value,
        )
    except acq.AcquisitionRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": exc.reason, "message": exc.message},
        ) from exc

    # ``guard_acquirable`` has already established that these resolve
    # and are sellable at the Offering's stated price — it refuses with
    # ``not_sellable`` otherwise — so neither can be None here.
    option = offering_commerce.find_option(db, offering)
    schedule = offering_commerce.pay_in_full_schedule(db, option)

    logger.info(
        "Offering checkout: offering=%s option=%s user=%s price=%s",
        offering.id, option.id, current_user.id, offering.price_cents,
    )
    unified = create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            discount_code=body.discount_code,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        ),
        current_user=current_user,
        db=db,
    )
    return OfferingCheckoutResponse(
        checkout_url=unified.checkout_url,
        transaction_id=unified.transaction_id,
        free=unified.free,
    )


# ---------------------------------------------------------------------------
# Stage 3E.3 — what did I just buy?
# ---------------------------------------------------------------------------


class PurchaseSummaryResponse(BaseModel):
    """One member's view of one purchase. Read-only."""

    transaction_id: str
    option_name: str | None = None
    space_name: str | None = None
    space_slug: str | None = None
    state: str
    amount_cents: int | None = None
    currency: str | None = None
    payment_mode: str = "single"
    installments_paid: int | None = None
    installments_expected: int | None = None
    installment_amount_cents: int | None = None
    total_expected_cents: int | None = None
    interval: str | None = None
    items: list[dict] = []


@router.get("/purchase-summary", response_model=PurchaseSummaryResponse)
def get_purchase_summary(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseSummaryResponse:
    """The purchase behind a Stripe Checkout Session, for its buyer.

    Why this exists
    ---------------
    A member returning from checkout lands back on whichever page they
    started from, and that page can only tell them about itself. Buying
    a bundle containing a Gathering and a Pathway, they saw "You're in"
    on the Gathering and no sign the Pathway existed.

    Read-only, and deliberately so. Nothing here grants, books, writes
    or retries: fulfilment belongs to the webhook, and a confirmation
    screen that could complete a purchase would be a second way to
    fulfil one. Revisiting an old success URL therefore does nothing at
    all beyond reading.

    Ownership, not possession of a link
    -----------------------------------
    A Stripe session id is long and unguessable but it is still only a
    string in a URL — shoulder-surfed, pasted into a chat, left in a
    browser history. So the check is that the requester *is the payer*,
    and a transaction belonging to somebody else answers 404 rather
    than 403: a different status would confirm the purchase exists.

    The state comes from the ledger rather than from the
    ``?checkout=success`` parameter that brought them here. That
    parameter is a trigger to ask a question, never its answer.
    """
    from app.services.purchase_included_summary import build_purchase_summary

    if not session_id or "{" in session_id:
        # An un-substituted ``{CHECKOUT_SESSION_ID}`` template: the
        # free-purchase path returns our own success_url without
        # passing through Stripe, so the placeholder arrives intact.
        raise HTTPException(status_code=404, detail="Purchase not found.")

    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .first()
    )
    if txn is None or txn.payer_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Purchase not found.")

    summary = build_purchase_summary(db, txn=txn, user_id=current_user.id)
    return PurchaseSummaryResponse(**summary.as_payload())
