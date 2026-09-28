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

That leaves one thing unsolved, named here because this module is where
the fix belongs. A limited code's last slot is not held by anything, so
two members can both reach Stripe with it. The answer cannot be to
refuse the loser once payment has succeeded: by then their card has
been charged, and handing someone a refund they did not ask for is
worse than the double-spend. Work Item 6 owes an atomic pre-payment
*reservation* — taken when a real checkout starts, counted against the
limit alongside redemptions, released when a session is abandoned or
expires, converted to a redemption exactly once on payment, and
refusing a competing checkout for the last slot before Stripe is called.
Deactivation must stop new reservations, and a code with live ones must
not be hard-deleted out from under them.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.money import MIN_PAID_CHARGE_CENTS
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountError,
    DiscountRejection,
    build_snapshot,
    compute_discount,
    normalise_code,
    validate_code,
)

logger = logging.getLogger(__name__)


def live_redemption_count(db: Session, discount_code_id: str) -> int:
    """How many times this code has actually been redeemed.

    Counted from the ledger rather than read from
    ``DiscountCode.redemption_count``, for the same reason the Creator
    CRUD does: the ledger is the record of what happened, and the column
    is a cache of it. A cache that drifts low would let a limited code
    over-redeem, which is the one failure this check exists to prevent.
    """
    return (
        db.query(func.count(DiscountRedemption.id))
        .filter(DiscountRedemption.discount_code_id == discount_code_id)
        .scalar()
    ) or 0


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


def resolve_discount(
    db: Session,
    *,
    raw_code: str | None,
    space_id: str,
    payment_option_id: str,
    original_cents: int,
    currency: str,
    now: datetime | None = None,
) -> AppliedDiscount:
    """Validate a code against one offer and price it, or raise.

    Raises :class:`DiscountError` carrying the reason, which callers map
    to their own shape — a preview reports it, checkout refuses with it.

    The redemption count is taken from the ledger and written onto the
    row before validation, so ``validate_code`` reads a true count
    rather than the cached column.
    """
    moment = now or datetime.utcnow()
    code = find_code(db, raw_code=raw_code, space_id=space_id)

    if code is not None:
        # ``validate_code`` reads ``redemption_count`` off the row. Give
        # it the ledger's answer rather than the cached one. Assigning to
        # the attribute in the identity map would dirty the row and flush
        # a pointless UPDATE, so the true count goes to validate_code by
        # way of a lightweight stand-in.
        code_for_validation = _WithLiveCount(code, live_redemption_count(db, code.id))
    else:
        code_for_validation = None

    # Raises DiscountError for not-found, wrong Collective, inactive,
    # expired, limit reached, wrong Payment Option.
    validate_code(
        code_for_validation,
        space_id=space_id,
        payment_option_id=payment_option_id,
        now=moment,
    )
    assert code is not None  # validate_code raises on None

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
