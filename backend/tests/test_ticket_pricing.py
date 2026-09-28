"""
Ticket price + currency validation — unit tests, no DB.
"""

from __future__ import annotations

import pytest

from app.services.ticket_pricing import (
    SUPPORTED_CURRENCIES,
    MIN_TICKET_PRICE_CENTS,
    MAX_TICKET_PRICE_CENTS,
    TicketPricingError,
    is_supported_currency,
    normalise_currency,
    validate_paid_gathering_price,
    validate_price_cents,
)


class TestCurrency:
    @pytest.mark.parametrize("code", sorted(SUPPORTED_CURRENCIES))
    def test_all_supported_currencies_normalise(self, code):
        assert normalise_currency(code) == code
        assert normalise_currency(code.lower()) == code
        assert normalise_currency(f" {code} ") == code
        assert is_supported_currency(code)

    @pytest.mark.parametrize("bad", ["JPY", "XYZ", "", "AU", "AUDS", "12A", None])
    def test_unsupported_or_malformed_rejected(self, bad):
        with pytest.raises(TicketPricingError):
            normalise_currency(bad)
        assert not is_supported_currency(bad)


class TestPrice:
    def test_min_price_accepted(self):
        assert validate_price_cents(MIN_TICKET_PRICE_CENTS) == MIN_TICKET_PRICE_CENTS

    def test_max_price_accepted(self):
        assert validate_price_cents(MAX_TICKET_PRICE_CENTS) == MAX_TICKET_PRICE_CENTS

    @pytest.mark.parametrize("bad", [0, -1, MIN_TICKET_PRICE_CENTS - 1, MAX_TICKET_PRICE_CENTS + 1, None, True, 25.0, "2500"])
    def test_invalid_prices_rejected(self, bad):
        with pytest.raises(TicketPricingError):
            validate_price_cents(bad)


class TestCombined:
    def test_both_valid_returns_tuple(self):
        price, cur = validate_paid_gathering_price(2500, "aud")
        assert price == 2500
        assert cur == "AUD"

    def test_price_missing(self):
        with pytest.raises(TicketPricingError):
            validate_paid_gathering_price(None, "AUD")

    def test_currency_missing(self):
        with pytest.raises(TicketPricingError):
            validate_paid_gathering_price(2500, None)


class TestTheFloorSurvivedBeingShared:
    """The floor moved to ``core.money`` so discounted checkout could use
    the same number. This path's behaviour must be exactly what it was.

    Asserted against literals, not against the constant. The existing
    tests above read the constant symbolically, so they would keep
    passing if its value drifted — which is precisely the risk that
    extracting it introduces.
    """

    def test_one_dollar_is_still_the_floor(self):
        assert MIN_TICKET_PRICE_CENTS == 100
        assert validate_price_cents(100) == 100

    def test_ninety_nine_cents_is_still_refused(self):
        with pytest.raises(TicketPricingError):
            validate_price_cents(99)

    def test_it_is_the_same_object_as_the_shared_floor(self):
        """Not a copy that happens to agree — two constants that drifted
        apart would be worse than one that was never shared."""
        from app.core.money import MIN_PAID_CHARGE_CENTS

        assert MIN_TICKET_PRICE_CENTS == MIN_PAID_CHARGE_CENTS

    def test_the_message_still_names_the_amount(self):
        with pytest.raises(TicketPricingError) as exc:
            validate_price_cents(50)
        assert "100" in str(exc.value)
