"""Discount arithmetic and validation — the pure layer.

Work Item 1 is deliberately unwired: no checkout, no Stripe, no
redemption fulfilment, no UI. What is proved here is that the numbers
are right and the rules are complete, so the surfaces that follow have
one thing to call rather than one thing to reimplement.

Prices are the live EMBODY ones, verified read-only against Render
production: Awaken $180 ($18 × 10), Activate $306 ($30.60 × 10), Empower
$378 ($37.80 × 10) — all ``payment_type=one_time``, space-attached, with
pricing held on ``PaymentOptionSchedule``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.discount_pricing import (
    MAX_PERCENT_BPS,
    DiscountError,
    DiscountRejection,
    build_snapshot,
    compute_discount,
    discount_committed_total,
    divides_evenly,
    normalise_code,
    percentage_discount_cents,
    platform_fee_cents,
)

AUD = "AUD"
# Live EMBODY commitments, in minor units.
AWAKEN = (1800, 10, 18000)      # $18.00 × 10 = $180
ACTIVATE = (3060, 10, 30600)    # $30.60 × 10 = $306
EMPOWER = (3780, 10, 37800)     # $37.80 × 10 = $378


def code(**kw):
    """A DiscountCode-shaped stand-in. The service takes the loaded row,
    not a query, so validation stays pure and testable."""
    base = dict(
        id="dc_1", space_id="s_1", code="FAMILY50",
        discount_type="percentage", percent_bps=5000, amount_cents=None,
        currency=None, is_active=True, expires_at=None,
        max_redemptions=None, redemption_count=0,
        scope_kind="space", scope_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# The case this work exists for
# ---------------------------------------------------------------------------

class TestTheRealEmbodyCase:
    def test_activate_at_fifty_percent_is_exactly_153(self):
        """$306 → $153. The target case, and it divides evenly."""
        amount, count, total = ACTIVATE

        result = discount_committed_total(
            installment_amount_cents=amount, installment_count=count,
            currency=AUD, discount_type="percentage", percent_bps=5000,
        )

        assert result.original_cents == total == 30600
        assert result.discount_cents == 15300
        assert result.final_cents == 15300          # $153.00
        assert divides_evenly(result.final_cents, count)
        assert result.final_cents // count == 1530  # $15.30 × 10

    @pytest.mark.parametrize("amount,count,total", [AWAKEN, ACTIVATE, EMPOWER])
    def test_every_live_embody_offer_halves_cleanly(self, amount, count, total):
        result = discount_committed_total(
            installment_amount_cents=amount, installment_count=count,
            currency=AUD, discount_type="percentage", percent_bps=5000,
        )
        assert result.final_cents == total // 2
        assert divides_evenly(result.final_cents, count)

    def test_the_discount_applies_to_the_commitment_not_one_instalment(self):
        """The mistake this design exists to prevent: discounting only
        the first payment gives away a tenth of what was promised."""
        amount, count, total = EMPOWER

        whole = discount_committed_total(
            installment_amount_cents=amount, installment_count=count,
            currency=AUD, discount_type="percentage", percent_bps=5000,
        )
        first_payment_only = compute_discount(
            original_cents=amount, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )

        assert whole.discount_cents == 18900          # half of $378
        assert first_payment_only.discount_cents == 1890
        assert whole.discount_cents == first_payment_only.discount_cents * count


# ---------------------------------------------------------------------------
# Percentage arithmetic
# ---------------------------------------------------------------------------

class TestPercentageDiscounts:
    @pytest.mark.parametrize("bps,expected", [
        (5000, 15300),   # 50%
        (2500, 7650),    # 25%
        (1000, 3060),    # 10%
        (10000 - 100, 30294),  # 99%, the maximum
        (1, 3),          # 0.01% — basis points are real precision
    ])
    def test_activate_at_various_percentages(self, bps, expected):
        result = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=bps,
        )
        assert result.discount_cents == expected
        assert result.final_cents == 30600 - expected

    def test_rounding_is_half_up_not_bankers(self):
        """Python's round() would send 2.5 → 2 and 3.5 → 4. A Creator
        cannot be told that; half-up is the rule we can explain."""
        # 5c at 50% = 2.5c
        assert percentage_discount_cents(5, 5000) == 3
        # 7c at 50% = 3.5c
        assert percentage_discount_cents(7, 5000) == 4

    def test_a_third_off_is_deterministic(self):
        result = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=3333,
        )
        # 30600 * 0.3333 = 10198.98 → 10199
        assert result.discount_cents == 10199
        assert result.final_cents == 20401

    def test_the_three_figures_always_balance(self):
        for cents in (1, 7, 99, 1800, 3060, 30600, 37800, 999_999):
            for bps in (1, 333, 2500, 5000, 9900):
                r = compute_discount(
                    original_cents=cents, currency=AUD,
                    discount_type="percentage", percent_bps=bps,
                )
                assert r.original_cents - r.discount_cents == r.final_cents
                assert 0 <= r.discount_cents <= cents

    def test_a_zero_price_stays_zero(self):
        r = compute_discount(
            original_cents=0, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        assert (r.discount_cents, r.final_cents) == (0, 0)


# ---------------------------------------------------------------------------
# Fixed-amount arithmetic
# ---------------------------------------------------------------------------

class TestFixedAmountDiscounts:
    def test_fifty_dollars_off_activate(self):
        r = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="fixed_amount", amount_cents=5000,
            discount_currency=AUD,
        )
        assert (r.discount_cents, r.final_cents) == (5000, 25600)

    def test_a_discount_larger_than_the_price_clamps_to_the_price(self):
        """Never a negative charge, never an accidental refund."""
        r = compute_discount(
            original_cents=1800, currency=AUD,
            discount_type="fixed_amount", amount_cents=99_999,
            discount_currency=AUD,
        )
        assert r.discount_cents == 1800
        assert r.final_cents == 0

    def test_a_different_currency_is_refused_not_converted(self):
        with pytest.raises(DiscountError) as exc:
            compute_discount(
                original_cents=30600, currency=AUD,
                discount_type="fixed_amount", amount_cents=5000,
                discount_currency="USD",
            )
        assert exc.value.reason is DiscountRejection.CURRENCY_MISMATCH

    def test_currency_comparison_is_case_insensitive(self):
        r = compute_discount(
            original_cents=30600, currency="aud",
            discount_type="fixed_amount", amount_cents=5000,
            discount_currency="AUD",
        )
        assert r.final_cents == 25600
        assert r.currency == "AUD"

    def test_a_fixed_discount_on_a_commitment_applies_once(self):
        """$50 off Empower is $50 off the commitment, not off each of
        ten instalments."""
        amount, count, total = EMPOWER
        r = discount_committed_total(
            installment_amount_cents=amount, installment_count=count,
            currency=AUD, discount_type="fixed_amount",
            amount_cents=5000, discount_currency=AUD,
        )
        assert r.original_cents == total
        assert r.discount_cents == 5000
        assert r.final_cents == 32800


# ---------------------------------------------------------------------------
# Uneven splits — reported, deliberately not resolved here
# ---------------------------------------------------------------------------

class TestUnevenCommitments:
    def test_an_uneven_total_is_returned_exactly(self):
        """The pricing layer computes the true discounted commitment. How
        Stripe represents an uneven split is a later decision; baking a
        rounding compromise in here would hide a payments constraint
        inside the pricing rule."""
        r = discount_committed_total(
            installment_amount_cents=3780, installment_count=10,
            currency=AUD, discount_type="percentage", percent_bps=3333,
        )
        # 37800 * 0.3333 = 12598.74 → 12599
        assert r.discount_cents == 12599
        assert r.final_cents == 25201
        assert not divides_evenly(r.final_cents, 10)

    def test_divides_evenly_answers_honestly(self):
        assert divides_evenly(15300, 10)
        assert not divides_evenly(25201, 10)
        assert not divides_evenly(100, 0)

    def test_no_rounding_compromise_is_applied(self):
        """Pins the deliberate absence: the service must not quietly
        adjust an uneven total to make it divide."""
        r = discount_committed_total(
            installment_amount_cents=3333, installment_count=7,
            currency=AUD, discount_type="percentage", percent_bps=5000,
        )
        assert r.original_cents == 23331
        assert r.final_cents == r.original_cents - r.discount_cents
        assert r.final_cents % 7 != 0


# ---------------------------------------------------------------------------
# Platform fee — on what was actually charged
# ---------------------------------------------------------------------------

class TestPlatformFeeFollowsTheDiscount:
    """Production could not demonstrate this: every live EMBODY
    transaction has ``platform_fee_basis_points=0``. These use a
    non-zero rate so the product decision is proved rather than assumed.
    """

    def test_the_fee_is_taken_on_the_discounted_amount(self):
        r = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        # 10% platform fee on $153, not on $306.
        assert platform_fee_cents(r.final_cents, 1000) == 1530
        assert platform_fee_cents(r.original_cents, 1000) == 3060

    def test_halving_the_price_halves_the_fee(self):
        # 10% divides cleanly at both amounts.
        assert platform_fee_cents(30600, 1000) == 3060
        assert platform_fee_cents(15300, 1000) == 1530

    def test_a_half_cent_rounds_up_rather_than_splitting_the_difference(self):
        """At 7.5%, $153 lands on 1147.5c. Half-up takes it to 1148, so
        the discounted fee is a cent more than exactly half the full fee.
        Recorded because it looks like an error and is not — rounding
        each charge independently is the only rule that keeps every
        individual fee a whole number of cents."""
        assert platform_fee_cents(30600, 750) == 2295
        assert platform_fee_cents(15300, 750) == 1148
        assert platform_fee_cents(15300, 750) * 2 == 2296

    def test_a_zero_rate_still_yields_zero(self):
        """The live EMBODY configuration today."""
        assert platform_fee_cents(15300, 0) == 0

    def test_the_fee_rounds_half_up(self):
        # 15301 * 0.075 = 1147.575 → 1148
        assert platform_fee_cents(15301, 750) == 1148

    def test_negative_inputs_are_refused(self):
        with pytest.raises(ValueError):
            platform_fee_cents(-1, 750)
        with pytest.raises(ValueError):
            platform_fee_cents(100, -1)


# ---------------------------------------------------------------------------
# Canonical code handling
# ---------------------------------------------------------------------------

class TestCodeNormalisation:
    @pytest.mark.parametrize("raw", [
        "FAMILY50", "family50", "Family50", "  family50  ", "fAmIlY50\t",
    ])
    def test_matching_is_case_and_whitespace_insensitive(self, raw):
        assert normalise_code(raw) == "FAMILY50"

    def test_none_and_empty_normalise_to_empty(self):
        assert normalise_code(None) == ""
        assert normalise_code("   ") == ""

    def test_normalisation_is_idempotent(self):
        once = normalise_code(" family50 ")
        assert normalise_code(once) == once


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

class TestValidation:
    def test_a_good_code_passes(self, ):
        from app.services.discount_pricing import validate_code
        validate_code(code(), space_id="s_1")

    def test_a_missing_code_is_not_found(self):
        from app.services.discount_pricing import validate_code
        with pytest.raises(DiscountError) as exc:
            validate_code(None, space_id="s_1")
        assert exc.value.reason is DiscountRejection.NOT_FOUND

    def test_another_collectives_code_is_refused(self):
        """Isolation. Checked before anything about the code's contents,
        and reported as 'not recognised' so it does not confirm that
        another Creator's code exists."""
        from app.services.discount_pricing import validate_code
        with pytest.raises(DiscountError) as exc:
            validate_code(code(space_id="s_OTHER"), space_id="s_1")
        assert exc.value.reason is DiscountRejection.WRONG_COLLECTIVE
        assert "not recognised" in exc.value.message

    def test_an_inactive_code_is_refused(self):
        from app.services.discount_pricing import validate_code
        with pytest.raises(DiscountError) as exc:
            validate_code(code(is_active=False), space_id="s_1")
        assert exc.value.reason is DiscountRejection.INACTIVE

    def test_an_expired_code_is_refused(self):
        from app.services.discount_pricing import validate_code
        now = datetime(2026, 9, 28, 12, 0, 0)
        with pytest.raises(DiscountError) as exc:
            validate_code(
                code(expires_at=now - timedelta(seconds=1)),
                space_id="s_1", now=now,
            )
        assert exc.value.reason is DiscountRejection.EXPIRED

    def test_expiry_is_exclusive_at_the_boundary(self):
        """Expiring 'at' a moment means it is gone at that moment."""
        from app.services.discount_pricing import validate_code
        now = datetime(2026, 9, 28, 12, 0, 0)
        with pytest.raises(DiscountError):
            validate_code(code(expires_at=now), space_id="s_1", now=now)
        validate_code(
            code(expires_at=now + timedelta(seconds=1)), space_id="s_1", now=now,
        )

    def test_a_full_code_is_refused(self):
        from app.services.discount_pricing import validate_code
        with pytest.raises(DiscountError) as exc:
            validate_code(
                code(max_redemptions=25, redemption_count=25), space_id="s_1",
            )
        assert exc.value.reason is DiscountRejection.LIMIT_REACHED

    def test_the_last_redemption_is_still_allowed(self):
        from app.services.discount_pricing import validate_code
        validate_code(code(max_redemptions=25, redemption_count=24), space_id="s_1")

    def test_an_unlimited_code_never_fills(self):
        from app.services.discount_pricing import validate_code
        validate_code(code(max_redemptions=None, redemption_count=9999), space_id="s_1")

    def test_an_option_scoped_code_rejects_another_option(self):
        from app.services.discount_pricing import validate_code
        scoped = code(scope_kind="payment_option", scope_id="po_activate")
        with pytest.raises(DiscountError) as exc:
            validate_code(scoped, space_id="s_1", payment_option_id="po_awaken")
        assert exc.value.reason is DiscountRejection.WRONG_PAYMENT_OPTION

    def test_an_option_scoped_code_accepts_its_own_option(self):
        from app.services.discount_pricing import validate_code
        scoped = code(scope_kind="payment_option", scope_id="po_activate")
        validate_code(scoped, space_id="s_1", payment_option_id="po_activate")

    def test_an_option_scoped_code_refuses_an_unnamed_option(self):
        from app.services.discount_pricing import validate_code
        scoped = code(scope_kind="payment_option", scope_id="po_activate")
        with pytest.raises(DiscountError):
            validate_code(scoped, space_id="s_1", payment_option_id=None)

    def test_a_space_scoped_code_applies_to_any_option(self):
        from app.services.discount_pricing import validate_code
        validate_code(code(), space_id="s_1", payment_option_id="po_anything")


