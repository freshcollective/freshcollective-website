"""Authorization for the creator plan-cancel endpoint.

The creator-scoped endpoint delegates to the same lifecycle service
as the admin endpoint. Ownership must be enforced server-side;
cross-Collective attempts return 404 (not 403 — existence not leaked).
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
from app.models.access_pass import AccessPass, AccessPassSource, AccessPassStatus, AccessPassType
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EntitlementSource, EntitlementStatus, EventSeries, Pathway, PathwayEntitlement
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as agr
from app.services.purchase_fulfilment import (
    AccessPassIntent, EntitlementIntent, FulfilmentIntent, serialise_intent,
)


def _uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_active_plan(db, creator, member, space):
    now = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=now, status="published", published_at=now,
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}", title="Life", status="active",
    )
    db.add_all([series, pathway])
    db.flush()
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken", payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id, name="W3",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add_all([opt, sched])
    db.flush()
    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=None),),
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=now, valid_until=None,
            total_credits=None, credits_per_week=None,
            eligible_pathway_id=None, eligible_series_id=series.id,
            grants_pathway_id=pathway.id,
        ),),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id, payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id, creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000, installments_expected=3,
        installments_paid=1, total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=f"cus_{uuid.uuid4().hex[:8]}",
        provider_subscription_schedule_id=f"sub_sched_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan)
    db.flush()
    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id, source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now, purchase_plan_id=plan.id,
    )
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=now, eligible_series_id=series.id,
        grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
    )
    db.add_all([ent, ap])
    db.flush()
    agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=None, granted_at=now,
    )
    db.commit()
    return plan


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


class TestCreatorPlanCancelAuthz:
    def test_creator_can_cancel_own_plan(self, db, client, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        plan = _make_active_plan(db, creator, member, space)
        app.dependency_overrides[get_creator_user] = lambda: creator

        with patch(
            "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
            side_effect=lambda plan: None,
        ):
            res = client.post(
                f"/api/creator/purchase-plans/{plan.id}/cancel",
                json={"reason": "creator_cancelled"},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["plan_status"] == "cancelled"
        assert body["plan_transitioned"] is True

    def test_cross_collective_creator_gets_404(self, db, client, make_user, make_space):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator_a)
        plan = _make_active_plan(db, creator_a, member, space_a)
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        with patch(
            "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        ) as mock_cancel:
            res = client.post(
                f"/api/creator/purchase-plans/{plan.id}/cancel",
                json={"reason": "creator_cancelled"},
            )
        assert res.status_code == 404
        assert "not found" in res.text.lower()
        mock_cancel.assert_not_called()

    def test_admin_can_cancel_any_plan(self, db, client, make_user, make_space):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        plan = _make_active_plan(db, creator, member, space)
        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        with patch(
            "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
            side_effect=lambda plan: None,
        ):
            res = client.post(
                f"/api/creator/purchase-plans/{plan.id}/cancel",
                json={"reason": "admin_cancelled"},
            )
        assert res.status_code == 200
