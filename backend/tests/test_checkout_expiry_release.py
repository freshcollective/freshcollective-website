"""Stripe telling us an abandoned plan checkout expired.

``checkout.session.expired`` already existed, but it only knew how to
cancel a pending PaymentTransaction. A finite payment plan's setup
Session has no transaction — nothing is charged until the first invoice
— so the handler found nothing and returned, and the plan sat in
``pending_setup`` for good. That is why the EMBODY client stayed blocked
even though Stripe had expired her Session and delivered the webhook
successfully.

The tests below are mostly about *not* acting: a stale Session id, a
plan that has moved on, a redelivery, a plan carrying something real.
A webhook that releases the wrong plan would be worse than one that
releases nothing, because the member would lose a live checkout.

The existing behaviour for every other checkout type is asserted here
too, since the new branch sits in front of it.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_checkout_expiry_release.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

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
from app.services.stripe_finite_plan import SetupSessionState
from app.webhooks.finite_plan_handlers import handle_finite_plan_setup_expired
from app.webhooks.routes import _handle_checkout_expired

SESSION_ID = "cs_test_expired_one"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world(db, make_user, make_space):
    member, creator = make_user(), make_user(role="creator")
    space = make_space(creator=creator)
    now = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title="T", starts_at=now - timedelta(days=5),
        ends_at=now + timedelta(days=60), status="published",
        published_at=now - timedelta(days=5),
    )
    pathway = Pathway(id=_uid("p"), space_id=space.id,
                      slug=f"p-{uuid.uuid4().hex[:8]}", title="P", status="active")
    db.add_all([series, pathway]); db.flush()
    option = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="event_series",
        attaches_to_id=series.id, name="Activate",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=30600, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    weekly = PaymentOptionSchedule(
        id=_uid("s"), payment_option_id=option.id, name="Weekly",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=3060, installment_count=10,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=30600, currency="AUD",
    )
    upfront = PaymentOptionSchedule(
        id=_uid("s"), payment_option_id=option.id, name="Pay in full",
        schedule_type="pay_in_full", status="published",
        total_amount_cents=30600, currency="AUD",
    )
    db.add_all([option, weekly, upfront]); db.flush(); db.commit()
    return SimpleNamespace(member=member, creator=creator, space=space,
                           option=option, weekly=weekly, upfront=upfront)


def make_plan(db, world, *, session_id=SESSION_ID,
              status=PurchasePlanStatus.pending_setup, paid=0, sched_id=None):
    plan = PurchasePlan(
        id=_uid("pplan"), member_user_id=world.member.id,
        payment_option_id=world.option.id,
        payment_option_schedule_id=world.weekly.id,
        space_id=world.space.id, creator_user_id=world.creator.id,
        status=status, currency="AUD",
        installment_amount_cents=3060, installments_expected=10,
        installments_paid=paid, total_expected_cents=30600,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800, stripe_mode="test",
        provider_setup_session_id=session_id,
        provider_subscription_schedule_id=sched_id,
        snapshot_grants_json={},
    )
    db.add(plan); db.flush(); db.commit()
    return plan


def expiry_event(plan_id: str, session_id: str = SESSION_ID) -> dict:
    """The shape Stripe delivers for an expired finite-plan setup."""
    return {
        "id": session_id,
        "object": "checkout.session",
        "status": "expired",
        "mode": "setup",
        "metadata": {
            "purchase_type": "finite_plan_setup",
            "purchase_plan_id": plan_id,
        },
    }


def fire(db, plan_id, session_id=SESSION_ID):
    ev = expiry_event(plan_id, session_id)
    handle_finite_plan_setup_expired(ev, db, ev["metadata"])


# ═══ 5 · expiry arrives before the member retries ════════════════════

class TestExpiryBeforeRetry:
    def test_the_plan_is_released_with_its_own_audit_reason(self, db, world):
        plan = make_plan(db, world)
        fire(db, plan.id)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert plan.cancelled_reason == rel.RELEASE_SESSION_EXPIRED
        assert plan.cancelled_at is not None
        # Nobody did this — Stripe told us. Attributing it to a person
        # would make the audit trail lie.
        assert plan.cancelled_by_user_id is None

    def test_the_member_can_then_start_either_method_cleanly(self, db, world):
        plan = make_plan(db, world)
        fire(db, plan.id)
        for schedule in (world.upfront, world.weekly):
            out = sup.resolve_pending_setup(
                db, user=world.member, payment_option_id=world.option.id,
                requested_schedule_id=schedule.id, now=datetime.utcnow(),
            )
            assert out.kind == "none"


# ═══ 6 · expiry arrives after the member already superseded ══════════

class TestExpiryAfterSupersession:
    def test_it_is_a_no_op_and_preserves_the_original_audit(self, db, world):
        plan = make_plan(db, world)
        with patch("app.services.checkout_supersession.inspect_setup_session",
                   return_value=SetupSessionState(
                       session_id=SESSION_ID, status="expired",
                       setup_intent_id=None, setup_intent_status=None,
                       payment_method_id=None, subscription_id=None)):
            sup.resolve_pending_setup(
                db, user=world.member, payment_option_id=world.option.id,
                requested_schedule_id=world.upfront.id, now=datetime.utcnow(),
            )
        db.commit()
        db.refresh(plan)
        assert plan.cancelled_reason == rel.RELEASE_SUPERSEDED
        first_at, first_by = plan.cancelled_at, plan.cancelled_by_user_id

        fire(db, plan.id)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert plan.cancelled_reason == rel.RELEASE_SUPERSEDED, \
            "the later webhook must not overwrite who released it"
        assert (plan.cancelled_at, plan.cancelled_by_user_id) == (first_at, first_by)

    def test_a_stale_session_id_cannot_touch_the_replacement_plan(self, db, world):
        """She superseded, got a new plan and a new Session. The OLD
        Session's expiry must not cancel the new checkout."""
        old = make_plan(db, world, session_id="cs_old")
        old.status = PurchasePlanStatus.cancelled
        old.cancelled_at = datetime.utcnow()
        old.cancelled_reason = rel.RELEASE_SUPERSEDED
        new = make_plan(db, world, session_id="cs_new")
        db.commit()
        # Stripe expires the old Session, naming the NEW plan by mistake.
        fire(db, new.id, session_id="cs_old")
        db.refresh(new)
        assert new.status is PurchasePlanStatus.pending_setup