# ---------------------------------------------------------------------------
# The immutable snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_it_captures_the_definition_and_the_money(self):
        amounts = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        snap = build_snapshot(code(), amounts)

        assert snap["code"] == "FAMILY50"
        assert snap["discount_type"] == "percentage"
        assert snap["percent_bps"] == 5000
        assert snap["original_amount_cents"] == 30600
        assert snap["discount_amount_cents"] == 15300
        assert snap["final_amount_cents"] == 15300
        assert snap["currency"] == AUD

    def test_it_does_not_change_when_the_definition_later_does(self):
        """The requirement in one test: a historical purchase reads its
        own copy, never the live row."""
        live = code()
        amounts = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        snap = build_snapshot(live, amounts)

        live.percent_bps = 1000
        live.is_active = False
        live.code = "CHANGED"

        assert snap["percent_bps"] == 5000
        assert snap["code"] == "FAMILY50"
        assert snap["discount_amount_cents"] == 15300

    def test_it_is_json_primitive_throughout(self):
        import json
        amounts = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        snap = build_snapshot(code(), amounts)
        assert json.loads(json.dumps(snap)) == snap

    def test_the_stored_code_is_canonical(self):
        amounts = compute_discount(
            original_cents=1800, currency=AUD,
            discount_type="percentage", percent_bps=5000,
        )
        assert build_snapshot(code(code="family50"), amounts)["code"] == "FAMILY50"


