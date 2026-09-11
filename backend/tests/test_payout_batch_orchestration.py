"""Manual creator payout batch — orchestration, exclusion rules,
immutability, cancellation.

Covers:

* eligibility filter — active refunds excluded, fully-refunded rows
  excluded (retained==0), payout_status='paid' excluded;
* snapshot-total staleness check;
* atomic marks-paid + creates BatchItems;
* BatchItem immutability across cancellation;
* revert_transactions=true reverts pointer + status;
* re-payment in a later batch creates a NEW BatchItem;
* payout batch scope — creator + currency across multiple owned Spaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.creator_payout_batch import (
    CreatorPayoutBatch,
    CreatorPayoutBatchItem,
    CreatorPayoutBatchStatus,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationReason,
    RefundOperationTerminalStatus,
    StripeIdentifierKind,
)
from app.services import payout_batch_orchestration as _pbo


def _make_txn(
    db, *, creator, space, gross=10000, fee=1000,
    refunded_creator=0, payout_status=PayoutStatus.pending,
    stripe_status=PaymentTransactionStatus.succeeded,
):
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=stripe_status,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=int(fee * 10000 / gross),
        platform_fee_cents=fee,
        net_creator_amount_cents=gross - fee,
        net_platform_amount_cents=fee,
        refunded_creator_amount_cents=refunded_creator,
        provider_charge_id=f"ch_{uuid.uuid4().hex[:12]}",
        stripe_mode="test",
        payout_status=payout_status,
    )
    db.add(txn)
    db.flush()
    db.commit()
    return txn


def _make_op(db, txn, *, terminal_status):
    op = RefundOperation(
        id=f"refop_{uuid.uuid4().hex[:12]}",
        payment_transaction_id=txn.id,
        requested_by_user_id=None,
        requested_at=datetime.utcnow(),
        reason=RefundOperationReason.member_request.value,
        requested_amount_cents=100,
        expected_cumulative_refunded_amount_cents=100,
        stripe_identifier_kind=StripeIdentifierKind.charge.value,
        stripe_identifier_value=txn.provider_charge_id,
        terminal_status=terminal_status,
    )
    db.add(op)
    db.commit()
    return op


class TestEligibility:
    def test_active_refund_excludes_transaction(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        t2 = _make_txn(db, creator=creator, space=space)
        # t2 has an active in_flight refund → excluded.
        _make_op(db, t2, terminal_status=RefundOperationTerminalStatus.in_flight.value)

        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000,  # only t1
            note=None, created_by=creator,
        )
        assert outcome.included_transaction_ids == [t1.id]
        assert outcome.transaction_count == 1

    def test_accepted_refund_excludes_transaction(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        t2 = _make_txn(db, creator=creator, space=space)
        _make_op(db, t2, terminal_status=RefundOperationTerminalStatus.accepted.value)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-02", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        assert outcome.included_transaction_ids == [t1.id]

    def test_fully_refunded_transaction_naturally_excluded(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # Fully refunded — retained creator amount = 0.
        _make_txn(
            db, creator=creator, space=space,
            refunded_creator=9000,
            stripe_status=PaymentTransactionStatus.refunded,
        )
        t2 = _make_txn(db, creator=creator, space=space)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-03", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        assert outcome.included_transaction_ids == [t2.id]
        assert outcome.transaction_count == 1

    def test_partially_refunded_included_at_retained_amount(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # Partially refunded: net_creator=9000, refunded_creator=3000
        # → retained 6000.
        t = _make_txn(
            db, creator=creator, space=space,
            refunded_creator=3000,
            stripe_status=PaymentTransactionStatus.partially_refunded,
        )
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-04", paid_at=datetime.utcnow(),
            submitted_total_cents=6000, note=None, created_by=creator,
        )
        assert outcome.total_amount_cents == 6000
        assert outcome.included_transaction_ids == [t.id]

    def test_already_paid_transaction_excluded(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_txn(db, creator=creator, space=space, payout_status=PayoutStatus.paid)
        with pytest.raises(_pbo.PayoutBatchNoEligibleError):
            _pbo.create_payout_batch(
                db, creator=creator, currency="AUD",
                reference="TEST-05", paid_at=datetime.utcnow(),
                submitted_total_cents=0, note=None, created_by=creator,
            )

    def test_scope_creator_plus_currency_across_multiple_spaces(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space_a)
        t2 = _make_txn(db, creator=creator, space=space_b)

        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="TEST-06", paid_at=datetime.utcnow(),
            submitted_total_cents=18000, note=None, created_by=creator,
        )
        assert set(outcome.included_transaction_ids) == {t1.id, t2.id}
        # Batch itself has NO space_id.
        batch = db.get(CreatorPayoutBatch, outcome.batch_id)
        assert not hasattr(batch, "space_id") or getattr(batch, "space_id", None) is None


class TestStaleness:
    def test_snapshot_total_mismatch_raises(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_txn(db, creator=creator, space=space)
        with pytest.raises(_pbo.PayoutBatchStalenessError):
            _pbo.create_payout_batch(
                db, creator=creator, currency="AUD",
                reference="STALE-01", paid_at=datetime.utcnow(),
                submitted_total_cents=99999,  # doesn't match snapshot
                note=None, created_by=creator,
            )


class TestBatchCreateSideEffects:
    def test_transactions_marked_paid_and_batch_item_created(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="MARK-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        db.refresh(t1)
        assert t1.payout_status == PayoutStatus.paid
        assert t1.payout_batch_id is not None
        assert t1.payout_reference == "MARK-01"
        item = db.query(CreatorPayoutBatchItem).filter(
            CreatorPayoutBatchItem.payment_transaction_id == t1.id
        ).first()
        assert item is not None
        assert item.creator_amount_cents_at_payout == 9000
        assert item.refunded_creator_amount_cents_at_payout == 0


class TestBatchItemImmutability:
    def test_cancel_with_revert_preserves_batch_items(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="IMMUT-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        batch = db.get(CreatorPayoutBatch, outcome.batch_id)
        _pbo.cancel_payout_batch(
            db, batch=batch,
            cancelled_by=creator,
            cancellation_reason="test cancel",
            revert_transactions=True,
        )
        db.refresh(t1)
        # PaymentTransaction reverted — convenience pointer cleared.
        assert t1.payout_status == PayoutStatus.pending
        assert t1.payout_batch_id is None
        assert t1.payout_reference is None
        # BatchItem row still exists — historical fact preserved.
        item = db.query(CreatorPayoutBatchItem).filter(
            CreatorPayoutBatchItem.payment_transaction_id == t1.id
        ).first()
        assert item is not None
        assert item.payout_batch_id == batch.id
        # Batch snapshot fields unchanged.
        db.refresh(batch)
        assert batch.status == CreatorPayoutBatchStatus.cancelled
        assert batch.total_amount_cents == 9000
        assert batch.transaction_count == 1

    def test_re_payment_in_second_batch_creates_new_item(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        first = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="ORIG-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        batch_a = db.get(CreatorPayoutBatch, first.batch_id)
        _pbo.cancel_payout_batch(
            db, batch=batch_a, cancelled_by=creator,
            cancellation_reason="admin error", revert_transactions=True,
        )
        # Now re-pay.
        second = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="REDO-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        items = db.query(CreatorPayoutBatchItem).filter(
            CreatorPayoutBatchItem.payment_transaction_id == t1.id
        ).order_by(CreatorPayoutBatchItem.created_at).all()
        assert len(items) == 2
        batch_ids = [item.payout_batch_id for item in items]
        assert first.batch_id in batch_ids
        assert second.batch_id in batch_ids

    def test_post_payout_refund_does_not_mutate_item_snapshot(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="SNAPSHOT-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        item = db.query(CreatorPayoutBatchItem).filter(
            CreatorPayoutBatchItem.payment_transaction_id == t1.id
        ).first()
        item_before = (item.creator_amount_cents_at_payout,
                       item.refunded_creator_amount_cents_at_payout)
        # Simulate a post-payout refund landing.
        t1.refunded_amount_cents = 3000
        t1.refunded_platform_fee_cents = 300
        t1.refunded_creator_amount_cents = 2700
        t1.status = PaymentTransactionStatus.partially_refunded
        db.commit()
        db.refresh(item)
        item_after = (item.creator_amount_cents_at_payout,
                      item.refunded_creator_amount_cents_at_payout)
        # BatchItem snapshot fields unchanged despite the refund.
        assert item_before == item_after


class TestCancellation:
    def test_cancel_without_revert_leaves_transactions_paid(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        t1 = _make_txn(db, creator=creator, space=space)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="NOREVERT-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        batch = db.get(CreatorPayoutBatch, outcome.batch_id)
        _pbo.cancel_payout_batch(
            db, batch=batch, cancelled_by=creator,
            cancellation_reason="record correction only",
            revert_transactions=False,
        )
        db.refresh(t1)
        assert t1.payout_status == PayoutStatus.paid
        assert t1.payout_batch_id == batch.id

    def test_repeat_cancel_is_idempotent(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_txn(db, creator=creator, space=space)
        outcome = _pbo.create_payout_batch(
            db, creator=creator, currency="AUD",
            reference="IDEM-01", paid_at=datetime.utcnow(),
            submitted_total_cents=9000, note=None, created_by=creator,
        )
        batch = db.get(CreatorPayoutBatch, outcome.batch_id)
        _pbo.cancel_payout_batch(
            db, batch=batch, cancelled_by=creator,
            cancellation_reason="first", revert_transactions=False,
        )
        r2 = _pbo.cancel_payout_batch(
            db, batch=batch, cancelled_by=creator,
            cancellation_reason="second", revert_transactions=False,
        )
        assert r2.already_cancelled is True
        assert r2.reverted_transaction_ids == []
