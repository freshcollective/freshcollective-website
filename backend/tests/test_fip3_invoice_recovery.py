"""FIP3 — same-invoice recovery (failed → succeeded, one row).

Domain rule locked in v1: one finite-plan instalment = one
Stripe invoice = one ``PaymentTransaction``. Failed collection
attempts are transitional states on that row; when Stripe
ultimately collects on the same invoice, the row is UPGRADED
``failed → succeeded`` rather than a second row minted.

Covers:
  R1  failed invoice → same invoice succeeds → same row updated
  R2  installments_paid increments exactly once
  R3  duplicate/replayed success is a no-op
  R4  payment_problem → active on recovery, grace fields cleared
  R5  suspended → active on recovery + plan-owned access reinstated
  R6  failed plan → late successful invoice recovers appropriately
  R7  final failed invoice later succeeds → completed
  R8  fee snapshot remains authoritative on recovered row
  R9  correct charge / PI ids populated on recovered row
  R10 replayed failure event AFTER recovery does not downgrade
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    EntitlementSource, EntitlementStatus,
    EventSeries, Pathway, PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as agr
from app.services import finite_plan_lifecycle as fpl
from app.services.purchase_fulfilment import (
    AccessPassIntent, EntitlementIntent, FulfilmentIntent, serialise_intent,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture — active plan at 1/3, ready to receive invoice #2
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_at_1_of_3(db, make_user, make_space):
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    starts = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=starts, status="published", published_at=starts,
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}", title="Awaken",
        status="active",
    )
    db.add_all([series, pathway]); db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken plan",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly × 3", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add_all([opt, sched]); db.flush()

    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=None),),
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=now, valid_until=None,
            total_credits=None, credits_per_week=None,
            eligible_pathway_id=None, eligible_series_id=series.id,
            grants_pathway_id=pathway.id,
        ),),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id, creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3, installments_paid=1,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_subscription_id=subscription_id,
        provider_subscription_schedule_id=f"ss_{uuid.uuid4().hex[:8]}",
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan); db.flush()

    # Seed invoice #1 succeeded, entitlement + pass active + linked
    # to plan + grant records — matches FIP3 first-invoice fulfilment.
    txn1 = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id, creator_user_id=creator.id,
        space_id=space.id, currency="AUD",
        gross_amount_cents=2000, platform_fee_basis_points=800,
        platform_fee_cents=160, net_creator_amount_cents=1840,
        net_platform_amount_cents=160,
        provider_invoice_id="in_seed_1",
        provider_subscription_id=subscription_id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id, installment_number=1,
        stripe_mode="test", payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn1); db.flush()

    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active, starts_at=now,
        purchase_plan_id=plan.id,
        created_at=now, updated_at=now,
    )
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn1.id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active, valid_from=now,
        eligible_series_id=series.id, grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add_all([ent, ap]); db.flush()

    agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=txn1.id,
        granted_at=now,
    )
    agr.record_series_grant(
        db, user_id=member.id, series_id=series.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=txn1.id,
        granted_at=now,
    )
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, pathway=pathway, option=opt, schedule=sched,
        plan=plan, subscription_id=subscription_id,
        entitlement=ent, access_pass=ap, first_txn=txn1,
    )


def _fail_invoice_2(db, s, invoice_id="in_invoice_2"):
    """Drive a failure event for invoice #2 on the plan."""
    fpl.handle_invoice_failed_for_plan(
        db, plan=s.plan, invoice_id=invoice_id, failed_at=datetime.utcnow(),
    )
    db.flush()


def _succeed_invoice_2(db, s, invoice_id="in_invoice_2",
                       charge_id=None, payment_intent_id=None):
    """Drive a success event for the SAME invoice #2."""
    charge_id = charge_id or f"ch_{uuid.uuid4().hex[:8]}"
    payment_intent_id = payment_intent_id or f"pi_{uuid.uuid4().hex[:8]}"
    fpl.record_later_successful_instalment(
        db, plan=s.plan,
        invoice_id=invoice_id,
        invoice_amount_cents=2000, invoice_currency="AUD",
        subscription_id=s.subscription_id,
        charge_id=charge_id, payment_intent_id=payment_intent_id,
        now=datetime.utcnow(),
    )
    db.flush()
    return charge_id, payment_intent_id


# ===========================================================================
# R1 — failed invoice → same invoice succeeds → same row updated
# R2 — installments_paid increments exactly once
# ===========================================================================


