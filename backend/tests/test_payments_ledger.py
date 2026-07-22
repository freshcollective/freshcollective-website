"""
Integration tests for ``GET /api/admin/payments/ledger``.

The endpoint composes ``resolve_period`` (already unit-tested in
``test_periods.py``) with a bulk name lookup. These tests focus on
what's new:

- Period windowing is applied to the DB filter.
- ``stripe_mode`` filter is orthogonal to the period.
- Denormalised names are present.
- No Stripe provider IDs leak into the response shape.
- Ordering is desc by created_at.
- Invalid period → 422.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.admin.routes import get_payments_ledger
from app.admin.schemas import LedgerRow
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)


def _seed_txn(
    db,
    *,
    payer,
    creator,
    space,
    created_at: datetime,
    ttype=PaymentTransactionType.member_collective_purchase,
    status=PaymentTransactionStatus.succeeded,
    stripe_mode: str = "test",
    gross: int = 1_000,
    payout_status: PayoutStatus = PayoutStatus.pending,
    provider: PaymentProvider = PaymentProvider.stripe,
):
    fee = int(gross * 0.08)
    txn = PaymentTransaction(
        id=f"txn_{created_at.strftime('%Y%m%d%H%M%S%f')}_{stripe_mode}_{gross}",
        transaction_type=ttype,
        status=status,
        payment_provider=provider,
        payer_user_id=payer.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=800,
        platform_fee_cents=fee,
        net_creator_amount_cents=gross - fee,
        stripe_mode=stripe_mode,
        payout_status=payout_status,
        created_at=created_at,
    )
    db.add(txn)
    db.flush()
    return txn


# ---------------------------------------------------------------------------


class TestLedgerPeriodWindowing:
    def test_all_time_returns_every_row(self, db, make_user, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        payer = make_user(role="user")
        space = make_space(creator=creator)

        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2020, 1, 1, 12, 0, 0))
        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2026, 7, 5, 12, 0, 0))

        rows = get_payments_ledger(period="all_time", stripe_mode="test", _=admin, db=db)
        assert len(rows) == 2

    def test_this_month_narrows_to_current_month(self, db, make_user, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        payer = make_user(role="user")
        space = make_space(creator=creator)

        # Insert a very old row + a row in the current month. The old row
        # must never appear in a "this_month" result.
        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2020, 1, 1, 12, 0, 0))
        recent_now = datetime.utcnow()
        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=recent_now.replace(hour=6))

        rows = get_payments_ledger(period="this_month", stripe_mode="test", _=admin, db=db)
        # The 2020 row must be filtered out. At least the recent row is present.
        for r in rows:
            assert r.created_at.year >= recent_now.year - 1

    def test_invalid_period_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as excinfo:
            get_payments_ledger(period="last_year", stripe_mode=None, _=admin, db=db)
        assert excinfo.value.status_code == 422


class TestLedgerStripeMode:
    def test_test_mode_excludes_live_rows(self, db, make_user, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        payer = make_user(role="user")
        space = make_space(creator=creator)

        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2026, 7, 5, 12, 0, 0), stripe_mode="test")
        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2026, 7, 6, 12, 0, 0), stripe_mode="live")

        rows_test = get_payments_ledger(period="all_time", stripe_mode="test", _=admin, db=db)
        rows_live = get_payments_ledger(period="all_time", stripe_mode="live", _=admin, db=db)
        assert len(rows_test) == 1
        assert len(rows_live) == 1
        assert rows_test[0].stripe_mode == "test"
        assert rows_live[0].stripe_mode == "live"


class TestLedgerDenormalisation:
    def test_names_inlined(self, db, make_user, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator", name="Lindsey")
        payer = make_user(role="user", name="Simone", email="simone@example.test")
        space = make_space(creator=creator, name="EMBODY")

        _seed_txn(db, payer=payer, creator=creator, space=space,
                  created_at=datetime(2026, 7, 5, 12, 0, 0))

        rows = get_payments_ledger(period="all_time", stripe_mode="test", _=admin, db=db)
        assert len(rows) == 1
        r = rows[0]
        assert r.payer_name == "Simone"
        assert r.payer_email == "simone@example.test"
        assert r.creator_name == "Lindsey"
        assert r.space_name == "EMBODY"
        assert r.pathway_title is None

    def test_ledger_row_shape_omits_stripe_ids(self):
        # Structural check: no field on LedgerRow leaks Stripe or opaque
        # provider IDs. The ledger is not a debugging surface.
        forbidden = {
            "provider_checkout_session_id",
            "provider_payment_intent_id",
            "provider_charge_id",
            "provider_invoice_id",
            "provider_subscription_id",
        }
        assert forbidden.isdisjoint(LedgerRow.model_fields.keys())


class TestLedgerOrdering:
    def test_desc_by_created_at(self, db, make_user, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        payer = make_user(role="user")
        space = make_space(creator=creator)

        for day in (2, 5, 3, 8, 1):
            _seed_txn(db, payer=payer, creator=creator, space=space,
                      created_at=datetime(2026, 7, day, 12, 0, 0))

        rows = get_payments_ledger(period="all_time", stripe_mode="test", _=admin, db=db)
        days = [r.created_at.day for r in rows]
        assert days == sorted(days, reverse=True)


class TestLedgerEmpty:
    def test_no_rows_returns_empty_list(self, db, make_user):
        admin = make_user(role="admin")
        rows = get_payments_ledger(period="all_time", stripe_mode="test", _=admin, db=db)
        assert rows == []
