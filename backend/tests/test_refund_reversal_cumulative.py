"""Cumulative fee-reversal algorithm (migration 127 + refund_reversal).

Covers the pure function ``compute_cumulative_reversal_targets`` and
the wired-up behaviour on the ``charge.refunded`` handler.

Invariant on every write:

    refunded_platform_fee_cents + refunded_creator_amount_cents
        == refunded_amount_cents
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.services.refund_reversal import compute_cumulative_reversal_targets
from app.webhooks.refund_handlers import _do_charge_refunded


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


class TestComputeCumulativeReversalTargets:
    def test_zero_refund_produces_zero_targets(self):
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=10000,
            platform_fee_cents=1000,
            net_creator_amount_cents=9000,
            cumulative_refunded=0,
        )
        assert (p, c) == (0, 0)

    def test_partial_refund_proportional_share(self):
        # 30% refund on gross=10000, fee=1000, creator=9000
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=10000,
            platform_fee_cents=1000,
            net_creator_amount_cents=9000,
            cumulative_refunded=3000,
        )
        assert p == 300
        assert c == 2700
        assert p + c == 3000

    def test_full_refund_coerced_to_exact_originals(self):
        # cumulative == gross → full-refund short circuit ignores rounding.
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=10000,
            platform_fee_cents=333,
            net_creator_amount_cents=9667,
            cumulative_refunded=10000,
        )
        assert p == 333
        assert c == 9667
        assert p + c == 10000

    def test_cumulative_beyond_gross_still_coerced(self):
        # Should never happen from Stripe, but defensively coerce.
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=10000,
            platform_fee_cents=1000,
            net_creator_amount_cents=9000,
            cumulative_refunded=15000,
        )
        assert p == 1000
        assert c == 9000

    def test_invariant_holds_across_range(self):
        # Fuzz across the whole cumulative range; invariant must hold.
        gross, fee = 10000, 333
        net = gross - fee
        for cum in range(0, gross + 1, 1):
            p, c = compute_cumulative_reversal_targets(
                gross_amount_cents=gross,
                platform_fee_cents=fee,
                net_creator_amount_cents=net,
                cumulative_refunded=cum,
            )
            assert p + c == cum, f"invariant failed at cum={cum}"
            assert 0 <= p <= fee
            assert 0 <= c <= net

    def test_zero_fee_platform_owned_transaction(self):
        # Platform-owned collective — fee=0 everywhere.
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=10000,
            platform_fee_cents=0,
            net_creator_amount_cents=10000,
            cumulative_refunded=3000,
        )
        assert p == 0
        assert c == 3000

    def test_pathological_fee_greater_than_gross_is_clamped(self):
        # Should never happen in practice but the clamp protects us.
        p, c = compute_cumulative_reversal_targets(
            gross_amount_cents=100,
            platform_fee_cents=1000,  # nonsense
            net_creator_amount_cents=-900,  # nonsense
            cumulative_refunded=50,
        )
        assert p >= 0
        assert c >= 0
        assert p + c == 50


# ---------------------------------------------------------------------------
# Handler-integration tests
# ---------------------------------------------------------------------------


def _make_txn(db, *, gross=10000, fee=1000):
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=int(fee * 10000 / gross),
        platform_fee_cents=fee,
        net_creator_amount_cents=gross - fee,
        net_platform_amount_cents=fee,
        provider_charge_id=f"ch_test_{uuid.uuid4().hex[:8]}",
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(txn)
    db.flush()
    db.commit()
    return txn


def _charge(txn, *, amount_refunded, refunded=False):
    return {
        "id": txn.provider_charge_id,
        "payment_intent": None,
        "amount_refunded": amount_refunded,
        "refunded": refunded,
        "refunds": {"data": [], "has_more": False},
    }


class TestHandlerCumulativeUpdate:
    def test_partial_then_larger_partial_uses_cumulative_targets(self, db):
        txn = _make_txn(db, gross=10000, fee=1000)
        _do_charge_refunded(db, charge=_charge(txn, amount_refunded=3000), event_created=None)
        db.commit()
        db.refresh(txn)
        assert txn.refunded_amount_cents == 3000
        assert txn.refunded_platform_fee_cents == 300
        assert txn.refunded_creator_amount_cents == 2700

        _do_charge_refunded(db, charge=_charge(txn, amount_refunded=7000), event_created=None)
        db.commit()
        db.refresh(txn)
        # Cumulative targets — NOT incremental
        assert txn.refunded_amount_cents == 7000
        assert txn.refunded_platform_fee_cents == 700
        assert txn.refunded_creator_amount_cents == 6300

    def test_multiple_partials_with_rounding_divergence(self, db):
        # Rounding matters: fee=333/10000 (~3.33%). Cumulative rounding
        # produces DIFFERENT results from summed per-event rounding.
        # Incremental would give 3+3+3=9 platform reversal.
        # Cumulative gives round(300 * 333 / 10000) = round(9.99) = 10.
        txn = _make_txn(db, gross=10000, fee=333)
        for cum in (100, 200, 300):
            _do_charge_refunded(db, charge=_charge(txn, amount_refunded=cum), event_created=None)
            db.commit()
        db.refresh(txn)
        assert txn.refunded_amount_cents == 300
        assert txn.refunded_platform_fee_cents == 10  # cumulative rounding, not 3+3+3
        assert txn.refunded_creator_amount_cents == 290
        assert txn.refunded_platform_fee_cents + txn.refunded_creator_amount_cents == 300

    def test_partial_then_full_coerces_to_exact_originals(self, db):
        txn = _make_txn(db, gross=10000, fee=333)
        _do_charge_refunded(db, charge=_charge(txn, amount_refunded=5000), event_created=None)
        db.commit()
        db.refresh(txn)
        _do_charge_refunded(
            db, charge=_charge(txn, amount_refunded=10000, refunded=True),
            event_created=None,
        )
        db.commit()
        db.refresh(txn)
        # Full refund → exact originals, no rounding drift.
        assert txn.refunded_amount_cents == 10000
        assert txn.refunded_platform_fee_cents == 333
        assert txn.refunded_creator_amount_cents == 9667
        assert txn.status == PaymentTransactionStatus.refunded

    def test_out_of_order_older_event_ignored(self, db):
        txn = _make_txn(db, gross=10000, fee=1000)
        _do_charge_refunded(db, charge=_charge(txn, amount_refunded=7000), event_created=None)
        db.commit()
        # An out-of-order older event with lower cumulative. Existing
        # monotonic guard skips before compute — ledger unchanged.
        _do_charge_refunded(db, charge=_charge(txn, amount_refunded=3000), event_created=None)
        db.commit()
        db.refresh(txn)
        assert txn.refunded_amount_cents == 7000
        assert txn.refunded_platform_fee_cents == 700
        assert txn.refunded_creator_amount_cents == 6300

    def test_duplicate_event_delivery_is_idempotent(self, db):
        txn = _make_txn(db, gross=10000, fee=1000)
        for _ in range(3):
            _do_charge_refunded(
                db, charge=_charge(txn, amount_refunded=5000), event_created=None,
            )
            db.commit()
        db.refresh(txn)
        assert txn.refunded_amount_cents == 5000
        assert txn.refunded_platform_fee_cents == 500
        assert txn.refunded_creator_amount_cents == 4500

    def test_full_refund_zero_retained(self, db):
        txn = _make_txn(db, gross=10000, fee=800)
        _do_charge_refunded(
            db, charge=_charge(txn, amount_refunded=10000, refunded=True),
            event_created=None,
        )
        db.commit()
        db.refresh(txn)
        # After full refund, retained fee + retained creator amount
        # both zero — the promised invariant for the summary aggregation.
        assert txn.platform_fee_cents - txn.refunded_platform_fee_cents == 0
        assert (txn.net_creator_amount_cents or 0) - txn.refunded_creator_amount_cents == 0

    def test_zero_fee_platform_owned_row(self, db):
        txn = _make_txn(db, gross=10000, fee=0)
        _do_charge_refunded(
            db, charge=_charge(txn, amount_refunded=4000), event_created=None,
        )
        db.commit()
        db.refresh(txn)
        # All the refund attributes to creator; platform reversal 0.
        assert txn.refunded_platform_fee_cents == 0
        assert txn.refunded_creator_amount_cents == 4000
