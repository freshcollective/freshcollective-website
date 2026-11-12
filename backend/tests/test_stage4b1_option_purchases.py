"""Stage 4B.1 — a card that has already been bought stops selling itself.

The production symptom. Tom bought "Test Gathering Experience" on a
discounted two-instalment plan. Stage 4B taught the card to say "You've
purchased this" — correctly — and directly underneath it still offered
"Purchase Test Gathering Experience" and "Start payment plan". The
banner knew about the viewer; the schedule rows never had.

Two things are being protected here, and they pull against each other:

* A member who has bought an arrangement must not be sold it again.
* A member who is *allowed* to buy again must still be able to. Some
  repeat purchases are legitimate — a new term after a completed plan,
  a retry after a cancelled one — and inventing a UI restriction the
  backend does not have would break them silently.

So the suppression signal is the till's own verdict:
``checkout_orchestration.find_same_option_hold``, the predicate behind
the 409 a duplicate checkout already receives. A button disappears
exactly when it would have been refused. That is also why
``find_same_option_hold`` was extracted rather than reimplemented — a
second opinion about repurchase eligibility would eventually disagree
with the one that takes the money.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage4b1_option_purchases.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider, PaymentTransaction,
    PaymentTransactionStatus, PaymentTransactionType, PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.spaces import member_option_purchases as mop


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


NOW = datetime.utcnow()


@pytest.fixture
def world(db, make_user, make_space):
    member = make_user()
    other = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    option = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="pathway",
        attaches_to_id=_uid("pw"), name="Test Gathering Experience",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=1_000, currency="AUD",
    )
    db.add(option)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sch"), payment_option_id=option.id, name="2 payments",
        schedule_type="recurring_installments", status="published",
        total_amount_cents=1_000, installment_amount_cents=500,
        installment_count=2, stripe_interval="month", stripe_interval_count=1,
        currency="AUD",
    )
    db.add(sched)
    db.flush()
    return dict(member=member, other=other, creator=creator,
                space=space, option=option, sched=sched)


def _plan(db, world, *, status, paid=0, per=300, final=None,
          total=600, expected=2, created=None, user=None):
    """Tom's agreement: 2 x A$3 after a A$4 discount off 2 x A$5."""
    row = PurchasePlan(
        id=_uid("pplan"), member_user_id=(user or world["member"]).id,
        payment_option_id=world["option"].id,
        payment_option_schedule_id=world["sched"].id,
        space_id=world["space"].id, creator_user_id=world["creator"].id,
        status=status, currency="AUD",
        installment_amount_cents=per,
        final_installment_amount_cents=final,
        installments_expected=expected, installments_paid=paid,
        total_expected_cents=total,
        stripe_interval="month", stripe_interval_count=1,
    )
    db.add(row)
    db.flush()
    if created is not None:
        row.created_at = created
        db.flush()
    return row


def _paid_instalment(db, world, plan, *, cents, n):
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        space_id=world["space"].id, currency="AUD",
        gross_amount_cents=cents, platform_fee_basis_points=0,
        payout_status=PayoutStatus.pending,
        payment_option_id=world["option"].id,
        purchase_plan_id=plan.id, installment_number=n,
        payer_user_id=plan.member_user_id,
    )
    db.add(txn)
    db.flush()
    return txn


def _ask(db, world, user=...):
    return mop.purchases_for_options(
        db,
        user=world["member"] if user is ... else user,
        payment_option_ids=[world["option"].id],
        now=NOW,
    )


# ---------------------------------------------------------------------------
# The reported case
# ---------------------------------------------------------------------------


