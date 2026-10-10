"""Sending a Connect-routed purchase's creator share.

The arithmetic and the state machine are checked directly; Stripe's
``Transfer.create`` is the only thing patched, because it is the one call
that would otherwise move money.

Two groups matter more than the rest. The **amount** tests pin the reason FC
chose separate charges and transfers — the creator is sent
``net_creator_amount_cents`` exactly, with Stripe's processing fee absorbed by
Fresh Collective rather than deducted, so the figure a creator was promised at
checkout is the figure that leaves.
The **race** tests use real concurrent database sessions rather than
sequential calls, because the property under test is that a row lock
serialises two workers, and sequential calls cannot demonstrate that.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import stripe
from sqlalchemy.orm import sessionmaker

from app.models.creator_stripe_account import CreatorStripeAccount, OnboardingState
from app.models.payment import (
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.services import connect_transfer_sweeper as sweeper
from app.services import connect_transfers as ct

ACCT = "acct_1ConnectReady"
CHARGE = "ch_testcharge"
TRANSFER_TARGET = "app.services.connect_transfers.get_stripe"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn(db, **overrides) -> PaymentTransaction:
    """A Connect-routed, paid, transfer-owed row unless overridden."""
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
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": ACCT,
        "connect_transfer_status": ConnectTransferStatus.pending.value,
        "provider_charge_id": CHARGE,
        "provider_payment_intent_id": "pi_test",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


class _FakeStripe:
    """Stands in for the SDK module, recording Transfer.create calls."""

    def __init__(self, *, result=None, error=None, results=None):
        self.calls: list[dict] = []
        self._result = result
        self._error = error
        self._results = list(results) if results else None

        outer = self

        class _Transfer:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if outer._results:
                    nxt = outer._results.pop(0)
                    if isinstance(nxt, Exception):
                        raise nxt
                    return nxt
                if outer._error is not None:
                    raise outer._error
                return outer._result or {"id": f"tr_{uuid.uuid4().hex[:16]}"}

        self.Transfer = _Transfer


def _patched(fake):
    return patch(TRANSFER_TARGET, return_value=fake)


# ---------------------------------------------------------------------------
# The amount
# ---------------------------------------------------------------------------


class TestAmount:
    """The creator receives gross minus Fresh Collective's commission.

    Stripe's processing fee is not subtracted — FC absorbs it. These
    expectations changed in October 2026 when that policy was adopted; the
    figures below are deliberately the same sales as before so the
    difference is legible in a diff.
    """

    def test_the_exact_eight_percent_example(self, db):
        """A$100 sale, 8% plan → A$92.00 to the creator.

        Stripe's A$2.00 is still recorded on the row, as FC's cost of sale.
        It used to come out of this figure, making it A$90.00.
        """
        txn = _txn(
            db, gross_amount_cents=10000, platform_fee_basis_points=800,
            platform_fee_cents=800, net_creator_amount_cents=9200,
            processing_fee_cents=200,
        )
        assert ct.compute_transfer_amount(txn) == 9200

    def test_a_founding_creator_on_zero_percent_receives_the_whole_sale(self, db):
        """0% commission means the full gross, not gross less Stripe's fee.

        This is the case that moved most: A$98.00 before, A$100.00 now. It
        also sits exactly on Stripe's ``source_transaction`` cap — a
        transfer may equal the source charge, which the documentation
        permits ("must not exceed").
        """
        txn = _txn(
            db, gross_amount_cents=10000, platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=10000,
            processing_fee_cents=200,
        )
        assert ct.compute_transfer_amount(txn) == 10000
        assert ct.compute_transfer_amount(txn) == txn.gross_amount_cents

    def test_a_discounted_purchase_uses_the_discounted_gross(self, db):
        """The ledger's gross is already what was charged, so the creator's
        share follows the money rather than the list price."""
        txn = _txn(
            db, gross_amount_cents=5000, platform_fee_basis_points=800,
            platform_fee_cents=400, net_creator_amount_cents=4600,
            processing_fee_cents=150,
        )
        assert ct.compute_transfer_amount(txn) == 4600

    def test_the_transfer_can_never_exceed_the_source_charge(self, db):
        """Stripe caps a ``source_transaction`` transfer at the charge
        amount. ``gross - platform_fee`` cannot exceed ``gross`` because a
        commission is never negative, so the cap is unreachable by
        construction — asserted across the whole fee range."""
        for bps in (0, 300, 400, 800, 10000):
            gross = 10000
            fee = round(gross * bps / 10000)
            txn = _txn(
                db, gross_amount_cents=gross, platform_fee_basis_points=bps,
                platform_fee_cents=fee,
                net_creator_amount_cents=gross - fee,
                processing_fee_cents=200,
            )
            if gross - fee <= 0:
                with pytest.raises(ct.TransferTerminal):
                    ct.compute_transfer_amount(txn)
            else:
                assert ct.compute_transfer_amount(txn) <= gross, bps

    def test_net_creator_amount_is_never_modified(self, db):
        """``net_creator_amount_cents`` is the payout-batch and refund
        anchor. The Connect figure is written to ``transfer_amount_cents``,
        which now equals it rather than being smaller."""
        txn = _txn(db)
        with _patched(_FakeStripe(result={"id": "tr_1"})):
            ct.execute_transfer(db, payment_transaction_id=txn.id)
        db.refresh(txn)
        assert txn.net_creator_amount_cents == 9200
        assert txn.processing_fee_cents == 200, "still recorded as FC's cost"
        assert txn.transfer_amount_cents == 9200

    def test_a_missing_fee_no_longer_prevents_a_transfer(self, db):
        """The amount does not depend on the fee, so an unreadable fee must
        not strand a payment. This used to raise ``TransferRetryable``."""
        txn = _txn(db, processing_fee_cents=None)
        assert ct.compute_transfer_amount(txn) == 9200

    def test_a_missing_creator_share_is_terminal(self, db):
        txn = _txn(db, net_creator_amount_cents=None)
        with pytest.raises(ct.TransferTerminal):
            ct.compute_transfer_amount(txn)

    @pytest.mark.parametrize("net_creator", [0, -1])
    def test_a_zero_or_negative_share_is_terminal(self, db, net_creator):
        """Nothing to send, and the row says why rather than looking sent.

        Reachable only through a fully-refunded or malformed row now that
        Stripe's fee is not subtracted — a 100% commission would also do it.
        """
        txn = _txn(db, net_creator_amount_cents=net_creator, processing_fee_cents=200)
        with pytest.raises(ct.TransferTerminal) as excinfo:
            ct.compute_transfer_amount(txn)
        assert "nothing to send" in str(excinfo.value)

    def test_a_fee_larger_than_the_commission_still_transfers(self, db):
        """The case the old formula refused outright: a A$2.00 sale whose
        processing fee exceeds the 8% commission. FC absorbs the
        difference, so the creator is still paid."""
        txn = _txn(
            db, gross_amount_cents=200, platform_fee_basis_points=800,
            platform_fee_cents=16, net_creator_amount_cents=184,
            processing_fee_cents=33,
        )
        assert ct.compute_transfer_amount(txn) == 184

    def test_a_zero_amount_row_is_marked_failed_not_sent(self, db):
        txn = _txn(db, net_creator_amount_cents=0, processing_fee_cents=200)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.status == ConnectTransferStatus.failed.value
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.failed.value
        assert txn.provider_transfer_id is None
        assert "nothing to send" in (txn.transfer_last_error or "")


# ---------------------------------------------------------------------------
# Becoming owed
# ---------------------------------------------------------------------------


class TestMarkOwed:
    def test_a_paid_connect_row_with_a_fee_becomes_pending(self, db):
        txn = _txn(db, connect_transfer_status=ConnectTransferStatus.awaiting_payment.value)
        assert ct.mark_transfer_owed(db, txn) is True
        db.commit()
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_an_unpaid_row_stays_awaiting_payment(self, db):
        txn = _txn(
            db,
            status=PaymentTransactionStatus.pending,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        assert ct.mark_transfer_owed(db, txn) is False
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    def test_an_unknown_fee_still_becomes_owed(self, db):
        """Owed and computable are different questions.

        The payment succeeded, so a transfer *is* owed — and only ``pending``
        rows are visible to the sweeper, which resolves the fee before sending.
        Leaving this ``awaiting_payment`` stranded a paid purchase that nothing
        would ever look at again.
        """
        txn = _txn(
            db, processing_fee_cents=None,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        assert ct.mark_transfer_owed(db, txn) is True
        db.commit()
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_a_pending_row_with_no_fee_is_still_sent(self, db):
        """There is no fee gate any more. The creator's share does not
        depend on Stripe's fee, so an unreadable fee must not hold up a
        payment — this used to send nothing and stay pending."""
        txn = _txn(
            db, processing_fee_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        fake = _FakeStripe(result={"id": "tr_nofee"})
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.sent is True
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_nofee"
        assert txn.transfer_amount_cents == 9200
        assert txn.processing_fee_cents is None, "still unknown, and that is fine"

    def test_a_manual_row_is_never_marked_owed(self, db):
        txn = _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        assert ct.mark_transfer_owed(db, txn) is False

    def test_an_already_owed_row_is_not_remarked(self, db):
        txn = _txn(db, connect_transfer_status=ConnectTransferStatus.pending.value)
        assert ct.mark_transfer_owed(db, txn) is False


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


class TestExecute:
    def test_a_successful_transfer_records_everything(self, db):
        txn = _txn(db)
        fake = _FakeStripe(result={"id": "tr_success"})
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.sent is True
        assert outcome.transfer_id == "tr_success"
        assert outcome.amount_cents == 9200

        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.provider_transfer_id == "tr_success"
        assert txn.transfer_amount_cents == 9200
        assert txn.transfer_sent_at is not None
        assert txn.transfer_attempted_at is not None
        assert txn.transfer_attempt_count == 1
        assert txn.transfer_last_error is None

    def test_the_stripe_call_shape(self, db):
        txn = _txn(db)
        fake = _FakeStripe(result={"id": "tr_1"})
        with _patched(fake):
            ct.execute_transfer(db, payment_transaction_id=txn.id)

        call = fake.calls[0]
        assert call["amount"] == 9200  # net_creator, with no fee subtracted
        assert call["currency"] == "aud"
        assert call["destination"] == ACCT
        assert call["source_transaction"] == CHARGE
        assert call["idempotency_key"] == f"txn:{txn.id}:transfer:v1"
        assert call["metadata"]["payment_transaction_id"] == txn.id

    def test_the_destination_is_the_snapshot_not_the_live_account(self, db, make_user):
        """A creator who swaps Stripe accounts after checkout cannot redirect
        an existing sale."""
        creator = make_user(role="creator")
        db.add(CreatorStripeAccount(
            id=f"csa_{uuid.uuid4()}", creator_user_id=creator.id, stripe_mode="test",
            stripe_account_id="acct_1Replacement",
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
            connect_payouts_enabled_at=datetime(2026, 9, 29, 12, 0, 0),
            fee_disclosure_acknowledged_at=datetime(2026, 9, 1, 8, 0, 0),
            fee_disclosure_version="2026-09-connect-v1",
        ))
        db.commit()

        txn = _txn(db, creator_user_id=creator.id, connect_destination_account_id=ACCT)
        fake = _FakeStripe(result={"id": "tr_1"})
        with _patched(fake):
            ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert fake.calls[0]["destination"] == ACCT
        assert fake.calls[0]["destination"] != "acct_1Replacement"

    def test_a_row_without_a_charge_omits_source_transaction(self, db):
        txn = _txn(db, provider_charge_id=None)
        fake = _FakeStripe(result={"id": "tr_1"})
        with _patched(fake):
            ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert "source_transaction" not in fake.calls[0]

    @pytest.mark.parametrize("status", [
        ConnectTransferStatus.awaiting_payment.value,
        ConnectTransferStatus.sent.value,
        ConnectTransferStatus.failed.value,
    ])
    def test_only_a_pending_row_is_sent(self, db, status):
        txn = _txn(db, connect_transfer_status=status)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.status == ct.SKIPPED
        assert fake.calls == []

    def test_a_manual_row_is_never_sent(self, db):
        txn = _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.status == ct.SKIPPED
        assert fake.calls == []

    def test_a_missing_transaction_is_skipped(self, db):
        fake = _FakeStripe()
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id="txn_nope")
        assert outcome.status == ct.SKIPPED
        assert fake.calls == []


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_balance_insufficient_is_retryable(self):
        """The one that matters. Observed against real Stripe: a transfer on a
        charge that has not settled is refused, and the identical call
        succeeds once the funds land."""
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        assert isinstance(ct.classify(err), ct.TransferRetryable)

    @pytest.mark.parametrize("code", sorted(ct.RETRYABLE_CODES))
    def test_every_retryable_code_is_retryable(self, code):
        err = stripe.InvalidRequestError("x", param=None, code=code)
        assert isinstance(ct.classify(err), ct.TransferRetryable)

    @pytest.mark.parametrize("code", [
        "amount_too_large", "account_invalid", "charge_already_refunded", None,
    ])
    def test_other_invalid_requests_are_terminal(self, code):
        """Stripe understood and refused. An identical retry gets an identical
        answer, which is positive evidence rather than a guess."""
        err = stripe.InvalidRequestError("refused", param=None, code=code)
        assert isinstance(ct.classify(err), ct.TransferTerminal)

    @pytest.mark.parametrize("factory", [
        lambda: stripe.APIConnectionError("no route"),
        lambda: stripe.RateLimitError("slow down"),
        lambda: stripe.APIError("500"),
        lambda: stripe.AuthenticationError("bad key"),
        lambda: stripe.PermissionError("nope"),
    ])
    def test_transport_and_config_failures_are_retryable(self, factory):
        """None of these is evidence the transfer is impossible, and a
        wrongly-terminal row is money nobody sends."""
        assert isinstance(ct.classify(factory()), ct.TransferRetryable)

    def test_an_unknown_exception_is_retryable(self):
        assert isinstance(ct.classify(RuntimeError("???")), ct.TransferRetryable)

    def test_an_idempotency_mismatch_is_terminal(self):
        """A request under this key already exists, so a transfer may have
        been created — never read as "nothing happened"."""
        err = stripe.IdempotencyError("key reused with different params")
        translated = ct.classify(err)
        assert isinstance(translated, ct.TransferTerminal)
        assert "may already exist" in str(translated)


class TestFailureRecording:
    def test_a_retryable_failure_stays_pending(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.status == ConnectTransferStatus.pending.value
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
        assert txn.transfer_attempt_count == 1
        assert "balance_insufficient" in (txn.transfer_last_error or "")
        assert txn.provider_transfer_id is None
        assert txn.transfer_sent_at is None

    def test_repeated_retryable_failures_accumulate_attempts(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        for _ in range(3):
            with _patched(_FakeStripe(error=err)):
                ct.execute_transfer(db, payment_transaction_id=txn.id)
        db.refresh(txn)
        assert txn.transfer_attempt_count == 3
        # Still owed. Never silently written off.
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_a_terminal_failure_marks_failed(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "No such destination", param="destination", code="account_invalid",
        )
        with _patched(_FakeStripe(error=err)):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.status == ConnectTransferStatus.failed.value
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.failed.value
        assert txn.provider_transfer_id is None
        assert "account_invalid" in (txn.transfer_last_error or "")

    def test_a_transfer_with_no_id_is_retryable(self, db):
        txn = _txn(db)
        with _patched(_FakeStripe(result={"no_id": True})):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)
        assert outcome.status == ConnectTransferStatus.pending.value
        db.refresh(txn)
        assert txn.provider_transfer_id is None

    def test_a_later_attempt_succeeds_after_a_retryable_failure(self, db):
        """The whole point of staying pending."""
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            ct.execute_transfer(db, payment_transaction_id=txn.id)
        with _patched(_FakeStripe(result={"id": "tr_later"})):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.sent is True
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert txn.provider_transfer_id == "tr_later"
        assert txn.transfer_attempt_count == 2
        assert txn.transfer_last_error is None


# ---------------------------------------------------------------------------
# One transfer, ever
# ---------------------------------------------------------------------------


class TestNoDoubleTransfer:
    def test_a_second_attempt_sends_nothing(self, db):
        txn = _txn(db)
        with _patched(_FakeStripe(result={"id": "tr_once"})):
            first = ct.execute_transfer(db, payment_transaction_id=txn.id)

        fake = _FakeStripe(result={"id": "tr_twice"})
        with _patched(fake):
            second = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert first.transfer_id == "tr_once"
        assert fake.calls == []
        assert second.transfer_id == "tr_once"
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_once"

    def test_the_idempotency_key_does_not_depend_on_the_amount(self, db):
        """A retry cannot become a second transfer by recomputing to a
        different figure."""
        txn = _txn(db)
        first = ct.idempotency_key(txn.id)
        txn.processing_fee_cents = 500
        db.commit()
        assert ct.idempotency_key(txn.id) == first


@pytest.mark.concurrency
class TestRaces:
    """Real concurrent sessions, because a row lock is the property here."""

    @staticmethod
    def _seed(engine) -> str:
        Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
        s = Session()
        try:
            txn = PaymentTransaction(
                id=f"txn_{uuid.uuid4().hex[:20]}",
                transaction_type=PaymentTransactionType.member_payment_option_purchase,
                status=PaymentTransactionStatus.succeeded,
                payment_provider=PaymentProvider.stripe,
                currency="AUD",
                gross_amount_cents=10000,
                platform_fee_basis_points=800,
                platform_fee_cents=800,
                net_creator_amount_cents=9200,
                net_platform_amount_cents=800,
                processing_fee_cents=200,
                payout_status=PayoutStatus.pending,
                stripe_mode="test",
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=ACCT,
                connect_transfer_status=ConnectTransferStatus.pending.value,
                provider_charge_id=CHARGE,
            )
            s.add(txn)
            s.commit()
            return txn.id
        finally:
            s.close()

    @staticmethod
    def _cleanup(engine, txn_id: str) -> None:
        Session = sessionmaker(bind=engine, future=True)
        s = Session()
        try:
            s.query(PaymentTransaction).filter(
                PaymentTransaction.id == txn_id,
            ).delete()
            s.commit()
        finally:
            s.close()

    def _run_two(self, engine, txn_id: str, fake) -> list:
        """Two workers, each on its own session, attempting at once."""
        Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
        outcomes: list = []
        barrier = threading.Barrier(2)

        def worker():
            s = Session()
            try:
                barrier.wait(timeout=10)
                outcomes.append(
                    ct.execute_transfer(s, payment_transaction_id=txn_id)
                )
            except Exception as exc:  # noqa: BLE001 — surfaced in the assertion
                outcomes.append(exc)
            finally:
                s.close()

        # Patched once around both threads rather than once inside each.
        # ``mock.patch`` is not thread-safe: two overlapping patches of
        # the same target can have the second thread record the first
        # thread's mock as "the original" and restore *that* on exit,
        # leaving a MagicMock on ``connect_transfers.get_stripe`` for
        # every test that runs afterwards in the session. The fake was
        # already shared by both workers, so hoisting changes nothing
        # about what this test exercises — the row lock still has to
        # serialise two genuinely concurrent callers.
        with _patched(fake):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)
        return outcomes

    def test_two_workers_produce_one_transfer(self, engine):
        """Sweeper against sweeper, or webhook against sweeper — the same
        row lock resolves both."""
        txn_id = self._seed(engine)
        try:
            fake = _FakeStripe(result={"id": "tr_only"})
            outcomes = self._run_two(engine, txn_id, fake)

            assert all(not isinstance(o, Exception) for o in outcomes), outcomes
            assert len(fake.calls) == 1, f"expected one Transfer.create, got {len(fake.calls)}"

            Session = sessionmaker(bind=engine, future=True)
            s = Session()
            try:
                row = s.query(PaymentTransaction).filter(
                    PaymentTransaction.id == txn_id,
                ).one()
                assert row.provider_transfer_id == "tr_only"
                assert row.connect_transfer_status == ConnectTransferStatus.sent.value
                assert row.transfer_attempt_count == 1
            finally:
                s.close()
        finally:
            self._cleanup(engine, txn_id)

    def test_the_loser_reports_the_existing_transfer(self, engine):
        txn_id = self._seed(engine)
        try:
            fake = _FakeStripe(result={"id": "tr_only"})
            outcomes = self._run_two(engine, txn_id, fake)
            ids = {o.transfer_id for o in outcomes if isinstance(o, ct.TransferOutcome)}
            # Both see the same transfer; neither invents a second.
            assert ids == {"tr_only"}
        finally:
            self._cleanup(engine, txn_id)


# ---------------------------------------------------------------------------
# The sweeper
# ---------------------------------------------------------------------------


class TestSweeper:
    def test_it_sends_an_owed_transfer(self, db):
        txn = _txn(db)
        with _patched(_FakeStripe(result={"id": "tr_swept"})):
            report = sweeper.sweep_pending_transfers(db)
        assert report.considered == 1
        assert report.sent == 1
        db.refresh(txn)
        assert txn.provider_transfer_id == "tr_swept"

    @pytest.mark.parametrize("status", [
        ConnectTransferStatus.awaiting_payment.value,
        ConnectTransferStatus.sent.value,
        ConnectTransferStatus.failed.value,
        ConnectTransferStatus.not_applicable.value,
    ])
    def test_it_never_acts_on_anything_but_pending(self, db, status):
        """``awaiting_payment`` above all: an abandoned Checkout Session lives
        there forever, and sweeping it would send FC's money before the
        customer's arrived."""
        if status == ConnectTransferStatus.not_applicable.value:
            _txn(
                db, payout_model=PayoutModel.manual.value,
                connect_destination_account_id=None,
                connect_transfer_status=status,
            )
        else:
            _txn(db, connect_transfer_status=status)
        fake = _FakeStripe()
        with _patched(fake):
            report = sweeper.sweep_pending_transfers(db)
        assert report.considered == 0
        assert fake.calls == []

    def test_it_never_acts_on_a_manual_row(self, db):
        _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert sweeper.sweep_pending_transfers(db).considered == 0
        assert fake.calls == []

    def test_it_never_reconsiders_a_row_that_already_has_a_transfer(self, db):
        _txn(
            db, provider_transfer_id="tr_already",
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert sweeper.sweep_pending_transfers(db).considered == 0
        assert fake.calls == []

    def test_it_records_a_resolved_fee_without_changing_the_amount(self, db):
        """The fee is still worth fetching — it is Fresh Collective's cost of
        sale and belongs on the row — but it no longer moves the amount."""
        # No charge id either — the sweeper learns both from the PaymentIntent,
        # and it never overwrites one it already has.
        txn = _txn(db, processing_fee_cents=None, provider_charge_id=None)

        class _Bt:
            fee = 250

        class _Charge:
            id = "ch_resolved"
            balance_transaction = _Bt()

        class _Pi:
            status = "succeeded"
            latest_charge = _Charge()

        fake = _FakeStripe(result={"id": "tr_after_fee"})
        fake.PaymentIntent = type("PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())})

        with patch("app.services.connect_transfer_sweeper.get_stripe", return_value=fake), \
             _patched(fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.fee_resolved == 1
        assert report.sent == 1
        db.refresh(txn)
        assert txn.processing_fee_cents == 250
        assert txn.provider_charge_id == "ch_resolved"
        # 9200, not 9200 - 250: the A$2.50 of card processing is Fresh
        # Collective's to absorb, so it never comes out of the creator's share.
        assert txn.transfer_amount_cents == 9200

    def test_an_unresolvable_fee_no_longer_strands_the_transfer(self, db):
        """The old behaviour left the row owed forever when Stripe would not
        report a fee. The creator's share never depended on that fee, so a
        bookkeeping gap must not hold their money."""
        txn = _txn(db, processing_fee_cents=None)

        class _Boom:
            @staticmethod
            def retrieve(*a, **k):
                raise stripe.APIConnectionError("no route")

        fake = _FakeStripe()
        fake.PaymentIntent = _Boom

        with patch("app.services.connect_transfer_sweeper.get_stripe", return_value=fake), \
             _patched(fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.fee_unavailable == 1
        assert report.sent == 1
        assert [c["amount"] for c in fake.calls] == [9200]
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        # The gap is still a gap: nothing was invented to paper over it.
        assert txn.processing_fee_cents is None

    def test_an_unsucceeded_payment_is_not_transferred(self, db):
        """A pending row whose payment turns out not to have succeeded must
        not send. Belt and braces behind ``mark_transfer_owed``."""
        txn = _txn(db, processing_fee_cents=None)

        class _Pi:
            status = "processing"
            latest_charge = None

        fake = _FakeStripe()
        fake.PaymentIntent = type("PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())})

        with patch("app.services.connect_transfer_sweeper.get_stripe", return_value=fake), \
             _patched(fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.sent == 0
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_it_reports_rows_needing_attention_without_giving_up(self, db):
        txn = _txn(db, transfer_attempt_count=ct.ATTENTION_ATTEMPTS)
        err = stripe.InvalidRequestError(
            "insufficient available funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            report = sweeper.sweep_pending_transfers(db)

        assert report.needs_attention == [txn.id]
        db.refresh(txn)
        # Still owed — reported, not written off.
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_it_is_bounded_by_the_limit(self, db):
        for _ in range(4):
            _txn(db)
        fake = _FakeStripe()   # unique id per call, as Stripe does
        with _patched(fake):
            report = sweeper.sweep_pending_transfers(db, limit=2)
        assert report.considered == 2
        assert len(fake.calls) == 2

    def test_a_terminal_failure_is_counted_and_not_retried(self, db):
        # Terminal now means there is no creator share to send at all. A fee
        # larger than the commission is no longer terminal — it is absorbed.
        txn = _txn(db, net_creator_amount_cents=0, processing_fee_cents=200)
        fake = _FakeStripe()
        with _patched(fake):
            first = sweeper.sweep_pending_transfers(db)
        assert first.failed == 1
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.failed.value

        with _patched(fake):
            second = sweeper.sweep_pending_transfers(db)
        assert second.considered == 0


# ---------------------------------------------------------------------------
# What absorbing the processing fee must not break
# ---------------------------------------------------------------------------


class TestAbsorbedFeePolicy:
    """The guarantees that made absorbing Stripe's processing fee safe."""

    def test_a_founding_creator_receives_the_entire_gross(self, db):
        """0% commission, end to end — not the arithmetic this time, but the
        figure actually handed to Stripe. A Founding Creator was promised the
        whole sale price, so the whole sale price has to leave."""
        txn = _txn(
            db, gross_amount_cents=10000, platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=10000,
            net_platform_amount_cents=0, processing_fee_cents=195,
        )
        fake = _FakeStripe(result={"id": "tr_founding"})
        with _patched(fake):
            outcome = ct.execute_transfer(db, payment_transaction_id=txn.id)

        assert outcome.sent is True
        # Exactly the gross: Stripe's A$1.95 came out of Fresh Collective's own
        # balance, and FC took no commission to cover it. This is the case
        # Stripe permits exactly — a transfer may equal, but not exceed, its
        # source charge.
        assert fake.calls[0]["amount"] == 10000
        assert fake.calls[0]["amount"] == txn.gross_amount_cents
        assert fake.calls[0]["source_transaction"] == CHARGE
        db.refresh(txn)
        assert txn.transfer_amount_cents == 10000

    def test_a_historical_transfer_is_never_recomputed(self, db):
        """Rows sent under the old formula keep the figure that actually left.

        The amount on a finished row records what Stripe did; it is not a value
        to re-derive. Recomputing it would rewrite history and make every
        reversal target wrong.
        """
        historical = _txn(
            db,
            connect_transfer_status=ConnectTransferStatus.sent.value,
            transfer_amount_cents=9000,          # 9200 - 200, the old formula
            provider_transfer_id="tr_historical",
            transfer_sent_at=datetime(2026, 9, 30, 10, 0, 0),
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = sweeper.sweep_pending_transfers(db)
            outcome = ct.execute_transfer(db, payment_transaction_id=historical.id)

        assert report.considered == 0            # invisible to the sweeper
        assert fake.calls == []                  # and no second transfer
        # The call reports the transfer that already exists rather than
        # making another, and reports it at its original amount.
        assert outcome.transfer_id == "tr_historical"
        assert outcome.amount_cents == 9000
        db.refresh(historical)
        assert historical.transfer_amount_cents == 9000
        assert historical.provider_transfer_id == "tr_historical"
        assert historical.connect_transfer_status == ConnectTransferStatus.sent.value

    def test_a_row_the_ledger_does_not_call_succeeded_is_never_sent(self, db):
        """The money has to be in before any of it goes out.

        This is the gate that does not depend on reaching Stripe, and it
        matters more than it used to: an unreadable processing fee once stopped
        the sweeper by accident, and that accident was also the only thing
        standing between an unpaid row and a transfer.
        """
        txn = _txn(
            db,
            status=PaymentTransactionStatus.pending,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.sent == 0
        assert report.still_pending == 1
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
        assert txn.provider_transfer_id is None

    def test_stripe_is_believed_over_the_ledger_about_payment(self, db):
        """Ledger says succeeded, Stripe says otherwise: nothing is sent. The
        ledger can be stale; Stripe holds the money."""
        txn = _txn(db, processing_fee_cents=None)      # forces the Stripe read

        class _Pi:
            status = "requires_payment_method"
            latest_charge = None

        fake = _FakeStripe()
        fake.PaymentIntent = type(
            "PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())},
        )
        with patch(
            "app.services.connect_transfer_sweeper.get_stripe", return_value=fake,
        ), _patched(fake):
            report = sweeper.sweep_pending_transfers(db)

        assert report.sent == 0
        assert report.still_pending == 1
        assert report.fee_unavailable == 0       # not a fee problem
        assert fake.calls == []
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
