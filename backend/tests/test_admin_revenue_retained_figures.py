"""World Management commerce semantics — retained-figure accounting.

Covers ``_compute_revenue_summary`` after the semantic rewrite that
uses cumulative refund reversal (migration 127) and distinguishes
platform-owned (``creator_user_id IS NULL``) from third-party creator
transactions.

Card-by-card invariants tested:

* Gross Volume includes fully-refunded rows at their original gross.
* Gross Volume includes partially-refunded rows at their original gross.
* Third-party creator partial refund reduces FC Revenue by the
  reversed platform fee.
* Third-party creator partial refund reduces Creator Earnings by
  the reversed creator amount.
* Platform-owned sale contributes retained-gross to FC Revenue.
* Platform-owned sale contributes ZERO to Creator Earnings.
* Fully-refunded platform-owned sale contributes zero FC Revenue.
* Pending Creator Payouts uses retained creator earnings.
* Platform-owned rows never appear in Pending Payouts.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.admin.routes import _compute_revenue_summary
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)


def _make_txn(
    db, *,
    creator_user_id: str | None,
    space_id: str,
    payer_user_id: str,
    gross: int, fee: int,
    refunded: int = 0,
    refunded_platform_fee: int = 0,
    refunded_creator: int = 0,
    status: PaymentTransactionStatus = PaymentTransactionStatus.succeeded,
    payout_status: PayoutStatus = PayoutStatus.pending,
    txn_type: PaymentTransactionType = PaymentTransactionType.member_payment_option_purchase,
) -> PaymentTransaction:
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=txn_type,
        status=status,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=payer_user_id,
        creator_user_id=creator_user_id,
        space_id=space_id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=(
            int(fee * 10000 / gross) if gross > 0 else 0
        ),
        platform_fee_cents=fee,
        net_creator_amount_cents=(gross - fee),
        net_platform_amount_cents=fee,
        refunded_amount_cents=refunded,
        refunded_platform_fee_cents=refunded_platform_fee,
        refunded_creator_amount_cents=refunded_creator,
        stripe_mode="test",
        payout_status=payout_status,
    )
    db.add(txn)
    db.flush()
    db.commit()
    return txn


class TestGrossVolume:
    def test_fully_refunded_row_still_counts_in_gross(self, db, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            refunded=10000, refunded_platform_fee=1000, refunded_creator=9000,
            status=PaymentTransactionStatus.refunded,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_gross_sales_cents == 10000

    def test_partially_refunded_row_counts_at_original_gross(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            refunded=3000, refunded_platform_fee=300, refunded_creator=2700,
            status=PaymentTransactionStatus.partially_refunded,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_gross_sales_cents == 10000


class TestThirdPartyCreator:
    def test_partial_refund_produces_proportional_retained_fc_fee(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        # $100 sale, 10% fee → $10 fee, $90 creator. Refund $30 →
        # reversed fee $3, retained fee $7.
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            refunded=3000, refunded_platform_fee=300, refunded_creator=2700,
            status=PaymentTransactionStatus.partially_refunded,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.platform_fee_revenue_cents == 700
        assert summary.total_fc_revenue_cents == 700  # no subs

    def test_partial_refund_produces_retained_creator_earnings(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            refunded=3000, refunded_platform_fee=300, refunded_creator=2700,
            status=PaymentTransactionStatus.partially_refunded,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        # Original creator net = 9000, reversed = 2700, retained = 6300.
        assert summary.total_creator_net_cents == 6300


class TestPlatformOwned:
    def test_platform_owned_retained_gross_flows_to_fc_revenue(
        self, db, make_user, make_space,
    ):
        member = make_user()
        # Platform-owned: creator=None → Space.creator_id IS NULL.
        space = make_space(creator_id=None)
        # $100 platform-owned sale, no refund. FC keeps entire $100.
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=0,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.not_applicable,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_fc_revenue_cents == 10000
        assert summary.platform_fee_revenue_cents == 10000

    def test_platform_owned_contributes_zero_to_creator_earnings(
        self, db, make_user, make_space,
    ):
        member = make_user()
        space = make_space(creator_id=None)
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=0,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.not_applicable,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_creator_net_cents == 0

    def test_fully_refunded_platform_owned_contributes_zero_fc_revenue(
        self, db, make_user, make_space,
    ):
        member = make_user()
        space = make_space(creator_id=None)
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=0,
            refunded=10000, refunded_platform_fee=0, refunded_creator=10000,
            status=PaymentTransactionStatus.refunded,
            payout_status=PayoutStatus.not_applicable,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        # Retained gross = 10000 - 10000 = 0.
        assert summary.total_fc_revenue_cents == 0
        assert summary.platform_fee_revenue_cents == 0
        # Gross Volume unchanged (history).
        assert summary.total_gross_sales_cents == 10000

    def test_partially_refunded_platform_owned_retained_gross(
        self, db, make_user, make_space,
    ):
        member = make_user()
        space = make_space(creator_id=None)
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=0,
            refunded=3000, refunded_platform_fee=0, refunded_creator=3000,
            status=PaymentTransactionStatus.partially_refunded,
            payout_status=PayoutStatus.not_applicable,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_fc_revenue_cents == 7000

    def test_embody_style_current_production_platform_owned(
        self, db, make_user, make_space,
    ):
        """Regression scenario mirroring current EMBODY production state
        under the PLATFORM-OWNED interpretation (Space.creator_id IS NULL):

        THREE rows in scope, all platform-owned, all fee=0:

          1. $1 pay-in-full — succeeded, refunded_amount_cents = 0
          2. $1 pay-in-full — fully refunded
          3. $20 finite-plan instalment — fully refunded

        Expected:
          Gross Volume            = 100 + 100 + 2000 = 2200 cents ($22)
          Fresh Collective Revenue = retained-gross-per-row summed:
                                     (100-0) + (100-100) + (2000-2000) = 100
          Creator Earnings         = 0 (platform-owned contributes zero)
          Pending Creator Payouts  = 0 (platform-owned excluded from pool)
        """
        member = make_user()
        space = make_space(creator_id=None)
        # Row 1 — surviving $1 succeeded, not refunded.
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=100, fee=0,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.not_applicable,
        )
        # Row 2 — $1 fully refunded.
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=100, fee=0,
            refunded=100, refunded_platform_fee=0, refunded_creator=100,
            status=PaymentTransactionStatus.refunded,
            payout_status=PayoutStatus.not_applicable,
        )
        # Row 3 — $20 fully refunded.
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=2000, fee=0,
            refunded=2000, refunded_platform_fee=0, refunded_creator=2000,
            status=PaymentTransactionStatus.refunded,
            payout_status=PayoutStatus.not_applicable,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_gross_sales_cents == 2200
        # Retained-gross bucket for platform-owned:
        #   100 (surviving) + 0 (refunded $1) + 0 (refunded $20) = 100.
        assert summary.total_fc_revenue_cents == 100
        assert summary.platform_fee_revenue_cents == 100
        assert summary.total_creator_net_cents == 0
        assert summary.pending_payout_cents == 0

    def test_embody_style_current_production_creator_owned_zero_fee(
        self, db, make_user, make_space,
    ):
        """Alternative interpretation — EMBODY has Space.creator_id set
        to a real user whose CreatorPlan carries 0 bps. Same three
        production rows, but creator_user_id IS NOT NULL and fee=0.

        Under the strict third-party path:
          Gross Volume            = 2200
          Fresh Collective Revenue = SUM(platform_fee - refunded_platform_fee) = 0
          Creator Earnings         = retained-net-creator, third-party only:
                                     (100-0) + (100-100) + (2000-2000) = 100
          Pending Creator Payouts  = 100 (the one succeeded row still pending)
        """
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        # Row 1 — surviving $1 succeeded.
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=100, fee=0,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.pending,
        )
        # Row 2 — $1 fully refunded.
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=100, fee=0,
            refunded=100, refunded_platform_fee=0, refunded_creator=100,
            status=PaymentTransactionStatus.refunded,
            payout_status=PayoutStatus.pending,
        )
        # Row 3 — $20 fully refunded.
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=2000, fee=0,
            refunded=2000, refunded_platform_fee=0, refunded_creator=2000,
            status=PaymentTransactionStatus.refunded,
            payout_status=PayoutStatus.pending,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.total_gross_sales_cents == 2200
        assert summary.total_fc_revenue_cents == 0
        assert summary.platform_fee_revenue_cents == 0
        # Retained creator earnings from the surviving row.
        assert summary.total_creator_net_cents == 100
        assert summary.pending_payout_cents == 100


class TestPendingPayoutRetained:
    def test_pending_payout_uses_retained_creator_earnings(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            refunded=3000, refunded_platform_fee=300, refunded_creator=2700,
            status=PaymentTransactionStatus.partially_refunded,
            payout_status=PayoutStatus.pending,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.pending_payout_cents == 6300

    def test_platform_owned_never_appears_in_pending_payouts(
        self, db, make_user, make_space,
    ):
        member = make_user()
        space = make_space(creator_id=None)
        _make_txn(
            db, creator_user_id=None, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=0,
            status=PaymentTransactionStatus.succeeded,
            # Even if some code path incorrectly stamped 'pending' on
            # a platform-owned row, our filter excludes it via
            # ``creator_user_id IS NOT NULL``.
            payout_status=PayoutStatus.pending,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.pending_payout_cents == 0

    def test_paid_status_excluded_from_pending(self, db, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_txn(
            db, creator_user_id=creator.id, space_id=space.id,
            payer_user_id=member.id,
            gross=10000, fee=1000,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.paid,
        )
        summary = _compute_revenue_summary(db, stripe_mode="test")
        assert summary.pending_payout_cents == 0
        assert summary.paid_out_cents == 9000  # retained (no refund)
