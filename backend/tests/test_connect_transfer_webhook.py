"""Where the webhook hands a Connect purchase over to the transfer path.

Tested at ``_attempt_connect_transfer`` and the two async handlers rather
than by rebuilding the whole fulfilment fixture, because what this commit
added to the webhook is exactly those functions and the ordering around them.
The unchanged fulfilment behaviour is covered by the existing suite.

The properties that matter:

* **fulfilment first, transfer second** — a transfer that explodes cannot
  touch the member's purchase or access;
* **not before the money is in** — Checkout completing is not the payment
  succeeding for a delayed-notification method;
* **never guess a fee** — an unknown processing fee means no transfer, not an
  estimated one.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import stripe

from app.models.payment import (
    ConnectTransferStatus,
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.webhooks.routes import (
    _attempt_connect_transfer,
    _handle_async_payment_failed,
    _handle_async_payment_succeeded,
)

ACCT = "acct_1ConnectReady"
SESSION = "cs_test_session"
TRANSFER_TARGET = "app.services.connect_transfers.get_stripe"


class _FakeStripe:
    def __init__(self, *, result=None, error=None):
        self.calls: list[dict] = []
        outer = self

        class _Transfer:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if error is not None:
                    raise error
                return result or {"id": f"tr_{uuid.uuid4().hex[:16]}"}

        self.Transfer = _Transfer


def _txn(db, **overrides) -> PaymentTransaction:
    """A Connect-routed, paid, fulfilled row awaiting its transfer."""
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "fulfilment_status": PaymentFulfilmentStatus.applied,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "processing_fee_cents": 200,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": ACCT,
        "connect_transfer_status": ConnectTransferStatus.awaiting_payment.value,
        "provider_charge_id": "ch_test",
        "provider_checkout_session_id": SESSION,
        "provider_payment_intent_id": "pi_test",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


class TestSuccessfulPayment:
    def test_awaiting_payment_to_pending_to_sent(self, db):
        """The full transition, in one webhook delivery."""
        txn = _txn(db)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

        fake = _FakeStripe(result={"id": "tr_done"})
        with patch(TRANSFER_TARGET, return_value=fake):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )

        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.provider_transfer_id == "tr_done"
        assert txn.transfer_amount_cents == 9000
        assert len(fake.calls) == 1

    def test_a_manual_row_is_left_alone(self, db):
        txn = _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        fake = _FakeStripe()
        with patch(TRANSFER_TARGET, return_value=fake):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.not_applicable.value


# ---------------------------------------------------------------------------
# Not before the money is in
# ---------------------------------------------------------------------------


class TestPaymentIntentGate:
    @pytest.mark.parametrize("pi_status", [
        "processing", "requires_payment_method", "requires_action", None,
    ])
    def test_an_unsucceeded_payment_sends_nothing(self, db, pi_status):
        """Checkout completing is not the payment succeeding. FC must not send
        its own money ahead of the customer's."""
        txn = _txn(db)
        fake = _FakeStripe()
        with patch(TRANSFER_TARGET, return_value=fake):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status=pi_status, source="checkout.session.completed",
            )
        assert fake.calls == []
        db.refresh(txn)
        # Still applicable, still not due.
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    def test_the_async_success_event_then_sends_it(self, db):
        """The delayed money lands and the transfer follows."""
        txn = _txn(db)
        with patch(TRANSFER_TARGET, return_value=_FakeStripe()):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="processing",
                source="checkout.session.completed",
            )
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

        class _Bt:
            fee = 200

        class _Charge:
            id = "ch_async"
            balance_transaction = _Bt()

        class _Pi:
            status = "succeeded"
            latest_charge = _Charge()

        fake = _FakeStripe(result={"id": "tr_async"})
        with patch("stripe.PaymentIntent.retrieve", return_value=_Pi()), \
             patch(TRANSFER_TARGET, return_value=fake):
            _handle_async_payment_succeeded(
                {"id": SESSION, "payment_intent": "pi_test", "metadata": {}}, db,
            )

        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.provider_transfer_id == "tr_async"

    def test_the_async_failure_event_never_transfers(self, db):
        txn = _txn(db)
        fake = _FakeStripe()
        with patch(TRANSFER_TARGET, return_value=fake):
            _handle_async_payment_failed({"id": SESSION}, db)
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    def test_the_async_handler_ignores_a_manual_row(self, db):
        _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        fake = _FakeStripe()
        with patch("stripe.PaymentIntent.retrieve") as pi, \
             patch(TRANSFER_TARGET, return_value=fake):
            _handle_async_payment_succeeded(
                {"id": SESSION, "payment_intent": "pi_test", "metadata": {}}, db,
            )
        assert pi.call_count == 0
        assert fake.calls == []


# ---------------------------------------------------------------------------
# Never guess a fee
# ---------------------------------------------------------------------------


