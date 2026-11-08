"""Stage 4 — discount codes across every supported purchase, flag ON.

The sibling class ``TestDiscountCodesArePayInFullOnlyWhileStage4IsOff``
in ``test_discount_checkout`` holds the flag-OFF contract, which is the
safety case for deploying this dark. Everything here runs with
``universal_discount_codes_enabled`` forced on, and asserts what the
flag buys.

Helpers are imported from ``test_discount_checkout`` rather than
restated. They encode the live EMBODY shape — Activate pay-in-full at
A$306, a 50% code — and a second copy would drift from the thing it is
meant to mirror.

What is deliberately NOT here: the pure arithmetic, which lives in
``test_stage4_discount_arithmetic`` with no database at all. These tests
are about whether the right arithmetic reaches the right place.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.checkout.schemas import PathwayCheckoutRequest, UnifiedCheckoutRequest
from app.core.config import settings
from app.models.discount_code import (
    DiscountCode,
    DiscountRedemption,
    DiscountReservation,
    DiscountTargetKind,
    ReservationStatus,
)
from app.models.payment import PaymentTransaction
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.discount_pricing import DiscountRejection

from tests.test_discount_checkout import (
    ACTIVATE_CENTS,
    HALF_OF_ACTIVATE,
    _uid,
    as_user,
    client,            # noqa: F401 — fixture
    make_code,
    make_offer,
    stripe_spy,        # noqa: F401 — fixture
    stripe_configured,  # noqa: F401 — fixture
    _reset_rate_limit,  # noqa: F401 — autouse fixture
)


@pytest.fixture(autouse=True)
def stage4_on(monkeypatch):
    """Every test in this module runs with Stage 4 switched on.

    Autouse and monkeypatched rather than set globally, so the flag-OFF
    suite in ``test_discount_checkout`` keeps testing the default and the
    two cannot contaminate each other.
    """
    monkeypatch.setattr(settings, "universal_discount_codes_enabled", True)


# ---------------------------------------------------------------------------
# Shapes this module needs that the pay-in-full helpers do not provide
# ---------------------------------------------------------------------------


def plan_schedule(
    db, option, *, per: int = 3_060, count: int = 10,
    interval: str = "week", interval_count: int = 1, currency: str = "AUD",
) -> PaymentOptionSchedule:
    """A published finite-instalment schedule on an existing Option."""
    sched = PaymentOptionSchedule(
        payment_option_id=option.id, name=f"{count} payments",
        schedule_type="recurring_installments", status="published",
        total_amount_cents=per * count,
        installment_amount_cents=per, installment_count=count,
        stripe_interval=interval, stripe_interval_count=interval_count,
        currency=currency,
    )
    db.add(sched)
    db.commit()
    return sched


def sellable_pathway(db, space, *, cents: int = 5_900, currency: str = "AUD") -> Pathway:
    """A Pathway whose own direct door is open.

    ``direct_purchase_enabled`` is set because Stage 2B made that the
    column the till consults; ``pricing_mode`` stays direct so the rule
    reads the same with the Stage 2B gate shut.
    """
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Direct Practice", status="active", access_type="one_time",
        price_cents=cents, currency=currency,
        pathway_type=PathwayType.guided_experience,
        direct_purchase_enabled=True,
    )
    db.add(p)
    db.commit()
    return p


def direct_pathway_checkout(db, user, *, pathway, code: str | None = None):
    from app.checkout.routes import create_pathway_checkout_session

    return create_pathway_checkout_session(
        PathwayCheckoutRequest(
            pathway_id=pathway.id,
            success_url="https://ok/success", cancel_url="https://ok/cancel",
            discount_code=code,
        ),
        current_user=user, db=db,
    )


def plan_checkout(db, user, *, option, schedule, code: str | None = None):
    from app.checkout.routes import create_unified_checkout_session

    return create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            success_url="https://ok/success", cancel_url="https://ok/cancel",
            discount_code=code,
        ),
        current_user=user, db=db,
    )


class _SetupSpy:
    """Captures the plan a discounted finite checkout established.

    Patches ``start_finite_plan_setup``'s Stripe call rather than the
    orchestrator, so the plan row is really written and really carries
    the discounted figures — which is the thing worth asserting.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id=f"cs_{uuid.uuid4().hex[:10]}",
            url="https://checkout.stripe.test/setup",
        )


@pytest.fixture
def setup_spy():
    spy = _SetupSpy()
    with patch("stripe.checkout.Session.create", side_effect=spy):
        yield spy


# ---------------------------------------------------------------------------
# Finite instalments — the headline of this stage
# ---------------------------------------------------------------------------


