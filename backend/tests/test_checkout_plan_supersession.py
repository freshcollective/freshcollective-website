"""Changing payment method before paying anything.

The production defect: a member started EMBODY's Activate weekly
checkout, changed her mind, and could not pay in full. The plan row is
written before Stripe is contacted, nothing ever expired it, and Rule D
in ``checkout_orchestration`` reads ``pending_setup`` as an agreement in
progress — for every payment method on the option. She could still buy
Awaken or Empower, which is what made it look so odd: only the option
she had touched was sealed.

Two properties are being protected here, and they pull against each
other. An abandoned checkout must stop blocking; a real agreement must
keep blocking. Most of what follows is the second one — plans with an
instalment paid, a subscription, a schedule, a completed Session, a
succeeded SetupIntent, or an attached payment method all still refuse,
and so does a Stripe read we could not perform. Getting the first right
at the cost of the second would be much worse than the bug.

Stripe is mocked throughout, at the three seams the resolver uses. No
test contacts Stripe and none sends mail.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_checkout_plan_supersession.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider, PaymentTransaction,
    PaymentTransactionStatus, PaymentTransactionType, PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import checkout_supersession as sup
from app.services import finite_plan_release as rel
from app.services.checkout_orchestration import check_same_option_not_active
from app.services.discount_stripe_sessions import (
    StripeStateChanged, StripeUnavailable,
)
from app.services.stripe_finite_plan import SetupSessionState

RESOLVER = "app.services.checkout_supersession"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _state(**kw) -> SetupSessionState:
    base = dict(
        session_id="cs_test_abandoned", status="expired",
        setup_intent_id="seti_1", setup_intent_status="canceled",
        payment_method_id=None, subscription_id=None,
    )
    base.update(kw)
    return SetupSessionState(**base)


@pytest.fixture
def world(db, make_user, make_space):
    """One Payment Option ("Activate") with both payment methods."""
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    now = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Term", starts_at=now - timedelta(days=5),
        ends_at=now + timedelta(days=60), status="published",
        published_at=now - timedelta(days=5),
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id, slug=f"p-{uuid.uuid4().hex[:8]}",
        title="Home Practice", status="active",
    )
    db.add_all([series, pathway])
    db.flush()

    option = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="event_series",
        attaches_to_id=series.id, name="Activate",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=30600, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    weekly = PaymentOptionSchedule(
        id=_uid("sch"), payment_option_id=option.id, name="Weekly payments",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=3060, installment_count=10,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=30600, currency="AUD",
    )
    upfront = PaymentOptionSchedule(
        id=_uid("sch"), payment_option_id=option.id, name="Pay in full",
        schedule_type="pay_in_full", status="published",
        total_amount_cents=30600, currency="AUD",
    )
    other_option = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="event_series",
        attaches_to_id=series.id, name="Awaken",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=18000, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    db.add_all([option, weekly, upfront, other_option])
    db.flush()
    db.commit()
    return SimpleNamespace(
        member=member, creator=creator, space=space, series=series,
        pathway=pathway, option=option, weekly=weekly, upfront=upfront,
        other_option=other_option,
    )


def make_plan(db, world, *, schedule=None, status=PurchasePlanStatus.pending_setup,
              session_id="cs_test_abandoned", paid=0, sched_id=None, sub_id=None):
    plan = PurchasePlan(
        id=_uid("pplan"), member_user_id=world.member.id,
        payment_option_id=world.option.id,
        payment_option_schedule_id=(schedule or world.weekly).id,
        space_id=world.space.id, creator_user_id=world.creator.id,
        status=status, currency="AUD",
        installment_amount_cents=3060, installments_expected=10,
        installments_paid=paid, total_expected_cents=30600,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=f"cus_{uuid.uuid4().hex[:8]}",
        provider_setup_session_id=session_id,
        provider_subscription_schedule_id=sched_id,
        provider_subscription_id=sub_id,
        stripe_mode="test", snapshot_grants_json={},
    )
    db.add(plan)
    db.flush()
    db.commit()
    return plan


def resolve(db, world, *, schedule):
    return sup.resolve_pending_setup(
        db, user=world.member, payment_option_id=world.option.id,
        requested_schedule_id=schedule.id, now=datetime.utcnow(),
    )


# ═══ 1 · weekly abandoned, then pay in full ═══════════════════════════

class TestWeeklyThenUpfront:
    def test_the_bug_without_the_fix_rule_d_would_refuse(self, db, world):
        make_plan(db, world)
        with pytest.raises(HTTPException) as e:
            check_same_option_not_active(
                db, user=world.member, payment_option=world.option,
                now=datetime.utcnow(),
            )
        assert e.value.status_code == 409
        assert "payment plan in progress" in str(e.value.detail)

    def test_supersession_releases_it_and_the_guard_then_passes(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()):
            out = resolve(db, world, schedule=world.upfront)
        assert out.kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert plan.cancelled_reason == rel.RELEASE_SUPERSEDED
        assert plan.cancelled_by_user_id == world.member.id
        assert plan.cancelled_at is not None
        # The whole point: pay-in-full is now reachable.
        check_same_option_not_active(
            db, user=world.member, payment_option=world.option,
            now=datetime.utcnow(),
        )

    def test_instalment_counters_are_not_touched(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()):
            resolve(db, world, schedule=world.upfront)
        db.refresh(plan)
        assert (plan.installments_paid, plan.installments_expected) == (0, 10)


# ═══ 2 · pay in full abandoned, then weekly ═══════════════════════════

class TestUpfrontThenWeekly:
    def test_an_abandoned_upfront_purchase_never_blocked_anything(self, db, world):
        """Already correct before this change — asserted so it stays so.

        The pay-in-full path creates its Stripe Session first and only
        then writes a ``pending`` PaymentTransaction, and no guard looks
        at pending transactions. So abandoning it leaves nothing in the
        way of a later weekly checkout.
        """
        db.add(PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.pending,
            payer_user_id=world.member.id, space_id=world.space.id,
            payment_option_id=world.option.id, gross_amount_cents=30600,
            currency="AUD", payout_status=PayoutStatus.pending,
            stripe_mode="test",
            provider_checkout_session_id="cs_test_upfront_abandoned",
        ))
        db.commit()
        check_same_option_not_active(
            db, user=world.member, payment_option=world.option,
            now=datetime.utcnow(),
        )
        assert resolve(db, world, schedule=world.weekly).kind == "none"

    def test_a_succeeded_upfront_purchase_still_blocks(self, db, world):
        """Rules A-C, untouched."""
        db.add(PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            payer_user_id=world.member.id, space_id=world.space.id,
            payment_option_id=world.option.id, gross_amount_cents=30600,
            currency="AUD", payout_status=PayoutStatus.pending,
            stripe_mode="test",
        ))
        db.commit()
        # Access-based rules are what refuse here; the point is that the
        # supersession path has not opened a hole in them.
        assert resolve(db, world, schedule=world.weekly).kind == "none"


# ═══ 3 · switching while the original Session is still open ══════════

class TestSessionStillOpen:
    def test_switching_method_expires_the_open_session_then_releases(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   return_value=_state(status="open", setup_intent_status=None)), \
             patch(f"{RESOLVER}.expire_session") as expire:
            out = resolve(db, world, schedule=world.upfront)
        expire.assert_called_once_with("cs_test_abandoned")
        assert out.kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled

    def test_same_method_with_a_live_session_is_reused_not_duplicated(self, db, world):
        """Retrying weekly after closing the tab must not open a second
        payment page — that is how someone ends up paying twice."""
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   return_value=_state(status="open", setup_intent_status=None)), \
             patch(f"{RESOLVER}._session_url", return_value="https://stripe/live"), \
             patch(f"{RESOLVER}.expire_session") as expire:
            out = resolve(db, world, schedule=world.weekly)
        assert out.kind == "reused"
        assert out.checkout_url == "https://stripe/live"
        expire.assert_not_called()
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    def test_reuse_falls_back_to_supersede_when_stripe_gives_no_url(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   return_value=_state(status="open", setup_intent_status=None)), \
             patch(f"{RESOLVER}._session_url", return_value=None), \
             patch(f"{RESOLVER}.expire_session"):
            out = resolve(db, world, schedule=world.weekly)
        assert out.kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled


# ═══ 4 · switching after Stripe already expired the Session ══════════

class TestSessionAlreadyExpired:
    def test_no_expire_call_is_made(self, db, world):
        make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()), \
             patch(f"{RESOLVER}.expire_session") as expire:
            out = resolve(db, world, schedule=world.upfront)
        expire.assert_not_called()
        assert out.kind == "superseded"

    def test_same_method_on_a_dead_session_supersedes(self, db, world):
        make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()):
            assert resolve(db, world, schedule=world.weekly).kind == "superseded"


# ═══ 9 · Stripe errors while expiring ════════════════════════════════

class TestStripeErrorsDuringExpiry:
    def test_unavailable_defers_rather_than_releasing(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   side_effect=StripeUnavailable("boom")):
            with pytest.raises(HTTPException) as e:
                resolve(db, world, schedule=world.upfront)
        assert e.value.status_code == 409
        assert "could not confirm" in str(e.value.detail).lower()
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup, \
            "a plan whose Session we cannot read must not be released"

    def test_expire_failure_defers(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   return_value=_state(status="open", setup_intent_status=None)), \
             patch(f"{RESOLVER}.expire_session",
                   side_effect=StripeUnavailable("timeout")):
            with pytest.raises(HTTPException):
                resolve(db, world, schedule=world.upfront)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    def test_state_changed_rereads_and_releases_when_still_unused(self, db, world):
        """Stripe refused the expire because the Session closed itself.
        We re-read rather than assume which way it went."""
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   side_effect=[_state(status="open", setup_intent_status=None),
                                _state(status="expired")]), \
             patch(f"{RESOLVER}.expire_session",
                   side_effect=StripeStateChanged("not open")):
            out = resolve(db, world, schedule=world.upfront)
        assert out.kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled

    def test_state_changed_refuses_when_the_reread_shows_it_was_used(self, db, world):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   side_effect=[_state(status="open", setup_intent_status=None),
                                _state(status="complete",
                                       setup_intent_status="succeeded",
                                       payment_method_id="pm_1")]), \
             patch(f"{RESOLVER}.expire_session",
                   side_effect=StripeStateChanged("not open")):
            with pytest.raises(HTTPException) as e:
                resolve(db, world, schedule=world.upfront)
        assert e.value.status_code == 409
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup


# ═══ 10 · Stripe failed or timed out creating the Session ════════════

class TestCheckoutCreationFailure:
    def test_a_plan_with_no_session_id_is_releasable(self, db, world):
        """``start_finite_plan_setup`` commits the plan and *then* calls
        Stripe, so a failure there leaves a plan the member never got a
        page for. It must not seal the option."""
        plan = make_plan(db, world, session_id=None)
        with patch(f"{RESOLVER}.inspect_setup_session") as inspect:
            out = resolve(db, world, schedule=world.upfront)
        inspect.assert_not_called()
        assert out.kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert plan.cancelled_reason == rel.RELEASE_SUPERSEDED

    def test_retrying_the_same_method_also_recovers(self, db, world):
        plan = make_plan(db, world, session_id=None)
        with patch(f"{RESOLVER}.inspect_setup_session"):
            assert resolve(db, world, schedule=world.weekly).kind == "superseded"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled


# ═══ 11-12 · real agreements stay protected ══════════════════════════

class TestRealAgreementsProtected:
    @pytest.mark.parametrize("status", [
        PurchasePlanStatus.active, PurchasePlanStatus.payment_problem,
    ])
    def test_active_and_payment_problem_are_not_considered(self, db, world, status):
        plan = make_plan(db, world, status=status,
                         sched_id=f"sub_sched_{uuid.uuid4().hex[:8]}")
        with patch(f"{RESOLVER}.inspect_setup_session") as inspect:
            out = resolve(db, world, schedule=world.upfront)
        assert out.kind == "none", "only pending_setup is ever superseded"
        inspect.assert_not_called()
        db.refresh(plan)
        assert plan.status is status
        # And Rule D still refuses, exactly as before.
        with pytest.raises(HTTPException) as e:
            check_same_option_not_active(
                db, user=world.member, payment_option=world.option,
                now=datetime.utcnow(),
            )
        assert e.value.status_code == 409

    def test_pending_setup_with_a_paid_instalment_refuses(self, db, world):
        plan = make_plan(db, world, paid=1)
        # Stripe is patched to a perfectly releasable-looking state, so
        # the only thing that can refuse here is the precondition.
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()) as insp:
            with pytest.raises(HTTPException) as e:
                resolve(db, world, schedule=world.upfront)
        assert e.value.status_code == 409
        assert "payment plan in progress" in str(e.value.detail)
        insp.assert_not_called(), "must refuse before asking Stripe anything"
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    @pytest.mark.parametrize("field", ["sched_id", "sub_id"])
    def test_pending_setup_carrying_a_stripe_arrangement_refuses(self, db, world, field):
        plan = make_plan(db, world, **{field: f"x_{uuid.uuid4().hex[:8]}"})
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()) as insp:
            with pytest.raises(HTTPException) as e:
                resolve(db, world, schedule=world.upfront)
        assert e.value.status_code == 409
        assert "payment plan in progress" in str(e.value.detail)
        insp.assert_not_called()
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    @pytest.mark.parametrize("usable", [
        {"status": "complete"},
        {"setup_intent_status": "succeeded"},
        {"payment_method_id": "pm_123"},
        {"subscription_id": "sub_123"},
    ])
    def test_a_usable_session_refuses(self, db, world, usable):
        plan = make_plan(db, world)
        with patch(f"{RESOLVER}.inspect_setup_session",
                   return_value=_state(**usable)):
            with pytest.raises(HTTPException) as e:
                resolve(db, world, schedule=world.upfront)
        assert e.value.status_code == 409
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    def test_another_members_plan_is_untouched(self, db, world, make_user):
        other = make_user()
        theirs = PurchasePlan(
            id=_uid("pplan"), member_user_id=other.id,
            payment_option_id=world.option.id,
            payment_option_schedule_id=world.weekly.id,
            space_id=world.space.id, creator_user_id=world.creator.id,
            status=PurchasePlanStatus.pending_setup, currency="AUD",
            installment_amount_cents=3060, installments_expected=10,
            installments_paid=0, total_expected_cents=30600,
            stripe_interval="week", stripe_interval_count=1,
            platform_fee_basis_points=800, stripe_mode="test",
            provider_setup_session_id="cs_theirs", snapshot_grants_json={},
        )
        db.add(theirs)
        mine = make_plan(db, world)
        db.commit()
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()):
            resolve(db, world, schedule=world.upfront)
        db.refresh(theirs); db.refresh(mine)
        assert theirs.status is PurchasePlanStatus.pending_setup
        assert mine.status is PurchasePlanStatus.cancelled

    def test_a_plan_on_another_option_is_untouched(self, db, world):
        other = PurchasePlan(
            id=_uid("pplan"), member_user_id=world.member.id,
            payment_option_id=world.other_option.id,
            payment_option_schedule_id=world.weekly.id,
            space_id=world.space.id, creator_user_id=world.creator.id,
            status=PurchasePlanStatus.pending_setup, currency="AUD",
            installment_amount_cents=1800, installments_expected=10,
            installments_paid=0, total_expected_cents=18000,
            stripe_interval="week", stripe_interval_count=1,
            platform_fee_basis_points=800, stripe_mode="test",
            provider_setup_session_id="cs_other_option", snapshot_grants_json={},
        )
        db.add(other)
        make_plan(db, world)
        db.commit()
        with patch(f"{RESOLVER}.inspect_setup_session", return_value=_state()):
            resolve(db, world, schedule=world.upfront)
        db.refresh(other)
        assert other.status is PurchasePlanStatus.pending_setup


# ═══ wiring ══════════════════════════════════════════════════════════

class TestWiring:
    """Order matters here, and only source can show it.

    The release has to happen before Rule D runs, or the guard refuses
    the request before anything has had a chance to clear the way. And
    the lock has to be taken before the read, or two requests can both
    decide there is nothing in progress.
    """

    @staticmethod
    def _src(path: str) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / path).read_text()

    def test_the_lock_is_taken_before_the_resolve(self):
        src = self._src("app/checkout/routes.py")
        lock = src.index("_supersession.lock_member_option")
        resolve_at = src.index("_supersession.resolve_pending_setup")
        assert lock < resolve_at

    def test_supersession_runs_before_rule_d_in_both_branches(self):
        src = self._src("app/checkout/routes.py")
        resolve_at = src.index("_supersession.resolve_pending_setup")
        guards = [
            i for i in range(len(src))
            if src.startswith("check_same_option_not_active(\n", i)
        ]
        assert len(guards) >= 2, "expected the plan and pay-in-full branches"
        assert all(g > resolve_at for g in guards), \
            "Rule D must not run before the abandoned plan is released"

    def test_a_reused_session_returns_without_creating_anything(self):
        src = self._src("app/checkout/routes.py")
        block = src[src.index('if _pending.kind == "reused"'):]
        head = block[: block.index("if is_recurring:")]
        assert "return UnifiedCheckoutResponse(" in head
        assert "start_finite_plan_setup" not in head
        assert "orchestrate_paid_checkout" not in head

    def test_rule_d_itself_is_unchanged(self):
        """Three other callers depend on it. The fix deliberately works
        by clearing the row it reads, not by changing what it blocks."""
        src = self._src("app/services/checkout_orchestration.py")
        assert "'pending_setup', 'active', 'payment_problem'" in src

    def test_the_expiry_webhook_routes_plans_before_transaction_handling(self):
        src = self._src("app/webhooks/routes.py")
        body = src[src.index("def _handle_checkout_expired"):]
        branch = body.index('metadata.get("purchase_type") == "finite_plan_setup"')
        txn_lookup = body.index("db.query(PaymentTransaction)")
        assert branch < txn_lookup

    def test_the_release_service_cannot_reach_access_or_bookings(self):
        """Structural, not incidental: the narrow release must not even
        import the machinery that could revoke something."""
        src = self._src("app/services/finite_plan_release.py")
        for forbidden in (
            "access_grant_records", "AccessPass", "EventBooking",
            "PathwayEntitlement", "_release_future_plan_bookings",
            "emit_access_suspended", "schedule_routing_if_needed",
        ):
            assert forbidden not in src, f"{forbidden} must not be reachable here"


# ═══ the legacy /api/checkout/pathway wrapper ════════════════════════

class TestLegacyPathwayRoute:
    """Still live: ``PaymentOptionSelector`` renders ``CheckoutButton``,
    which posts to ``/api/checkout/pathway``, and does so for recurring
    schedules too. Its recurring branch calls Rule D, so the abandoned
    plan reached that route as well — fixing only ``/api/checkout``
    would have left the defect accessible through a real journey.
    """

    @staticmethod
    def _src(path: str) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / path).read_text()

    def test_it_takes_the_lock_and_resolves_before_rule_d(self):
        src = self._src("app/checkout/routes.py")
        body = src[src.index("def create_pathway_checkout_session"):]
        lock = body.index("_supersession.lock_member_option")
        resolve_at = body.index("_supersession.resolve_pending_setup")
        guard = body.index("check_same_option_not_active(")
        assert lock < resolve_at < guard

    def test_it_returns_a_pathway_response_on_reuse(self):
        src = self._src("app/checkout/routes.py")
        body = src[src.index("def create_pathway_checkout_session"):]
        block = body[body.index('if _pending.kind == "reused"'):]
        head = block[: block.index("if is_recurring:")]
        assert "return PathwayCheckoutResponse(checkout_url=_pending.checkout_url)" in head
        assert "start_finite_plan_setup" not in head

    def test_both_live_routes_are_covered(self):
        src = self._src("app/checkout/routes.py")
        assert src.count("_supersession.resolve_pending_setup") == 2, (
            "the unified endpoint and the legacy pathway wrapper are the two "
            "live member checkout entry points; both must release"
        )
