"""FIP2 — invoice.payment_succeeded (first invoice) tests.

The handler:
  1. Locates the plan by ``invoice.subscription``.
  2. Rejects any livemode mismatch as ``skipped`` (safe).
  3. FIP2 scope: only processes when plan is ``pending_setup``.
     ``active`` plans (later invoices) skip cleanly — those are
     FIP3's job.
  4. Verifies expected currency + amount.
  5. Creates one PaymentTransaction with correct provider ids,
     ``installment_number=1``, fee snapshot applied.
  6. Applies the snapshotted grants intent atomically via the
     shared fulfilment service — every access row carries
     ``purchase_plan_id``.
  7. Transitions plan ``pending_setup → active`` +
     ``installments_paid = 1``.
  8. Replay-safe via ``provider_invoice_id`` natural key + FIP1
     webhook idempotency.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.purchase_fulfilment import (
    FulfilmentIntent,
    AccessPassIntent,
    serialise_intent,
)
from app.webhooks.finite_plan_handlers import (
    handle_invoice_payment_succeeded,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture — plan primed with Stripe ids + snapshotted intent
# ---------------------------------------------------------------------------


@pytest.fixture
def primed_plan(db, make_user, make_space):
    """A plan that has passed setup — provider_subscription_id +
    snapshot_grants_json both populated. Ready to receive its first
    invoice.payment_succeeded event."""
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule
    from app.models.platform import EventSeries

    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    starts = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=starts, status="published", published_at=starts,
    )
    db.add(series)
    db.flush()
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000, currency="AUD",
    )
    db.add(opt)
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly × 10", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=10,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=20000, currency="AUD",
    )
    db.add(sched)
    db.flush()

    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    # Snapshot intent: one term_pass AccessPass keyed on the Series.
    intent = FulfilmentIntent(
        access_passes=(
            AccessPassIntent(
                pass_type=AccessPassType.term_pass,
                valid_from=datetime.utcnow(),
                valid_until=None,
                total_credits=10,
                credits_per_week=1,
                eligible_pathway_id=None,
                eligible_series_id=series.id,
                grants_pathway_id=None,
            ),
        ),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        creator_user_id=creator.id,
        status=PurchasePlanStatus.pending_setup,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=10,
        installments_paid=0,
        total_expected_cents=20000,
        stripe_interval="week",
        stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_setup_session_id=f"cs_test_{uuid.uuid4().hex[:8]}",
        provider_customer_id=f"cus_test_{uuid.uuid4().hex[:8]}",
        provider_payment_method_id=f"pm_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_schedule_id=f"sub_sched_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=subscription_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
    )
    db.add(plan)
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, option=opt, schedule=sched,
        plan=plan, subscription_id=subscription_id, intent=intent,
    )


def _invoice(*, invoice_id, subscription_id, amount, currency="aud", status="paid"):
    return {
        "id": invoice_id,
        "subscription": subscription_id,
        "amount_paid": amount,
        "currency": currency,
        "status": status,
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestFirstInvoiceHappyPath:
    def test_creates_payment_transaction_and_activates_plan(
        self, db, primed_plan,
    ):
        s = primed_plan
        invoice = _invoice(
            invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id,
            amount=2000,
        )

        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )

        db.refresh(s.plan)
        # Plan activated.
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 1
        assert s.plan.activated_at is not None

        # One PaymentTransaction created, correctly shaped.
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == s.plan.id)
            .all()
        )
        assert len(rows) == 1
        txn = rows[0]
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.fulfilment_status == PaymentFulfilmentStatus.applied
        assert txn.gross_amount_cents == 2000
        assert txn.platform_fee_basis_points == 800  # snapshot
        assert txn.platform_fee_cents == 160
        assert txn.net_creator_amount_cents == 1840
        assert txn.currency == "AUD"
        assert txn.provider_invoice_id == invoice["id"]
        assert txn.provider_subscription_id == s.subscription_id
        assert txn.provider_charge_id == invoice["charge"]
        assert txn.provider_payment_intent_id == invoice["payment_intent"]
        assert txn.payment_option_id == s.option.id
        assert txn.payment_option_schedule_id == s.schedule.id
        assert txn.installment_number == 1
        assert txn.stripe_mode == "test"

        # AccessPass created + linked to plan.
        passes = (
            db.query(AccessPass)
            .filter(AccessPass.user_id == s.member.id)
            .all()
        )
        assert len(passes) == 1
        pass_ = passes[0]
        assert pass_.status == AccessPassStatus.active
        assert pass_.purchase_plan_id == s.plan.id
        assert pass_.eligible_series_id == s.series.id


# ---------------------------------------------------------------------------
# Replay safety
# ---------------------------------------------------------------------------


class TestFirstInvoiceReplay:
    def test_duplicate_invoice_event_creates_no_second_transaction(
        self, db, primed_plan,
    ):
        s = primed_plan
        invoice = _invoice(
            invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id,
            amount=2000,
        )
        event_id = f"evt_{uuid.uuid4().hex}"

        handle_invoice_payment_succeeded(
            invoice, db, provider_event_id=event_id, event_livemode=False,
        )
        # Second delivery — same event id → FIP1 helper skips.
        handle_invoice_payment_succeeded(
            invoice, db, provider_event_id=event_id, event_livemode=False,
        )

        count = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE purchase_plan_id = :p"
            ),
            {"p": s.plan.id},
        ).scalar_one()
        assert count == 1

    def test_different_event_same_invoice_still_deduped(
        self, db, primed_plan,
    ):
        """Even a *different* event id for the same invoice does not
        produce a second transaction — the ``provider_invoice_id``
        natural-key guard in the handler catches it."""
        s = primed_plan
        invoice = _invoice(
            invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id,
            amount=2000,
        )

        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active

        # New event id, same invoice — represents a bug that bypasses
        # the webhook_events helper. Handler-level guard must still
        # catch it.
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",  # DIFFERENT
            event_livemode=False,
        )

        count = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE provider_invoice_id = :i"
            ),
            {"i": invoice["id"]},
        ).scalar_one()
        assert count == 1


# ---------------------------------------------------------------------------
# Mode + status guards
# ---------------------------------------------------------------------------


class TestModeAndStatusGuards:
    def test_livemode_mismatch_is_skipped_safely(self, db, primed_plan):
        s = primed_plan
        assert s.plan.stripe_mode == "test"

        invoice = _invoice(
            invoice_id="in_livemode_should_never_touch_this",
            subscription_id=s.subscription_id,
            amount=2000,
        )
        # Live event landing on a test plan — must be a skip, not a
        # mutation.
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=True,  # <- MISMATCH
        )

        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup
        assert s.plan.installments_paid == 0
        # No PaymentTransaction created.
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE purchase_plan_id = :p"
            ),
            {"p": s.plan.id},
        ).scalar_one()
        assert count == 0

    def test_active_plan_receives_later_invoice_records_second_txn(
        self, db, primed_plan,
    ):
        """FIP3: later invoices on an already-active plan are
        processed by the same handler — instalment number
        increments, a second PaymentTransaction is recorded, and
        the snapshot grants are NOT re-applied (access already
        exists from first-invoice fulfilment)."""
        s = primed_plan
        s.plan.status = PurchasePlanStatus.active
        s.plan.installments_paid = 1
        s.plan.activated_at = datetime.utcnow()
        db.commit()

        invoice = _invoice(
            invoice_id=f"in_later_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id,
            amount=2000,
        )
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )

        db.refresh(s.plan)
        assert s.plan.installments_paid == 2
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM payment_transactions "
                "WHERE purchase_plan_id = :p"
            ),
            {"p": s.plan.id},
        ).scalar_one()
        assert count == 1  # one FIP3 later-instalment txn

    def test_no_matching_subscription_is_skipped(self, db, primed_plan):
        """An invoice for a subscription we don't own (test-mode
        noise) → skip, don't mutate."""
        invoice = _invoice(
            invoice_id="in_stranger",
            subscription_id="sub_not_ours",
            amount=2000,
        )
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )
        # No transactions created anywhere.
        count = db.execute(
            text("SELECT COUNT(*) FROM payment_transactions "
                 "WHERE provider_invoice_id = 'in_stranger'")
        ).scalar_one()
        assert count == 0

    def test_unpaid_invoice_is_skipped(self, db, primed_plan):
        s = primed_plan
        invoice = _invoice(
            invoice_id="in_unpaid",
            subscription_id=s.subscription_id,
            amount=2000,
            status="open",  # not paid
        )
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup


