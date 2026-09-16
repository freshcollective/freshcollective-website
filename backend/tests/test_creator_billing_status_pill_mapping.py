"""Payment setup → Creator billing pill mapping.

Two regression axes:

1. **Backend guarantee**: ``creator_billing_connected`` can only be
   True when the caller's ``CreatorSubscription`` is currently
   ``active`` or ``trialing`` — the query filter enforces it. An
   ended / lapsed / cancelled sub whose ``stripe_subscription_id``
   is still populated on the row CANNOT surface as "Connected".
   This is the invariant Lindsey asked me to verify before deploy.

2. **Frontend guarantee**: the pill rendered on Creator Studio
   Billing must be one of "Connected" / "Not required" / "Not
   connected". Any $0 plan (Founding Creator OR Community) reads
   "Not required" — the historical mislabel where Community
   rendered "Not connected" is closed by the frontend patch made
   alongside this test.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)


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


def _ensure_plan(db, *, slug, fee_bps, price):
    p = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if p:
        return p
    p = CreatorPlan(
        id=_uid("cp"), name=slug.title(), slug=slug,
        monthly_price_cents=price, transaction_fee_basis_points=fee_bps,
        collective_limit=1, is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _sub(db, user, plan, *, source, status, stripe_subscription_id=None, stripe_customer_id=None):
    row = CreatorSubscription(
        id=_uid("sub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=status,
        starts_at=datetime.utcnow(),
        source=source,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def stripe_enabled(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")


# ---------------------------------------------------------------------------
# Backend invariant — the pill's source of truth
# ---------------------------------------------------------------------------


class TestCreatorBillingConnectedSafety:
    """The exact invariant Lindsey asked to verify:
    ``creator_billing_connected=True`` cannot arise from a
    stripe_subscription_id lingering on an ended row."""

    def test_cancelled_sub_with_stripe_ids_does_not_report_connected(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        # Populated Stripe ids simulate a subscription that was
        # once live and later cancelled via ``customer.subscription.deleted``.
        _sub(
            db, creator, plan,
            source="stripe_paid",
            status=CreatorSubscriptionStatus.cancelled,
            stripe_subscription_id="sub_ended_but_id_survives",
            stripe_customer_id="cus_ended",
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["payment_setup"]["creator_billing_connected"] is False

    def test_unpaid_sub_with_stripe_ids_does_not_report_connected(
        self, db, client, make_user, stripe_enabled,
    ):
        """After grace expiry the sub sits at ``status='unpaid'``
        with its Stripe ids intact. Must not read as Connected."""
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(
            db, creator, plan,
            source="stripe_paid",
            status=CreatorSubscriptionStatus.unpaid,
            stripe_subscription_id="sub_unpaid",
            stripe_customer_id="cus_unpaid",
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        assert res.json()["payment_setup"]["creator_billing_connected"] is False

    def test_active_sub_with_cancel_at_period_end_still_reports_connected(
        self, db, client, make_user, stripe_enabled,
    ):
        """``cancel_at_period_end=True`` leaves ``status='active'``
        until Stripe fires ``customer.subscription.deleted`` at
        period end. Billing IS still healthy through the paid-through
        date, so Connected is truthful."""
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        sub = _sub(
            db, creator, plan,
            source="stripe_paid",
            status=CreatorSubscriptionStatus.active,
            stripe_subscription_id="sub_cancel_scheduled",
            stripe_customer_id="cus_cancel_scheduled",
        )
        sub.cancel_at_period_end = True
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        assert res.json()["payment_setup"]["creator_billing_connected"] is True

    def test_active_sub_reports_connected(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(
            db, creator, plan,
            source="stripe_paid",
            status=CreatorSubscriptionStatus.active,
            stripe_subscription_id="sub_active",
            stripe_customer_id="cus_active",
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        assert res.json()["payment_setup"]["creator_billing_connected"] is True


# ---------------------------------------------------------------------------
# Frontend contract — pill mapping shape
# ---------------------------------------------------------------------------


class TestFrontendBillingPillMapping:
    """The Creator Studio Billing page turns
    ``creator_billing_connected`` + ``current_plan.monthly_price_cents``
    into a three-state pill. Any $0 plan (Community OR Founding
    Creator) must read as "Not required"; priced plans without an
    active sub read as "Not connected"; active Stripe-paid subs
    read as "Connected".
    """

    _BILLING = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend/src/app/creator-studio/billing/page.tsx"
    )

    def test_pill_treats_any_zero_price_plan_as_not_required(self):
        """Broadening from ``monthly=0 && !is_purchasable`` to
        ``monthly=0`` alone fixes the historical Community
        mislabel — Community is free non-commercial + is_purchasable=true,
        so the tighter check made it fall through to "Not connected".
        """
        assert self._BILLING.exists()
        source = self._BILLING.read_text(encoding="utf-8")
        # Positive: the broadened check is present.
        assert "current_plan.monthly_price_cents === 0\n                    ? 'not_applicable'" in source, (
            "billing/page.tsx: expected the Creator billing pill to "
            "map ANY ``monthly_price_cents === 0`` plan to "
            "'not_applicable' ('Not required'). If this check has "
            "been re-narrowed to ``&& is_purchasable === false``, "
            "Community will render 'Not connected' again — see the "
            "2026-09-16 state-6 mislabel fix."
        )
        # Negative: the tighter historical shape is not present.
        assert "current_plan.is_purchasable === false" not in source, (
            "billing/page.tsx: the Creator billing pill check must "
            "not gate 'Not required' on is_purchasable — Community is "
            "purchasable AND free."
        )

    def test_pill_states_are_exhaustive_three_way(self):
        """StatusBadge accepts exactly three states. Guards against
        a future refactor that adds a fourth state without updating
        the labels below."""
        assert self._BILLING.exists()
        source = self._BILLING.read_text(encoding="utf-8")
        assert "'connected' | 'not_connected' | 'not_applicable'" in source
