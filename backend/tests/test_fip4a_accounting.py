"""FIP4A — accounting rules for finite-plan invoice fulfilment.

Locks the FIP4A-approved contractual-vs-cash distinction:

  * fulfilment gate uses ``invoice.status='paid' AND invoice.total ==
    plan.installment_amount_cents AND invoice.currency==plan.currency``
    — NOT ``amount_paid``. A balance-satisfied invoice is a
    legitimate paid instalment.
  * ``PaymentTransaction.gross_amount_cents = invoice.total`` — the
    contractual invoice amount. Fee snapshot + net_creator flow off
    this. Matches revenue-recognition accounting.
  * ``PaymentTransaction.notes`` carries a precise audit note when
    ``amount_paid < total`` (balance-satisfied case) with
    invoice_total / provider_amount_paid / starting_balance /
    ending_balance in cents. Normal card-funded rows carry no note.
  * ``Invoice.pay`` race recovery is state-based: on
    ``InvalidRequestError``, refetch invoice; if now paid + same
    subscription + same billing_reason, treat as success. Do not
    match on error message text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe

from app.models.access_pass import AccessPassType
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import finite_plan_lifecycle as fpl
from app.services import stripe_finite_plan
from app.services.purchase_fulfilment import (
    AccessPassIntent, FulfilmentIntent, serialise_intent,
)
from app.webhooks.finite_plan_handlers import (
    _compose_balance_settlement_note,
    _do_invoice_succeeded,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures — one primed pending_setup plan (first invoice) and one
# already-active plan (later instalments).
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_plan(db, make_user, make_space):
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
        name="PO", payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly x 3", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add_all([opt, sched]); db.flush()
    intent = FulfilmentIntent(access_passes=(AccessPassIntent(
        pass_type=AccessPassType.term_pass,
        valid_from=datetime.utcnow(), valid_until=None,
        total_credits=None, credits_per_week=None,
        eligible_pathway_id=None, eligible_series_id=series.id,
        grants_pathway_id=None,
    ),))
    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id, creator_user_id=creator.id,
        status=PurchasePlanStatus.pending_setup,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3, installments_paid=0,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_subscription_id=subscription_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
    )
    db.add(plan); db.commit()
    return SimpleNamespace(
        member=member, creator=creator, space=space, series=series,
        option=opt, schedule=sched, plan=plan, subscription_id=subscription_id,
    )


def _invoice(*, invoice_id, subscription_id, total, amount_paid=None,
             starting_balance=0, ending_balance=0, status="paid",
             currency="aud", charge="ch_x", pi="pi_x"):
    """Build an invoice payload as it would arrive in a Stripe webhook."""
    return {
        "id": invoice_id,
        "subscription": subscription_id,
        "status": status,
        "total": total,
        "amount_paid": amount_paid if amount_paid is not None else total,
        "currency": currency,
        "charge": charge,
        "payment_intent": pi,
        "billing_reason": "subscription_create",
        "starting_balance": starting_balance,
        "ending_balance": ending_balance,
    }


# ===========================================================================
# _compose_balance_settlement_note — precise audit signal
# ===========================================================================


class TestBalanceSettlementNote:
    def test_normal_card_funded_returns_none(self):
        inv = _invoice(invoice_id="in_x", subscription_id="sub_x", total=2000, amount_paid=2000)
        assert _compose_balance_settlement_note(inv, invoice_total=2000, provider_amount_paid=2000) is None

    def test_fully_balance_satisfied_returns_precise_note(self):
        inv = _invoice(
            invoice_id="in_x", subscription_id="sub_x",
            total=2000, amount_paid=0,
            starting_balance=-2000, ending_balance=0,
        )
        note = _compose_balance_settlement_note(inv, invoice_total=2000, provider_amount_paid=0)
        assert note is not None
        assert "customer balance" in note
        assert "invoice_total=2000c" in note
        assert "provider_amount_paid=0c" in note
        assert "starting_balance=-2000c" in note
        assert "ending_balance=0c" in note

    def test_partial_balance_satisfied_returns_note(self):
        inv = _invoice(
            invoice_id="in_x", subscription_id="sub_x",
            total=2000, amount_paid=1500,
            starting_balance=-500, ending_balance=0,
        )
        note = _compose_balance_settlement_note(inv, invoice_total=2000, provider_amount_paid=1500)
        assert "provider_amount_paid=1500c" in note


# ===========================================================================
# _do_invoice_succeeded — fulfilment + accounting behaviour
# ===========================================================================


class TestFulfilmentBalanceSatisfiedAccepted:
    def test_balance_satisfied_invoice_activates_plan(self, db, pending_plan):
        """total=2000, amount_paid=0, satisfied via customer balance
        → plan activates, one PaymentTransaction with gross=2000
        and a precise audit note."""
        s = pending_plan
        inv = _invoice(
            invoice_id="in_balance_only",
            subscription_id=s.subscription_id,
            total=2000, amount_paid=0,
            starting_balance=-2000, ending_balance=0,
        )
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 1

        txns = db.query(PaymentTransaction).filter(
            PaymentTransaction.purchase_plan_id == s.plan.id,
        ).all()
        assert len(txns) == 1
        txn = txns[0]
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.gross_amount_cents == 2000, "contractual amount not cash"
        # Fee still calculated off contractual amount.
        assert txn.platform_fee_basis_points == 800
        assert txn.platform_fee_cents == 160
        assert txn.net_creator_amount_cents == 1840
        # Audit note precise enough for future FIP4C reconciliation.
        assert txn.notes is not None
        assert "invoice_total=2000c" in txn.notes
        assert "provider_amount_paid=0c" in txn.notes
        assert "starting_balance=-2000c" in txn.notes


class TestFulfilmentNormalCardFunded:
    def test_normal_card_funded_invoice_unchanged(self, db, pending_plan):
        s = pending_plan
        inv = _invoice(
            invoice_id="in_card",
            subscription_id=s.subscription_id,
            total=2000, amount_paid=2000,
            starting_balance=0, ending_balance=0,
        )
        _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.purchase_plan_id == s.plan.id,
        ).one()
        assert txn.gross_amount_cents == 2000
        # No audit note on normal card-funded rows.
        assert txn.notes is None


class TestFulfilmentTotalMismatchRejected:
    def test_wrong_total_rejects(self, db, pending_plan):
        s = pending_plan
        inv = _invoice(
            invoice_id="in_wrong_total",
            subscription_id=s.subscription_id,
            total=1500, amount_paid=1500,
        )
        with pytest.raises(RuntimeError) as exc:
            _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        assert "1500" in str(exc.value)
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.purchase_plan_id == s.plan.id,
        ).count() == 0


class TestFulfilmentCurrencyMismatchRejected:
    def test_wrong_currency_rejects(self, db, pending_plan):
        s = pending_plan
        inv = _invoice(
            invoice_id="in_wrong_ccy",
            subscription_id=s.subscription_id,
            total=2000, amount_paid=2000,
            currency="usd",
        )
        with pytest.raises(RuntimeError) as exc:
            _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
        assert "USD" in str(exc.value)


# ===========================================================================
# Payments received aggregation — accrual gross remains contractual
# ===========================================================================


class TestPaymentsReceivedAggregationAccrual:
    def test_sum_of_gross_matches_contractual_regardless_of_payment_source(
        self, db, pending_plan,
    ):
        """A mix of card-funded and balance-satisfied paid invoices
        aggregates in Payments Received as sum(gross) = contractual.
        Cash actually collected via card is smaller but not what
        this dashboard shows (that's FIP4C to refine)."""
        s = pending_plan
        # First invoice — card funded.
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id="in_a", subscription_id=s.subscription_id,
                total=2000, amount_paid=2000,
            ),
            event_livemode=False,
        )
        # Second invoice — balance satisfied.
        _do_invoice_succeeded(
            db,
            invoice=_invoice(
                invoice_id="in_b", subscription_id=s.subscription_id,
                total=2000, amount_paid=0,
                starting_balance=-2000, ending_balance=0,
            ),
            event_livemode=False,
        )
        rows = db.query(PaymentTransaction).filter(
            PaymentTransaction.purchase_plan_id == s.plan.id,
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
        ).all()
        assert len(rows) == 2
        # Contractual gross totals.
        assert sum(r.gross_amount_cents for r in rows) == 4000
        # Fee still applied per row on contractual gross.
        assert sum(r.platform_fee_cents for r in rows) == 320  # 2*160
        assert sum(r.net_creator_amount_cents for r in rows) == 3680  # 2*1840


