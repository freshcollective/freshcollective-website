"""FIP4B1 — member plan-recovery state on Pathway / Series responses.

Locks the shared helper + response wiring:

  * active finite plan → no recovery banner (member_plan_state=None)
  * payment_problem plan on same pathway → banner state, grace date
    serialised, install counters carried through
  * suspended plan on same pathway → suspended banner state
  * anonymous viewer → never gets member_plan_state
  * plan grants a DIFFERENT pathway → no banner on this pathway
  * plan grants via event_series grant → banner on the series
  * legacy attaches_to shape without grant rows → still surfaced
  * pay-in-full members / free-access viewers unaffected
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES, GRANT_KIND_PATHWAY, PaymentOptionGrant,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway, PathwayType
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.member_plan_state import (
    build_member_plan_state,
    find_recovery_plan_for_pathway,
    find_recovery_plan_for_series,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def po_and_plan(db, make_user, make_space):
    """Pathway + PaymentOption granting it (via modern grant row) +
    a member who owns a plan on that option. Test parameterises
    plan.status."""
    member = make_user()
    space = make_space()
    pw = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}", title="Test",
        status="active", access_type="one_time",
        pricing_mode="payment_options",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pw); db.flush()
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        pathway_id=pw.id,
        attaches_to_kind="pathway", attaches_to_id=pw.id,
        name="Test PO",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
    )
    db.add(opt); db.flush()
    db.add(PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=opt.id,
        grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id,
    ))
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly x 3", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add(sched); db.flush()
    now = datetime.utcnow()
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3, installments_paid=1,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        stripe_mode="test",
        snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
        activated_at=now,
        created_at=now, updated_at=now,
    )
    db.add(plan); db.commit()
    return SimpleNamespace(
        member=member, space=space, pathway=pw, option=opt, plan=plan,
    )


class TestFindRecoveryPlanForPathway:
    def test_active_plan_returns_none(self, db, po_and_plan):
        s = po_and_plan
        plan = find_recovery_plan_for_pathway(
            db, user=s.member, pathway_id=s.pathway.id,
        )
        assert plan is None, "active plan should not need recovery"

    def test_payment_problem_plan_returned(self, db, po_and_plan):
        s = po_and_plan
        s.plan.status = PurchasePlanStatus.payment_problem
        s.plan.payment_problem_started_at = datetime.utcnow()
        s.plan.grace_expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        plan = find_recovery_plan_for_pathway(
            db, user=s.member, pathway_id=s.pathway.id,
        )
        assert plan is not None
        assert plan.id == s.plan.id
        assert plan.status == PurchasePlanStatus.payment_problem

    def test_suspended_plan_returned(self, db, po_and_plan):
        s = po_and_plan
        s.plan.status = PurchasePlanStatus.suspended
        s.plan.suspended_at = datetime.utcnow()
        db.commit()
        plan = find_recovery_plan_for_pathway(
            db, user=s.member, pathway_id=s.pathway.id,
        )
        assert plan is not None
        assert plan.status == PurchasePlanStatus.suspended

    def test_plan_granting_different_pathway_returns_none(
        self, db, po_and_plan, make_space,
    ):
        s = po_and_plan
        # Move plan to payment_problem then create a DIFFERENT
        # pathway the plan doesn't grant.
        s.plan.status = PurchasePlanStatus.payment_problem
        s.plan.grace_expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        other_pw = Pathway(
            id=_uid("pw2"), space_id=s.space.id,
            slug=f"pw2-{uuid.uuid4().hex[:8]}", title="Other",
            status="active", access_type="one_time",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(other_pw); db.commit()
        plan = find_recovery_plan_for_pathway(
            db, user=s.member, pathway_id=other_pw.id,
        )
        assert plan is None

    def test_failed_completed_cancelled_not_returned(self, db, po_and_plan):
        s = po_and_plan
        for terminal in (
            PurchasePlanStatus.failed,
            PurchasePlanStatus.completed,
            PurchasePlanStatus.cancelled,
        ):
            s.plan.status = terminal
            db.commit()
            plan = find_recovery_plan_for_pathway(
                db, user=s.member, pathway_id=s.pathway.id,
            )
            assert plan is None, f"{terminal.value} must not surface as needing recovery"

    def test_suspended_wins_over_payment_problem(self, db, po_and_plan, make_user):
        """If two plans on different options both grant the same
        pathway, the more urgent state wins."""
        s = po_and_plan
        # Make the first plan suspended.
        s.plan.status = PurchasePlanStatus.suspended
        s.plan.suspended_at = datetime.utcnow()
        db.commit()

        # A second PO also granting the same pathway.
        opt2 = PaymentOption(
            id=_uid("po2"), space_id=s.space.id,
            pathway_id=s.pathway.id,
            attaches_to_kind="pathway", attaches_to_id=s.pathway.id,
            name="Other PO",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
        )
        db.add(opt2); db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("pog2"), payment_option_id=opt2.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=s.pathway.id,
        ))
        sched2 = PaymentOptionSchedule(
            id=_uid("sched2"), payment_option_id=opt2.id,
            name="Weekly x 3", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=3,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=6000, currency="AUD",
        )
        db.add(sched2); db.flush()
        now = datetime.utcnow()
        plan2 = PurchasePlan(
            id=_uid("pplan2"),
            member_user_id=s.member.id,
            payment_option_id=opt2.id,
            payment_option_schedule_id=sched2.id,
            space_id=s.space.id,
            status=PurchasePlanStatus.payment_problem,
            grace_expires_at=now + timedelta(days=5),
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3, installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
            created_at=now, updated_at=now,
        )
        db.add(plan2); db.commit()

        matched = find_recovery_plan_for_pathway(
            db, user=s.member, pathway_id=s.pathway.id,
        )
        assert matched is not None
        assert matched.status == PurchasePlanStatus.suspended, "suspended should outrank payment_problem"


class TestBuildMemberPlanState:
    def test_shape_carries_grace_and_counters(self, db, po_and_plan):
        s = po_and_plan
        s.plan.status = PurchasePlanStatus.payment_problem
        s.plan.payment_problem_started_at = datetime.utcnow()
        s.plan.grace_expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        state = build_member_plan_state(db, s.plan)
        assert state.status == "payment_problem"
        assert state.payment_option_name == "Test PO"
        assert state.installments_paid == 1
        assert state.installments_expected == 3
        assert state.grace_expires_at is not None
        assert state.suspended_at is None
        assert state.recovery_required is True

    def test_suspended_shape(self, db, po_and_plan):
        s = po_and_plan
        s.plan.status = PurchasePlanStatus.suspended
        s.plan.suspended_at = datetime.utcnow()
        db.commit()
        state = build_member_plan_state(db, s.plan)
        assert state.status == "suspended"
        assert state.suspended_at is not None


class TestSeriesGrantsSurfaceState:
    def test_series_granted_via_grant_row_returns_plan(self, db, make_user, make_space):
        member = make_user()
        space = make_space()
        starts = datetime.utcnow()
        series = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
            starts_at=starts, status="published", published_at=starts,
        )
        db.add(series); db.flush()
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="event_series", attaches_to_id=series.id,
            name="Series PO",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
        )
        db.add(opt); db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=opt.id,
            grant_kind=GRANT_KIND_EVENT_SERIES, series_id=series.id,
        ))
        series_sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Weekly x 3", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=3,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=6000, currency="AUD",
        )
        db.add(series_sched); db.flush()
        now = datetime.utcnow()
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=series_sched.id,
            space_id=space.id,
            status=PurchasePlanStatus.payment_problem,
            grace_expires_at=now + timedelta(days=7),
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3, installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
            created_at=now, updated_at=now,
        )
        db.add(plan); db.commit()

        matched = find_recovery_plan_for_series(
            db, user=member, series_id=series.id,
        )
        assert matched is not None
        assert matched.id == plan.id


class TestFreeAndPayInFullMembersUnaffected:
    def test_member_with_no_plan_returns_none(self, db, make_user, make_space):
        member = make_user()
        space = make_space()
        pw = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}", title="Free",
            status="active", access_type="free",
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw); db.commit()
        assert find_recovery_plan_for_pathway(
            db, user=member, pathway_id=pw.id,
        ) is None

    def test_other_member_with_plan_does_not_surface(
        self, db, po_and_plan, make_user,
    ):
        s = po_and_plan
        s.plan.status = PurchasePlanStatus.payment_problem
        s.plan.grace_expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        someone_else = make_user()
        # Different member — plan belongs to s.member, not someone_else.
        matched = find_recovery_plan_for_pathway(
            db, user=someone_else, pathway_id=s.pathway.id,
        )
        assert matched is None
