"""The database's own guarantees about discount codes.

Application validation can be bypassed — by a future endpoint, a script,
a console. These assert the guarantees that hold regardless: a malformed
code cannot be stored, two Creators can both own FAMILY50 while neither
can collide with themselves, and a replayed redemption collides instead
of double-counting.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

import app.models.community_care  # noqa: F401
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_code(db, space, **kw) -> DiscountCode:
    base = dict(
        id=_uid("dc"), space_id=space.id, code="FAMILY50",
        discount_type="percentage", percent_bps=5000,
        is_active=True, redemption_count=0, scope_kind="space",
    )
    base.update(kw)
    row = DiscountCode(**base)
    db.add(row)
    db.flush()
    return row


class TestUniquenessIsPerCollective:
    def test_two_collectives_may_both_run_family50(self, db, make_space):
        """Codes belong to a Creator, not to the platform."""
        a, b = make_space(), make_space()

        make_code(db, a, code="FAMILY50")
        make_code(db, b, code="FAMILY50")
        db.flush()

        assert db.query(DiscountCode).filter(
            DiscountCode.code == "FAMILY50").count() == 2

    def test_one_collective_cannot_duplicate_its_own_code(self, db, make_space):
        space = make_space()
        make_code(db, space, code="FAMILY50")

        with pytest.raises(IntegrityError):
            make_code(db, space, code="FAMILY50")
            db.flush()


class TestTheShapeConstraints:
    def test_a_percentage_code_cannot_also_carry_an_amount(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), discount_type="percentage",
                      percent_bps=5000, amount_cents=500)

    def test_a_percentage_code_must_carry_a_percentage(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), discount_type="percentage",
                      percent_bps=None)

    @pytest.mark.parametrize("bps", [0, -1, 10001])
    def test_a_percentage_must_be_within_range(self, db, make_space, bps):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), discount_type="percentage", percent_bps=bps)

    def test_a_fixed_code_needs_an_amount_and_a_currency(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), discount_type="fixed_amount",
                      percent_bps=None, amount_cents=5000, currency=None)

    def test_a_valid_fixed_code_stores(self, db, make_space):
        row = make_code(db, make_space(), code="TAKE50OFF",
                        discount_type="fixed_amount", percent_bps=None,
                        amount_cents=5000, currency="AUD")
        assert row.amount_cents == 5000

    def test_an_unknown_discount_type_is_refused(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), discount_type="buy_one_get_one",
                      percent_bps=None)

    def test_a_zero_or_negative_redemption_limit_is_refused(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), max_redemptions=0)

    def test_an_option_scope_must_name_an_option(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), scope_kind="payment_option", scope_id=None)

    def test_a_space_scope_must_not_name_one(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_code(db, make_space(), scope_kind="space", scope_id="po_x")


def make_txn(db, space) -> PaymentTransaction:
    """A real transaction row — the redemption ledger's FK is genuine,
    so fabricated ids are refused (which is itself worth knowing)."""
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=15300,
        platform_fee_basis_points=0,
        platform_fee_cents=0,
        net_creator_amount_cents=15300,
        net_platform_amount_cents=0,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(txn)
    db.flush()
    return txn


class TestTheRedemptionLedger:
    def _redemption(self, db, code, space, **kw):
        base = dict(
            id=_uid("dr"), discount_code_id=code.id, space_id=space.id,
            original_amount_cents=30600, discount_amount_cents=15300,
            final_amount_cents=15300, currency="AUD",
            payment_transaction_id=make_txn(db, space).id,
        )
        base.update(kw)
        row = DiscountRedemption(**base)
        db.add(row)
        db.flush()
        return row

    def test_the_amounts_must_balance(self, db, make_space):
        space = make_space()
        code = make_code(db, space)
        with pytest.raises(IntegrityError):
            self._redemption(db, code, space, final_amount_cents=999)

    def test_exactly_one_purchase_reference_is_required(self, db, make_space):
        space = make_space()
        code = make_code(db, space)
        with pytest.raises(IntegrityError):
            self._redemption(db, code, space,
                             payment_transaction_id=None, purchase_plan_id=None)

    def test_both_references_at_once_is_refused(self, db, make_space):
        space = make_space()
        code = make_code(db, space)
        with pytest.raises(IntegrityError):
            self._redemption(db, code, space,
                             payment_transaction_id=make_txn(db, space).id,
                             purchase_plan_id=_uid("plan"))

    def test_the_same_transaction_cannot_redeem_a_code_twice(self, db, make_space):
        """The webhook-replay guard, at the database level."""
        space = make_space()
        code = make_code(db, space)
        txn = make_txn(db, space).id

        self._redemption(db, code, space, payment_transaction_id=txn)
        with pytest.raises(IntegrityError):
            self._redemption(db, code, space, payment_transaction_id=txn)

    def test_a_fabricated_purchase_reference_is_refused(self, db, make_space):
        """The FK is real: a redemption cannot point at a purchase that
        does not exist."""
        space = make_space()
        code = make_code(db, space)
        with pytest.raises(IntegrityError):
            self._redemption(db, code, space,
                             payment_transaction_id=_uid("txn_nope"))

    def test_different_purchases_redeem_the_same_code_independently(self, db, make_space):
        space = make_space()
        code = make_code(db, space)

        self._redemption(db, code, space, payment_transaction_id=make_txn(db, space).id)
        self._redemption(db, code, space, payment_transaction_id=make_txn(db, space).id)

        assert db.query(DiscountRedemption).filter(
            DiscountRedemption.discount_code_id == code.id).count() == 2


class TestTheSnapshotColumns:
    def test_payment_transactions_carries_one(self, db):
        from sqlalchemy import inspect
        cols = {c["name"] for c in inspect(db.bind).get_columns("payment_transactions")}
        assert "discount_snapshot_json" in cols
        # Beside the precedent it follows.
        assert "snapshot_grants_json" in cols

    def test_purchase_plans_carries_one(self, db):
        from sqlalchemy import inspect
        cols = {c["name"] for c in inspect(db.bind).get_columns("purchase_plans")}
        assert "discount_snapshot_json" in cols
        assert "snapshot_grants_json" in cols

    def test_both_are_nullable_so_nothing_needs_backfilling(self, db):
        """Some historical transactions legitimately have no grant
        snapshot either; absence means 'not recorded', not 'no discount'."""
        from sqlalchemy import inspect
        for table in ("payment_transactions", "purchase_plans"):
            col = next(
                c for c in inspect(db.bind).get_columns(table)
                if c["name"] == "discount_snapshot_json"
            )
            assert col["nullable"] is True
