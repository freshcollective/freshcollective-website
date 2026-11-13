"""What a Collective's membership costs, read from the Collective.

The server's answer, in one place. Nothing in a checkout request names a
price, an interval or a currency: all three come from here, are written
onto the agreement, and are never read from the Collective again.

Separate from ``spaces.membership_pricing`` on purpose. That module
answers *is this paid?* and is read on public pages, so it tolerates a
surprise value by saying no. This one answers *what exactly are the
terms?* and must refuse rather than guess — a half-configured Collective
is a configuration error, not a free one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException

from app.models.platform import Space

#: ``pricing_type`` → Stripe recurring interval.
#:
#: ``paid_one_time`` is deliberately absent. A one-off joining fee is a
#: purchase, not a subscription, and Stage 5A.0's review recommended it
#: travel the existing pay-in-full path rather than this one. Reaching
#: here with it is a routing mistake and says so.
_INTERVALS: Final[dict[str, str]] = {
    "paid_monthly": "month",
    "paid_annual": "year",
}

#: Below this, Stripe's own minimum charge makes the agreement
#: uncollectable in most currencies. Refused at configuration time
#: rather than discovered at the first invoice.
MIN_AMOUNT_CENTS: Final = 50


@dataclass(frozen=True)
class AgreedTerms:
    interval: str
    interval_count: int
    amount_cents: int
    currency: str


def resolve(space: Space) -> AgreedTerms:
    """The terms a member would be agreeing to, or a 409.

    A 409 rather than a 400: the request is well formed and it is the
    Collective's configuration that cannot support a subscription. The
    member can do nothing about it, so the message points at the
    creator.
    """
    pricing_type = (space.pricing_type or "").strip()
    interval = _INTERVALS.get(pricing_type)
    if interval is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This collective does not offer recurring membership. "
                "Please contact the collective's creator."
            ),
        )

    amount = space.pricing_amount_cents
    if not isinstance(amount, int) or amount < MIN_AMOUNT_CENTS:
        raise HTTPException(
            status_code=409,
            detail=(
                "This collective's membership price is not set up yet. "
                "Please contact the collective's creator."
            ),
        )

    currency = (space.pricing_currency or "").strip().upper()
    if not currency:
        raise HTTPException(
            status_code=409,
            detail=(
                "This collective's membership currency is not set up yet. "
                "Please contact the collective's creator."
            ),
        )

    return AgreedTerms(
        interval=interval,
        interval_count=1,
        amount_cents=amount,
        currency=currency,
    )
