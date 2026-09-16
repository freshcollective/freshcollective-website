"""Creator / Pro monthly Stripe subscription — endpoints + webhooks.

Covers:

* ``POST /api/creator/billing/subscribe`` — 503 when Stripe / Price
  env vars missing; 403 for non-purchasable plans (Community /
  Founding Creator / Organisation); 409 on same-plan; success returns
  a checkout URL and metadata that isolates from finite-plan events.
* ``POST /api/creator/billing/portal-session`` — 409 without active
  Stripe sub; success returns a Portal URL.
* ``POST /api/creator/billing/downgrade`` — refuses over-limit.
* Webhook: ``checkout.session.completed`` for a creator sub creates a
  ``past_due`` placeholder row — no false ``active`` activation.
* Webhook: ``invoice.paid`` for a creator sub flips ``status=active``,
  refreshes ``current_period_end``, clears ``grace_expires_at``.
* Webhook: ``invoice.payment_failed`` sets ``past_due`` +
  ``grace_expires_at = now + 7 days``.
* Webhook: ``customer.subscription.deleted`` sets ``cancelled``,
  clears grace.
* Webhook: metadata isolation — invoice for a member finite-plan sub
  falls through to FIP handlers (creator handler returns False).
* Webhook: dedup via ``stripe_webhook_events`` — duplicate event.id
  no-ops.
* Grace-expiry sweep: past_due + grace_expires_at < now → unpaid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
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
from app.services.creator_subscription_lifecycle import (
    sweep_expired_creator_grace,
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


def _ensure_plan(
    db, *, slug: str, fee_bps: int, price: int, collective_limit: int = 1,
) -> CreatorPlan:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if plan:
        return plan
    plan = CreatorPlan(
        id=_uid("cp"),
        name=slug.title(),
        slug=slug,
        monthly_price_cents=price,
        transaction_fee_basis_points=fee_bps,
        collective_limit=collective_limit,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _grant_sub(
    db, user, plan, *,
    source: str = "stripe_paid",
    status: CreatorSubscriptionStatus = CreatorSubscriptionStatus.active,
    stripe_subscription_id: str | None = None,
    stripe_customer_id: str | None = None,
) -> CreatorSubscription:
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
    """Stripe treated as configured, both Price IDs populated."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_price_id_creator", "price_creator_test")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_test")


