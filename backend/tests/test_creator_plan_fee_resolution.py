"""Fee resolution + missing-plan guard + atomic plan-change.

Covers:

* :func:`resolve_fee_context` short-circuits to fee_bps=0 on
  platform-owned Spaces (creator_id IS NULL).
* :func:`_resolve_fee_bps_for_creator` raises
  :class:`NoActiveCreatorPlanError` when the creator has no
  active/trialing subscription AND the guard flag is on.
* The same missing-plan condition falls back to fee_bps=0 with a
  WARNING log when the guard flag is off (grace mode used during the
  deploy that removes the cheapest-plan fallback).
* Explicit 0% plan (e.g. Founding Creator) resolves normally when
  active — no exception.
* Every checkout entry point translates the exception to HTTP 409.
* Community plan (paid_offers_enabled=False) triggers HTTP 403 at
  paid checkout via :class:`PlanForbidsPaidOffersError`.
* Admin slug allowlist blocks admin plan creation with an
  unrecognised slug.
* Atomic Change-Plan endpoint revokes the current sub + grants the
  new one in one transaction, and refuses downgrades that would
  exceed the destination plan's active-Collective limit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_admin_user, get_creator_user
from app.core.config import settings
from app.core.database import get_db
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
from app.models.platform import Space
from app.services.checkout_orchestration import (
    NoActiveCreatorPlanError,
    PlanForbidsPaidOffersError,
    _resolve_fee_bps_for_creator,
    resolve_fee_context,
    try_resolve_fee_context,
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
    app.dependency_overrides.pop(get_admin_user, None)


def _ensure_plan(db, *, slug: str, fee_bps: int, price: int = 0) -> CreatorPlan:
    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
    if plan:
        return plan
    plan = CreatorPlan(
        id=_uid("cp"),
        name=slug.title(),
        slug=slug,
        monthly_price_cents=price,
        transaction_fee_basis_points=fee_bps,
        collective_limit=1 if slug != "founding-creator" else 99,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def _grant_sub(db, user, plan) -> CreatorSubscription:
    sub = CreatorSubscription(
        id=_uid("sub"),
        user_id=user.id,
        creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active,
        starts_at=datetime.utcnow(),
        source="manual_grant",
    )
    db.add(sub)
    db.flush()
    return sub


@pytest.fixture
def guard_on(monkeypatch):
    monkeypatch.setattr(settings, "creator_plan_guard_enabled", True)


@pytest.fixture
def guard_off(monkeypatch):
    monkeypatch.setattr(settings, "creator_plan_guard_enabled", False)


class TestResolveFeeContext:
    def test_platform_owned_returns_zero_fee(self, db, make_user, guard_on):
        # ``space.creator_id IS NULL`` — Fresh Collective owns it.
        space = Space(
            id=_uid("s"),
            slug=f"platform-{uuid.uuid4().hex[:6]}",
            name="Platform Space",
            status="active",
            creator_id=None,
        )
        db.add(space)
        db.commit()

        ctx = resolve_fee_context(space, db)
        assert ctx.is_platform_owned is True
        assert ctx.fee_bps == 0
        assert ctx.creator_plan_id is None
        assert ctx.permits_paid_offers is True

    def test_active_plan_returns_its_fee(
        self, db, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(db, creator, plan)
        db.commit()

        ctx = resolve_fee_context(space, db)
        assert ctx.fee_bps == 800
        assert ctx.creator_plan_id == plan.id
        assert ctx.permits_paid_offers is True

    def test_missing_plan_raises_when_guard_on(
        self, db, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        with pytest.raises(NoActiveCreatorPlanError):
            resolve_fee_context(space, db)

    def test_missing_plan_falls_back_to_zero_when_guard_off(
        self, db, make_user, make_space, guard_off,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        ctx = resolve_fee_context(space, db)
        assert ctx.fee_bps == 0
        assert ctx.creator_plan_id is None
        # Grace mode preserves current EMBODY behaviour — permits
        # paid offers so existing member checkout still works.
        assert ctx.permits_paid_offers is True

    def test_community_plan_permits_paid_offers_false(
        self, db, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        plan = _ensure_plan(db, slug="community", fee_bps=0, price=0)
        _grant_sub(db, creator, plan)
        db.commit()
        ctx = resolve_fee_context(space, db)
        assert ctx.permits_paid_offers is False

    def test_founding_creator_permits_paid_offers_at_zero_percent(
        self, db, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        plan = _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0)
        _grant_sub(db, creator, plan)
        db.commit()
        ctx = resolve_fee_context(space, db)
        assert ctx.fee_bps == 0
        assert ctx.permits_paid_offers is True

    def test_try_resolve_returns_none_on_missing_plan(
        self, db, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        assert try_resolve_fee_context(space, db) is None


class TestResolveFeeBpsFallbacksRemoved:
    def test_no_cheapest_plan_fallback(
        self, db, make_user, guard_on,
    ):
        # Deliberately seed a plan with a distinctive fee value —
        # if the cheapest-plan fallback still existed we'd get it here.
        creator = make_user(role="creator")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        # Creator has no subscription; guard on → raises. No fallback.
        with pytest.raises(NoActiveCreatorPlanError):
            _resolve_fee_bps_for_creator(creator.id, db)

    def test_no_hardcoded_800_fallback(
        self, db, make_user, guard_on,
    ):
        # No plans in DB at all — historically returned 800 bps.
        creator = make_user(role="creator")
        # Delete any existing seeded plans (may exist from bootstrap).
        db.query(CreatorPlan).delete()
        db.commit()
        with pytest.raises(NoActiveCreatorPlanError):
            _resolve_fee_bps_for_creator(creator.id, db)


class TestPaidCheckoutGuard:
    """The unified paid-checkout entry point must translate
    :class:`NoActiveCreatorPlanError` to HTTP 409 and
    :class:`PlanForbidsPaidOffersError` (via
    ``fee_context.permits_paid_offers=False``) to HTTP 403."""

    def _make_paid_option(self, db, space):
        opt = PaymentOption(
            id=_uid("po"),
            space_id=space.id,
            attaches_to_kind="space",
            attaches_to_id=space.id,
            name="Test Option",
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

    def test_paid_checkout_returns_409_when_creator_has_no_plan(
        self, db, client, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        opt, sched = self._make_paid_option(db, space)
        member = make_user(role="user")
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: member
        # Simulate the unified checkout call via the shared orchestrator.
        from app.services.checkout_orchestration import (
            ResolvedOption,
            orchestrate_paid_checkout,
        )
        from fastapi import HTTPException

        resolved = ResolvedOption(
            payment_option=opt,
            payment_schedule=sched,
            space=space,
            price_cents=sched.total_amount_cents or 10_000,
            currency="AUD",
        )
        with pytest.raises(HTTPException) as exc:
            orchestrate_paid_checkout(
                db=db,
                resolved=resolved,
                payer=member,
                success_url="https://example.test/success",
                cancel_url="https://example.test/cancel",
                now=datetime.utcnow(),
            )
        assert exc.value.status_code == 409
        assert "commercial terms" in exc.value.detail.lower()

    def test_paid_checkout_returns_403_on_community_plan(
        self, db, client, make_user, make_space, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        plan = _ensure_plan(db, slug="community", fee_bps=0, price=0)
        _grant_sub(db, creator, plan)
        opt, sched = self._make_paid_option(db, space)
        member = make_user(role="user")
        db.commit()

        from app.services.checkout_orchestration import (
            ResolvedOption,
            orchestrate_paid_checkout,
        )
        from fastapi import HTTPException

        resolved = ResolvedOption(
            payment_option=opt,
            payment_schedule=sched,
            space=space,
            price_cents=sched.total_amount_cents or 10_000,
            currency="AUD",
        )
        with pytest.raises(HTTPException) as exc:
            orchestrate_paid_checkout(
                db=db,
                resolved=resolved,
                payer=member,
                success_url="https://example.test/success",
                cancel_url="https://example.test/cancel",
                now=datetime.utcnow(),
            )
        assert exc.value.status_code == 403
        assert "paid offers" in exc.value.detail.lower()


class TestAdminSlugAllowlist:
    def test_reject_unrecognised_slug(self, db, client, make_user):
        admin = make_user(role="admin")
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            "/api/admin/creator-plans",
            json={
                "name": "Bogus Tier",
                "slug": "creator-vip",   # not in RECOGNISED_PLAN_SLUGS
                "description": None,
                "monthly_price_cents": 9900,
                "currency": "AUD",
                "transaction_fee_basis_points": 500,
                "collective_limit": 3,
                "is_active": True,
            },
        )
        assert res.status_code == 422
        assert "recognised" in res.text.lower()

    def test_accept_recognised_slug(self, db, client, make_user):
        admin = make_user(role="admin")
        # Make sure founding-creator doesn't already exist in test DB.
        db.query(CreatorPlan).filter(CreatorPlan.slug == "founding-creator").delete()
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            "/api/admin/creator-plans",
            json={
                "name": "Founding Creator",
                "slug": "founding-creator",
                "description": "Founder terms",
                "monthly_price_cents": 0,
                "currency": "AUD",
                "transaction_fee_basis_points": 0,
                "collective_limit": 1,
                "is_active": True,
            },
        )
        assert res.status_code == 201, res.text


class TestAtomicPlanChange:
    def test_change_plan_revokes_current_and_grants_new(
        self, db, client, make_user,
    ):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        old_plan = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        new_plan = _ensure_plan(db, slug="pro", fee_bps=300, price=7900)
        _grant_sub(db, creator, old_plan)
        db.commit()

        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            f"/api/admin/creators/{creator.id}/plan/change",
            json={
                "plan_slug": "pro",
                "reason": "replacement",
                "note": "upgrade",
                "duration": "indefinite",
            },
        )
        assert res.status_code == 200, res.text

        # Exactly one active sub, on the new plan. The existing
        # activation service (``_create_or_reactivate``) reuses the
        # just-cancelled row and flips its plan_id to the new plan,
        # so the "one row per user" invariant holds and the audit
        # trail lives on CreatorPlanGrant, not on the CreatorSubscription
        # itself.
        active = (
            db.query(CreatorSubscription)
            .filter(
                CreatorSubscription.user_id == creator.id,
                CreatorSubscription.status.in_([
                    CreatorSubscriptionStatus.active,
                    CreatorSubscriptionStatus.trialing,
                ]),
            )
            .all()
        )
        assert len(active) == 1
        assert active[0].creator_plan_id == new_plan.id

        # Audit trail preserves the revoke + grant events.
        from app.models.creator_billing import CreatorPlanGrant
        audit = (
            db.query(CreatorPlanGrant)
            .filter(CreatorPlanGrant.subscription_id == active[0].id)
            .order_by(CreatorPlanGrant.created_at.asc())
            .all()
        )
        actions = [row.action for row in audit]
        # Grant for the original plan + revoke + new grant. Order:
        # earliest first.
        assert "revoked" in actions
        assert "granted" in actions

    def test_change_plan_from_none_grants_new(
        self, db, client, make_user,
    ):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            f"/api/admin/creators/{creator.id}/plan/change",
            json={
                "plan_slug": "creator",
                "reason": "correction",
                "duration": "indefinite",
            },
        )
        assert res.status_code == 200, res.text

    def test_downgrade_over_limit_refused(
        self, db, client, make_user, make_space,
    ):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        pro = _ensure_plan(db, slug="pro", fee_bps=300, price=7900)
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        _grant_sub(db, creator, pro)
        # Create 3 active Collectives for the creator — Pro allows 5,
        # Creator allows 1. Downgrade must refuse.
        for _ in range(3):
            make_space(creator=creator)
        db.commit()

        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            f"/api/admin/creators/{creator.id}/plan/change",
            json={
                "plan_slug": "creator",
                "reason": "replacement",
                "duration": "indefinite",
            },
        )
        assert res.status_code == 409
        assert "collective" in res.text.lower()

    def test_change_plan_reason_other_requires_note(
        self, db, client, make_user,
    ):
        creator = make_user(role="creator")
        admin = make_user(role="admin")
        _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        db.commit()
        app.dependency_overrides[get_admin_user] = lambda: admin
        res = client.post(
            f"/api/admin/creators/{creator.id}/plan/change",
            json={
                "plan_slug": "creator",
                "reason": "other",
                "duration": "indefinite",
                # note deliberately absent
            },
        )
        assert res.status_code == 422


class TestBillingResponseAdminWithPlan:
    """``GET /api/creator/billing`` must reflect an admin's active
    CreatorSubscription in ``current_plan`` — not silently hide it
    behind the Platform Owner short-circuit.

    Regression: production incident 2026-09-15 where Lindsey's
    freshly-assigned Founding Creator sub returned in the DB but the
    Creator Studio Billing card still showed 'Platform Owner — no
    creator subscription plan attached'.
    """

    def test_admin_with_active_sub_reports_plan_and_platform_owner(
        self, db, client, make_user,
    ):
        admin = make_user(role="admin")
        plan = _ensure_plan(db, slug="founding-creator", fee_bps=0, price=0)
        _grant_sub(db, admin, plan)
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: admin
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()

        # Both signals are true — dual status is preserved.
        assert body["is_platform_owner"] is True
        assert body["has_active_plan"] is True
        # And the plan card actually renders the founding-creator row.
        assert body["current_plan"] is not None
        assert body["current_plan"]["slug"] == "founding-creator"
        assert body["current_plan"]["transaction_fee_basis_points"] == 0
        assert body["current_plan"]["monthly_price_cents"] == 0
        # Subscription is populated (not None as in the historical
        # admin-only branch).
        assert body["subscription"] is not None

    def test_admin_without_sub_still_gets_platform_owner_branch(
        self, db, client, make_user,
    ):
        # Admin with no CreatorSubscription — historical behaviour
        # remains: current_plan=None, is_platform_owner=True.
        admin = make_user(role="admin")
        db.commit()

        app.dependency_overrides[get_creator_user] = lambda: admin
        res = client.get("/api/creator/billing")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["is_platform_owner"] is True
        assert body["current_plan"] is None
        assert body["subscription"] is None
        # ``has_active_plan`` stays True — admin always transacts.
        assert body["has_active_plan"] is True


class TestUniqueActiveSubIndex:
    def test_second_active_grant_fails_at_db_level(
        self, db, make_user,
    ):
        # Attempts to insert two active subs for the same user must
        # be rejected by the partial UNIQUE index added in migration 130.
        creator = make_user(role="creator")
        plan_a = _ensure_plan(db, slug="creator", fee_bps=800, price=1900)
        plan_b = _ensure_plan(db, slug="pro", fee_bps=300, price=7900)
        _grant_sub(db, creator, plan_a)
        # Second active sub — same user, different plan, both active.
        db.add(CreatorSubscription(
            id=_uid("sub"),
            user_id=creator.id,
            creator_plan_id=plan_b.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="manual_grant",
        ))
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
