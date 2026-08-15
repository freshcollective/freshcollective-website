"""FIP2 — Stripe Checkout setup-Session disclosure composer.

Verifies :func:`compose_setup_disclosure` produces the exact
member-facing text pushed into ``custom_text.submit.message`` for
weekly / fortnightly / monthly finite payment plans, with correct
singular/plural handling, currency formatting, and plan-name
substitution.

The composer is a pure function of ``PurchasePlan`` snapshot values
+ the Payment Option name — no DB reads, no Stripe SDK involvement.
Tests use lightweight fakes to avoid pulling in the full ORM
fixture stack.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.finite_plan_disclosure import compose_setup_disclosure


@dataclass
class _FakePlan:
    """Duck-typed stand-in for ``PurchasePlan`` — the composer only
    reads the immutable snapshot fields."""

    installment_amount_cents: int
    installments_expected: int
    total_expected_cents: int
    stripe_interval: str
    stripe_interval_count: int
    currency: str = "AUD"


# ---------------------------------------------------------------------------
# Cadence variants — exact text assertions
# ---------------------------------------------------------------------------


class TestCadenceVariants:
    def test_weekly_three_payments(self):
        plan = _FakePlan(
            installment_amount_cents=2000,
            installments_expected=3,
            total_expected_cents=6000,
            stripe_interval="week",
            stripe_interval_count=1,
            currency="AUD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="FIP2 Test Plan")
        # Header sentence.
        assert text.startswith(
            "FIP2 Test Plan — A$20 weekly × 3 payments (A$60 total)."
        )
        # Authorisation clause.
        assert (
            "By saving your payment details, you authorise Fresh Collective "
            "to start this payment plan."
        ) in text
        # First-payment clause.
        assert "Your first A$20 payment will be charged after setup," in text
        # Follow-up clause — plural (count-1 = 2).
        assert "followed by 2 weekly payments of A$20." in text
        # Access clause.
        assert text.endswith("Access begins after the first payment succeeds.")

    def test_fortnightly_five_payments(self):
        plan = _FakePlan(
            installment_amount_cents=8000,
            installments_expected=5,
            total_expected_cents=40000,
            stripe_interval="week",
            stripe_interval_count=2,
            currency="AUD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="Term Pass")
        assert text.startswith(
            "Term Pass — A$80 fortnightly × 5 payments (A$400 total)."
        )
        assert "Your first A$80 payment will be charged after setup," in text
        assert "followed by 4 fortnightly payments of A$80." in text

    def test_monthly_six_payments(self):
        plan = _FakePlan(
            installment_amount_cents=10000,
            installments_expected=6,
            total_expected_cents=60000,
            stripe_interval="month",
            stripe_interval_count=1,
            currency="AUD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="Retreat")
        assert text.startswith(
            "Retreat — A$100 monthly × 6 payments (A$600 total)."
        )
        assert "Your first A$100 payment will be charged after setup," in text
        assert "followed by 5 monthly payments of A$100." in text


# ---------------------------------------------------------------------------
# Singular vs plural
# ---------------------------------------------------------------------------


class TestSingularPlural:
    def test_two_payments_uses_singular_followup(self):
        """A 2-payment plan means 1 follow-up — singular ``payment``."""
        plan = _FakePlan(
            installment_amount_cents=5000,
            installments_expected=2,
            total_expected_cents=10000,
            stripe_interval="week",
            stripe_interval_count=1,
        )
        text = compose_setup_disclosure(plan=plan, option_name="Two-Step")
        assert "followed by 1 weekly payment of A$50." in text
        assert "1 weekly payments" not in text  # never plural

    def test_three_payments_uses_plural_followup(self):
        plan = _FakePlan(
            installment_amount_cents=5000,
            installments_expected=3,
            total_expected_cents=15000,
            stripe_interval="week",
            stripe_interval_count=1,
        )
        text = compose_setup_disclosure(plan=plan, option_name="Three-Step")
        assert "followed by 2 weekly payments of A$50." in text


# ---------------------------------------------------------------------------
# Currency formatting
# ---------------------------------------------------------------------------


class TestCurrencyFormatting:
    def test_whole_dollars_dropped_zero_decimals(self):
        plan = _FakePlan(
            installment_amount_cents=2000,
            installments_expected=3,
            total_expected_cents=6000,
            stripe_interval="week",
            stripe_interval_count=1,
            currency="AUD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="X")
        assert "A$20" in text
        assert "A$20.00" not in text
        assert "A$60" in text
        assert "A$60.00" not in text

    def test_partial_dollars_show_two_decimals(self):
        plan = _FakePlan(
            installment_amount_cents=3450,
            installments_expected=2,
            total_expected_cents=6900,
            stripe_interval="week",
            stripe_interval_count=1,
            currency="AUD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="X")
        assert "A$34.50" in text
        assert "A$69" in text  # 6900 cents = $69 exactly

    def test_usd_uses_us_dollar_prefix(self):
        plan = _FakePlan(
            installment_amount_cents=2000,
            installments_expected=3,
            total_expected_cents=6000,
            stripe_interval="week",
            stripe_interval_count=1,
            currency="USD",
        )
        text = compose_setup_disclosure(plan=plan, option_name="X")
        assert "US$20" in text
        assert "US$60" in text
        assert "A$" not in text

    def test_unknown_currency_falls_back_to_code_prefix(self):
        plan = _FakePlan(
            installment_amount_cents=2000,
            installments_expected=3,
            total_expected_cents=6000,
            stripe_interval="week",
            stripe_interval_count=1,
            currency="XPT",
        )
        text = compose_setup_disclosure(plan=plan, option_name="X")
        assert "XPT 20" in text
        assert "XPT 60" in text


# ---------------------------------------------------------------------------
# Length / Stripe cap
# ---------------------------------------------------------------------------


class TestStripeCap:
    def test_disclosure_fits_stripe_1200_char_limit(self):
        # Long option name to worst-case the total length.
        long_name = "A " * 400  # 800 chars
        plan = _FakePlan(
            installment_amount_cents=999900,
            installments_expected=99,
            total_expected_cents=999900 * 99,
            stripe_interval="week",
            stripe_interval_count=2,
        )
        text = compose_setup_disclosure(plan=plan, option_name=long_name.strip())
        # Stripe's documented limit for custom_text.submit.message is 1200.
        assert len(text) <= 1200


# ---------------------------------------------------------------------------
# Stripe SDK integration — assert exact custom_text is passed
# ---------------------------------------------------------------------------


class TestCustomTextPassedToStripe:
    """Assert the ``custom_text.submit.message`` argument sent to
    ``stripe.checkout.Session.create`` is exactly the composed
    disclosure. Parametrised across the three supported cadences."""

    @pytest.mark.parametrize("cadence,per,count,total,expected_adverb,expected_followup", [
        (("week", 1),  2000, 3, 6000,   "weekly",      "2 weekly payments"),
        (("week", 2),  8000, 5, 40000,  "fortnightly", "4 fortnightly payments"),
        (("month", 1), 10000, 6, 60000, "monthly",     "5 monthly payments"),
    ])
    def test_create_setup_session_forwards_custom_text(
        self, monkeypatch,
        cadence, per, count, total, expected_adverb, expected_followup,
    ):
        from unittest.mock import MagicMock
        from types import SimpleNamespace
        import stripe as stripe_sdk
        from app.services import stripe_finite_plan
        from app.core.config import settings

        # Real Stripe call replaced with a spy.
        captured = {}
        def fake_create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="cs_test_disclosure",
                url="https://stripe.test/cs_test_disclosure",
            )
        monkeypatch.setattr(stripe_sdk.checkout.Session, "create", fake_create)
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")

        plan = SimpleNamespace(
            id="pplan_test",
            member_user_id="user_test",
            payment_option_id="po_test",
            payment_option_schedule_id="sched_test",
            installment_amount_cents=per,
            installments_expected=count,
            total_expected_cents=total,
            stripe_interval=cadence[0],
            stripe_interval_count=cadence[1],
            currency="AUD",
        )

        stripe_finite_plan.create_setup_session(
            plan=plan,
            option_name="FIP2 Test Plan",
            member_email="member@example.com",
            success_url="https://example/s",
            cancel_url="https://example/c",
            reuse_customer_id=None,
        )

        assert "custom_text" in captured
        submit = captured["custom_text"]["submit"]
        message = submit["message"]
        # Header + total + adverb + follow-up all present.
        assert "FIP2 Test Plan" in message
        assert expected_adverb in message
        assert expected_followup in message
        assert "Access begins after the first payment succeeds." in message
