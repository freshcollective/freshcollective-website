"""``_admin_plan_row`` classification regression for World Management
→ Fresh Collective Plans.

Bug (2026-09-16): every non-purchasable plan was classified as
``plan_type='enterprise'`` and inherited the Organisation-style
presentation on the World Management catalogue (Tailored pricing /
Active organisations metric / Custom pricing model). Founding
Creator was ``is_purchasable=False`` but had an explicit $0 price —
it should render as a normal creator plan with its real
transaction-fee / paid-offers / collective-limit bullets, not as an
enterprise placeholder.

Fix: only classify as ``enterprise`` when
``monthly_price_cents IS NULL`` on the capability (i.e. truly
custom pricing).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import CreatorPlan


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_admin_user, None)


def _ensure_plan(db, *, slug: str, fee_bps: int, price: int, collective_limit: int = 1) -> CreatorPlan:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if plan:
        return plan
    plan = CreatorPlan(
        id=_uid("cp"),
        name=slug.title().replace("-", " "),
        slug=slug,
        monthly_price_cents=price,
        transaction_fee_basis_points=fee_bps,
        collective_limit=collective_limit,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


class TestAdminPlanRowPlanType:
    def test_founding_creator_renders_as_subscription_not_enterprise(
        self, db, client, make_user,
    ):
        """Founding Creator is non-purchasable but has an explicit $0
        price. World Management must classify it as a subscription
        (real creator plan card), not enterprise (Talk-to-us / Active
        organisations)."""
        admin = make_user(role="admin")
        _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0, collective_limit=10)
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.get("/api/admin/creator-plans")
        assert res.status_code == 200, res.text
        rows = {r["slug"]: r for r in res.json()}
        assert "founding-creator" in rows
        founding = rows["founding-creator"]
        assert founding["plan_type"] == "subscription", founding
        assert founding["monthly_price_cents"] == 0
        assert founding["is_purchasable"] is False
        assert founding["paid_offers_enabled"] is True
        assert founding["commercial_use"] is True
        # Transaction fee visible (Community would be None because
        # paid_offers_enabled=False; Founding Creator is 0 explicitly).
        assert founding["transaction_fee_basis_points"] == 0

    def test_organisation_still_renders_as_enterprise(
        self, db, client, make_user,
    ):
        """Organisation retains enterprise/custom-pricing
        presentation — it has ``monthly_price_cents=None`` on the
        capability. Regression: the fix must not accidentally flip
        Organisation into a subscription card."""
        admin = make_user(role="admin")
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.get("/api/admin/creator-plans")
        assert res.status_code == 200, res.text
        rows = {r["slug"]: r for r in res.json()}
        assert "organisation" in rows
        org = rows["organisation"]
        assert org["plan_type"] == "enterprise", org
        assert org["monthly_price_cents"] is None
        assert org["is_purchasable"] is False

    def test_creator_and_pro_render_as_subscription(
        self, db, client, make_user,
    ):
        """Baseline: Creator and Pro remain ``plan_type='subscription'``
        — unchanged by the fix. Any drift here would silently break the
        card copy on the World Management catalogue for the two most
        commonly displayed plans."""
        admin = make_user(role="admin")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _ensure_plan(db, slug="pro", fee_bps=300, price=7900, collective_limit=5)
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.get("/api/admin/creator-plans")
        assert res.status_code == 200, res.text
        rows = {r["slug"]: r for r in res.json()}
        for slug in ("creator", "pro"):
            assert rows[slug]["plan_type"] == "subscription"
            assert rows[slug]["is_purchasable"] is True
            assert rows[slug]["monthly_price_cents"] is not None
