"""Cross-Collective isolation for Creator Studio financial surfaces.

Regression coverage for the bug where Payments received /
Payment Plans / billing context leaked across an admin viewer's
Collectives — the endpoints used to filter by
``PaymentTransaction.creator_user_id == current_user.id`` alone,
which conflated "current viewer" with "owner of selected Space".

Scenarios (per approved spec):

* Space is the authoritative query boundary when ``space_slug`` is
  supplied. Legacy creator-wide behaviour is preserved when it's not.
* Normal creator on a Space they don't own → 404 (no existence leak).
* Platform admin may resolve any Space; the query does NOT retain
  ``creator_user_id == current_user.id`` (that would exclude the
  real creator's rows).
* Per-Space billing context resolves the effective fee from the
  Space's creator's active plan — not the viewer's plan. Platform-
  owned Spaces (``Space.creator_id IS NULL``) return zero.
* ``viewer_is_platform_admin`` and ``selected_space_is_platform_owned``
  are independent signals — the endpoint returns both, and the
  frontend uses each for a different rendering decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Space
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


def _make_succeeded_txn(
    db, *, creator, member, space,
    gross_cents: int = 10_000, fee_bps: int = 800,
) -> PaymentTransaction:
    """A ``member_payment_option_purchase`` succeeded Stripe txn — the
    shape counted by ``get_creator_payment_summary`` and returned by
    ``list_creator_payments``."""
    fee_cents = int(gross_cents * fee_bps / 10000)
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=fee_bps,
        platform_fee_cents=fee_cents,
        net_creator_amount_cents=gross_cents - fee_cents,
        net_platform_amount_cents=fee_cents,
        provider_charge_id=f"ch_{uuid.uuid4().hex[:12]}",
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(txn)
    db.commit()
    return txn


def _make_purchase_plan(db, *, member, creator, space) -> PurchasePlan:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="space", attaches_to_id=space.id,
        name="Scoped Plan Option",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=10_000, currency="AUD",
    )
    db.add(opt); db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly x 4",
        schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2500, installment_count=4,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=10_000, currency="AUD",
    )
    db.add(sched); db.flush()
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2500,
        installments_expected=4,
        installments_paid=1,
        total_expected_cents=10_000,
        stripe_interval="week",
        stripe_interval_count=1,
        platform_fee_basis_points=800,
        stripe_mode="test",
        activated_at=datetime.utcnow(),
    )
    db.add(plan)
    db.commit()
    return plan


@pytest.fixture
def known_plan(db):
    """Seed a distinctive CreatorPlan so ``resolve_fee_context`` returns
    a value we can assert (300 bps = 3%)."""
    plan = (
        db.query(CreatorPlan).filter(CreatorPlan.slug == "test-pro-3pct").first()
    )
    if plan is None:
        plan = CreatorPlan(
            id="cp_test_pro_3pct",
            name="Test Pro 3%",
            slug="test-pro-3pct",
            monthly_price_cents=9900,
            transaction_fee_basis_points=300,
            collective_limit=10,
            is_active=True,
        )
        db.add(plan)
        db.flush()
    return plan


def _grant_subscription(db, user, plan):
    sub = CreatorSubscription(
        id=_uid("csub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active,
        starts_at=datetime.utcnow(),
        source="manual_grant",
    )
    db.add(sub)
    db.commit()
    return sub


class TestListPaymentsSpaceScoping:
    """``GET /api/creator/payments?space_slug=…`` isolation."""

    def test_owner_sees_only_own_space_transactions(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        _make_succeeded_txn(db, creator=creator, member=member, space=space_a)
        _make_succeeded_txn(db, creator=creator, member=member, space=space_b)
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.get(f"/api/creator/payments?space_slug={space_a.slug}")
        assert res.status_code == 200
        rows = res.json()
        assert len(rows) == 1
        assert rows[0]["space_id"] == space_a.id

    def test_admin_sees_transactions_from_another_creators_space(
        self, db, client, make_user, make_space,
    ):
        # Regression: admin viewing another creator's Space must NOT
        # be filtered by ``creator_user_id == admin.id`` (that used to
        # return an empty list — the original cross-Collective bug).
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_succeeded_txn(db, creator=creator, member=member, space=space)

        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.get(f"/api/creator/payments?space_slug={space.slug}")
        assert res.status_code == 200
        rows = res.json()
        assert len(rows) == 1
        assert rows[0]["space_id"] == space.id

    def test_cross_collective_creator_gets_404(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator_a)
        _make_succeeded_txn(db, creator=creator_a, member=member, space=space_a)

        # creator_b tries to view creator_a's Space.
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        res = client.get(f"/api/creator/payments?space_slug={space_a.slug}")
        # 404 rather than 403 — existence must not be leaked.
        assert res.status_code == 404

    def test_unknown_slug_returns_404(self, db, client, make_user):
        creator = make_user(role="creator")
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/payments?space_slug=this-space-does-not-exist")
        assert res.status_code == 404

    def test_omitting_slug_preserves_legacy_creator_wide_behaviour(
        self, db, client, make_user, make_space,
    ):
        # Without a slug, we keep the historical creator_user_id filter
        # so a creator with multiple Spaces still sees the union of
        # their own transactions.
        creator = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        _make_succeeded_txn(db, creator=creator, member=member, space=space_a)
        _make_succeeded_txn(db, creator=creator, member=member, space=space_b)
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.get("/api/creator/payments")
        assert res.status_code == 200
        assert len(res.json()) == 2


class TestSummarySpaceScoping:
    """``GET /api/creator/payments/summary?space_slug=…`` — summary must
    always share the row-list's scope."""

    def test_admin_summary_reflects_scoped_space_only(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        other_creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        other_space = make_space(creator=other_creator)
        _make_succeeded_txn(
            db, creator=creator, member=member, space=space, gross_cents=5000,
        )
        # Noise in a different Space to prove the summary respects scope.
        _make_succeeded_txn(
            db, creator=other_creator, member=member, space=other_space,
            gross_cents=99_000,
        )

        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.get(f"/api/creator/payments/summary?space_slug={space.slug}")
        assert res.status_code == 200
        body = res.json()
        assert body["total_gross_amount_cents"] == 5000
        assert body["succeeded_count"] == 1

    def test_cross_collective_summary_returns_404(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        space_a = make_space(creator=creator_a)
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        res = client.get(f"/api/creator/payments/summary?space_slug={space_a.slug}")
        assert res.status_code == 404


class TestPaymentPlansSpaceScoping:
    """``GET /api/creator/payment-plans?space_slug=…`` isolation."""

    def test_admin_sees_plans_in_another_creators_space(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        _make_purchase_plan(db, member=member, creator=creator, space=space)

        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.get(f"/api/creator/payment-plans?space_slug={space.slug}")
        assert res.status_code == 200
        rows = res.json()
        assert len(rows) == 1
        assert rows[0]["space_id"] == space.id

    def test_owner_sees_only_scoped_space_plans(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space_a = make_space(creator=creator)
        space_b = make_space(creator=creator)
        _make_purchase_plan(db, member=member, creator=creator, space=space_a)
        _make_purchase_plan(db, member=member, creator=creator, space=space_b)

        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.get(f"/api/creator/payment-plans?space_slug={space_a.slug}")
        assert res.status_code == 200
        rows = res.json()
        assert len(rows) == 1
        assert rows[0]["space_id"] == space_a.id

    def test_cross_collective_creator_gets_404(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        space_a = make_space(creator=creator_a)
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        res = client.get(f"/api/creator/payment-plans?space_slug={space_a.slug}")
        assert res.status_code == 404


class TestBillingContextEndpoint:
    """``GET /api/creator/spaces/{slug}/billing-context`` — the frontend
    depends on the four independent signals returned here."""

    def test_admin_viewer_sees_space_creators_fee_not_own_fee(
        self, db, client, make_user, make_space, known_plan,
    ):
        # Set the Space's creator on the 300-bps test plan. Admin has
        # no subscription. Endpoint must return 300 (Space's creator's
        # fee), NOT the fallback / admin viewer's fee.
        creator = make_user(role="creator")
        _grant_subscription(db, creator, known_plan)
        space = make_space(creator=creator)
        admin = make_user(role="admin")
        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.get(f"/api/creator/spaces/{space.slug}/billing-context")
        assert res.status_code == 200
        body = res.json()
        assert body["effective_transaction_fee_basis_points"] == 300
        assert body["selected_space_is_platform_owned"] is False
        assert body["viewer_is_platform_admin"] is True
        assert body["viewer_is_space_owner"] is False
        assert body["space_creator_user_id"] == creator.id

    def test_platform_owned_space_returns_zero_fee(
        self, db, client, make_user, make_space,
    ):
        admin = make_user(role="admin")
        # Space.creator_id IS NULL is the canonical "platform-owned"
        # discriminator. Bypass make_space's default so we can null it.
        space = Space(
            id=_uid("s"),
            slug=f"platform-space-{uuid.uuid4().hex[:8]}",
            name="Platform Space",
            status="active",
            creator_id=None,
        )
        db.add(space)
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: admin

        res = client.get(f"/api/creator/spaces/{space.slug}/billing-context")
        assert res.status_code == 200
        body = res.json()
        assert body["selected_space_is_platform_owned"] is True
        assert body["effective_transaction_fee_basis_points"] == 0
        assert body["space_creator_user_id"] is None

    def test_owner_viewing_own_space_sets_viewer_is_space_owner(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        app.dependency_overrides[get_creator_user] = lambda: creator

        res = client.get(f"/api/creator/spaces/{space.slug}/billing-context")
        assert res.status_code == 200
        body = res.json()
        assert body["viewer_is_space_owner"] is True
        assert body["viewer_is_platform_admin"] is False
        assert body["selected_space_is_platform_owned"] is False

    def test_unknown_slug_returns_404(self, db, client, make_user):
        creator = make_user(role="creator")
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/spaces/no-such-space/billing-context")
        assert res.status_code == 404

    def test_cross_collective_creator_gets_404(
        self, db, client, make_user, make_space,
    ):
        creator_a = make_user(role="creator")
        creator_b = make_user(role="creator")
        space_a = make_space(creator=creator_a)
        app.dependency_overrides[get_creator_user] = lambda: creator_b

        res = client.get(f"/api/creator/spaces/{space_a.slug}/billing-context")
        assert res.status_code == 404