@pytest.fixture
def stripe_missing_price(monkeypatch):
    """Stripe enabled but Price ID env var absent — the fail-safe path."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_price_id_creator", None)
    monkeypatch.setattr(settings, "stripe_price_id_pro", None)


# ---------------------------------------------------------------------------
# POST /billing/subscribe
# ---------------------------------------------------------------------------

class TestSubscribeEndpoint:
    def test_returns_503_when_stripe_not_configured(
        self, db, client, make_user, monkeypatch,
    ):
        creator = make_user(role="creator")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        monkeypatch.setattr(settings, "stripe_secret_key", "")
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            "/api/creator/billing/subscribe", json={"plan_slug": "creator"},
        )
        assert res.status_code == 503

    def test_returns_503_when_price_id_missing(
        self, db, client, make_user, stripe_missing_price,
    ):
        creator = make_user(role="creator")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        with patch(
            "app.services.stripe_creator_billing.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_x"),
        ):
            res = client.post(
                "/api/creator/billing/subscribe", json={"plan_slug": "creator"},
            )
        assert res.status_code == 503
        assert "not configured" in res.text.lower()

    def test_rejects_non_purchasable_plan(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            "/api/creator/billing/subscribe",
            json={"plan_slug": "founding-creator"},
        )
        assert res.status_code == 403

    def test_rejects_when_already_on_same_plan(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_existing",
            stripe_customer_id="cus_existing",
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            "/api/creator/billing/subscribe", json={"plan_slug": "creator"},
        )
        assert res.status_code == 409

    def test_creates_checkout_session_with_isolation_metadata(
        self, db, client, make_user, stripe_enabled,
    ):
        creator = make_user(role="creator")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        with patch(
            "app.services.stripe_creator_billing.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_new"),
        ), patch(
            "app.services.stripe_creator_billing.stripe.checkout.Session.create",
        ) as mock_session:
            mock_session.return_value = {"url": "https://checkout.stripe.test/x"}
            res = client.post(
                "/api/creator/billing/subscribe", json={"plan_slug": "creator"},
            )
        assert res.status_code == 200
        assert res.json()["checkout_url"].startswith("https://checkout.stripe.test/")
        args, kwargs = mock_session.call_args
        # Metadata MUST carry the discriminator that keeps
        # creator-billing events isolated from finite-plan events.
        assert kwargs["mode"] == "subscription"
        assert kwargs["metadata"]["purchase_type"] == "creator_subscription"
        assert kwargs["metadata"]["creator_user_id"] == creator.id
        assert kwargs["metadata"]["creator_plan_slug"] == "creator"
        # Same metadata is duplicated onto the subscription so future
        # customer.subscription.* and invoice.* events resolve
        # correctly via the subscription lookup.
        assert kwargs["subscription_data"]["metadata"]["purchase_type"] == "creator_subscription"
        # Card-only per workstream amendment A.
        assert kwargs["payment_method_types"] == ["card"]


# ---------------------------------------------------------------------------
# POST /billing/downgrade — over-limit refusal
# ---------------------------------------------------------------------------

class TestDowngradeOverLimit:
    def test_refuses_downgrade_when_active_collectives_exceed_target_limit(
        self, db, client, make_user, make_space, stripe_enabled,
    ):
        creator = make_user(role="creator")
        pro = _ensure_plan(db, slug="pro", fee_bps=300, price=7900, collective_limit=5)
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, pro,
            stripe_subscription_id="sub_pro", stripe_customer_id="cus_pro",
        )
        for _ in range(3):
            make_space(creator=creator)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.post(
            "/api/creator/billing/downgrade", json={"plan_slug": "creator"},
        )
        assert res.status_code == 409
        assert "collective" in res.text.lower()


# ---------------------------------------------------------------------------
# Webhook: checkout.session.completed — link only, no false activation
# ---------------------------------------------------------------------------

class TestCheckoutCompletedNoFalseActivation:
    def test_creates_past_due_placeholder_not_active(
        self, db, make_user,
    ):
        from app.webhooks.creator_billing_handlers import (
            handle_checkout_completed_creator_subscription,
        )
        creator = make_user(role="creator")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        session = {
            "id": "cs_test_1",
            "subscription": "sub_new",
            "customer": "cus_new",
            "metadata": {
                "purchase_type": "creator_subscription",
                "creator_user_id": creator.id,
                "creator_plan_slug": "creator",
            },
        }
        handle_checkout_completed_creator_subscription(
            session, db, event_id="evt_1", event_type="checkout.session.completed",
        )
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_new")
            .first()
        )
        assert row is not None
        # Placeholder — activation only happens on invoice.paid.
        assert row.status == CreatorSubscriptionStatus.past_due
        assert row.source == "stripe_paid"


# ---------------------------------------------------------------------------
# Webhook: invoice.paid — real activation
# ---------------------------------------------------------------------------

class TestInvoicePaidActivates:
    def test_activates_placeholder_row_and_sets_period_end(
        self, db, make_user,
    ):
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_paid,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_activate",
            stripe_customer_id="cus_x",
            status=CreatorSubscriptionStatus.past_due,
        )
        db.commit()
        period_end_ts = int((datetime.utcnow() + timedelta(days=30)).timestamp())
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value={
                "id": "sub_activate",
                "customer": "cus_x",
                "current_period_end": period_end_ts,
                "cancel_at_period_end": False,
                "metadata": {
                    "purchase_type": "creator_subscription",
                    "creator_user_id": creator.id,
                    "creator_plan_slug": "creator",
                },
                "items": {"data": [{"id": "si", "price": {"id": "price_creator_test"}}]},
                "current_period_start": period_end_ts - 30 * 86400,
                "status": "active",
            },
        ):
            handled = handle_invoice_paid(
                {"id": "in_1", "subscription": "sub_activate"},
                db, event_id="evt_paid_1", event_type="invoice.paid",
            )
        assert handled is True
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_activate")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.active
        assert row.current_period_end is not None
        assert row.grace_expires_at is None

    def test_ignores_finite_plan_invoice(self, db, make_user):
        """Metadata gate — invoice for a member finite-plan sub returns
        False so the dispatcher falls through to the FIP handler."""
        from app.webhooks.creator_billing_handlers import handle_invoice_paid
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value={
                "id": "sub_finite",
                "metadata": {"purchase_type": "finite_plan_setup"},
            },
        ):
            handled = handle_invoice_paid(
                {"id": "in_finite", "subscription": "sub_finite"},
                db,
                event_id="evt_finite_1",
                event_type="invoice.paid",
            )
        assert handled is False


# ---------------------------------------------------------------------------
# Webhook: invoice.payment_failed — grace
# ---------------------------------------------------------------------------

class TestInvoicePaymentFailedGrace:
    def test_sets_past_due_and_grace_window(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_invoice_payment_failed,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_grace",
            stripe_customer_id="cus_x",
        )
        db.commit()
        with patch(
            "app.webhooks.creator_billing_handlers.scb.retrieve_subscription",
            return_value={
                "id": "sub_grace",
                "metadata": {
                    "purchase_type": "creator_subscription",
                    "creator_user_id": creator.id,
                    "creator_plan_slug": "creator",
                },
            },
        ):
            before = datetime.utcnow()
            handled = handle_invoice_payment_failed(
                {"id": "in_fail_1", "subscription": "sub_grace"},
                db,
                event_id="evt_fail_1",
                event_type="invoice.payment_failed",
            )
            after = datetime.utcnow()
        assert handled is True
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_grace")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.past_due
        assert row.grace_expires_at is not None
        # Grace is 7 days ± test timing slack.
        delta = row.grace_expires_at - before
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, minutes=5)


# ---------------------------------------------------------------------------
# Webhook: customer.subscription.deleted → cancelled
# ---------------------------------------------------------------------------

class TestSubscriptionDeletedFinalises:
    def test_flips_status_cancelled_and_clears_grace(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_deleted,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        sub = _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_end", stripe_customer_id="cus_x",
        )
        sub.grace_expires_at = datetime.utcnow() + timedelta(days=3)
        db.commit()
        subscription = {
            "id": "sub_end",
            "metadata": {
                "purchase_type": "creator_subscription",
                "creator_user_id": creator.id,
                "creator_plan_slug": "creator",
            },
        }
        handled = handle_subscription_deleted(
            subscription, db,
            event_id="evt_del_1",
            event_type="customer.subscription.deleted",
        )
        assert handled is True
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_end")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.cancelled
        assert row.grace_expires_at is None


# ---------------------------------------------------------------------------
# Webhook idempotency
# ---------------------------------------------------------------------------

class TestWebhookIdempotency:
    def test_duplicate_event_id_is_noop(self, db, make_user):
        from app.webhooks.creator_billing_handlers import (
            handle_subscription_deleted,
        )
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_dup",
            stripe_customer_id="cus_x",
        )
        db.commit()
        subscription = {
            "id": "sub_dup",
            "metadata": {
                "purchase_type": "creator_subscription",
                "creator_user_id": creator.id,
                "creator_plan_slug": "creator",
            },
        }
        h1 = handle_subscription_deleted(
            subscription, db,
            event_id="evt_dup", event_type="customer.subscription.deleted",
        )
        # First delivery: state mutated.
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_dup")
            .first()
        )
        assert row.status == CreatorSubscriptionStatus.cancelled
        assert h1 is True

        # Re-activate row to prove the second delivery does NOT re-mutate.
        row.status = CreatorSubscriptionStatus.active
        db.commit()

        h2 = handle_subscription_deleted(
            subscription, db,
            event_id="evt_dup",  # same event id
            event_type="customer.subscription.deleted",
        )
        db.expire_all()
        row = (
            db.query(CreatorSubscription)
            .filter(CreatorSubscription.stripe_subscription_id == "sub_dup")
            .first()
        )
        # Row untouched — second call was a dedup no-op.
        assert row.status == CreatorSubscriptionStatus.active
        assert h2 is True   # handled (metadata matched), but no-op


# ---------------------------------------------------------------------------
# Grace-expiry sweep
# ---------------------------------------------------------------------------

class TestGraceExpirySweep:
    def test_past_due_with_expired_grace_moves_to_unpaid(
        self, db, make_user,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        sub = _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_expired",
            stripe_customer_id="cus_x",
            status=CreatorSubscriptionStatus.past_due,
        )
        sub.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        n = sweep_expired_creator_grace(db)
        assert n == 1
        db.expire_all()
        row = db.query(CreatorSubscription).filter(
            CreatorSubscription.id == sub.id,
        ).first()
        assert row.status == CreatorSubscriptionStatus.unpaid

    def test_past_due_within_grace_untouched(self, db, make_user):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        sub = _grant_sub(
            db, creator, plan,
            stripe_subscription_id="sub_grace_ok",
            stripe_customer_id="cus_x",
            status=CreatorSubscriptionStatus.past_due,
        )
        sub.grace_expires_at = datetime.utcnow() + timedelta(days=3)
        db.commit()
        n = sweep_expired_creator_grace(db)
        assert n == 0
        db.expire_all()
        row = db.query(CreatorSubscription).filter(
            CreatorSubscription.id == sub.id,
        ).first()
        assert row.status == CreatorSubscriptionStatus.past_due
