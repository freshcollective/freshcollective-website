"""FIP4C — creator visibility of finite payment plans.

Covers spec §13 + the FIP4C-refine owner-only rule:

  O1  creator sees plans for own Collective only
  O2  creator cannot see another creator's plans
  O3  moderator CANNOT see plans in a Collective they only moderate
      (Payment Plans is a financial-visibility surface; per
      docs/permissions-matrix.md moderators "do not inherit
      billing privileges")
  O4  mixed role — a user who owns A and moderates B sees plans + attention for A only
  D1  active plan summary shape
  D2  payment_problem summary shape
  D3  suspended summary shape
  D4  completed summary shape
  F1  default view hides failed / cancelled / pending_setup
  F2  explicit status filter surfaces failed / cancelled / pending_setup
  F3  payment_option_id filter narrows the response
  F4  member_search matches name or email, case-insensitive
  M1  X of N paid comes from plan counters
  M2  total = installments_expected * installment_amount_cents
  M3  paid_amount_cents sums succeeded PaymentTransactions only (skips failed rows)
  M4  remaining_amount_cents = total - paid; never negative
  M5  customer-balance audit-note scenario (invoice.total contractual) still totals correctly
  T1  pay-in-full transaction row remains unchanged (unaffected by FIP4C)
  T2  finite-plan transaction row carries purchase_plan_id + installment_number
  T3  pay-in-full transaction row has both fields NULL
  L1  no provider ids leak into CreatorPurchasePlanSummary
  L2  no provider ids leak into CreatorPaymentTransactionOut
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.creator.routes import (
    get_creator_payment_plans_attention_count,
    list_creator_payment_plans,
    list_creator_payments,
)
from app.creator.schemas import (
    CreatorPaymentPlansAttentionCount,
    CreatorPaymentTransactionOut,
    CreatorPurchasePlanSummary,
)
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import SpaceMembership
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Helper — build a canonical plan + its succeeded/failed instalment rows
# ---------------------------------------------------------------------------


def _make_option_and_schedule(db, space, *, name="Test Plan", inst_cents=2000, count=3):
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="space", attaches_to_id=space.id,
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=inst_cents * count, currency="AUD",
    )
    db.add(opt); db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name=f"Weekly × {count}",
        schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=inst_cents, installment_count=count,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=inst_cents * count, currency="AUD",
    )
    db.add(sched); db.flush()
    return opt, sched


def _make_plan(
    db, *, member, creator, space, option, schedule,
    status=PurchasePlanStatus.active, paid=1,
):
    now = datetime.utcnow()
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=option.id,
        payment_option_schedule_id=schedule.id,
        space_id=space.id, creator_user_id=creator.id,
        status=status,
        currency=schedule.currency,
        installment_amount_cents=schedule.installment_amount_cents,
        installments_expected=schedule.installment_count,
        installments_paid=paid,
        total_expected_cents=schedule.installment_amount_cents * schedule.installment_count,
        stripe_interval=schedule.stripe_interval,
        stripe_interval_count=schedule.stripe_interval_count,
        platform_fee_basis_points=800,
        stripe_mode="test",
        activated_at=now if paid > 0 else None,
    )
    db.add(plan); db.flush()
    return plan


def _make_succeeded_txn(db, plan, invoice_id, installment_number):
    """Create a succeeded PaymentTransaction for a plan's instalment."""
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=plan.member_user_id, creator_user_id=plan.creator_user_id,
        space_id=plan.space_id, currency=plan.currency,
        gross_amount_cents=plan.installment_amount_cents,
        platform_fee_basis_points=plan.platform_fee_basis_points,
        platform_fee_cents=int(plan.installment_amount_cents * plan.platform_fee_basis_points / 10000),
        net_creator_amount_cents=plan.installment_amount_cents - int(plan.installment_amount_cents * plan.platform_fee_basis_points / 10000),
        net_platform_amount_cents=int(plan.installment_amount_cents * plan.platform_fee_basis_points / 10000),
        provider_invoice_id=invoice_id,
        payment_option_id=plan.payment_option_id,
        payment_option_schedule_id=plan.payment_option_schedule_id,
        purchase_plan_id=plan.id,
        installment_number=installment_number,
        stripe_mode="test", payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn); db.flush()
    return txn


