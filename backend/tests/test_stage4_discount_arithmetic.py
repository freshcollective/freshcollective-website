"""Stage 4 — how a discount is spread across a finite plan.

Pure arithmetic, no database and no clock. Every figure in §6 and §7 of
the brief appears here as a test, because the examples ARE the
specification: "4 monthly payments of A$40" and "A$43.33, A$43.33,
A$43.34" are what a creator and a member were promised, and an
implementation that produced 43.34/43.33/43.33 would sum correctly while
charging the wrong first payment.

The invariant everything else rests on: the instalments sum to the
authoritative discounted total, exactly, in integer cents. Not within a
cent — exactly. A tolerance is what the two invoice gates used to need
and deliberately no longer have.
"""

from __future__ import annotations

import pytest

from app.core.money import MIN_PAID_CHARGE_CENTS
from app.services.discount_pricing import (
    DiscountError,
    DiscountRejection,
    DiscountedInstalments,
    allocate_instalments,
    discount_committed_total,
    discount_instalment_plan,
    divides_evenly,
)


def plan(
    *, per: int, count: int, currency: str = "AUD",
    discount_type: str = "percentage", percent_bps: int | None = None,
    amount_cents: int | None = None, discount_currency: str | None = None,
    minimum: int = MIN_PAID_CHARGE_CENTS,
) -> DiscountedInstalments:
    return discount_instalment_plan(
        installment_amount_cents=per,
        installment_count=count,
        currency=currency,
        discount_type=discount_type,
        percent_bps=percent_bps,
        amount_cents=amount_cents,
        discount_currency=discount_currency,
        minimum_charge_cents=minimum,
    )


# ---------------------------------------------------------------------------
# The brief's own worked examples
# ---------------------------------------------------------------------------


class TestTheBriefsExamples:
    """§6 and §7, verbatim. If these change, the product decision changed."""

    def test_percentage_four_payments_of_fifty_at_twenty_percent(self):
        # §6: 4 x A$50 = A$200, 20% off → 4 x A$40, total A$160.
        d = plan(per=5000, count=4, percent_bps=2000)

        assert d.schedule == [4000, 4000, 4000, 4000]
        assert d.amounts.original_cents == 20_000
        assert d.amounts.discount_cents == 4_000
        assert d.amounts.final_cents == 16_000
        assert d.is_even

    def test_fixed_amount_dividing_evenly(self):
        # §7: 4 x A$50 = A$200, A$40 off → 4 x A$40, total A$160.
        d = plan(
            per=5000, count=4, discount_type="fixed_amount",
            amount_cents=4000, discount_currency="AUD",
        )

        assert d.schedule == [4000, 4000, 4000, 4000]
        assert d.amounts.final_cents == 16_000
        assert d.is_even

    def test_fixed_amount_dividing_unevenly(self):
        # §7: 3 x A$50 = A$150, A$20 off → A$130 as 43.33 / 43.33 / 43.34.
        #
        # The order matters as much as the figures. A member told
        # "A$43.33 a month" must not be charged A$43.34 the first time,
        # so the remainder is last.
        d = plan(
            per=5000, count=3, discount_type="fixed_amount",
            amount_cents=2000, discount_currency="AUD",
        )

        assert d.schedule == [4333, 4333, 4334]
        assert d.amounts.final_cents == 13_000
        assert not d.is_even
        assert d.base_cents == 4333
        assert d.final_cents == 4334

    def test_the_discount_is_never_applied_to_the_first_instalment_alone(self):
        """§D, stated as the thing that must NOT happen.

        4 x A$50 at 20% is four payments of A$40 — not A$10, A$50, A$50,
        A$50, which also totals A$160 and is the shape the brief rules
        out.
        """
        d = plan(per=5000, count=4, percent_bps=2000)

        assert d.schedule[0] == 4000
        assert len(set(d.schedule)) == 1


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


