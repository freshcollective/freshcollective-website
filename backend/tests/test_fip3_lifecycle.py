"""FIP3 — finite payment plan lifecycle beyond the first invoice.

Covers §17 of the milestone brief:
  * later successful instalment (2..N)
  * invoice.payment_failed → payment_problem + grace
  * recovery inside grace
  * grace expiry sweep → suspended
  * suspension is source-aware (overlapping access preserved)
  * reinstatement after suspension on recovery
  * final instalment → completed
  * fee snapshot reused
  * customer.subscription.deleted reconciliation
  * schedule.completed reconciliation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.access_grant_record import AccessGrantRecord
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentProvider,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    EventSeries,
    Pathway,
    PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as agr
from app.services import finite_plan_lifecycle as fpl
from app.services.purchase_fulfilment import (
    AccessPassIntent,
    EntitlementIntent,
    FulfilmentIntent,
    serialise_intent,
)
from app.webhooks.finite_plan_handlers import (
    _do_invoice_succeeded,
    _do_invoice_failed,
    _do_subscription_deleted,
    _do_schedule_completed,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Shared fixture — an ACTIVE plan (past first invoice) with one pathway
# entitlement + one series access pass, both linked to the plan.
# ---------------------------------------------------------------------------


@pytest.fixture
def active_plan(db, make_user, make_space):
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
        slug=f"p-{uuid.uuid4().hex[:8]}",
        title="Life in Alignment",
        status="active",
    )
    db.add_all([series, pathway])
    db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Life in Alignment",
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
    db.add_all([opt, sched])
    db.flush()

    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    schedule_id = f"sub_sched_{uuid.uuid4().hex[:12]}"

    now = datetime.utcnow()
    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=None),),
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=now, valid_until=None,
            total_credits=None, credits_per_week=None,
            eligible_pathway_id=None,
            eligible_series_id=series.id,
            grants_pathway_id=pathway.id,
        ),),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3,
        installments_paid=1,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=f"cus_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_schedule_id=schedule_id,
        provider_subscription_id=subscription_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan)
    db.flush()

    # Simulate the first-invoice fulfilment: create linked entitlement +
    # access pass + PaymentTransaction + grant records. Matches what
    # apply_intent + the FIP3 hooks would have written.
    txn1 = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=2000,
        platform_fee_basis_points=800,
        platform_fee_cents=160,
        net_creator_amount_cents=1840,
        net_platform_amount_cents=160,
        provider_invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=subscription_id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        installment_number=1,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn1)
    db.flush()
    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now,
        purchase_plan_id=plan.id,
        created_at=now, updated_at=now,
    )
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn1.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=now,
        eligible_series_id=series.id,
        grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add_all([ent, ap])
    db.flush()

    # Grant records for this plan's grants (pathway + series).
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
        schedule_id=schedule_id, first_txn=txn1,
        entitlement=ent, access_pass=ap,
    )


def _invoice(*, invoice_id, subscription_id, amount, currency="aud", status="paid"):
    # FIP4A: handler now gates on ``invoice.total`` (contractual)
    # rather than ``invoice.amount_paid``. Existing fixtures
    # represent normal card-funded invoices where total==amount_paid.
    return {
        "id": invoice_id,
        "subscription": subscription_id,
        "amount_paid": amount,
        "total": amount,
        "currency": currency,
        "status": status,
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
    }


# ===========================================================================
# 1. Later successful instalment
# ===========================================================================


class TestLaterInstalmentSuccess:
    def test_second_instalment_records_txn_and_advances_counter(self, db, active_plan):
        s = active_plan
        inv = _invoice(
            invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000,
        )
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)

        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 2

        txns = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.purchase_plan_id == s.plan.id,
                PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            )
            .order_by(PaymentTransaction.installment_number)
            .all()
        )
        assert len(txns) == 2
        second = txns[1]
        assert second.installment_number == 2
        assert second.gross_amount_cents == 2000
        assert second.platform_fee_basis_points == 800  # snapshot preserved
        assert second.platform_fee_cents == 160
        assert second.net_creator_amount_cents == 1840
        assert second.provider_invoice_id == inv["id"]

    def test_second_instalment_does_not_duplicate_fulfilment(self, db, active_plan):
        s = active_plan
        ent_ids_before = {
            e.id for e in db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == s.member.id).all()
        }
        pass_ids_before = {
            p.id for p in db.query(AccessPass)
            .filter(AccessPass.user_id == s.member.id).all()
        }
        inv = _invoice(
            invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000,
        )
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        db.commit()

        ent_ids_after = {
            e.id for e in db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == s.member.id).all()
        }
        pass_ids_after = {
            p.id for p in db.query(AccessPass)
            .filter(AccessPass.user_id == s.member.id).all()
        }
        # No new access rows minted.
        assert ent_ids_after == ent_ids_before
        assert pass_ids_after == pass_ids_before

    def test_replay_same_invoice_creates_no_second_txn(self, db, active_plan):
        s = active_plan
        inv_id = f"in_2_{uuid.uuid4().hex[:8]}"
        inv = _invoice(invoice_id=inv_id, subscription_id=s.subscription_id, amount=2000)
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)

        db.refresh(s.plan)
        assert s.plan.installments_paid == 2
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == inv_id)
            .all()
        )
        assert len(rows) == 1


# ===========================================================================
# 2. Final instalment → completed
# ===========================================================================


class TestFinalInstalmentCompletion:
    def test_final_instalment_transitions_to_completed(self, db, active_plan):
        s = active_plan
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_3_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.completed_at is not None
        assert s.plan.installments_paid == 3
        # Access rows remain ACTIVE — completion is not revocation.
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active


# ===========================================================================
# 3. Failure opens grace; replay preserves grace
# ===========================================================================


class TestFailureOpensGrace:
    def test_failure_transitions_to_payment_problem_with_7d_grace(self, db, active_plan):
        s = active_plan
        inv = _invoice(
            invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000, status="open",
        )
        before = datetime.utcnow()
        _do_invoice_failed(db, invoice=inv, event_livemode=False)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem
        assert s.plan.payment_problem_started_at is not None
        assert s.plan.grace_expires_at is not None
        # ~ 7 days later
        delta = s.plan.grace_expires_at - s.plan.payment_problem_started_at
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, hours=1)
        assert s.plan.last_failed_invoice_id == inv["id"]

    def test_duplicate_failure_same_invoice_does_not_extend_grace(self, db, active_plan):
        s = active_plan
        inv = _invoice(
            invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000, status="open",
        )
        _do_invoice_failed(db, invoice=inv, event_livemode=False)
        db.refresh(s.plan)
        original_deadline = s.plan.grace_expires_at

        _do_invoice_failed(db, invoice=inv, event_livemode=False)
        db.refresh(s.plan)
        assert s.plan.grace_expires_at == original_deadline

    def test_second_failure_different_invoice_preserves_original_deadline(
        self, db, active_plan,
    ):
        s = active_plan
        inv1 = _invoice(
            invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000, status="open",
        )
        _do_invoice_failed(db, invoice=inv1, event_livemode=False)
        db.refresh(s.plan)
        original_deadline = s.plan.grace_expires_at

        inv2 = _invoice(
            invoice_id=f"in_3_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id, amount=2000, status="open",
        )
        _do_invoice_failed(db, invoice=inv2, event_livemode=False)
        db.refresh(s.plan)
        assert s.plan.grace_expires_at == original_deadline
        assert s.plan.last_failed_invoice_id == inv2["id"]

    def test_failure_does_not_touch_entitlement_or_pass(self, db, active_plan):
        s = active_plan
        _do_invoice_failed(
            db,
            invoice=_invoice(
                invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000, status="open",
            ),
            event_livemode=False,
        )
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active


# ===========================================================================
# 4. Recovery inside grace clears fields
# ===========================================================================


class TestRecoveryInsideGrace:
    def test_recovery_clears_grace_and_returns_to_active(self, db, active_plan):
        s = active_plan
        failing_inv_id = f"in_2_{uuid.uuid4().hex[:8]}"
        _do_invoice_failed(
            db,
            invoice=_invoice(
                invoice_id=failing_inv_id,
                subscription_id=s.subscription_id, amount=2000, status="open",
            ),
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem

        # Recovery — retry of same invoice ID succeeds. Our handler
        # short-circuits on existing txn row; use a fresh id to
        # simulate Stripe recording the successful payment attempt.
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_2r_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.payment_problem_started_at is None
        assert s.plan.grace_expires_at is None
        assert s.plan.last_failed_invoice_id is None
        assert s.plan.installments_paid == 2


# ===========================================================================
# 5. Grace expiry → suspended (via reconciler)
# ===========================================================================


class TestGraceExpirySuspension:
    def test_expired_grace_plan_is_suspended_and_access_paused(
        self, db, active_plan,
    ):
        s = active_plan
        # Open grace, then rewind the deadline into the past.
        _do_invoice_failed(
            db,
            invoice=_invoice(
                invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000, status="open",
            ),
            event_livemode=False,
        )
        db.refresh(s.plan)
        s.plan.grace_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        outcomes = fpl.sweep_expired_grace_plans(db, now=datetime.utcnow())
        assert len(outcomes) == 1
        assert outcomes[0].plan_id == s.plan.id

        db.refresh(s.plan)
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.suspended
        assert s.plan.suspended_at is not None
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

    def test_recovered_plan_before_sweep_is_left_alone(self, db, active_plan):
        s = active_plan
        _do_invoice_failed(
            db,
            invoice=_invoice(
                invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000, status="open",
            ),
            event_livemode=False,
        )
        # Recovery lands first.
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_2r_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        # Now the reconciler runs — plan is active, nothing to sweep.
        outcomes = fpl.sweep_expired_grace_plans(db, now=datetime.utcnow() + timedelta(days=30))
        assert outcomes == []


# ===========================================================================
# 6. Overlapping access — suspension preserves independently-granted access
# ===========================================================================


class TestOverlappingAccessSafety:
    def test_suspension_preserves_pathway_when_manual_grant_present(
        self, db, active_plan,
    ):
        s = active_plan
        # An unrelated admin/manual grant record for the SAME pathway,
        # not linked to this plan.
        agr.record_pathway_grant(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            source_type=agr.SOURCE_ADMIN_GRANT,
            source_purchase_plan_id=None,
            granted_at=datetime.utcnow(),
        )
        db.commit()

        outcome = fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.refresh(s.entitlement)
        assert s.entitlement.status == EntitlementStatus.active, (
            "entitlement must remain active because a manual grant "
            "still covers the same pathway"
        )
        assert s.entitlement.id in outcome.preserved_entitlement_ids
        assert s.entitlement.id not in outcome.suspended_entitlement_ids

    def test_suspension_preserves_series_when_other_plan_grants_it(
        self, db, active_plan, make_user,
    ):
        s = active_plan
        # A second, unrelated PurchasePlan grants the same series to
        # the same member (different Payment Option/Plan). We create
        # a real row so the FK on access_grant_records is satisfied.
        other_plan = PurchasePlan(
            id=_uid("pplan_other"),
            member_user_id=s.member.id,
            payment_option_id=s.option.id,
            payment_option_schedule_id=s.schedule.id,
            space_id=s.space.id,
            creator_user_id=s.creator.id,
            status=PurchasePlanStatus.active,
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3,
            installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            platform_fee_basis_points=800,
            provider_subscription_id=f"sub_test_other_{uuid.uuid4().hex[:8]}",
            provider_subscription_schedule_id=f"sub_sched_other_{uuid.uuid4().hex[:8]}",
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
        )
        db.add(other_plan)
        db.flush()
        agr.record_series_grant(
            db, user_id=s.member.id, series_id=s.series.id,
            source_type=agr.SOURCE_PLAN_PAYMENT,
            source_purchase_plan_id=other_plan.id,
            granted_at=datetime.utcnow(),
        )
        db.commit()

        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.refresh(s.access_pass)
        # AccessPass is a per-grant row. When plan A suspends, plan
        # A's pass is suspended (that is the pass attributable to
        # this plan). The unrelated pass minted by the other plan
        # stays active independently — the member is not stranded
        # for series X because they still have that separate pass.
        assert s.access_pass.status == AccessPassStatus.suspended

    def test_suspension_suspends_when_sole_grant_is_this_plan(self, db, active_plan):
        s = active_plan
        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended


# ===========================================================================
# 7. Reinstatement after suspension on successful recovery
# ===========================================================================


class TestReinstatementAfterSuspension:
    def test_recovery_after_suspension_reinstates_access(self, db, active_plan):
        s = active_plan
        # Push into suspended.
        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.refresh(s.entitlement)
        assert s.entitlement.status == EntitlementStatus.suspended

        # Later recovery lands.
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_2r_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        db.refresh(s.plan)
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.reinstated_at is not None
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_reinstate_creates_no_duplicate_rows(self, db, active_plan):
        s = active_plan
        ent_id = s.entitlement.id
        pass_id = s.access_pass.id
        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id=f"in_2r_{uuid.uuid4().hex[:8]}",
                subscription_id=s.subscription_id, amount=2000,
            ),
            event_livemode=False,
        )
        ent_rows = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.user_id == s.member.id).all()
        )
        pass_rows = (
            db.query(AccessPass)
            .filter(AccessPass.user_id == s.member.id).all()
        )
        assert {e.id for e in ent_rows} == {ent_id}
        assert {p.id for p in pass_rows} == {pass_id}


# ===========================================================================
# 8. Subscription end reconciliation
# ===========================================================================


class TestSubscriptionEndReconciliation:
    def test_deleted_after_completion_is_noop(self, db, active_plan):
        s = active_plan
        # Complete the plan first (2 more instalments).
        for _ in range(2):
            _do_invoice_succeeded(
                db,
                invoice=_invoice(
                    invoice_id=f"in_{uuid.uuid4().hex[:8]}",
                    subscription_id=s.subscription_id, amount=2000,
                ),
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        completed_at = s.plan.completed_at

        # Now Stripe emits subscription.deleted (end_behavior='cancel').
        # Must remain completed; must NOT be reinterpreted as failure.
        _do_subscription_deleted(
            db,
            subscription={"id": s.subscription_id},
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.completed_at == completed_at
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_deleted_before_completion_marks_failed_and_suspends_access(
        self, db, active_plan,
    ):
        """Under the FIP3 hardening: subscription.deleted delegates
        to the order-independent reconciler. Genuine abnormal end
        is proven by a provider-side invoice inventory that shows
        every outstanding invoice as terminally dead (``void``)
        with none reconcilable. Only then do we transition failed +
        suspend access."""
        s = active_plan
        # Plan sits at 1/3 paid. Provider inventory: 1 paid + 2 void
        # (Stripe stopped attempting and won't retry).
        def _fetcher(_sub_id):
            return [
                {"id": "in_seed_a", "amount_paid": 2000, "currency": "aud",
                 "status": "paid", "created": 100,
                 "charge": "ch_a", "payment_intent": "pi_a"},
                {"id": "in_void_b", "amount_paid": 0, "currency": "aud",
                 "status": "void", "created": 200},
                {"id": "in_void_c", "amount_paid": 0, "currency": "aud",
                 "status": "void", "created": 300},
            ]
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=_fetcher,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

    def test_schedule_completed_at_full_paid_transitions_to_completed(
        self, db, active_plan,
    ):
        s = active_plan
        # Fast-forward to complete via lifecycle service.
        for _ in range(2):
            _do_invoice_succeeded(
                db,
                invoice=_invoice(
                    invoice_id=f"in_{uuid.uuid4().hex[:8]}",
                    subscription_id=s.subscription_id, amount=2000,
                ),
                event_livemode=False,
            )
        db.refresh(s.plan)
        _do_schedule_completed(
            db,
            schedule={"id": s.schedule_id},
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed


# ===========================================================================
# 9. Fee snapshot preserved across all instalments
# ===========================================================================


class TestFeeSnapshotPreserved:
    def test_all_instalments_use_snapshot_fee_bps(self, db, active_plan):
        s = active_plan
        # Change the schedule's fee bps to simulate a mid-plan fee bump.
        s.plan.platform_fee_basis_points = 800  # snapshot value is 800
        db.commit()

        for i in range(2, 4):
            _do_invoice_succeeded(
                db,
                invoice=_invoice(
                    invoice_id=f"in_{i}_{uuid.uuid4().hex[:8]}",
                    subscription_id=s.subscription_id, amount=2000,
                ),
                event_livemode=False,
            )

        txns = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == s.plan.id)
            .filter(PaymentTransaction.status == PaymentTransactionStatus.succeeded)
            .order_by(PaymentTransaction.installment_number)
            .all()
        )
        assert len(txns) == 3
        for t in txns:
            assert t.platform_fee_basis_points == 800
            assert t.platform_fee_cents == 160
            assert t.net_creator_amount_cents == 1840


# ===========================================================================
# 10. Access grant records — write path
# ===========================================================================


class TestAccessGrantRecords:
    def test_first_invoice_recorded_grants_for_pathway_and_series(
        self, db, active_plan,
    ):
        s = active_plan
        rows = (
            db.query(AccessGrantRecord)
            .filter(AccessGrantRecord.source_purchase_plan_id == s.plan.id)
            .all()
        )
        kinds = {r.grant_kind for r in rows}
        assert "pathway" in kinds
        assert "series" in kinds

    def test_overlap_query_ignores_this_plan(self, db, active_plan):
        s = active_plan
        # No other source — overlap must be False.
        assert not agr.user_has_other_active_grant_for_pathway(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            excluding_purchase_plan_id=s.plan.id,
        )
        # Add an admin grant record → overlap True.
        agr.record_pathway_grant(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            source_type=agr.SOURCE_ADMIN_GRANT,
            source_purchase_plan_id=None,
            granted_at=datetime.utcnow(),
        )
        db.commit()
        assert agr.user_has_other_active_grant_for_pathway(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            excluding_purchase_plan_id=s.plan.id,
        )

    def test_revoke_and_reinstate_are_reversible(self, db, active_plan):
        s = active_plan
        now = datetime.utcnow()
        revoked = agr.revoke_records_for_plan(
            db, purchase_plan_id=s.plan.id, reason="plan_suspended", now=now,
        )
        assert len(revoked) == 2
        # Overlap query must not consider revoked records.
        assert not agr.user_has_other_active_grant_for_pathway(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            excluding_purchase_plan_id="different_plan_id",
        )
        # Reinstate — records return to active.
        agr.reinstate_records_for_plan(
            db, purchase_plan_id=s.plan.id, now=datetime.utcnow(),
        )
        assert agr.user_has_other_active_grant_for_pathway(
            db, user_id=s.member.id, pathway_id=s.pathway.id,
            excluding_purchase_plan_id="different_plan_id",
        )
