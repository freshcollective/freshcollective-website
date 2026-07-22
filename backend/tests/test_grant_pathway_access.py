"""
Tests for ``POST /api/admin/entitlements/grant``.

The endpoint replaces the old ``POST /api/admin/payments/manual-pathway-purchase``
that also fabricated a ``PaymentTransaction``. These tests assert:

- No ``PaymentTransaction`` is ever created by this action.
- ``PathwayEntitlement`` is created with the structured ``grant_reason``
  and ``granted_by_user_id`` audit fields populated.
- Reactivation of a revoked entitlement updates the audit fields to the
  *new* grant event (rather than silently overwriting a prior grant).
- 409 on active entitlement (no duplicates).
- 422 on invalid reason.
- 422 when ``reason='other'`` with no note.
- Creator receives an in-app notification for creator-owned pathways.
- Platform-owned pathways skip notification.
- The removed routes are no longer registered.
"""

from __future__ import annotations

import uuid

import pytest

from app.admin.routes import grant_pathway_access
from app.admin.schemas import GrantPathwayAccessRequest
from app.models.notification import Notification
from app.models.payment import PaymentTransaction
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def make_pathway(db, make_space):
    def _factory(*, space=None, price_cents: int = 5_000, currency: str = "AUD"):
        space = space or make_space()
        p = Pathway(
            id=f"pw_{uuid.uuid4().hex[:12]}",
            space_id=space.id,
            slug=f"path-{uuid.uuid4().hex[:8]}",
            title="Test Pathway",
            access_type="one_time",
            pricing_mode="legacy",
            price_cents=price_cents,
            currency=currency,
        )
        db.add(p)
        db.flush()
        return p, space
    return _factory


# ---------------------------------------------------------------------------
# No PaymentTransaction is ever created
# ---------------------------------------------------------------------------


class TestNoFabricatedRevenue:
    def test_grant_does_not_create_payment_transaction(self, db, make_user, make_pathway):
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        before = db.query(PaymentTransaction).count()
        grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id,
                pathway_id=pathway.id,
                reason="comp",
                note="Founding-member gift",
            ),
            admin=admin,
            db=db,
        )
        after = db.query(PaymentTransaction).count()
        assert after == before, "Grant access must not create a PaymentTransaction."


# ---------------------------------------------------------------------------
# Entitlement + audit trail
# ---------------------------------------------------------------------------


class TestEntitlementCreatedWithAudit:
    def test_new_entitlement_records_who_reason_note(self, db, make_user, make_pathway):
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        result = grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id,
                pathway_id=pathway.id,
                reason="beta",
                note="Early tester cohort",
            ),
            admin=admin,
            db=db,
        )
        assert result.reactivated is False
        assert result.reason == "beta"
        assert result.note == "Early tester cohort"
        assert result.granted_by_user_id == admin.id

        ent = db.query(PathwayEntitlement).filter_by(id=result.entitlement_id).one()
        assert ent.status == EntitlementStatus.active
        assert ent.source == EntitlementSource.admin
        assert ent.granted_by_user_id == admin.id
        assert ent.grant_reason == "beta"
        assert ent.notes == "Early tester cohort"


class TestReactivationUpdatesAudit:
    def test_revoked_entitlement_is_reactivated_and_audit_refreshed(
        self, db, make_user, make_pathway,
    ):
        admin_a = make_user(role="admin")
        admin_b = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        first = grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id,
                pathway_id=pathway.id,
                reason="comp",
                note="First grant",
            ),
            admin=admin_a, db=db,
        )
        ent = db.query(PathwayEntitlement).filter_by(id=first.entitlement_id).one()
        # Revoke it
        ent.status = EntitlementStatus.revoked
        db.commit()

        second = grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id,
                pathway_id=pathway.id,
                reason="replacement",
                note="Restored after refund",
            ),
            admin=admin_b, db=db,
        )
        assert second.reactivated is True
        assert second.entitlement_id == first.entitlement_id
        assert second.reason == "replacement"

        db.refresh(ent)
        assert ent.status == EntitlementStatus.active
        assert ent.grant_reason == "replacement"
        assert ent.granted_by_user_id == admin_b.id
        assert ent.notes == "Restored after refund"


# ---------------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------------


