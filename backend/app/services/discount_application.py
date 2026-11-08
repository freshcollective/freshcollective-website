"""Turning a typed-in code into an amount to charge.

``discount_pricing`` is pure: it knows the rules and the arithmetic but
never touches a database or a clock it wasn't handed. This module is the
layer that reads. It finds the code, counts what has actually been
redeemed, asks ``discount_pricing`` whether the code may be used and
what it is worth, and hands back a figure.

There is one function for that, and both the preview surface and
checkout call it. That is the point of the module: a preview that
computed a price by a different route than the charge would eventually
disagree with it, and the member would be the one to find out. Same
inputs, same code path, same answer — with a fresh read each time,
because the two calls are separated by however long it takes a person to
read a page and click a button, and a code can expire or fill up in that
gap.

Nothing here writes. Recording that a code was *redeemed* belongs to
fulfilment (Work Item 6), which happens when Stripe confirms payment —
not when a member asks what something would cost.

The slot problem this module once listed as unsolved is solved:
``discount_reservations`` holds a code's slot before Stripe is called,
counts it against the limit alongside redemptions, and converts it to a
redemption exactly once on payment. ``consumed_slots`` is the figure the
limit is measured against.

Two resolvers, one rule set. :func:`resolve_discount` prices a single
charge — a pay-in-full purchase, a direct Pathway, a ticket.
:func:`resolve_plan_discount` prices a finite plan, where the discount
applies to the whole commitment and the instalments derive from the
discounted total. They share every eligibility rule and differ only in
what "the price" is, which is the one thing that genuinely differs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.money import MIN_PAID_CHARGE_CENTS
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.services.discount_reservations import ReservationAttempt, consumed_slots
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountedInstalments,
    DiscountError,
    DiscountRejection,
    build_snapshot,
    compute_discount,
    discount_instalment_plan,
    normalise_code,
    validate_code,
)

logger = logging.getLogger(__name__)


def find_code(db: Session, *, raw_code: str | None, space_id: str) -> DiscountCode | None:
    """Look a code up within one Collective, case-insensitively.

    Scoped to ``space_id`` in the query itself, not checked afterwards,
    so a code belonging to another Collective is never loaded — let
    alone reported on.
    """
    code = normalise_code(raw_code)
    if not code:
        return None
    return (
        db.query(DiscountCode)
        .filter(DiscountCode.space_id == space_id, DiscountCode.code == code)
        .first()
    )


def _eligible_code(
    db: Session,
    *,
    raw_code: str | None,
    space_id: str,
    payment_option_id: str | None,
    now: datetime,
    own_attempt: "ReservationAttempt | None",
) -> DiscountCode:
    """Find a code and check every eligibility rule, or raise.

    Shared verbatim by both resolvers, which is the point: a pay-in-full
    purchase, a direct Pathway and a finite plan are eligible on
    identical terms, and the only thing that differs between them is what
    "the price" means. Two copies of these rules would drift.

    ``payment_option_id`` is ``None`` for a direct purchase, and that is
    load-bearing rather than incidental: ``validate_code`` already
    refuses a Payment Option-scoped code when no option is named, so a
    code restricted to EMBODY Term 4 cannot reach a standalone purchase
    of a Pathway that Option happens to include. The scope distinction
    the brief asks for is existing behaviour, not a new rule.
    """
    code = find_code(db, raw_code=raw_code, space_id=space_id)

    if code is not None:
        # ``validate_code`` reads ``redemption_count`` off the row. Give
        # it the ledger's answer rather than the cached one. Assigning to
        # the attribute in the identity map would dirty the row and flush
        # a pointless UPDATE, so the true count goes to validate_code by
        # way of a lightweight stand-in.
        # Slots, not redemptions: a code with one use left and one live
        # reservation against it is unavailable, even though nothing has
        # been redeemed yet. Counting redemptions alone here would let two
        # members reach Stripe with a one-use code.
        code_for_validation = _WithLiveCount(
            code, consumed_slots(db, code.id, excluding_attempt=own_attempt),
        )
    else:
        code_for_validation = None

    # Raises DiscountError for not-found, wrong Collective, inactive,
    # expired, limit reached, wrong Payment Option.
    validate_code(
        code_for_validation,
        space_id=space_id,
        payment_option_id=payment_option_id,
        now=now,
    )
    assert code is not None  # validate_code raises on None
    return code


def resolve_discount(
    db: Session,
    *,
    raw_code: str | None,
    space_id: str,
    #: ``None`` for a direct purchase, which has no Payment Option. Not a
    #: convenience default — see :func:`_eligible_code`.
    payment_option_id: str | None = None,
    original_cents: int,
    currency: str,
    now: datetime | None = None,
    #: The purchase attempt asking. Its own held reservation is excluded
    #: from the slot count, so a member who already holds the last slot
    #: is not told their own code is fully used when they retry or
    #: reload.
    own_attempt: "ReservationAttempt | None" = None,
) -> AppliedDiscount:
    """Validate a code against one charge and price it, or raise.

    One charge: a pay-in-full Payment Option, a direct Pathway, a
    standalone Gathering ticket, a direct Offering. For a finite plan use
    :func:`resolve_plan_discount`, which discounts the commitment rather
    than a payment.

    Raises :class:`DiscountError` carrying the reason, which callers map
    to their own shape — a preview reports it, checkout refuses with it.
    """
    moment = now or datetime.utcnow()
    code = _eligible_code(
        db, raw_code=raw_code, space_id=space_id,
        payment_option_id=payment_option_id, now=moment,
        own_attempt=own_attempt,
    )

    # Raises DiscountError on currency mismatch for fixed-amount codes.
    amounts = compute_discount(
        original_cents=original_cents,
        currency=currency,
        discount_type=code.discount_type,
        percent_bps=code.percent_bps,
        amount_cents=code.amount_cents,
        discount_currency=code.currency,
    )

    if amounts.final_cents <= 0:
        # A fixed-amount code can be worth more than the offer it is
        # used on, and clamping leaves nothing to charge. Free access is
        # a complimentary pass, granted deliberately — not something a
        # code should be able to produce as a side effect of a price
        # changing underneath it. Same stance as the 99% ceiling on
        # percentage codes.
        raise DiscountError(
            DiscountRejection.NOT_PURCHASABLE,
            "That code would make this offer free. Complimentary access is "
            "arranged directly with the Collective rather than through a code.",
        )

    if amounts.final_cents < MIN_PAID_CHARGE_CENTS:
        # Something is left to charge, but too little for a payment
        # provider to take — Stripe refuses amounts this small, and left
        # alone it would surface as a provider error at the moment of
        # purchase rather than as something anyone could act on.
        #
        # The discount is NOT quietly trimmed to clear the floor. A code
        # that silently stopped being worth what it says is a worse
        # answer than one that is refused: the Creator wrote "half off"
        # and a member who is charged something else has been told a
        # small lie by the system rather than by anyone.
        raise DiscountError(
            DiscountRejection.BELOW_MINIMUM,
            "That code leaves too little to charge on this offer. The "
            "smallest payment we can take is "
            f"{MIN_PAID_CHARGE_CENTS / 100:.2f} {amounts.currency}.",
        )

    return AppliedDiscount(
        code=normalise_code(code.code),
        discount_code_id=code.id,
        amounts=amounts,
        snapshot=build_snapshot(code, amounts),
    )


@dataclass(frozen=True)
class DiscountedPlanQuote:
    """A discounted finite plan, priced and split. What checkout agrees to.

    ``applied`` is the discount against the WHOLE commitment — its
    ``amounts.original_cents`` is the plan's undiscounted total, not one
    instalment — and ``instalments`` is the schedule derived from it.
    Carried together because a plan row needs both, and because reading
    one without the other is how a plan ends up storing a discounted
    total against undiscounted instalments.
    """

    applied: AppliedDiscount
    instalments: DiscountedInstalments


def resolve_plan_discount(
    db: Session,
    *,
    raw_code: str | None,
    space_id: str,
    payment_option_id: str,
    installment_amount_cents: int,
    installment_count: int,
    currency: str,
    now: datetime | None = None,
    own_attempt: ReservationAttempt | None = None,
) -> DiscountedPlanQuote:
    """Validate a code against a finite plan and price the whole plan.

    Same eligibility rules as :func:`resolve_discount` — the shared
    :func:`_eligible_code` is the only place they live. What differs is
    the price: a plan's is its commitment, ``installment_amount_cents ×
    installment_count``, and the discount reduces that. The instalments
    then derive from the discounted total.

    The other way round — discounting each instalment — would look
    identical on an exact division and quietly give away a different
    amount on every other one. Worse, "20% off" would stop meaning 20%
    off what the member committed to.

    Raises :class:`DiscountError`, including ``BELOW_MINIMUM`` when the
    discount leaves an *instalment* too small to charge even though the
    total is fine. That is the rule a plan has and a single charge does
    not, and it is why this is a second function rather than a flag on
    the first.
    """
    moment = now or datetime.utcnow()
    code = _eligible_code(
        db, raw_code=raw_code, space_id=space_id,
        payment_option_id=payment_option_id, now=moment,
        own_attempt=own_attempt,
    )

    instalments = discount_instalment_plan(
        installment_amount_cents=installment_amount_cents,
        installment_count=installment_count,
        currency=currency,
        discount_type=code.discount_type,
        percent_bps=code.percent_bps,
        amount_cents=code.amount_cents,
        discount_currency=code.currency,
        minimum_charge_cents=MIN_PAID_CHARGE_CENTS,
    )

    applied = AppliedDiscount(
        code=normalise_code(code.code),
        discount_code_id=code.id,
        amounts=instalments.amounts,
        # The snapshot records the commitment-level figures, plus the
        # schedule they were split into. A plan's charge history has to
        # be explicable years later, when the code may have been edited
        # or deleted — and "A$130 total, 43.33/43.33/43.34" is the part
        # that explains it.
        snapshot={
            **build_snapshot(code, instalments.amounts),
            "payment_mode": "plan",
            "installment_count": instalments.installment_count,
            "installment_amount_cents": instalments.base_cents,
            "final_installment_amount_cents": instalments.final_cents,
        },
    )
    return DiscountedPlanQuote(applied=applied, instalments=instalments)


class _WithLiveCount:
    """A read-only view of a code whose redemption count is the ledger's.

    ``validate_code`` reads its inputs with ``getattr``, so a stand-in
    that forwards everything except the one attribute we want to correct
    is enough — and it keeps the ORM row clean, which matters because
    dirtying it here would flush an UPDATE during what is meant to be a
    read.
    """

    __slots__ = ("_row", "redemption_count")

    def __init__(self, row: DiscountCode, count: int) -> None:
        object.__setattr__(self, "_row", row)
        object.__setattr__(self, "redemption_count", count)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_row"), name)