# ---------------------------------------------------------------------------
# Fulfilment integrity
# ---------------------------------------------------------------------------


class TestFulfilmentIntegrity:
    def test_snapshot_target_missing_marks_blocked(
        self, db, primed_plan,
    ):
        """Creator deletes the granted Series between plan-start and
        first-invoice — apply_intent can't run, txn is blocked, plan
        stays pending_setup so an operator can intervene."""
        s = primed_plan

        # Delete the Series the snapshot references. Cascade the
        # AccessPass ... wait, there's no AccessPass yet — we're
        # simulating pre-fulfilment mutation.
        db.execute(
            text("DELETE FROM event_series WHERE id = :i"),
            {"i": s.series.id},
        )
        db.commit()

        invoice = _invoice(
            invoice_id=f"in_blocked_{uuid.uuid4().hex[:8]}",
            subscription_id=s.subscription_id,
            amount=2000,
        )
        handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )

        db.refresh(s.plan)
        # Plan does NOT activate — access could not be applied.
        assert s.plan.status == PurchasePlanStatus.pending_setup
        # PaymentTransaction row exists and is blocked.
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == s.plan.id)
            .one()
        )
        assert txn.fulfilment_status == PaymentFulfilmentStatus.blocked
        assert txn.status == PaymentTransactionStatus.succeeded  # money still came
        # No AccessPass created.
        count = db.execute(
            text("SELECT COUNT(*) FROM access_passes "
                 "WHERE user_id = :u AND purchase_plan_id = :p"),
            {"u": s.member.id, "p": s.plan.id},
        ).scalar_one()
        assert count == 0