# ═══ 7 · duplicate / late / out-of-order delivery ════════════════════

class TestRedelivery:
    def test_a_second_delivery_of_the_same_event_changes_nothing(self, db, world):
        plan = make_plan(db, world)
        fire(db, plan.id)
        db.refresh(plan)
        stamp = (plan.cancelled_at, plan.cancelled_reason)
        fire(db, plan.id)
        fire(db, plan.id)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert (plan.cancelled_at, plan.cancelled_reason) == stamp

    def test_an_unknown_plan_id_is_skipped_not_raised(self, db, world):
        fire(db, "pplan_does_not_exist", session_id="cs_unknown")

    def test_missing_metadata_is_skipped_not_raised(self, db, world):
        ev = {"id": "cs_nometa", "metadata": {"purchase_type": "finite_plan_setup"}}
        handle_finite_plan_setup_expired(ev, db, ev["metadata"])

    @pytest.mark.parametrize("kw", [{"paid": 2}, {"sched_id": "sub_sched_x"}])
    def test_a_plan_carrying_something_real_is_left_alone(self, db, world, kw):
        plan = make_plan(db, world, **kw)
        fire(db, plan.id)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    @pytest.mark.parametrize("status", [
        PurchasePlanStatus.active, PurchasePlanStatus.completed,
        PurchasePlanStatus.cancelled, PurchasePlanStatus.failed,
    ])
    def test_a_plan_past_pending_setup_is_left_alone(self, db, world, status):
        plan = make_plan(db, world, status=status)
        fire(db, plan.id)
        db.refresh(plan)
        assert plan.status is status


# ═══ existing expiry behaviour for other checkout types ══════════════

