"""FIP3 hardening — order-independence + historical overlap safety.

Section 1 — Order-independence of finite-end reconciliation
   subscription.deleted / schedule.completed events MUST NOT
   make a terminal failure decision from the local counter
   alone. They delegate to
   ``services.finite_plan_end_reconciliation`` which pulls
   Stripe's authoritative invoice inventory and reconciles any
   paid invoices we haven't yet ledgered before deciding.

   Tests:
     1a. final invoice.succeeded arrives BEFORE subscription.deleted
     1b. subscription.deleted arrives BEFORE final invoice.succeeded
         (reconciler finds paid invoice and completes)
     1c. schedule.completed arrives BEFORE final invoice.succeeded
     1d. delayed / replayed final invoice.succeeded on a plan the
         reconciler couldn't complete (deferred / abnormal case);
         late success still recovers
     1e. genuine early cancellation with unpaid instalments still
         transitions to failed + suspends access

Section 2 — Historical overlapping-access safety
   Pre-FIP3 grants (rows created before migration 119) that DO
   NOT have access_grant_records must still be treated as
   independent access sources when a later finite plan reactivates
   the same entitlement / pass.

   The migration's expanded backfill inserts one grant record per
   active PathwayEntitlement / AccessPass BEFORE the plan
   reactivates them, so overlap queries during suspension find
   the historical provenance. Additionally,
   ``_apply_entitlement`` no longer overwrites the row's
   ``source`` column on reactivation — a belt-and-braces signal.

   Tests:
     2A. historical manual/admin grant → plan reactivates → plan suspends
     2B. historical pay-in-full grant → plan reactivates → plan suspends
     2C. equivalent Series/AccessPass scenario
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
from app.services.finite_plan_end_reconciliation import (
    DECISION_ABNORMAL, DECISION_COMPLETED, DECISION_DEFERRED,
    reconcile_finite_plan_end,
)
from app.services.purchase_fulfilment import (
    AccessPassIntent, EntitlementIntent, FulfilmentIntent,
    apply_intent, serialise_intent,
)
from app.webhooks.finite_plan_handlers import (
    _do_invoice_succeeded, _do_subscription_deleted, _do_schedule_completed,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture shared with hardening tests
# ---------------------------------------------------------------------------


@pytest.fixture
def near_end_plan(db, make_user, make_space):
    """Plan sitting at 2/3 paid (one instalment away from completion)."""
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
    schedule_id = f"sub_sched_{uuid.uuid4().hex[:12]}"

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
        installments_expected=3, installments_paid=2,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_subscription_id=subscription_id,
        provider_subscription_schedule_id=schedule_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan); db.flush()

    # Seed the first two paid PaymentTransactions with predictable
    # provider_invoice_ids so hardening tests can craft matching
    # provider invoice lists.
    seed_invoice_ids = ["in_seed_1", "in_seed_2"]
    txns = []
    for i, inv_id in enumerate(seed_invoice_ids, start=1):
        t = PaymentTransaction(
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
            provider_invoice_id=inv_id,
            provider_subscription_id=subscription_id,
            payment_option_id=opt.id, payment_option_schedule_id=sched.id,
            purchase_plan_id=plan.id, installment_number=i,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(t); db.flush()
        txns.append(t)

    # Entitlement + AccessPass linked to plan (first-invoice fulfilment).
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
        payment_transaction_id=txns[0].id,
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
        source_payment_transaction_id=txns[0].id,
        granted_at=now,
    )
    agr.record_series_grant(
        db, user_id=member.id, series_id=series.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=txns[0].id,
        granted_at=now,
    )
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, pathway=pathway, option=opt, schedule=sched,
        plan=plan, subscription_id=subscription_id, schedule_id=schedule_id,
        entitlement=ent, access_pass=ap,
    )


def _stripe_invoice(*, invoice_id: str, amount: int = 2000,
                    status: str = "paid", created: int = 0) -> dict:
    return {
        "id": invoice_id,
        "amount_paid": amount if status == "paid" else 0,
        "amount_due": amount,
        "total": amount,   # FIP4A: contractual amount is authoritative
        "currency": "aud",
        "status": status,
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
        "created": created,
    }


def _fetcher_returning(invoices: list[dict]):
    """Build an InvoiceFetcher that ignores the subscription_id and
    returns the provided list (a copy each call so mutation-safe)."""
    def _fetch(_subscription_id: str) -> list[dict]:
        return [dict(i) for i in invoices]
    return _fetch


# ===========================================================================
# Section 1 — Order-independence
# ===========================================================================


class TestOrderIndependentFiniteEnd:

    def test_1a_final_invoice_then_subscription_deleted(self, db, near_end_plan):
        """Invoice.succeeded lands FIRST → plan completed. Then
        subscription.deleted arrives. Provider agrees (all invoices
        paid). Plan stays completed; access preserved."""
        s = near_end_plan
        # Final invoice arrives via webhook.
        final_inv_id = f"in_final_{uuid.uuid4().hex[:8]}"
        _do_invoice_succeeded(
            db,
            invoice={
                "id": final_inv_id,
                "subscription": s.subscription_id,
                "amount_paid": 2000, "total": 2000, "currency": "aud", "status": "paid",
                "charge": f"ch_{uuid.uuid4().hex[:8]}",
                "payment_intent": f"pi_{uuid.uuid4().hex[:8]}",
            },
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        completed_at = s.plan.completed_at

        # subscription.deleted delivered afterwards. Reconciler sees
        # all 3 invoices as paid → decision=completed → no-op.
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", created=100),
            _stripe_invoice(invoice_id="in_seed_2", created=200),
            _stripe_invoice(invoice_id=final_inv_id, created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.completed_at == completed_at
        db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_1b_subscription_deleted_before_final_invoice_completes_via_reconcile(
        self, db, near_end_plan,
    ):
        """Reconciler sees the paid final invoice in Stripe even
        though we've never processed a webhook for it. It drives
        the plan to completed itself. Access preserved."""
        s = near_end_plan
        missing_inv_id = f"in_final_{uuid.uuid4().hex[:8]}"
        fetcher = _fetcher_returning([
            # Two we already have + one we don't.
            _stripe_invoice(invoice_id="in_seed_1", created=100),
            _stripe_invoice(invoice_id="in_seed_2", created=200),
            _stripe_invoice(invoice_id=missing_inv_id, created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.installments_paid == 3
        assert s.plan.completed_at is not None
        db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

        # And the third PaymentTransaction is written correctly.
        third = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == missing_inv_id)
            .one()
        )
        assert third.installment_number == 3
        assert third.status == PaymentTransactionStatus.succeeded

    def test_1c_schedule_completed_before_final_invoice_completes(self, db, near_end_plan):
        s = near_end_plan
        missing_inv_id = f"in_final_{uuid.uuid4().hex[:8]}"
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", created=100),
            _stripe_invoice(invoice_id="in_seed_2", created=200),
            _stripe_invoice(invoice_id=missing_inv_id, created=300),
        ])
        fpl.handle_schedule_completed_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        assert s.plan.installments_paid == 3

    def test_1d_late_final_invoice_recovers_a_failed_plan(self, db, near_end_plan):
        """Genuine out-of-order incident: subscription.deleted arrives
        AND Stripe temporarily shows the final invoice as failed
        (so we go to ``failed`` + suspend). Then the actual paid
        webhook arrives late. The plan MUST recover to completed
        and access MUST be restored."""
        s = near_end_plan
        # Simulate: Stripe API temporarily reports all invoices as
        # failed (open/uncollectible). Reconciler decides abnormal.
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", status="paid", created=100),
            _stripe_invoice(invoice_id="in_seed_2", status="paid", created=200),
            _stripe_invoice(invoice_id="in_final_dead", status="uncollectible", created=300),
        ])
        # We want abnormal here, not deferred — force by clearing
        # the ambiguous invoice: use void status which is terminal-dead.
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", status="paid", created=100),
            _stripe_invoice(invoice_id="in_seed_2", status="paid", created=200),
            _stripe_invoice(invoice_id="in_final_void", status="void", created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.failed
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

        # NOW the delayed successful final invoice arrives.
        late_inv_id = f"in_late_final_{uuid.uuid4().hex[:8]}"
        _do_invoice_succeeded(
            db,
            invoice={
                "id": late_inv_id,
                "subscription": s.subscription_id,
                "amount_paid": 2000, "total": 2000, "currency": "aud", "status": "paid",
                "charge": f"ch_{uuid.uuid4().hex[:8]}",
                "payment_intent": f"pi_{uuid.uuid4().hex[:8]}",
            },
            event_livemode=False,
        )
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.completed, (
            "late final invoice must recover a failed plan to completed"
        )
        assert s.plan.installments_paid == 3
        assert s.entitlement.status == EntitlementStatus.active, (
            "access suspended by the out-of-order provider-end event "
            "must be restored when the paid final invoice arrives late"
        )
        assert s.access_pass.status == AccessPassStatus.active

    def test_1e_genuine_early_cancellation_still_fails(self, db, near_end_plan):
        """Provider genuinely ended with one instalment unpaid + no
        pending activity. Reconciler returns abnormal, plan goes
        failed, access suspended (source-aware)."""
        s = near_end_plan
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", status="paid", created=100),
            _stripe_invoice(invoice_id="in_seed_2", status="paid", created=200),
            _stripe_invoice(invoice_id="in_dead_final", status="void", created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.failed
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

    def test_1f_ambiguous_provider_state_defers_terminal_decision(
        self, db, near_end_plan,
    ):
        """Reconciler with an OPEN invoice defers instead of failing.
        Plan stays active; access untouched."""
        s = near_end_plan
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", status="paid", created=100),
            _stripe_invoice(invoice_id="in_seed_2", status="paid", created=200),
            _stripe_invoice(invoice_id="in_open_final", status="open", created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan); db.refresh(s.entitlement); db.refresh(s.access_pass)
        assert s.plan.status == PurchasePlanStatus.active, (
            "ambiguous provider state must defer terminal transition"
        )
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_1g_provider_lags_behind_installments_expected_defers(
        self, db, near_end_plan,
    ):
        """Stripe shows fewer invoices than the plan expects
        (invoice creation lagging). Reconciler defers."""
        s = near_end_plan
        # Only 2 invoices visible, plan expects 3.
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", status="paid", created=100),
            _stripe_invoice(invoice_id="in_seed_2", status="paid", created=200),
        ])
        outcome = reconcile_finite_plan_end(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        assert outcome.decision == DECISION_DEFERRED

    def test_1h_reconciler_deferred_on_stripe_api_failure(self, db, near_end_plan):
        s = near_end_plan
        def _boom(_sid): raise RuntimeError("Stripe timeout")
        outcome = reconcile_finite_plan_end(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=_boom,
        )
        assert outcome.decision == DECISION_DEFERRED
        assert "Stripe timeout" in (outcome.note or "")

    def test_1i_replay_of_reconciler_is_idempotent(self, db, near_end_plan):
        """Two calls in a row (e.g., subscription.deleted delivered
        twice, or a schedule.completed + deleted pair) do not
        double-book."""
        s = near_end_plan
        missing_inv_id = f"in_final_{uuid.uuid4().hex[:8]}"
        fetcher = _fetcher_returning([
            _stripe_invoice(invoice_id="in_seed_1", created=100),
            _stripe_invoice(invoice_id="in_seed_2", created=200),
            _stripe_invoice(invoice_id=missing_inv_id, created=300),
        ])
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        fpl.handle_subscription_deleted_for_plan(
            db, plan=s.plan, now=datetime.utcnow(),
            invoice_fetcher=fetcher,
        )
        db.refresh(s.plan)
        assert s.plan.installments_paid == 3
        # Only one PaymentTransaction for the reconciled invoice.
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == missing_inv_id)
            .all()
        )
        assert len(rows) == 1


# ===========================================================================
# Section 2 — Historical overlapping-access safety
# ===========================================================================


class TestHistoricalOverlappingAccess:
    """Rows created BEFORE migration 119 that have no grant records
    from creation time. The migration backfills one grant record
    per active row so overlap queries function; ``_apply_entitlement``
    additionally preserves the row's ``source`` column on
    reactivation so historical provenance survives."""

    def _bootstrap_historical(
        self, db, make_user, make_space,
        *,
        entitlement_source: EntitlementSource,
        with_pay_in_full_txn: bool = False,
    ):
        """Create a pre-FIP3 grant simulation:
          * user, space, pathway, series
          * historical PathwayEntitlement rooted in a non-plan source
          * optional pay-in-full PaymentTransaction linked via
            AccessPass.payment_transaction_id
          * NO access_grant_record — mirrors pre-FIP3 rows
          * Then run apply_intent with a plan → reactivates.
          * Then run suspension → assert history is preserved.
        """
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
            slug=f"p-{uuid.uuid4().hex[:8]}", title="X",
            status="active",
        )
        db.add_all([series, pathway]); db.flush()

        # Historical entitlement pre-dates any FIP3 grant record.
        now = datetime.utcnow()
        historical = PathwayEntitlement(
            id=_uid("pe"), user_id=member.id, space_id=space.id,
            pathway_id=pathway.id,
            source=entitlement_source,
            status=EntitlementStatus.active,
            starts_at=now - timedelta(days=180),
            purchase_plan_id=None,
            created_at=now - timedelta(days=180),
            updated_at=now - timedelta(days=180),
        )
        db.add(historical); db.flush()

        historical_txn = None
        historical_ap = None
        if with_pay_in_full_txn:
            historical_txn = PaymentTransaction(
                id=str(uuid.uuid4()),
                transaction_type=PaymentTransactionType.member_payment_option_purchase,
                status=PaymentTransactionStatus.succeeded,
                payment_provider=PaymentProvider.stripe,
                fulfilment_status=PaymentFulfilmentStatus.applied,
                payer_user_id=member.id, creator_user_id=creator.id,
                space_id=space.id, currency="AUD",
                gross_amount_cents=50000, platform_fee_basis_points=800,
                platform_fee_cents=4000, net_creator_amount_cents=46000,
                net_platform_amount_cents=4000,
                purchase_plan_id=None, installment_number=None,
                stripe_mode="test", payout_status=PayoutStatus.paid,
                created_at=now - timedelta(days=180),
                updated_at=now - timedelta(days=180),
            )
            db.add(historical_txn); db.flush()
            historical_ap = AccessPass(
                id=_uid("ap_hist"), user_id=member.id, space_id=space.id,
                payment_transaction_id=historical_txn.id,
                pass_type=AccessPassType.pathway_access,
                status=AccessPassStatus.active,
                valid_from=now - timedelta(days=180),
                eligible_pathway_id=pathway.id,
                source=AccessPassSource.one_time_purchase,
                created_at=now - timedelta(days=180),
                updated_at=now - timedelta(days=180),
            )
            db.add(historical_ap); db.flush()

        db.commit()
        # Simulate the migration's backfill for this newly-created
        # "historical" row. In production the migration inserts
        # records for every active pathway_entitlement / access_pass
        # at deploy time; here we hand-emulate for rows created
        # inside the test.
        _mig_backfill_for_entitlement(db, historical)
        if historical_ap is not None:
            _mig_backfill_for_access_pass(db, historical_ap)
        db.commit()

        return SimpleNamespace(
            member=member, creator=creator, space=space,
            series=series, pathway=pathway,
            historical_entitlement=historical,
            historical_transaction=historical_txn,
            historical_access_pass=historical_ap,
        )

    def _create_plan_and_reactivate(self, db, ctx):
        """Fresh finite plan whose first-invoice fulfilment
        reactivates the historical entitlement row."""
        opt = PaymentOption(
            id=_uid("po"), space_id=ctx.space.id,
            attaches_to_kind="pathway", attaches_to_id=ctx.pathway.id,
            name="Plan for X",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
            grants_pathway_id=ctx.pathway.id,
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
        now = datetime.utcnow()
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=ctx.member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            space_id=ctx.space.id, creator_user_id=ctx.creator.id,
            status=PurchasePlanStatus.active,
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3, installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            platform_fee_basis_points=800,
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            provider_subscription_schedule_id=f"ss_{uuid.uuid4().hex[:8]}",
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [
                {"pathway_id": ctx.pathway.id, "starts_at": None, "ends_at": None},
            ], "access_passes": [], "bookings": []},
            activated_at=now,
        )
        db.add(plan); db.flush()

        # PaymentTransaction #1 for the plan.
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            payer_user_id=ctx.member.id, creator_user_id=ctx.creator.id,
            space_id=ctx.space.id, currency="AUD",
            gross_amount_cents=2000, platform_fee_basis_points=800,
            platform_fee_cents=160, net_creator_amount_cents=1840,
            net_platform_amount_cents=160,
            provider_invoice_id=f"in_{uuid.uuid4().hex[:8]}",
            provider_subscription_id=plan.provider_subscription_id,
            payment_option_id=opt.id, payment_option_schedule_id=sched.id,
            purchase_plan_id=plan.id, installment_number=1,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(txn); db.flush()

        # Fulfilment intent → apply_intent reactivates the historical row.
        intent = FulfilmentIntent(
            entitlements=(EntitlementIntent(pathway_id=ctx.pathway.id, ends_at=None),),
            access_passes=(),
        )
        apply_intent(
            db, intent=intent, txn=txn,
            payer_user_id=ctx.member.id, space_id=ctx.space.id,
            payment_option_id=opt.id, payment_option_schedule_id=sched.id,
            session_id=None, payment_intent_id=None, now=now,
            purchase_plan_id=plan.id,
        )
        db.commit()
        return plan

    def test_2a_historical_admin_grant_survives_plan_suspension(
        self, db, make_user, make_space,
    ):
        ctx = self._bootstrap_historical(
            db, make_user, make_space,
            entitlement_source=EntitlementSource.admin,
        )
        plan = self._create_plan_and_reactivate(db, ctx)

        # Row still exists as one entitlement; source column preserved.
        db.refresh(ctx.historical_entitlement)
        assert ctx.historical_entitlement.source == EntitlementSource.admin
        assert ctx.historical_entitlement.purchase_plan_id == plan.id

        # Suspend the plan.
        fpl.suspend_plan_now(db, plan=plan, now=datetime.utcnow())
        db.refresh(ctx.historical_entitlement)
        assert ctx.historical_entitlement.status == EntitlementStatus.active, (
            "historical admin_grant entitlement must not be suspended "
            "when a subsequent plan-driven reactivation is suspended"
        )

    def test_2b_historical_pay_in_full_survives_plan_suspension(
        self, db, make_user, make_space,
    ):
        ctx = self._bootstrap_historical(
            db, make_user, make_space,
            entitlement_source=EntitlementSource.one_time_purchase,
            with_pay_in_full_txn=True,
        )
        plan = self._create_plan_and_reactivate(db, ctx)
        db.refresh(ctx.historical_entitlement)
        # Source stays one_time_purchase (was already), plan takes ownership.
        assert ctx.historical_entitlement.purchase_plan_id == plan.id

        fpl.suspend_plan_now(db, plan=plan, now=datetime.utcnow())
        db.refresh(ctx.historical_entitlement)
        assert ctx.historical_entitlement.status == EntitlementStatus.active, (
            "historical pay-in-full entitlement must not be suspended "
            "when a subsequent plan-driven reactivation is suspended"
        )

    def test_2c_historical_series_pass_survives_plan_suspension(
        self, db, make_user, make_space,
    ):
        """AccessPass equivalent: user has a historical Series pass
        (from admin grant or old pay-in-full). Later a finite plan
        for a different option grants the same Series. Suspending
        the finite plan leaves the historical pass alone."""
        member = make_user()
        creator = make_user(role="creator")
        space = make_space(creator=creator)

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
            name="Historic pass",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=50000, currency="AUD",
        )
        db.add(opt); db.flush()
        now = datetime.utcnow()
        historical_txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            payer_user_id=member.id, creator_user_id=creator.id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=50000, platform_fee_basis_points=800,
            platform_fee_cents=4000, net_creator_amount_cents=46000,
            net_platform_amount_cents=4000,
            payment_option_id=opt.id,
            purchase_plan_id=None, installment_number=None,
            stripe_mode="test", payout_status=PayoutStatus.paid,
            created_at=now - timedelta(days=90),
            updated_at=now - timedelta(days=90),
        )
        db.add(historical_txn); db.flush()

        historical_ap = AccessPass(
            id=_uid("ap_hist"), user_id=member.id, space_id=space.id,
            payment_transaction_id=historical_txn.id,
            payment_option_id=opt.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=now - timedelta(days=90),
            eligible_series_id=series.id,
            source=AccessPassSource.one_time_purchase,
            created_at=now - timedelta(days=90),
            updated_at=now - timedelta(days=90),
        )
        db.add(historical_ap); db.flush()
        db.commit()
        _mig_backfill_for_access_pass(db, historical_ap)
        db.commit()

        # Now a finite plan for the same series grants a plan-owned pass.
        plan_opt = PaymentOption(
            id=_uid("po2"), space_id=space.id,
            attaches_to_kind="event_series", attaches_to_id=series.id,
            name="Plan pass",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
        )
        plan_sched = PaymentOptionSchedule(
            id=_uid("sched2"), payment_option_id=plan_opt.id,
            name="Weekly × 3", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=3,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=6000, currency="AUD",
        )
        db.add_all([plan_opt, plan_sched]); db.flush()
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=plan_opt.id,
            payment_option_schedule_id=plan_sched.id,
            space_id=space.id, creator_user_id=creator.id,
            status=PurchasePlanStatus.active,
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3, installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            platform_fee_basis_points=800,
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            provider_subscription_schedule_id=f"ss_{uuid.uuid4().hex[:8]}",
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
            activated_at=now,
        )
        db.add(plan); db.flush()
        plan_txn = PaymentTransaction(
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
            provider_invoice_id=f"in_{uuid.uuid4().hex[:8]}",
            payment_option_id=plan_opt.id,
            payment_option_schedule_id=plan_sched.id,
            purchase_plan_id=plan.id, installment_number=1,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(plan_txn); db.flush()

        # Plan grants a new AccessPass linked to the plan.
        plan_ap = AccessPass(
            id=_uid("ap_plan"), user_id=member.id, space_id=space.id,
            payment_transaction_id=plan_txn.id,
            payment_option_id=plan_opt.id,
            payment_option_schedule_id=plan_sched.id,
            purchase_plan_id=plan.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_from=now, eligible_series_id=series.id,
            source=AccessPassSource.one_time_purchase,
            created_at=now, updated_at=now,
        )
        db.add(plan_ap); db.flush()
        agr.record_series_grant(
            db, user_id=member.id, series_id=series.id,
            source_type=agr.SOURCE_PLAN_PAYMENT,
            source_purchase_plan_id=plan.id,
            source_payment_transaction_id=plan_txn.id,
            granted_at=now,
        )
        db.commit()

        # Suspend plan → historical pass survives; plan pass suspends.
        fpl.suspend_plan_now(db, plan=plan, now=datetime.utcnow())
        db.refresh(historical_ap); db.refresh(plan_ap)
        assert historical_ap.status == AccessPassStatus.active, (
            "historical AccessPass for the same series must survive "
            "plan suspension via the migration-119 backfilled grant record"
        )
        assert plan_ap.status == AccessPassStatus.suspended

    def test_2_source_column_preserved_on_reactivation(
        self, db, make_user, make_space,
    ):
        """Regression guard for the ``_apply_entitlement`` change —
        source must NOT be overwritten by plan-driven reactivation."""
        ctx = self._bootstrap_historical(
            db, make_user, make_space,
            entitlement_source=EntitlementSource.admin,
        )
        self._create_plan_and_reactivate(db, ctx)
        db.refresh(ctx.historical_entitlement)
        assert ctx.historical_entitlement.source == EntitlementSource.admin


# ---------------------------------------------------------------------------
# Helpers — hand-emulate the migration-119 backfill for rows created
# inside a test transaction (the migration itself runs before the test).
# ---------------------------------------------------------------------------


def _mig_backfill_for_entitlement(db, ent: PathwayEntitlement) -> None:
    source_map = {
        EntitlementSource.one_time_purchase: agr.SOURCE_PAY_IN_FULL,
        EntitlementSource.admin: agr.SOURCE_ADMIN_GRANT,
        EntitlementSource.manual_grant: agr.SOURCE_ADMIN_GRANT,
        EntitlementSource.subscription: agr.SOURCE_SUBSCRIPTION,
        EntitlementSource.free: agr.SOURCE_FREE,
        EntitlementSource.included: agr.SOURCE_FREE,
    }
    source_type = (
        agr.SOURCE_PLAN_PAYMENT if ent.purchase_plan_id
        else source_map.get(ent.source, agr.SOURCE_MANUAL)
    )
    agr.record_pathway_grant(
        db, user_id=ent.user_id, pathway_id=ent.pathway_id,
        source_type=source_type,
        source_purchase_plan_id=ent.purchase_plan_id,
        granted_at=ent.created_at,
    )


def _mig_backfill_for_access_pass(db, ap: AccessPass) -> None:
    ap_source_map = {
        AccessPassSource.one_time_purchase: agr.SOURCE_PAY_IN_FULL,
        AccessPassSource.admin_grant: agr.SOURCE_ADMIN_GRANT,
        AccessPassSource.manual: agr.SOURCE_ADMIN_GRANT,
        AccessPassSource.subscription: agr.SOURCE_SUBSCRIPTION,
        AccessPassSource.free: agr.SOURCE_FREE,
    }
    source_type = (
        agr.SOURCE_PLAN_PAYMENT if ap.purchase_plan_id
        else ap_source_map.get(ap.source, agr.SOURCE_MANUAL)
    )
    if ap.eligible_series_id:
        agr.record_series_grant(
            db, user_id=ap.user_id, series_id=ap.eligible_series_id,
            source_type=source_type,
            source_purchase_plan_id=ap.purchase_plan_id,
            source_payment_transaction_id=ap.payment_transaction_id,
            granted_at=ap.created_at,
        )
    elif ap.eligible_pathway_id:
        agr.record_pathway_grant(
            db, user_id=ap.user_id, pathway_id=ap.eligible_pathway_id,
            source_type=source_type,
            source_purchase_plan_id=ap.purchase_plan_id,
            source_payment_transaction_id=ap.payment_transaction_id,
            granted_at=ap.created_at,
        )
