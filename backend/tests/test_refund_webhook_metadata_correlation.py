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


# ---------------------------------------------------------------------------
# Correction 4 — an empty embedded refund list
# ---------------------------------------------------------------------------
#
# Production evidence: refop_9e29c6aa38484d06b7c6ddee sat at ``accepted``
# forever. The ledger had updated, the Connect transfer had reversed and the
# member had been emailed — but ``charge.refunds.data`` arrived empty, the
# correlator returned on it before looking at anything else, and the op was
# never confirmed. Reading the Refund directly showed status ``succeeded``
# with both metadata keys intact.

RETRIEVE_TARGET = "stripe.Refund.retrieve"


class _StripeRefund:
    """What ``stripe.Refund.retrieve`` hands back — an object, not a dict."""

    def __init__(self, *, refund_id, op_id, txn_id, status="succeeded"):
        self.id = refund_id
        self.status = status
        self.metadata = {
            "refund_operation_id": op_id,
            "payment_transaction_id": txn_id,
        }


def _empty_charge(txn):
    """The payload that caused the bug: refunded, with no embedded data."""
    return {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": True,
        "refunds": {"data": [], "has_more": False},
    }


def _correlate(db, txn, charge, event_id=None):
    """``confirming_webhook_event_id`` is an FK to ``webhook_events``, so
    these tests pass ``None`` like the ones above rather than inventing
    an id the database would reject."""
    return correlate_refund_operations(
        db, txn=txn, charge=charge,
        event_created=None, webhook_event_row_id=event_id,
    )


def test_empty_refund_list_confirms_via_verified_retrieve(db):
    """The reported bug."""
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    retrieved = _StripeRefund(refund_id=refund_id, op_id=op.id, txn_id=txn.id)
    with patch(RETRIEVE_TARGET, return_value=retrieved):
        transitioned = _correlate(db, txn, _empty_charge(txn))

    assert transitioned == [op.id]
    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.webhook_confirmed.value
    assert op.confirmed_at is not None


@pytest.mark.parametrize("field,value", [
    ("id", "re_a_completely_different_refund"),
    ("status", "pending"),
])
def test_a_retrieved_refund_that_disagrees_does_not_transition(db, field, value):
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    retrieved = _StripeRefund(refund_id=refund_id, op_id=op.id, txn_id=txn.id)
    setattr(retrieved, field, value)
    with patch(RETRIEVE_TARGET, return_value=retrieved):
        assert _correlate(db, txn, _empty_charge(txn)) == []

    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value


@pytest.mark.parametrize("key", [
    "refund_operation_id",
    "payment_transaction_id",
])
def test_mismatched_metadata_does_not_transition(db, key):
    """Both keys are checked. A Refund that belongs to a different
    operation or a different transaction proves nothing about this one."""
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    retrieved = _StripeRefund(refund_id=refund_id, op_id=op.id, txn_id=txn.id)
    retrieved.metadata[key] = "belongs_to_something_else"
    with patch(RETRIEVE_TARGET, return_value=retrieved):
        assert _correlate(db, txn, _empty_charge(txn)) == []

    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value


def test_absent_metadata_does_not_transition(db):
    """Being the only accepted op is not evidence. The ledger stays
    webhook-authoritative."""
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    retrieved = _StripeRefund(refund_id=refund_id, op_id=op.id, txn_id=txn.id)
    retrieved.metadata = {}
    with patch(RETRIEVE_TARGET, return_value=retrieved):
        assert _correlate(db, txn, _empty_charge(txn)) == []

    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value


def test_a_failed_retrieve_leaves_the_op_accepted_and_does_not_raise(db):
    """The customer's refund is already written by the caller. Nothing
    about it may depend on Stripe answering this second call."""
    from unittest.mock import patch

    import stripe as stripe_sdk

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    error = stripe_sdk.APIConnectionError("Stripe is unreachable")
    with patch(RETRIEVE_TARGET, side_effect=error):
        transitioned = _correlate(db, txn, _empty_charge(txn))

    assert transitioned == []
    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.accepted.value, (
        "left exactly where the reconciliation path expects to find it"
    )


def test_an_op_with_no_stripe_refund_id_is_never_retrieved(db):
    """Nothing to verify against, so nothing is asked of Stripe."""
    from unittest.mock import patch

    txn = _make_txn(db)
    _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=None,
    )
    db.commit()

    with patch(RETRIEVE_TARGET) as retrieve:
        assert _correlate(db, txn, _empty_charge(txn)) == []

    assert retrieve.call_count == 0


def test_a_dashboard_refund_with_no_ops_makes_no_stripe_call(db):
    """The common case must not gain a network round trip."""
    from unittest.mock import patch

    txn = _make_txn(db)
    db.commit()

    with patch(RETRIEVE_TARGET) as retrieve:
        assert _correlate(db, txn, _empty_charge(txn)) == []

    assert retrieve.call_count == 0


def test_the_embedded_fast_path_makes_no_stripe_call(db):
    """Unchanged: when the payload carries the refund, that is enough."""
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    charge = {
        "id": txn.provider_charge_id,
        "amount_refunded": 3000,
        "refunded": True,
        "refunds": {"data": [{
            "id": refund_id,
            "amount": 3000,
            "metadata": {"refund_operation_id": op.id},
        }], "has_more": False},
    }

    with patch(RETRIEVE_TARGET) as retrieve:
        assert _correlate(db, txn, charge) == [op.id]

    assert retrieve.call_count == 0, "the fast path must stay a fast path"
    db.refresh(op)
    assert op.terminal_status == RefundOperationTerminalStatus.webhook_confirmed.value


def test_replay_of_an_empty_payload_is_idempotent(db):
    """A redelivered event must neither re-transition nor re-query."""
    from unittest.mock import patch

    txn = _make_txn(db)
    refund_id = f"re_{uuid.uuid4().hex[:16]}"
    op = _make_op(
        db, txn,
        terminal_status=RefundOperationTerminalStatus.accepted.value,
        stripe_refund_id=refund_id,
    )
    db.commit()

    retrieved = _StripeRefund(refund_id=refund_id, op_id=op.id, txn_id=txn.id)
    with patch(RETRIEVE_TARGET, return_value=retrieved):
        first = _correlate(db, txn, _empty_charge(txn))
    db.refresh(op)
    confirmed_at = op.confirmed_at

    with patch(RETRIEVE_TARGET, return_value=retrieved) as retrieve:
        second = _correlate(db, txn, _empty_charge(txn))

    assert first == [op.id]
    assert second == []
    assert retrieve.call_count == 0, (
        "a confirmed op is not a candidate, so the replay costs no API call"
    )
    db.refresh(op)
    assert op.confirmed_at == confirmed_at
