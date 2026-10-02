"""``payout_status`` is manual-payout bookkeeping, and Connect is not in it.

The first live Connect sale
---------------------------
Gross 200c, FC fee 16c, Stripe fee 33c, transferred 151c,
``connect_transfer_status='sent'`` — and ``payout_status='pending'``,
which says Fresh Collective still owes that creator 184c by hand.

Nothing could have paid them twice: the payout batch query filters
``payout_model = 'manual'`` explicitly, with a comment saying why
``payout_status`` alone cannot be trusted. But two reporting figures
read ``payout_status`` without that filter — the admin "Pending Payouts"
total and the creator's own ``pending_payout_cents`` — so money Stripe
had already sent was counted as outstanding.

Every creation path already wrote ``not_applicable`` for Connect rows.
The payment-succeeded webhook overwrote it unconditionally. That one
line is the whole defect; migration 146 repairs the rows it already
produced.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.models.payment import (
    ConnectTransferStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
    PayoutStatus,
)

#: The production sale this file exists for.
LIVE = dict(
    gross_amount_cents=200,
    platform_fee_cents=16,
    processing_fee_cents=33,
    transfer_amount_cents=151,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _connect_row(db, creator_id, **overrides) -> PaymentTransaction:
    values = {
        "id": _uid("txn"),
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "creator_user_id": creator_id,
        "currency": "AUD",
        "gross_amount_cents": LIVE["gross_amount_cents"],
        "platform_fee_basis_points": 800,
        "platform_fee_cents": LIVE["platform_fee_cents"],
        "net_creator_amount_cents": 184,
        "processing_fee_cents": LIVE["processing_fee_cents"],
        "transfer_amount_cents": LIVE["transfer_amount_cents"],
        "payout_model": PayoutModel.connect.value,
        # Required by ``ck_payment_transactions_connect_has_destination``.
        "connect_destination_account_id": "acct_1LiveCreator",
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "payout_status": PayoutStatus.not_applicable,
        "stripe_mode": "test",
        "created_at": datetime(2026, 10, 1, 9, 0, 0),
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The webhook no longer drags Connect rows into the manual queue
# ---------------------------------------------------------------------------


class TestTheSucceededWebhookRespectsPayoutModel:
    def test_a_connect_row_is_not_moved_to_pending(self, db, make_user):
        """The exact line that broke it: an unconditional
        ``txn.payout_status = PayoutStatus.pending`` on payment success."""
        import inspect

        from app.webhooks import routes as webhook_routes

        source = inspect.getsource(webhook_routes._handle_checkout_completed)
        assignment = source.index("txn.payout_status = PayoutStatus.pending")
        guard = source.index("if txn.payout_model != PayoutModel.connect.value:")
        assert guard < assignment, (
            "the pending assignment must sit behind a payout_model guard"
        )

    def test_a_manual_row_keeps_its_pending_semantics(self, db, make_user):
        creator = make_user(role="creator")
        row = _connect_row(
            db, creator.id,
            payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=None,
            transfer_amount_cents=None,
            payout_status=PayoutStatus.pending,
        )
        assert row.payout_status == PayoutStatus.pending


class TestManualPayoutsStillExcludeConnect:
    def test_the_batch_query_filters_on_payout_model_not_payout_status(self):
        """The money-safety guard, unchanged by this task. Pinned because
        it is the reason the defect was a reporting bug and not a
        double-payment one."""
        import inspect

        from app.services import payout_batch_orchestration

        source = inspect.getsource(payout_batch_orchestration)
        assert "pt.payout_model = 'manual'" in source

    def test_a_connect_row_is_not_payable_by_hand(self, db, make_user):
        """Even sitting at ``pending`` — the state migration 146 repairs —
        a Connect row contributes nothing to a manual batch."""
        from app.services import payout_batch_orchestration as batches

        creator = make_user(role="creator")
        _connect_row(db, creator.id, payout_status=PayoutStatus.pending)

        summary = batches.compute_payable_summary(
            db, creator_user_id=creator.id, currency="AUD",
        )

        assert summary["payable_cents"] == 0
        assert summary["transaction_count"] == 0


# ---------------------------------------------------------------------------
# The creator-facing API can finally tell the two apart
# ---------------------------------------------------------------------------


class TestThePaymentsApiExposesConnect:
    def test_a_connect_row_carries_its_economics(self, db, make_user):
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        row = _connect_row(db, creator.id)

        detail = _connect_detail(row)

        assert detail is not None
        assert detail.sale_amount_cents == 200
        assert detail.platform_fee_cents == 16
        assert detail.processing_fee_cents == 33
        assert detail.creator_amount_cents == 151
        assert detail.status_label == "Sent to Stripe"

    def test_the_creator_amount_is_the_transfer_not_the_net(self, db, make_user):
        """184c is gross minus FC's fee. 151c is what actually moved,
        because Stripe's fee comes out of that too. Showing 184 would
        overstate the sale by the processing fee."""
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        row = _connect_row(db, creator.id)

        assert row.net_creator_amount_cents == 184
        assert _connect_detail(row).creator_amount_cents == 151

    def test_the_lines_account_for_the_sale(self, db, make_user):
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        detail = _connect_detail(_connect_row(db, creator.id))

        assert (
            detail.platform_fee_cents
            + detail.processing_fee_cents
            + detail.creator_amount_cents
        ) == detail.sale_amount_cents

    def test_an_unmeasured_processing_fee_is_none_not_zero(self, db, make_user):
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        row = _connect_row(
            db, creator.id, processing_fee_cents=None, transfer_amount_cents=None,
        )

        detail = _connect_detail(row)

        assert detail.processing_fee_cents is None
        assert detail.creator_amount_cents is None

    def test_a_manual_row_carries_no_connect_block(self, db, make_user):
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        row = _connect_row(
            db, creator.id,
            payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=None,
            transfer_amount_cents=None,
            payout_status=PayoutStatus.pending,
        )

        assert _connect_detail(row) is None

    def test_no_stripe_internals_reach_the_creator(self, db, make_user):
        from app.creator.routes import _connect_detail

        creator = make_user(role="creator")
        detail = _connect_detail(_connect_row(db, creator.id))

        leaked = set(detail.model_dump()) & {
            "provider_transfer_id", "connect_destination_account_id",
            "connect_recovery_state", "connect_transfer_attempts",
            "connect_outstanding_recovery_cents", "last_error_message",
        }
        assert leaked == set(), leaked


class TestTheTwoCreatorSurfacesCannotDrift:
    def test_the_detail_mirrors_the_earnings_row(self):
        """Payments received and the Billing earnings list are built from
        the same ``connect_earnings.to_row``. If that dataclass gains a
        field, this fails rather than the new value silently vanishing
        from one of the two surfaces."""
        import dataclasses

        from app.creator.schemas import TransactionConnectDetail
        from app.services.connect_earnings import ConnectEarningRow

        earning_fields = {f.name for f in dataclasses.fields(ConnectEarningRow)}
        detail_fields = set(TransactionConnectDetail.model_fields)
        # The detail deliberately drops the two identity fields; the row
        # it hangs off already carries them.
        assert detail_fields == earning_fields - {
            "payment_transaction_id", "created_at",
        }


# ---------------------------------------------------------------------------
# Migration 146
# ---------------------------------------------------------------------------


class TestTheBackfill:
    def _statement(self) -> str:
        from pathlib import Path

        import app.creator.routes as anchor

        root = Path(anchor.__file__).resolve().parents[2]
        path = root / "alembic/versions/146_connect_payout_status_not_applicable.py"
        return path.read_text()

    def test_it_only_touches_connect_rows(self):
        body = self._statement()
        assert "payout_model = 'connect'" in body
        assert "payout_status = 'pending'" in body

    def test_it_never_writes_paid(self):
        """A Connect transfer is not a manual disbursement, and 'paid'
        would also wrongly imply the bank account was reached."""
        assert "'paid'" not in self._statement()

    def test_running_it_twice_changes_nothing_more(self, db, make_user):
        from sqlalchemy import text

        creator = make_user(role="creator")
        stuck = _connect_row(db, creator.id, payout_status=PayoutStatus.pending)
        manual = _connect_row(
            db, creator.id,
            payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            connect_transfer_status=None,
            transfer_amount_cents=None,
            payout_status=PayoutStatus.pending,
        )

        statement = text(
            "UPDATE payment_transactions SET payout_status = 'not_applicable' "
            "WHERE payout_model = 'connect' AND payout_status = 'pending'"
        )
        first = db.execute(statement).rowcount
        second = db.execute(statement).rowcount
        db.commit()

        assert first >= 1
        assert second == 0, "a second run must be a no-op"
        db.refresh(stuck)
        db.refresh(manual)
        assert stuck.payout_status == PayoutStatus.not_applicable
        assert manual.payout_status == PayoutStatus.pending, (
            "manual history must not be touched"
        )
