"""Clawing the creator's share back: refunds, disputes, external reversals.

The formula tests are the important ones. The reversal target is anchored on
``refunded_creator_amount_cents`` — the figure the existing refund machinery
already derives — and scaled onto the amount actually transferred, because FC
retained the Stripe processing fee before transferring and the creator never
received it. Getting that wrong means either over-reversing (Stripe refuses)
or under-reversing (FC quietly absorbs the difference).

Everything cumulative is recomputed from the transaction's refund state rather
than accumulated, so a re-delivered event is a no-op by arithmetic rather than
by a flag.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import stripe
from sqlalchemy.orm import sessionmaker

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
from app.services import connect_reversals as cr
from app.webhooks import connect_money_handlers as money

ACCT = "acct_1ConnectReady"
TRANSFER = "tr_sent"
CHARGE = "ch_test"
TARGET = "app.services.connect_reversals.get_stripe"


class _FakeStripe:
    """Records reversal calls; can also serve a Transfer.retrieve."""

    def __init__(self, *, error=None, transfer_obj=None):
        self.reversals: list[dict] = []
        self.retrieves: list[str] = []
        outer = self

        class _Transfer:
            @staticmethod
            def create_reversal(transfer_id, **kwargs):
                outer.reversals.append({"transfer": transfer_id, **kwargs})
                if error is not None:
                    raise error
                return {"id": f"trr_{uuid.uuid4().hex[:12]}", **kwargs}

            @staticmethod
            def retrieve(transfer_id, **kwargs):
                outer.retrieves.append(transfer_id)
                if error is not None:
                    raise error
                return transfer_obj or {}

        self.Transfer = _Transfer


def _patched(fake):
    return patch(TARGET, return_value=fake)


def _txn(db, **overrides) -> PaymentTransaction:
    """A Connect row whose transfer has been sent: A$100 sale, 8%, A$2 fee."""
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
        # Connect rows carry not_applicable — FC's manual payout process does
        # not cover them. See the payout-status decision in migration 143.
        "payout_status": PayoutStatus.not_applicable,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": ACCT,
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "transfer_amount_cents": 9000,
        "provider_transfer_id": TRANSFER,
        "provider_charge_id": CHARGE,
        "provider_payment_intent_id": "pi_test",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


def _refunded(txn, db, *, amount: int, creator_share: int, platform_share: int):
    """Apply what the existing refund machinery would have written."""
    txn.refunded_amount_cents = amount
    txn.refunded_creator_amount_cents = creator_share
    txn.refunded_platform_fee_cents = platform_share
    txn.status = (
        PaymentTransactionStatus.refunded
        if amount >= txn.gross_amount_cents
        else PaymentTransactionStatus.partially_refunded
    )
    db.commit()
    # The invariant the existing machinery guarantees, restated here so a
    # change to it would break these tests too.
    assert platform_share + creator_share == amount


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------


class TestTarget:
    def test_no_refund_means_no_target(self, db):
        assert cr.compute_reversal_target(_txn(db)) == 0

    def test_a_full_refund_targets_the_whole_transfer(self, db):
        """Coerced, not computed — exactly the transfer, no rounding drift."""
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        assert cr.compute_reversal_target(txn) == 9000

    def test_the_target_never_exceeds_what_was_transferred(self, db):
        """``refunded_creator_amount_cents`` is 9200 in gross-split terms but
        only 9000 was ever sent. Reversing 9200 would be refused by Stripe and
        would try to take money the creator never got."""
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        assert txn.refunded_creator_amount_cents == 9200
        assert cr.compute_reversal_target(txn) == 9000

    def test_a_half_refund_targets_half_the_transfer(self, db):
        txn = _txn(db)
        # What compute_cumulative_reversal_targets produces for 5000 of 10000.
        _refunded(txn, db, amount=5000, creator_share=4600, platform_share=400)
        # 9000 × 4600 / 9200 = 4500
        assert cr.compute_reversal_target(txn) == 4500

    def test_a_small_partial_refund(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=1000, creator_share=920, platform_share=80)
        # 9000 × 920 / 9200 = 900
        assert cr.compute_reversal_target(txn) == 900

    def test_a_zero_percent_creator_reverses_gross_less_the_fee(self, db):
        """A Founding Creator received gross less the Stripe fee; a full refund
        takes exactly that back, and FC absorbs the fee it cannot recover."""
        txn = _txn(
            db, platform_fee_basis_points=0, platform_fee_cents=0,
            net_creator_amount_cents=10000, net_platform_amount_cents=0,
            transfer_amount_cents=9800,
        )
        _refunded(txn, db, amount=10000, creator_share=10000, platform_share=0)
        assert cr.compute_reversal_target(txn) == 9800

    def test_a_row_with_no_transfer_has_no_target(self, db):
        txn = _txn(db, transfer_amount_cents=None, provider_transfer_id=None,
                   connect_transfer_status=ConnectTransferStatus.pending.value)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        assert cr.compute_reversal_target(txn) == 0

    def test_the_idempotency_key_includes_the_cumulative_target(self):
        """A re-delivery computes the same target and is deduped; a second
        partial refund computes a larger one and is legitimately a new
        request, which a transaction-only key would have collapsed."""
        first = cr.reversal_idempotency_key("txn_1", 4500)
        again = cr.reversal_idempotency_key("txn_1", 4500)
        larger = cr.reversal_idempotency_key("txn_1", 9000)
        assert first == again
        assert first != larger


# ---------------------------------------------------------------------------
# Reversing
# ---------------------------------------------------------------------------


class TestReverse:
    def test_a_full_refund_reverses_the_whole_transfer(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert outcome.reversed_now == 9000
        assert outcome.fully_reversed is True
        assert fake.reversals[0]["transfer"] == TRANSFER
        assert fake.reversals[0]["amount"] == 9000
        assert fake.reversals[0]["idempotency_key"] == \
            cr.reversal_idempotency_key(txn.id, 9000)

        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.reversed_transfer_amount_cents == 9000
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value
        assert txn.connect_unrecovered_amount_cents == 0

    def test_a_partial_refund_partially_reverses(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=5000, creator_share=4600, platform_share=400)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert outcome.reversed_now == 4500
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.partially_reversed.value
        assert txn.reversed_transfer_amount_cents == 4500

    def test_a_second_partial_refund_reverses_only_the_delta(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=5000, creator_share=4600, platform_share=400)
        fake = _FakeStripe()
        with _patched(fake):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)

        # A second refund takes the cumulative total to 7500.
        _refunded(txn, db, amount=7500, creator_share=6900, platform_share=600)
        with _patched(fake):
            second = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        # 9000 × 6900 / 9200 = 6750; delta = 6750 − 4500 = 2250.
        assert second.reversed_now == 2250
        assert [r["amount"] for r in fake.reversals] == [4500, 2250]
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 6750
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.partially_reversed.value

    def test_a_partial_then_full_refund_completes_the_reversal(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=5000, creator_share=4600, platform_share=400)
        fake = _FakeStripe()
        with _patched(fake):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        with _patched(fake):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert [r["amount"] for r in fake.reversals] == [4500, 4500]
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value

    def test_a_duplicate_refund_event_reverses_nothing_further(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        fake = _FakeStripe()
        with _patched(fake):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)
            again = cr.reverse_to_target(db, payment_transaction_id=txn.id)
            third = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert len(fake.reversals) == 1
        assert again.status == cr.NOOP and again.reversed_now == 0
        assert third.status == cr.NOOP
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_an_already_fully_reversed_transfer_is_a_noop(self, db):
        txn = _txn(
            db,
            connect_transfer_status=ConnectTransferStatus.reversed.value,
            reversed_transfer_amount_cents=9000,
        )
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)
        assert outcome.status == cr.NOOP
        assert fake.reversals == []

    def test_a_row_with_no_transfer_is_skipped(self, db):
        txn = _txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        fake = _FakeStripe()
        with _patched(fake):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)
        assert outcome.status == cr.SKIPPED
        assert fake.reversals == []

    def test_a_manual_row_is_skipped(self, db):
        txn = _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None, provider_transfer_id=None,
            transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
            payout_status=PayoutStatus.pending,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert cr.reverse_to_target(
                db, payment_transaction_id=txn.id,
            ).status == cr.SKIPPED
        assert fake.reversals == []

    def test_the_refund_split_invariant_is_untouched(self, db):
        """The reversal reads the split; it never rewrites it."""
        txn = _txn(db)
        _refunded(txn, db, amount=5000, creator_share=4600, platform_share=400)
        with _patched(_FakeStripe()):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)
        db.refresh(txn)
        assert txn.refunded_platform_fee_cents + txn.refunded_creator_amount_cents \
            == txn.refunded_amount_cents
        assert txn.net_creator_amount_cents == 9200


# ---------------------------------------------------------------------------
# When Stripe will not give it back
# ---------------------------------------------------------------------------


class TestClassification:
    def test_insufficient_balance_is_its_own_class(self):
        err = stripe.InvalidRequestError(
            "Insufficient funds", param=None, code="balance_insufficient",
        )
        assert isinstance(cr.classify(err), cr.ReversalRecoveryRequired)

    def test_transient_codes_are_retryable(self):
        err = stripe.InvalidRequestError("busy", param=None, code="lock_timeout")
        assert isinstance(cr.classify(err), cr.ReversalRetryable)

    def test_other_refusals_are_terminal(self):
        err = stripe.InvalidRequestError(
            "cannot reverse", param=None, code="transfer_already_reversed",
        )
        assert isinstance(cr.classify(err), cr.ReversalTerminal)

    def test_transport_failures_are_retryable(self):
        assert isinstance(
            cr.classify(stripe.APIConnectionError("no route")), cr.ReversalRetryable,
        )

    def test_an_unknown_exception_is_retryable(self):
        assert isinstance(cr.classify(RuntimeError("???")), cr.ReversalRetryable)


class TestRecoveryRequired:
    def _insufficient(self):
        return stripe.InvalidRequestError(
            "Insufficient funds in the connected account",
            param=None, code="balance_insufficient",
        )

    def test_it_records_the_outstanding_amount_not_a_success(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        with _patched(_FakeStripe(error=self._insufficient())):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert outcome.status == ConnectRecoveryState.required.value
        assert outcome.unrecovered == 9000
        assert outcome.reversed_now == 0

        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000
        # Never pretends the money came back.
        assert txn.reversed_transfer_amount_cents == 0
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value
        assert "balance" in (txn.reversal_last_error or "")
        assert txn.reversal_attempt_count == 1

    def test_the_outstanding_amount_is_the_remaining_delta(self, db):
        """A partial reversal already happened; only the rest is outstanding."""
        txn = _txn(
            db, reversed_transfer_amount_cents=4500,
            connect_transfer_status=ConnectTransferStatus.partially_reversed.value,
        )
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        with _patched(_FakeStripe(error=self._insufficient())):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)
        assert outcome.unrecovered == 4500
        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 4500

    def test_the_advisory_matches_the_existing_recovery_vocabulary(self):
        """Reuses the phrase the refund routes already speak, so tooling built
        for manual post-payout recovery understands Connect too."""
        assert cr.RECOVERY_ADVISORY == "post_payout_manual_recovery_required"

    def test_a_retryable_failure_records_the_outstanding_amount(self, db):
        """Nothing was recovered, and the row has to say so.

        FC is owed this money whatever the reason the call failed, so a
        retryable failure records the shortfall exactly as a balance problem
        does — otherwise the row shows nothing outstanding and no sweeper can
        find it again. The *reason* is in ``reversal_last_error``; the
        *position* is in these two columns.
        """
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        with _patched(_FakeStripe(error=stripe.APIConnectionError("no route"))):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert outcome.status == "retryable"
        assert outcome.unrecovered == 9000
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 0
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000
        assert "no route" in (txn.reversal_last_error or "")
        assert txn.reversal_attempt_count == 1

    def test_a_terminal_refusal_still_leaves_the_money_owed(self, db):
        """A dead end for this request is not FC ceasing to be owed."""
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        err = stripe.InvalidRequestError(
            "no", param=None, code="transfer_already_reversed",
        )
        with _patched(_FakeStripe(error=err)):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)
        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000

    def test_a_later_attempt_can_still_succeed(self, db):
        txn = _txn(db)
        _refunded(txn, db, amount=10000, creator_share=9200, platform_share=800)
        with _patched(_FakeStripe(error=self._insufficient())):
            cr.reverse_to_target(db, payment_transaction_id=txn.id)
        with _patched(_FakeStripe()):
            outcome = cr.reverse_to_target(db, payment_transaction_id=txn.id)

        assert outcome.reversed_now == 9000
        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value
        assert txn.connect_unrecovered_amount_cents == 0
        assert txn.reversal_last_error is None


# ---------------------------------------------------------------------------
# Races
# ---------------------------------------------------------------------------


@pytest.mark.concurrency
class TestConcurrentReversal:
    @staticmethod
    def _seed(engine) -> str:
        Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
        s = Session()
        try:
            txn = PaymentTransaction(
                id=f"txn_{uuid.uuid4().hex[:20]}",
                transaction_type=PaymentTransactionType.member_payment_option_purchase,
                status=PaymentTransactionStatus.refunded,
                payment_provider=PaymentProvider.stripe,
                currency="AUD",
                gross_amount_cents=10000,
                platform_fee_basis_points=800,
                platform_fee_cents=800,
                net_creator_amount_cents=9200,
                net_platform_amount_cents=800,
                processing_fee_cents=200,
                refunded_amount_cents=10000,
                refunded_platform_fee_cents=800,
                refunded_creator_amount_cents=9200,
                payout_status=PayoutStatus.not_applicable,
                stripe_mode="test",
                payout_model=PayoutModel.connect.value,
                connect_destination_account_id=ACCT,
                connect_transfer_status=ConnectTransferStatus.sent.value,
                transfer_amount_cents=9000,
                provider_transfer_id=f"tr_{uuid.uuid4().hex[:12]}",
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

    def test_two_attempts_cannot_exceed_the_target(self, engine):
        """The row lock is the property: the loser recomputes a delta of zero
        against the winner's committed total."""
        txn_id = self._seed(engine)
        try:
            fake = _FakeStripe()
            Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
            barrier = threading.Barrier(2)
            outcomes: list = []

            def worker():
                s = Session()
                try:
                    barrier.wait(timeout=10)
                    with _patched(fake):
                        outcomes.append(
                            cr.reverse_to_target(s, payment_transaction_id=txn_id)
                        )
                except Exception as exc:  # noqa: BLE001
                    outcomes.append(exc)
                finally:
                    s.close()

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

            assert all(not isinstance(o, Exception) for o in outcomes), outcomes
            assert len(fake.reversals) == 1, fake.reversals
            assert sum(
                o.reversed_now for o in outcomes if isinstance(o, cr.ReversalOutcome)
            ) == 9000

            Session2 = sessionmaker(bind=engine, future=True)
            s2 = Session2()
            try:
                row = s2.query(PaymentTransaction).filter(
                    PaymentTransaction.id == txn_id,
                ).one()
                assert row.reversed_transfer_amount_cents == 9000
                assert row.connect_transfer_status == \
                    ConnectTransferStatus.reversed.value
            finally:
                s2.close()
        finally:
            self._cleanup(engine, txn_id)