def _make_failed_txn(db, plan, invoice_id):
    """Create a failed PaymentTransaction (mirrors FIP3 handle_invoice_failed_for_plan)."""
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.failed,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.pending,
        payer_user_id=plan.member_user_id, creator_user_id=plan.creator_user_id,
        space_id=plan.space_id, currency=plan.currency,
        gross_amount_cents=plan.installment_amount_cents,
        platform_fee_basis_points=plan.platform_fee_basis_points,
        platform_fee_cents=0,
        net_creator_amount_cents=0,
        net_platform_amount_cents=0,
        provider_invoice_id=invoice_id,
        payment_option_id=plan.payment_option_id,
        payment_option_schedule_id=plan.payment_option_schedule_id,
        purchase_plan_id=plan.id,
        installment_number=None,
        stripe_mode="test", payout_status=PayoutStatus.not_applicable,
        created_at=now, updated_at=now,
    )
    db.add(txn); db.flush()
    return txn


def _make_payinfull_txn(db, *, payer, creator, space, option, gross_cents=5000):
    """Create a pay-in-full succeeded transaction with NO purchase_plan_id."""
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=payer.id, creator_user_id=creator.id,
        space_id=space.id, currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=800,
        platform_fee_cents=int(gross_cents * 800 / 10000),
        net_creator_amount_cents=gross_cents - int(gross_cents * 800 / 10000),
        net_platform_amount_cents=int(gross_cents * 800 / 10000),
        payment_option_id=option.id,
        purchase_plan_id=None,
        installment_number=None,
        stripe_mode="test", payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn); db.flush()
    return txn


# ---------------------------------------------------------------------------
# Fixtures — two creators, each with a Collective + members
# ---------------------------------------------------------------------------


@pytest.fixture
def scene(db, make_user, make_space):
    """Two independent creators + one member each. Every test starts
    with a clean plan-less DB scoped to the test's SAVEPOINT."""
    creator_a = make_user(role="creator")
    creator_b = make_user(role="creator")
    space_a = make_space(creator=creator_a)
    space_b = make_space(creator=creator_b)
    member_a = make_user()
    member_b = make_user()
    db.commit()
    return SimpleNamespace(
        creator_a=creator_a, creator_b=creator_b,
        space_a=space_a, space_b=space_b,
        member_a=member_a, member_b=member_b,
    )


# ---------------------------------------------------------------------------
# O-series — ownership scoping
# ---------------------------------------------------------------------------