# ===========================================================================
# Fix A — state-based race recovery in finalize_and_pay_first_invoice
# ===========================================================================


class TestFinalizeAndPayRaceRecovery:
    def _plan_shell(self):
        # A duck-typed minimal PurchasePlan with only the fields
        # ``finalize_and_pay_first_invoice`` reads.
        return SimpleNamespace(
            id="pplan_race",
            installment_amount_cents=2000,
            installments_expected=3,
            currency="AUD",
            stripe_mode="test",
        )

    def test_race_refetch_paid_treated_as_success(self):
        plan = self._plan_shell()
        sub = {"id": "sub_x", "latest_invoice": "in_x"}
        # First retrieve: draft state (about to try pay).
        draft_inv = {"id": "in_x", "status": "draft",
                     "billing_reason": "subscription_create",
                     "subscription": "sub_x"}
        # After InvalidRequestError, refetch: Stripe paid it in the race.
        paid_inv = {"id": "in_x", "status": "paid",
                    "billing_reason": "subscription_create",
                    "subscription": "sub_x"}
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"), \
             patch("stripe.Subscription.retrieve", return_value=sub), \
             patch("stripe.Invoice.retrieve", side_effect=[draft_inv, paid_inv]), \
             patch("stripe.Invoice.finalize_invoice", return_value=None), \
             patch("stripe.Invoice.pay",
                   side_effect=stripe.InvalidRequestError("Invoice is already paid",
                                                          param=None)):
            invoice_id, status = stripe_finite_plan.finalize_and_pay_first_invoice(
                plan=plan, subscription_id="sub_x",
            )
        assert invoice_id == "in_x"
        assert status == "paid"

    def test_race_refetch_not_paid_propagates(self):
        plan = self._plan_shell()
        sub = {"id": "sub_x", "latest_invoice": "in_x"}
        draft_inv = {"id": "in_x", "status": "draft",
                     "billing_reason": "subscription_create",
                     "subscription": "sub_x"}
        # Refetch still shows non-paid — a genuine error.
        still_open = {"id": "in_x", "status": "open",
                      "billing_reason": "subscription_create",
                      "subscription": "sub_x"}
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"), \
             patch("stripe.Subscription.retrieve", return_value=sub), \
             patch("stripe.Invoice.retrieve", side_effect=[draft_inv, still_open]), \
             patch("stripe.Invoice.finalize_invoice", return_value=None), \
             patch("stripe.Invoice.pay",
                   side_effect=stripe.InvalidRequestError("boom", param=None)):
            with pytest.raises(stripe.InvalidRequestError):
                stripe_finite_plan.finalize_and_pay_first_invoice(
                    plan=plan, subscription_id="sub_x",
                )

    def test_race_refetch_different_subscription_propagates(self):
        """Safety guard — refetch returned a different subscription
        id, this is not our invoice; do not silently treat as
        success. Propagate the original error."""
        plan = self._plan_shell()
        sub = {"id": "sub_x", "latest_invoice": "in_x"}
        draft_inv = {"id": "in_x", "status": "draft",
                     "billing_reason": "subscription_create",
                     "subscription": "sub_x"}
        weird = {"id": "in_x", "status": "paid",
                 "billing_reason": "subscription_create",
                 "subscription": "sub_someone_else"}
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"), \
             patch("stripe.Subscription.retrieve", return_value=sub), \
             patch("stripe.Invoice.retrieve", side_effect=[draft_inv, weird]), \
             patch("stripe.Invoice.finalize_invoice", return_value=None), \
             patch("stripe.Invoice.pay",
                   side_effect=stripe.InvalidRequestError("Invoice is already paid",
                                                          param=None)):
            with pytest.raises(stripe.InvalidRequestError):
                stripe_finite_plan.finalize_and_pay_first_invoice(
                    plan=plan, subscription_id="sub_x",
                )

    def test_race_refetch_different_billing_reason_propagates(self):
        plan = self._plan_shell()
        sub = {"id": "sub_x", "latest_invoice": "in_x"}
        draft_inv = {"id": "in_x", "status": "draft",
                     "billing_reason": "subscription_create",
                     "subscription": "sub_x"}
        weird = {"id": "in_x", "status": "paid",
                 "billing_reason": "manual",
                 "subscription": "sub_x"}
        with patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"), \
             patch("stripe.Subscription.retrieve", return_value=sub), \
             patch("stripe.Invoice.retrieve", side_effect=[draft_inv, weird]), \
             patch("stripe.Invoice.finalize_invoice", return_value=None), \
             patch("stripe.Invoice.pay",
                   side_effect=stripe.InvalidRequestError("Invoice is already paid",
                                                          param=None)):
            with pytest.raises(stripe.InvalidRequestError):
                stripe_finite_plan.finalize_and_pay_first_invoice(
                    plan=plan, subscription_id="sub_x",
                )
