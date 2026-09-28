"""What a discount code is worth, and whether it may be used.

The one place a discount is calculated or validated. Server-side by
construction: a caller passes the code the member typed and the price
the offer actually costs, and gets back an amount it did not choose.
Nothing here trusts a number from a browser.

Two shapes of discount:

  * ``percentage`` — basis points, so 50% is ``5000``. Integer, because
    a float percentage multiplied into cents drifts on odd amounts.
  * ``fixed_amount`` — minor units, in a named currency. A fixed
    discount in the wrong currency is refused rather than converted.

Rounding, stated once: the discount is rounded **half-up** to the cent,
and the final amount is then ``original - discount``. Half-up rather
than Python's banker's rounding, which would make 2.5c and 3.5c round
the same way and is a surprising rule to explain to a Creator. Because
the final amount is derived by subtraction rather than rounded
separately, ``original == discount + final`` always holds exactly.

Finite plans: :func:`discount_committed_total` returns the **exact**
discounted commitment. It deliberately does not decide how an uneven
total is split across instalments — that is a Stripe-representation
question, and inventing a rounding compromise here would bake a
payments constraint into the pricing layer. The common real case is
exact: Activate $306 at 50% → $153 → $15.30 × 10.

Validation is separated from arithmetic (:func:`validate_code` vs
:func:`compute_discount`) so a preview surface and a checkout can share
one rule set while only the latter consumes a redemption.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

BPS_DENOMINATOR = 10_000

#: The largest discount a code may express. 100% is deliberately
#: excluded: a zero-charge purchase is a different fulfilment shape
#: (there is an existing free path that skips Stripe entirely) and a
#: recurring Stripe Price of zero is not a coherent object. Complimentary
#: access is its own feature, not a discount of everything.
MAX_PERCENT_BPS = 9_900


class DiscountRejection(str, enum.Enum):
    """Why a code cannot be used. One member per rule, so a caller can
    map each to its own message without parsing prose."""

    NOT_FOUND = "not_found"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    LIMIT_REACHED = "limit_reached"
    WRONG_COLLECTIVE = "wrong_collective"
    WRONG_PAYMENT_OPTION = "wrong_payment_option"
    CURRENCY_MISMATCH = "currency_mismatch"
    NOT_PURCHASABLE = "not_purchasable"


class DiscountError(Exception):
    """A code that cannot be applied. Carries the reason as data."""

    def __init__(self, reason: DiscountRejection, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class DiscountAmounts:
    """The three figures every surface needs, and their provenance.

    ``original`` and ``final`` are both recorded rather than derived at
    read time, because a historical purchase must keep saying what it
    charged even after the code changes.
    """

    original_cents: int
    discount_cents: int
    final_cents: int
    currency: str

    def __post_init__(self) -> None:
        # The invariant the database CHECK also enforces. Asserted here
        # so a bug surfaces at the point of calculation, not at INSERT.
        if self.original_cents - self.discount_cents != self.final_cents:
            raise ValueError(
                f"discount arithmetic does not balance: {self.original_cents} "
                f"- {self.discount_cents} != {self.final_cents}"
            )


@dataclass(frozen=True)
class AppliedDiscount:
    """A validated, calculated discount, ready to be recorded."""

    code: str
    discount_code_id: str
    amounts: DiscountAmounts
    snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise_code(raw: str | None) -> str:
    """The canonical form: trimmed, upper-cased.

    Applied on write and on lookup, which is what makes matching
    case-insensitive without a functional index — ``family50``,
    ``Family50`` and ``  FAMILY50  `` are the same code.
    """
    return (raw or "").strip().upper()


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def percentage_discount_cents(original_cents: int, percent_bps: int) -> int:
    """Half-up to the cent, never more than the original."""
    raw = Decimal(original_cents) * Decimal(percent_bps) / Decimal(BPS_DENOMINATOR)
    return min(_round_half_up(raw), original_cents)


def compute_discount(
    *,
    original_cents: int,
    currency: str,
    discount_type: str,
    percent_bps: int | None = None,
    amount_cents: int | None = None,
    discount_currency: str | None = None,
) -> DiscountAmounts:
    """The discount on a single amount. Pure — no database, no clock.

    A fixed discount larger than the price clamps to the price rather
    than producing a negative charge or a refund.
    """
    if original_cents < 0:
        raise ValueError("original_cents cannot be negative")

    if discount_type == "percentage":
        if percent_bps is None or percent_bps <= 0:
            raise ValueError("percentage discount requires a positive percent_bps")
        discount = percentage_discount_cents(original_cents, percent_bps)
    elif discount_type == "fixed_amount":
        if amount_cents is None or amount_cents <= 0:
            raise ValueError("fixed discount requires a positive amount_cents")
        if discount_currency and discount_currency.upper() != currency.upper():
            raise DiscountError(
                DiscountRejection.CURRENCY_MISMATCH,
                "This code is in a different currency to this offer.",
            )
        discount = min(amount_cents, original_cents)
    else:
        raise ValueError(f"unknown discount_type {discount_type!r}")

    return DiscountAmounts(
        original_cents=original_cents,
        discount_cents=discount,
        final_cents=original_cents - discount,
        currency=currency.upper(),
    )


def discount_committed_total(
    *,
    installment_amount_cents: int,
    installment_count: int,
    currency: str,
    discount_type: str,
    percent_bps: int | None = None,
    amount_cents: int | None = None,
    discount_currency: str | None = None,
) -> DiscountAmounts:
    """Discount a finite plan's WHOLE commitment, not one instalment.

    The committed total is ``installment × count`` — the same product
    ``finite_plan_orchestration`` writes to
    ``PurchasePlan.total_expected_cents``. Discounting the commitment and
    then deriving instalments is the only reading that makes "50% off"
    mean what a member thinks it means; discounting the first payment
    alone would give away a tenth of what was promised.

    Returns the exact discounted total. How an uneven total is split
    across instalments is deliberately NOT decided here.
    """
    if installment_count <= 0:
        raise ValueError("installment_count must be positive")
    if installment_amount_cents <= 0:
        raise ValueError("installment_amount_cents must be positive")

    return compute_discount(
        original_cents=installment_amount_cents * installment_count,
        currency=currency,
        discount_type=discount_type,
        percent_bps=percent_bps,
        amount_cents=amount_cents,
        discount_currency=discount_currency,
    )


def divides_evenly(total_cents: int, installment_count: int) -> bool:
    """Whether a discounted commitment splits into equal whole cents.

    Reported, not resolved. The Stripe representation of an uneven split
    is decided with the finite-plan work, not here.
    """
    return installment_count > 0 and total_cents % installment_count == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_code(
    code: Any,
    *,
    space_id: str,
    payment_option_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Raise :class:`DiscountError` if this code cannot be used here.

    Takes the loaded row rather than querying, so it is pure and can be
    called from a preview surface and from fulfilment alike. Every rule
    is re-checked at fulfilment, because time passes between the two and
    a code can expire or fill up in between.

    Isolation is the first rule deliberately: a code belonging to
    another Collective is refused before anything about its contents is
    considered, and the caller reports it as though the code did not
    exist rather than confirming another Creator's code is real.
    """
    if code is None:
        raise DiscountError(DiscountRejection.NOT_FOUND, "That code was not recognised.")

    if getattr(code, "space_id", None) != space_id:
        raise DiscountError(
            DiscountRejection.WRONG_COLLECTIVE, "That code was not recognised.",
        )

    if not getattr(code, "is_active", False):
        raise DiscountError(DiscountRejection.INACTIVE, "That code is no longer active.")

    expires_at = getattr(code, "expires_at", None)
    if expires_at is not None:
        moment = now or datetime.utcnow()
        if expires_at <= moment:
            raise DiscountError(DiscountRejection.EXPIRED, "That code has expired.")

    max_redemptions = getattr(code, "max_redemptions", None)
    if max_redemptions is not None:
        if (getattr(code, "redemption_count", 0) or 0) >= max_redemptions:
            raise DiscountError(
                DiscountRejection.LIMIT_REACHED,
                "That code has reached its redemption limit.",
            )

    if getattr(code, "scope_kind", "space") == "payment_option":
        if not payment_option_id or getattr(code, "scope_id", None) != payment_option_id:
            raise DiscountError(
                DiscountRejection.WRONG_PAYMENT_OPTION,
                "That code does not apply to this offer.",
            )


