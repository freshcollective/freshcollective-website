"""Closing the processing-fee gap without touching anybody's money.

The fee is Fresh Collective's cost of sale. Absorbing it meant a transfer no
longer waits for Stripe to report it, which left rows that could never be
priced afterwards — the transfer sweeper only sees rows that still owe a
transfer. This reconciliation fills those in.

The tests that matter most are the ones proving what it does *not* do. It
writes one figure for Fresh Collective's own books, and a creator's earnings,
a historical commission and every transfer must come out the other side
byte-identical.
"""

from __future__ import annotations

import pathlib
import uuid
from unittest.mock import patch

import pytest

from app.models.payment import (
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)
from app.services import processing_fee_reconciliation as recon

MODULE = "app.services.processing_fee_reconciliation"
CHARGE = "ch_recon"


def _txn(db, **overrides) -> PaymentTransaction:
    """A succeeded Stripe sale whose processing fee was never recorded."""
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
        "processing_fee_cents": None,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": "acct_1ConnectReady",
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "transfer_amount_cents": 9200,
        "provider_transfer_id": f"tr_{uuid.uuid4().hex[:12]}",
        "provider_charge_id": CHARGE,
        "provider_payment_intent_id": "pi_recon",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


def _manual_txn(db, **overrides) -> PaymentTransaction:
    """The same, but paid by hand — no Connect state at all."""
    values = {
        "payout_model": PayoutModel.manual.value,
        "connect_destination_account_id": None,
        "connect_transfer_status": ConnectTransferStatus.not_applicable.value,
        "transfer_amount_cents": None,
        "provider_transfer_id": None,
    }
    values.update(overrides)
    return _txn(db, **values)


def _snapshot(txn: PaymentTransaction) -> dict:
    return {
        c.name: getattr(txn, c.name)
        for c in PaymentTransaction.__table__.columns
    }


# ---------------------------------------------------------------------------
# It records the fee Stripe actually charged
# ---------------------------------------------------------------------------


class TestItRecordsTheRealFee:
    def test_a_succeeded_row_with_no_fee_is_filled_in(self, db):
        txn = _txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=217) as read:
            report = recon.reconcile_missing_fees(db)

        assert report.resolved == 1
        assert report.unreadable == []
        assert read.call_args.args[0] == CHARGE    # the row's own charge
        db.refresh(txn)
        assert txn.processing_fee_cents == 217

    def test_a_manual_payout_row_is_reconciled_too(self, db):
        """The figure is Fresh Collective's cost of sale whatever the payout
        model, and the admin totals sum every succeeded row."""
        txn = _manual_txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=190):
            report = recon.reconcile_missing_fees(db)

        assert report.resolved == 1
        db.refresh(txn)
        assert txn.processing_fee_cents == 190
        assert txn.payout_model == PayoutModel.manual.value

    def test_it_learns_a_missing_charge_id_from_the_payment_intent(self, db):
        txn = _txn(db, provider_charge_id=None)

        class _Pi:
            latest_charge = "ch_learned"

        fake = type("S", (), {"PaymentIntent": type(
            "PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())},
        )})()

        with patch("app.checkout.stripe_client.get_stripe", return_value=fake), \
             patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=205) as read:
            report = recon.reconcile_missing_fees(db)

        assert report.resolved == 1
        assert report.charge_ids_learned == 1
        assert read.call_args.args[0] == "ch_learned"
        db.refresh(txn)
        assert txn.processing_fee_cents == 205
        assert txn.provider_charge_id == "ch_learned"

    def test_an_expanded_latest_charge_object_is_accepted_too(self, db):
        """``latest_charge`` is an id unexpanded and an object expanded. Both
        shapes have to work, because which one arrives is Stripe's choice."""
        _txn(db, provider_charge_id=None)

        class _Charge:
            id = "ch_object"

        class _Pi:
            latest_charge = _Charge()

        fake = type("S", (), {"PaymentIntent": type(
            "PI", (), {"retrieve": staticmethod(lambda *a, **k: _Pi())},
        )})()

        with patch("app.checkout.stripe_client.get_stripe", return_value=fake), \
             patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=1) as read:
            recon.reconcile_missing_fees(db)

        assert read.call_args.args[0] == "ch_object"


# ---------------------------------------------------------------------------
# It never estimates
# ---------------------------------------------------------------------------