class TestOtherCheckoutTypesUnaffected:
    def test_a_pending_pay_in_full_transaction_is_still_cancelled(self, db, world):
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.pending,
            payer_user_id=world.member.id, space_id=world.space.id,
            payment_option_id=world.option.id, gross_amount_cents=30600,
            currency="AUD", payout_status=PayoutStatus.pending,
            stripe_mode="test",
            provider_checkout_session_id="cs_upfront_expired",
        )
        db.add(txn); db.commit()
        _handle_checkout_expired(
            {"id": "cs_upfront_expired", "metadata": {}}, db,
        )
        db.refresh(txn)
        assert txn.status is PaymentTransactionStatus.cancelled

    def test_a_session_with_no_metadata_key_still_works(self, db, world):
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.pending,
            payer_user_id=world.member.id, space_id=world.space.id,
            payment_option_id=world.option.id, gross_amount_cents=30600,
            currency="AUD", payout_status=PayoutStatus.pending,
            stripe_mode="test",
            provider_checkout_session_id="cs_nometa_at_all",
        )
        db.add(txn); db.commit()
        _handle_checkout_expired({"id": "cs_nometa_at_all"}, db)
        db.refresh(txn)
        assert txn.status is PaymentTransactionStatus.cancelled

    def test_a_finite_plan_session_does_not_fall_through_to_txn_handling(self, db, world):
        plan = make_plan(db, world)
        _handle_checkout_expired(expiry_event(plan.id), db)
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled


# ═══ 8 · concurrency ═════════════════════════════════════════════════

class TestConcurrency:
    def test_the_advisory_lock_is_mutually_exclusive(self, db, world, engine):
        """Two requests for the same member+option cannot both hold it.

        Proven without blocking: this session takes the lock, a second
        connection asks for it with ``pg_try_...`` and must be refused,
        and a different member's key must still be free.
        """
        sup.lock_member_option(
            db, user_id=world.member.id, payment_option_id=world.option.id,
        )
        key = f"fc:checkout:{world.member.id}:{world.option.id}"
        other = f"fc:checkout:someone-else:{world.option.id}"
        with engine.connect() as conn:
            taken = conn.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:k)::bigint)"),
                {"k": key},
            ).scalar()
            free = conn.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:k)::bigint)"),
                {"k": other},
            ).scalar()
        assert taken is False, "a second request must wait, not proceed"
        assert free is True, "unrelated members must not serialise"

    def test_taking_it_twice_in_one_transaction_is_fine(self, db, world):
        for _ in range(3):
            sup.lock_member_option(
                db, user_id=world.member.id, payment_option_id=world.option.id,
            )

    def test_serialised_requests_leave_exactly_one_plan_in_flight(self, db, world):
        """What the lock buys: the second request sees the first's plan
        and supersedes it rather than adding a second agreement."""
        first = make_plan(db, world)
        with patch("app.services.checkout_supersession.inspect_setup_session",
                   return_value=SetupSessionState(
                       session_id=SESSION_ID, status="expired",
                       setup_intent_id=None, setup_intent_status=None,
                       payment_method_id=None, subscription_id=None)):
            sup.resolve_pending_setup(
                db, user=world.member, payment_option_id=world.option.id,
                requested_schedule_id=world.upfront.id, now=datetime.utcnow(),
            )
        db.commit()
        in_flight = db.execute(text("""
            SELECT count(*) FROM purchase_plans
            WHERE member_user_id = :u AND payment_option_id = :o
              AND status::text IN ('pending_setup','active','payment_problem')
        """), {"u": world.member.id, "o": world.option.id}).scalar()
        assert in_flight == 0
        db.refresh(first)
        assert first.status is PurchasePlanStatus.cancelled


# ═══ the release primitive itself ════════════════════════════════════