class TestOwnership:
    def test_O1_creator_sees_only_own_plans(self, db, scene):
        opt_a, sched_a = _make_option_and_schedule(db, scene.space_a, name="A plan")
        opt_b, sched_b = _make_option_and_schedule(db, scene.space_b, name="B plan")
        plan_a = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                            space=scene.space_a, option=opt_a, schedule=sched_a)
        plan_b = _make_plan(db, member=scene.member_b, creator=scene.creator_b,
                            space=scene.space_b, option=opt_b, schedule=sched_b)
        db.commit()

        out = list_creator_payment_plans(
            status=None, payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        ids = {p.id for p in out}
        assert plan_a.id in ids
        assert plan_b.id not in ids

    def test_O2_cannot_see_other_creators_plans_via_option_filter(self, db, scene):
        """Even if the caller guesses a payment_option_id belonging to
        someone else's Collective, the space-id filter runs first and
        the response stays empty."""
        opt_b, sched_b = _make_option_and_schedule(db, scene.space_b, name="B plan")
        _make_plan(db, member=scene.member_b, creator=scene.creator_b,
                   space=scene.space_b, option=opt_b, schedule=sched_b)
        db.commit()

        out = list_creator_payment_plans(
            status=None, payment_option_id=opt_b.id, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert out == []

    def test_O3_moderator_cannot_see_plans_in_moderated_space(self, db, scene, make_user):
        """Moderators do not inherit billing privileges — per
        docs/permissions-matrix.md — so Payment Plans (a
        financial-visibility surface) must exclude them. The
        moderator here has an active creator-role SpaceMembership on
        Creator A's Collective; they must still see zero plans."""
        opt_a, sched_a = _make_option_and_schedule(db, scene.space_a, name="A plan")
        plan_a = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                            space=scene.space_a, option=opt_a, schedule=sched_a)
        mod = make_user(role="creator")
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            space_id=scene.space_a.id, user_id=mod.id,
            role="moderator", status="active",
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        out = list_creator_payment_plans(
            status=None, payment_option_id=None, member_search=None,
            current_user=mod, db=db,
        )
        assert plan_a.id not in {p.id for p in out}
        assert out == []

        # Attention-count endpoint must apply the same rule — no
        # leak of even the COUNT of another owner's payment problems.
        pp_plan = _make_plan(
            db, member=scene.member_a, creator=scene.creator_a,
            space=scene.space_a, option=opt_a, schedule=sched_a,
            status=PurchasePlanStatus.payment_problem, paid=1,
        )
        db.commit()
        assert pp_plan  # keep the linter happy — used by the query above
        count = get_creator_payment_plans_attention_count(current_user=mod, db=db)
        assert count.count == 0
        assert count.payment_problem_count == 0
        assert count.suspended_count == 0

    def test_O4_mixed_owner_and_moderator_returns_owned_only(
        self, db, scene, make_user,
    ):
        """A user who owns Collective A and moderates Collective B
        sees Payment Plans + attention counts for A only. This is
        the mixed-role case that would previously have leaked B's
        financial state via the set-union helper."""
        # Fresh user who will own their own space AND moderate scene.space_b.
        owner_and_mod = make_user(role="creator")
        own_space = scene.space_a  # already exists; make owner_and_mod own it
        own_space.creator_id = owner_and_mod.id

        # Moderator membership on scene.space_b (owned by scene.creator_b).
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            space_id=scene.space_b.id, user_id=owner_and_mod.id,
            role="moderator", status="active",
            joined_at=datetime.utcnow(),
        ))
        db.commit()

        opt_a, sched_a = _make_option_and_schedule(db, own_space, name="A plan")
        opt_b, sched_b = _make_option_and_schedule(db, scene.space_b, name="B plan")
        owned_plan = _make_plan(
            db, member=scene.member_a, creator=owner_and_mod,
            space=own_space, option=opt_a, schedule=sched_a,
            status=PurchasePlanStatus.payment_problem, paid=1,
        )
        moderated_plan = _make_plan(
            db, member=scene.member_b, creator=scene.creator_b,
            space=scene.space_b, option=opt_b, schedule=sched_b,
            status=PurchasePlanStatus.suspended, paid=1,
        )
        db.commit()

        # Plan list — only the owned plan.
        out = list_creator_payment_plans(
            status=None, payment_option_id=None, member_search=None,
            current_user=owner_and_mod, db=db,
        )
        ids = {p.id for p in out}
        assert owned_plan.id in ids
        assert moderated_plan.id not in ids

        # Attention count — reflects the owned plan only. The
        # sidebar badge is driven by exactly this endpoint, so a
        # leak here would show B's payment problem in the nav.
        count = get_creator_payment_plans_attention_count(
            current_user=owner_and_mod, db=db,
        )
        assert count.count == 1
        assert count.payment_problem_count == 1
        assert count.suspended_count == 0


# ---------------------------------------------------------------------------
# D-series — status-specific summary shape
# ---------------------------------------------------------------------------