class TestItNeverEstimates:
    def test_an_unreadable_fee_stays_null_and_is_logged_for_retry(self, db):
        txn = _txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=None):
            report = recon.reconcile_missing_fees(db)

        assert report.resolved == 0
        assert report.unreadable == [txn.id]
        db.refresh(txn)
        assert txn.processing_fee_cents is None     # not 0, not a guess

    def test_a_row_with_nothing_to_read_from_is_never_queued(self, db):
        """No charge and no payment intent means no fee to find. Queueing it
        would mean a Stripe call every fifteen minutes, for ever, for a row
        that can never resolve."""
        _txn(db, provider_charge_id=None, provider_payment_intent_id=None)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge") as read:
            report = recon.reconcile_missing_fees(db)

        assert report.considered == 0
        assert read.call_args_list == []

    def test_a_payment_intent_that_cannot_be_read_is_retried_not_guessed(self, db):
        txn = _txn(db, provider_charge_id=None)

        def _boom(*a, **k):
            raise RuntimeError("no route to Stripe")

        fake = type("S", (), {"PaymentIntent": type(
            "PI", (), {"retrieve": staticmethod(_boom)},
        )})()

        with patch("app.checkout.stripe_client.get_stripe", return_value=fake), \
             patch(f"{MODULE}.retrieve_processing_fee_for_charge") as read:
            report = recon.reconcile_missing_fees(db)

        assert report.unreadable == [txn.id]
        assert read.call_args_list == []            # never asked with no charge
        db.refresh(txn)
        assert txn.processing_fee_cents is None
        assert txn.provider_charge_id is None

    @pytest.mark.parametrize("overrides, why", [
        ({"status": PaymentTransactionStatus.pending}, "not succeeded"),
        ({"payment_provider": PaymentProvider.manual}, "never a Stripe payment"),
        ({"gross_amount_cents": 0, "platform_fee_cents": 0,
          "net_creator_amount_cents": 0, "net_platform_amount_cents": 0,
          "transfer_amount_cents": None, "provider_transfer_id": None,
          "connect_transfer_status": ConnectTransferStatus.pending.value},
         "nothing was charged"),
    ])
    def test_rows_that_can_never_have_a_fee_are_left_alone(self, db, overrides, why):
        _txn(db, **overrides)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge") as read:
            report = recon.reconcile_missing_fees(db)
        assert report.considered == 0, why
        assert read.call_args_list == [], why


# ---------------------------------------------------------------------------
# It changes nothing else — the point of the whole exercise
# ---------------------------------------------------------------------------


class TestItTouchesNothingElse:
    def test_only_the_fee_column_changes(self, db):
        txn = _txn(db)
        before = _snapshot(txn)

        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=250):
            recon.reconcile_missing_fees(db)

        db.refresh(txn)
        after = _snapshot(txn)
        changed = {
            k for k in before
            if before[k] != after[k] and k not in {"updated_at"}
        }
        assert changed == {"processing_fee_cents"}

    def test_creator_earnings_and_the_commission_are_untouched(self, db):
        """Named explicitly because these are the figures that would matter
        if this job ever went wrong."""
        txn = _txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=9999):
            recon.reconcile_missing_fees(db)

        db.refresh(txn)
        # Even an absurd fee — larger than the commission — moves nothing.
        assert txn.net_creator_amount_cents == 9200
        assert txn.platform_fee_cents == 800
        assert txn.platform_fee_basis_points == 800
        assert txn.net_platform_amount_cents == 800
        assert txn.transfer_amount_cents == 9200
        assert txn.gross_amount_cents == 10000

    def test_a_historical_transfer_amount_is_not_recomputed(self, db):
        """A row sent under the old formula keeps the figure that really
        left, fee or no fee."""
        txn = _txn(db, transfer_amount_cents=9000)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=200):
            recon.reconcile_missing_fees(db)

        db.refresh(txn)
        assert txn.transfer_amount_cents == 9000
        assert txn.processing_fee_cents == 200

    def test_no_transfer_is_ever_initiated(self, db):
        txn = _txn(db, connect_transfer_status=ConnectTransferStatus.pending.value,
                   transfer_amount_cents=None, provider_transfer_id=None)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=200), \
             patch("app.services.connect_transfers.execute_transfer") as execute:
            recon.reconcile_missing_fees(db)

        assert execute.call_args_list == []
        db.refresh(txn)
        assert txn.provider_transfer_id is None
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_payout_state_is_never_marked(self, db):
        """The six manual Founding Creator payments are still owed by hand.
        Recording Fresh Collective's cost of sale must not look like paying
        anybody."""
        txn = _manual_txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=200):
            recon.reconcile_missing_fees(db)

        db.refresh(txn)
        assert txn.payout_status == PayoutStatus.pending
        assert txn.payout_marked_at is None
        assert txn.payout_batch_id is None
        assert txn.payout_reference is None


