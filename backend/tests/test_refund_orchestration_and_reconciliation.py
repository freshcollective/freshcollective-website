"""End-to-end tests for the creator refund orchestration + reconciliation.

Covers:

* happy path: creator submits, Stripe accepts, RefundOperation reaches
  ``accepted``, webhook (via correlator) transitions to
  ``webhook_confirmed``;
* API-post-Stripe update is conditional — does NOT regress a
  ``webhook_confirmed`` set by the correlator during the race;
* in-flight blocker: second refund attempt while one is active → 409;
* reconciliation (Phase A): stale in_flight replayed with SAME
  idempotency key, adopts cached Refund, transitions to ``accepted``;
* reconciliation of an ``accepted`` op via ``Refund.retrieve``
  transitions it to ``webhook_confirmed`` when Stripe reports
  ``status='succeeded'``;
* no new refund is allowed until reconciliation completes;
* Stripe 4xx (over-refund) surfaces as 409 with ``refused`` op;
* over-refund guard rejects ledger-side without Stripe call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import Space
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationReason,
    RefundOperationTerminalStatus,
    StripeIdentifierKind,
)
from app.services import refund_reconciliation as _rec
from app.services.refund_webhook_correlator import correlate_refund_operations


def _make_creator_owned_txn(db, make_user, make_space):
    creator = make_user(role="creator")
    member = make_user()
    space = make_space(creator=creator)
    txn = PaymentTransaction(
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
    db.add(txn)
    db.flush()
    db.commit()
    return SimpleNamespace(creator=creator, member=member, space=space, txn=txn)


@pytest.fixture
def client(db):
    """TestClient with dep-overrides pointing at the test session."""
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


def _fake_refund(*, id="re_test", amount=3000):
    return SimpleNamespace(id=id, amount=amount, status="succeeded")


class TestHappyPath:
    def test_creator_refund_accepted_then_webhook_confirms(self, db, client, make_user, make_space):
        s = _make_creator_owned_txn(db, make_user, make_space)
        app.dependency_overrides[get_creator_user] = lambda: s.creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_fake_refund(id="re_ok_1", amount=3000),
        ):
            res = client.post(
                f"/api/creator/payments/{s.txn.id}/refund",
                json={"amount_cents": 3000, "reason": "member_request"},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["terminal_status"] == "accepted"
        assert body["stripe_refund_id"] == "re_ok_1"
        assert body["refundable_before_cents"] == 10000
        assert body["refundable_after_cents"] == 7000

        # RefundOperation persisted.
        op = db.query(RefundOperation).filter(
            RefundOperation.payment_transaction_id == s.txn.id
        ).first()
        assert op is not None
        assert op.terminal_status == "accepted"
        assert op.stripe_refund_id == "re_ok_1"

        # PaymentTransaction refund columns UNCHANGED — webhook is authoritative.
        db.refresh(s.txn)
        assert s.txn.refunded_amount_cents == 0

        # Simulate webhook arrival — correlator transitions to webhook_confirmed.
        charge = {
            "id": s.txn.provider_charge_id,
            "amount_refunded": 3000,
            "refunded": False,
            "refunds": {"data": [{
                "id": "re_ok_1", "amount": 3000,
                "metadata": {"refund_operation_id": op.id},
            }], "has_more": False},
        }
        correlate_refund_operations(
            db, txn=s.txn, charge=charge,
            event_created=None, webhook_event_row_id=None,
        )
        db.commit()
        db.refresh(op)
        assert op.terminal_status == "webhook_confirmed"


class TestInFlightBlock:
    def test_second_refund_while_first_accepted_returns_409(
        self, db, client, make_user, make_space,
    ):
        s = _make_creator_owned_txn(db, make_user, make_space)
        app.dependency_overrides[get_creator_user] = lambda: s.creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            return_value=_fake_refund(id="re_first", amount=1000),
        ):
            r1 = client.post(
                f"/api/creator/payments/{s.txn.id}/refund",
                json={"amount_cents": 1000, "reason": "member_request"},
            )
        assert r1.status_code == 200

        # Second attempt while the first RefundOperation is accepted.
        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
        ) as mock_create:
            r2 = client.post(
                f"/api/creator/payments/{s.txn.id}/refund",
                json={"amount_cents": 500, "reason": "duplicate"},
            )
        assert r2.status_code == 409
        assert "already being processed" in r2.text
        mock_create.assert_not_called()


class TestWebhookBeforeAPIPersistRace:
    def test_webhook_correlator_wins_race_and_api_does_not_regress(
        self, db, client, make_user, make_space,
    ):
        """Simulate: API inserts in_flight; correlator fires (metadata
        match); API's post-Stripe update runs LAST. The conditional
        UPDATE must not regress webhook_confirmed → accepted.
        """
        s = _make_creator_owned_txn(db, make_user, make_space)
        app.dependency_overrides[get_creator_user] = lambda: s.creator

        # Simulate the race by having the mock Stripe call itself
        # trigger the correlator with the new Refund's metadata.
        def fake_create_refund(**kw):
            refund_op_id = kw["refund_operation_id"]
            # Trigger correlator with the Refund payload.
            charge = {
                "id": s.txn.provider_charge_id,
                "amount_refunded": 3000,
                "refunded": False,
                "refunds": {"data": [{
                    "id": "re_race", "amount": 3000,
                    "metadata": {"refund_operation_id": refund_op_id},
                }], "has_more": False},
            }
            correlate_refund_operations(
                db, txn=s.txn, charge=charge,
                event_created=None, webhook_event_row_id=None,
            )
            db.commit()
            return _fake_refund(id="re_race", amount=3000)

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            side_effect=fake_create_refund,
        ):
            res = client.post(
                f"/api/creator/payments/{s.txn.id}/refund",
                json={"amount_cents": 3000, "reason": "member_request"},
            )
        assert res.status_code == 200

        # Op should be webhook_confirmed (correlator won); API's
        # conditional UPDATE was a no-op (rowcount 0).
        op = db.query(RefundOperation).filter(
            RefundOperation.payment_transaction_id == s.txn.id
        ).first()
        assert op.terminal_status == "webhook_confirmed"
        assert op.stripe_refund_id == "re_race"


class TestReconciliationInFlight:
    def test_phase_a_replays_same_idempotency_key(self, db, make_user, make_space):
        s = _make_creator_owned_txn(db, make_user, make_space)
        # Simulate a stale in_flight — server crashed after commit
        # but before Stripe outcome persisted.
        op_id = f"refop_{uuid.uuid4().hex[:12]}"
        op = RefundOperation(
            id=op_id,
            payment_transaction_id=s.txn.id,
            requested_by_user_id=s.creator.id,
            requested_at=datetime.utcnow() - timedelta(minutes=5),
            reason=RefundOperationReason.member_request.value,
            requested_amount_cents=3000,
            expected_cumulative_refunded_amount_cents=3000,
            stripe_identifier_kind=StripeIdentifierKind.charge.value,
            stripe_identifier_value=s.txn.provider_charge_id,
            terminal_status=RefundOperationTerminalStatus.in_flight.value,
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db.add(op)
        db.commit()

        captured = {}

        def fake_create_refund(**kw):
            captured.update(kw)
            return _fake_refund(id="re_reconciled", amount=3000)

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            side_effect=fake_create_refund,
        ):
            new_status = _rec.reconcile_in_flight(db, op)

        db.refresh(op)
        assert new_status == RefundOperationTerminalStatus.accepted.value
        assert op.stripe_refund_id == "re_reconciled"
        assert op.reconciled_at is not None
        # Same idempotency key derived from op.id.
        assert captured["refund_operation_id"] == op_id

    def test_phase_a_returns_cached_4xx_marks_refused(self, db, make_user, make_space):
        s = _make_creator_owned_txn(db, make_user, make_space)
        op_id = f"refop_{uuid.uuid4().hex[:12]}"
        op = RefundOperation(
            id=op_id,
            payment_transaction_id=s.txn.id,
            requested_by_user_id=s.creator.id,
            requested_at=datetime.utcnow() - timedelta(minutes=5),
            reason=RefundOperationReason.member_request.value,
            requested_amount_cents=3000,
            expected_cumulative_refunded_amount_cents=3000,
            stripe_identifier_kind=StripeIdentifierKind.charge.value,
            stripe_identifier_value=s.txn.provider_charge_id,
            terminal_status=RefundOperationTerminalStatus.in_flight.value,
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db.add(op)
        db.commit()

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
            side_effect=stripe.InvalidRequestError("already refunded", param=None),
        ):
            new_status = _rec.reconcile_in_flight(db, op)

        db.refresh(op)
        assert new_status == RefundOperationTerminalStatus.refused.value
        assert op.api_error_message is not None


class TestReconciliationAccepted:
    def test_accepted_op_confirmed_via_retrieve(self, db, make_user, make_space):
        s = _make_creator_owned_txn(db, make_user, make_space)
        op = RefundOperation(
            id=f"refop_{uuid.uuid4().hex[:12]}",
            payment_transaction_id=s.txn.id,
            requested_by_user_id=s.creator.id,
            requested_at=datetime.utcnow() - timedelta(minutes=15),
            reason=RefundOperationReason.member_request.value,
            requested_amount_cents=3000,
            expected_cumulative_refunded_amount_cents=3000,
            stripe_identifier_kind=StripeIdentifierKind.charge.value,
            stripe_identifier_value=s.txn.provider_charge_id,
            stripe_refund_id="re_stranded",
            terminal_status=RefundOperationTerminalStatus.accepted.value,
            updated_at=datetime.utcnow() - timedelta(minutes=15),
        )
        db.add(op)
        db.commit()

        fake_charge = SimpleNamespace(
            id=s.txn.provider_charge_id,
            amount_refunded=3000,
            refunded=False,
            refunds=SimpleNamespace(data=[], has_more=False),
        )
        # Emulate .to_dict_recursive() behaviour used by the reconciler.
        def _to_dict():
            return {
                "id": s.txn.provider_charge_id,
                "amount_refunded": 3000,
                "refunded": False,
                "payment_intent": None,
                "refunds": {"data": [], "has_more": False},
            }
        fake_charge.to_dict_recursive = _to_dict

        with patch(
            "app.services.stripe_refund_orchestration.retrieve_refund",
            return_value=SimpleNamespace(
                id="re_stranded", status="succeeded",
                charge=s.txn.provider_charge_id, amount=3000,
            ),
        ), patch(
            "app.services.stripe_refund_orchestration.retrieve_charge",
            return_value=fake_charge,
        ):
            new_status = _rec.reconcile_accepted(db, op)

        db.refresh(op)
        db.refresh(s.txn)
        assert new_status == RefundOperationTerminalStatus.webhook_confirmed.value
        assert op.confirmed_at is not None
        assert op.reconciled_at is not None
        # Ledger force-synced from the fetched Charge.
        assert s.txn.refunded_amount_cents == 3000
        assert s.txn.refunded_platform_fee_cents == 300
        assert s.txn.refunded_creator_amount_cents == 2700


class TestOverRefundGuard:
    def test_ledger_side_over_refund_rejected(self, db, client, make_user, make_space):
        s = _make_creator_owned_txn(db, make_user, make_space)
        app.dependency_overrides[get_creator_user] = lambda: s.creator

        with patch(
            "app.services.stripe_refund_orchestration.create_refund",
        ) as mock_create:
            res = client.post(
                f"/api/creator/payments/{s.txn.id}/refund",
                json={"amount_cents": 20000, "reason": "member_request"},
            )
        assert res.status_code == 409
        assert "exceeds" in res.text.lower() or "refundable" in res.text.lower()
        mock_create.assert_not_called()
