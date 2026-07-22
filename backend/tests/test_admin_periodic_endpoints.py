"""
Integration tests for the periodic summary endpoints.

Rather than a TestClient trip (which would require the full auth stack
and a valid admin session), these exercise the two responsibilities the
endpoints add on top of the existing summaries:

1. Windowing — ``_compute_payment_summary`` / ``_compute_revenue_summary``
   see only rows whose ``created_at`` lies in the requested half-open
   interval.
2. Stripe-mode independence — a ``stripe_mode`` filter is orthogonal to
   the period window; the two never mix.

The response wrapper the endpoint returns is trivial glue (schema
projection); ``test_periods.py`` already covers the boundary math it
depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.admin.routes import (
    _compute_payment_summary,
    _compute_revenue_summary,
    get_admin_payment_summary_periodic,
    get_revenue_summary_periodic,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_member_txn(
    db,
    *,
    creator,
    payer,
    space,
    created_at: datetime,
    gross_cents: int = 5_000,
    stripe_mode: str = "test",
    status: PaymentTransactionStatus = PaymentTransactionStatus.succeeded,
    payout_status: PayoutStatus = PayoutStatus.pending,
) -> PaymentTransaction:
    """Insert a member-collective-purchase transaction at a fixed
    ``created_at`` (naive UTC). Uses the same money proportions
    (`platform_fee_basis_points=800`) as the ticket factory."""
    fee = int(gross_cents * 0.08)
    txn = PaymentTransaction(
        id=f"txn_{created_at.strftime('%Y%m%d%H%M%S%f')}_{gross_cents}_{stripe_mode}",
        transaction_type=PaymentTransactionType.member_collective_purchase,
        status=status,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=800,
        platform_fee_cents=fee,
        net_creator_amount_cents=gross_cents - fee,
        stripe_mode=stripe_mode,
        payout_status=payout_status,
        created_at=created_at,
    )
    db.add(txn)
    db.flush()
    return txn


@pytest.fixture
def commerce_seed(db, make_user, make_space):
    """Seed a spread of transactions across period boundaries.

    Wall clock: 18 July 2026 13:30 Sydney (AEST +10) = 03:30 UTC.

      A: 5 July 2026 UTC  — in "this_month" AND in FY 2026-27
      B: 10 June 2026 UTC — in "last_month" AND in FY 2025-26
      C: 15 May 2026 UTC  — in month-before-last AND in FY 2025-26
      D: 5 July 2025 UTC  — same-day-of-FY on previous FY
      E: 5 July 2026 UTC  — same as A but stripe_mode='live'
      F: 5 May 2020 UTC   — far past, only in `all_time`
    """
    creator = make_user(role="creator")
    payer = make_user(role="user")
    space = make_space(creator=creator)

    seeds = {
        "A_this_month_test": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2026, 7, 5, 12, 0, 0),
            gross_cents=1_000, stripe_mode="test",
        ),
        "B_last_month_test": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2026, 6, 10, 12, 0, 0),
            gross_cents=2_000, stripe_mode="test",
        ),
        "C_month_before_last_test": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2026, 5, 15, 12, 0, 0),
            gross_cents=3_000, stripe_mode="test",
        ),
        "D_prev_fy_same_day_test": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2025, 7, 5, 12, 0, 0),
            gross_cents=4_000, stripe_mode="test",
        ),
        "E_this_month_live": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2026, 7, 5, 12, 0, 0),
            gross_cents=8_000, stripe_mode="live",
        ),
        "F_far_past_test": _seed_member_txn(
            db, creator=creator, payer=payer, space=space,
            created_at=datetime(2020, 5, 5, 12, 0, 0),
            gross_cents=500, stripe_mode="test",
        ),
    }
    return seeds


NOW = datetime(2026, 7, 18, 3, 30, 0, tzinfo=timezone.utc)  # 18 Jul 2026 13:30 Sydney AEST


# ---------------------------------------------------------------------------
# Payment summary — windowing
# ---------------------------------------------------------------------------


class TestPaymentSummaryWindow:
    def test_this_month_current_only_covers_july(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, _ = resolve_period("this_month", now=NOW)
        summary = _compute_payment_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        )
        # A (test, 1000) + E (live, 8000) both fall in July 2026 UTC.
        assert summary.total_gross_amount_cents == 9_000
        assert summary.succeeded_count == 2

    def test_this_month_previous_covers_june_1_18(self, db, commerce_seed):
        from app.core.periods import resolve_period
        _, previous_bounds = resolve_period("this_month", now=NOW)
        assert previous_bounds is not None
        summary = _compute_payment_summary(
            db,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
        )
        # B (10 June, 2000) falls in 1–18 June. C is in May, not counted.
        assert summary.total_gross_amount_cents == 2_000
        assert summary.succeeded_count == 1

    def test_last_month_current_covers_full_june(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, previous_bounds = resolve_period("last_month", now=NOW)
        current = _compute_payment_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        )
        # Only B lands in June 2026.
        assert current.total_gross_amount_cents == 2_000
        assert previous_bounds is not None
        previous = _compute_payment_summary(
            db,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
        )
        # Only C lands in May 2026.
        assert previous.total_gross_amount_cents == 3_000


# ---------------------------------------------------------------------------
# Revenue summary — windowing
# ---------------------------------------------------------------------------


class TestRevenueSummaryWindow:
    def test_this_fy_current_covers_jul_to_now(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, previous_bounds = resolve_period("this_fy", now=NOW)
        current = _compute_revenue_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        )
        # A+E succeed in current FY 2026-27 by 18 Jul.
        # gross_sales = A(1000) + E(8000) = 9000
        assert current.total_gross_sales_cents == 9_000
        assert current.succeeded_transactions == 2

        assert previous_bounds is not None
        previous = _compute_revenue_summary(
            db,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
        )
        # Prev FY same span: [1 Jul 2025, 18 Jul 2025 03:30 UTC).
        # Only D (5 July 2025) lands in that window.
        assert previous.total_gross_sales_cents == 4_000

    def test_all_time_current_covers_every_row(self, db, commerce_seed):
        summary = _compute_revenue_summary(db, starts_at=None, ends_at=None)
        # All six rows succeeded.
        assert summary.succeeded_transactions == 6

    def test_empty_window_returns_zeros_not_errors(self, db, commerce_seed):
        # Empty window: 1 Jan 2026 → 1 Feb 2026. No seeded rows here.
        summary = _compute_revenue_summary(
            db,
            starts_at=datetime(2026, 1, 1, 0, 0, 0),
            ends_at=datetime(2026, 2, 1, 0, 0, 0),
        )
        assert summary.total_gross_sales_cents == 0
        assert summary.succeeded_transactions == 0
        assert summary.refunded_transactions == 0
        assert summary.failed_transactions == 0


# ---------------------------------------------------------------------------
# Stripe-mode independence
# ---------------------------------------------------------------------------


class TestStripeModeIndependent:
    def test_test_mode_excludes_live_row(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, _ = resolve_period("this_month", now=NOW)
        summary = _compute_payment_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
            stripe_mode="test",
        )
        # A only (E is live)
        assert summary.total_gross_amount_cents == 1_000
        assert summary.succeeded_count == 1

    def test_live_mode_excludes_test_rows(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, _ = resolve_period("this_month", now=NOW)
        summary = _compute_payment_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
            stripe_mode="live",
        )
        # E only
        assert summary.total_gross_amount_cents == 8_000
        assert summary.succeeded_count == 1

    def test_no_mode_includes_both(self, db, commerce_seed):
        from app.core.periods import resolve_period
        current_bounds, _ = resolve_period("this_month", now=NOW)
        summary = _compute_payment_summary(
            db,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        )
        assert summary.total_gross_amount_cents == 9_000  # A + E


# ---------------------------------------------------------------------------
# Endpoint wrapper — response shape
# ---------------------------------------------------------------------------


class TestEndpointResponseShape:
    def test_all_time_response_has_no_previous(self, db, commerce_seed, make_user):
        admin = make_user(role="admin")
        result = get_admin_payment_summary_periodic(
            period="all_time",
            stripe_mode=None,
            _=admin,
            db=db,
        )
        assert result.period == "all_time"
        assert result.current_bounds.label == "All time"
        assert result.current_bounds.starts_at is None
        assert result.current_bounds.ends_at is None
        assert result.previous is None
        assert result.previous_bounds is None

    def test_this_month_response_carries_both_windows(self, db, commerce_seed, make_user):
        admin = make_user(role="admin")
        result = get_revenue_summary_periodic(
            period="this_month",
            stripe_mode="test",
            _=admin,
            db=db,
        )
        assert result.period == "this_month"
        assert result.stripe_mode == "test"
        assert result.current_bounds.label == "This month"
        assert result.current_bounds.starts_at is not None
        assert result.current_bounds.ends_at is not None
        assert result.previous is not None
        assert result.previous_bounds is not None
        assert result.previous_bounds.starts_at is not None
        assert result.previous_bounds.ends_at is not None

    def test_invalid_period_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as excinfo:
            get_admin_payment_summary_periodic(
                period="last_quarter",
                stripe_mode=None,
                _=admin,
                db=db,
            )
        assert excinfo.value.status_code == 422
