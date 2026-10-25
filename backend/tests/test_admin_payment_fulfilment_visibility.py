"""Blocked fulfilments have to be findable.

``fulfilment_status`` has existed since the shared fulfilment service
landed, and five handlers write ``blocked`` to it — a missing Pathway, a
malformed snapshot, a resolver error, a failed validation, and now a
buyer whose eligibility changed mid-checkout. Nothing read it. The enum
docstring said "marked so operational tooling can surface it"; no
tooling did, so an unfulfilled purchase was discoverable only in the
logs.

These tests pin the three read paths that fix that, and the one
boundary that was deliberately kept: the ledger still exposes no Stripe
provider IDs, because it is a reporting surface and not a debugging one
(``test_payments_ledger.test_ledger_row_shape_omits_stripe_ids``). The
Stripe handle an operator needs lives on ``GET /api/admin/payments``,
which is the endpoint designed to carry it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.admin.routes import get_payments_ledger, list_payments
from app.admin.schemas import LedgerRow, PaymentTransactionOut
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space(status="active")


@pytest.fixture
def admin(make_user):
    return make_user(role="admin")


def _txn(
    db, *, payer, space,
    fulfilment=PaymentFulfilmentStatus.applied,
    status=PaymentTransactionStatus.succeeded,
    gross=5000,
    created_at=None,
    session_id=None,
    intent_id=None,
    stripe_mode="test",
):
    row = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=status,
        fulfilment_status=fulfilment,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=800,
        platform_fee_cents=int(gross * 0.08),
        net_creator_amount_cents=gross - int(gross * 0.08),
        net_platform_amount_cents=int(gross * 0.08),
        payout_status=PayoutStatus.pending,
        stripe_mode=stripe_mode,
        provider_checkout_session_id=session_id,
        provider_payment_intent_id=intent_id,
        created_at=created_at or datetime.utcnow(),
        updated_at=created_at or datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# 1. The field is in the response
# ---------------------------------------------------------------------------


class TestFulfilmentStatusIsReturned:

    def test_the_schema_carries_it(self):
        assert "fulfilment_status" in PaymentTransactionOut.model_fields

    def test_an_applied_transaction_reports_applied(
        self, db, space, admin, make_user,
    ):
        _txn(db, payer=make_user(), space=space)
        [out] = list_payments(_=admin, db=db)
        assert out.fulfilment_status == "applied"

    def test_a_blocked_transaction_reports_blocked(
        self, db, space, admin, make_user,
    ):
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        [out] = list_payments(_=admin, db=db)
        assert out.fulfilment_status == "blocked"

    def test_payment_and_fulfilment_are_reported_separately(
        self, db, space, admin, make_user,
    ):
        """The distinction the whole change exists for: the money
        arrived and the access did not."""
        _txn(
            db, payer=make_user(), space=space,
            status=PaymentTransactionStatus.succeeded,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        [out] = list_payments(_=admin, db=db)
        assert out.status == "succeeded"
        assert out.fulfilment_status == "blocked"

    def test_every_existing_field_survives(
        self, db, space, admin, make_user,
    ):
        """Preserve all existing transaction information, Stripe
        references included — that is what the operator follows up
        with."""
        txn = _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            session_id="cs_test_abc123",
            intent_id="pi_test_def456",
        )
        [out] = list_payments(_=admin, db=db)
        assert out.id == txn.id
        assert out.provider_checkout_session_id == "cs_test_abc123"
        assert out.provider_payment_intent_id == "pi_test_def456"
        assert out.gross_amount_cents == 5000
        assert out.currency == "AUD"
        assert out.stripe_mode == "test"


# ---------------------------------------------------------------------------
# 2. Filtering
# ---------------------------------------------------------------------------


class TestFilteringByFulfilmentStatus:

    def test_it_returns_only_blocked(self, db, space, admin, make_user):
        blocked = _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        _txn(db, payer=make_user(), space=space)
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.pending,
        )
        out = list_payments(fulfilment_status="blocked", _=admin, db=db)
        assert [o.id for o in out] == [blocked.id]

    @pytest.mark.parametrize(
        "value", ["applied", "pending", "blocked"],
    )
    def test_every_status_is_filterable(
        self, db, space, admin, make_user, value,
    ):
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus(value),
        )
        out = list_payments(fulfilment_status=value, _=admin, db=db)
        assert len(out) == 1
        assert out[0].fulfilment_status == value

    def test_omitting_it_returns_everything(
        self, db, space, admin, make_user,
    ):
        _txn(db, payer=make_user(), space=space)
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        assert len(list_payments(_=admin, db=db)) == 2

    def test_the_two_axes_compose(self, db, space, admin, make_user):
        """The question an operator actually asks: what did we collect
        and fail to deliver?"""
        wanted = _txn(
            db, payer=make_user(), space=space,
            status=PaymentTransactionStatus.succeeded,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        # Blocked but never paid — not money we are holding.
        _txn(
            db, payer=make_user(), space=space,
            status=PaymentTransactionStatus.failed,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        out = list_payments(
            status="succeeded", fulfilment_status="blocked",
            _=admin, db=db,
        )
        assert [o.id for o in out] == [wanted.id]

    def test_an_unknown_value_is_refused_cleanly(
        self, db, space, admin, make_user,
    ):
        """422, not a 500. The column is a Postgres enum, so passing an
        unrecognised value straight through makes the query itself
        fail — which is what the sibling ``status`` and
        ``transaction_type`` filters still do. A tool for finding
        unfulfilled purchases must not fall over on a typo."""
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        with pytest.raises(HTTPException) as exc:
            list_payments(fulfilment_status="not_a_status", _=admin, db=db)
        assert exc.value.status_code == 422
        assert "blocked" in str(exc.value.detail)

    def test_the_known_values_are_listed_in_the_error(
        self, db, admin,
    ):
        with pytest.raises(HTTPException) as exc:
            list_payments(fulfilment_status="nope", _=admin, db=db)
        for value in ("pending", "applied", "blocked"):
            assert value in str(exc.value.detail)


# ---------------------------------------------------------------------------
# 3. The existing filters still work
# ---------------------------------------------------------------------------


class TestExistingFiltersAreUnchanged:

    def test_status_still_filters(self, db, space, admin, make_user):
        ok = _txn(db, payer=make_user(), space=space)
        _txn(
            db, payer=make_user(), space=space,
            status=PaymentTransactionStatus.failed,
        )
        out = list_payments(status="succeeded", _=admin, db=db)
        assert [o.id for o in out] == [ok.id]

    def test_space_still_filters(
        self, db, space, admin, make_user, make_space,
    ):
        mine = _txn(db, payer=make_user(), space=space)
        other = make_space(status="active")
        _txn(db, payer=make_user(), space=other)
        out = list_payments(space_id=space.id, _=admin, db=db)
        assert [o.id for o in out] == [mine.id]

    def test_stripe_mode_still_filters(self, db, space, admin, make_user):
        live = _txn(db, payer=make_user(), space=space, stripe_mode="live")
        _txn(db, payer=make_user(), space=space, stripe_mode="test")
        out = list_payments(stripe_mode="live", _=admin, db=db)
        assert [o.id for o in out] == [live.id]

    def test_transaction_type_still_filters(
        self, db, space, admin, make_user,
    ):
        _txn(db, payer=make_user(), space=space)
        out = list_payments(
            transaction_type="member_payment_option_purchase",
            _=admin, db=db,
        )
        assert len(out) == 1
        assert list_payments(
            transaction_type="refund", _=admin, db=db,
        ) == []

    def test_creator_still_filters(self, db, space, admin, make_user):
        mine = _txn(db, payer=make_user(), space=space)
        out = list_payments(
            creator_user_id=space.creator_id, _=admin, db=db,
        )
        assert [o.id for o in out] == [mine.id]

    def test_ordering_is_still_newest_first(
        self, db, space, admin, make_user,
    ):
        old = _txn(
            db, payer=make_user(), space=space,
            created_at=datetime.utcnow() - timedelta(days=3),
        )
        new = _txn(
            db, payer=make_user(), space=space,
            created_at=datetime.utcnow(),
        )
        out = list_payments(_=admin, db=db)
        assert [o.id for o in out] == [new.id, old.id]


# ---------------------------------------------------------------------------
# 4. Admin-only
# ---------------------------------------------------------------------------


class TestAdminOnly:

    def test_the_dependency_is_the_admin_one(self):
        """The authorisation is a route dependency, so it cannot be
        skipped by calling the function differently — asserted on the
        signature rather than by faking a request."""
        import inspect

        sig = inspect.signature(list_payments)
        dep = sig.parameters["_"].default
        assert getattr(dep, "dependency", None).__name__ == "get_admin_user"

    def test_the_new_filter_did_not_displace_it(self):
        import inspect

        params = list(inspect.signature(list_payments).parameters)
        assert "fulfilment_status" in params
        assert "_" in params

    def test_a_non_admin_is_refused_by_the_dependency(self, db, make_user):
        from app.auth.dependencies import get_admin_user

        with pytest.raises(HTTPException) as exc:
            get_admin_user(current_user=make_user(role="user"))
        assert exc.value.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 5. The ledger boundary is preserved
# ---------------------------------------------------------------------------


class TestTheLedgerStaysAReportingSurface:

    def test_the_ledger_reports_fulfilment(self, db, space, admin, make_user):
        """"Did we deliver what we sold" is a reporting question, so it
        belongs here."""
        _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
        )
        rows = get_payments_ledger(period="this_month", _=admin, db=db)
        assert [r.fulfilment_status for r in rows] == ["blocked"]

    def test_the_ledger_still_leaks_no_provider_ids(self):
        """Unchanged contract. The Stripe handle lives on
        ``/api/admin/payments``, which is admin-gated the same way and
        is the endpoint designed to carry it."""
        forbidden = {
            "provider_checkout_session_id",
            "provider_payment_intent_id",
            "provider_charge_id",
            "provider_invoice_id",
            "provider_subscription_id",
        }
        assert forbidden.isdisjoint(LedgerRow.model_fields.keys())

    def test_a_blocked_transaction_is_reachable_from_both(
        self, db, space, admin, make_user,
    ):
        """Together they give the operator the whole picture: the
        ledger says a sale was not delivered, the payments endpoint
        says which Stripe object to go and look at."""
        txn = _txn(
            db, payer=make_user(), space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            intent_id="pi_test_followup",
        )
        ledger = get_payments_ledger(period="this_month", _=admin, db=db)
        assert any(
            r.fulfilment_status == "blocked" for r in ledger
        )
        [detail] = list_payments(
            fulfilment_status="blocked", _=admin, db=db,
        )
        assert detail.id == txn.id
        assert detail.provider_payment_intent_id == "pi_test_followup"
