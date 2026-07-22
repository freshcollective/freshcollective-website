"""
Tests for ``PATCH /api/admin/creator-plans/{plan_id}`` and the
data-driven ``member_allowance_per_collective`` field on
``AdminCreatorPlanRow``.

The catalogue's member allowance must come from
``PlanCapability.member_allowance_per_collective`` — the same value the
enforcement path reads — so the display and the enforcement rule can
never drift. These tests lock that.

The edit endpoint is guarded so it cannot touch synthesised entries
(Organisation), records a ``PlanChangeEvent`` with a field-level diff
on every successful change, and preserves historical records via the
audit trail rather than mutating past state.
"""

from __future__ import annotations

import uuid

import pytest

from app.admin.routes import (
    edit_creator_plan,
    list_creator_plans,
)
from app.admin.schemas import AdminCreatorPlanEdit
from app.creator.plan_config import PLANS_BY_SLUG
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
    PlanChangeEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_plan(
    db,
    *,
    slug: str = "creator",
    name: str = "Creator",
    price: int = 1900,
    fee_bps: int = 800,
    collective_limit: int = 1,
    is_active: bool = True,
) -> CreatorPlan:
    plan = CreatorPlan(
        id=f"plan_{uuid.uuid4().hex[:8]}",
        name=name,
        slug=slug,
        description="Seeded for tests",
        monthly_price_cents=price,
        currency="AUD",
        transaction_fee_basis_points=fee_bps,
        collective_limit=collective_limit,
        is_active=is_active,
    )
    db.add(plan)
    db.flush()
    return plan


# ---------------------------------------------------------------------------
# 1. member_allowance_per_collective sourced from PlanCapability
# ---------------------------------------------------------------------------


class TestMemberAllowanceFromCapability:
    def test_row_matches_capability_value(self, db, make_user):
        """The catalogue row for Community must expose the same value
        the enforcement path reads (``PlanCapability.member_allowance_per_collective``)."""
        admin = make_user(role="admin")
        # Seed Community with an intentionally wrong collective_limit in
        # the DB — if the frontend/backend were reading `member_allowance`
        # from the DB it would break here.
        _seed_plan(db, slug="community", name="Community", price=0, fee_bps=0, collective_limit=99)

        rows = list_creator_plans(_=admin, db=db)
        community = next(r for r in rows if r.slug == "community")

        # The API's value must equal PlanCapability's — not any DB column.
        expected = PLANS_BY_SLUG["community"].member_allowance_per_collective
        assert community.member_allowance_per_collective == expected
        assert community.member_allowance_per_collective == 100

    def test_creator_row_carries_capability_value(self, db, make_user):
        admin = make_user(role="admin")
        _seed_plan(db, slug="creator", name="Creator", price=1900, fee_bps=800)
        rows = list_creator_plans(_=admin, db=db)
        creator = next(r for r in rows if r.slug == "creator")
        assert creator.member_allowance_per_collective == 500

    def test_pro_capability_value_none_is_preserved(self, db, make_user):
        """Pro uses pooled_member_allowance, so
        ``member_allowance_per_collective`` is None on the capability.
        The API must not silently substitute a number."""
        admin = make_user(role="admin")
        _seed_plan(db, slug="pro", name="Pro", price=7900, fee_bps=300, collective_limit=5)
        rows = list_creator_plans(_=admin, db=db)
        pro = next(r for r in rows if r.slug == "pro")
        assert pro.member_allowance_per_collective is None


# ---------------------------------------------------------------------------
# 2. PATCH endpoint — happy path + audit
# ---------------------------------------------------------------------------


