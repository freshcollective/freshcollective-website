"""Stage 3 — creator plan activation domain service.

Covers:
  * Fresh activation via ``stripe_paid`` source (new subscription row
    + promote_to_creator + World Builders auto-enrol + audit + notification).
  * Fresh activation via ``manual_grant`` source (parity with the
    pre-refactor admin flow).
  * Idempotent no-op when the user already has an active subscription
    on the same plan.
  * Reactivation of a cancelled subscription of the same source.
  * Conflict when the user has an active subscription on a *different*
    plan.
  * ``promote_to_creator`` primitive on its own.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.admin.service import promote_to_creator
from app.creator.plan_activation import (
    ActivationConflictError,
    ActivationSource,
    UnknownCreatorPlanError,
    activate_creator_plan,
)
from app.models.creator_billing import (
    CreatorPlan,
    CreatorPlanGrant,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.platform import Space, SpaceMembership
from app.models.user import UserRole
# Import brings community_care models into SQLAlchemy metadata so the
# User model's FK to community_care_actions resolves at flush time.
# The webhook + claim tests exercise the same code path; they trigger
# the graph load through their broader import chain (spaces.routes),
# so no equivalent line is needed there.
import app.models.community_care  # noqa: F401
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _plans(db):
    for slug, price, fee_bps, cap in (
        ("creator", 1900, 800, 1),
        ("pro", 7900, 300, 5),
    ):
        if db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first() is None:
            db.add(CreatorPlan(
                id=f"cp_{slug}",
                name=slug.title(),
                slug=slug,
                monthly_price_cents=price,
                transaction_fee_basis_points=fee_bps,
                collective_limit=cap,
                is_active=True,
            ))
    db.flush()


@pytest.fixture
def world_builders(db, make_user):
    """Ensure a World-Builders-style Space exists so the eligibility
    reconciler has something to enrol into."""
    owner = make_user(role="admin")
    space = Space(
        id=f"s_wb_{uuid.uuid4().hex[:8]}",
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        name="World Builders",
        status="active",
        is_public=False,
        creator_id=owner.id,
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


# ---------------------------------------------------------------------------
# promote_to_creator primitive
# ---------------------------------------------------------------------------


class TestPromoteToCreator:
    def test_promotes_role_and_enrols_in_world_builders(
        self, db, make_user, world_builders,
    ):
        user = make_user(role="user")
        assert user.role == "user"

        promote_to_creator(user, db)
        db.flush()

        assert user.role == "creator"
        wb_membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == world_builders.id,
                SpaceMembership.source == "auto_role",
            )
            .first()
        )
        assert wb_membership is not None
        assert wb_membership.status == "active"

    def test_idempotent_when_already_creator(self, db, make_user, world_builders):
        user = make_user(role="creator")
        promote_to_creator(user, db)
        db.flush()
        # Reconciler is idempotent for *this* fixture's WB space.
        # (Migration 095 seeds a permanent WB row too; that's a
        # separate space and is orthogonal to this test's assertion.)
        wb = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == world_builders.id,
            SpaceMembership.source == "auto_role",
        ).all()
        assert len(wb) == 1


# ---------------------------------------------------------------------------
# activate_creator_plan — happy paths
# ---------------------------------------------------------------------------


class TestFreshActivationStripe:
    def test_new_subscription_created_with_stripe_paid_source(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user")
        result = activate_creator_plan(
            db, user, "creator",
            ActivationSource(
                source="stripe_paid",
                stripe_subscription_id="sub_test_123",
                stripe_customer_id="cus_test_456",
            ),
        )
        db.flush()

        sub = result.subscription
        assert sub.source == "stripe_paid"
        assert sub.status == CreatorSubscriptionStatus.active
        assert sub.stripe_subscription_id == "sub_test_123"
        assert sub.stripe_customer_id == "cus_test_456"
        assert sub.granted_by_user_id is None
        assert sub.grant_reason is None
        assert not result.was_reactivated
        assert not result.was_noop

    def test_activation_promotes_user_and_enrols_in_world_builders(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user")
        activate_creator_plan(
            db, user, "creator",
            ActivationSource(source="stripe_paid"),
        )
        db.flush()
        assert user.role == "creator"
        wb = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == world_builders.id,
        ).first()
        assert wb is not None
        assert wb.status == "active"

    def test_records_grant_audit_row(self, db, make_user, _plans, world_builders):
        user = make_user(role="user")
        result = activate_creator_plan(
            db, user, "pro",
            ActivationSource(source="stripe_paid"),
        )
        db.flush()
        grants = db.query(CreatorPlanGrant).filter(
            CreatorPlanGrant.subscription_id == result.subscription.id,
        ).all()
        assert len(grants) == 1
        assert grants[0].action == "granted"

    def test_sends_welcome_notification(self, db, make_user, _plans, world_builders):
        user = make_user(role="user")
        activate_creator_plan(
            db, user, "creator",
            ActivationSource(source="stripe_paid"),
        )
        db.flush()
        # Raw SQL query — the Notification model's FK graph pulls in
        # community_care_actions which isn't imported in this test
        # context.
        rows = db.execute(
            text(
                "SELECT notification_type FROM notifications "
                "WHERE user_id = :uid"
            ),
            {"uid": user.id},
        ).fetchall()
        assert any(r.notification_type == "creator_plan_granted_by_stripe" for r in rows)


class TestFreshActivationManualGrant:
    def test_new_subscription_created_with_manual_grant_source(
        self, db, make_user, _plans, world_builders,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="user")
        result = activate_creator_plan(
            db, creator, "creator",
            ActivationSource(
                source="manual_grant",
                reason="comp",
                note="Beta partner",
                actor_user_id=admin.id,
            ),
        )
        db.flush()
        sub = result.subscription
        assert sub.source == "manual_grant"
        assert sub.grant_reason == "comp"
        assert sub.grant_note == "Beta partner"
        assert sub.granted_by_user_id == admin.id
        assert creator.role == "creator"


# ---------------------------------------------------------------------------
# activate_creator_plan — idempotency / conflict
# ---------------------------------------------------------------------------


class TestIdempotencyAndConflict:
    def test_repeat_activation_same_plan_is_noop(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user")
        first = activate_creator_plan(
            db, user, "creator", ActivationSource(source="stripe_paid"),
        )
        db.flush()
        second = activate_creator_plan(
            db, user, "creator", ActivationSource(source="stripe_paid"),
        )
        db.flush()

        assert second.was_noop is True
        assert second.subscription.id == first.subscription.id
        # Only one grant row for one activation event.
        grants = db.query(CreatorPlanGrant).filter(
            CreatorPlanGrant.subscription_id == first.subscription.id,
        ).all()
        assert len(grants) == 1

    def test_conflict_on_different_active_plan(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user")
        activate_creator_plan(
            db, user, "creator", ActivationSource(source="stripe_paid"),
        )
        db.flush()

        with pytest.raises(ActivationConflictError):
            activate_creator_plan(
                db, user, "pro", ActivationSource(source="stripe_paid"),
            )

    def test_reactivates_cancelled_subscription_of_same_source(
        self, db, make_user, _plans, world_builders,
    ):
        user = make_user(role="user")
        first = activate_creator_plan(
            db, user, "creator", ActivationSource(source="stripe_paid"),
        )
        db.flush()
        # Cancel it (simulating the future cancel flow).
        first.subscription.status = CreatorSubscriptionStatus.cancelled
        db.flush()

        second = activate_creator_plan(
            db, user, "creator", ActivationSource(source="stripe_paid"),
        )
        db.flush()

        assert second.was_reactivated is True
        assert second.subscription.id == first.subscription.id
        assert second.subscription.status == CreatorSubscriptionStatus.active

    def test_unknown_plan_raises(self, db, make_user):
        user = make_user()
        with pytest.raises(UnknownCreatorPlanError):
            activate_creator_plan(
                db, user, "nonexistent",
                ActivationSource(source="stripe_paid"),
            )