class TestSameInvoiceRecovery:
    def test_R1_failed_invoice_upgraded_in_place_on_recovery(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        db.refresh(s.plan)
        failed_txns = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .all()
        )
        assert len(failed_txns) == 1
        failed_row_id = failed_txns[0].id
        assert failed_txns[0].status == PaymentTransactionStatus.failed

        _succeed_invoice_2(db, s)

        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .all()
        )
        assert len(rows) == 1, "must not create a second row for the same invoice"
        assert rows[0].id == failed_row_id, "must update the existing row in place"
        assert rows[0].status == PaymentTransactionStatus.succeeded

    def test_R2_installments_paid_increments_exactly_once(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        db.refresh(s.plan)
        # Failed handler must NOT increment installments_paid.
        assert s.plan.installments_paid == 1

        _succeed_invoice_2(db, s)
        db.refresh(s.plan)
        assert s.plan.installments_paid == 2


# ===========================================================================
# R3 — duplicate/replayed success is a no-op
# ===========================================================================


class TestDuplicateSuccessNoOp:
    def test_R3_replayed_success_does_not_change_state(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        _succeed_invoice_2(db, s)
        db.refresh(s.plan)
        first_installments = s.plan.installments_paid
        first_status = s.plan.status

        _succeed_invoice_2(db, s)  # replay
        db.refresh(s.plan)
        assert s.plan.installments_paid == first_installments
        assert s.plan.status == first_status
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .all()
        )
        assert len(rows) == 1


# ===========================================================================
# R4 — payment_problem → active on recovery, grace fields cleared
# ===========================================================================


class TestPaymentProblemToActive:
    def test_R4_recovery_from_payment_problem_clears_grace(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem
        assert s.plan.payment_problem_started_at is not None
        assert s.plan.grace_expires_at is not None
        assert s.plan.last_failed_invoice_id == "in_invoice_2"

        _succeed_invoice_2(db, s)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.payment_problem_started_at is None
        assert s.plan.grace_expires_at is None
        assert s.plan.last_failed_invoice_id is None


# ===========================================================================
# R5 — suspended → active on recovery + access reinstated
# ===========================================================================


class TestSuspendedRecoveryReinstatesAccess:
    def test_R5_recovery_from_suspended_reinstates_plan_owned_access(
        self, db, plan_at_1_of_3,
    ):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        # Force expiry + sweep.
        s.plan.grace_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        fpl.sweep_expired_grace_plans(db, now=datetime.utcnow())
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.suspended
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

        # Recovery on the same overdue invoice #2.
        _succeed_invoice_2(db, s)
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.reinstated_at is not None
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

        # Same single row for invoice #2.
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status == PaymentTransactionStatus.succeeded


# ===========================================================================
# R6 — failed plan → late successful invoice recovers appropriately
# ===========================================================================


class TestFailedPlanLateRecovery:
    def test_R6_failed_plan_recovers_to_active_on_late_non_final_success(
        self, db, plan_at_1_of_3,
    ):
        """Simulate an out-of-order provider-end event that marked
        the plan failed and suspended plan-owned access; then a
        delayed invoice #2 success arrives. Plan lifts back to
        active, access reinstated, single row for invoice #2."""
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)

        # Emulate the abnormal-end path: mark plan failed +
        # suspend plan-owned access via the shared helper.
        agr.revoke_records_for_plan(
            db, purchase_plan_id=s.plan.id, reason="plan_failed", now=datetime.utcnow(),
        )
        s.plan.status = PurchasePlanStatus.failed
        fpl._apply_access_effects_for_plan_state(
            db, plan=s.plan,
            new_ap_status=AccessPassStatus.suspended,
            new_ent_status=EntitlementStatus.suspended,
            now=datetime.utcnow(),
        )
        db.commit()
        db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

        _succeed_invoice_2(db, s)
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 2
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active


# ===========================================================================
# R7 — final failed invoice later succeeds → completed
# ===========================================================================


class TestFinalFailedInvoiceRecoversToCompleted:
    def test_R7_final_invoice_failed_then_recovered_transitions_to_completed(
        self, db, plan_at_1_of_3,
    ):
        s = plan_at_1_of_3
        # Bring plan to 2/3 first.
        _succeed_invoice_2(db, s)
        db.refresh(s.plan)
        assert s.plan.installments_paid == 2

        # Final invoice #3 fails, then recovers on the same id.
        _fail_invoice_2(db, s, invoice_id="in_invoice_3_final")
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem

        _succeed_invoice_2(db, s, invoice_id="in_invoice_3_final")
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.completed_at is not None
        assert s.plan.installments_paid == 3
        assert s.plan.payment_problem_started_at is None
        assert s.plan.grace_expires_at is None

        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_3_final")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].installment_number == 3


# ===========================================================================
# R8 — fee snapshot remains authoritative on recovered row
# ===========================================================================


class TestFeeSnapshotOnRecoveredRow:
    def test_R8_recovered_row_uses_plan_snapshot_fee_bps(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        # Fee snapshot on plan is 800 bps.
        _fail_invoice_2(db, s)
        _succeed_invoice_2(db, s)

        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .one()
        )
        assert row.platform_fee_basis_points == 800
        assert row.platform_fee_cents == 160  # 2000 * 800/10000
        assert row.net_creator_amount_cents == 1840
        assert row.net_platform_amount_cents == 160
        assert row.gross_amount_cents == 2000


# ===========================================================================
# R9 — correct charge / PI ids populated on recovered row
# ===========================================================================


class TestProviderIdsOnRecoveredRow:
    def test_R9_recovered_row_gets_recovery_time_provider_ids(
        self, db, plan_at_1_of_3,
    ):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        recovery_charge = "ch_recovery_success"
        recovery_pi = "pi_recovery_success"
        _succeed_invoice_2(
            db, s,
            charge_id=recovery_charge,
            payment_intent_id=recovery_pi,
        )
        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .one()
        )
        assert row.provider_charge_id == recovery_charge
        assert row.provider_payment_intent_id == recovery_pi
        assert row.installment_number == 2
        assert row.purchase_plan_id == s.plan.id
        assert row.provider_subscription_id == s.subscription_id
        assert row.payout_status == PayoutStatus.pending


# ===========================================================================
# R10 — replayed failure AFTER recovery does not downgrade
# ===========================================================================


class TestFailureAfterRecoveryIsIgnored:
    def test_R10_failure_replay_after_recovery_is_ignored(self, db, plan_at_1_of_3):
        s = plan_at_1_of_3
        _fail_invoice_2(db, s)
        _succeed_invoice_2(db, s)
        db.refresh(s.plan)
        # Replayed failure event for the same invoice.
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan, invoice_id="in_invoice_2",
            failed_at=datetime.utcnow(),
        )
        db.flush()
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 2
        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_2")
            .one()
        )
        assert row.status == PaymentTransactionStatus.succeeded