class TestEditPlanHappyPath:
    def test_edit_updates_fields_and_writes_audit_row(self, db, make_user):
        admin = make_user(role="admin", name="Lindsey")
        plan = _seed_plan(db, slug="creator", name="Creator", price=1900, fee_bps=800)

        result = edit_creator_plan(
            plan.id,
            AdminCreatorPlanEdit(
                name="Creator (updated)",
                monthly_price_cents=2200,
                transaction_fee_basis_points=750,
            ),
            admin=admin, db=db,
        )
        assert result.name == "Creator (updated)"
        assert result.monthly_price_cents == 2200
        assert result.transaction_fee_basis_points == 750

        # Audit row records the diff
        events = db.query(PlanChangeEvent).filter_by(plan_id=plan.id).all()
        assert len(events) == 1
        e = events[0]
        assert e.changed_by_user_id == admin.id
        assert set(e.changes.keys()) == {"name", "monthly_price_cents", "transaction_fee_basis_points"}
        assert e.changes["name"] == {"before": "Creator", "after": "Creator (updated)"}
        assert e.changes["monthly_price_cents"] == {"before": 1900, "after": 2200}
        assert e.changes["transaction_fee_basis_points"] == {"before": 800, "after": 750}

    def test_no_op_edit_writes_no_audit_row(self, db, make_user):
        admin = make_user(role="admin")
        plan = _seed_plan(db)
        edit_creator_plan(
            plan.id,
            AdminCreatorPlanEdit(name=plan.name),  # same value
            admin=admin, db=db,
        )
        assert db.query(PlanChangeEvent).filter_by(plan_id=plan.id).count() == 0

    def test_partial_edit_only_updates_supplied_fields(self, db, make_user):
        admin = make_user(role="admin")
        plan = _seed_plan(db, price=1900, fee_bps=800)
        edit_creator_plan(
            plan.id,
            AdminCreatorPlanEdit(monthly_price_cents=2500),
            admin=admin, db=db,
        )
        db.refresh(plan)
        assert plan.monthly_price_cents == 2500
        assert plan.transaction_fee_basis_points == 800   # unchanged


# ---------------------------------------------------------------------------
# 3. Guards — synthetic + not-found + validation
# ---------------------------------------------------------------------------


class TestEditPlanGuards:
    def test_synthetic_id_refused(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as e:
            edit_creator_plan(
                "synthetic-organisation",
                AdminCreatorPlanEdit(name="Attempt"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_unknown_id_returns_404(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as e:
            edit_creator_plan(
                "plan_missing",
                AdminCreatorPlanEdit(name="X"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 404

    def test_negative_price_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        plan = _seed_plan(db)
        with pytest.raises(HTTPException) as e:
            edit_creator_plan(
                plan.id,
                AdminCreatorPlanEdit(monthly_price_cents=-1),
                admin=admin, db=db,
            )
        assert e.value.status_code == 422

    def test_out_of_range_fee_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        plan = _seed_plan(db)
        with pytest.raises(HTTPException):
            edit_creator_plan(
                plan.id, AdminCreatorPlanEdit(transaction_fee_basis_points=-1),
                admin=admin, db=db,
            )
        with pytest.raises(HTTPException):
            edit_creator_plan(
                plan.id, AdminCreatorPlanEdit(transaction_fee_basis_points=10001),
                admin=admin, db=db,
            )

    def test_collective_limit_below_one_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        plan = _seed_plan(db)
        with pytest.raises(HTTPException) as e:
            edit_creator_plan(
                plan.id, AdminCreatorPlanEdit(collective_limit=0),
                admin=admin, db=db,
            )
        assert e.value.status_code == 422

    def test_empty_name_rejected(self, db, make_user):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        plan = _seed_plan(db)
        with pytest.raises(HTTPException):
            edit_creator_plan(
                plan.id, AdminCreatorPlanEdit(name="   "),
                admin=admin, db=db,
            )


# ---------------------------------------------------------------------------
# 4. Subscription integrity across edit
# ---------------------------------------------------------------------------


class TestSubscriptionsSurviveEdit:
    def test_existing_subscription_still_resolves_edited_plan(
        self, db, make_user,
    ):
        """Editing a plan must not silently move creators between plans
        or damage historical subscription rows."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = _seed_plan(db, slug="creator")
        sub = CreatorSubscription(
            id=str(uuid.uuid4()),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            source="stripe_paid",
        )
        db.add(sub)
        db.flush()

        edit_creator_plan(
            plan.id,
            AdminCreatorPlanEdit(monthly_price_cents=3900),
            admin=admin, db=db,
        )

        db.refresh(sub)
        assert sub.creator_plan_id == plan.id
        assert sub.status == CreatorSubscriptionStatus.active
