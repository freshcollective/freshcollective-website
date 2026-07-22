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