class TestStatusSummaries:
    def _one(self, db, scene, *, status, paid, extra):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        plan = _make_plan(
            db, member=scene.member_a, creator=scene.creator_a,
            space=scene.space_a, option=opt, schedule=sched,
            status=status, paid=paid,
        )
        for k, v in extra.items():
            setattr(plan, k, v)
        db.commit()
        return plan, opt

    def test_D1_active(self, db, scene):
        plan, opt = self._one(db, scene, status=PurchasePlanStatus.active, paid=1, extra={})
        out = list_creator_payment_plans(
            status=["active"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert len(out) == 1
        s = out[0]
        assert s.status == "active"
        assert s.installments_paid == 1
        assert s.installments_expected == 3
        assert s.member_email == scene.member_a.email
        assert s.payment_option_name == opt.name

    def test_D2_payment_problem_carries_grace_deadline(self, db, scene):
        deadline = datetime.utcnow() + timedelta(days=6)
        _, opt = self._one(
            db, scene, status=PurchasePlanStatus.payment_problem, paid=1,
            extra={
                "payment_problem_started_at": datetime.utcnow() - timedelta(days=1),
                "grace_expires_at": deadline,
                "last_failed_invoice_id": "in_test",
            },
        )
        out = list_creator_payment_plans(
            status=["payment_problem"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert len(out) == 1
        assert out[0].status == "payment_problem"
        assert out[0].grace_expires_at is not None
        # `last_failed_invoice_id` MUST NOT appear on the wire — enforced
        # by schema; check the field simply isn't present.
        assert not hasattr(out[0], "last_failed_invoice_id")

    def test_D3_suspended_carries_suspended_at(self, db, scene):
        _, _ = self._one(
            db, scene, status=PurchasePlanStatus.suspended, paid=1,
            extra={
                "suspended_at": datetime.utcnow() - timedelta(hours=2),
                "payment_problem_started_at": datetime.utcnow() - timedelta(days=8),
                "grace_expires_at": datetime.utcnow() - timedelta(days=1),
            },
        )
        out = list_creator_payment_plans(
            status=["suspended"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert len(out) == 1
        assert out[0].status == "suspended"
        assert out[0].suspended_at is not None

    def test_D4_completed_carries_completed_at(self, db, scene):
        _, _ = self._one(
            db, scene, status=PurchasePlanStatus.completed, paid=3,
            extra={"completed_at": datetime.utcnow()},
        )
        out = list_creator_payment_plans(
            status=["completed"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert len(out) == 1
        assert out[0].status == "completed"
        assert out[0].installments_paid == 3
        assert out[0].completed_at is not None


# ---------------------------------------------------------------------------
# F-series — filters
# ---------------------------------------------------------------------------


class TestFilters:
    def test_F1_default_hides_failed_cancelled_pending(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        active = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                            space=scene.space_a, option=opt, schedule=sched,
                            status=PurchasePlanStatus.active, paid=1)
        failed = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                            space=scene.space_a, option=opt, schedule=sched,
                            status=PurchasePlanStatus.failed, paid=0)
        cancelled = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                               space=scene.space_a, option=opt, schedule=sched,
                               status=PurchasePlanStatus.cancelled, paid=0)
        pending = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                             space=scene.space_a, option=opt, schedule=sched,
                             status=PurchasePlanStatus.pending_setup, paid=0)
        db.commit()

        out = list_creator_payment_plans(
            status=None, payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        ids = {p.id for p in out}
        assert active.id in ids
        assert failed.id not in ids
        assert cancelled.id not in ids
        assert pending.id not in ids

    def test_F2_explicit_filter_surfaces_failed(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        failed = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                            space=scene.space_a, option=opt, schedule=sched,
                            status=PurchasePlanStatus.failed, paid=0)
        db.commit()
        out = list_creator_payment_plans(
            status=["failed"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        assert failed.id in {p.id for p in out}

    def test_F3_payment_option_filter_narrows(self, db, scene):
        opt1, sched1 = _make_option_and_schedule(db, scene.space_a, name="Plan A")
        opt2, sched2 = _make_option_and_schedule(db, scene.space_a, name="Plan B")
        p1 = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                        space=scene.space_a, option=opt1, schedule=sched1)
        p2 = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                        space=scene.space_a, option=opt2, schedule=sched2)
        db.commit()
        out = list_creator_payment_plans(
            status=None, payment_option_id=opt1.id, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        ids = {p.id for p in out}
        assert p1.id in ids
        assert p2.id not in ids

    def test_F4_member_search_case_insensitive(self, db, scene, make_user):
        # Create a member with a distinctive email.
        m = make_user(name="Robin Test", email="robin.mixedcase@example.test")
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        p = _make_plan(db, member=m, creator=scene.creator_a,
                       space=scene.space_a, option=opt, schedule=sched)
        # Also a plan for scene.member_a that should NOT match.
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched)
        db.commit()
        out = list_creator_payment_plans(
            status=None, payment_option_id=None, member_search="ROBIN",
            current_user=scene.creator_a, db=db,
        )
        ids = {r.id for r in out}
        assert p.id in ids
        assert len(ids) == 1


# ---------------------------------------------------------------------------
# M-series — money / progress calculations
# ---------------------------------------------------------------------------


class TestMoney:
    def test_M1_M2_M4_progress_and_totals(self, db, scene):
        # 4-instalment plan at $25, first 2 paid.
        opt, sched = _make_option_and_schedule(db, scene.space_a, inst_cents=2500, count=4)
        plan = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                          space=scene.space_a, option=opt, schedule=sched,
                          status=PurchasePlanStatus.active, paid=2)
        _make_succeeded_txn(db, plan, "in_1", 1)
        _make_succeeded_txn(db, plan, "in_2", 2)
        db.commit()
        out = list_creator_payment_plans(
            status=["active"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        s = out[0]
        assert s.installments_paid == 2
        assert s.installments_expected == 4
        assert s.total_amount_cents == 10000
        assert s.paid_amount_cents == 5000
        assert s.remaining_amount_cents == 5000

    def test_M3_failed_transactions_do_not_count_toward_paid(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a, inst_cents=2000, count=3)
        plan = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                          space=scene.space_a, option=opt, schedule=sched,
                          status=PurchasePlanStatus.payment_problem, paid=1)
        _make_succeeded_txn(db, plan, "in_1", 1)
        _make_failed_txn(db, plan, "in_2_failed")  # NOT counted
        db.commit()
        out = list_creator_payment_plans(
            status=["payment_problem"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        s = out[0]
        assert s.paid_amount_cents == 2000
        assert s.remaining_amount_cents == 4000

    def test_M4_remaining_never_negative(self, db, scene):
        """Belt-and-braces: an overpayment (should never happen but
        would if a bug landed) must not produce a negative remaining."""
        opt, sched = _make_option_and_schedule(db, scene.space_a, inst_cents=1000, count=2)
        plan = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                          space=scene.space_a, option=opt, schedule=sched,
                          status=PurchasePlanStatus.active, paid=2)
        _make_succeeded_txn(db, plan, "in_1", 1)
        _make_succeeded_txn(db, plan, "in_2", 2)
        # Simulated overpayment row.
        _make_succeeded_txn(db, plan, "in_bonus", 3)
        db.commit()
        out = list_creator_payment_plans(
            status=["active"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        s = out[0]
        assert s.remaining_amount_cents == 0

    def test_M5_customer_balance_audit_note_does_not_corrupt_totals(self, db, scene):
        """FIP4A rule: gross_amount_cents is CONTRACTUAL. A row
        satisfied via Stripe customer-balance credit carries an
        audit note but the gross field is still the full contractual
        instalment amount. Creator totals must therefore stay
        correct regardless of settlement path."""
        opt, sched = _make_option_and_schedule(db, scene.space_a, inst_cents=2000, count=3)
        plan = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                          space=scene.space_a, option=opt, schedule=sched,
                          status=PurchasePlanStatus.active, paid=2)
        _make_succeeded_txn(db, plan, "in_1", 1)
        balance_txn = _make_succeeded_txn(db, plan, "in_2_bal", 2)
        balance_txn.notes = (
            "Invoice satisfied partly via Stripe customer balance. "
            "invoice_total=2000c; provider_amount_paid=500c; "
            "starting_balance=-1500c; ending_balance=0c."
        )
        # gross_amount_cents stays 2000 (contractual)
        assert balance_txn.gross_amount_cents == 2000
        db.commit()
        out = list_creator_payment_plans(
            status=["active"], payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        s = out[0]
        assert s.paid_amount_cents == 4000
        assert s.remaining_amount_cents == 2000


# ---------------------------------------------------------------------------
# T-series — transaction row plan-context enrichment
# ---------------------------------------------------------------------------


class TestTransactionRowPlanContext:
    def test_T1_T3_payinfull_row_unchanged_and_null_plan_context(self, db, scene):
        opt, _ = _make_option_and_schedule(db, scene.space_a)
        pif_txn = _make_payinfull_txn(
            db, payer=scene.member_a, creator=scene.creator_a,
            space=scene.space_a, option=opt,
        )
        db.commit()

        rows = list_creator_payments(current_user=scene.creator_a, db=db)
        matching = [r for r in rows if r.id == pif_txn.id]
        assert len(matching) == 1
        r = matching[0]
        assert r.purchase_plan_id is None
        assert r.installment_number is None
        # Regression: existing fields still present + correct.
        assert r.gross_amount_cents == 5000
        assert r.status == "succeeded"

    def test_T2_finite_plan_row_carries_plan_context(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a, inst_cents=2000, count=3)
        plan = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                          space=scene.space_a, option=opt, schedule=sched,
                          status=PurchasePlanStatus.active, paid=2)
        _make_succeeded_txn(db, plan, "in_1", 1)
        _make_succeeded_txn(db, plan, "in_2", 2)
        db.commit()

        rows = list_creator_payments(current_user=scene.creator_a, db=db)
        plan_rows = [r for r in rows if r.purchase_plan_id == plan.id]
        assert len(plan_rows) == 2
        inst_numbers = sorted(r.installment_number for r in plan_rows)
        assert inst_numbers == [1, 2]


# ---------------------------------------------------------------------------
# L-series — leak protection (spec §3 / §11)
# ---------------------------------------------------------------------------


class TestLeakProtection:
    _PROVIDER_ID_FIELDS_FORBIDDEN_ON_PLAN_SUMMARY = {
        "provider_customer_id",
        "provider_subscription_id",
        "provider_subscription_schedule_id",
        "provider_payment_method_id",
        "provider_setup_session_id",
        "last_failed_invoice_id",
        "stripe_product_id",
        "stripe_price_id",
        "stripe_mode",
        "snapshot_grants_json",
    }

    _PROVIDER_ID_FIELDS_FORBIDDEN_ON_TX_ROW = {
        # Instalment context is fine (purchase_plan_id, installment_number).
        # But the underlying Stripe ids of the plan must never surface.
        "provider_subscription_id",
        "provider_invoice_id",
        "provider_charge_id",
        "provider_payment_intent_id",
        "provider_customer_id",
    }

    def test_L1_plan_summary_exposes_no_provider_ids(self):
        fields = set(CreatorPurchasePlanSummary.model_fields.keys())
        leaks = fields & self._PROVIDER_ID_FIELDS_FORBIDDEN_ON_PLAN_SUMMARY
        assert leaks == set(), f"plan summary leaks provider ids: {leaks}"

    def test_L2_creator_transaction_row_exposes_no_provider_ids(self):
        fields = set(CreatorPaymentTransactionOut.model_fields.keys())
        leaks = fields & self._PROVIDER_ID_FIELDS_FORBIDDEN_ON_TX_ROW
        assert leaks == set(), f"creator tx row leaks provider ids: {leaks}"


# ---------------------------------------------------------------------------
# A-series — attention-count endpoint + sidebar signal
# ---------------------------------------------------------------------------


class TestAttentionCount:
    def test_A1_only_payment_problem_and_suspended_count(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.active, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.payment_problem, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.suspended, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.completed, paid=3)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.failed, paid=0)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.cancelled, paid=0)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.pending_setup, paid=0)
        db.commit()

        out = get_creator_payment_plans_attention_count(
            current_user=scene.creator_a, db=db,
        )
        assert isinstance(out, CreatorPaymentPlansAttentionCount)
        assert out.payment_problem_count == 1
        assert out.suspended_count == 1
        assert out.count == 2

    def test_A2_zero_when_no_attention_states(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.active, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.completed, paid=3)
        db.commit()

        out = get_creator_payment_plans_attention_count(
            current_user=scene.creator_a, db=db,
        )
        assert out.count == 0
        assert out.payment_problem_count == 0
        assert out.suspended_count == 0

    def test_A3_creator_scope_respected(self, db, scene):
        """A payment_problem plan in another creator's Collective
        must NOT contribute to the caller's attention count."""
        opt_b, sched_b = _make_option_and_schedule(db, scene.space_b, name="B plan")
        _make_plan(db, member=scene.member_b, creator=scene.creator_b,
                   space=scene.space_b, option=opt_b, schedule=sched_b,
                   status=PurchasePlanStatus.payment_problem, paid=1)
        _make_plan(db, member=scene.member_b, creator=scene.creator_b,
                   space=scene.space_b, option=opt_b, schedule=sched_b,
                   status=PurchasePlanStatus.suspended, paid=1)
        db.commit()

        out = get_creator_payment_plans_attention_count(
            current_user=scene.creator_a, db=db,
        )
        assert out.count == 0

    def test_A4_zero_when_creator_manages_no_spaces(self, db, make_user):
        """A creator with no owned/moderated Spaces gets 0, not 500."""
        c = make_user(role="creator")
        db.commit()
        out = get_creator_payment_plans_attention_count(current_user=c, db=db)
        assert out.count == 0
        assert out.payment_problem_count == 0
        assert out.suspended_count == 0


# ---------------------------------------------------------------------------
# C-series — attention convenience filter + purchasability copy truthfulness
# ---------------------------------------------------------------------------


class TestAttentionFilter:
    def test_C1_explicit_attention_status_filter_returns_only_those(self, db, scene):
        opt, sched = _make_option_and_schedule(db, scene.space_a)
        pp = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                        space=scene.space_a, option=opt, schedule=sched,
                        status=PurchasePlanStatus.payment_problem, paid=1)
        sp = _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                        space=scene.space_a, option=opt, schedule=sched,
                        status=PurchasePlanStatus.suspended, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.active, paid=1)
        _make_plan(db, member=scene.member_a, creator=scene.creator_a,
                   space=scene.space_a, option=opt, schedule=sched,
                   status=PurchasePlanStatus.completed, paid=3)
        db.commit()
        out = list_creator_payment_plans(
            status=["payment_problem", "suspended"],
            payment_option_id=None, member_search=None,
            current_user=scene.creator_a, db=db,
        )
        ids = {p.id for p in out}
        assert ids == {pp.id, sp.id}


class TestPurchasabilityCopyTruthfulness:
    """FIP4C — the "checkout coming later" copy previously fired on
    every recurring_installments schedule regardless of feature-gate
    state. The refined helper must consult the platform gate and:
      * flag ON  + recurring_installments published → ``ready``
      * flag OFF + recurring_installments published →
        ``configured_not_yet_checkoutable`` with a truthful note that
        does NOT say "coming later".
    """

    def _make_finite_option_with_pathway_grant(self, db, space):
        """A finite-plan-only Payment Option that grants a Pathway —
        the grant-bundle shape ``_option_supports_finite_member_checkout``
        accepts."""
        from app.models.platform import Pathway
        from app.models.payment_option_grant import (
            GRANT_KIND_PATHWAY, PaymentOptionGrant,
        )
        pw = Pathway(
            id=_uid("path"), space_id=space.id,
            slug=f"p-{uuid.uuid4().hex[:8]}", title="Test pathway",
            status="active",
        )
        db.add(pw); db.flush()
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="space", attaches_to_id=space.id,
            name="Finite only",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=6000, currency="AUD",
        )
        db.add(opt); db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("g"), payment_option_id=opt.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id, position=0,
        ))
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Weekly × 3",
            schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=3,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=6000, currency="AUD",
        )
        db.add(sched); db.flush()
        return opt, sched

    def test_C2_gate_off_configured_not_yet_checkoutable_with_truthful_note(
        self, db, scene, monkeypatch,
    ):
        from app.core.config import settings
        from app.creator._space_payment_options_routes import _derive_purchasability
        monkeypatch.setattr(settings, "finite_plan_member_checkout_enabled", False)
        opt, _ = self._make_finite_option_with_pathway_grant(db, scene.space_a)
        opt._schedules_cache = list(
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.payment_option_id == opt.id).all()
        )
        state, notes = _derive_purchasability(opt)
        assert state == "configured_not_yet_checkoutable"
        joined = " ".join(notes).lower()
        # Truthful about WHY it isn't live and doesn't imply
        # unfinished platform work.
        assert "coming later" not in joined
        assert (
            "not currently enabled" in joined
            or "platform" in joined
        )

    def test_C3_gate_on_finite_plan_option_reports_ready(
        self, db, scene, monkeypatch,
    ):
        from app.core.config import settings
        from app.creator._space_payment_options_routes import _derive_purchasability
        monkeypatch.setattr(settings, "finite_plan_member_checkout_enabled", True)
        opt, _ = self._make_finite_option_with_pathway_grant(db, scene.space_a)
        opt._schedules_cache = list(
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.payment_option_id == opt.id).all()
        )
        state, notes = _derive_purchasability(opt)
        assert state == "ready"
        assert notes == []

    def test_C4_schedule_response_carries_is_member_checkoutable(
        self, db, scene, monkeypatch,
    ):
        """The creator's Payment Options list response must include
        ``is_member_checkoutable`` per schedule so the editor can
        render the correct pending/live note."""
        from app.core.config import settings
        from app.creator.routes import _schedule_to_dict
        monkeypatch.setattr(settings, "finite_plan_member_checkout_enabled", False)
        opt, sched = self._make_finite_option_with_pathway_grant(db, scene.space_a)
        d = _schedule_to_dict(sched, opt)
        assert "is_member_checkoutable" in d
        assert d["is_member_checkoutable"] is False
        # Flipping the flag must flip the field.
        monkeypatch.setattr(settings, "finite_plan_member_checkout_enabled", True)
        d2 = _schedule_to_dict(sched, opt)
        assert d2["is_member_checkoutable"] is True
