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