class TestUnknownFee:
    def test_an_unknown_fee_sends_nothing_but_records_the_debt(self, db):
        """No estimate and no partial transfer — but the row becomes ``pending``.

        Owed and computable are separate questions. The payment succeeded, so a
        transfer is owed; only ``pending`` rows are visible to the sweeper,
        which resolves the fee from the PaymentIntent before sending anything.
        Leaving it ``awaiting_payment`` stranded a paid purchase.
        """
        txn = _txn(db, processing_fee_cents=None)
        fake = _FakeStripe()
        with patch(TRANSFER_TARGET, return_value=fake):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
        assert txn.processing_fee_cents is None
        assert txn.transfer_amount_cents is None
        assert txn.provider_transfer_id is None

    def test_a_fee_less_row_is_picked_up_by_the_sweeper(self, db):
        """The other half: the row the webhook could not price is resolved and
        sent by the sweeper, rather than sitting unseen."""
        from app.services import connect_transfer_sweeper as sweeper

        txn = _txn(db, processing_fee_cents=None)
        with patch(TRANSFER_TARGET, return_value=_FakeStripe()):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )

        class _Bt:
            fee = 210

        class _Charge:
            id = "ch_test"
            balance_transaction = _Bt()

        class _Pi:
            status = "succeeded"
            latest_charge = _Charge()

        fake = _FakeStripe(result={"id": "tr_swept"})
        fake.PaymentIntent = type(
            "PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())},
        )
        with patch(
            "app.services.connect_transfer_sweeper.get_stripe", return_value=fake,
        ), patch(TRANSFER_TARGET, return_value=fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.fee_resolved == 1
        assert report.sent == 1
        db.refresh(txn)
        assert txn.processing_fee_cents == 210
        assert txn.transfer_amount_cents == 9200 - 210
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value


# ---------------------------------------------------------------------------
# Fulfilment is never at risk
# ---------------------------------------------------------------------------


class TestFulfilmentSurvives:
    def test_a_retryable_transfer_failure_leaves_the_purchase_intact(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        with patch(TRANSFER_TARGET, return_value=_FakeStripe(error=err)):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )

        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
        assert txn.transfer_attempt_count == 1

    def test_a_terminal_transfer_failure_leaves_the_purchase_intact(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "No such destination", param="destination", code="account_invalid",
        )
        with patch(TRANSFER_TARGET, return_value=_FakeStripe(error=err)):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )

        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert txn.connect_transfer_status == ConnectTransferStatus.failed.value

    def test_an_unexpected_explosion_does_not_propagate(self, db):
        """Nothing here may turn into a 5xx: fulfilment has committed, and
        Stripe re-delivering would find nothing left to do."""
        txn = _txn(db)
        with patch(
            "app.services.connect_transfers.execute_transfer",
            side_effect=RuntimeError("boom"),
        ):
            _attempt_connect_transfer(   # must not raise
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )
        db.refresh(txn)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied

    def test_a_missing_transaction_is_harmless(self, db):
        _attempt_connect_transfer(
            db, payment_transaction_id="txn_nope",
            payment_intent_status="succeeded", source="test",
        )


# ---------------------------------------------------------------------------
# One transfer per purchase
# ---------------------------------------------------------------------------


class TestDuplicateDelivery:
    def test_a_redelivered_webhook_sends_one_transfer(self, db):
        txn = _txn(db)
        fake = _FakeStripe(result={"id": "tr_once"})
        with patch(TRANSFER_TARGET, return_value=fake):
            for _ in range(3):
                _attempt_connect_transfer(
                    db, payment_transaction_id=txn.id,
                    payment_intent_status="succeeded", source="test",
                )
        assert len(fake.calls) == 1
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_once"
        assert txn.transfer_attempt_count == 1

    def test_a_webhook_after_the_sweeper_sends_nothing_more(self, db):
        """Webhook against sweeper: whichever arrives second finds the transfer
        already recorded."""
        from app.services import connect_transfer_sweeper as sweeper

        txn = _txn(db, connect_transfer_status=ConnectTransferStatus.pending.value)
        fake = _FakeStripe(result={"id": "tr_swept"})
        with patch(TRANSFER_TARGET, return_value=fake):
            sweeper.sweep_pending_transfers(db)
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )
        assert len(fake.calls) == 1
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_swept"

    def test_a_sweeper_after_the_webhook_sends_nothing_more(self, db):
        from app.services import connect_transfer_sweeper as sweeper

        txn = _txn(db)
        fake = _FakeStripe(result={"id": "tr_hook"})
        with patch(TRANSFER_TARGET, return_value=fake):
            _attempt_connect_transfer(
                db, payment_transaction_id=txn.id,
                payment_intent_status="succeeded", source="test",
            )
            report = sweeper.sweep_pending_transfers(db)
        assert len(fake.calls) == 1
        assert report.considered == 0
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_hook"


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


def test_the_async_events_are_dispatched():
    """Both are new in this commit; if the branches were dropped a delayed
    payment would silently never transfer."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app/webhooks/routes.py"
    ).read_text()
    for event in (
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
    ):
        assert f'elif event_type == "{event}"' in source, event


def test_the_transfer_runs_after_fulfilment_commits():
    """Ordering is structural, not a convention. The call sits after the
    fulfilment try/except, so it cannot be inside the block that rolls back."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app/webhooks/routes.py"
    ).read_text()
    handler_start = source.index("def _handle_checkout_completed(")
    handler_end = source.index("def _attempt_connect_transfer(")
    body = source[handler_start:handler_end]

    rollback_at = body.rindex("db.rollback()")
    transfer_at = body.index("_attempt_connect_transfer(")
    assert transfer_at > rollback_at, (
        "the transfer attempt must come after the fulfilment rollback handler"
    )
