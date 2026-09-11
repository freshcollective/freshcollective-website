"""Admin plan cancellation — coordinated Stripe + access + booking release.

Covers §6 of the audit sign-off:

* cancel stops Stripe SubscriptionSchedule + plan status + plan-owned
  access + future plan-dependent bookings in one operation;
* refunds remain completely separate;
* natural payment-10 completion still leaves term access active
  through the AccessPass ``valid_until`` (the cancel path is a
  separate lifecycle);
* the operation is convergent — a repeated call on an already-
  cancelled plan still finishes any incomplete access/booking/AGR
  cleanup rather than short-circuiting;
* a plan whose Stripe SubscriptionSchedule is already ``canceled``
  provider-side is safe to cancel locally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe

from app.models.access_grant_record import AccessGrantRecord
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    EntitlementSource,
    EntitlementStatus,
    Event,
    EventBooking,
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
from app.webhooks.finite_plan_handlers import _do_invoice_succeeded
from app.webhooks.refund_handlers import handle_charge_refunded


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture — plan-driven Awaken-style purchase with a Series pass,
# one future booking, one past attended booking. installments_expected=3
# (for the completion test) so the whole plan can play out quickly.
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_with_bookings(db, make_user, make_space):
    member = make_user()
    creator = make_user(role="creator")
    admin = make_user(role="admin")
    space = make_space(creator=creator)

    now = datetime.utcnow()
    series_starts = now - timedelta(days=10)
    series_ends = now + timedelta(days=60)

    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=series_starts, ends_at=series_ends,
        status="published", published_at=series_starts,
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}", title="Home Practice",
        status="active",
    )
    db.add_all([series, pathway])
    db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken", payment_type=PaymentOptionType.one_time,
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

    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=series_ends),),
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=series_starts, valid_until=series_ends,
            total_credits=10, credits_per_week=1,
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
        installments_expected=3, installments_paid=1,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=f"cus_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_schedule_id=schedule_id,
        provider_subscription_id=subscription_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=series_starts,
    )
    db.add(plan)
    db.flush()

    first_txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id, creator_user_id=creator.id,
        space_id=space.id, currency="AUD",
        gross_amount_cents=2000,
        platform_fee_basis_points=800, platform_fee_cents=160,
        net_creator_amount_cents=1840, net_platform_amount_cents=160,
        provider_invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=subscription_id,
        provider_charge_id=f"ch_test_{uuid.uuid4().hex[:8]}",
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        installment_number=1, stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=series_starts, updated_at=series_starts,
    )
    db.add(first_txn)
    db.flush()

    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id, source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=series_starts, ends_at=series_ends,
        purchase_plan_id=plan.id,
        created_at=series_starts, updated_at=series_starts,
    )
    plan_pass = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=first_txn.id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=series_starts, valid_until=series_ends,
        total_credits=10, credits_per_week=1,
        eligible_series_id=series.id, grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
        used_credits=0,
    )
    db.add_all([ent, plan_pass])
    db.flush()

    agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=first_txn.id,
        granted_at=series_starts,
    )
    agr.record_series_grant(
        db, user_id=member.id, series_id=series.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=first_txn.id,
        granted_at=series_starts,
    )

    past_event = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Past Session",
        starts_at=now - timedelta(days=3),
        ends_at=now - timedelta(days=3) + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=series.id,
        gathering_type="workshop", attendance_format="online",
    )
    future_event = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Future Session",
        starts_at=now + timedelta(days=14),
        ends_at=now + timedelta(days=14) + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=series.id,
        gathering_type="workshop", attendance_format="online",
    )
    db.add_all([past_event, future_event])
    db.flush()

    past_booking = EventBooking(
        id=_uid("b"), event_id=past_event.id, user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=now - timedelta(days=20),
        access_pass_id=plan_pass.id, credits_used=1,
        attendance_status="attended",
        attendance_marked_at=now - timedelta(days=3),
    )
    future_booking = EventBooking(
        id=_uid("b"), event_id=future_event.id, user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=now - timedelta(days=15),
        access_pass_id=plan_pass.id, credits_used=1,
    )
    db.add_all([past_booking, future_booking])
    plan_pass.used_credits = 2
    db.flush()
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, admin=admin, space=space,
        series=series, pathway=pathway,
        option=opt, schedule=sched, plan=plan,
        subscription_id=subscription_id,
        first_txn=first_txn,
        entitlement=ent, plan_pass=plan_pass,
        past_event=past_event, past_booking=past_booking,
        future_event=future_event, future_booking=future_booking,
        series_starts=series_starts, series_ends=series_ends,
    )


def _paid_invoice(*, invoice_id, subscription_id, amount=2000, currency="aud"):
    return {
        "id": invoice_id, "subscription": subscription_id,
        "total": amount, "amount_paid": amount,
        "currency": currency, "status": "paid",
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
    }


# ===========================================================================
# 6. Cancel stops Stripe + plan access + future bookings
# ===========================================================================


def test_cancel_plan_stops_stripe_access_and_future_bookings(
    db, plan_with_bookings,
):
    s = plan_with_bookings
    calls = []

    def fake_cancel(*, plan):
        calls.append(plan.id)

    with patch(
        "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        side_effect=fake_cancel,
    ):
        outcome = fpl.cancel_plan_by_admin(
            db, plan=s.plan,
            admin_user_id=s.admin.id,
            reason="member_hardship_request",
            note="Refund handled separately.",
            now=datetime.utcnow(),
        )
    db.commit()

    # Stripe cancel invoked exactly once.
    assert calls == [s.plan.id]
    # Plan transitioned + audit stamped.
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.cancelled
    assert s.plan.cancelled_at is not None
    assert s.plan.cancelled_by_user_id == s.admin.id
    assert "member_hardship_request" in (s.plan.cancelled_reason or "")
    assert "Refund handled separately" in (s.plan.cancelled_reason or "")
    # Access suspended.
    db.refresh(s.plan_pass)
    db.refresh(s.entitlement)
    assert s.plan_pass.status == AccessPassStatus.suspended
    assert s.entitlement.status == EntitlementStatus.suspended
    # Future booking cancelled + credit restored on plan pass.
    db.refresh(s.future_booking)
    assert s.future_booking.status == BookingStatus.cancelled
    assert s.plan_pass.used_credits == 1  # only the past booking counts
    # Past booking untouched.
    db.refresh(s.past_booking)
    assert s.past_booking.status == BookingStatus.confirmed
    # AGR revoked with plan_cancelled reason.
    agrs = (
        db.query(AccessGrantRecord)
        .filter(AccessGrantRecord.source_purchase_plan_id == s.plan.id)
        .all()
    )
    assert len(agrs) == 2
    for r in agrs:
        assert r.revoked_at is not None
        assert r.revoked_reason == "plan_cancelled"
    # Outcome reports the transitioning call.
    assert outcome.plan_transitioned is True
    assert s.future_booking.id in outcome.cancelled_booking_ids
    assert outcome.grant_records_revoked == 2


# ===========================================================================
# 7. Repeated cancellation is safe and does not corrupt state
# ===========================================================================


def test_repeated_cancellation_is_idempotent(db, plan_with_bookings):
    s = plan_with_bookings
    calls = []

    def fake_cancel(*, plan):
        calls.append(plan.id)

    with patch(
        "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        side_effect=fake_cancel,
    ):
        first = fpl.cancel_plan_by_admin(
            db, plan=s.plan, admin_user_id=s.admin.id,
            reason="admin_cancelled", note=None, now=datetime.utcnow(),
        )
        db.commit()
        # Capture the original audit fields
        original_cancelled_at = s.plan.cancelled_at
        original_reason = s.plan.cancelled_reason
        original_by = s.plan.cancelled_by_user_id

        # Second call — same admin, different reason. Nothing should
        # overwrite the original audit stamps; nothing double-cancelled.
        second = fpl.cancel_plan_by_admin(
            db, plan=s.plan, admin_user_id=s.admin.id,
            reason="second_call_should_be_noop",
            note="ignored", now=datetime.utcnow() + timedelta(seconds=5),
        )
        db.commit()

    # Stripe cancel called both times (helper is idempotent provider-side).
    assert calls == [s.plan.id, s.plan.id]
    # Original audit preserved.
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.cancelled
    assert s.plan.cancelled_at == original_cancelled_at
    assert s.plan.cancelled_reason == original_reason
    assert s.plan.cancelled_by_user_id == original_by
    # Second call reports plan_transitioned=False.
    assert first.plan_transitioned is True
    assert second.plan_transitioned is False
    # No duplicate booking cancellations on the second call.
    assert second.cancelled_booking_ids == []
    # No duplicate AGR revoked either.
    assert second.grant_records_revoked == 0


# ===========================================================================
# 8. Stripe already cancelled — safe (helper returns cleanly)
# ===========================================================================


def test_cancel_safe_when_stripe_schedule_already_canceled(db, plan_with_bookings):
    """Simulates the helper detecting a provider-side ``canceled`` status
    and short-circuiting. From the caller's perspective this is
    indistinguishable from a fresh cancel — no raise, downstream steps
    still run.
    """
    s = plan_with_bookings

    def fake_cancel(*, plan):
        # Helper returns cleanly for an already-canceled schedule.
        return None

    with patch(
        "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        side_effect=fake_cancel,
    ):
        outcome = fpl.cancel_plan_by_admin(
            db, plan=s.plan, admin_user_id=s.admin.id,
            reason="already_dead_provider_side", note=None,
            now=datetime.utcnow(),
        )
    db.commit()

    assert outcome.plan_transitioned is True
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.cancelled
    db.refresh(s.plan_pass)
    assert s.plan_pass.status == AccessPassStatus.suspended
    db.refresh(s.future_booking)
    assert s.future_booking.status == BookingStatus.cancelled


# ===========================================================================
# 9. Refund remains independent under cancellation
# ===========================================================================


def test_refund_after_cancel_updates_ledger_only(db, plan_with_bookings):
    s = plan_with_bookings
    charge_id = s.first_txn.provider_charge_id

    with patch(
        "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        side_effect=lambda plan: None,
    ):
        fpl.cancel_plan_by_admin(
            db, plan=s.plan, admin_user_id=s.admin.id,
            reason="refund_scenario", note=None, now=datetime.utcnow(),
        )
    db.commit()

    db.refresh(s.plan_pass)
    pass_status_before_refund = s.plan_pass.status  # suspended
    booking_status_before = s.future_booking.status
    plan_status_before = s.plan.status

    # Now the operator refunds this instalment. Handler wraps in the
    # webhook idempotency helper — commits its own transaction.
    handle_charge_refunded(
        charge={
            "id": charge_id, "amount_refunded": 2000, "refunded": True,
            "payment_intent": None,
        },
        db=db,
        provider_event_id=f"evt_test_{uuid.uuid4().hex[:12]}",
        event_created=int(datetime.utcnow().timestamp()),
        event_livemode=False,
    )
    db.commit()

    db.refresh(s.first_txn)
    db.refresh(s.plan_pass)
    db.refresh(s.plan)
    db.refresh(s.future_booking)

    # Ledger row updated.
    assert s.first_txn.refunded_amount_cents == 2000
    assert s.first_txn.status == PaymentTransactionStatus.refunded
    # Plan / access / bookings NOT changed by the refund.
    assert s.plan.status == plan_status_before
    assert s.plan_pass.status == pass_status_before_refund
    assert s.future_booking.status == booking_status_before


# ===========================================================================
# 10. Natural payment-N completion preserves term access until valid_until
# ===========================================================================


def test_natural_completion_preserves_term_access(db, plan_with_bookings):
    """Play the plan to natural completion (3 of 3). Cancel path is
    NOT invoked. AccessPass stays active, PathwayEntitlement stays
    active, and the valid_until window is respected.
    """
    s = plan_with_bookings
    # Fixture starts at installments_paid=1. Land 2 more successful
    # invoices to reach the natural end.
    inv2 = _paid_invoice(
        invoice_id=f"in_2_{uuid.uuid4().hex[:8]}",
        subscription_id=s.subscription_id,
    )
    _do_invoice_succeeded(db, invoice=inv2, event_livemode=False)
    db.commit()
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.active
    assert s.plan.installments_paid == 2

    inv3 = _paid_invoice(
        invoice_id=f"in_3_{uuid.uuid4().hex[:8]}",
        subscription_id=s.subscription_id,
    )
    _do_invoice_succeeded(db, invoice=inv3, event_livemode=False)
    db.commit()

    db.refresh(s.plan)
    db.refresh(s.plan_pass)
    db.refresh(s.entitlement)
    db.refresh(s.future_booking)

    # Plan is completed.
    assert s.plan.status == PurchasePlanStatus.completed
    assert s.plan.installments_paid == 3
    assert s.plan.completed_at is not None
    # Access is NOT suspended — valid_until (~50d from now) is honoured.
    assert s.plan_pass.status == AccessPassStatus.active
    assert s.entitlement.status == EntitlementStatus.active
    # Future booking still valid.
    assert s.future_booking.status == BookingStatus.confirmed


# ===========================================================================
# 13. Regression — convergence from INCOMPLETE prior cancellation
# ===========================================================================


def test_repeated_cancel_converges_incomplete_local_cleanup(
    db, plan_with_bookings,
):
    """Simulate a partial state: plan.status is already ``cancelled``
    (from an earlier attempt) but access + bookings + AGR were NOT
    finished. A repeated ``cancel_plan_by_admin`` MUST finish the
    cleanup, not short-circuit on the plan status check.
    """
    s = plan_with_bookings
    original_cancelled_at = datetime.utcnow() - timedelta(hours=2)
    # Force the incomplete-cleanup state directly.
    s.plan.status = PurchasePlanStatus.cancelled
    s.plan.cancelled_at = original_cancelled_at
    s.plan.cancelled_by_user_id = s.admin.id
    s.plan.cancelled_reason = "prior_partial_attempt"
    db.flush()
    db.commit()
    # Access + bookings + AGR are STILL active — mimicking an earlier
    # commit that stopped before cleanup finished.
    assert s.plan_pass.status == AccessPassStatus.active
    assert s.entitlement.status == EntitlementStatus.active
    assert s.future_booking.status == BookingStatus.confirmed
    for r in db.query(AccessGrantRecord).filter(
        AccessGrantRecord.source_purchase_plan_id == s.plan.id,
    ).all():
        assert r.revoked_at is None

    with patch(
        "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
        side_effect=lambda plan: None,
    ):
        outcome = fpl.cancel_plan_by_admin(
            db, plan=s.plan, admin_user_id=s.admin.id,
            reason="converge_the_mess", note=None,
            now=datetime.utcnow(),
        )
    db.commit()

    # Plan audit fields untouched (transition already happened earlier).
    db.refresh(s.plan)
    assert s.plan.cancelled_at == original_cancelled_at
    assert s.plan.cancelled_reason == "prior_partial_attempt"
    assert outcome.plan_transitioned is False
    # ... BUT cleanup completed:
    db.refresh(s.plan_pass)
    db.refresh(s.entitlement)
    db.refresh(s.future_booking)
    assert s.plan_pass.status == AccessPassStatus.suspended
    assert s.entitlement.status == EntitlementStatus.suspended
    assert s.future_booking.status == BookingStatus.cancelled
    for r in db.query(AccessGrantRecord).filter(
        AccessGrantRecord.source_purchase_plan_id == s.plan.id,
    ).all():
        assert r.revoked_at is not None
        assert r.revoked_reason == "plan_cancelled"
    # Outcome reflects the finished-in-this-call work.
    assert s.future_booking.id in outcome.cancelled_booking_ids
    assert outcome.grant_records_revoked == 2
