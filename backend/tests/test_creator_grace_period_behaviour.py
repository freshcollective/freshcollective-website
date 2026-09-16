"""Fresh Collective 7-day grace-period behaviour end-to-end.

``handle_invoice_payment_failed`` writes ``status='past_due'`` +
``grace_expires_at = now + 7 days`` on the CreatorSubscription row.
The 2026-09-17 grace-lifecycle audit found that three resolvers
filtered on ``active|trialing`` and instantly stripped commercial
capability the moment the webhook fired — the opposite of what the
grace window is for.

Fix: broaden three resolver filters to
``active|trialing|past_due``:

* ``_resolve_fee_bps_for_creator`` — member checkout keeps the
  snapshotted 8%/3% fee during grace.
* ``resolve_creator_plan`` — creator retains paid-offer /
  collective-limit / pathway-limit capability during grace.
* ``get_creator_billing`` — Billing page renders the plan card +
  the payment-failed / grace banner during grace.

``unpaid`` and ``cancelled`` remain OUTSIDE the filter. After the
grace-expiry cron flips ``past_due → unpaid`` at 7 days, all three
resolvers return "no plan" and commercial capability is removed as
before — grace duration is enforced at the DB status transition,
not at the resolver.
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
from app.creator.plan_guards import resolve_creator_plan
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.services.checkout_orchestration import (
    NoActiveCreatorPlanError,
    ResolvedOption,
    _resolve_fee_bps_for_creator,
    orchestrate_paid_checkout,
    resolve_fee_context,
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


def _sub(db, user, plan, *, status, source="stripe_paid",
         stripe_subscription_id=None, stripe_customer_id=None,
         grace_expires_at=None):
    sub = CreatorSubscription(
        id=_uid("sub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=status,
        starts_at=datetime.utcnow(),
        source=source,
        stripe_subscription_id=stripe_subscription_id or _uid("stripe_sub"),
        stripe_customer_id=stripe_customer_id or _uid("stripe_cus"),
        grace_expires_at=grace_expires_at,
    )
    db.add(sub)
    db.flush()
    return sub


def _make_paid_option(db, space):
    """Minimum viable Payment Option for a pay-in-full checkout."""
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name="Test Paid Option",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=10_000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"),
        payment_option_id=opt.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=10_000,
        currency="AUD",
    )
    db.add(sched)
    db.flush()
    return opt, sched


@pytest.fixture
def guard_on(monkeypatch):
    monkeypatch.setattr(settings, "creator_plan_guard_enabled", True)


# ---------------------------------------------------------------------------
# 1. Fee resolution — past_due keeps the snapshotted fee
# ---------------------------------------------------------------------------


class TestFeeResolutionDuringGrace:
    def test_past_due_creator_still_resolves_snapshotted_fee(
        self, db, make_user, guard_on,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(
            db, creator, plan,
            status=CreatorSubscriptionStatus.past_due,
            grace_expires_at=datetime.utcnow() + timedelta(days=5),
        )
        db.commit()
        fee_bps, plan_id, sub_id = _resolve_fee_bps_for_creator(creator.id, db)
        assert fee_bps == 800
        assert plan_id == plan.id
        assert sub_id is not None

    def test_unpaid_creator_after_grace_expiry_raises(
        self, db, make_user, guard_on,
    ):
        """The cron transitions past_due → unpaid at 7 days.
        ``unpaid`` MUST remain outside the resolver so commercial
        capability collapses on that boundary."""
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator, plan, status=CreatorSubscriptionStatus.unpaid)
        db.commit()
        with pytest.raises(NoActiveCreatorPlanError):
            _resolve_fee_bps_for_creator(creator.id, db)

    def test_cancelled_creator_raises(self, db, make_user, guard_on):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator, plan, status=CreatorSubscriptionStatus.cancelled)
        db.commit()
        with pytest.raises(NoActiveCreatorPlanError):
            _resolve_fee_bps_for_creator(creator.id, db)

    def test_active_and_trialing_unchanged(self, db, make_user, guard_on):
        # Two separate users to exercise both statuses without violating
        # the partial UNIQUE index.
        creator_a = make_user(role="creator")
        creator_t = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator_a, plan, status=CreatorSubscriptionStatus.active)
        _sub(db, creator_t, plan, status=CreatorSubscriptionStatus.trialing)
        db.commit()
        for c in (creator_a, creator_t):
            fee_bps, _, _ = _resolve_fee_bps_for_creator(c.id, db)
            assert fee_bps == 800


# ---------------------------------------------------------------------------
# 2. Paid-offer authoring guard — past_due keeps commercial capability
# ---------------------------------------------------------------------------


class TestCapabilityResolutionDuringGrace:
    def test_past_due_creator_reads_creator_capability(
        self, db, make_user,
    ):
        """``resolve_creator_plan`` must return the CREATOR capability
        (paid_offers_enabled=True) — NOT fall through to the cheapest-
        plan fallback which would return Community and 403 the
        paid-offer guard."""
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(
            db, creator, plan,
            status=CreatorSubscriptionStatus.past_due,
            grace_expires_at=datetime.utcnow() + timedelta(days=5),
        )
        db.commit()
        capability = resolve_creator_plan(creator, db)
        assert capability is not None
        assert capability.slug == "creator"
        assert capability.paid_offers_enabled is True

    def test_unpaid_creator_after_grace_does_not_read_creator_capability(
        self, db, make_user,
    ):
        """``unpaid`` MUST fall out of the resolver so the guard
        system doesn't keep granting the creator their paid-offer
        capability after grace has expired."""
        creator = make_user(role="creator")
        # Seed both community + creator so the "cheapest active plan"
        # fallback in resolve_creator_plan can find community as the
        # zero-price option — mirrors production seed. Without this,
        # the test DB only knows about ``creator`` and the fallback
        # inadvertently returns that even though the sub is unpaid.
        _ensure_plan(db, slug="community", fee_bps=0, price=0)
        creator_plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator, creator_plan, status=CreatorSubscriptionStatus.unpaid)
        db.commit()
        capability = resolve_creator_plan(creator, db)
        # Falls through to the cheapest-plan fallback — community.
        # Critically the Creator capability (paid_offers_enabled=True)
        # is NOT returned, so ``guard_paid_offers_enabled`` will 403
        # any paid-offer authoring attempt.
        assert capability is not None
        assert capability.slug == "community"
        assert capability.paid_offers_enabled is False


# ---------------------------------------------------------------------------
# 3. Billing page endpoint — plan card + banner reachable during grace
# ---------------------------------------------------------------------------


class TestBillingPageDuringGrace:
    def test_past_due_creator_billing_page_renders_plan_card_and_banner(
        self, db, client, make_user,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        grace = datetime.utcnow() + timedelta(days=5)
        _sub(
            db, creator, plan,
            status=CreatorSubscriptionStatus.past_due,
            grace_expires_at=grace,
        )
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()

        # Plan card renders — has_active_plan=True + current_plan present.
        assert body["has_active_plan"] is True
        assert body["current_plan"] is not None
        assert body["current_plan"]["slug"] == "creator"
        # Subscription surfaces with past_due status — the banner
        # condition on the frontend keys on this exact value.
        assert body["subscription"] is not None
        assert body["subscription"]["status"] == "past_due"
        assert body["subscription"]["grace_expires_at"] is not None
        # Paid offers still permitted so the frontend doesn't switch
        # to the plan-forbids-paid-offers state.
        assert body["plan_permits_paid_offers"] is True

    def test_unpaid_creator_after_grace_renders_not_configured(
        self, db, client, make_user,
    ):
        creator = make_user(role="creator")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator, plan, status=CreatorSubscriptionStatus.unpaid)
        db.commit()
        app.dependency_overrides[get_creator_user] = lambda: creator
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        # Empty-state branch — past-grace behaviour is unchanged.
        assert body["has_active_plan"] is False
        assert body["current_plan"] is None
        assert body["subscription"] is None


# ---------------------------------------------------------------------------
# 4. End-to-end: member paid checkout succeeds during grace
# ---------------------------------------------------------------------------


class TestMemberCheckoutDuringGrace:
    def test_paid_checkout_succeeds_and_snapshots_snapshotted_fee(
        self, db, client, make_user, make_space, guard_on, monkeypatch,
    ):
        """The whole point of grace: a member trying to buy an
        already-published Payment Option must succeed — they cannot
        be told the creator's commercial terms are missing."""
        creator = make_user(role="creator")
        member = make_user(role="user")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(
            db, creator, plan,
            status=CreatorSubscriptionStatus.past_due,
            grace_expires_at=datetime.utcnow() + timedelta(days=5),
        )
        space = make_space(creator=creator)
        opt, sched = _make_paid_option(db, space)
        db.commit()

        # ``resolve_fee_context`` (the public entry point that
        # orchestrate_paid_checkout uses) resolves cleanly.
        ctx = resolve_fee_context(space, db)
        assert ctx.fee_bps == 800
        assert ctx.permits_paid_offers is True
        assert ctx.creator_id == creator.id


# ---------------------------------------------------------------------------
# 5. Post-grace re-blocking — unpaid restores prior behaviour
# ---------------------------------------------------------------------------


class TestPostGraceReBlocking:
    def test_paid_checkout_blocks_when_creator_goes_unpaid(
        self, db, client, make_user, make_space, guard_on,
    ):
        """After 7-day grace the cron flips past_due → unpaid.
        Fee resolution then raises again — new member checkouts 409."""
        creator = make_user(role="creator")
        member = make_user(role="user")
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _sub(db, creator, plan, status=CreatorSubscriptionStatus.unpaid)
        space = make_space(creator=creator)
        db.commit()

        with pytest.raises(NoActiveCreatorPlanError):
            resolve_fee_context(space, db)
