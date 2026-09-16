"""Creator Studio Billing display truthfulness + invoice retrieval.

Regression coverage for the 2026-09-16 live-test findings:

1. ``payment_setup.creator_billing_connected`` must reflect whether
   the caller has a live Stripe-paid subscription (was hardcoded
   False, so an active $19 Creator sub still rendered as
   "NOT CONNECTED").
2. Founding Creator / manual_grant plans continue to report
   ``creator_billing_connected=False`` — the frontend's "$0 +
   is_purchasable=False" branch renders "Not required" for those,
   so the flag stays False without misleading the display.
3. ``GET /api/creator/billing/invoices`` returns Stripe-backed
   invoices when the caller has a Stripe subscription, empty +
   ``billed_via_stripe=False`` otherwise, and never surfaces
   member finite-plan invoices even if the same Customer id is
   reused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

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


def _ensure_plan(db, *, slug, fee_bps, price, limit=1):
    p = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if p:
        return p
    p = CreatorPlan(
        id=_uid("cp"), name=slug.title(), slug=slug,
        monthly_price_cents=price, transaction_fee_basis_points=fee_bps,
        collective_limit=limit, is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _grant_sub(db, user, plan, *, source, status=CreatorSubscriptionStatus.active,
               stripe_subscription_id=None, stripe_customer_id=None):
    sub = CreatorSubscription(
        id=_uid("sub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=status,
        starts_at=datetime.utcnow(),
        source=source,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
    )
    db.add(sub)
    db.flush()
    return sub


@pytest.fixture
def stripe_enabled(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")


# ---------------------------------------------------------------------------
# Billing status truthfulness
# ---------------------------------------------------------------------------


class TestCreatorBillingConnectedFlag:
    def test_active_stripe_paid_sub_reports_billing_connected_true(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan, source="stripe_paid",
            stripe_subscription_id="sub_live_1",
            stripe_customer_id="cus_live_1",
        )
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["payment_setup"]["creator_billing_connected"] is True

    def test_founding_creator_manual_grant_reports_billing_connected_false(
        self, db, client, make_user, stripe_enabled,
    ):
        """Founding Creator / manual_grant is not billed via Stripe.
        The flag stays False; the frontend then reads
        ``current_plan.monthly_price_cents == 0 && !is_purchasable``
        and renders "Not required" — the truthful state."""
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0)
        _grant_sub(db, creator, plan, source="manual_grant")
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["payment_setup"]["creator_billing_connected"] is False

    def test_no_active_sub_reports_billing_connected_false(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["payment_setup"]["creator_billing_connected"] is False


# ---------------------------------------------------------------------------
# Invoice retrieval
# ---------------------------------------------------------------------------


class TestBillingInvoicesEndpoint:
    def test_returns_stripe_invoices_for_active_stripe_paid_sub(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan, source="stripe_paid",
            stripe_subscription_id="sub_live_2",
            stripe_customer_id="cus_live_2",
        )
        db.commit()

        fake_invoice_ts = int((datetime.utcnow() - timedelta(days=2)).timestamp())
        fake_stripe_response = {
            "data": [
                {
                    "id": "in_test_1",
                    "number": "FC-0001",
                    "created": fake_invoice_ts,
                    "period_start": fake_invoice_ts - 30 * 86400,
                    "period_end": fake_invoice_ts,
                    "amount_paid": 1900,
                    "amount_due": 1900,
                    "currency": "aud",
                    "status": "paid",
                    "hosted_invoice_url": "https://invoice.stripe.test/i/live_1",
                    "invoice_pdf": "https://invoice.stripe.test/i/live_1.pdf",
                    "description": None,
                },
            ],
        }

        with patch(
            "app.services.stripe_creator_billing.stripe.Invoice.list",
        ) as mock_list:
            # Simulate a Stripe list response — the code path uses
            # ``resp.auto_paging_iter()`` if available, else falls back
            # to ``resp.get("data", [])`` — provide a dict so the
            # fallback branch fires.
            mock_list.return_value = fake_stripe_response
            app.dependency_overrides[get_creator_user] = lambda: creator
            res = client.get("/api/creator/billing/invoices")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["billed_via_stripe"] is True
        assert len(body["invoices"]) == 1
        row = body["invoices"][0]
        assert row["id"] == "in_test_1"
        assert row["amount_paid_cents"] == 1900
        assert row["currency"] == "AUD"
        assert row["status"] == "paid"
        assert row["hosted_invoice_url"].startswith("https://invoice.stripe.test/")

        # Verify Stripe was called with BOTH customer AND subscription
        # filter — the isolation invariant that keeps member
        # finite-plan invoices out of the creator history.
        _, kwargs = mock_list.call_args
        assert kwargs["customer"] == "cus_live_2"
        assert kwargs["subscription"] == "sub_live_2"

    def test_returns_empty_billed_via_stripe_false_for_manual_grant(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0)
        _grant_sub(db, creator, plan, source="manual_grant")
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: creator
        # Must not call Stripe at all — no sub → early return.
        with patch(
            "app.services.stripe_creator_billing.stripe.Invoice.list",
        ) as mock_list:
            res = client.get("/api/creator/billing/invoices")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["billed_via_stripe"] is False
        assert body["invoices"] == []
        assert mock_list.call_count == 0

    def test_returns_503_when_stripe_disabled(
        self, db, client, make_user, monkeypatch,
    ):
        creator = make_user(role="creator")
        db.commit()
        monkeypatch.setattr(settings, "stripe_secret_key", "")
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing/invoices")
        assert res.status_code == 503
