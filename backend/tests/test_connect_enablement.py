"""Acknowledgement, the routing-enable guard, and the Connect earnings view.

The guard is the important part. ``connect_payouts_enabled_at`` is the one field
in this codebase that causes money to take a different path, and the tests here
exist to keep it that way: nothing automatic sets it, acknowledging does not set
it, and it cannot be set for a creator Stripe would not actually pay.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.creator_stripe_account import (
    FEE_DISCLOSURE_VERSION,
    CreatorStripeAccount,
    OnboardingState,
)
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
from app.services import connect_earnings as earnings
from app.services import connect_routing_enablement as enablement

ACCT = "acct_1ConnectReady"


def _account(db, creator_id, **overrides) -> CreatorStripeAccount:
    """Payout-ready and acknowledged, unless overridden."""
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
        "stripe_account_id": ACCT,
        "onboarding_state": OnboardingState.ready.value,
        "transfers_status": "active",
        "transfers_enabled": True,
        "payouts_status": "active",
        "payouts_enabled": True,
        "details_submitted": True,
        "external_account_count": 1,
        "fee_disclosure_acknowledged_at": datetime(2026, 9, 20, 10, 0, 0),
        "fee_disclosure_version": FEE_DISCLOSURE_VERSION,
    }
    values.update(overrides)
    row = CreatorStripeAccount(**values)
    db.add(row)
    db.commit()
    return row


def _connect_txn(db, creator_id, **overrides) -> PaymentTransaction:
    """A Connect sale: A$100, 8% fee, A$2 Stripe fee → A$90 to the creator."""
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "creator_user_id": creator_id,
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
        "provider_transfer_id": f"tr_{uuid.uuid4().hex[:12]}",
        "created_at": datetime(2026, 9, 20, 12, 0, 0),
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


def _manual_txn(db, creator_id, **overrides) -> PaymentTransaction:
    values = {
        "id": f"txn_{uuid.uuid4().hex[:20]}",
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.succeeded,
        "payment_provider": PaymentProvider.stripe,
        "creator_user_id": creator_id,
        "currency": "AUD",
        "gross_amount_cents": 10000,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 800,
        "net_creator_amount_cents": 9200,
        "net_platform_amount_cents": 800,
        "payout_status": PayoutStatus.pending,
        "stripe_mode": "test",
        "payout_model": PayoutModel.manual.value,
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Acknowledgement
# ---------------------------------------------------------------------------


class TestAcknowledgement:
    def test_it_records_when_and_which_wording(self, db, make_user):
        creator = make_user(role="creator")
        _account(
            db, creator.id,
            fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
        )
        row = enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
        assert row.fee_disclosure_acknowledged_at is not None
        assert row.fee_disclosure_version == FEE_DISCLOSURE_VERSION

    def test_acknowledging_never_enables_routing(self, db, make_user):
        """The whole reason the two are separate acts."""
        creator = make_user(role="creator")
        _account(
            db, creator.id,
            fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
        )
        row = enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
        assert row.connect_payouts_enabled_at is None
        db.refresh(row)
        assert row.connect_payouts_enabled_at is None

    def test_acknowledging_twice_is_harmless(self, db, make_user):
        creator = make_user(role="creator")
        _account(
            db, creator.id,
            fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
        )
        enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
        row = enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
        assert row.fee_disclosure_version == FEE_DISCLOSURE_VERSION

    def test_a_creator_with_no_account_cannot_acknowledge(self, db, make_user):
        creator = make_user(role="creator")
        with pytest.raises(enablement.RoutingEnablementError) as excinfo:
            enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
        assert excinfo.value.reason == enablement.BLOCKER_NO_ACCOUNT_ROW

    def test_a_version_without_a_timestamp_is_rejected(self, db, make_user):
        """Half-recorded consent is worse than none."""
        creator = make_user(role="creator")
        with pytest.raises(IntegrityError):
            _account(
                db, creator.id,
                fee_disclosure_acknowledged_at=None,
                fee_disclosure_version=FEE_DISCLOSURE_VERSION,
            )


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


class TestEnablementGuard:
    def test_a_fully_ready_acknowledged_creator_can_be_enabled(self, db, make_user):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(db, creator.id)

        row = enablement.enable_routing(
            db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
        )
        assert row.connect_payouts_enabled_at is not None

    def test_it_cannot_be_enabled_without_acknowledgement(self, db, make_user):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(
            db, creator.id,
            fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
        )
        with pytest.raises(enablement.RoutingEnablementError) as excinfo:
            enablement.enable_routing(
                db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
            )
        assert excinfo.value.reason == enablement.BLOCKER_NOT_ACKNOWLEDGED
        assert enablement.find_account(
            db, creator_user_id=creator.id,
        ).connect_payouts_enabled_at is None

    def test_it_cannot_be_enabled_unless_payouts_are_active(self, db, make_user):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(
            db, creator.id,
            onboarding_state=OnboardingState.transfers_only.value,
            payouts_status="restricted", payouts_enabled=False,
            external_account_count=0,
        )
        with pytest.raises(enablement.RoutingEnablementError) as excinfo:
            enablement.enable_routing(
                db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
            )
        assert excinfo.value.reason == enablement.BLOCKER_PAYOUTS_NOT_ACTIVE

    def test_it_cannot_be_enabled_without_a_stripe_account(self, db, make_user):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(
            db, creator.id, stripe_account_id=None,
            onboarding_state=OnboardingState.not_started.value,
            transfers_status=None, transfers_enabled=False,
            payouts_status=None, payouts_enabled=False,
        )
        with pytest.raises(enablement.RoutingEnablementError):
            enablement.enable_routing(
                db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
            )

    def test_it_cannot_be_enabled_with_no_account_for_this_mode(self, db, make_user):
        """A live account is invisible to a test-mode deployment."""
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(db, creator.id, stripe_mode="live", stripe_account_id="acct_liveOnly")
        with pytest.raises(enablement.RoutingEnablementError) as excinfo:
            enablement.enable_routing(
                db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
            )
        assert excinfo.value.reason == enablement.BLOCKER_NO_ACCOUNT_ROW

    def test_the_assessment_lists_every_missing_condition(self, db, make_user):
        """An admin should see the whole picture, not the first failure."""
        creator = make_user(role="creator")
        account = _account(
            db, creator.id,
            payouts_status="restricted", payouts_enabled=False,
            fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
        )
        assessment = enablement.assess(account)
        assert assessment.ready is False
        assert set(assessment.blockers) == {
            enablement.BLOCKER_PAYOUTS_NOT_ACTIVE,
            enablement.BLOCKER_PAYOUTS_NOT_ENABLED,
            enablement.BLOCKER_NOT_ACKNOWLEDGED,
        }

    def test_enabling_twice_keeps_the_original_timestamp(self, db, make_user):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(db, creator.id)
        first = enablement.enable_routing(
            db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
        ).connect_payouts_enabled_at
        again = enablement.enable_routing(
            db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
        ).connect_payouts_enabled_at
        assert first == again

    def test_disabling_leaves_everything_in_flight_alone(self, db, make_user):
        """Future sales only. A transfer already owed is still owed."""
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _account(db, creator.id)
        enablement.enable_routing(
            db, creator_user_id=creator.id, enabled_by_user_id=admin.id,
        )
        txn = _connect_txn(
            db, creator.id,
            connect_transfer_status=ConnectTransferStatus.pending.value,
            transfer_amount_cents=None, provider_transfer_id=None,
        )

        row = enablement.disable_routing(
            db, creator_user_id=creator.id, disabled_by_user_id=admin.id,
        )
        assert row.connect_payouts_enabled_at is None
        db.refresh(txn)
        assert txn.payout_model == PayoutModel.connect.value
        assert txn.connect_transfer_status == ConnectTransferStatus.pending.value

    def test_the_schema_refuses_routing_without_acknowledgement(self, db, make_user):
        """Belt and braces: a caller that bypasses the service still cannot
        produce an unsafe row."""
        creator = make_user(role="creator")
        with pytest.raises(IntegrityError):
            _account(
                db, creator.id,
                fee_disclosure_acknowledged_at=None, fee_disclosure_version=None,
                connect_payouts_enabled_at=datetime(2026, 9, 29, 12, 0, 0),
            )

    def test_nothing_else_in_the_codebase_assigns_the_routing_flag(self):
        """The one field that changes where money goes has exactly one writer."""
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        writers = []
        for path in app_dir.rglob("*.py"):
            text = path.read_text()
            if "connect_payouts_enabled_at =" in text or \
                    "connect_payouts_enabled_at=" in text.replace(
                        "connect_payouts_enabled_at=None", "",
                    ):
                writers.append(path.relative_to(app_dir).as_posix())
        assert writers == ["services/connect_routing_enablement.py"], writers


# ---------------------------------------------------------------------------
# The earnings view
# ---------------------------------------------------------------------------


class TestConnectEarnings:
    def test_the_fee_arithmetic_is_shown_per_sale(self, db, make_user):
        creator = make_user(role="creator")
        _connect_txn(db, creator.id)
        rows = earnings.list_connect_earnings(db, creator_user_id=creator.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.sale_amount_cents == 10000
        assert row.platform_fee_cents == 800
        assert row.processing_fee_cents == 200
        assert row.creator_amount_cents == 9000
        # The three parts account for the sale exactly.
        assert (
            row.platform_fee_cents
            + row.processing_fee_cents
            + row.creator_amount_cents
        ) == row.sale_amount_cents

    def test_a_zero_percent_creator_receives_gross_less_the_stripe_fee(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        _connect_txn(
            db, creator.id, platform_fee_basis_points=0, platform_fee_cents=0,
            net_creator_amount_cents=10000, net_platform_amount_cents=0,
            transfer_amount_cents=9800,
        )
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        assert row.platform_fee_cents == 0
        assert row.processing_fee_cents == 200
        assert row.creator_amount_cents == 9800

    def test_manual_sales_are_not_included(self, db, make_user):
        """Kept apart because FC owes nothing by hand on a Connect sale."""
        creator = make_user(role="creator")
        _manual_txn(db, creator.id)
        assert earnings.list_connect_earnings(db, creator_user_id=creator.id) == []

    def test_another_creators_sales_are_not_included(self, db, make_user):
        mine = make_user(role="creator")
        theirs = make_user(role="creator")
        _connect_txn(db, theirs.id)
        assert earnings.list_connect_earnings(db, creator_user_id=mine.id) == []

    @pytest.mark.parametrize("status, label", [
        (ConnectTransferStatus.awaiting_payment.value, "Waiting for payment"),
        (ConnectTransferStatus.pending.value, "Preparing payout"),
        (ConnectTransferStatus.sent.value, "Sent to Stripe"),
        (ConnectTransferStatus.failed.value, "Needs attention"),
        (ConnectTransferStatus.partially_reversed.value, "Partly refunded"),
        (ConnectTransferStatus.reversed.value, "Refunded"),
    ])
    def test_each_status_gets_plain_wording(self, db, make_user, status, label):
        creator = make_user(role="creator")
        extra = {}
        if status in (
            ConnectTransferStatus.partially_reversed.value,
            ConnectTransferStatus.reversed.value,
        ):
            extra["reversed_transfer_amount_cents"] = 9000
        _connect_txn(db, creator.id, connect_transfer_status=status, **extra)
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        assert row.status_label == label

    def test_sent_does_not_say_paid(self, db, make_user):
        """A completed transfer reaches the creator's Stripe balance, not their
        bank. The wording must not claim otherwise."""
        creator = make_user(role="creator")
        _connect_txn(db, creator.id)
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        assert row.status_label == "Sent to Stripe"
        assert "paid" not in row.status_label.lower()

    def test_outstanding_recovery_reads_as_needs_attention(self, db, make_user):
        """And as nothing more specific. A creator being chased for money should
        hear it from a person, not read an amount in a table."""
        creator = make_user(role="creator")
        _connect_txn(
            db, creator.id,
            connect_recovery_state=ConnectRecoveryState.required.value,
            connect_unrecovered_amount_cents=9000,
        )
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        assert row.status_label == "Needs attention"

    def test_an_unknown_fee_is_not_reported_as_zero(self, db, make_user):
        """Zero would be a lie about a real cost."""
        creator = make_user(role="creator")
        _connect_txn(
            db, creator.id, processing_fee_cents=None,
            transfer_amount_cents=None, provider_transfer_id=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        assert row.processing_fee_cents is None
        assert row.creator_amount_cents is None
        assert row.amount_is_estimate is True

    def test_a_row_exposes_no_stripe_ids_or_recovery_internals(self, db, make_user):
        creator = make_user(role="creator")
        _connect_txn(
            db, creator.id,
            connect_recovery_state=ConnectRecoveryState.required.value,
            connect_unrecovered_amount_cents=9000,
            reversal_last_error="balance_insufficient: acct_1Secret",
        )
        row = earnings.list_connect_earnings(db, creator_user_id=creator.id)[0]
        fields = {f: getattr(row, f) for f in row.__dataclass_fields__}
        rendered = " ".join(str(v) for v in fields.values())
        assert ACCT not in rendered
        assert "tr_" not in rendered
        assert "acct_" not in rendered
        assert "balance_insufficient" not in rendered
        for forbidden in (
            "connect_destination_account_id", "provider_transfer_id",
            "connect_unrecovered_amount_cents", "reversal_last_error",
        ):
            assert forbidden not in fields

    def test_the_summary_totals_the_rows(self, db, make_user):
        creator = make_user(role="creator")
        _connect_txn(db, creator.id)
        _connect_txn(
            db, creator.id,
            connect_transfer_status=ConnectTransferStatus.pending.value,
            transfer_amount_cents=None, provider_transfer_id=None,
        )
        rows = earnings.list_connect_earnings(db, creator_user_id=creator.id)
        summary = earnings.summarise(rows, currency="AUD")

        assert summary.row_count == 2
        assert summary.sale_total_cents == 20000
        assert summary.platform_fee_total_cents == 1600
        assert summary.processing_fee_total_cents == 400
        assert summary.creator_total_cents == 18000
        assert summary.sent_total_cents == 9000
        assert summary.awaiting_total_cents == 9000

    def test_an_unpriced_row_contributes_nothing_to_the_totals(self, db, make_user):
        """A partial sum presented as a total would be wrong in the one
        direction that matters."""
        creator = make_user(role="creator")
        _connect_txn(
            db, creator.id, processing_fee_cents=None,
            transfer_amount_cents=None, provider_transfer_id=None,
            connect_transfer_status=ConnectTransferStatus.pending.value,
        )
        rows = earnings.list_connect_earnings(db, creator_user_id=creator.id)
        summary = earnings.summarise(rows, currency="AUD")
        assert summary.row_count == 1
        assert summary.creator_total_cents == 0
        assert summary.processing_fee_total_cents == 0


class TestManualEarningsUnchanged:
    def test_a_connect_sale_is_absent_from_the_manual_pending_total(
        self, db, make_user,
    ):
        """The manual figure means "FC owes this by hand". A Connect sale does
        not belong in it, and its ``payout_status`` keeps it out."""
        creator = make_user(role="creator")
        manual = _manual_txn(db, creator.id)
        connect = _connect_txn(db, creator.id)

        pending = [
            t for t in db.query(PaymentTransaction).filter(
                PaymentTransaction.creator_user_id == creator.id,
            ).all()
            if t.payout_status == PayoutStatus.pending
        ]
        assert [t.id for t in pending] == [manual.id]
        assert connect.payout_status == PayoutStatus.not_applicable
