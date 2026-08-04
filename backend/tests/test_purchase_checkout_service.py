"""Stage 2 — purchase-checkout service tests.

Covers:

  * Successful Checkout Session creation in subscription mode
    (Creator and Creator Portfolio).
  * Metadata composition — exactly and only the whitelisted keys.
  * One-time (collective membership) scaffold still refuses cleanly
    until Stage 5 wires the line items.
  * Refusal of intents that are not in ``pending`` state.
  * Refusal of intents that have already generated a Session.
  * Refusal when the Stripe Price ID for the requested plan is unset.
  * Refusal when Stripe is not configured at all.
  * ``missing_env_var_for_creator_plan`` preflight helper is a pure
    function of ``settings`` and never touches the DB.

Mocks the Stripe SDK by patching ``stripe.checkout.Session.create``
directly. Service code uses the module-level ``stripe`` import so
``except stripe.StripeError`` binds to the real class.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe

from app.checkout.stripe_client import StripeNotConfiguredError
from app.core.config import settings
from app.models.creator_billing import CreatorPlan
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.purchases.checkout import (
    InvalidIntentStateError,
    MissingPricingError,
    UnknownPlanError,
    create_checkout_session_for_intent,
    create_collective_membership_intent,
    create_creator_subscription_intent,
    missing_env_var_for_creator_plan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stripe_configured(monkeypatch):
    """Force settings.stripe_enabled True + Price IDs present."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
    monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_test")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_test")
    monkeypatch.setattr(settings, "public_app_url", "https://app.test.local")
    return settings


@pytest.fixture
def stripe_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    return settings


@pytest.fixture
def _creator_plans(db):
    """Ensure both billable CreatorPlan rows exist."""
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


def _fake_stripe_session(
    session_id: str = "cs_test_generated",
    url: str = "https://checkout.stripe.test/session/x",
    customer: str | None = "cus_test_123",
):
    """Stand-in for ``stripe.checkout.Session`` that carries the
    attributes our code reads."""
    return SimpleNamespace(id=session_id, url=url, customer=customer)


# ---------------------------------------------------------------------------
# Successful subscription-mode Session creation
# ---------------------------------------------------------------------------