class TestTheInstalmentsAlwaysSumToTheTotal:
    """No money lost, no money created — §6, and the reason the invoice
    gates can stay exact."""

    @pytest.mark.parametrize("per", [100, 333, 1000, 2999, 5000, 12_345, 99_999])
    @pytest.mark.parametrize("count", [2, 3, 4, 5, 6, 7, 10, 12])
    @pytest.mark.parametrize("bps", [1, 500, 1234, 3333, 5000, 6667, 9900])
    def test_percentage_sums_exactly(self, per, count, bps):
        try:
            d = plan(per=per, count=count, percent_bps=bps)
        except DiscountError:
            # Refused for a stated reason (too little to charge). That is
            # a decision, not a rounding failure, and is tested below.
            return

        assert sum(d.schedule) == d.amounts.final_cents
        assert d.amounts.original_cents - d.amounts.discount_cents == d.amounts.final_cents

    @pytest.mark.parametrize("count", [2, 3, 4, 7, 11])
    @pytest.mark.parametrize("off", [1, 99, 100, 777, 1999, 5000])
    def test_fixed_amount_sums_exactly(self, count, off):
        try:
            d = plan(
                per=5000, count=count, discount_type="fixed_amount",
                amount_cents=off, discount_currency="AUD",
            )
        except DiscountError:
            return

        assert sum(d.schedule) == d.amounts.final_cents

    def test_the_remainder_is_never_more_than_a_cent_per_instalment(self):
        """The difference is a rounding artefact, not a pricing decision.
        At most N-1 cents over the whole plan."""
        for count in range(2, 13):
            d = plan(per=3333, count=count, percent_bps=3333)
            assert 0 <= d.final_cents - d.base_cents < count

    def test_the_dataclass_refuses_a_schedule_that_does_not_balance(self):
        """Asserted at construction rather than discovered at invoice
        four. A hand-built inconsistent schedule is a bug, and this is
        where it should stop."""
        from app.services.discount_pricing import DiscountAmounts

        with pytest.raises(ValueError, match="does not sum"):
            DiscountedInstalments(
                amounts=DiscountAmounts(
                    original_cents=15_000, discount_cents=2_000,
                    final_cents=13_000, currency="AUD",
                ),
                installment_count=3,
                base_cents=4333,
                final_cents=4333,   # one cent short
            )


# ---------------------------------------------------------------------------
# Allocation, on its own
# ---------------------------------------------------------------------------


class TestAllocation:

    def test_exact_division(self):
        assert allocate_instalments(16_000, 4) == (4000, 4000)

    def test_one_cent_remainder(self):
        assert allocate_instalments(13_000, 3) == (4333, 4334)

    def test_two_cent_remainder(self):
        assert allocate_instalments(10_001, 3) == (3333, 3335)

    def test_a_single_instalment_is_the_whole_total(self):
        assert allocate_instalments(4999, 1) == (4999, 4999)

    def test_zero_is_allowed_arithmetically(self):
        """The arithmetic does not police product rules — that is
        ``discount_instalment_plan``'s job, and it refuses a free plan
        with a reason a member can read."""
        assert allocate_instalments(0, 4) == (0, 0)

    def test_a_non_positive_count_is_a_programming_error(self):
        with pytest.raises(ValueError):
            allocate_instalments(1000, 0)

    def test_a_negative_total_is_a_programming_error(self):
        with pytest.raises(ValueError):
            allocate_instalments(-1, 3)

    def test_divides_evenly_agrees_with_the_allocation(self):
        for total in (0, 1, 99, 13_000, 16_000, 10_001):
            for count in (1, 2, 3, 4, 7):
                base, final = allocate_instalments(total, count)
                assert divides_evenly(total, count) == (base == final)


# ---------------------------------------------------------------------------
# The commitment is what gets discounted
# ---------------------------------------------------------------------------


class TestTheWholeCommitmentIsDiscounted:

    def test_a_percentage_applies_to_the_total_not_one_payment(self):
        """"50% off" means half the commitment. Discounting one invoice
        would give away a tenth of what was promised on a ten-payment
        plan."""
        d = plan(per=3060, count=10, percent_bps=5000)

        assert d.amounts.original_cents == 30_600
        assert d.amounts.final_cents == 15_300
        assert d.schedule == [1530] * 10

    def test_a_fixed_amount_applies_once_to_the_plan_not_once_per_payment(self):
        """A$20 off a three-payment plan is A$20 off, not A$60 off."""
        d = plan(
            per=5000, count=3, discount_type="fixed_amount",
            amount_cents=2000, discount_currency="AUD",
        )

        assert d.amounts.discount_cents == 2000

    def test_committed_total_matches_the_plan_row_arithmetic(self):
        """``discount_committed_total`` discounts ``per x count``, the
        same product ``finite_plan_orchestration`` writes to
        ``total_expected_cents``."""
        amounts = discount_committed_total(
            installment_amount_cents=3060, installment_count=10,
            currency="AUD", discount_type="percentage", percent_bps=5000,
        )

        assert amounts.original_cents == 3060 * 10


# ---------------------------------------------------------------------------
# Cadence and shape are preserved
# ---------------------------------------------------------------------------


