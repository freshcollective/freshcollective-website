"""Money Fresh Collective is owed back, made visible to an operator.

A creator may refund their own sale after the Connect transfer has gone
out. The member's refund commits first and is never contingent on
recovery, so when the connected account cannot cover the clawback the
row records ``connect_recovery_state = required`` with the exact
shortfall. Correct — and also the moment FC is owed money by one of its
own creators, which until now lived only in a log line and a sweeper
report.

These cover the read, the grouping, and the two ways it clears. Nothing
here touches the reversal or the retry schedule.
"""

from __future__ import annotations

import uuid

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
from app.services import connect_recovery_watch as watch


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _owed(db, creator_id, *, cents=151, currency="AUD", **overrides):
    """A refunded Connect sale whose clawback did not complete."""
    values = {
        "id": _uid("txn"),
        "transaction_type": PaymentTransactionType.member_payment_option_purchase,
        "status": PaymentTransactionStatus.refunded,
        "payment_provider": PaymentProvider.stripe,
        "creator_user_id": creator_id,
        "currency": currency,
        "gross_amount_cents": 200,
        "platform_fee_basis_points": 800,
        "platform_fee_cents": 16,
        "net_creator_amount_cents": 184,
        "processing_fee_cents": 33,
        "transfer_amount_cents": 151,
        "payout_model": PayoutModel.connect.value,
        "connect_destination_account_id": "acct_1LiveCreator",
        "provider_transfer_id": _uid("tr"),
        "connect_transfer_status": ConnectTransferStatus.sent.value,
        "payout_status": PayoutStatus.not_applicable,
        "connect_recovery_state": ConnectRecoveryState.required.value,
        "connect_unrecovered_amount_cents": cents,
        "stripe_mode": "test",
    }
    values.update(overrides)
    row = PaymentTransaction(**values)
    db.add(row)
    db.commit()
    return row