class TestDuplicatePrevention:
    def test_active_entitlement_returns_409(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id, pathway_id=pathway.id, reason="comp", note="first",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as excinfo:
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id=member.id, pathway_id=pathway.id, reason="comp", note="second",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 409

    def test_active_entitlement_leaves_state_unchanged(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        first = grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id, pathway_id=pathway.id, reason="comp", note="first",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException):
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id=member.id, pathway_id=pathway.id, reason="other", note="try to overwrite",
                ),
                admin=admin, db=db,
            )
        # Original grant remains untouched.
        ent = db.query(PathwayEntitlement).filter_by(id=first.entitlement_id).one()
        assert ent.grant_reason == "comp"
        assert ent.notes == "first"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_reason_rejected(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        with pytest.raises(HTTPException) as excinfo:
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id=member.id, pathway_id=pathway.id, reason="bribery",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 422

    def test_other_reason_requires_note(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        with pytest.raises(HTTPException) as excinfo:
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id=member.id, pathway_id=pathway.id, reason="other", note=None,
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 422

    def test_other_reason_with_whitespace_only_note_rejected(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        member = make_user(role="user")
        pathway, _ = make_pathway()

        with pytest.raises(HTTPException) as excinfo:
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id=member.id, pathway_id=pathway.id, reason="other", note="   ",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 422

    def test_unknown_member_404(self, db, make_user, make_pathway):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        pathway, _ = make_pathway()

        with pytest.raises(HTTPException) as excinfo:
            grant_pathway_access(
                GrantPathwayAccessRequest(
                    member_user_id="u_missing", pathway_id=pathway.id, reason="comp",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Creator notification
# ---------------------------------------------------------------------------


class TestCreatorNotification:
    def test_creator_receives_in_app_notification(self, db, make_user, make_pathway, make_space):
        admin = make_user(role="admin")
        creator = make_user(role="creator", name="Lindsey")
        member = make_user(role="user", name="Simone")
        space = make_space(creator=creator, name="EMBODY")
        pathway, _ = make_pathway(space=space)

        grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id, pathway_id=pathway.id, reason="comp",
                note="VIP gift",
            ),
            admin=admin, db=db,
        )

        notifs = (
            db.query(Notification)
            .filter(
                Notification.user_id == creator.id,
                Notification.notification_type == "pathway_access_granted_by_platform",
            )
            .all()
        )
        assert len(notifs) == 1
        n = notifs[0]
        assert pathway.title in n.title
        assert "Simone" in n.message
        assert "Complimentary access" in n.message  # human label, not raw enum

    def test_admin_granting_own_pathway_skips_self_notification(
        self, db, make_user, make_pathway, make_space,
    ):
        """If admin is the creator (owner-plus-admin case), don't notify self."""
        admin = make_user(role="admin")
        member = make_user(role="user")
        space = make_space(creator=admin)
        pathway, _ = make_pathway(space=space)

        grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id, pathway_id=pathway.id, reason="comp",
            ),
            admin=admin, db=db,
        )

        notifs = db.query(Notification).filter(Notification.user_id == admin.id).all()
        assert notifs == []

    def test_platform_owned_pathway_no_notification(self, db, make_user, make_pathway, make_space):
        """A pathway whose Space has no creator (platform-owned) has no
        creator to notify. The grant still succeeds."""
        admin = make_user(role="admin")
        member = make_user(role="user")
        # Build a platform-owned space by nulling creator_id after creation.
        # `make_space` requires a creator, so we make one and then null.
        space = make_space()
        space.creator_id = None
        db.commit()
        pathway, _ = make_pathway(space=space)

        result = grant_pathway_access(
            GrantPathwayAccessRequest(
                member_user_id=member.id, pathway_id=pathway.id, reason="beta",
            ),
            admin=admin, db=db,
        )
        assert result.entitlement_id  # succeeded

        notifs = db.query(Notification).filter(
            Notification.notification_type == "pathway_access_granted_by_platform"
        ).all()
        assert notifs == []


# ---------------------------------------------------------------------------
# Removed routes
# ---------------------------------------------------------------------------


class TestRemovedRoutes:
    def test_manual_purchase_route_removed(self):
        from app.main import app
        from fastapi.routing import APIRoute
        paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
        assert "/api/admin/payments/manual-pathway-purchase" not in paths

    def test_raw_manual_payment_route_removed(self):
        from app.main import app
        from fastapi.routing import APIRoute
        paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
        assert "/api/admin/payments/manual" not in paths
