"""FIP1 — recurring_installments schedule validation.

The validator lives in ``services/schedule_validation.py``. Two
entry points:

* :func:`validate_recurring_installments_payload` — raises
  ``HTTPException(422)``; used by Creator create/update routes at
  the moment a schedule is being *published*.
* :func:`validate_recurring_installments_row` — raises
  ``ScheduleValidationError``; used by future non-HTTP callers
  (FIP2 plan-creation etc.).

Both share one snapshot + validation function so the rules cannot
drift between them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.schedule_validation import (
    ScheduleValidationError,
    apply_recurring_derivations,
    derive_stripe_cadence,
    validate_recurring_installments_payload,
    validate_recurring_installments_row,
)


def _payload(**overrides):
    """A minimal valid recurring_installments payload; override to test bad cases."""
    base = dict(
        schedule_type="recurring_installments",
        installment_amount_cents=2000,
        installment_count=10,
        stripe_interval="week",
        stripe_interval_count=1,
        total_amount_cents=20000,
        currency="AUD",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestValidCadences:
    def test_weekly_ten_payments_valid(self):
        validate_recurring_installments_payload(
            _payload(stripe_interval="week", stripe_interval_count=1)
        )

    def test_fortnightly_five_payments_valid(self):
        validate_recurring_installments_payload(_payload(
            stripe_interval="week", stripe_interval_count=2,
            installment_count=5, installment_amount_cents=8000,
            total_amount_cents=40000,
        ))

    def test_monthly_six_payments_valid(self):
        validate_recurring_installments_payload(_payload(
            stripe_interval="month", stripe_interval_count=1,
            installment_count=6, installment_amount_cents=10000,
            total_amount_cents=60000,
        ))


class TestInvalidInstallmentCount:
    def test_zero_installments_invalid(self):
        with pytest.raises(HTTPException) as exc:
            validate_recurring_installments_payload(
                _payload(installment_count=0)
            )
        assert exc.value.status_code == 422

    def test_one_installment_invalid(self):
        # One "instalment" is really pay_in_full — force the Creator
        # to use the correct schedule_type.
        with pytest.raises(HTTPException) as exc:
            validate_recurring_installments_payload(
                _payload(installment_count=1)
            )
        assert exc.value.status_code == 422
        # The message tells the Creator why.
        assert "installment_count" in str(exc.value.detail)

    def test_missing_installment_count_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(installment_count=None)
            )


class TestInvalidAmount:
    def test_zero_amount_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(installment_amount_cents=0)
            )

    def test_negative_amount_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(installment_amount_cents=-100)
            )

    def test_missing_amount_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(installment_amount_cents=None)
            )


class TestInvalidCadence:
    def test_unknown_interval_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(stripe_interval="day")
            )

    def test_weekly_x3_invalid(self):
        # Not one of the three supported cadences.
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(stripe_interval="week", stripe_interval_count=3)
            )

    def test_missing_interval_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(
                _payload(stripe_interval=None)
            )


class TestCurrency:
    def test_currency_lowercase_but_alpha_rejected(self):
        # We accept only 3-letter ISO 4217. Case is not the schema's
        # job to normalise — the routes upper() it themselves before
        # persist.
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(_payload(currency="AU"))

    def test_currency_with_digits_rejected(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(_payload(currency="AU1"))


class TestTotalCrossCheck:
    """v1 requires strict equality: total == amount × count.

    The schema describes equal fixed instalments. No hidden
    tolerance — a mismatched total is a Creator input error and
    must surface as one.
    """

    def test_matching_total_valid(self):
        validate_recurring_installments_payload(_payload(
            installment_amount_cents=2000, installment_count=10,
            total_amount_cents=20000,
        ))

    def test_one_cent_over_invalid(self):
        # $340 × 10 = $3400.00 exactly. $3400.01 is off by 1c.
        with pytest.raises(HTTPException) as exc:
            validate_recurring_installments_payload(_payload(
                installment_amount_cents=34000, installment_count=10,
                total_amount_cents=340001,
            ))
        assert "equal" in str(exc.value.detail).lower() or "match" in str(exc.value.detail).lower()

    def test_one_cent_under_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(_payload(
                installment_amount_cents=34000, installment_count=10,
                total_amount_cents=339999,
            ))

    def test_grossly_wrong_total_invalid(self):
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(_payload(
                installment_amount_cents=2000, installment_count=10,
                total_amount_cents=99999,
            ))

    def test_uneven_split_via_rounded_amount_invalid(self):
        # $200 / 3 as $66.67 × 3 = $200.01. Not equal to $200 — must fail.
        # Creators wanting non-integer splits should adjust either the
        # per-instalment amount or the total until they match exactly.
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(_payload(
                installment_amount_cents=6667, installment_count=3,
                total_amount_cents=20000,
            ))


class TestNoOpForOtherScheduleTypes:
    def test_pay_in_full_skipped(self):
        """Pay-in-full payloads pass through with no validation errors."""
        payload = SimpleNamespace(
            schedule_type="pay_in_full",
            installment_amount_cents=None,   # normally NULL for pay_in_full
            installment_count=None,
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=20000,
            currency="AUD",
        )
        validate_recurring_installments_payload(payload)

    def test_manual_skipped(self):
        payload = SimpleNamespace(schedule_type="manual")
        validate_recurring_installments_payload(payload)


class TestOrmRowEntryPoint:
    """The persisted-row entry point raises a domain exception (not HTTP)."""

    def test_valid_row(self):
        row = _payload()
        validate_recurring_installments_row(row)

    def test_invalid_row_raises_domain_error(self):
        row = _payload(installment_count=0)
        with pytest.raises(ScheduleValidationError):
            validate_recurring_installments_row(row)


# ---------------------------------------------------------------------------
# derive_stripe_cadence
# ---------------------------------------------------------------------------


class TestDeriveStripeCadence:
    def test_semantic_keys_map_to_stripe_pair(self):
        assert derive_stripe_cadence("week") == ("week", 1)
        assert derive_stripe_cadence("weekly") == ("week", 1)
        assert derive_stripe_cadence("fortnight") == ("week", 2)
        assert derive_stripe_cadence("fortnightly") == ("week", 2)
        assert derive_stripe_cadence("biweekly") == ("week", 2)
        assert derive_stripe_cadence("month") == ("month", 1)
        assert derive_stripe_cadence("monthly") == ("month", 1)

    def test_case_insensitive_and_trimmed(self):
        assert derive_stripe_cadence("  Weekly  ") == ("week", 1)
        assert derive_stripe_cadence("FORTNIGHTLY") == ("week", 2)

    def test_unknown_returns_none(self):
        assert derive_stripe_cadence("daily") is None
        assert derive_stripe_cadence("") is None
        assert derive_stripe_cadence(None) is None


# ---------------------------------------------------------------------------
# apply_recurring_derivations — Creator payload normalisation
# ---------------------------------------------------------------------------


class TestApplyRecurringDerivations:
    """Reproduces the browser-flagged bug ($20/week × 3) and asserts the
    normalisation the backend now applies on save."""

    def test_creator_payload_20_weekly_x3_derives_stripe_cadence_and_total(self):
        """The exact failing browser payload — UI sends ``interval='week'``
        but no Stripe pair and no total. After derivation, the row has
        everything the FIP1 validator needs on publish."""
        payload = SimpleNamespace(
            schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000,
            installment_count=3,
            interval="week",
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=None,
            currency="AUD",
        )
        apply_recurring_derivations(payload)
        assert payload.stripe_interval == "week"
        assert payload.stripe_interval_count == 1
        assert payload.total_amount_cents == 6000  # $60 = $20 × 3
        # Publish-time validation now passes.
        validate_recurring_installments_payload(payload)

    def test_fortnightly_maps_to_week_x2(self):
        payload = _payload(
            interval="fortnight",
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=None,
            installment_amount_cents=8000,
            installment_count=5,
        )
        apply_recurring_derivations(payload)
        assert payload.stripe_interval == "week"
        assert payload.stripe_interval_count == 2
        assert payload.total_amount_cents == 40000  # $400 = $80 × 5

    def test_monthly_maps_to_month_x1(self):
        payload = _payload(
            interval="monthly",
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=None,
            installment_amount_cents=10000,
            installment_count=6,
        )
        apply_recurring_derivations(payload)
        assert payload.stripe_interval == "month"
        assert payload.stripe_interval_count == 1
        assert payload.total_amount_cents == 60000

    def test_pay_in_full_payload_is_untouched(self):
        payload = SimpleNamespace(
            schedule_type="pay_in_full",
            installment_amount_cents=None,
            installment_count=None,
            interval=None,
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=20000,
            currency="AUD",
        )
        apply_recurring_derivations(payload)
        assert payload.stripe_interval is None
        assert payload.stripe_interval_count is None
        assert payload.total_amount_cents == 20000

    def test_explicit_stripe_pair_is_preserved(self):
        payload = _payload(
            interval="week",
            stripe_interval="month",  # deliberately conflicting
            stripe_interval_count=1,
            total_amount_cents=20000,
        )
        apply_recurring_derivations(payload)
        # Do not override what the caller explicitly sent.
        assert payload.stripe_interval == "month"
        assert payload.stripe_interval_count == 1

    def test_explicit_total_is_preserved(self):
        payload = _payload(
            installment_amount_cents=2000,
            installment_count=3,
            total_amount_cents=5999,  # deliberately wrong; caller wins
        )
        apply_recurring_derivations(payload)
        assert payload.total_amount_cents == 5999
        # Downstream strict validator will still catch this mismatch.
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_recurring_installments_payload(payload)

    def test_unknown_interval_leaves_stripe_fields_null(self):
        payload = _payload(
            interval="daily",
            stripe_interval=None,
            stripe_interval_count=None,
            total_amount_cents=None,
        )
        apply_recurring_derivations(payload)
        assert payload.stripe_interval is None
        assert payload.stripe_interval_count is None
        # total still derived because amount+count are present.
        assert payload.total_amount_cents == 20000  # $20 × 10 default