# ---------------------------------------------------------------------------
# Safe to run again, and bounded
# ---------------------------------------------------------------------------


class TestRetrySafety:
    def test_an_existing_fee_is_never_overwritten(self, db):
        txn = _txn(db, processing_fee_cents=123)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=999) as read:
            report = recon.reconcile_missing_fees(db)

        assert report.considered == 0
        assert read.call_args_list == []
        db.refresh(txn)
        assert txn.processing_fee_cents == 123

    def test_a_second_pass_is_a_no_op(self, db):
        txn = _txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=217):
            first = recon.reconcile_missing_fees(db)
            second = recon.reconcile_missing_fees(db)

        assert (first.resolved, second.resolved) == (1, 0)
        assert second.considered == 0
        db.refresh(txn)
        assert txn.processing_fee_cents == 217

    def test_a_row_filled_in_by_someone_else_mid_pass_is_skipped(self, db):
        """The webhook and the transfer sweeper write this column too. The
        claim is a query, not a lock, so the value is re-checked."""
        txn = _txn(db)

        def _steal(_charge):
            # Stand in for a concurrent writer landing between claim and read.
            db.query(PaymentTransaction).filter(
                PaymentTransaction.id == txn.id,
            ).update({"processing_fee_cents": 111})
            db.commit()
            return 222

        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", side_effect=_steal):
            recon.reconcile_missing_fees(db)

        db.refresh(txn)
        # Whoever wrote first wins; this pass does not clobber them.
        assert txn.processing_fee_cents == 111

    def test_one_pass_is_bounded(self, db):
        for _ in range(5):
            _txn(db)
        with patch(f"{MODULE}.retrieve_processing_fee_for_charge", return_value=200):
            report = recon.reconcile_missing_fees(db, limit=2)

        assert report.considered == 2
        assert report.resolved == 2
        remaining = db.query(PaymentTransaction).filter(
            PaymentTransaction.processing_fee_cents.is_(None),
        ).count()
        assert remaining == 3

    def test_one_unreadable_row_does_not_block_the_rest(self, db):
        """Rows are committed one at a time, so a row Stripe will not price
        cannot hold up the queue behind it."""
        first = _txn(db)                       # claimed first: created_at ASC
        second = _txn(db)

        with patch(
            f"{MODULE}.retrieve_processing_fee_for_charge",
            side_effect=[None, 200],
        ):
            report = recon.reconcile_missing_fees(db)

        assert report.resolved == 1
        assert report.unreadable == [first.id]
        db.refresh(first)
        db.refresh(second)
        assert first.processing_fee_cents is None
        assert second.processing_fee_cents == 200


# ---------------------------------------------------------------------------
# How it is scheduled
# ---------------------------------------------------------------------------


