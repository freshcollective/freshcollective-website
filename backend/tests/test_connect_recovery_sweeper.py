"""Retrying outstanding creator recoveries.

The sweeper chooses rows and timing; every figure comes from the reversal
service. So these tests mostly check selection, backoff and the counts — plus
the two properties that matter most: it cannot exceed the cumulative target, and
it never touches the customer's refund.

Backoff is exercised by passing ``now`` rather than sleeping.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
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
from app.services import connect_recovery_sweeper as rs
from app.services import connect_reversals as cr

ACCT = "acct_1ConnectReady"
TARGET = "app.services.connect_reversals.get_stripe"
NOW = datetime(2026, 9, 29, 12, 0, 0)


class _FakeStripe:
    def __init__(self, *, error=None, errors=None):
        self.reversals: list[dict] = []
        self._errors = list(errors) if errors else None
        outer = self

        class _Transfer:
            @staticmethod
            def create_reversal(transfer_id, **kwargs):
                outer.reversals.append({"transfer": transfer_id, **kwargs})
                if outer._errors:
                    nxt = outer._errors.pop(0)
                    if nxt is not None:
                        raise nxt
                    return {"id": f"trr_{uuid.uuid4().hex[:10]}"}
                if error is not None:
                    raise error
                return {"id": f"trr_{uuid.uuid4().hex[:10]}"}

            @staticmethod
            def retrieve(transfer_id, **kwargs):
                return {}

        self.Transfer = _Transfer


def _patched(fake):
    return patch(TARGET, return_value=fake)


def _insufficient():
    return stripe.InvalidRequestError(
        "Insufficient funds in the connected account",
        param=None, code="balance_insufficient",
    )


def _outstanding_txn(db, **overrides) -> PaymentTransaction:
    """A fully refunded Connect row whose reversal did not complete.

    A$100 sale, 8% plan, A$2 Stripe fee → A$90 transferred, all of it owed back.
    """
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.refunded,
        "payment_provider": PaymentProvider.stripe,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "processing_fee_cents": 200,
        "refunded_amount_cents": 10000,
        "refunded_platform_fee_cents": 800,
        "refunded_creator_amount_cents": 9200,
        "payout_status": PayoutStatus.not_applicable,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": ACCT,
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "transfer_amount_cents": 9000,
        "provider_transfer_id": f"tr_{uuid.uuid4().hex[:12]}",
        "provider_charge_id": f"ch_{uuid.uuid4().hex[:12]}",
        "connect_recovery_state": ConnectRecoveryState.required.value,
        "connect_unrecovered_amount_cents": 9000,
        "reversal_attempt_count": 1,
        "reversal_attempted_at": NOW - timedelta(days=2),
        "reversal_last_error": "balance_insufficient",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_an_outstanding_row_is_picked_up(self, db):
        txn = _outstanding_txn(db)
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.attempted == 1
        assert report.reversed == 1
        assert fake.reversals[0]["amount"] == 9000
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.connect_unrecovered_amount_cents == 0
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value

    def test_a_manual_row_is_ignored(self, db):
        _outstanding_txn(
            db, payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None, provider_transfer_id=None,
            transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.not_applicable.value,
            connect_recovery_state=ConnectRecoveryState.none.value,
            connect_unrecovered_amount_cents=0,
            payout_status=PayoutStatus.pending,
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)
        assert report.attempted == 0
        assert fake.reversals == []

    def test_a_row_with_no_transfer_is_ignored(self, db):
        """Nothing was ever sent, so nothing can be owed back."""
        _outstanding_txn(
            db, provider_transfer_id=None, transfer_amount_cents=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
            connect_recovery_state=ConnectRecoveryState.none.value,
            connect_unrecovered_amount_cents=0,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert rs.sweep_pending_recoveries(db, now=NOW).attempted == 0
        assert fake.reversals == []

    def test_a_fully_reversed_row_is_skipped(self, db):
        _outstanding_txn(
            db,
            connect_transfer_status=ConnectTransferStatus.reversed.value,
            reversed_transfer_amount_cents=9000,
            connect_recovery_state=ConnectRecoveryState.recovered.value,
            connect_unrecovered_amount_cents=0,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert rs.sweep_pending_recoveries(db, now=NOW).attempted == 0
        assert fake.reversals == []

    def test_an_externally_reconciled_row_is_skipped(self, db):
        """Someone reversed it from the Dashboard and ``transfer.reversed``
        caught the ledger up. There is nothing left to ask Stripe for."""
        txn = _outstanding_txn(db)
        fake = _FakeStripe(transfer_obj=None) if False else _FakeStripe()

        # Reconcile as the webhook would.
        class _Reconciled(_FakeStripe):
            def __init__(self):
                super().__init__()
                outer = self

                class _Transfer:
                    @staticmethod
                    def retrieve(transfer_id, **kwargs):
                        return {
                            "id": transfer_id, "amount": 9000,
                            "amount_reversed": 9000, "reversed": True,
                        }

                    @staticmethod
                    def create_reversal(transfer_id, **kwargs):
                        outer.reversals.append({"transfer": transfer_id, **kwargs})
                        return {"id": "trr_x"}

                self.Transfer = _Transfer

        recon = _Reconciled()
        with _patched(recon):
            cr.reconcile_from_stripe(db, transfer_id=txn.provider_transfer_id)

        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value

        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)
        assert report.attempted == 0
        assert fake.reversals == []

    def test_a_row_with_no_outstanding_amount_is_skipped(self, db):
        _outstanding_txn(db, connect_unrecovered_amount_cents=0)
        fake = _FakeStripe()
        with _patched(fake):
            assert rs.sweep_pending_recoveries(db, now=NOW).attempted == 0
        assert fake.reversals == []

    def test_a_row_not_marked_required_is_skipped(self, db):
        _outstanding_txn(
            db, connect_recovery_state=ConnectRecoveryState.recovered.value,
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert rs.sweep_pending_recoveries(db, now=NOW).attempted == 0
        assert fake.reversals == []

    def test_it_is_bounded_by_the_limit(self, db):
        for _ in range(4):
            _outstanding_txn(db)
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, limit=2, now=NOW)
        assert report.attempted == 2
        assert len(fake.reversals) == 2


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_a_never_attempted_row_is_due_immediately(self, db):
        _outstanding_txn(db, reversal_attempted_at=None, reversal_attempt_count=0)
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)
        assert report.attempted == 1

    def test_a_recent_attempt_is_left_to_cool_off(self, db):
        """An empty creator balance is not asked about continuously."""
        txn = _outstanding_txn(
            db, reversal_attempt_count=3,
            reversal_attempted_at=NOW - timedelta(minutes=1),
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.attempted == 0
        assert report.cooling_off == 1
        # Still counted as outstanding, so it is never out of sight.
        assert report.outstanding_cents == 9000
        assert fake.reversals == []
        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 9000

    def test_the_cooldown_grows_with_attempts_and_is_capped(self):
        assert rs.cooldown_for(0) == timedelta(0)
        assert rs.cooldown_for(1) == timedelta(seconds=rs.BASE_COOLDOWN_SECONDS)
        assert rs.cooldown_for(2) == timedelta(seconds=rs.BASE_COOLDOWN_SECONDS * 2)
        assert rs.cooldown_for(3) == timedelta(seconds=rs.BASE_COOLDOWN_SECONDS * 4)
        assert rs.cooldown_for(50) == timedelta(seconds=rs.MAX_COOLDOWN_SECONDS)

    def test_a_row_past_its_cooldown_is_attempted(self, db):
        _outstanding_txn(
            db, reversal_attempt_count=2,
            reversal_attempted_at=NOW - timedelta(hours=2),
        )
        fake = _FakeStripe()
        with _patched(fake):
            assert rs.sweep_pending_recoveries(db, now=NOW).attempted == 1


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class TestOutcomes:
    def test_a_retryable_failure_succeeds_on_a_later_sweep(self, db):
        txn = _outstanding_txn(db)
        transient = stripe.APIConnectionError("no route")

        with _patched(_FakeStripe(error=transient)):
            first = rs.sweep_pending_recoveries(db, now=NOW)
        assert first.still_retryable == 1
        assert first.reversed == 0
        db.refresh(txn)
        assert txn.connect_unrecovered_amount_cents == 9000
        assert txn.reversed_transfer_amount_cents == 0

        # Later, past the new cooldown, it goes through.
        later = NOW + timedelta(hours=6)
        fake = _FakeStripe()
        with _patched(fake):
            second = rs.sweep_pending_recoveries(db, now=later)
        assert second.reversed == 1
        assert fake.reversals[0]["amount"] == 9000
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value
        assert txn.connect_unrecovered_amount_cents == 0
        assert txn.connect_recovery_state == ConnectRecoveryState.recovered.value

    def test_insufficient_balance_stays_required_and_is_not_treated_as_transient(
        self, db,
    ):
        txn = _outstanding_txn(db)
        with _patched(_FakeStripe(error=_insufficient())):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.recovery_required == 1
        assert report.still_retryable == 0
        assert report.reversed == 0
        db.refresh(txn)
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000
        assert txn.reversed_transfer_amount_cents == 0
        # Never silently converted to success.
        assert txn.connect_transfer_status == ConnectTransferStatus.sent.value

    def test_an_empty_balance_is_not_hammered_across_sweeps(self, db):
        """Each failure pushes the next attempt further out."""
        txn = _outstanding_txn(db, reversal_attempt_count=0, reversal_attempted_at=None)
        fake = _FakeStripe(error=_insufficient())
        with _patched(fake):
            rs.sweep_pending_recoveries(db, now=NOW)
            # Immediately again: the cooldown holds it back.
            second = rs.sweep_pending_recoveries(db, now=NOW)

        assert len(fake.reversals) == 1
        assert second.attempted == 0
        assert second.cooling_off == 1
        db.refresh(txn)
        assert txn.reversal_attempt_count == 1

    def test_a_partial_recovery_is_counted_as_reversed(self, db):
        """Half the purchase was refunded, so only half the transfer is owed."""
        txn = _outstanding_txn(
            db, status=PaymentTransactionStatus.partially_refunded,
            refunded_amount_cents=5000, refunded_platform_fee_cents=400,
            refunded_creator_amount_cents=4600,
            connect_unrecovered_amount_cents=4500,
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.reversed == 1
        assert fake.reversals[0]["amount"] == 4500
        db.refresh(txn)
        assert txn.connect_transfer_status == \
            ConnectTransferStatus.partially_reversed.value
        assert txn.reversed_transfer_amount_cents == 4500

    def test_it_reports_rows_needing_attention_without_writing_them_off(self, db):
        txn = _outstanding_txn(
            db, reversal_attempt_count=rs.ATTENTION_ATTEMPTS,
            reversal_attempted_at=NOW - timedelta(days=5),
        )
        with _patched(_FakeStripe(error=_insufficient())):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.needs_attention == [txn.id]
        assert report.outstanding_cents == 9000
        db.refresh(txn)
        # Still owed and still in the queue.
        assert txn.connect_recovery_state == ConnectRecoveryState.required.value
        assert txn.connect_unrecovered_amount_cents == 9000

    def test_a_dispute_row_recovers_the_whole_transfer(self, db):
        """No refund at all — the target comes from the dispute, derived by the
        reversal service from stored state rather than known by the sweeper."""
        txn = _outstanding_txn(
            db, status=PaymentTransactionStatus.succeeded,
            refunded_amount_cents=0, refunded_platform_fee_cents=0,
            refunded_creator_amount_cents=0,
            connect_dispute_opened_at=NOW - timedelta(days=1),
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert report.reversed == 1
        assert fake.reversals[0]["amount"] == 9000
        db.refresh(txn)
        assert txn.connect_transfer_status == ConnectTransferStatus.reversed.value


# ---------------------------------------------------------------------------
# Never over-reverse, never touch the refund
# ---------------------------------------------------------------------------


class TestSafety:
    def test_duplicate_sweeps_do_not_over_reverse(self, db):
        txn = _outstanding_txn(db)
        fake = _FakeStripe()
        with _patched(fake):
            rs.sweep_pending_recoveries(db, now=NOW)
            second = rs.sweep_pending_recoveries(db, now=NOW + timedelta(days=1))
            third = rs.sweep_pending_recoveries(db, now=NOW + timedelta(days=2))

        assert len(fake.reversals) == 1
        assert second.attempted == 0 and third.attempted == 0
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 9000

    def test_it_never_reverses_past_the_cumulative_target(self, db):
        """A partially refunded row where a previous reversal already met the
        target: the delta is zero and nothing is sent."""
        txn = _outstanding_txn(
            db, status=PaymentTransactionStatus.partially_refunded,
            refunded_amount_cents=5000, refunded_platform_fee_cents=400,
            refunded_creator_amount_cents=4600,
            reversed_transfer_amount_cents=4500,
            connect_transfer_status=ConnectTransferStatus.partially_reversed.value,
            # Stale bookkeeping: the row still claims an outstanding amount the
            # target no longer supports.
            connect_unrecovered_amount_cents=4500,
        )
        fake = _FakeStripe()
        with _patched(fake):
            report = rs.sweep_pending_recoveries(db, now=NOW)

        assert fake.reversals == []
        assert report.skipped == 1
        db.refresh(txn)
        assert txn.reversed_transfer_amount_cents == 4500

    def test_the_customer_refund_is_never_touched(self, db):
        txn = _outstanding_txn(db)
        before = (
            txn.refunded_amount_cents,
            txn.refunded_platform_fee_cents,
            txn.refunded_creator_amount_cents,
            txn.status,
        )
        with _patched(_FakeStripe()):
            rs.sweep_pending_recoveries(db, now=NOW)
        db.refresh(txn)
        assert (
            txn.refunded_amount_cents,
            txn.refunded_platform_fee_cents,
            txn.refunded_creator_amount_cents,
            txn.status,
        ) == before
        assert txn.net_creator_amount_cents == 9200

    def test_a_failed_recovery_also_leaves_the_refund_untouched(self, db):
        txn = _outstanding_txn(db)
        with _patched(_FakeStripe(error=_insufficient())):
            rs.sweep_pending_recoveries(db, now=NOW)
        db.refresh(txn)
        assert txn.refunded_amount_cents == 10000
        assert txn.status == PaymentTransactionStatus.refunded

    def test_payout_status_is_never_touched(self, db):
        txn = _outstanding_txn(db)
        with _patched(_FakeStripe()):
            rs.sweep_pending_recoveries(db, now=NOW)
        db.refresh(txn)
        assert txn.payout_status == PayoutStatus.not_applicable


@pytest.mark.concurrency
class TestConcurrentSweeps:
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
                connect_recovery_state=ConnectRecoveryState.required.value,
                connect_unrecovered_amount_cents=9000,
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

    def test_two_sweeps_cannot_exceed_the_target(self, engine):
        """The lock lives in the reversal service; this proves the sweeper
        inherits it rather than working around it."""
        txn_id = self._seed(engine)
        try:
            fake = _FakeStripe()
            Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
            barrier = threading.Barrier(2)
            errors: list = []

            def worker():
                s = Session()
                try:
                    barrier.wait(timeout=10)
                    with _patched(fake):
                        rs.sweep_pending_recoveries(s, now=NOW)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                finally:
                    s.close()

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

            assert errors == [], errors
            assert len(fake.reversals) == 1, fake.reversals
            assert fake.reversals[0]["amount"] == 9000

            Session2 = sessionmaker(bind=engine, future=True)
            s2 = Session2()
            try:
                row = s2.query(PaymentTransaction).filter(
                    PaymentTransaction.id == txn_id,
                ).one()
                assert row.reversed_transfer_amount_cents == 9000
                assert row.connect_transfer_status == \
                    ConnectTransferStatus.reversed.value
                assert row.connect_unrecovered_amount_cents == 0
                # The refund, untouched by either worker.
                assert row.refunded_amount_cents == 10000
            finally:
                s2.close()
        finally:
            self._cleanup(engine, txn_id)


def test_the_sweeper_duplicates_no_reversal_maths():
    """All amounts come from the reversal service. A target computed here would
    eventually disagree with the one the refund path uses."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "app/services/connect_recovery_sweeper.py"
    ).read_text()
    for forbidden in (
        "refunded_creator_amount_cents",
        "net_creator_amount_cents",
        "processing_fee_cents",
        "round(",
    ):
        assert forbidden not in source, (
            f"{forbidden!r} appears in the sweeper — reversal arithmetic belongs "
            "in connect_reversals"
        )
