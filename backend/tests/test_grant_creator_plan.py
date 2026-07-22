"""
Tests for the manual creator-plan grant flow — Grant / Extend / Revoke.

Verifies:

- No ``PaymentTransaction`` is created; Stripe fields stay null.
- Structured audit fields on ``CreatorSubscription`` + append-only
  ``CreatorPlanGrant`` history table are populated.
- Conflict handling with real paid Stripe subs (409, hard block).
- Conflict handling with existing manual grants (409, hint).
- Reactivation path when a prior grant is cancelled.
- Reason + duration validation.
- Creator notification is emitted with correct wording (fixed date vs
  ongoing).
- Plan-limit enforcement path continues to find manual grants.
- Extend / Revoke behaviour and their own conflict rules.
- Old PATCH endpoint is removed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.admin.routes import (
    extend_creator_plan_grant,
    grant_creator_plan_access,
    revoke_creator_plan_grant,
    list_creator_plan_grant_history,
)
from app.admin.schemas import (
    ExtendPlanAccessRequest,
    GrantPlanAccessRequest,
    RevokePlanAccessRequest,
)
from app.creator.plan_guards import resolve_creator_plan
from app.models.creator_billing import (
    CreatorPlan,
    CreatorPlanGrant,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.notification import Notification
from app.models.payment import PaymentTransaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_plan(db):
    """Create a CreatorPlan; sensible defaults so most tests can call
    with just a slug."""
    def _factory(*, slug: str = "creator", name: str = "Creator", price: int = 4900,
                 bps: int = 800, collective_limit: int = 3) -> CreatorPlan:
        # The plan slug must match the plan_config PLANS_BY_SLUG map for
        # the capability lookup to succeed. Reuse the fixed slugs that map
        # (`community`, `creator`, `pro`).
        plan = CreatorPlan(
            id=f"plan_{uuid.uuid4().hex[:8]}",
            name=name,
            slug=slug,
            monthly_price_cents=price,
            currency="AUD",
            transaction_fee_basis_points=bps,
            collective_limit=collective_limit,
            is_active=True,
        )
        db.add(plan)
        db.flush()
        return plan
    return _factory


# ---------------------------------------------------------------------------
# 1. No fabricated revenue
# ---------------------------------------------------------------------------


class TestNoFabricatedRevenue:
    def test_grant_creates_no_payment_transaction(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        before = db.query(PaymentTransaction).count()
        grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id,
                plan_slug=plan.slug,
                reason="comp",
                note="Founding creator",
                duration="6_months",
            ),
            admin=admin, db=db,
        )
        after = db.query(PaymentTransaction).count()
        assert after == before, "Grant plan access must not create a PaymentTransaction."

    def test_grant_leaves_stripe_fields_null(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="beta", duration="3_months",
            ),
            admin=admin, db=db,
        )
        sub = db.query(CreatorSubscription).filter_by(id=result.subscription_id).one()
        assert sub.stripe_subscription_id is None
        assert sub.stripe_customer_id is None
        assert sub.source == "manual_grant"


# ---------------------------------------------------------------------------
# 2. Audit fields + history
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_new_grant_writes_audit_fields(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="migration", note="Old system was Podia",
                duration="12_months",
            ),
            admin=admin, db=db,
        )
        sub = db.query(CreatorSubscription).filter_by(id=result.subscription_id).one()
        assert sub.granted_by_user_id == admin.id
        assert sub.grant_reason == "migration"
        assert sub.grant_note == "Old system was Podia"
        assert sub.starts_at is not None
        assert sub.ends_at is not None

    def test_history_row_recorded_on_grant(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", duration="1_month",
            ),
            admin=admin, db=db,
        )
        events = db.query(CreatorPlanGrant).filter_by(subscription_id=result.subscription_id).all()
        assert len(events) == 1
        assert events[0].action == "granted"
        assert events[0].reason == "comp"
        assert events[0].actor_user_id == admin.id
        assert events[0].creator_plan_id == plan.id

    def test_history_survives_extend_and_revoke(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="beta", duration="1_month",
            ),
            admin=admin, db=db,
        )
        extend_creator_plan_grant(
            result.subscription_id,
            ExtendPlanAccessRequest(duration="3_months", note="Cohort extended"),
            admin=admin, db=db,
        )
        revoke_creator_plan_grant(
            result.subscription_id,
            RevokePlanAccessRequest(reason="beta ended", note="Wrapped up"),
            admin=admin, db=db,
        )
        events = (
            db.query(CreatorPlanGrant)
            .filter_by(subscription_id=result.subscription_id)
            .order_by(CreatorPlanGrant.created_at.asc())
            .all()
        )
        assert [e.action for e in events] == ["granted", "extended", "revoked"]


# ---------------------------------------------------------------------------
# 3. Conflict with a paid Stripe subscription — HARD BLOCK
# ---------------------------------------------------------------------------


class TestConflictWithPaidStripe:
    def test_grant_refused_when_stripe_paid_active(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        pro = make_plan(slug="pro", name="Pro", price=14900)
        # Simulate a real paid Stripe subscription
        paid = CreatorSubscription(
            id=str(uuid.uuid4()),
            user_id=creator.id,
            creator_plan_id=pro.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="stripe_paid",
            stripe_subscription_id="sub_fake123",
            stripe_customer_id="cus_fake123",
        )
        db.add(paid)
        db.flush()

        other = make_plan(slug="creator")
        with pytest.raises(HTTPException) as excinfo:
            grant_creator_plan_access(
                GrantPlanAccessRequest(
                    creator_user_id=creator.id, plan_slug=other.slug,
                    reason="comp", duration="1_month",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 409
        # Verify the paid subscription was not modified
        db.refresh(paid)
        assert paid.creator_plan_id == pro.id
        assert paid.source == "stripe_paid"


# ---------------------------------------------------------------------------
# 4. Conflict with an active manual grant — 409 with hint
# ---------------------------------------------------------------------------


class TestConflictWithActiveGrant:
    def test_second_grant_refused_when_first_still_active(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="beta", duration="3_months",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as excinfo:
            grant_creator_plan_access(
                GrantPlanAccessRequest(
                    creator_user_id=creator.id, plan_slug=plan.slug,
                    reason="comp", duration="1_month",
                ),
                admin=admin, db=db,
            )
        assert excinfo.value.status_code == 409
        assert "extend or revoke" in excinfo.value.detail.lower()


# ---------------------------------------------------------------------------
# 5. Expired / revoked grant → reactivation path
# ---------------------------------------------------------------------------


class TestReactivationAfterRevoke:
    def test_grant_after_revoke_reactivates_same_row(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")

        first = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="beta", duration="1_month",
            ),
            admin=admin, db=db,
        )
        revoke_creator_plan_grant(
            first.subscription_id,
            RevokePlanAccessRequest(reason="beta ended"),
            admin=admin, db=db,
        )

        second = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="replacement", note="Back after refund",
                duration="6_months",
            ),
            admin=admin, db=db,
        )
        assert second.reactivated is True
        assert second.subscription_id == first.subscription_id
        # Old revocation fields cleared, new grant fields written
        sub = db.query(CreatorSubscription).filter_by(id=first.subscription_id).one()
        assert sub.status == CreatorSubscriptionStatus.active
        assert sub.revoked_at is None
        assert sub.grant_reason == "replacement"


# ---------------------------------------------------------------------------
# 6. Validation — reason enum + duration required
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_reason_rejected(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        with pytest.raises(HTTPException) as e:
            grant_creator_plan_access(
                GrantPlanAccessRequest(
                    creator_user_id=creator.id, plan_slug=plan.slug,
                    reason="freebie", duration="1_month",
                ), admin=admin, db=db,
            )
        assert e.value.status_code == 422

    def test_other_reason_requires_note(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        with pytest.raises(HTTPException) as e:
            grant_creator_plan_access(
                GrantPlanAccessRequest(
                    creator_user_id=creator.id, plan_slug=plan.slug,
                    reason="other", note=None, duration="1_month",
                ), admin=admin, db=db,
            )
        assert e.value.status_code == 422

    def test_missing_duration_and_ends_at_rejected(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        with pytest.raises(HTTPException) as e:
            grant_creator_plan_access(
                GrantPlanAccessRequest(
                    creator_user_id=creator.id, plan_slug=plan.slug,
                    reason="comp",
                ), admin=admin, db=db,
            )
        assert e.value.status_code == 422
        assert "duration" in e.value.detail.lower()

    def test_indefinite_duration_yields_null_ends_at(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="internal", duration="indefinite",
            ), admin=admin, db=db,
        )
        sub = db.query(CreatorSubscription).filter_by(id=result.subscription_id).one()
        assert sub.ends_at is None

    def test_explicit_ends_at_wins_over_duration(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        explicit = datetime(2027, 1, 1, 12, 0, 0)
        result = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", ends_at=explicit, duration="1_month",
            ), admin=admin, db=db,
        )
        assert result.ends_at == explicit


# ---------------------------------------------------------------------------
# 7. Creator notification
# ---------------------------------------------------------------------------


class TestNotification:
    def test_fixed_end_date_notification_mentions_date(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator", name="Simone")
        plan = make_plan(slug="creator", name="Creator")
        grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", note="internal-only", duration="3_months",
            ), admin=admin, db=db,
        )
        notifs = db.query(Notification).filter_by(
            user_id=creator.id,
            notification_type="creator_plan_granted_by_platform",
        ).all()
        assert len(notifs) == 1
        assert "Creator" in notifs[0].message
        assert "until" in notifs[0].message
        # Internal note MUST NOT leak into the message
        assert "internal-only" not in notifs[0].message

    def test_indefinite_notification_uses_ongoing_wording(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator", name="Creator")
        grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="internal", duration="indefinite",
            ), admin=admin, db=db,
        )
        notifs = db.query(Notification).filter_by(
            user_id=creator.id,
            notification_type="creator_plan_granted_by_platform",
        ).all()
        assert len(notifs) == 1
        assert "ongoing" in notifs[0].message.lower()


# ---------------------------------------------------------------------------
# 8. Plan-limit integration
# ---------------------------------------------------------------------------


class TestPlanLimitIntegration:
    def test_manual_grant_is_honoured_by_capability_lookup(self, db, make_user, make_plan):
        """A creator with only a manual grant should read as being on the
        granted plan when the plan-limit path looks them up."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        # Use a slug the plan_config recognises so capability lookup succeeds.
        plan = make_plan(slug="creator", name="Creator", collective_limit=3)

        grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", duration="6_months",
            ), admin=admin, db=db,
        )
        cap = resolve_creator_plan(creator, db)
        assert cap is not None
        # The important assertion: the guard found the grant. The exact
        # capability numbers come from plan_config.
        assert cap.slug == "creator"