# ---------------------------------------------------------------------------
# External reversals
# ---------------------------------------------------------------------------


class TestReconcileFromStripe:
    def test_a_full_external_reversal_is_reconciled(self, db):
        """Reversed from the Dashboard: the row must stop claiming ``sent``."""
        txn = _txn(db)
        fake = _FakeStripe(transfer_obj={
            "id": TRANSFER, "amount": 9000, "amount_reversed": 9000, "reversed": True,
        })
        with _patched(fake):
            outcome = money.connect_reversals.reconcile_from_stripe(
                db, transfer_id=TRANSFER,
            )
        assert fake.retrieves == [TRANSFER]
        assert outcome.cumulative_reversed == 9000
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.reversed_transfer_amount_cents == 9000

    def test_a_partial_external_reversal_is_reconciled(self, db):
        txn = _txn(db)
        fake = _FakeStripe(transfer_obj={
            "id": TRANSFER, "amount": 9000, "amount_reversed": 3000, "reversed": False,
        })
        with _patched(fake):
            money.connect_reversals.reconcile_from_stripe(db, transfer_id=TRANSFER)
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.partially_reversed.value
        assert txn.reversed_transfer_amount_cents == 3000

    def test_it_never_lowers_the_recorded_total(self, db):
        txn = _txn(
            db, reversed_transfer_amount_cents=9000,
            connect_transfer_status=ConnectTransferStatus.reversed.value,
        )
        fake = _FakeStripe(transfer_obj={
            "id": TRANSFER, "amount": 9000, "amount_reversed": 4000, "reversed": False,
        })
        with _patched(fake):
            outcome = money.connect_reversals.reconcile_from_stripe(
                db, transfer_id=TRANSFER,
            )
        assert outcome.status == cr.NOOP
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_an_external_reversal_settles_an_outstanding_recovery(self, db):
        """FC could not reverse it; someone did it from the Dashboard."""
        txn = _txn(
            db, connect_recovery_state=ConnectRecoveryState.required.value,
            connect_unrecovered_amount_cents=9000,
        )
        fake = _FakeStripe(transfer_obj={
            "id": TRANSFER, "amount": 9000, "amount_reversed": 9000, "reversed": True,
        })
        with _patched(fake):
            money.connect_reversals.reconcile_from_stripe(db, transfer_id=TRANSFER)
        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 0
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value

    def test_an_unknown_transfer_is_skipped(self, db):
        fake = _FakeStripe()
        with _patched(fake):
            outcome = money.connect_reversals.reconcile_from_stripe(
                db, transfer_id="tr_not_ours",
            )
        assert outcome.status == cr.SKIPPED
        assert fake.retrieves == []

    def test_the_webhook_handler_reconciles(self, db):
        txn = _txn(db)
        fake = _FakeStripe(transfer_obj={
            "id": TRANSFER, "amount": 9000, "amount_reversed": 9000, "reversed": True,
        })
        with _patched(fake):
            money.handle_transfer_reversed({"id": TRANSFER}, db)
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value

    def test_the_handler_tolerates_an_event_with_no_id(self, db):
        money.handle_transfer_reversed({}, db)   # must not raise


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