def build_snapshot(code: Any, amounts: DiscountAmounts) -> dict[str, Any]:
    """The immutable record written onto the transaction or plan.

    Everything needed to explain the charge later without reading the
    live definition — which may by then have been edited, deactivated or
    deleted. Deliberately flat and primitive so it survives JSON round
    trips and schema changes.
    """
    return {
        "discount_code_id": getattr(code, "id", None),
        "code": normalise_code(getattr(code, "code", None)),
        "discount_type": getattr(code, "discount_type", None),
        "percent_bps": getattr(code, "percent_bps", None),
        "amount_cents": getattr(code, "amount_cents", None),
        "scope_kind": getattr(code, "scope_kind", None),
        "scope_id": getattr(code, "scope_id", None),
        "original_amount_cents": amounts.original_cents,
        "discount_amount_cents": amounts.discount_cents,
        "final_amount_cents": amounts.final_cents,
        "currency": amounts.currency,
    }


def platform_fee_cents(final_cents: int, fee_basis_points: int) -> int:
    """The platform fee on what was ACTUALLY charged.

    Stated here rather than left to each call site because it is the
    product decision the discount work turns on: Fresh Collective takes
    its share of the discounted amount, not of the list price a member
    never paid. Same half-up rounding as everything else; mirrors
    ``checkout_orchestration``'s ``round(gross * fee_bps / 10000)``.
    """
    if final_cents < 0 or fee_basis_points < 0:
        raise ValueError("fee inputs cannot be negative")
    raw = Decimal(final_cents) * Decimal(fee_basis_points) / Decimal(BPS_DENOMINATOR)
    return _round_half_up(raw)