class TestWhatIsSurfaced:
    def test_an_unrecovered_refund_is_reported(self, db, make_user):
        creator = make_user(role="creator")
        _owed(db, creator.id, cents=151)

        [row] = watch.outstanding_recoveries(db)

        assert row.creator_user_id == creator.id
        assert row.outstanding_cents == 151
        assert row.transaction_count == 1
        assert row.currency == "AUD"

    def test_a_single_transaction_carries_its_id_for_a_direct_link(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        txn = _owed(db, creator.id)

        [row] = watch.outstanding_recoveries(db)

        assert row.sample_transaction_id == txn.id

    def test_several_sales_aggregate_per_creator(self, db, make_user):
        creator = make_user(role="creator")
        _owed(db, creator.id, cents=151)
        _owed(db, creator.id, cents=349)

        [row] = watch.outstanding_recoveries(db)

        assert row.outstanding_cents == 500
        assert row.transaction_count == 2
        assert row.sample_transaction_id is None, (
            "an admin with two outstanding sales should go to the list, not "
            "to one of them"
        )

    def test_currencies_are_never_added_together(self, db, make_user):
        """Summing cents across currencies produces a number that is not
        money."""
        creator = make_user(role="creator")
        _owed(db, creator.id, cents=151, currency="AUD")
        _owed(db, creator.id, cents=200, currency="NZD")

        rows = watch.outstanding_recoveries(db)

        assert {(r.currency, r.outstanding_cents) for r in rows} == {
            ("AUD", 151), ("NZD", 200),
        }

    def test_the_largest_debt_comes_first(self, db, make_user):
        small = make_user(role="creator")
        large = make_user(role="creator")
        _owed(db, small.id, cents=100)
        _owed(db, large.id, cents=9000)

        rows = watch.outstanding_recoveries(db)

        assert [r.creator_user_id for r in rows] == [large.id, small.id]


class TestWhatIsNot:
    def test_a_recovered_row_disappears(self, db, make_user):
        """One of the two ways the item clears itself."""
        creator = make_user(role="creator")
        row = _owed(db, creator.id)
        assert len(watch.outstanding_recoveries(db)) == 1

        row.connect_recovery_state = ConnectRecoveryState.recovered.value
        row.connect_unrecovered_amount_cents = 0
        db.commit()

        assert watch.outstanding_recoveries(db) == []

    def test_a_zero_outstanding_amount_disappears(self, db, make_user):
        """The other way, independently of the state column."""
        creator = make_user(role="creator")
        row = _owed(db, creator.id)

        row.connect_unrecovered_amount_cents = 0
        db.commit()

        assert watch.outstanding_recoveries(db) == []

    def test_a_healthy_connect_sale_is_not_listed(self, db, make_user):
        creator = make_user(role="creator")
        _owed(
            db, creator.id,
            status=PaymentTransactionStatus.succeeded,
            connect_recovery_state=ConnectRecoveryState.none.value,
            connect_unrecovered_amount_cents=0,
        )

        assert watch.outstanding_recoveries(db) == []

    def test_a_manual_row_is_never_listed(self, db, make_user):
        creator = make_user(role="creator")
        _owed(
            db, creator.id,
            payout_model=PayoutModel.manual.value,
            connect_destination_account_id=None,
            provider_transfer_id=None,
            connect_transfer_status=None,
            transfer_amount_cents=None,
            payout_status=PayoutStatus.pending,
            connect_recovery_state=ConnectRecoveryState.none.value,
            connect_unrecovered_amount_cents=0,
        )

        assert watch.outstanding_recoveries(db) == []

    def test_the_schema_will_not_even_store_a_manual_recovery(self, db, make_user):
        """``ck_payment_transactions_recovery_requires_connect`` makes the
        dangerous combination unstorable, so the filter above is a second
        line rather than the only one."""
        import pytest
        from sqlalchemy.exc import IntegrityError

        creator = make_user(role="creator")
        with pytest.raises(IntegrityError):
            _owed(
                db, creator.id,
                payout_model=PayoutModel.manual.value,
                connect_destination_account_id=None,
                provider_transfer_id=None,
                connect_transfer_status=None,
                transfer_amount_cents=None,
                payout_status=PayoutStatus.pending,
            )
        db.rollback()


class TestItIsBroaderThanTheSweeper:
    def test_a_row_the_sweeper_will_never_retry_is_still_surfaced(
        self, db, make_user,
    ):
        """``_claim_ids`` also requires a transfer id and a status other
        than ``reversed``, because it decides whether to ask Stripe again.
        A row it has stopped picking up is not resolved — it needs a human
        sooner, since nothing automatic will clear it."""
        creator = make_user(role="creator")
        _owed(
            db, creator.id,
            connect_transfer_status=ConnectTransferStatus.reversed.value,
            reversed_transfer_amount_cents=151,
        )

        rows = watch.outstanding_recoveries(db)

        assert len(rows) == 1
        assert rows[0].outstanding_cents == 151


class TestItChangesNothing:
    def test_reading_never_writes(self, db, make_user):
        creator = make_user(role="creator")
        row = _owed(db, creator.id)

        watch.outstanding_recoveries(db)
        watch.outstanding_recoveries(db)
        db.refresh(row)

        assert row.connect_recovery_state == ConnectRecoveryState.required.value
        assert row.connect_unrecovered_amount_cents == 151
        assert row.reversal_attempt_count == 0


class TestTheOverviewPayload:
    def _overview(self, db, admin):
        from app.admin.routes import get_platform_overview

        return get_platform_overview(_=admin, db=db)

    def test_the_admin_sees_the_creator_and_the_amount(self, db, make_user):
        admin = make_user(role="admin")
        creator = make_user(role="creator", name="Ada Lovelace")
        _owed(db, creator.id, cents=151)

        [row] = self._overview(db, admin).connect_recovery_outstanding

        assert row.creator_name == "Ada Lovelace"
        assert row.outstanding_cents == 151
        assert row.currency == "AUD"

    def test_nothing_owed_is_an_empty_list(self, db, make_user):
        admin = make_user(role="admin")

        assert self._overview(db, admin).connect_recovery_outstanding == []
