"""World Builders — auto-grant access lifecycle tests.

Covers the ``services.creator_eligibility`` reconciler + the route
guards that keep an auto-grant collective off the public join flow.

The reconciler is the beating heart of the feature; each of the
lifecycle transitions in its docstring is exercised here as a
separate test. The route guards are tested by direct FastAPI
handler calls (matching the pattern used elsewhere in this suite).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.admin.service import set_user_role
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
    is_eligible_creator,
    reconcile_at_session_time,
)
from app.creator.routes import update_space
from app.creator.schemas import SpaceUpdateRequest
from app.spaces.routes import join_space, list_public_spaces


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world_builders(db, make_user):
    """Create a World-Builders-style auto-grant space owned by an admin.
    Not necessarily slug='world-builders' — the reconciler discovers
    the space by ``auto_grant_role``, not by slug."""
    owner = make_user(role="admin")
    space = Space(
        id=f"s_{uuid.uuid4().hex[:12]}",
        slug=f"wb-{uuid.uuid4().hex[:8]}",
        name="World Builders",
        status="draft",
        is_public=False,
        creator_id=owner.id,
        auto_grant_role=UserRole.creator.value,
    )
    db.add(space)
    db.flush()
    return space


def _get_membership(db, user_id: str, space_id: str) -> SpaceMembership | None:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
        )
        .first()
    )


# ---------------------------------------------------------------------------
# is_eligible_creator predicate
# ---------------------------------------------------------------------------


class TestEligibilityPredicate:
    def test_active_creator_is_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="creator")) is True

    def test_plain_user_is_not_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="user")) is False

    def test_admin_is_not_eligible(self, make_user):
        assert is_eligible_creator(make_user(role="admin")) is False

    def test_suspended_creator_is_not_eligible(self, make_user):
        u = make_user(role="creator", creator_suspended_at=datetime.utcnow())
        assert is_eligible_creator(u) is False

    def test_cancelled_creator_is_not_eligible(self, make_user):
        u = make_user(role="creator", creator_cancelled_at=datetime.utcnow())
        assert is_eligible_creator(u) is False


# ---------------------------------------------------------------------------
# Lifecycle reconciliation
# ---------------------------------------------------------------------------


class TestReconciliationLifecycle:
    def test_eligible_creator_gets_active_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active
        assert m.role == SpaceRole.learner
        assert m.source == AUTO_ROLE_SOURCE

    def test_reconciler_is_idempotent(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        rows = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == creator.id,
                SpaceMembership.space_id == world_builders.id,
            )
            .all()
        )
        assert len(rows) == 1

    def test_suspension_pauses_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_suspended_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.paused

    def test_lifting_suspension_reactivates_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator", creator_suspended_at=datetime.utcnow())
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_suspended_at = None
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active

    def test_cancellation_removes_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_cancelled_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed

    def test_role_change_removes_membership(self, db, make_user, world_builders):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.role = "user"
        apply_creator_eligibility_change(creator, db)
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed

    def test_cancellation_then_restore_reactivates_same_row(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        first = _get_membership(db, creator.id, world_builders.id)
        first_id = first.id

        creator.creator_cancelled_at = datetime.utcnow()
        apply_creator_eligibility_change(creator, db)
        db.flush()

        creator.creator_cancelled_at = None
        apply_creator_eligibility_change(creator, db)
        db.flush()
        second = _get_membership(db, creator.id, world_builders.id)
        assert second.id == first_id
        assert second.status == SpaceMembershipStatus.active

    def test_non_auto_role_membership_is_never_touched(
        self, db, make_user, world_builders
    ):
        """A pre-existing 'joined' or 'invited' membership must survive
        every reconciler pass, including role-change removals."""
        creator = make_user(role="creator")
        explicit = SpaceMembership(
            id=f"m_{uuid.uuid4().hex[:12]}",
            user_id=creator.id,
            space_id=world_builders.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
        )
        db.add(explicit)
        db.flush()

        # Role change to 'user' should NOT sweep the explicit membership.
        creator.role = "user"
        apply_creator_eligibility_change(creator, db)
        db.flush()
        db.refresh(explicit)
        assert explicit.status == SpaceMembershipStatus.active
        assert explicit.source == "joined"


# ---------------------------------------------------------------------------
# Route guards
# ---------------------------------------------------------------------------


class TestJoinIsRefused:
    def test_join_returns_403_on_auto_grant_space(
        self, db, make_user, world_builders
    ):
        # The endpoint filters by status=='active'; the auto-grant space
        # starts as 'draft' so we flip it to active for this test only.
        world_builders.status = "active"
        db.flush()
        stranger = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            join_space(slug=world_builders.slug, db=db, current_user=stranger)
        assert e.value.status_code == 403
        assert "automatically" in e.value.detail.lower()


class TestPublicListExcludesAutoGrant:
    def test_auto_grant_space_hidden_from_public_list(
        self, db, world_builders, make_space
    ):
        # A normal public collective should still appear.
        normal = make_space(is_public=True, status="active")
        world_builders.status = "active"
        world_builders.is_public = True  # even if is_public, auto_grant hides it
        db.flush()

        rows = list_public_spaces(db=db)
        ids = {r.id for r in rows}
        assert normal.id in ids
        assert world_builders.id not in ids


# ---------------------------------------------------------------------------
# Admin role change wires into the reconciler
# ---------------------------------------------------------------------------


class TestAdminRoleChangeReconciles:
    def test_setting_creator_to_user_removes_auto_role_membership(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        apply_creator_eligibility_change(creator, db)
        db.flush()
        assert _get_membership(db, creator.id, world_builders.id).status \
            == SpaceMembershipStatus.active

        set_user_role(db, creator.id, "user")
        db.flush()
        m = _get_membership(db, creator.id, world_builders.id)
        assert m.status == SpaceMembershipStatus.removed


# ---------------------------------------------------------------------------
# Session-time reconciler short-circuit
# ---------------------------------------------------------------------------


class TestUpdateSpaceGuards:
    def test_editable_field_change_is_allowed_on_auto_managed(
        self, db, make_user, world_builders
    ):
        """Editing tagline / description / timezone on an auto-managed
        collective is allowed; the creator still owns the collective."""
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(tagline="A refreshed tagline")
        # _get_managed_space checks the caller is the space owner or
        # an admin; the owner from the fixture is an admin, so this passes.
        update_space(
            slug=world_builders.slug,
            body=body,
            db=db,
            current_user=owner,
        )
        db.refresh(world_builders)
        assert world_builders.tagline == "A refreshed tagline"

    def test_toggling_is_public_is_refused_on_auto_managed(
        self, db, make_user, world_builders
    ):
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(is_public=True)  # attempting to unlock
        with pytest.raises(HTTPException) as e:
            update_space(
                slug=world_builders.slug,
                body=body,
                db=db,
                current_user=owner,
            )
        assert e.value.status_code == 403
        assert "is_public" in e.value.detail

    def test_pricing_change_is_refused_on_auto_managed(
        self, db, make_user, world_builders
    ):
        owner = db.query(type(make_user())).filter_by(id=world_builders.creator_id).one()
        body = SpaceUpdateRequest(pricing_type="paid_monthly")
        with pytest.raises(HTTPException) as e:
            update_space(
                slug=world_builders.slug,
                body=body,
                db=db,
                current_user=owner,
            )
        assert e.value.status_code == 403
        assert "pricing_type" in e.value.detail


class TestSessionTimeReconciler:
    def test_short_circuits_when_nothing_relevant(self, db, make_user):
        """No auto-grant space + no auto_role rows → zero writes."""
        u = make_user(role="user")
        # No world_builders fixture — no auto-grant space exists at all.
        reconcile_at_session_time(u, db)
        # Should not error, no rows created.
        assert (
            db.query(SpaceMembership).filter(SpaceMembership.user_id == u.id).count()
            == 0
        )

    def test_grants_membership_when_reconciler_runs(
        self, db, make_user, world_builders
    ):
        creator = make_user(role="creator")
        reconcile_at_session_time(creator, db)
        m = _get_membership(db, creator.id, world_builders.id)
        assert m is not None
        assert m.status == SpaceMembershipStatus.active