class TestADiscountedPaymentPlan:

    def test_the_plan_records_the_discounted_instalment_and_total(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """A$306 over ten payments, half off → A$153 total, A$15.30 each.

        The common real case, and exactly even — which is why an
        even-split-first implementation would have shipped every live
        EMBODY plan.
        """
        space, buyer = make_space(), make_user()
        option, _pay_in_full = make_offer(db, space)
        sched = plan_schedule(db, option, per=3_060, count=10)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        plan = db.query(PurchasePlan).one()
        assert plan.total_expected_cents == HALF_OF_ACTIVATE
        assert plan.installment_amount_cents == 1_530
        assert plan.installments_expected == 10
        # Even, so no separate final amount is declared — which is what
        # every pre-Stage-4 row means too.
        assert plan.final_installment_amount_cents is None
        assert plan.has_uneven_final_installment is False

    def test_an_uneven_plan_declares_its_final_instalment(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """A$150 over three, A$20 off → 43.33 / 43.33 / 43.34."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=15_000)
        sched = plan_schedule(db, option, per=5_000, count=3)
        make_code(
            db, space, discount_type="fixed_amount",
            percent_bps=None, amount_cents=2_000, currency="AUD",
        )

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        plan = db.query(PurchasePlan).one()
        assert plan.installment_amount_cents == 4_333
        assert plan.final_installment_amount_cents == 4_334
        assert plan.total_expected_cents == 13_000
        assert plan.has_uneven_final_installment is True
        # The invariant, on the row itself.
        assert (
            plan.installment_amount_cents * 2 + plan.final_installment_amount_cents
            == plan.total_expected_cents
        )

    def test_the_cadence_and_count_are_the_creators_not_the_discounts(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(
            db, option, per=5_000, count=6, interval="week", interval_count=2,
        )
        make_code(db, space, percent_bps=2000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        plan = db.query(PurchasePlan).one()
        assert plan.installments_expected == 6
        assert plan.stripe_interval == "week"
        assert plan.stripe_interval_count == 2
        assert plan.payment_option_schedule_id == sched.id

    def test_the_discount_is_snapshotted_on_the_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """So the charge stays explicable after the code is edited or
        deleted — and so the redemption can be found at activation."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        code = make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        snap = db.query(PurchasePlan).one().discount_snapshot_json
        assert snap["code"] == "FAMILY50"
        assert snap["discount_code_id"] == code.id
        assert snap["payment_mode"] == "plan"
        assert snap["installment_count"] == 10
        assert snap["installment_amount_cents"] == 1_530
        # Commitment-level, not one payment — that is what was discounted.
        assert snap["original_amount_cents"] == ACTIVATE_CENTS
        assert snap["final_amount_cents"] == HALF_OF_ACTIVATE

    def test_an_undiscounted_plan_is_unchanged(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """Regression: the plan row for a plain purchase must look exactly
        as it did before Stage 4."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option, per=3_060, count=10)

        plan_checkout(db, buyer, option=option, schedule=sched)

        plan = db.query(PurchasePlan).one()
        assert plan.installment_amount_cents == 3_060
        assert plan.total_expected_cents == 30_600
        assert plan.final_installment_amount_cents is None
        assert plan.discount_snapshot_json is None

    def test_a_plan_discount_that_leaves_payments_too_small_is_refused(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """§8 — refused with an explanation, never reshaped and never
        silently charged at full price."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=800)
        sched = plan_schedule(db, option, per=200, count=4)
        make_code(db, space, percent_bps=7500)

        with pytest.raises(HTTPException) as exc:
            plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        assert exc.value.status_code == 409
        assert "smallest payment" in str(exc.value.detail).lower()
        assert db.query(PurchasePlan).count() == 0

    def test_nothing_is_charged_when_a_plan_discount_is_refused(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=800)
        sched = plan_schedule(db, option, per=200, count=4)
        make_code(db, space, percent_bps=7500)

        with pytest.raises(HTTPException):
            plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        assert setup_spy.calls == []


# ---------------------------------------------------------------------------
# One use per purchase — §13
# ---------------------------------------------------------------------------


class TestAPlanConsumesOneUse:

    def _activate(self, db, plan):
        """Run the redemption conversion the first-invoice handler runs."""
        from app.services import discount_reservations as res

        return res.convert_plan_reservation(
            db, plan=plan, now=datetime.utcnow(), commit=True,
        )

    def test_establishing_a_plan_holds_a_slot_but_redeems_nothing(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """Capturing a card is not a redemption. A plan whose first
        payment never lands must leave the slot for someone else."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000, max_redemptions=1)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        assert db.query(DiscountRedemption).count() == 0
        held = db.query(DiscountReservation).one()
        assert held.status == ReservationStatus.held.value
        assert held.target_kind == DiscountTargetKind.payment_option.value

    def test_the_first_payment_redeems_exactly_once(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()

        self._activate(db, plan)

        redemption = db.query(DiscountRedemption).one()
        assert redemption.purchase_plan_id == plan.id
        assert redemption.payment_transaction_id is None
        # Frozen figures, from the reservation — the commitment's.
        assert redemption.original_amount_cents == ACTIVATE_CENTS
        assert redemption.final_amount_cents == HALF_OF_ACTIVATE

    def test_later_instalments_add_no_further_uses(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """§13's product decision, and it is structural: the partial
        unique index on (code, plan) permits exactly one row, so
        instalment four cannot add another even if asked."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()

        # Instalment one, then nine more — the webhook is idempotent and
        # a redelivery lands here too.
        for _ in range(10):
            self._activate(db, plan)

        assert db.query(DiscountRedemption).count() == 1

    def test_a_ten_use_code_is_not_exhausted_by_one_four_payment_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """§13's worked example, in reverse: the purchase counts once, so
        nine uses remain."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option, per=5_000, count=4)
        code = make_code(db, space, percent_bps=5000, max_redemptions=10)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()
        for _ in range(4):
            self._activate(db, plan)

        from app.services.discount_reservations import consumed_slots

        assert consumed_slots(db, code.id) == 1

    def test_a_plan_with_no_code_records_no_redemption(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)

        plan_checkout(db, buyer, option=option, schedule=sched)
        plan = db.query(PurchasePlan).one()

        assert self._activate(db, plan) is None
        assert db.query(DiscountRedemption).count() == 0

    def test_a_plan_claiming_a_code_with_no_reservation_still_activates(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """The member has paid and their plan is real. Refusing to
        activate over a missing hold would be the worse outcome, and the
        ledger under-counts rather than over-counts."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()
        db.query(DiscountReservation).delete()
        db.commit()

        assert self._activate(db, plan) is None
        assert db.query(DiscountRedemption).count() == 0


# ---------------------------------------------------------------------------
# Stability — §11
# ---------------------------------------------------------------------------


class TestAnEstablishedPlanIsStable:

    def test_editing_the_code_does_not_change_the_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        code = make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        before = db.query(PurchasePlan).one()
        agreed_per = before.installment_amount_cents
        agreed_total = before.total_expected_cents

        code.percent_bps = 1000
        db.commit()
        db.expire_all()

        after = db.query(PurchasePlan).one()
        assert after.installment_amount_cents == agreed_per
        assert after.total_expected_cents == agreed_total

    def test_expiring_the_code_does_not_change_the_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        code = make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        agreed = db.query(PurchasePlan).one().installment_amount_cents

        code.is_active = False
        code.expires_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
        db.expire_all()

        assert db.query(PurchasePlan).one().installment_amount_cents == agreed

    def test_editing_the_payment_option_price_does_not_change_the_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """The plan snapshots its money at creation, as it always has.
        A discount does not change that rule — it changes the figures
        being snapshotted."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option, per=3_060, count=10)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        agreed = db.query(PurchasePlan).one().installment_amount_cents

        sched.installment_amount_cents = 9_999
        sched.total_amount_cents = 99_990
        db.commit()
        db.expire_all()

        assert db.query(PurchasePlan).one().installment_amount_cents == agreed


# ---------------------------------------------------------------------------
# The two invoice gates — the thing that made this impossible before
# ---------------------------------------------------------------------------


class TestThePerInstalmentAmountGate:
    """``PurchasePlan.expected_installment_cents`` is what replaced the
    single scalar both gates compared against. It is deliberately NOT
    behind the Stage 4 flag — see the model docstring."""

    def _plan(self, per, final, count):
        p = PurchasePlan()
        p.installment_amount_cents = per
        p.final_installment_amount_cents = final
        p.installments_expected = count
        return p

    def test_an_even_plan_expects_the_same_amount_every_time(self):
        p = self._plan(1_530, None, 10)

        assert [p.expected_installment_cents(i) for i in range(1, 11)] == [1_530] * 10

    def test_an_uneven_plan_expects_the_final_amount_last(self):
        p = self._plan(4_333, 4_334, 3)

        assert [p.expected_installment_cents(i) for i in (1, 2, 3)] == [4_333, 4_333, 4_334]

    def test_a_single_payment_plan_is_also_its_last(self):
        p = self._plan(4_333, 4_999, 1)

        assert p.expected_installment_cents(1) == 4_999

    def test_a_redundant_final_amount_does_not_make_a_plan_uneven(self):
        """Writing the base amount into the final column is a no-op, not
        a second Stripe Price."""
        p = self._plan(1_530, 1_530, 10)

        assert p.has_uneven_final_installment is False

    def test_the_lookup_works_with_the_flag_off(self, monkeypatch):
        """§22 — a plan established while Stage 4 was on must keep
        billing correctly if it is later switched off. This is the
        assertion that makes that true rather than hoped for."""
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        p = self._plan(4_333, 4_334, 3)

        assert p.expected_installment_cents(3) == 4_334
        assert p.has_uneven_final_installment is True


# ---------------------------------------------------------------------------
# Direct purchases — §15
# ---------------------------------------------------------------------------


class TestADirectPathwayPurchase:

    def test_a_collective_wide_code_applies(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=5_900)
        make_code(db, space, percent_bps=5000)

        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        assert stripe_spy.unit_amount == 2_950

    def test_the_transaction_records_the_discounted_amount_and_snapshot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=5_900)
        make_code(db, space, percent_bps=5000)

        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        assert txn.gross_amount_cents == 2_950
        assert (txn.discount_snapshot_json or {})["code"] == "FAMILY50"

    def test_the_slot_is_held_against_the_pathway_not_an_option(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """A direct purchase has no Payment Option, which is why the
        reservation needed a second shape at all."""
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        make_code(db, space, percent_bps=5000)

        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        r = db.query(DiscountReservation).one()
        assert r.target_kind == DiscountTargetKind.pathway.value
        assert r.target_id == pathway.id
        assert r.payment_option_id is None
        assert r.payment_option_schedule_id is None

    def test_a_retry_reuses_its_own_hold_rather_than_spending_a_second_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The reason the direct shape needed its own unique index."""
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        code = make_code(db, space, percent_bps=5000, max_redemptions=1)

        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")
        first = db.query(DiscountReservation).one()
        # The member's page is live, so a second attempt is handed it back
        # rather than opening another.
        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        assert db.query(DiscountReservation).count() == 1
        assert db.query(DiscountReservation).one().id == first.id

    def test_the_fee_follows_the_discounted_amount(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """§12 — a creator's fee is charged on what was actually taken,
        never on the list price."""
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=10_000)
        make_code(db, space, percent_bps=5000)

        direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        assert txn.gross_amount_cents == 5_000
        assert txn.platform_fee_cents == round(
            5_000 * txn.platform_fee_basis_points / 10_000
        )
        assert txn.net_creator_amount_cents == 5_000 - txn.platform_fee_cents

    def test_a_direct_purchase_without_a_code_is_unchanged(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=5_900)

        direct_pathway_checkout(db, buyer, pathway=pathway)

        assert stripe_spy.unit_amount == 5_900
        assert db.query(DiscountReservation).count() == 0
        assert db.query(PaymentTransaction).one().discount_snapshot_json is None

    def test_an_unknown_code_is_refused_without_charging(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)

        with pytest.raises(HTTPException) as exc:
            direct_pathway_checkout(db, buyer, pathway=pathway, code="NOPE")

        assert exc.value.status_code == 409
        assert stripe_spy.calls == []
        assert db.query(PaymentTransaction).count() == 0


# ---------------------------------------------------------------------------
# Scope integrity — §4
# ---------------------------------------------------------------------------


class TestScopeIntegrity:

    def test_an_option_scoped_code_does_not_reach_a_direct_purchase(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """§4's worked example. EMBODY20 applies to the EMBODY Term 4
        Payment Option; a member buying an unrelated Pathway directly
        does not get it — and neither does one buying a Pathway that
        Option happens to include."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        pathway = sellable_pathway(db, space)
        make_code(
            db, space, code="EMBODY20", percent_bps=2000,
            scope_kind="payment_option", scope_id=option.id,
        )

        with pytest.raises(HTTPException) as exc:
            direct_pathway_checkout(db, buyer, pathway=pathway, code="EMBODY20")

        assert exc.value.status_code == 409
        assert stripe_spy.calls == []

    def test_an_option_scoped_code_does_not_reach_another_option(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        from tests.test_discount_checkout import checkout

        space, buyer = make_space(), make_user()
        mine, _mine_sched = make_offer(db, space)
        theirs, theirs_sched = make_offer(db, space)
        make_code(
            db, space, code="MINE20", percent_bps=2000,
            scope_kind="payment_option", scope_id=mine.id,
        )

        with pytest.raises(HTTPException):
            checkout(db, buyer, option=theirs, schedule=theirs_sched, code="MINE20")

        assert stripe_spy.calls == []

    def test_an_option_scoped_code_still_applies_to_its_own_plan(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """Scoped to the Option, not to one schedule on it — so it covers
        the Option's instalment plan as well as its pay-in-full."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(
            db, space, code="EMBODY20", percent_bps=2000,
            scope_kind="payment_option", scope_id=option.id,
        )

        plan_checkout(db, buyer, option=option, schedule=sched, code="EMBODY20")

        plan = db.query(PurchasePlan).one()
        assert plan.total_expected_cents == round(ACTIVATE_CENTS * 0.8)

    def test_a_code_from_another_collective_is_not_recognised(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Reported as unrecognised rather than refused, so a refusal
        never confirms another creator's code is real."""
        mine, theirs = make_space(), make_space()
        buyer = make_user()
        pathway = sellable_pathway(db, mine)
        make_code(db, theirs, code="THEIRS50", percent_bps=5000)

        with pytest.raises(HTTPException) as exc:
            direct_pathway_checkout(db, buyer, pathway=pathway, code="THEIRS50")

        assert "not recognised" in str(exc.value.detail).lower()


# ---------------------------------------------------------------------------
# The flag — §22
# ---------------------------------------------------------------------------


class TestTheFlagGatesTheNewDoors:

    def test_a_direct_pathway_code_is_refused_while_the_flag_is_off(
        self, db, make_space, make_user, stripe_configured, stripe_spy, monkeypatch,
    ):
        """Refused, not ignored. Charging full price after accepting a
        code is the one outcome §10 rules out."""
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        make_code(db, space, percent_bps=5000)

        with pytest.raises(HTTPException) as exc:
            direct_pathway_checkout(db, buyer, pathway=pathway, code="FAMILY50")

        assert exc.value.status_code == 400
        assert stripe_spy.calls == []

    def test_a_direct_pathway_purchase_without_a_code_works_with_the_flag_off(
        self, db, make_space, make_user, stripe_configured, stripe_spy, monkeypatch,
    ):
        """The refusal is about the code, not about the door."""
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=5_900)

        direct_pathway_checkout(db, buyer, pathway=pathway)

        assert stripe_spy.unit_amount == 5_900

    def test_a_plan_code_is_refused_with_the_v1_wording_while_off(
        self, db, make_space, make_user, stripe_configured, setup_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000)

        with pytest.raises(HTTPException) as exc:
            plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        assert exc.value.status_code == 400
        assert "pay-in-full" in str(exc.value.detail).lower()

    def test_pay_in_full_payment_option_codes_work_either_way(
        self, db, make_space, make_user, stripe_configured, stripe_spy, monkeypatch,
    ):
        """The pre-existing door is not gated. Stage 4 adds doors; it does
        not put a switch in front of the one that was already open."""
        from tests.test_discount_checkout import checkout

        for enabled in (False, True):
            monkeypatch.setattr(
                settings, "universal_discount_codes_enabled", enabled,
            )
            space, buyer = make_space(), make_user()
            option, sched = make_offer(db, space)
            make_code(db, space, percent_bps=5000)

            checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

            assert stripe_spy.unit_amount == HALF_OF_ACTIVATE


# ---------------------------------------------------------------------------
# The preview surface — §9, §10
# ---------------------------------------------------------------------------


class TestPreviewingEveryArrangement:

    def _preview(self, client, body):
        return client.post("/api/checkout/discount-preview", json=body)

    def test_a_plan_preview_returns_the_actual_schedule(
        self, client, db, make_space, make_user,
    ):
        """§7 — the member must see the real instalments before agreeing,
        so the server sends them rather than a total to divide."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=15_000)
        sched = plan_schedule(db, option, per=5_000, count=3)
        make_code(
            db, space, discount_type="fixed_amount",
            percent_bps=None, amount_cents=2_000, currency="AUD",
        )
        as_user(buyer)

        res = self._preview(client, {
            "payment_option_id": option.id,
            "payment_option_schedule_id": sched.id,
            "code": "FAMILY50",
        })

        body = res.json()
        assert body["valid"] is True
        assert body["payment_mode"] == "plan"
        assert body["installment_count"] == 3
        assert body["installment_amount_cents"] == 4_333
        assert body["final_installment_amount_cents"] == 4_334
        assert body["final_amount_cents"] == 13_000

    def test_an_even_plan_preview_still_sends_both_figures(
        self, client, db, make_space, make_user,
    ):
        """So a client renders accurately without deciding whether a
        remainder exists."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option, per=3_060, count=10)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = self._preview(client, {
            "payment_option_id": option.id,
            "payment_option_schedule_id": sched.id,
            "code": "FAMILY50",
        }).json()

        assert body["installment_amount_cents"] == 1_530
        assert body["final_installment_amount_cents"] == 1_530

    def test_a_direct_pathway_preview_prices_the_pathways_own_price(
        self, client, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space, cents=5_900)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = self._preview(client, {
            "direct_kind": "pathway", "direct_id": pathway.id,
            "code": "FAMILY50",
        }).json()

        assert body["valid"] is True
        assert body["payment_mode"] == "single"
        assert body["original_amount_cents"] == 5_900
        assert body["final_amount_cents"] == 2_950

    def test_a_pay_in_full_preview_is_unchanged(
        self, client, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        option, sched = make_offer(db, space)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = self._preview(client, {
            "payment_option_id": option.id,
            "payment_option_schedule_id": sched.id,
            "code": "FAMILY50",
        }).json()

        assert body["final_amount_cents"] == HALF_OF_ACTIVATE
        assert body["installment_count"] is None

    def test_naming_both_shapes_is_refused(self, client, db, make_space, make_user):
        """An answer about the wrong price is worse than no answer."""
        space, buyer = make_space(), make_user()
        option, sched = make_offer(db, space)
        pathway = sellable_pathway(db, space)
        as_user(buyer)

        res = self._preview(client, {
            "payment_option_id": option.id,
            "payment_option_schedule_id": sched.id,
            "direct_kind": "pathway", "direct_id": pathway.id,
            "code": "X",
        })

        assert res.status_code == 422

    def test_naming_neither_shape_is_refused(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        as_user(buyer)

        res = self._preview(client, {"code": "X"})

        assert res.status_code == 422

    def test_a_direct_preview_refuses_a_pathway_that_is_not_sold_directly(
        self, client, db, make_space, make_user,
    ):
        """Preview must not quote a price the till would refuse.

        The door is closed the way production closes it today: with the
        Stage 2B gate shut, ``pricing_mode='payment_options'`` means an
        Option prices this Pathway and the ``price_cents`` beside it is
        dormant. ``direct_purchase_enabled`` is deliberately NOT what is
        set here — with that gate shut nothing reads it, so setting it
        would be testing a column no code consults.

        Both branches are covered: the gate-open form is the test below.
        """
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        pathway.pricing_mode = "payment_options"
        db.commit()
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        res = self._preview(client, {
            "direct_kind": "pathway", "direct_id": pathway.id, "code": "FAMILY50",
        })

        assert res.status_code == 400

    def test_the_same_refusal_holds_with_the_stage_2b_gate_open(
        self, client, db, make_space, make_user, monkeypatch,
    ):
        """With Stage 2B open, ``direct_purchase_enabled`` is the column
        that decides. One rule, two expressions — and the preview must
        obey whichever is live rather than carrying its own copy."""
        monkeypatch.setattr(
            settings, "pathway_multiple_purchase_options_enabled", True,
        )
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        pathway.direct_purchase_enabled = False
        db.commit()
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        res = self._preview(client, {
            "direct_kind": "pathway", "direct_id": pathway.id, "code": "FAMILY50",
        })

        assert res.status_code == 400

    def test_an_unknown_direct_kind_is_refused(
        self, client, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        as_user(buyer)

        res = self._preview(client, {
            "direct_kind": "offering", "direct_id": "x", "code": "X",
        })

        assert res.status_code == 422

    def test_a_direct_preview_is_refused_while_the_flag_is_off(
        self, client, db, make_space, make_user, monkeypatch,
    ):
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        space, buyer = make_space(), make_user()
        pathway = sellable_pathway(db, space)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        res = self._preview(client, {
            "direct_kind": "pathway", "direct_id": pathway.id, "code": "FAMILY50",
        })

        assert res.status_code == 400

    def test_preview_and_checkout_agree_on_a_plan(
        self, client, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """§10 — the quote and the charge come from one calculation. A
        preview that reached its figure another way would eventually
        disagree, and the member would be the one to find out."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=15_000)
        sched = plan_schedule(db, option, per=5_000, count=3)
        make_code(
            db, space, discount_type="fixed_amount",
            percent_bps=None, amount_cents=2_000, currency="AUD",
        )
        as_user(buyer)

        quoted = self._preview(client, {
            "payment_option_id": option.id,
            "payment_option_schedule_id": sched.id,
            "code": "FAMILY50",
        }).json()

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()

        assert plan.installment_amount_cents == quoted["installment_amount_cents"]
        assert plan.final_installment_amount_cents == quoted["final_installment_amount_cents"]
        assert plan.total_expected_cents == quoted["final_amount_cents"]


# ---------------------------------------------------------------------------
# Refunds — §14
# ---------------------------------------------------------------------------


class TestRefundsOperateOnWhatWasCollected:
    """§14's worked example: a A$100 bundle at 20% off is a A$80 payment,
    and a full refund returns A$80.

    There is nothing to implement for this and that is the finding. The
    refund path measures against ``PaymentTransaction.gross_amount_cents``,
    which for a discounted purchase IS the discounted amount — set at
    checkout, never re-derived from a list price. So these tests exist to
    pin that, not to describe new behaviour: the way this could break is
    someone later "fixing" a discounted refund by reaching for the
    original price.
    """

    def test_the_refundable_amount_is_the_discounted_gross(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        from tests.test_discount_checkout import checkout

        space, buyer = make_space(), make_user()
        option, sched = make_offer(db, space, cents=10_000)
        make_code(db, space, percent_bps=2000)

        checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        # A$100 at 20% off — the §14 example exactly.
        assert txn.gross_amount_cents == 8_000
        assert txn.gross_amount_cents - (txn.refunded_amount_cents or 0) == 8_000

    def test_the_original_price_is_recorded_but_is_not_the_refundable_amount(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Both figures are on the row, and only one of them is money
        that changed hands. The snapshot explains the charge; the gross
        IS the charge."""
        from tests.test_discount_checkout import checkout

        space, buyer = make_space(), make_user()
        option, sched = make_offer(db, space, cents=10_000)
        make_code(db, space, percent_bps=2000)

        checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        snap = txn.discount_snapshot_json
        assert snap["original_amount_cents"] == 10_000
        assert snap["final_amount_cents"] == 8_000
        assert txn.gross_amount_cents == snap["final_amount_cents"]

    def test_a_refund_does_not_restore_the_discount_use(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The existing policy, preserved rather than changed — §13 is
        explicit that a refund-restores-discount rule must not be
        introduced quietly.

        Nothing in the refund path touches ``discount_redemptions``, and
        that is the behaviour: a redemption records that a code WAS used,
        which stays true after a refund. If that should change it is a
        product decision, and this test is where it would be made
        deliberately.
        """
        import inspect

        from app.creator import refund_routes

        src = inspect.getsource(refund_routes)
        assert "DiscountRedemption" not in src
        assert "discount_redemptions" not in src

    def test_a_discounted_plan_instalment_records_what_it_charged(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """Each instalment's own gross is its own amount, so a refund of
        one payment refunds that payment — not a share of a list price."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=15_000)
        sched = plan_schedule(db, option, per=5_000, count=3)
        make_code(
            db, space, discount_type="fixed_amount",
            percent_bps=None, amount_cents=2_000, currency="AUD",
        )

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        plan = db.query(PurchasePlan).one()

        # What each invoice will be checked against, and recorded as.
        assert [plan.expected_installment_cents(i) for i in (1, 2, 3)] == [
            4_333, 4_333, 4_334,
        ]


# ---------------------------------------------------------------------------
# Creator visibility — §17
# ---------------------------------------------------------------------------


class TestTheCreatorCanSeeADiscountedPlan:

    def test_an_instalment_row_carries_the_plans_discount(self):
        """Without this a creator sees a A$15.30 payment and no sign a
        code was involved — the amount right, the page unable to explain
        it. §17's "smallest change needed to avoid misleading financial
        information"."""
        from app.creator.routes import resolve_discount_view

        instalment = SimpleNamespace(
            discount_snapshot_json=None, purchase_plan_id="pplan_1",
        )
        plan_snaps = {"pplan_1": {"code": "FAMILY50", "percent_bps": 5000}}

        view, scope = resolve_discount_view(instalment, plan_snaps)

        assert view["code"] == "FAMILY50"
        assert scope == "payment_plan"

    def test_a_pay_in_full_rows_own_snapshot_wins(self):
        """Its figures are about that charge, so they are not replaced by
        a plan's even if both somehow existed."""
        from app.creator.routes import resolve_discount_view

        txn = SimpleNamespace(
            discount_snapshot_json={"code": "MINE"}, purchase_plan_id="pplan_1",
        )

        view, scope = resolve_discount_view(txn, {"pplan_1": {"code": "PLANS"}})

        assert view["code"] == "MINE"
        assert scope == "purchase"

    def test_a_payment_with_no_code_shows_nothing(self):
        """Every transaction predating discount codes, and every
        undiscounted one since. A creator looking at one sees exactly
        what they saw before."""
        from app.creator.routes import resolve_discount_view

        assert resolve_discount_view(
            SimpleNamespace(discount_snapshot_json=None, purchase_plan_id=None), {},
        ) == ({}, None)

    def test_an_instalment_of_an_undiscounted_plan_shows_nothing(self):
        from app.creator.routes import resolve_discount_view

        txn = SimpleNamespace(
            discount_snapshot_json=None, purchase_plan_id="pplan_1",
        )

        assert resolve_discount_view(txn, {}) == ({}, None)

    def test_the_scope_says_whether_the_figures_are_the_plans(
        self, db, make_space, make_user, stripe_configured, setup_spy,
    ):
        """A plan's snapshot holds the WHOLE commitment's original and
        discount. Printing "Original A$306" beside a A$15.30 payment
        would mislead in a new way while fixing the old one, so the
        scope travels with the figures."""
        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space)
        sched = plan_schedule(db, option)
        make_code(db, space, percent_bps=5000)

        plan_checkout(db, buyer, option=option, schedule=sched, code="FAMILY50")
        snap = db.query(PurchasePlan).one().discount_snapshot_json

        # The commitment, explicitly labelled as a plan.
        assert snap["payment_mode"] == "plan"
        assert snap["original_amount_cents"] == ACTIVATE_CENTS
        # And the per-payment figure a creator actually needs.
        assert snap["installment_amount_cents"] == 1_530


# ---------------------------------------------------------------------------
# The instalment lifecycle, with an uneven schedule
# ---------------------------------------------------------------------------


class TestAnUnevenPlanBillsThroughToTheEnd:
    """The failure this prevents is the ugliest one available here.

    Before Stage 4 both invoice gates compared every invoice against one
    scalar. An uneven final instalment would have been *rejected* — not
    at setup, where a member could be told something, but at invoice
    three, after they had already paid twice. So the gate is exercised
    end to end on the exact shape that would have broken: 43.33, 43.33,
    43.34.
    """

    def _established(self, db, make_space, make_user):
        """An active plan with an uneven discounted schedule.

        Built directly rather than through checkout: what is under test
        is the billing of an established plan, and driving the setup
        again would only re-test the previous class.
        """
        from app.models.creator_billing import (
            CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
        )

        space, buyer = make_space(), make_user()
        option, _ = make_offer(db, space, cents=15_000)
        sched = plan_schedule(db, option, per=5_000, count=3)

        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=buyer.id,
            payment_option_id=option.id,
            payment_option_schedule_id=sched.id,
            space_id=space.id,
            creator_user_id=space.creator_id,
            status=PurchasePlanStatus.active,
            currency="AUD",
            installment_amount_cents=4_333,
            final_installment_amount_cents=4_334,
            installments_expected=3,
            installments_paid=1,
            total_expected_cents=13_000,
            platform_fee_basis_points=0,
            payout_model="manual",
            stripe_interval="month",
            stripe_interval_count=1,
            stripe_mode="test",
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
            activated_at=datetime.utcnow(),
        )
        db.add(plan)
        db.commit()
        return plan

    def _record(self, db, plan, *, amount: int, invoice: str):
        from app.services.finite_plan_lifecycle import (
            record_later_successful_instalment,
        )

        return record_later_successful_instalment(
            db,
            plan=plan,
            invoice_id=invoice,
            invoice_amount_cents=amount,
            invoice_currency="AUD",
            subscription_id=plan.provider_subscription_id,
            charge_id=None,
            payment_intent_id=None,
            now=datetime.utcnow(),
        )

    def test_the_middle_instalment_takes_the_base_amount(
        self, db, make_space, make_user,
    ):
        plan = self._established(db, make_space, make_user)

        outcome = self._record(db, plan, amount=4_333, invoice="in_2")

        assert outcome.installment_number == 2
        assert plan.installments_paid == 2

    def test_the_final_instalment_takes_the_odd_cent(
        self, db, make_space, make_user,
    ):
        """The assertion the whole stage turns on. Before Stage 4 this
        raised, and the member's plan died one payment from the end."""
        plan = self._established(db, make_space, make_user)
        self._record(db, plan, amount=4_333, invoice="in_2")

        outcome = self._record(db, plan, amount=4_334, invoice="in_3")

        assert outcome.installment_number == 3
        assert plan.installments_paid == 3

    def test_the_base_amount_is_refused_on_the_final_instalment(
        self, db, make_space, make_user,
    ):
        """The gate stayed exact. No tolerance was restored — an invoice
        a cent short of what was agreed is still wrong, and saying so
        loudly is the point."""
        plan = self._established(db, make_space, make_user)
        self._record(db, plan, amount=4_333, invoice="in_2")

        with pytest.raises(RuntimeError, match="amount mismatch"):
            self._record(db, plan, amount=4_333, invoice="in_3")

    def test_the_final_amount_is_refused_on_a_middle_instalment(
        self, db, make_space, make_user,
    ):
        """Both directions. The gate knows which instalment this is, not
        merely which amounts are plausible."""
        plan = self._established(db, make_space, make_user)

        with pytest.raises(RuntimeError, match="amount mismatch"):
            self._record(db, plan, amount=4_334, invoice="in_2")

    def test_the_recorded_transactions_sum_to_the_agreed_total(
        self, db, make_space, make_user,
    ):
        """What the creator is paid, and what a refund would work from."""
        plan = self._established(db, make_space, make_user)
        self._record(db, plan, amount=4_333, invoice="in_2")
        self._record(db, plan, amount=4_334, invoice="in_3")

        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == plan.id)
            .all()
        )
        # Instalment one was not recorded here (it belongs to the
        # activation path), so these are two of three.
        assert sum(r.gross_amount_cents for r in rows) == 4_333 + 4_334
        assert plan.installment_amount_cents + sum(
            r.gross_amount_cents for r in rows
        ) == plan.total_expected_cents

    def test_a_replayed_invoice_does_not_pay_twice(
        self, db, make_space, make_user,
    ):
        plan = self._established(db, make_space, make_user)
        self._record(db, plan, amount=4_333, invoice="in_2")

        again = self._record(db, plan, amount=4_333, invoice="in_2")

        assert again.installment_number == 2
        assert plan.installments_paid == 2

    def test_the_gate_holds_with_the_stage_4_flag_off(
        self, db, make_space, make_user, monkeypatch,
    ):
        """§22's actual requirement, exercised rather than asserted about
        a property: a plan established while Stage 4 was on keeps billing
        after it is switched off."""
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        plan = self._established(db, make_space, make_user)
        self._record(db, plan, amount=4_333, invoice="in_2")

        outcome = self._record(db, plan, amount=4_334, invoice="in_3")

        assert outcome.installment_number == 3