class TestAnActiveDiscountedPlan:
    def test_the_agreed_figures_are_the_plans_not_the_options(self, db, world):
        """The Option still lists 2 x A$5. Tom agreed 2 x A$3, and the
        creator may edit the Option or the code at any time — so the
        plan is the only honest source."""
        plan = _plan(db, world, status=PurchasePlanStatus.active, paid=1)
        _paid_instalment(db, world, plan, cents=300, n=1)

        [pur] = _ask(db, world)
        assert pur.kind == "plan"
        assert pur.plan.installment_amount_cents == 300
        assert pur.plan.total_expected_cents == 600
        assert pur.plan.installments_paid == 1
        assert pur.plan.installments_expected == 2
        assert pur.plan.paid_amount_cents == 300
        assert pur.plan.remaining_amount_cents == 300
        assert pur.plan.currency == "AUD"
        assert pur.plan.interval == "month"

    def test_it_blocks_a_second_purchase(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active, paid=1)
        assert _ask(db, world)[0].blocks_repurchase is True

    def test_it_names_the_arrangement_the_member_chose(self, db, world):
        """An Option can offer several; the card must show theirs rather
        than the first on the list."""
        _plan(db, world, status=PurchasePlanStatus.active)
        assert _ask(db, world)[0].plan.payment_option_schedule_id == (
            world["sched"].id
        )

    def test_an_uneven_plan_keeps_its_odd_final_payment(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active,
              per=4_333, final=4_334, total=13_000, expected=3)
        plan = _ask(db, world)[0].plan
        assert plan.installment_amount_cents == 4_333
        assert plan.final_installment_amount_cents == 4_334

    def test_an_even_plan_declares_no_final_amount(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        assert _ask(db, world)[0].plan.final_installment_amount_cents is None


# ---------------------------------------------------------------------------
# Lifecycle — §8
# ---------------------------------------------------------------------------


class TestEveryPlanState:
    @pytest.mark.parametrize("status", [
        PurchasePlanStatus.pending_setup,
        PurchasePlanStatus.active,
        PurchasePlanStatus.payment_problem,
    ])
    def test_a_live_arrangement_blocks_a_second_one(self, db, world, status):
        """Rule D's own list. These are the states the till refuses."""
        _plan(db, world, status=status)
        [pur] = _ask(db, world)
        assert pur.blocks_repurchase is True
        assert pur.plan.status == status.value

    @pytest.mark.parametrize("status", [
        PurchasePlanStatus.completed,
        PurchasePlanStatus.cancelled,
        PurchasePlanStatus.failed,
        PurchasePlanStatus.suspended,
    ])
    def test_the_rest_are_reported_but_do_not_block(self, db, world, status):
        """Absent from Rule D on purpose, so buying again is legitimate
        — a new term, or a retry. The plan is still reported so the card
        can describe it accurately instead of claiming nothing exists.
        """
        _plan(db, world, status=status)
        [pur] = _ask(db, world)
        assert pur.blocks_repurchase is False
        assert pur.plan.status == status.value

    def test_a_refunded_instalment_does_not_inflate_paid_to_date(
        self, db, world,
    ):
        """``paid_amount_cents`` counts succeeded transactions, the same
        rule the creator surface uses. A refund is its own row."""
        plan = _plan(db, world, status=PurchasePlanStatus.cancelled, paid=1)
        txn = _paid_instalment(db, world, plan, cents=300, n=1)
        txn.refunded_amount_cents = 300
        db.flush()
        [pur] = _ask(db, world)
        assert pur.plan.paid_amount_cents == 300
        assert pur.plan.remaining_amount_cents == 300


class TestWhichPlanTheMemberIsLivingWith:
    def test_a_live_plan_wins_over_a_finished_one(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.cancelled,
              created=NOW - timedelta(days=200))
        _plan(db, world, status=PurchasePlanStatus.active,
              created=NOW - timedelta(days=1))
        assert _ask(db, world)[0].plan.status == "active"

    def test_a_live_plan_wins_even_when_it_is_the_older_row(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active,
              created=NOW - timedelta(days=200))
        _plan(db, world, status=PurchasePlanStatus.cancelled,
              created=NOW - timedelta(days=1))
        assert _ask(db, world)[0].plan.status == "active"

    def test_with_no_live_plan_the_most_recent_is_described(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.failed,
              created=NOW - timedelta(days=200))
        _plan(db, world, status=PurchasePlanStatus.completed, total=600,
              created=NOW - timedelta(days=1))
        assert _ask(db, world)[0].plan.status == "completed"


# ---------------------------------------------------------------------------
# Purchase is not access — §6, §10
# ---------------------------------------------------------------------------


class TestPurchaseIsNotAccess:
    def test_a_member_who_bought_nothing_has_no_entry(self, db, world):
        assert _ask(db, world) == []

    def test_a_pass_from_this_option_reads_as_a_pay_in_full_purchase(
        self, db, world,
    ):
        db.add(AccessPass(
            id=_uid("ap"), user_id=world["member"].id,
            space_id=world["space"].id,
            payment_option_id=world["option"].id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
        ))
        db.flush()
        [pur] = _ask(db, world)
        assert pur.kind == "pay_in_full"
        assert pur.plan is None
        assert pur.blocks_repurchase is True

    def test_a_pass_from_a_different_option_says_nothing_about_this_one(
        self, db, world,
    ):
        """§6 — owning an included experience by another route is not a
        purchase of this arrangement."""
        other_option = PaymentOption(
            id=_uid("po"), space_id=world["space"].id,
            attaches_to_kind="pathway", attaches_to_id=_uid("pw"),
            name="Something else", payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=500, currency="AUD",
        )
        db.add(other_option)
        db.flush()
        db.add(AccessPass(
            id=_uid("ap"), user_id=world["member"].id,
            space_id=world["space"].id,
            payment_option_id=other_option.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
        ))
        db.flush()
        assert _ask(db, world) == []

    def test_an_expired_pass_no_longer_blocks_a_repurchase(self, db, world):
        db.add(AccessPass(
            id=_uid("ap"), user_id=world["member"].id,
            space_id=world["space"].id,
            payment_option_id=world["option"].id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            valid_until=NOW - timedelta(days=1),
        ))
        db.flush()
        assert _ask(db, world) == []


# ---------------------------------------------------------------------------
# One viewer only
# ---------------------------------------------------------------------------


class TestItIsOnlyEverAboutTheViewer:
    def test_a_signed_out_reader_is_told_nothing(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        assert mop.purchases_for_options(
            db, user=None,
            payment_option_ids=[world["option"].id], now=NOW,
        ) == []

    def test_one_member_cannot_see_anothers_plan(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        assert _ask(db, world, user=world["other"]) == []

    def test_an_empty_option_list_asks_nothing(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        assert mop.purchases_for_options(
            db, user=world["member"], payment_option_ids=[], now=NOW,
        ) == []


class TestTheSpaceScopedHelper:
    def test_it_reports_only_options_that_block(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        held = mop.held_option_ids_in_space(
            db, user=world["member"], space_id=world["space"].id, now=NOW,
        )
        assert held == {world["option"].id}

    def test_a_finished_plan_is_not_held(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.cancelled)
        assert mop.held_option_ids_in_space(
            db, user=world["member"], space_id=world["space"].id, now=NOW,
        ) == set()

    def test_a_signed_out_reader_holds_nothing(self, db, world):
        _plan(db, world, status=PurchasePlanStatus.active)
        assert mop.held_option_ids_in_space(
            db, user=None, space_id=world["space"].id, now=NOW,
        ) == set()