# ---------------------------------------------------------------------------
# What "expires on this date" means
# ---------------------------------------------------------------------------
#
# A Creator picks a calendar day, not an instant. "Ends 31 Oct" means the
# code works for all of 31 October *where the Collective is*, and stops
# when that day does.
#
# Resolved on the server, against ``Space.timezone``, because the browser's
# timezone is the buyer's or the Creator's travel accident and has nothing
# to do with when the offer ends. A frontend sending ``23:59:59`` would
# make a Melbourne code run eleven hours into 1 November.
#
# Stored as the UTC instant the day ends — which is the start of the NEXT
# local day, held EXCLUSIVELY. ``core/periods`` documents why that shape:
# a half-open interval "is the only shape that composes without arithmetic
# hazards near midnight, month rollover, or DST transitions". It also
# matches ``validate_code``, which already treats ``expires_at <= now`` as
# expired, so the boundary instant is the first moment the code is gone.

from datetime import date, timedelta  # noqa: E402
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: E402

#: Matches the ``Space.timezone`` column default. Used only when a stored
#: timezone string is unusable, which the NOT NULL default should prevent.
FALLBACK_TIMEZONE = "Australia/Melbourne"


def collective_timezone(timezone_name: str | None) -> ZoneInfo:
    """``ZoneInfo`` for a Collective, never raising on a bad value.

    Mirrors the defensive lookup in ``creator/routes`` recurrence
    generation: an unknown timezone should never reach here, but falling
    back is better than a 500 on a Creator saving a discount code.
    """
    try:
        return ZoneInfo(timezone_name or FALLBACK_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FALLBACK_TIMEZONE)


def resolve_expiry_instant(expires_on: date | None, timezone_name: str | None) -> datetime | None:
    """The UTC instant a code chosen to end on ``expires_on`` stops working.

    Midnight at the START of the following local day, returned UTC-naive to
    match the ``DateTime(timezone=False)`` storage convention.

    Melbourne, 31 Oct 2026 (AEDT, UTC+11):
        → 1 Nov 2026 00:00 +11:00
        → 2026-10-31 13:00 UTC

    So the code is valid through 11:59:59 pm on the 31st in Melbourne, and
    gone the moment the 1st begins there.
    """
    if expires_on is None:
        return None
    tz = collective_timezone(timezone_name)
    end_of_day_local = datetime.combine(
        expires_on + timedelta(days=1), time.min, tzinfo=tz,
    )
    return end_of_day_local.astimezone(UTC).replace(tzinfo=None)


def expiry_date_in_timezone(
    expires_at: datetime | None, timezone_name: str | None,
) -> date | None:
    """The calendar day a stored expiry instant represents.

    The inverse of :func:`resolve_expiry_instant`, so a Creator is shown
    back the date they chose rather than whatever the instant looks like
    in the reader's timezone. Exact rather than approximate: the stored
    instant is the start of the following local day, so stepping back one
    microsecond lands inside the chosen day whatever the offset.
    """
    if expires_at is None:
        return None
    tz = collective_timezone(timezone_name)
    local = expires_at.replace(tzinfo=UTC).astimezone(tz)
    return (local - timedelta(microseconds=1)).date()