class TestTheArrangementIsPreserved:
    """§6: the number of instalments and the cadence are the creator's,
    and a discount does not renegotiate them."""

    @pytest.mark.parametrize("count", [2, 3, 4, 6, 10, 12])
    def test_the_number_of_payments_never_changes(self, count):
        d = plan(per=5000, count=count, percent_bps=2500)

        assert d.installment_count == count
        assert len(d.schedule) == count

    def test_a_discount_is_not_silently_turned_into_fewer_payments(self):
        """§8 rules this out explicitly. A plan that cannot be
        discounted is refused, never reshaped."""
        with pytest.raises(DiscountError) as exc:
            plan(per=150, count=4, percent_bps=9900)

        assert exc.value.reason is DiscountRejection.BELOW_MINIMUM


# ---------------------------------------------------------------------------
# Limits — §8
# ---------------------------------------------------------------------------


class TestLimits:

    def test_a_discount_that_leaves_nothing_is_refused_as_complimentary(self):
        """Free access is a complimentary pass, deliberately granted —
        not something a code produces as a side effect."""
        with pytest.raises(DiscountError) as exc:
            plan(
                per=5000, count=4, discount_type="fixed_amount",
                amount_cents=20_000, discount_currency="AUD",
            )

        assert exc.value.reason is DiscountRejection.NOT_PURCHASABLE
        assert "complimentary" in exc.value.message.lower()

    def test_a_fixed_discount_larger_than_the_plan_cannot_go_negative(self):
        """Clamped to the price, then refused for leaving nothing — never
        a negative instalment."""
        with pytest.raises(DiscountError) as exc:
            plan(
                per=5000, count=2, discount_type="fixed_amount",
                amount_cents=999_999, discount_currency="AUD",
            )

        assert exc.value.reason is DiscountRejection.NOT_PURCHASABLE

    def test_an_instalment_below_the_minimum_is_refused_not_rounded_up(self):
        """§8: do not silently increase the discounted price. The
        creator wrote the discount; a member charged more than it says
        has been told a small lie by the system."""
        with pytest.raises(DiscountError) as exc:
            plan(per=200, count=4, percent_bps=7500)

        assert exc.value.reason is DiscountRejection.BELOW_MINIMUM
        assert "smallest payment" in exc.value.message.lower()

    def test_the_floor_is_checked_per_instalment_not_on_the_total(self):
        """A plan can clear the floor overall and still have payments too
        small to take. 6 x A$0.50 is A$3 total — fine as a lump, refused
        as a schedule."""
        total_would_be_fine = 6 * 50
        assert total_would_be_fine > MIN_PAID_CHARGE_CENTS

        with pytest.raises(DiscountError) as exc:
            plan(
                per=1000, count=6, discount_type="fixed_amount",
                amount_cents=5700, discount_currency="AUD",
            )

        assert exc.value.reason is DiscountRejection.BELOW_MINIMUM

    def test_exactly_at_the_minimum_is_allowed(self):
        """The floor is inclusive — the smallest payment we CAN take is
        still one we take."""
        d = plan(
            per=200, count=4, discount_type="fixed_amount",
            amount_cents=400, discount_currency="AUD",
        )

        assert d.base_cents == MIN_PAID_CHARGE_CENTS

    def test_the_floor_is_supplied_not_assumed(self):
        """Passed in rather than imported, so this module stays free of
        the money configuration and a test can state the floor it is
        exercising."""
        d = plan(per=200, count=4, percent_bps=7500, minimum=50)

        assert d.base_cents == 50


# ---------------------------------------------------------------------------
# Currency — §7, §12
# ---------------------------------------------------------------------------


class TestCurrency:

    def test_a_fixed_discount_in_another_currency_is_refused(self):
        """Refused rather than converted. FC does not hold an exchange
        rate and must not invent one at checkout."""
        with pytest.raises(DiscountError) as exc:
            plan(
                per=5000, count=3, currency="USD",
                discount_type="fixed_amount", amount_cents=2000,
                discount_currency="AUD",
            )

        assert exc.value.reason is DiscountRejection.CURRENCY_MISMATCH

    def test_a_fixed_discount_in_the_matching_currency_applies(self):
        d = plan(
            per=5000, count=3, currency="USD",
            discount_type="fixed_amount", amount_cents=2000,
            discount_currency="USD",
        )

        assert d.currency == "USD"
        assert d.schedule == [4333, 4333, 4334]

    def test_a_percentage_is_currency_agnostic(self):
        """A percentage needs no currency of its own — it is a ratio."""
        for currency in ("AUD", "USD", "NZD", "GBP", "EUR"):
            d = plan(per=5000, count=4, currency=currency, percent_bps=2000)
            assert d.currency == currency
            assert d.schedule == [4000] * 4

    def test_aud_is_not_assumed_anywhere_in_the_result(self):
        d = plan(per=5000, count=2, currency="NZD", percent_bps=1000)

        assert d.amounts.currency == "NZD"