# ---------------------------------------------------------------------------
# 100% — deferred on purpose
# ---------------------------------------------------------------------------

class TestHundredPercentIsOutOfScope:
    def test_the_ceiling_is_ninety_nine_percent(self):
        """Not an arbitrary cap. A zero charge is a different fulfilment
        shape, and a recurring Stripe Price of zero is not coherent.
        Complimentary access is its own feature."""
        assert MAX_PERCENT_BPS == 9900

    def test_the_arithmetic_itself_would_cope(self):
        """Recorded so the later decision is about payments, not maths."""
        r = compute_discount(
            original_cents=30600, currency=AUD,
            discount_type="percentage", percent_bps=10000,
        )
        assert r.final_cents == 0


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

class TestInputGuards:
    def test_a_negative_price_is_refused(self):
        with pytest.raises(ValueError):
            compute_discount(
                original_cents=-1, currency=AUD,
                discount_type="percentage", percent_bps=5000,
            )

    def test_an_unknown_discount_type_is_refused(self):
        with pytest.raises(ValueError):
            compute_discount(
                original_cents=100, currency=AUD, discount_type="buy_one_get_one",
            )

    @pytest.mark.parametrize("count", [0, -1])
    def test_a_nonsense_instalment_count_is_refused(self, count):
        with pytest.raises(ValueError):
            discount_committed_total(
                installment_amount_cents=1000, installment_count=count,
                currency=AUD, discount_type="percentage", percent_bps=5000,
            )

    def test_a_percentage_code_without_a_percentage_is_refused(self):
        with pytest.raises(ValueError):
            compute_discount(
                original_cents=100, currency=AUD,
                discount_type="percentage", percent_bps=None,
            )

    def test_the_balance_invariant_is_asserted_at_construction(self):
        from app.services.discount_pricing import DiscountAmounts
        with pytest.raises(ValueError):
            DiscountAmounts(
                original_cents=100, discount_cents=10,
                final_cents=50, currency=AUD,
            )


