"""Regression: creator-eligibility reconciler must not INSERT a
duplicate auto_role SpaceMembership when the user already has a
membership in an auto-grant Space via a different ``source``.

Reproduces the production 500 hit on 2026-09-15 when assigning a
Creator Plan to the Fresh Collective founder — she was already a
member of the World Builders Space (via ``source='creator_owner'``),
and ``apply_creator_eligibility_change`` unconditionally attempted to
INSERT a competing ``source='auto_role'`` row, violating the unique
constraint ``space_memberships_user_space_unique (user_id, space_id)``
which spans every source value.

Guard-under-test:
  * ``_has_any_membership`` in
    ``backend/app/services/creator_eligibility.py`` — a short-circuit
    that skips the INSERT when any membership row already exists for
    (user, space), regardless of source. Non-auto_role rows remain
    off-limits to the reconciler per its module docstring; the guard
    just prevents the reconciler from stepping on them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import UserRole
from app.services.creator_eligibility import (
    AUTO_ROLE_SOURCE,
    apply_creator_eligibility_change,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_auto_grant_space(db, owner) -> Space:
    space = Space(
        id=_uid("s"),
        slug=f"auto-grant-{uuid.uuid4().hex[:6]}",
        name="Auto-Grant Space",
        status="active",
        is_public=False,
        creator_id=owner.id,
        # Every user with role='creator' should auto-grant into here.
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


class TestReconcilerIdempotency:
    def test_skips_insert_when_creator_owner_row_already_exists(
        self, db, make_user,
    ):
        """The production case — Lindsey owns the auto-grant Space, so
        she already has a ``source='creator_owner'`` membership. The
        reconciler must NOT try to INSERT a competing auto_role row."""
        owner = make_user(role="creator")
        space = _make_auto_grant_space(db, owner)

        # Simulate the creator_owner membership that Space creation
        # normally creates elsewhere in the codebase.
        db.add(SpaceMembership(
            id=_uid("mem"),
            user_id=owner.id,
            space_id=space.id,
            role=SpaceRole.creator,
            status=SpaceMembershipStatus.active,
            source="creator_owner",
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        # This must not raise UniqueViolation.
        apply_creator_eligibility_change(owner, db)
        db.commit()

        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == owner.id,
                SpaceMembership.space_id == space.id,
            )
            .all()
        )
        assert len(rows) == 1
        # The creator_owner row was left untouched — the reconciler is
        # explicitly not authorised to sweep non-auto_role rows.
        assert rows[0].source == "creator_owner"

    def test_skips_insert_when_joined_row_already_exists(
        self, db, make_user,
    ):
        """A user who manually joined an auto-grant Space before being
        promoted to Creator has a ``source='joined'`` row. The
        reconciler must skip the auto_role INSERT — same reason."""
        user = make_user(role="creator")
        other = make_user(role="creator")   # some other owner
        space = _make_auto_grant_space(db, other)

        db.add(SpaceMembership(
            id=_uid("mem"),
            user_id=user.id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        apply_creator_eligibility_change(user, db)
        db.commit()

        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source == "joined"

    def test_inserts_auto_role_when_no_prior_membership_exists(
        self, db, make_user,
    ):
        """Baseline: a creator with no existing membership in the
        auto-grant Space gets a fresh auto_role row inserted. The
        idempotency guard must not accidentally suppress this case."""
        creator = make_user(role="creator")
        other = make_user(role="creator")
        space = _make_auto_grant_space(db, other)
        db.commit()

        apply_creator_eligibility_change(creator, db)
        db.commit()

        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == creator.id,
                SpaceMembership.space_id == space.id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source == AUTO_ROLE_SOURCE
        assert rows[0].status == SpaceMembershipStatus.active

    def test_reactivates_existing_auto_role_row(
        self, db, make_user,
    ):
        """When an auto_role row already exists in a non-active status,
        the reconciler UPDATEs it back to active — no INSERT."""
        creator = make_user(role="creator")
        other = make_user(role="creator")
        space = _make_auto_grant_space(db, other)

        db.add(SpaceMembership(
            id=_uid("mem"),
            user_id=creator.id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.removed,
            source=AUTO_ROLE_SOURCE,
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        apply_creator_eligibility_change(creator, db)
        db.commit()

        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == creator.id,
                SpaceMembership.space_id == space.id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source == AUTO_ROLE_SOURCE
        assert rows[0].status == SpaceMembershipStatus.active


class TestPlanChangePreservesOwnerMembership:
    """End-to-end: the atomic Change Plan endpoint must succeed when
    the target creator is already a member (via creator_owner) of an
    auto-grant Space. This is the exact production 500 case."""

    def test_change_plan_succeeds_when_creator_owns_auto_grant_space(
        self, db, client, make_user, make_space,
    ):
        from app.auth.dependencies import get_admin_user
        from app.main import app
        from app.models.creator_billing import (
            CreatorPlan,
            CreatorSubscription,
            CreatorSubscriptionStatus,
        )

        # Seed a "creator" plan and grant it to a creator.
        plan = db.query(CreatorPlan).filter(CreatorPlan.slug == "creator").first()
        if plan is None:
            plan = CreatorPlan(
                id=_uid("cp"),
                name="Creator",
                slug="creator",
                monthly_price_cents=1900,
                transaction_fee_basis_points=800,
                collective_limit=1,
                is_active=True,
            )
            db.add(plan)
            db.flush()

        target_plan = (
            db.query(CreatorPlan).filter(CreatorPlan.slug == "founding-creator").first()
        )
        if target_plan is None:
            target_plan = CreatorPlan(
                id=_uid("cp"),
                name="Founding Creator",
                slug="founding-creator",
                monthly_price_cents=0,
                transaction_fee_basis_points=0,
                collective_limit=1,
                is_active=True,
            )
            db.add(target_plan)
            db.flush()

        creator = make_user(role="creator")
        admin = make_user(role="admin")

        # An auto-grant Space (the World-Builders shape) which the
        # creator already owns — hence a source='creator_owner' row.
        auto_space = _make_auto_grant_space(db, creator)
        db.add(SpaceMembership(
            id=_uid("mem"),
            user_id=creator.id,
            space_id=auto_space.id,
            role=SpaceRole.creator,
            status=SpaceMembershipStatus.active,
            source="creator_owner",
            joined_at=datetime.utcnow(),
        ))

        # Grant them the initial Creator plan.
        db.add(CreatorSubscription(
            id=_uid("sub"),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="manual_grant",
        ))
        db.commit()

        app.dependency_overrides[get_admin_user] = lambda: admin
        try:
            res = client.post(
                f"/api/admin/creators/{creator.id}/plan/change",
                json={
                    "plan_slug": "founding-creator",
                    "reason": "comp",
                    "note": "founder terms",
                    "duration": "indefinite",
                },
            )
            # The exact production 500 must now succeed.
            assert res.status_code == 200, res.text

            # The creator_owner row is untouched — no duplicate auto_role.
            rows = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.user_id == creator.id,
                    SpaceMembership.space_id == auto_space.id,
                )
                .all()
            )
            assert len(rows) == 1
            assert rows[0].source == "creator_owner"

            # New CreatorSubscription is on the target plan.
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
            assert active[0].creator_plan_id == target_plan.id
        finally:
            app.dependency_overrides.pop(get_admin_user, None)


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.core.database import get_db
    from app.main import app

    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