class TestItRunsInsideTheExistingCron:
    """No new service, no new schedule, no blueprint change.

    A new Render cron would mean editing ``render.yaml``, and a blueprint
    sync reverts Dashboard-set environment flags. Reusing the sweeper's cron
    avoids that entirely.
    """

    @staticmethod
    def _run_main():
        """The cron's entry point, with the money work and Sentry stubbed."""
        from scripts import fc_connect_transfer_sweeper as cron
        with patch("sys.argv", ["fc_connect_transfer_sweeper"]), \
             patch.object(
                 cron._sweeper, "sweep_pending_transfers",
                 return_value=cron._sweeper.SweepReport(),
             ), \
             patch.object(cron, "report_partial_failures", return_value=None), \
             patch.object(cron, "report_balance_headroom", return_value=None), \
             patch.object(cron, "report_payout_schedule_stragglers", return_value=None):
            return cron.main()

    def test_the_sweep_cron_reconciles_fees_after_sweeping(self, db):
        from scripts import fc_connect_transfer_sweeper as cron
        with patch.object(
            cron, "reconcile_processing_fees", return_value=None,
        ) as rec:
            assert self._run_main() == 0
        assert rec.call_count == 1

    def test_it_runs_after_the_money_work_not_before(self, db):
        """It must not be able to affect, or delay, a transfer."""
        from scripts import fc_connect_transfer_sweeper as cron
        order: list[str] = []
        with patch("sys.argv", ["fc_connect_transfer_sweeper"]), \
             patch.object(
                 cron._sweeper, "sweep_pending_transfers",
                 side_effect=lambda *a, **k: (
                     order.append("sweep"), cron._sweeper.SweepReport(),
                 )[1],
             ), \
             patch.object(cron, "report_partial_failures", return_value=None), \
             patch.object(cron, "report_balance_headroom", return_value=None), \
             patch.object(cron, "report_payout_schedule_stragglers", return_value=None), \
             patch.object(
                 cron, "reconcile_processing_fees",
                 side_effect=lambda *a, **k: order.append("fees"),
             ):
            assert cron.main() == 0
        assert order == ["sweep", "fees"]

    def test_a_reconciliation_failure_does_not_fail_the_sweep(self, db):
        """The sweep has already moved money by this point. A bookkeeping
        read that throws must not turn a good run into a failed cron and an
        operator page."""
        from scripts import fc_connect_transfer_sweeper as cron
        with patch.object(
            cron.fee_recon, "reconcile_missing_fees",
            side_effect=RuntimeError("Stripe down"),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.reconcile_processing_fees(db) is None
        assert cap.call_args_list == []

    def test_a_failure_still_leaves_the_cron_able_to_fail_for_real(self):
        """``main``'s only ``except`` stays the fatal one, so a genuine
        failure still exits non-zero and Render still notices. Pinned here
        because moving this handler into ``main`` is the tempting shortcut.
        """
        import ast
        from scripts import fc_connect_transfer_sweeper as cron
        tree = ast.parse(pathlib.Path(cron.__file__).read_text())
        main = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "main"
        )
        handlers = [n for n in ast.walk(main) if isinstance(n, ast.ExceptHandler)]
        assert len(handlers) == 1
        returns = [n for n in ast.walk(handlers[0]) if isinstance(n, ast.Return)]
        assert returns and all(r.value.value != 0 for r in returns)

    def test_unpriced_rows_are_reported_to_sentry_as_a_warning(self, db):
        """Warning, not error: a creator is unaffected, but Fresh
        Collective's cost of sale is incomplete and somebody should know."""
        from scripts import fc_connect_transfer_sweeper as cron
        report = recon.FeeReconciliationReport(resolved=2)
        report.unreadable = ["txn_a", "txn_b", "txn_c"]
        with patch.object(
            cron.fee_recon, "reconcile_missing_fees", return_value=report,
        ), patch.object(cron, "capture_job_summary", return_value="evt") as cap:
            assert cron.reconcile_processing_fees(db) == "evt"

        assert cap.call_args.kwargs["level"] == "warning"
        assert cap.call_args.kwargs["rows_unpriced"] == 3
        assert cap.call_args.kwargs["rows_resolved"] == 2
        # Transaction ids are not breadcrumbs; they stay in the Render log.
        assert "txn_a" not in str(cap.call_args)

    def test_a_clean_pass_reports_nothing(self, db):
        from scripts import fc_connect_transfer_sweeper as cron
        with patch.object(
            cron.fee_recon, "reconcile_missing_fees",
            return_value=recon.FeeReconciliationReport(resolved=1),
        ), patch.object(cron, "capture_job_summary") as cap:
            assert cron.reconcile_processing_fees(db) is None
        assert cap.call_args_list == []


# ---------------------------------------------------------------------------
# The production failure of 2026-10-11
# ---------------------------------------------------------------------------