class TestCreatorSubscriptionSuccess:
    def test_creates_intent_in_pending_state(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        assert intent.kind == PurchaseIntentKind.creator_subscription
        assert intent.plan_slug == "creator"
        assert intent.status == PurchaseIntentStatus.pending
        assert intent.payer_user_id == user.id
        assert intent.provider_checkout_session_id is None

    def test_creates_stripe_subscription_session_and_persists_ids(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        with patch("stripe.checkout.Session.create") as create_mock:
            create_mock.return_value = _fake_stripe_session()
            result = create_checkout_session_for_intent(
                db, intent, customer_email=user.email
            )

        _, kwargs = create_mock.call_args
        assert kwargs["mode"] == "subscription"
        assert kwargs["line_items"] == [
            {"price": "price_creator_test", "quantity": 1}
        ]
        assert kwargs["idempotency_key"] == f"purchase_intent:{intent.id}:session:v1"

        # URLs are built from the resolved public app URL and carry the
        # raw claim token.
        assert kwargs["success_url"].startswith(
            "https://app.test.local/checkout/complete?token="
        )
        assert kwargs["cancel_url"] == "https://app.test.local/for-creators#plans"
        assert kwargs["customer_email"] == user.email

        assert intent.provider_checkout_session_id == "cs_test_generated"
        assert intent.provider_customer_id == "cus_test_123"
        assert intent.status == PurchaseIntentStatus.pending

        # Claim token: hash stored, raw not in the URL.
        assert intent.claim_token_hash is not None
        assert len(intent.claim_token_hash) == 64
        assert intent.claim_token_hash not in kwargs["success_url"]

        assert result.checkout_url == "https://checkout.stripe.test/session/x"
        assert result.provider_checkout_session_id == "cs_test_generated"
        assert result.purchase_intent_id == intent.id

    def test_pro_uses_the_pro_price_and_snapshots_3pct_fee(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="pro", payer_user_id=user.id
        )
        with patch("stripe.checkout.Session.create") as create_mock:
            create_mock.return_value = _fake_stripe_session(session_id="cs_pro_x")
            create_checkout_session_for_intent(db, intent, customer_email=user.email)

        _, kwargs = create_mock.call_args
        assert kwargs["line_items"][0]["price"] == "price_pro_test"
        assert intent.platform_fee_bps == 300


# ---------------------------------------------------------------------------
# Metadata composition
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_metadata_carries_intent_id_kind_and_plan(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        with patch("stripe.checkout.Session.create") as create_mock:
            create_mock.return_value = _fake_stripe_session()
            create_checkout_session_for_intent(db, intent, customer_email=user.email)

        _, kwargs = create_mock.call_args
        md = kwargs["metadata"]
        assert md["purchase_intent_id"] == intent.id
        assert md["kind"] == "creator_subscription"
        assert md["plan_slug"] == "creator"
        assert kwargs["subscription_data"]["metadata"] == md
        assert "claim_email" not in md
        assert set(md.keys()) == {"purchase_intent_id", "kind", "plan_slug"}


# ---------------------------------------------------------------------------
# One-time (collective_membership) scaffold
# ---------------------------------------------------------------------------


class TestOneTimeMembershipScaffold:
    def test_intent_persists_but_session_creation_is_not_wired(
        self, db, make_space, stripe_configured,
    ):
        space = make_space()
        intent = create_collective_membership_intent(
            db, space_id=space.id, payer_user_id=None
        )
        assert intent.kind == PurchaseIntentKind.collective_membership
        assert intent.space_id == space.id
        assert intent.payer_user_id is None

        with patch("stripe.checkout.Session.create") as create_mock:
            create_mock.return_value = _fake_stripe_session()
            with pytest.raises(MissingPricingError):
                create_checkout_session_for_intent(db, intent)


# ---------------------------------------------------------------------------
# Intent-state validation
# ---------------------------------------------------------------------------


class TestIntentStateValidation:
    @pytest.mark.parametrize(
        "bad_status",
        [
            PurchaseIntentStatus.paid,
            PurchaseIntentStatus.consumed,
            PurchaseIntentStatus.expired,
            PurchaseIntentStatus.cancelled,
            PurchaseIntentStatus.refunded,
        ],
    )
    def test_refuses_non_pending_status(
        self, db, make_user, _creator_plans, stripe_configured, bad_status,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        intent.status = bad_status
        db.flush()
        with pytest.raises(InvalidIntentStateError):
            create_checkout_session_for_intent(db, intent)

    def test_refuses_when_intent_already_has_session(
        self, db, make_user, _creator_plans, stripe_configured,
    ):
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        intent.provider_checkout_session_id = "cs_already_here"
        db.flush()
        with pytest.raises(InvalidIntentStateError):
            create_checkout_session_for_intent(db, intent)


# ---------------------------------------------------------------------------
# Pricing / plan resolution
# ---------------------------------------------------------------------------


class TestPricingAndPlanResolution:
    def test_service_missing_price_id_raises_missing_pricing_error(
        self, db, make_user, _creator_plans, monkeypatch,
    ):
        """The service-level defensive check still refuses when a
        Price ID is unset — even though the route preflight should
        normally catch this before any DB row is written."""
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")
        monkeypatch.setattr(settings, "stripe_price_id_creator", None)
        monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_test")
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        with pytest.raises(MissingPricingError):
            create_checkout_session_for_intent(db, intent)

    def test_unknown_plan_slug_raises_unknown_plan_error(
        self, db, make_user, stripe_configured,
    ):
        with pytest.raises(UnknownPlanError):
            create_creator_subscription_intent(
                db, plan_slug="community", payer_user_id=make_user().id
            )


# ---------------------------------------------------------------------------
# missing_env_var_for_creator_plan — preflight helper is pure
# ---------------------------------------------------------------------------


class TestPreflightHelper:
    def test_returns_none_when_creator_price_id_set(self, monkeypatch, db):
        monkeypatch.setattr(settings, "stripe_price_id_creator", "price_x")
        before = db.query(PurchaseIntent).count()
        assert missing_env_var_for_creator_plan("creator") is None
        assert db.query(PurchaseIntent).count() == before  # no DB touch

    def test_returns_var_name_when_creator_price_id_unset(self, monkeypatch, db):
        monkeypatch.setattr(settings, "stripe_price_id_creator", None)
        before = db.query(PurchaseIntent).count()
        assert missing_env_var_for_creator_plan("creator") == "STRIPE_PRICE_ID_CREATOR"
        assert db.query(PurchaseIntent).count() == before

    def test_returns_var_name_when_pro_price_id_unset(self, monkeypatch, db):
        monkeypatch.setattr(settings, "stripe_price_id_pro", None)
        assert missing_env_var_for_creator_plan("pro") == "STRIPE_PRICE_ID_PRO"


# ---------------------------------------------------------------------------
# Stripe not configured
# ---------------------------------------------------------------------------


class TestStripeUnconfigured:
    def test_get_stripe_raises_when_secret_key_missing(self, stripe_not_configured):
        from app.checkout.stripe_client import get_stripe
        with pytest.raises(StripeNotConfiguredError):
            get_stripe()

    def test_service_refuses_when_unconfigured_after_intent_exists(
        self, db, make_user, _creator_plans, stripe_not_configured, monkeypatch,
    ):
        """The service still refuses, but note: the route preflight
        should prevent this branch from ever running in production —
        this proves the defensive check works, not the intended flow."""
        monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_test")
        user = make_user()
        intent = create_creator_subscription_intent(
            db, plan_slug="creator", payer_user_id=user.id
        )
        with pytest.raises(StripeNotConfiguredError):
            create_checkout_session_for_intent(db, intent)
        assert intent.status == PurchaseIntentStatus.pending
        assert intent.provider_checkout_session_id is None