# ---------------------------------------------------------------------------
# What a chosen expiry DATE means
# ---------------------------------------------------------------------------

class TestExpiryIsACalendarDayInTheCollectivesTimezone:
    """A Creator picks a day, not an instant.

    "Ends 31 Oct" means the code works for all of 31 October where the
    Collective is. The server resolves that, because the browser's
    timezone is the reader's travel accident and has nothing to do with
    when an offer ends — a frontend sending 23:59:59 would run a
    Melbourne code eleven hours into 1 November.

    Stored as the start of the NEXT local day, held exclusively, which is
    the half-open shape ``core/periods`` documents as the only one that
    survives midnight, month rollover and DST without arithmetic hazards.
    ``validate_code`` already treats ``expires_at <= now`` as expired, so
    that instant is the first moment the code is gone.
    """

    def test_melbourne_resolves_to_the_right_utc_instant(self):
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        # 31 Oct 2026 is AEDT (+11). The day ends at 1 Nov 00:00 +11:00.
        instant = resolve_expiry_instant(date(2026, 10, 31), "Australia/Melbourne")

        assert instant == datetime(2026, 10, 31, 13, 0, 0)

    def test_a_code_is_still_valid_late_on_the_chosen_day(self):
        """11:59 pm Melbourne on the 31st — inside the day, so usable."""
        from app.services.discount_pricing import resolve_expiry_instant, validate_code
        from datetime import date

        instant = resolve_expiry_instant(date(2026, 10, 31), "Australia/Melbourne")
        # 23:59 Melbourne on the 31st = 12:59 UTC.
        validate_code(code(expires_at=instant), space_id="s_1",
                      now=datetime(2026, 10, 31, 12, 59, 0))

    def test_and_expired_the_moment_the_next_day_begins_there(self):
        from app.services.discount_pricing import resolve_expiry_instant, validate_code
        from datetime import date

        instant = resolve_expiry_instant(date(2026, 10, 31), "Australia/Melbourne")
        with pytest.raises(DiscountError) as exc:
            validate_code(code(expires_at=instant), space_id="s_1", now=instant)
        assert exc.value.reason is DiscountRejection.EXPIRED

    def test_it_does_not_leak_into_the_next_local_day(self):
        """The bug this replaced: 23:59:59 UTC would have kept a Melbourne
        code alive until 11am on 1 November."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        correct = resolve_expiry_instant(date(2026, 10, 31), "Australia/Melbourne")
        naive_utc_end_of_day = datetime(2026, 10, 31, 23, 59, 59)

        assert correct < naive_utc_end_of_day
        # Eleven hours of difference, which is exactly the AEDT offset.
        assert (naive_utc_end_of_day - correct).total_seconds() > 10 * 3600

    def test_a_dst_sensitive_date_uses_the_offset_in_force_that_day(self):
        """Melbourne moves to AEDT (+11) on 4 Oct 2026. A date either
        side of that must use its own offset, not a fixed one."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        aest = resolve_expiry_instant(date(2026, 10, 1), "Australia/Melbourne")
        aedt = resolve_expiry_instant(date(2026, 10, 31), "Australia/Melbourne")

        # 2 Oct 00:00 +10:00 → 1 Oct 14:00 UTC
        assert aest == datetime(2026, 10, 1, 14, 0, 0)
        # 1 Nov 00:00 +11:00 → 31 Oct 13:00 UTC
        assert aedt == datetime(2026, 10, 31, 13, 0, 0)

    def test_the_dst_transition_day_itself_resolves(self):
        """4 Oct 2026 is the day the clocks go forward — 2am does not
        exist. Midnight does, so the boundary is well defined."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        instant = resolve_expiry_instant(date(2026, 10, 3), "Australia/Melbourne")
        assert instant == datetime(2026, 10, 3, 14, 0, 0)

    def test_a_utc_collective_gets_plain_midnight(self):
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        assert resolve_expiry_instant(date(2026, 10, 31), "UTC") == datetime(2026, 11, 1)

    def test_a_western_collective_ends_later_in_utc(self):
        """New York is behind UTC, so its day ends after UTC's does."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        # 1 Nov 2026 00:00 EDT (-4) → 1 Nov 04:00 UTC.
        assert resolve_expiry_instant(
            date(2026, 10, 31), "America/New_York",
        ) == datetime(2026, 11, 1, 4, 0, 0)

    def test_the_collectives_timezone_decides_not_the_readers(self):
        """The same chosen day yields different instants per Collective —
        and nothing in the call depends on the caller's environment."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        chosen = date(2026, 10, 31)
        results = {
            tz: resolve_expiry_instant(chosen, tz)
            for tz in ("Australia/Melbourne", "UTC", "America/New_York")
        }
        assert len(set(results.values())) == 3

    def test_an_unusable_timezone_falls_back_rather_than_raising(self):
        """A Creator saving a code should not meet a 500 because a stored
        timezone string is wrong; the column's NOT NULL default is the
        same value this falls back to."""
        from app.services.discount_pricing import resolve_expiry_instant
        from datetime import date

        assert resolve_expiry_instant(
            date(2026, 10, 31), "Not/AZone",
        ) == datetime(2026, 10, 31, 13, 0, 0)

    def test_no_expiry_stays_no_expiry(self):
        from app.services.discount_pricing import resolve_expiry_instant
        assert resolve_expiry_instant(None, "Australia/Melbourne") is None

    @pytest.mark.parametrize("tz", [
        "Australia/Melbourne", "UTC", "America/New_York", "Europe/London",
        "Pacific/Auckland", "Asia/Kolkata",
    ])
    @pytest.mark.parametrize("day", ["2026-01-15", "2026-10-03", "2026-10-31", "2026-12-31"])
    def test_the_displayed_date_is_always_the_chosen_date(self, tz, day):
        """The round trip that matters to a Creator: whatever we store,
        they are shown back the day they picked — including across DST
        boundaries and half-hour offsets."""
        from app.services.discount_pricing import (
            expiry_date_in_timezone, resolve_expiry_instant,
        )
        from datetime import date as _date

        chosen = _date.fromisoformat(day)
        instant = resolve_expiry_instant(chosen, tz)

        assert expiry_date_in_timezone(instant, tz) == chosen