class TestDisputes:
    def _dispute(self, **overrides) -> dict:
        d = {"id": "dp_1", "charge": CHARGE, "payment_intent": "pi_test"}
        d.update(overrides)
        return d

    def test_a_dispute_on_a_sent_transfer_recovers_the_whole_transfer(self, db):
        """FC is liable for the whole charge, so the whole transfer is owed
        back — not a proportion of a refund that has not happened."""
        txn = _txn(db)
        fake = _FakeStripe()
        with _patched(fake):
            money.handle_dispute_created(self._dispute(), db)

        assert fake.reversals[0]["amount"] == 9000
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is not None
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.reversed_transfer_amount_cents == 9000

    def test_a_dispute_with_no_refund_still_reverses_in_full(self, db):
        """The refund-derived target would be zero here; the override is what
        makes the dispute case correct."""
        txn = _txn(db)
        assert cr.compute_reversal_target(txn) == 0
        with _patched(_FakeStripe()):
            money.handle_dispute_created(self._dispute(), db)
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_a_dispute_before_the_transfer_was_sent_holds_it(self, db):
        """Do not keep paying a creator for a charge FC may lose."""
        txn = _txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            money.handle_dispute_created(self._dispute(), db)

        assert fake.reversals == []
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is not None
        # Still owed in principle — held, not cancelled.
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_a_dispute_on_an_awaiting_payment_row_holds_it(self, db):
        txn = _txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.awaiting_payment.value,
        )
        with _patched(_FakeStripe()):
            money.handle_dispute_created(self._dispute(), db)
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is not None
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.awaiting_payment.value

    def test_a_dispute_on_an_already_reversed_row_is_a_noop(self, db):
        txn = _txn(
            db, connect_transfer_status=ConnectTransferStatus.reversed.value,
            reversed_transfer_amount_cents=9000,
        )
        fake = _FakeStripe()
        with _patched(fake):
            money.handle_dispute_created(self._dispute(), db)
        assert fake.reversals == []
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_an_insufficient_balance_on_a_dispute_records_the_shortfall(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "Insufficient funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            money.handle_dispute_created(self._dispute(), db)
        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000

    def test_a_manual_row_gets_no_connect_treatment(self, db):
        txn = _txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None, provider_transfer_id=None,
            transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
            payout_status=PayoutStatus.pending,
        )
        fake = _FakeStripe()
        with _patched(fake):
            money.handle_dispute_created(self._dispute(), db)
        assert fake.reversals == []
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is None
        # payout_status is untouched — ``held`` belongs to manual batches.
        assert txn.payout_status == PayoutStatus.pending

    def test_payout_status_is_never_touched_by_a_dispute(self, db):
        txn = _txn(db)
        with _patched(_FakeStripe()):
            money.handle_dispute_created(self._dispute(), db)
        db.refresh(txn)
        assert txn.payout_status == PayoutStatus.not_applicable

    def test_an_unknown_charge_is_harmless(self, db):
        with _patched(_FakeStripe()):
            money.handle_dispute_created(
                self._dispute(charge="ch_unknown", payment_intent=None), db,
            )

    def test_winning_a_dispute_releases_the_held_transfer(self, db):
        """Otherwise the hold would outlive the dispute and the creator would
        never be paid."""
        txn = _txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        with _patched(_FakeStripe()):
            money.handle_dispute_created(self._dispute(), db)
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is not None

        money.handle_dispute_closed(self._dispute(status="won"), db)
        db.refresh(txn)
        assert txn.connect_dispute_opened_at is None
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_losing_a_dispute_leaves_the_recovery_outstanding(self, db):
        txn = _txn(db)
        err = stripe.InvalidRequestError(
            "Insufficient funds", param=None, code="balance_insufficient",
        )
        with _patched(_FakeStripe(error=err)):
            money.handle_dispute_created(self._dispute(), db)
        money.handle_dispute_closed(self._dispute(status="lost"), db)
        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000
        assert txn.connect_dispute_opened_at is not None


class TestSweeperHoldsDisputes:
    def test_a_disputed_owed_transfer_is_not_swept(self, db):
        from app.services import connect_transfer_sweeper as sweeper

        txn = _txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
            connect_dispute_opened_at=datetime(2026, 9, 29, 12, 0, 0),
        )
        with patch(
            "app.services.connect_transfers.get_stripe", return_value=_FakeStripe(),
        ):
            report = sweeper.sweep_pending_transfers(db)

        assert report.considered == 0
        # Reported, not silently stalled.
        assert report.held_by_dispute == 1
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value