class TestItWorksInACronEnvironment:
    """A cron has ``STRIPE_SECRET_KEY`` and deliberately no webhook secret.

    The reconciler shipped reusing ``retrieve_processing_fee_for_charge``,
    which gated on ``settings.stripe_enabled`` — secret key *and* webhook
    secret. Every run therefore raised::

        RuntimeError: Stripe is not configured —
                      cannot create finite payment plan.

    straight after a PaymentIntent read had succeeded with HTTP 200, which
    is the tell: the job could reach Stripe perfectly well, and only the
    helper's own check refused.

    ``STRIPE_WEBHOOK_SECRET`` is absent from every cron environment by
    design — a job receives no webhooks — so this was not a misconfigured
    service. It is the same mistake ``ensure_api_configured`` was written
    to end for the Connect sweepers, reintroduced through a helper that had
    not been brought into line.
    """

    @staticmethod
    def _cron_env(monkeypatch):
        """Exactly what the sweeper has in production: a key, no webhook."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_cron", raising=False)
        monkeypatch.setattr(settings, "stripe_webhook_secret", None, raising=False)
        # The precondition that makes this test meaningful.
        assert settings.stripe_api_enabled is True
        assert settings.stripe_enabled is False
        return settings

    def test_the_fee_reader_does_not_raise_without_a_webhook_secret(
        self, monkeypatch,
    ):
        """The regression itself. Before the fix this raised RuntimeError."""
        from app.services import stripe_finite_plan as sfp
        self._cron_env(monkeypatch)

        class _Bt:
            fee = 46

        class _Charge:
            balance_transaction = _Bt()

        monkeypatch.setattr(
            sfp, "get_stripe",
            lambda: type("S", (), {"Charge": type(
                "C", (), {"retrieve": staticmethod(lambda *a, **k: _Charge())},
            )})(),
        )
        assert sfp.retrieve_processing_fee_for_charge("ch_x") == 46

    def test_the_whole_reconciliation_pass_succeeds_in_a_cron(
        self, db, monkeypatch,
    ):
        """End to end through the real helper, in the real cron environment.

        This is the shape of the production failure: a succeeded row with no
        fee, a reachable Stripe, and no webhook secret.
        """
        txn = _txn(db)
        self._cron_env(monkeypatch)

        from app.services import stripe_finite_plan as sfp

        class _Bt:
            fee = 46

        class _Charge:
            balance_transaction = _Bt()

        monkeypatch.setattr(
            sfp, "get_stripe",
            lambda: type("S", (), {"Charge": type(
                "C", (), {"retrieve": staticmethod(lambda *a, **k: _Charge())},
            )})(),
        )
        report = recon.reconcile_missing_fees(db)       # must not raise

        assert report.resolved == 1
        db.refresh(txn)
        assert txn.processing_fee_cents == 46

    def test_a_configuration_problem_returns_none_rather_than_raising(
        self, monkeypatch,
    ):
        """The contract the function always documented but did not keep.

        ``_bind_key()`` sat *outside* the ``try``, so a configuration failure
        escaped as an exception while every other failure returned ``None``.
        An informational read must never be able to fail its caller.
        """
        from app.checkout.stripe_client import StripeNotConfiguredError
        from app.services import stripe_finite_plan as sfp

        def _unconfigured():
            raise StripeNotConfiguredError("no key")

        monkeypatch.setattr(sfp, "get_stripe", _unconfigured)
        assert sfp.retrieve_processing_fee_for_charge("ch_x") is None

    def test_an_unreadable_fee_is_still_never_estimated(self, db, monkeypatch):
        """The rule the fix must not trade away: the figure comes from
        Stripe's balance transaction or it stays NULL."""
        txn = _txn(db)
        self._cron_env(monkeypatch)

        from app.services import stripe_finite_plan as sfp

        class _Charge:
            balance_transaction = None          # Stripe will not price it

        monkeypatch.setattr(
            sfp, "get_stripe",
            lambda: type("S", (), {"Charge": type(
                "C", (), {"retrieve": staticmethod(lambda *a, **k: _Charge())},
            )})(),
        )
        report = recon.reconcile_missing_fees(db)

        assert report.resolved == 0
        assert report.unreadable == [txn.id]
        db.refresh(txn)
        assert txn.processing_fee_cents is None     # not 0, not a guess

    def test_a_balance_transaction_with_no_fee_is_not_read_as_zero(
        self, db, monkeypatch,
    ):
        """The other way Stripe can decline to price a charge: the balance
        transaction exists but carries no ``fee``. Zero is a number a person
        would believe, and believing it would understate Fresh Collective's
        cost of sale. ``None`` keeps the row in the queue instead."""
        txn = _txn(db)
        self._cron_env(monkeypatch)

        from app.services import stripe_finite_plan as sfp

        class _Bt:
            pass                                # present, but no .fee

        class _Charge:
            balance_transaction = _Bt()

        monkeypatch.setattr(
            sfp, "get_stripe",
            lambda: type("S", (), {"Charge": type(
                "C", (), {"retrieve": staticmethod(lambda *a, **k: _Charge())},
            )})(),
        )
        assert sfp.retrieve_processing_fee_for_charge("ch_x") is None

        report = recon.reconcile_missing_fees(db)
        assert report.resolved == 0
        assert report.unreadable == [txn.id]
        db.refresh(txn)
        assert txn.processing_fee_cents is None

    def test_taking_money_still_requires_the_webhook_secret(self, monkeypatch):
        """The protection this fix must not weaken.

        Reading a fee needs the key alone. *Creating* a payment plan still
        needs the webhook secret, because charging a member with no
        verifiable completion webhook would strand them. ``_bind_key``
        keeps that stricter gate.
        """
        import pytest as _pytest

        from app.services.stripe_finite_plan import _bind_key
        self._cron_env(monkeypatch)
        with _pytest.raises(RuntimeError, match="Stripe is not configured"):
            _bind_key()
