"""The refund gate for Connect rows, and the order refunds happen in.

The guarantee worth protecting: the customer's refund is not contingent on FC's
ability to recover from the creator. Refunding the platform charge and clawing
the transfer back are two steps, the second is downstream reconciliation, and a
failure there leaves the refund standing and the shortfall recorded.

The gate tests exist because ``payout_status`` cannot answer the question the
gate asks. A Connect row's ``payout_status`` is ``not_applicable`` — FC's
manual payout process does not cover it — so a gate reading that field would
refuse every Connect refund. It reads ``connect_transfer_status`` instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import stripe

from types import SimpleNamespace

from app.creator.refund_routes import _payout_gate_action
from app.models.refund_operation import RefundOperation
from app.models.payment import (
    ConnectRecoveryState,
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.webhooks.refund_handlers import handle_charge_refunded

ACCT = "acct_1ConnectReady"
TRANSFER = "tr_sent"
CHARGE = "ch_refund_test"
REVERSAL_TARGET = "app.services.connect_reversals.get_stripe"


class _FakeStripe:
    def __init__(self, *, error=None):
        self.reversals: list[dict] = []
        outer = self

        class _Transfer:
            @staticmethod
            def create_reversal(transfer_id, **kwargs):
                outer.reversals.append({"transfer": transfer_id, **kwargs})
                if error is not None:
                    raise error
                return {"id": "trr_1"}

            @staticmethod
            def retrieve(transfer_id, **kwargs):
                return {}

        self.Transfer = _Transfer


def _connect_txn(db, **overrides) -> PaymentTransaction:
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "processing_fee_cents": 200,
        "payout_status": PayoutStatus.not_applicable,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": ACCT,
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "transfer_amount_cents": 9000,
        "provider_transfer_id": TRANSFER,
        "provider_charge_id": CHARGE,
        "provider_payment_intent_id": "pi_refund_test",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


def _manual_txn(db, **overrides) -> PaymentTransaction:
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.manual.value,
        "provider_charge_id": f"ch_{uuid.uuid4().hex[:12]}",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


def _charge(*, amount_refunded: int, refunded: bool, charge_id: str = CHARGE) -> dict:
    return {
        "id": charge_id,
        "amount_refunded": amount_refunded,
        "refunded": refunded,
        "payment_intent": "pi_refund_test",
    }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestConnectGate:
    @pytest.mark.parametrize("status", [
        ConnectTransferStatus.awaiting_payment.value,
        ConnectTransferStatus.pending.value,
        ConnectTransferStatus.failed.value,
        ConnectTransferStatus.reversed.value,
    ])
    @pytest.mark.parametrize("is_admin", [True, False])
    def test_no_creator_funds_outstanding_means_anyone_may_refund(
        self, db, status, is_admin,
    ):
        """Nothing has been sent, or it has all come back. A refund just
        cancels the obligation."""
        txn = _connect_txn(
            db, connect_transfer_status=status,
            reversed_transfer_amount_cents=(
                9000 if status == ConnectTransferStatus.reversed.value else 0
            ),
        )
        allowed, advisory = _payout_gate_action(txn=txn, actor_is_admin=is_admin)
        assert allowed is True
        assert advisory is None

    @pytest.mark.parametrize("status", [
        ConnectTransferStatus.sent.value,
        ConnectTransferStatus.partially_reversed.value,
    ])
    @pytest.mark.parametrize("is_admin", [True, False])
    def test_sent_funds_are_refundable_by_creator_and_admin_alike(
        self, db, status, is_admin,
    ):
        """Policy change, deliberate: this was admin-only at launch.

        A creator has to be able to refund their own sale without waiting
        on Fresh Collective, and the risk that made the restriction look
        prudent is handled downstream instead of by refusing — the
        customer refund commits first and any shortfall is recorded as
        ``connect_recovery_state = required`` with the exact amount.
        """
        txn = _connect_txn(
            db, connect_transfer_status=status,
            reversed_transfer_amount_cents=(
                4500 if status == ConnectTransferStatus.partially_reversed.value else 0
            ),
        )
        allowed, advisory = _payout_gate_action(txn=txn, actor_is_admin=is_admin)
        assert allowed is True
        assert advisory == "post_payout_manual_recovery_required", (
            "the advisory describes the transaction's state, not who pressed "
            "the button — operations need it either way"
        )

    def test_an_unknown_transfer_status_still_refuses(self):
        """Refuse rather than guess about money.

        Unpersisted on purpose: ``ck_payment_transactions_connect_transfer_
        status`` already makes an unknown value unstorable, so this covers
        the branch without pretending the database would allow the row.
        The gate reads two attributes and nothing else.
        """
        from types import SimpleNamespace

        txn = SimpleNamespace(
            payout_model="connect",
            connect_transfer_status="some_future_state",
        )
        assert _payout_gate_action(txn=txn, actor_is_admin=True) == (False, None)
        assert _payout_gate_action(txn=txn, actor_is_admin=False) == (False, None)

    def test_not_applicable_payout_status_does_not_block_a_connect_refund(self, db):
        """The bug this gate rewrite exists to prevent: the old gate refused
        ``not_applicable`` outright, which is every Connect row."""
        txn = _connect_txn(
            db, connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        assert txn.payout_status == PayoutStatus.not_applicable
        allowed, _ = _payout_gate_action(txn=txn, actor_is_admin=False)
        assert allowed is True


class TestManualGateUnchanged:
    def test_pending_allows_a_creator(self, db):
        txn = _manual_txn(db, payout_status=PayoutStatus.pending)
        assert _payout_gate_action(txn=txn, actor_is_admin=False) == (True, None)

    def test_paid_is_admin_only_with_the_existing_advisory(self, db):
        txn = _manual_txn(db, payout_status=PayoutStatus.paid)
        assert _payout_gate_action(txn=txn, actor_is_admin=False) == (False, None)
        assert _payout_gate_action(txn=txn, actor_is_admin=True) == (
            True, "post_payout_manual_recovery_required",
        )

    def test_held_is_admin_only_with_the_existing_advisory(self, db):
        txn = _manual_txn(db, payout_status=PayoutStatus.held)
        assert _payout_gate_action(txn=txn, actor_is_admin=False) == (False, None)
        assert _payout_gate_action(txn=txn, actor_is_admin=True) == (
            True, "post_hold_manual_review_required",
        )

    def test_cancelled_is_treated_as_pending(self, db):
        txn = _manual_txn(db, payout_status=PayoutStatus.cancelled)
        assert _payout_gate_action(txn=txn, actor_is_admin=False) == (True, None)

    def test_not_applicable_still_refuses_on_a_manual_row(self, db):
        """Unchanged: a manual row that never owed a creator anything is not a
        refundable member payment."""
        txn = _manual_txn(db, payout_status=PayoutStatus.not_applicable)
        assert _payout_gate_action(txn=txn, actor_is_admin=True) == (False, None)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class TestRefundThenReversal:
    def test_a_full_refund_refunds_the_customer_and_reverses_the_creator(self, db):
        txn = _connect_txn(db)
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            handle_charge_refunded(
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=int(datetime(2026, 9, 29, 12).timestamp()),
                event_livemode=False,
            )

        db.refresh(txn)
        # Customer side, by the existing machinery.
        assert txn.refunded_amount_cents == 10000
        assert txn.refunded_platform_fee_cents == 800
        assert txn.refunded_creator_amount_cents == 9200
        assert txn.status == PaymentTransactionStatus.refunded
        # Creator side.
        assert fake.reversals[0]["amount"] == 9000
        assert txn.reversed_transfer_amount_cents == 9000
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value

    def test_a_partial_refund_reverses_proportionally(self, db):
        txn = _connect_txn(db)
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            handle_charge_refunded(
                _charge(amount_refunded=5000, refunded=False), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        db.refresh(txn)
        assert txn.refunded_creator_amount_cents == 4600
        assert fake.reversals[0]["amount"] == 4500
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.partially_reversed.value

    def test_a_second_partial_refund_reverses_only_the_delta(self, db):
        txn = _connect_txn(db)
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            handle_charge_refunded(
                _charge(amount_refunded=5000, refunded=False), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
            handle_charge_refunded(
                _charge(amount_refunded=7500, refunded=False), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        assert [r["amount"] for r in fake.reversals] == [4500, 2250]
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 6750

    def test_a_redelivered_refund_event_reverses_nothing_extra(self, db):
        """Two guards agree: the webhook lease dedupes the event, and the
        cumulative target makes a second attempt a zero delta anyway."""
        txn = _connect_txn(db)
        event_id = f"evt_{uuid.uuid4().hex}"
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            for _ in range(3):
                handle_charge_refunded(
                    _charge(amount_refunded=10000, refunded=True), db,
                    provider_event_id=event_id,
                    event_created=None, event_livemode=False,
                )
        assert len(fake.reversals) == 1
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_distinct_events_with_the_same_total_do_not_over_reverse(self, db):
        """Stripe can deliver a fresh event id for the same cumulative total.
        The delta is zero, so nothing more is reversed."""
        txn = _connect_txn(db)
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            for _ in range(2):
                handle_charge_refunded(
                    _charge(amount_refunded=10000, refunded=True), db,
                    provider_event_id=f"evt_{uuid.uuid4().hex}",
                    event_created=None, event_livemode=False,
                )
        assert len(fake.reversals) == 1
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000


class TestCustomerRefundIsNeverContingent:
    def test_an_insufficient_creator_balance_leaves_the_refund_standing(self, db):
        """The point of the whole ordering."""
        txn = _connect_txn(db)
        err = stripe.InvalidRequestError(
            "Insufficient funds", param=None, code="balance_insufficient",
        )
        with patch(REVERSAL_TARGET, return_value=_FakeStripe(error=err)):
            handle_charge_refunded(
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )

        db.refresh(txn)
        # Customer refund intact.
        assert txn.refunded_amount_cents == 10000
        assert txn.status == PaymentTransactionStatus.refunded
        # Shortfall recorded, not assumed recovered.
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000
        assert txn.reversed_transfer_amount_cents == 0

    def test_a_retryable_reversal_failure_leaves_the_refund_standing(self, db):
        txn = _connect_txn(db)
        with patch(
            REVERSAL_TARGET,
            return_value=_FakeStripe(error=stripe.APIConnectionError("no route")),
        ):
            handle_charge_refunded(
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        db.refresh(txn)
        assert txn.refunded_amount_cents == 10000
        assert txn.reversed_transfer_amount_cents == 0

    def test_the_refund_is_already_committed_when_the_reversal_runs(self, db):
        """The ordering guarantee, asserted where it is observable.

        An unexpected explosion in the reversal path triggers a
        ``db.rollback()``, which in production cannot touch the refund —
        ``process_webhook_event`` committed it before the reversal was
        attempted. Under the test fixture's SAVEPOINT that rollback also
        discards the seeded row, so reading it back afterwards would prove
        nothing.

        So the assertion is made from inside the reversal instead: at the
        moment it is called, the refund must already be written. And the
        explosion must not propagate.
        """
        txn = _connect_txn(db)
        seen: list[int] = []

        def _explode(db_, *, payment_transaction_id, **kwargs):
            row = db_.query(PaymentTransaction).filter(
                PaymentTransaction.id == payment_transaction_id,
            ).one()
            seen.append(row.refunded_amount_cents)
            raise RuntimeError("boom")

        with patch(
            "app.services.connect_reversals.reverse_to_target",
            side_effect=_explode,
        ):
            handle_charge_refunded(   # must not raise
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )

        assert seen == [10000], (
            "the customer refund must already be recorded before the creator "
            "reversal is attempted"
        )

    def test_a_recovered_shortfall_converges_after_a_retry(self, db):
        """Manual/admin recovery and webhook reconciliation reach one state."""
        txn = _connect_txn(db)
        err = stripe.InvalidRequestError(
            "Insufficient funds", param=None, code="balance_insufficient",
        )
        with patch(REVERSAL_TARGET, return_value=_FakeStripe(error=err)):
            handle_charge_refunded(
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 9000

        # The creator's balance recovers and the reversal is retried.
        from app.services import connect_reversals as cr
        with patch(REVERSAL_TARGET, return_value=_FakeStripe()):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)

        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 0
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.refunded_amount_cents == 10000


class TestManualRowsUnaffected:
    def test_a_manual_refund_attempts_no_reversal(self, db):
        txn = _manual_txn(db)
        charge_id = txn.provider_charge_id
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            handle_charge_refunded(
                {
                    "id": charge_id, "amount_refunded": 10000,
                    "refunded": True, "payment_intent": None,
                },
                db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        assert fake.reversals == []
        db.refresh(txn)
        # The existing accounting, unchanged.
        assert txn.refunded_amount_cents == 10000
        assert txn.refunded_platform_fee_cents == 800
        assert txn.refunded_creator_amount_cents == 9200
        assert txn.payout_status == PayoutStatus.pending
        assert txn.connect_recovery_state == ConnectRecoveryState.none.value

    def test_a_connect_row_with_no_transfer_attempts_no_reversal(self, db):
        txn = _connect_txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        fake = _FakeStripe()
        with patch(REVERSAL_TARGET, return_value=fake):
            handle_charge_refunded(
                _charge(amount_refunded=10000, refunded=True), db,
                provider_event_id=f"evt_{uuid.uuid4().hex}",
                event_created=None, event_livemode=False,
            )
        assert fake.reversals == []
        db.refresh(txn)
        assert txn.refunded_amount_cents == 10000

# ---------------------------------------------------------------------------
# The HTTP boundary
# ---------------------------------------------------------------------------


class TestCreatorCanRefundASentTransferOverHttp:
    """One route-level test, for the one thing the gate unit tests cannot
    show: that a non-admin creator actually gets through
    ``POST /api/creator/payments/{id}/refund`` on a transfer that has
    already gone out.

    Deliberately not a second copy of the reversal and recovery tests
    above — those already cover what happens to the money. This covers
    only the boundary: authorisation, the payout gate, and the advisory
    that gets stamped on the way through.
    """

    def _client(self, db, creator):
        from fastapi.testclient import TestClient

        from app.auth.dependencies import get_creator_user
        from app.core.database import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_creator_user] = lambda: creator
        return TestClient(app)

    def _release(self):
        from app.auth.dependencies import get_creator_user
        from app.core.database import get_db
        from app.main import app

        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_creator_user, None)

    def test_a_non_admin_owner_may_refund_after_the_transfer_was_sent(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        assert creator.role != "admin", "the whole point of the test"
        space = make_space(creator=creator)
        txn = _connect_txn(
            db,
            space_id=space.id,
            creator_user_id=creator.id,
            connect_transfer_status=ConnectTransferStatus.sent.value,
        )
        assert txn.payout_status == PayoutStatus.not_applicable

        refund = SimpleNamespace(id="re_test_boundary")
        client = self._client(db, creator)
        try:
            with patch(
                "app.services.stripe_refund_orchestration.create_refund",
                return_value=refund,
            ) as submit:
                response = client.post(
                    f"/api/creator/payments/{txn.id}/refund",
                    json={"amount_cents": 10000, "reason": "member_request"},
                )
        finally:
            self._release()

        assert response.status_code not in (403, 404, 409), response.text
        assert response.status_code == 200, response.text
        assert submit.call_count == 1, "the refund must actually be submitted"

        op = (
            db.query(RefundOperation)
            .filter(RefundOperation.payment_transaction_id == txn.id)
            .one()
        )
        assert op.requested_by_user_id == creator.id
        assert op.payout_advisory == "post_payout_manual_recovery_required", (
            "operations need to know the refund happened after the transfer "
            "went out, whoever initiated it"
        )