# ---------------------------------------------------------------------------
# 9. Extend + Revoke
# ---------------------------------------------------------------------------


class TestExtendAndRevoke:
    def _grant(self, db, admin, creator, plan):
        return grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", duration="1_month",
            ), admin=admin, db=db,
        )

    def test_extend_updates_ends_at(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        first = self._grant(db, admin, creator, plan)
        old_ends_at = first.ends_at

        extend_creator_plan_grant(
            first.subscription_id,
            ExtendPlanAccessRequest(duration="12_months"),
            admin=admin, db=db,
        )
        sub = db.query(CreatorSubscription).filter_by(id=first.subscription_id).one()
        assert sub.ends_at is not None
        assert sub.ends_at > old_ends_at

    def test_extend_refused_on_stripe_paid(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="pro")
        paid = CreatorSubscription(
            id=str(uuid.uuid4()),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="stripe_paid",
        )
        db.add(paid); db.flush()
        with pytest.raises(HTTPException) as e:
            extend_creator_plan_grant(
                paid.id, ExtendPlanAccessRequest(duration="3_months"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_revoke_sets_status_and_audit(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        first = self._grant(db, admin, creator, plan)

        revoke_creator_plan_grant(
            first.subscription_id,
            RevokePlanAccessRequest(reason="beta ended", note="wrap"),
            admin=admin, db=db,
        )
        sub = db.query(CreatorSubscription).filter_by(id=first.subscription_id).one()
        assert sub.status == CreatorSubscriptionStatus.cancelled
        assert sub.revoked_at is not None
        assert sub.revoked_by_user_id == admin.id
        assert sub.revoked_reason == "beta ended"

    def test_revoke_refused_on_stripe_paid(self, db, make_user, make_plan):
        from fastapi import HTTPException
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="pro")
        paid = CreatorSubscription(
            id=str(uuid.uuid4()),
            user_id=creator.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
            source="stripe_paid",
        )
        db.add(paid); db.flush()
        with pytest.raises(HTTPException) as e:
            revoke_creator_plan_grant(
                paid.id, RevokePlanAccessRequest(),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409


# ---------------------------------------------------------------------------
# 10. History endpoint + removed old route
# ---------------------------------------------------------------------------


class TestHistoryAndRemovedRoute:
    def test_history_endpoint_returns_ordered_events(self, db, make_user, make_plan):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        plan = make_plan(slug="creator")
        first = grant_creator_plan_access(
            GrantPlanAccessRequest(
                creator_user_id=creator.id, plan_slug=plan.slug,
                reason="comp", duration="1_month",
            ), admin=admin, db=db,
        )
        extend_creator_plan_grant(
            first.subscription_id,
            ExtendPlanAccessRequest(duration="3_months", note="Extended"),
            admin=admin, db=db,
        )
        rows = list_creator_plan_grant_history(first.subscription_id, _=admin, db=db)
        assert [r.action for r in rows] == ["granted", "extended"]
        assert rows[0].plan_slug == plan.slug
        assert rows[0].actor_user_id == admin.id

    def test_old_patch_endpoint_removed(self):
        from app.main import app
        from fastapi.routing import APIRoute
        for r in app.routes:
            if isinstance(r, APIRoute):
                assert r.path != "/api/admin/creator-billing/{user_id}/plan", (
                    "PATCH /creator-billing/{user_id}/plan must be removed; "
                    "it silently overwrote paid subscriptions."
                )
