"""Metadata-first refund webhook correlator (Correction 1 + Correction 3).

Covers:

* transition an in_flight op via ``metadata.refund_operation_id`` when
  the webhook arrives before the API path has persisted ``accepted``;
* transition an accepted op via metadata OR fallback stripe_refund_id
  matching;
* correlator does NOT overwrite terminal-fail state;
* correlator does NOT overwrite a mismatched stripe_refund_id;
* correlator does NOT falsely conclude an accepted op is unrelated
  when the embedded refunds.data[] page is truncated;
* Dashboard-originated refunds with no matching op are safely ignored.
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
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationReason,
    RefundOperationTerminalStatus,
    StripeIdentifierKind,
)
from app.services.refund_webhook_correlator import correlate_refund_operations


def _make_txn(db):
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        currency="AUD",
        gross_amount_cents=10000,
        platform_fee_basis_points=1000,
        platform_fee_cents=1000,
        net_creator_amount_cents=9000,
        net_platform_amount_cents=1000,
        provider_charge_id=f"ch_{uuid.uuid4().hex[:12]}",
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(txn)
    db.flush()
    return txn


def _make_op(
    db, txn, *,
    terminal_status=RefundOperationTerminalStatus.in_flight.value,
    stripe_refund_id=None,
    amount=3000,
):
    op_id = f"refop_{uuid.uuid4().hex[:12]}"
    op = RefundOperation(
        id=op_id,
        payment_transaction_id=txn.id,
        requested_by_user_id=None,
        requested_at=datetime.utcnow(),
        reason=RefundOperationReason.member_request.value,
        note=None,
        requested_amount_cents=amount,
        expected_cumulative_refunded_amount_cents=amount,
        stripe_identifier_kind=StripeIdentifierKind.charge.value,
        stripe_identifier_value=txn.provider_charge_id,
        stripe_refund_id=stripe_refund_id,
        terminal_status=terminal_status,
    )
    db.add(op)
    db.flush()
    return op


def _charge_with_refunds(*, refund_dicts):
    return {
        "id": f"ch_{uuid.uuid4().hex[:12]}",
        "amount_refunded": sum(r.get("amount", 0) for r in refund_dicts),
        "refunded": False,
        "refunds": {"data": refund_dicts, "has_more": False},
    }


def test_metadata_correlation_transitions_in_flight_op(db):
    txn = _make_txn(db)
    op = _make_op(db, txn)
    db.commit()

    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": False,
        "refunds": {
            "data": [{
                "id": "re_stripe_1",
                "amount": 3000,
                "metadata": {"refund_operation_id": op.id},
            }],
            "has_more": False,
        },
    }
    transitioned = correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    assert op.id in transitioned
    assert op.terminal_status == RefundOperationTerminalStatus.webhook_confirmed.value
    assert op.stripe_refund_id == "re_stripe_1"
    assert op.confirmed_at is not None


def test_metadata_correlation_transitions_accepted_op(db):
    txn = _make_txn(db)
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id="re_pre_set",
    )
    db.commit()

    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": False,
        "refunds": {
            "data": [{
                "id": "re_pre_set",
                "amount": 3000,
                "metadata": {"refund_operation_id": op.id},
            }],
            "has_more": False,
        },
    }
    correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.webhook_confirmed.value


def test_correlator_does_not_overwrite_terminal_fail_op(db):
    txn = _make_txn(db)
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.refused.value,
        stripe_refund_id=None,
    )
    db.commit()

    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": False,
        "refunds": {
            "data": [{
                "id": "re_stray",
                "amount": 3000,
                "metadata": {"refund_operation_id": op.id},
            }],
            "has_more": False,
        },
    }
    correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    # Refused stays refused — correlator refuses to overwrite.
    assert op.terminal_status == RefundOperationTerminalStatus.refused.value
    assert op.stripe_refund_id is None


def test_correlator_does_not_overwrite_stripe_refund_id_mismatch(db):
    txn = _make_txn(db)
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id="re_A",
    )
    db.commit()

    # Webhook carries a different id but same refund_operation_id
    # metadata — real corruption scenario.
    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": False,
        "refunds": {
            "data": [{
                "id": "re_B",
                "amount": 3000,
                "metadata": {"refund_operation_id": op.id},
            }],
            "has_more": False,
        },
    }
    correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    # No transition, stripe_refund_id unchanged.
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value
    assert op.stripe_refund_id == "re_A"


def test_dashboard_refund_with_no_metadata_is_safely_ignored(db):
    txn = _make_txn(db)
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.in_flight.value,
    )
    db.commit()

    # Dashboard refund — no metadata, unfamiliar id.
    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 2000,
        "refunded": False,
        "refunds": {
            "data": [{"id": "re_dash_1", "amount": 2000, "metadata": {}}],
            "has_more": False,
        },
    }
    transitioned = correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    # No transition — Dashboard refund not correlated to our op.
    assert transitioned == []
    assert op.terminal_status == RefundOperationTerminalStatus.in_flight.value


def test_truncated_refunds_data_leaves_accepted_op_unchanged(db):
    """Regression for Correction 3 — absence of our stripe_refund_id
    in the embedded refunds.data[] with has_more=True must NOT be
    treated as proof of non-match. Op stays ``accepted`` for a
    subsequent webhook or reconciliation to heal.
    """
    txn = _make_txn(db)
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id="re_ours",
    )
    db.commit()

    # Charge has been refunded many times; our refund is not in the
    # first page. has_more=True.
    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 50000,
        "refunded": False,
        "refunds": {
            "data": [
                {"id": "re_other_1", "amount": 1000, "metadata": {}},
                {"id": "re_other_2", "amount": 1000, "metadata": {}},
            ],
            "has_more": True,
        },
    }
    transitioned = correlate_refund_operations(
        db, txn=txn, charge=charge, event_created=None, webhook_event_row_id=None,
    )
    db.commit()
    db.refresh(op)
    # Nothing transitioned — but our op is NOT falsely marked failed.
    assert op.id not in transitioned
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value
    assert op.stripe_refund_id == "re_ours"
