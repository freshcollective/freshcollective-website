"""Authorization + payout-state gate for the creator refund endpoint.

* Creator can refund a transaction whose Space.creator_id == user.id.
* Creator gets 404 on a cross-Collective transaction (existence not leaked).
* Admin can refund any transaction.
* ``payout_status='paid'`` refuses creator with 409, allows admin with
  ``payout_advisory`` flag on the RefundOperation.
* ``payout_status='held'`` behaves the same way.
* Non-Stripe or terminal-status transactions are refused with clear reasons.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.main import app
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.refund_operation import RefundOperation


def _make_txn(db, creator, member, space, **overrides):
    defaults = dict(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=10000,
        platform_fee_basis_points=1000,
        platform_fee_cents=1000,
        net_creator_amount_cents=9000,
        net_platform_amount_cents=1000,
        provider_charge_id=f"ch_{uuid.uuid4().hex[:12]}",
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    defaults.update(overrides)
    txn = PaymentTransaction(**defaults)
    db.add(txn)
    db.commit()
    return txn


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


def _mock_ok(id="re_test", amount=1000):
    return SimpleNamespace(id=id, amount=amount, status="succeeded")


class TestOwnership:
    def test_creator_can_refund_own_transaction(self, db, client, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(db, creator, member, space)
        app.dependency_overrides[get_creator_user] = lambda: creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_mock_ok(),
        ):
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert res.status_code == 200

    def test_cross_collective_returns_404(self, db, client, make_user, make_space):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator_a)
        space_b = make_space(creator=creator_b)
        # Transaction belongs to creator_a's Space.
        txn = _make_txn(db, creator_a, member, space_a)
        # But creator_b tries to refund it.
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
        ) as mock_create:
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert res.status_code == 404
        # Existence not leaked — 404 not 403.
        assert "not found" in res.text.lower()
        mock_create.assert_not_called()

    def test_admin_can_refund_any_transaction(self, db, client, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(db, creator, member, space)
        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_mock_ok(),
        ):
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert res.status_code == 200


class TestPayoutStateGate:
    def test_creator_blocked_when_transaction_paid_out(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(
            db, creator, member, space,
            payout_status=PayoutStatus.paid,
        )
        app.dependency_overrides[get_creator_user] = lambda: creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
        ) as mock_create:
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert res.status_code == 409
        assert "paid out" in res.text.lower()
        mock_create.assert_not_called()

    def test_admin_allowed_when_paid_with_payout_advisory(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(
            db, creator, member, space,
            payout_status=PayoutStatus.paid,
        )
        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_mock_ok(id="re_override"),
        ):
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "error_correction"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["payout_advisory"] == "post_payout_manual_recovery_required"
        # And it's persisted on the RefundOperation.
        op = db.query(RefundOperation).filter(
            RefundOperation.payment_transaction_id == txn.id,
        ).first()
        assert op is not None
        assert op.payout_advisory == "post_payout_manual_recovery_required"

    def test_creator_blocked_when_transaction_held(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(
            db, creator, member, space,
            payout_status=PayoutStatus.held,
        )
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            f"/api/creator/payments/{txn.id}/refund",
            json={"amount_cents": 1000, "reason": "member_request"},
        )
        assert res.status_code == 409

    def test_pending_transaction_allows_creator_refund(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(db, creator, member, space)  # payout_status=pending default
        app.dependency_overrides[get_creator_user] = lambda: creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_mock_ok(),
        ):
            res = client.post(
                f"/api/creator/payments/{txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert res.status_code == 200


class TestRefundabilityChecks:
    def test_non_stripe_transaction_refused(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(
            db, creator, member, space,
            payment_provider=PaymentProvider.manual,
        )
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            f"/api/creator/payments/{txn.id}/refund",
            json={"amount_cents": 1000, "reason": "member_request"},
        )
        assert res.status_code == 409

    def test_terminal_failed_transaction_refused(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(
            db, creator, member, space,
            status=PaymentTransactionStatus.failed,
        )
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            f"/api/creator/payments/{txn.id}/refund",
            json={"amount_cents": 1000, "reason": "member_request"},
        )
        assert res.status_code == 409

    def test_unknown_reason_refused_with_422(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(db, creator, member, space)
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            f"/api/creator/payments/{txn.id}/refund",
            json={"amount_cents": 1000, "reason": "not_a_valid_reason"},
        )
        assert res.status_code == 422
