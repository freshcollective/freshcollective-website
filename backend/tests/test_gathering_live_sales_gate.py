"""The two keys that stand between a Gathering ticket and a real charge.

Why two
-------
``standalone_gathering_sales_enabled`` is the kind of flag somebody
turns on to try something out. That is fine in Stripe test mode and
is exactly how the flow should be exercised. In live mode the
consequence of being wrong is taking a member's money for a session
nobody has arranged to be paid for, so live mode asks a second
question: has the payout and merchant-of-record arrangement actually
been settled?

The second key did not exist. The service documented it as a later
stage and, in the meantime, live mode rested on the convention that
production ran test keys — a convention nothing enforced and nothing
would have noticed breaking. These tests pin both keys and the
specific hole that was open.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.gathering_tickets import (
    TicketSalesDisabled,
    ensure_sales_enabled_or_raise,
)


@pytest.fixture
def flags(monkeypatch):
    """Set the three values the guard reads, explicitly, every time."""
    def _set(*, enabled: bool, confirmed: bool, live: bool):
        monkeypatch.setattr(
            settings, "standalone_gathering_sales_enabled", enabled,
            raising=False,
        )
        monkeypatch.setattr(
            settings, "standalone_gathering_live_confirmed", confirmed,
            raising=False,
        )
        monkeypatch.setattr(
            settings, "stripe_secret_key",
            "sk_live_fake" if live else "sk_test_fake",
            raising=False,
        )
        assert settings.stripe_mode == ("live" if live else "test")
    return _set


class TestTheFirstKey:
    def test_sales_are_off_by_default(self):
        """Neither flag is on unless an operator turned it on."""
        assert settings.standalone_gathering_sales_enabled is False
        assert settings.standalone_gathering_live_confirmed is False

    def test_nothing_sells_with_the_first_key_off(self, flags):
        for live in (False, True):
            flags(enabled=False, confirmed=True, live=live)
            with pytest.raises(TicketSalesDisabled):
                ensure_sales_enabled_or_raise()

    def test_test_mode_needs_only_the_first_key(self, flags):
        """So the whole flow can be exercised before the business
        decision behind the second key has been made."""
        flags(enabled=True, confirmed=False, live=False)
        ensure_sales_enabled_or_raise()


class TestTheSecondKey:
    def test_live_mode_refuses_without_confirmation(self, flags):
        """The hole that was open.

        Before this guard existed, these exact settings — the feature
        flag on, live keys present — would have charged a member.
        """
        flags(enabled=True, confirmed=False, live=True)
        with pytest.raises(TicketSalesDisabled) as exc:
            ensure_sales_enabled_or_raise()
        assert "live" in str(exc.value).lower()

    def test_live_mode_proceeds_once_confirmed(self, flags):
        flags(enabled=True, confirmed=True, live=True)
        ensure_sales_enabled_or_raise()

    def test_the_second_key_alone_does_nothing(self, flags):
        """It confirms live sales; it does not enable them."""
        flags(enabled=False, confirmed=True, live=True)
        with pytest.raises(TicketSalesDisabled):
            ensure_sales_enabled_or_raise()

    def test_confirmation_is_irrelevant_in_test_mode(self, flags):
        """Setting it early neither helps nor harms."""
        flags(enabled=True, confirmed=True, live=False)
        ensure_sales_enabled_or_raise()


class TestTheGuardIsReachedBeforeStripe:
    def test_checkout_refuses_before_contacting_stripe(self, flags):
        """The guard runs at the top of the endpoint, so a disabled
        environment never creates a Session to abandon."""
        import inspect

        from app.spaces import routes

        src = inspect.getsource(routes.create_gathering_ticket_checkout)
        guard = src.index("ensure_sales_enabled_or_raise")
        # Nothing that reaches Stripe appears before the guard.
        for later in ("load_and_validate_offer", "checkout_url"):
            assert src.index(later) > guard, later
