"""Stage 2 — /api/purchases/creator-subscription route tests.

Two groups of tests:

  * **HTTP-shape** tests via TestClient — schema validation, OpenAPI
    registration, structured 503 body when Stripe is unconfigured.
    These do not need to observe DB state; TestClient's fresh
    session is fine.
  * **PurchaseIntent-integrity** tests via direct handler invocation —
    prove that failed preflight / failed Stripe SDK calls leave zero
    PurchaseIntent rows behind. Direct invocation is used so the
    fixture's SAVEPOINT-wrapped session sees the rollback.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import stripe
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.creator_billing import CreatorPlan
from app.models.purchase_intent import PurchaseIntent, PurchaseIntentStatus
from app.purchases.routes import (
    CreatorSubscriptionCheckoutRequest,
    create_creator_subscription_checkout,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _creator_plans(db):
    for slug, fee_bps, price in (("creator", 800, 1900), ("pro", 300, 7900)):
        existing = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if existing is None:
            db.add(
                CreatorPlan(
                    id=f"cp_{slug}",
                    name=slug.title(),
                    slug=slug,
                    monthly_price_cents=price,
                    transaction_fee_basis_points=fee_bps,
                    collective_limit=1 if slug == "creator" else 5,
                    is_active=True,
                )
            )
    db.flush()


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
    monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_test")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_test")
    monkeypatch.setattr(settings, "public_app_url", "https://app.test.local")


# ---------------------------------------------------------------------------
# HTTP shape
# ---------------------------------------------------------------------------


def test_route_registered_in_openapi() -> None:
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    assert "/api/purchases/creator-subscription" in spec["paths"]


def test_schema_rejects_community_plan(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
    client = TestClient(app)
    res = client.post(
        "/api/purchases/creator-subscription",
        json={"plan_slug": "community"},
    )
    assert res.status_code == 422


def test_schema_rejects_missing_body() -> None:
    client = TestClient(app)
    res = client.post("/api/purchases/creator-subscription", json={})
    assert res.status_code == 422


def test_503_when_stripe_not_configured_has_structured_body(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    client = TestClient(app)
    res = client.post(
        "/api/purchases/creator-subscription",
        json={"plan_slug": "creator"},
    )
    assert res.status_code == 503
    detail = res.json().get("detail")
    assert isinstance(detail, dict)
    assert detail.get("reason") == "stripe_not_configured"
    assert detail.get("would_create") == {
        "kind": "creator_subscription",
        "plan_slug": "creator",
    }
    # The 503 body must NOT contain operator-authored prose. Frontend
    # owns copy; only a stable reason code (and, for price_id case,
    # a machine identifier) crosses the wire.
    assert "message" not in detail
    assert "detail" not in detail


def test_503_when_price_id_missing_has_env_var_name(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
    monkeypatch.setattr(settings, "stripe_price_id_creator", None)
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_x")
    client = TestClient(app)
    res = client.post(
        "/api/purchases/creator-subscription",
        json={"plan_slug": "creator"},
    )
    assert res.status_code == 503
    detail = res.json().get("detail")
    assert detail.get("reason") == "price_id_not_configured"
    assert detail.get("missing_env_var") == "STRIPE_PRICE_ID_CREATOR"
    # Still no message field — frontend owns copy.
    assert "message" not in detail


# ---------------------------------------------------------------------------
# PurchaseIntent integrity: no orphan rows on any 503 / rollback path
# ---------------------------------------------------------------------------


def _request(plan_slug: str) -> CreatorSubscriptionCheckoutRequest:
    return CreatorSubscriptionCheckoutRequest(plan_slug=plan_slug)


class TestNoOrphanIntent:
    """Confirms the Stage 2 brief's ordering invariant:

        Validate plan → Stripe configured? → Price ID present?
                     → THEN create PurchaseIntent → create Session
    """

    def test_missing_stripe_credentials_creates_no_intent(
        self, db, monkeypatch, _creator_plans,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", None)
        monkeypatch.setattr(settings, "stripe_webhook_secret", None)

        before = db.query(PurchaseIntent).count()
        with pytest.raises(HTTPException) as exc:
            create_creator_subscription_checkout(
                _request("creator"), db=db, current_user=None
            )
        assert exc.value.status_code == 503
        assert exc.value.detail["reason"] == "stripe_not_configured"

        assert db.query(PurchaseIntent).count() == before

    def test_missing_creator_price_id_creates_no_intent(
        self, db, monkeypatch, _creator_plans,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
        monkeypatch.setattr(settings, "stripe_price_id_creator", None)
        monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_x")

        before = db.query(PurchaseIntent).count()
        with pytest.raises(HTTPException) as exc:
            create_creator_subscription_checkout(
                _request("creator"), db=db, current_user=None
            )
        assert exc.value.status_code == 503
        assert exc.value.detail["reason"] == "price_id_not_configured"
        assert exc.value.detail["missing_env_var"] == "STRIPE_PRICE_ID_CREATOR"

        assert db.query(PurchaseIntent).count() == before

    def test_missing_portfolio_price_id_creates_no_intent(
        self, db, monkeypatch, _creator_plans,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
        monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_x")
        monkeypatch.setattr(settings, "stripe_price_id_pro", None)

        before = db.query(PurchaseIntent).count()
        with pytest.raises(HTTPException) as exc:
            create_creator_subscription_checkout(
                _request("pro"), db=db, current_user=None
            )
        assert exc.value.status_code == 503
        assert exc.value.detail["reason"] == "price_id_not_configured"
        assert exc.value.detail["missing_env_var"] == "STRIPE_PRICE_ID_PRO"

        assert db.query(PurchaseIntent).count() == before

    def test_stripe_api_failure_rolls_back_pending_intent(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        """Preflight passes; PurchaseIntent gets written; Stripe then
        rejects the Session. The route must roll the intent back so
        no orphan pending row survives."""
        user = make_user()
        before = db.query(PurchaseIntent).count()

        with patch("stripe.checkout.Session.create") as create_mock:
            create_mock.side_effect = stripe.StripeError("simulated failure")
            with pytest.raises(HTTPException) as exc:
                create_creator_subscription_checkout(
                    _request("creator"), db=db, current_user=user
                )
        assert exc.value.status_code == 502

        # SAVEPOINT-wrapped rollback: the intent that was flushed
        # before the Stripe call is gone.
        after = db.query(PurchaseIntent).count()
        assert after == before

    def test_successful_creation_leaves_exactly_one_pending_intent(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        before = db.query(PurchaseIntent).count()

        with patch("stripe.checkout.Session.create") as create_mock:
            from types import SimpleNamespace
            create_mock.return_value = SimpleNamespace(
                id="cs_success_x",
                url="https://checkout.stripe.test/x",
                customer="cus_success_x",
            )
            res = create_creator_subscription_checkout(
                _request("creator"), db=db, current_user=user
            )

        after = db.query(PurchaseIntent).count()
        assert after == before + 1

        intent = (
            db.query(PurchaseIntent)
            .filter(PurchaseIntent.provider_checkout_session_id == "cs_success_x")
            .one()
        )
        # Status stays pending — only a verified webhook may promote
        # an intent to paid.
        assert intent.status == PurchaseIntentStatus.pending
        assert intent.plan_slug == "creator"
        assert intent.payer_user_id == user.id
        # Response echoes the persisted IDs.
        assert res.provider_checkout_session_id == "cs_success_x"
        assert res.purchase_intent_id == intent.id
        assert res.checkout_url == "https://checkout.stripe.test/x"
