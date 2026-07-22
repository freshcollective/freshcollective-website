"""
Ticket price + currency validation for standalone paid Gatherings.

MVP scope (per Stage 2 spec):
  - Only two-decimal-minor-unit currencies (so `_cents` naming stays honest).
  - Uppercase ISO 4217 code.
  - Price stored as integer minor units, > 0.

Used by:
  - The creator EventForm (application layer) to validate save+publish.
  - The Stage 2B checkout endpoint to authoritatively load price+currency
    from the database. Client-supplied price/currency values are never
    trusted; they are only accepted at creator-edit time from a
    caretaker of the Space.
"""

from __future__ import annotations

# Two-decimal-minor-unit ISO 4217 currencies whitelisted for MVP.
# JPY-style zero-minor-unit currencies are intentionally excluded so the
# `ticket_price_cents` column name remains semantically accurate.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({
    "AUD", "USD", "GBP", "EUR", "NZD", "CAD",
})

# Absolute minimum price we'll accept. Stripe itself refuses very small
# amounts (typically < 50 minor units in most currencies); reject earlier
# with a clearer message.
MIN_TICKET_PRICE_CENTS: int = 100  # e.g. $1.00 AUD

# Absolute maximum sanity guard — not a business limit, just protection
# against pathological input (e.g. accidental extra zero on a big price).
# Well below Stripe's own hard cap of 99999999 minor units.
MAX_TICKET_PRICE_CENTS: int = 500_000_00  # $500,000 in cents


class TicketPricingError(ValueError):
    """Raised when a ticket price / currency combination is invalid."""


def normalise_currency(raw: str | None) -> str:
    """Return uppercase ISO 4217 code; raise if unsupported or malformed."""
    if raw is None:
        raise TicketPricingError("Currency is required for a paid Gathering.")
    code = raw.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise TicketPricingError(
            f"Currency must be a 3-letter ISO 4217 code (got {raw!r})."
        )
    if code not in SUPPORTED_CURRENCIES:
        supported = ", ".join(sorted(SUPPORTED_CURRENCIES))
        raise TicketPricingError(
            f"Currency {code!r} is not supported for standalone Gathering "
            f"tickets. Supported: {supported}."
        )
    return code


def validate_price_cents(raw: int | None) -> int:
    """Return the integer price in minor units; raise if invalid."""
    if raw is None:
        raise TicketPricingError("Ticket price is required for a paid Gathering.")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise TicketPricingError("Ticket price must be an integer number of cents.")
    if raw < MIN_TICKET_PRICE_CENTS:
        raise TicketPricingError(
            f"Ticket price must be at least {MIN_TICKET_PRICE_CENTS} cents."
        )
    if raw > MAX_TICKET_PRICE_CENTS:
        raise TicketPricingError(
            f"Ticket price must be at most {MAX_TICKET_PRICE_CENTS} cents."
        )
    return raw


def validate_paid_gathering_price(
    price_cents: int | None,
    currency: str | None,
) -> tuple[int, str]:
    """Convenience: validate both together. Returns (price, currency)."""
    return validate_price_cents(price_cents), normalise_currency(currency)


def is_supported_currency(code: str | None) -> bool:
    """Non-raising check for UI-side filtering."""
    try:
        normalise_currency(code)
        return True
    except TicketPricingError:
        return False
