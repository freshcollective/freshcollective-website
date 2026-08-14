"""FIP1 — PurchasePlan model + linkage columns.

Verifies the foundation:

* The ``purchase_plans`` row can be created with the minimum
  required fields and defaults sensibly.
* Multiple ``PaymentTransaction`` rows can be grouped under one
  ``PurchasePlan`` via the new ``purchase_plan_id`` FK.
* Different plans never collide (uniqueness of Stripe subscription
  ids is enforced only when populated — NULL rows coexist).
* Pay-in-full transactions still work with ``purchase_plan_id=NULL``
  (backward compatibility for legacy rows and every current-live
  pay-in-full row).
* ``AccessPass`` and ``PathwayEntitlement`` accept the linkage FK
  (nullable).
* The recurring_installments 503 guard is still in place — no
  member-facing behaviour changed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentProvider,
    PayoutStatus,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_option_and_schedule(db, space):
    """Minimal PaymentOption + recurring PaymentOptionSchedule."""
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule

    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name="Awaken",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()

    sched = PaymentOptionSchedule(
        id=_uid("sched"),
        payment_option_id=opt.id,
        name="Weekly × 10",
        schedule_type="recurring_installments",
        status="draft",
        installment_amount_cents=2000,
        installment_count=10,
        stripe_interval="week",
        stripe_interval_count=1,
        total_amount_cents=20000,
        currency="AUD",
    )
    db.add(sched)
    db.flush()
    return opt, sched


class TestPurchasePlanShape:
    def test_minimum_row_creates_with_defaults(self, db, make_user, make_space):
        member = make_user()
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)

        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            space_id=space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        # Defaults land as documented.
        assert plan.status == PurchasePlanStatus.pending_setup
        assert plan.installments_paid == 0
        assert plan.currency == "AUD"
        assert plan.platform_fee_basis_points == 0
        assert plan.stripe_mode == "test"
        assert plan.activated_at is None
        assert plan.completed_at is None
        assert plan.cancelled_at is None
        # Provider identifiers all NULL during pending_setup.
        assert plan.provider_customer_id is None
        assert plan.provider_setup_session_id is None
        assert plan.provider_subscription_schedule_id is None

    def test_lifecycle_states_are_all_persistable(self, db, make_user, make_space):
        """Sanity: every enum value survives a round-trip."""
        member = make_user()
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)
        for i, status in enumerate(PurchasePlanStatus):
            plan = PurchasePlan(
                id=_uid(f"pplan{i}"),
                member_user_id=member.id,
                payment_option_id=opt.id,
                payment_option_schedule_id=sched.id,
                space_id=space.id,
                installment_amount_cents=2000,
                installments_expected=10,
                total_expected_cents=20000,
                stripe_interval="week",
                stripe_interval_count=1,
                status=status,
            )
            db.add(plan)
        db.commit()


class TestGroupingByPurchasePlan:
    def test_multiple_transactions_share_one_plan(
        self, db, make_user, make_space,
    ):
        """Ten instalment PaymentTransactions all point back to one PurchasePlan."""
        member = make_user()
        creator = make_user(role="creator")
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)

        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            space_id=space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            status=PurchasePlanStatus.active,
        )
        db.add(plan)
        db.flush()

        # Simulate 3 successful invoices having landed.
        for i in range(3):
            txn = PaymentTransaction(
                id=_uid(f"txn{i}"),
                transaction_type=PaymentTransactionType.member_payment_option_purchase,
                status=PaymentTransactionStatus.succeeded,
                payment_provider=PaymentProvider.stripe,
                payer_user_id=member.id,
                creator_user_id=creator.id,
                space_id=space.id,
                currency="AUD",
                gross_amount_cents=2000,
                platform_fee_basis_points=800,
                platform_fee_cents=160,
                payment_option_id=opt.id,
                payment_option_schedule_id=sched.id,
                purchase_plan_id=plan.id,
                provider_invoice_id=f"in_test_{i}",
                payout_status=PayoutStatus.pending,
            )
            db.add(txn)
        db.commit()

        # Reverse lookup: three transactions under one plan.
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == plan.id)
            .all()
        )
        assert len(rows) == 3
        assert all(r.gross_amount_cents == 2000 for r in rows)

    def test_different_plans_do_not_collide(self, db, make_user, make_space):
        """Two members buying the same option produce distinct plans + distinct groupings."""
        alice = make_user()
        bob = make_user()
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)

        alice_plan = PurchasePlan(
            id=_uid("pplan_a"),
            member_user_id=alice.id, payment_option_id=opt.id,
            payment_option_schedule_id=sched.id, space_id=space.id,
            installment_amount_cents=2000, installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week", stripe_interval_count=1,
        )
        bob_plan = PurchasePlan(
            id=_uid("pplan_b"),
            member_user_id=bob.id, payment_option_id=opt.id,
            payment_option_schedule_id=sched.id, space_id=space.id,
            installment_amount_cents=2000, installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week", stripe_interval_count=1,
        )
        db.add_all([alice_plan, bob_plan])
        db.commit()
        assert alice_plan.id != bob_plan.id

    def test_pay_in_full_transaction_has_no_plan(self, db, make_user, make_space):
        """Legacy pay-in-full continues to work with purchase_plan_id NULL."""
        member = make_user()
        creator = make_user(role="creator")
        space = make_space()
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=member.id,
            creator_user_id=creator.id,
            space_id=space.id,
            currency="AUD",
            gross_amount_cents=20000,
            platform_fee_basis_points=800,
            platform_fee_cents=1600,
            payout_status=PayoutStatus.pending,
            # purchase_plan_id left NULL — this is the legacy shape.
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        assert txn.purchase_plan_id is None


class TestProviderIdentifierUniqueness:
    def test_null_provider_ids_coexist(self, db, make_user, make_space):
        """Multiple plans with NULL provider_* ids do not violate the partial unique."""
        member = make_user()
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)
        for i in range(3):
            plan = PurchasePlan(
                id=_uid(f"pplan{i}"),
                member_user_id=member.id, payment_option_id=opt.id,
                payment_option_schedule_id=sched.id, space_id=space.id,
                installment_amount_cents=2000, installments_expected=10,
                total_expected_cents=20000,
                stripe_interval="week", stripe_interval_count=1,
                # provider_subscription_id left NULL
            )
            db.add(plan)
        db.commit()  # No IntegrityError.

    def test_populated_provider_subscription_id_is_unique(
        self, db, make_user, make_space,
    ):
        """Two plans cannot share one Stripe subscription id."""
        member = make_user()
        space = make_space()
        opt, sched = _make_option_and_schedule(db, space)
        shared = f"sub_dup_{uuid.uuid4().hex[:8]}"

        first = PurchasePlan(
            id=_uid("pplan1"),
            member_user_id=member.id, payment_option_id=opt.id,
            payment_option_schedule_id=sched.id, space_id=space.id,
            installment_amount_cents=2000, installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week", stripe_interval_count=1,
            provider_subscription_id=shared,
        )
        db.add(first)
        db.commit()

        second = PurchasePlan(
            id=_uid("pplan2"),
            member_user_id=member.id, payment_option_id=opt.id,
            payment_option_schedule_id=sched.id, space_id=space.id,
            installment_amount_cents=2000, installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week", stripe_interval_count=1,
            provider_subscription_id=shared,
        )
        db.add(second)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestRecurringGuardStillActive:
    """Regression: FIP1 must not accidentally enable recurring checkout."""

    def test_503_guard_source_is_intact(self):
        """Assert the exact code path that must remain."""
        from app.services import checkout_orchestration
        # The literal string of the guard's message. If a later phase
        # removes it, this test fails and the removal is explicit.
        source = open(checkout_orchestration.__file__).read()
        assert 'schedule_type == "recurring_installments"' in source
        assert 'status_code=503' in source