class TestReleasePrimitive:
    def test_it_writes_only_the_four_audit_columns(self, db, world):
        plan = make_plan(db, world)
        before = {
            c: getattr(plan, c) for c in (
                "member_user_id", "payment_option_id", "payment_option_schedule_id",
                "installments_paid", "installments_expected", "total_expected_cents",
                "provider_setup_session_id", "provider_customer_id",
                "platform_fee_basis_points", "stripe_mode",
            )
        }
        assert rel.release_abandoned_setup(
            db, plan=plan, reason=rel.RELEASE_SUPERSEDED,
            now=datetime.utcnow(), actor_user_id=world.member.id,
        ) is True
        db.commit(); db.refresh(plan)
        for col, was in before.items():
            assert getattr(plan, col) == was, f"{col} must not change"

    def test_a_second_call_is_a_no_op_and_keeps_the_first_stamps(self, db, world):
        plan = make_plan(db, world)
        rel.release_abandoned_setup(
            db, plan=plan, reason=rel.RELEASE_SUPERSEDED,
            now=datetime.utcnow(), actor_user_id=world.member.id,
        )
        db.commit()
        stamp = (plan.cancelled_at, plan.cancelled_reason, plan.cancelled_by_user_id)
        assert rel.release_abandoned_setup(
            db, plan=plan, reason=rel.RELEASE_SESSION_EXPIRED,
            now=datetime.utcnow() + timedelta(hours=1), actor_user_id=None,
        ) is False
        assert (plan.cancelled_at, plan.cancelled_reason,
                plan.cancelled_by_user_id) == stamp

    @pytest.mark.parametrize("kw,needle", [
        ({"status": PurchasePlanStatus.active}, "not pending_setup"),
        ({"paid": 1}, "instalment"),
        ({"sched_id": "sub_sched_x"}, "schedule"),
    ])
    def test_it_refuses_anything_that_might_be_real(self, db, world, kw, needle):
        plan = make_plan(db, world, **kw)
        assert needle in (rel.releasable(plan) or "")
        with pytest.raises(rel.PlanNotReleasable):
            rel.release_abandoned_setup(
                db, plan=plan, reason="x", now=datetime.utcnow(),
            )

    def test_it_does_not_commit_so_a_later_failure_rolls_it_back(self, db, world):
        plan = make_plan(db, world)
        rel.release_abandoned_setup(
            db, plan=plan, reason=rel.RELEASE_SUPERSEDED, now=datetime.utcnow(),
        )
        db.rollback()
        db.expire_all()
        assert db.get(PurchasePlan, plan.id).status is PurchasePlanStatus.pending_setup


# ═══ the orphaned plan: Stripe failed before we stored a Session id ══

class TestOrphanedPlanRelease:
    """``start_finite_plan_setup`` commits the plan and *then* calls
    Stripe. A definite failure and an uncertain timeout look identical
    from here — both raise ``stripe.StripeError`` and both leave a plan
    with no Session id — so both are handled the same way.

    Two independent routes out, because neither alone is enough:
    the member's next attempt supersedes it, and Stripe's expiry event
    releases it even if they never come back.
    """

    def test_the_expiry_event_releases_a_plan_with_no_session_id(self, db, world):
        """Stripe made the Session, the id never reached us. This event
        is the only word we will ever get about it."""
        plan = make_plan(db, world, session_id=None)
        fire(db, plan.id, session_id="cs_stripe_made_but_we_never_saw")
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.cancelled
        assert plan.cancelled_reason == rel.RELEASE_SESSION_EXPIRED

    def test_a_different_recorded_session_is_still_treated_as_stale(self, db, world):
        """The guard must stay narrow: only a NULL id falls through."""
        plan = make_plan(db, world, session_id="cs_current")
        fire(db, plan.id, session_id="cs_previous")
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup

    def test_the_member_is_never_permanently_blocked(self, db, world):
        """The property that matters: whichever happens first — a retry
        or the expiry event — the option is purchasable again."""
        # Route A: they come back and try the other method.
        orphan = make_plan(db, world, session_id=None)
        with patch("app.services.checkout_supersession.inspect_setup_session"):
            out = sup.resolve_pending_setup(
                db, user=world.member, payment_option_id=world.option.id,
                requested_schedule_id=world.upfront.id, now=datetime.utcnow(),
            )
        db.commit()
        assert out.kind == "superseded"
        db.refresh(orphan)
        assert orphan.status is PurchasePlanStatus.cancelled

        # Route B: they never come back; Stripe's event arrives instead.
        orphan2 = make_plan(db, world, session_id=None)
        fire(db, orphan2.id, session_id="cs_whatever")
        db.refresh(orphan2)
        assert orphan2.status is PurchasePlanStatus.cancelled

        # Either way nothing is left in the way.
        remaining = db.execute(text("""
            SELECT count(*) FROM purchase_plans
            WHERE member_user_id = :u AND payment_option_id = :o
              AND status::text IN ('pending_setup','active','payment_problem')
        """), {"u": world.member.id, "o": world.option.id}).scalar()
        assert remaining == 0

    def test_an_orphan_carrying_something_real_is_still_refused(self, db, world):
        """Falling through on a NULL id must not weaken the invariants."""
        plan = make_plan(db, world, session_id=None, paid=1)
        fire(db, plan.id, session_id="cs_x")
        db.refresh(plan)
        assert plan.status is PurchasePlanStatus.pending_setup
