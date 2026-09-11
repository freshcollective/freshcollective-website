"""Booking release semantics on finite-plan suspension.

Covers the product rules approved with the launch audit:

* grace (``payment_problem``) leaves access + bookings untouched;
* grace expiry (``suspended``) cancels every future confirmed booking
  whose ``access_pass_id`` belongs to the plan, and restores each
  booking's consumed credit on the plan pass — unconditionally,
  regardless of whether the member holds another qualifying pass.
  The earlier "preserve if overlapping access exists" branch was
  removed after the entitlement audit: keeping the booking linked
  to the (now-suspended) plan pass hid the booking from the
  alternate pass's weekly / total quota checks in ``book_event``,
  letting the member exceed their entitlement;
* past bookings are never touched by suspension;
* recovery from suspension restores access but does NOT auto-recreate
  cancelled bookings — the member may rebook subject to normal
  quota / capacity checks against whichever pass then selects.
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
from app.webhooks.finite_plan_handlers import _do_invoice_failed, _do_invoice_succeeded

from fastapi import BackgroundTasks, HTTPException
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.spaces.routes import book_event


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture — a plan-driven purchase with a Term-4-style Series pass,
# two future series events, one past attended series event, and one
# booking per event linked via ``access_pass_id`` to the plan pass.
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_with_bookings(db, make_user, make_space):
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    # Term-4-style window: series lasts 60 days from ~10 days ago so a
    # past-attended event is inside the window and future events are
    # comfortably inside it too.
    now = datetime.utcnow()
    series_starts = now - timedelta(days=10)
    series_ends = now + timedelta(days=60)

    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term 4",
        starts_at=series_starts, ends_at=series_ends,
        status="published", published_at=series_starts,
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}",
        title="EMBODY In-Person Sessions",
        status="active",
    )
    db.add_all([series, pathway])
    db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken — 1 Session per week",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly × 10", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=10,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=20000, currency="AUD",
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
            eligible_pathway_id=None,
            eligible_series_id=series.id,
            grants_pathway_id=pathway.id,
        ),),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=10,
        installments_paid=3,
        total_expected_cents=20000,
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

    # First-invoice fulfilment simulation.
    first_txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=member.id, creator_user_id=creator.id,
        space_id=space.id, currency="AUD",
        gross_amount_cents=2000,
        platform_fee_basis_points=800,
        platform_fee_cents=160,
        net_creator_amount_cents=1840,
        net_platform_amount_cents=160,
        provider_invoice_id=f"in_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=subscription_id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        installment_number=1,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=series_starts, updated_at=series_starts,
    )
    db.add(first_txn)
    db.flush()

    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=series_starts, ends_at=series_ends,
        purchase_plan_id=plan.id,
        created_at=series_starts, updated_at=series_starts,
    )
    plan_pass = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=first_txn.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=series_starts, valid_until=series_ends,
        total_credits=10, credits_per_week=1,
        eligible_series_id=series.id,
        grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
        used_credits=0,
        created_at=series_starts, updated_at=series_starts,
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

    # Three series events: one past (attended), two future.
    past_event = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Past Term-4 Session",
        starts_at=now - timedelta(days=3),
        ends_at=now - timedelta(days=3) + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=series.id,
        gathering_type="workshop", attendance_format="online",
    )
    future_event_a = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Future Term-4 Session A",
        starts_at=now + timedelta(days=14),
        ends_at=now + timedelta(days=14) + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=series.id,
        gathering_type="workshop", attendance_format="online",
    )
    future_event_b = Event(
        id=_uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Future Term-4 Session B",
        starts_at=now + timedelta(days=28),
        ends_at=now + timedelta(days=28) + timedelta(hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=series.id,
        gathering_type="workshop", attendance_format="online",
    )
    db.add_all([past_event, future_event_a, future_event_b])
    db.flush()

    past_booking = EventBooking(
        id=_uid("b"), event_id=past_event.id, user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=now - timedelta(days=20),
        access_pass_id=plan_pass.id,
        credits_used=1,
        source="member",
        attendance_status="attended",
        attendance_marked_at=now - timedelta(days=3),
    )
    booking_a = EventBooking(
        id=_uid("b"), event_id=future_event_a.id, user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=now - timedelta(days=15),
        access_pass_id=plan_pass.id,
        credits_used=1,
        source="member",
    )
    booking_b = EventBooking(
        id=_uid("b"), event_id=future_event_b.id, user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=now - timedelta(days=10),
        access_pass_id=plan_pass.id,
        credits_used=1,
        source="member",
    )
    db.add_all([past_booking, booking_a, booking_b])

    # Sync the pass counter to reflect the three bookings above.
    plan_pass.used_credits = 3
    db.flush()
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, pathway=pathway,
        option=opt, schedule=sched, plan=plan,
        subscription_id=subscription_id,
        first_txn=first_txn,
        entitlement=ent, plan_pass=plan_pass,
        past_event=past_event, past_booking=past_booking,
        future_event_a=future_event_a, booking_a=booking_a,
        future_event_b=future_event_b, booking_b=booking_b,
        series_starts=series_starts, series_ends=series_ends,
    )


def _grant_alt_pass(
    db, s, *,
    valid_from=None, valid_until=None,
    total_credits=10, credits_per_week=1,
) -> AccessPass:
    """Grant the member a second, pay-in-full AccessPass for the same
    Series. Used to test the overlap-preservation path.

    Also records an AGR row with ``source_purchase_plan_id=None`` so
    the AGR overlap check would recognise it as "another source"
    (though we're primarily testing the AccessPass-level overlap
    used by the booking-release helper).
    """
    other_txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=s.member.id, creator_user_id=s.creator.id,
        space_id=s.space.id, currency="AUD",
        gross_amount_cents=20000,
        platform_fee_basis_points=800,
        platform_fee_cents=1600,
        net_creator_amount_cents=18400,
        net_platform_amount_cents=1600,
        provider_charge_id=f"ch_test_{uuid.uuid4().hex[:8]}",
        payment_option_id=s.option.id,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(other_txn)
    db.flush()

    alt = AccessPass(
        id=_uid("ap"), user_id=s.member.id, space_id=s.space.id,
        payment_transaction_id=other_txn.id,
        payment_option_id=s.option.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=valid_from or s.series_starts,
        valid_until=valid_until or s.series_ends,
        total_credits=total_credits, credits_per_week=credits_per_week,
        eligible_series_id=s.series.id,
        grants_pathway_id=s.pathway.id,
        source=AccessPassSource.one_time_purchase,
        used_credits=0,
    )
    db.add(alt)
    db.flush()

    agr.record_pathway_grant(
        db, user_id=s.member.id, pathway_id=s.pathway.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=other_txn.id,
        granted_at=datetime.utcnow(),
    )
    agr.record_series_grant(
        db, user_id=s.member.id, series_id=s.series.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=other_txn.id,
        granted_at=datetime.utcnow(),
    )
    db.commit()
    return alt


def _fake_failed_invoice(*, invoice_id, subscription_id, amount=2000, currency="aud"):
    return {
        "id": invoice_id, "subscription": subscription_id,
        "total": amount, "amount_paid": 0,
        "currency": currency, "status": "open",
    }


def _fake_paid_invoice(*, invoice_id, subscription_id, amount=2000, currency="aud"):
    return {
        "id": invoice_id, "subscription": subscription_id,
        "total": amount, "amount_paid": amount,
        "currency": currency, "status": "paid",
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
    }


# ===========================================================================
# 1. Grace leaves bookings untouched
# ===========================================================================


def test_grace_leaves_bookings_and_access_untouched(db, plan_with_bookings):
    s = plan_with_bookings
    # Trigger the grace-opening failure via the webhook handler so we
    # exercise the full path a failed instalment would take.
    inv = _fake_failed_invoice(
        invoice_id=f"in_fail_{uuid.uuid4().hex[:8]}",
        subscription_id=s.subscription_id,
    )
    _do_invoice_failed(db, invoice=inv, event_livemode=False)
    db.commit()

    db.refresh(s.plan)
    db.refresh(s.plan_pass)
    db.refresh(s.booking_a)
    db.refresh(s.booking_b)
    db.refresh(s.past_booking)

    assert s.plan.status == PurchasePlanStatus.payment_problem
    assert s.plan.grace_expires_at is not None
    # Access + bookings unchanged during grace.
    assert s.plan_pass.status == AccessPassStatus.active
    assert s.plan_pass.used_credits == 3
    assert s.booking_a.status == BookingStatus.confirmed
    assert s.booking_b.status == BookingStatus.confirmed
    assert s.past_booking.status == BookingStatus.confirmed


# ===========================================================================
# 2. Suspension cancels future plan-dependent bookings, restores credit
# ===========================================================================


def test_suspension_cancels_future_bookings_and_restores_credit(
    db, plan_with_bookings,
):
    s = plan_with_bookings
    # Simulate grace-expired plan.
    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()

    outcome = fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()

    db.refresh(s.plan)
    db.refresh(s.plan_pass)
    db.refresh(s.booking_a)
    db.refresh(s.booking_b)
    db.refresh(s.past_booking)

    assert s.plan.status == PurchasePlanStatus.suspended
    assert s.plan_pass.status == AccessPassStatus.suspended
    # Both future bookings cancelled.
    assert s.booking_a.status == BookingStatus.cancelled
    assert s.booking_a.cancelled_at is not None
    assert s.booking_b.status == BookingStatus.cancelled
    assert s.booking_b.cancelled_at is not None
    # Two credits restored (one per cancelled booking); past booking
    # counted 1 that stays consumed. Net: 3 - 2 = 1.
    assert s.plan_pass.used_credits == 1
    # Past booking untouched.
    assert s.past_booking.status == BookingStatus.confirmed
    assert s.past_booking.cancelled_at is None
    # Outcome exposes the released bookings.
    assert set(outcome.cancelled_booking_ids) == {s.booking_a.id, s.booking_b.id}


# ===========================================================================
# 3. Past bookings untouched by suspension
# ===========================================================================


def test_past_bookings_untouched_by_suspension(db, plan_with_bookings):
    s = plan_with_bookings
    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()

    fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()

    db.refresh(s.past_booking)
    # Past booking must not be touched — attendance is history.
    assert s.past_booking.status == BookingStatus.confirmed
    assert s.past_booking.cancelled_at is None
    assert s.past_booking.attendance_status == "attended"


# ===========================================================================
# 4. Suspension always cancels plan-linked bookings, EVEN with overlapping pass
# ===========================================================================


def test_suspension_cancels_bookings_even_with_overlapping_pass(
    db, plan_with_bookings,
):
    """The overlap-preservation branch was removed after the audit —
    keeping a booking on a suspended plan pass hid it from the
    alternate pass's weekly/total quota check in ``book_event``,
    letting the member exceed their entitlement. Every future
    plan-linked booking is now cancelled unconditionally.
    """
    s = plan_with_bookings
    _grant_alt_pass(db, s)  # active pay-in-full for the same series

    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()

    outcome = fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()

    db.refresh(s.plan_pass)
    db.refresh(s.booking_a)
    db.refresh(s.booking_b)

    # Both future bookings cancelled despite the overlapping alt pass.
    assert s.booking_a.status == BookingStatus.cancelled
    assert s.booking_a.cancelled_at is not None
    assert s.booking_b.status == BookingStatus.cancelled
    # Credits restored on the plan pass (3 - 2 future bookings = 1
    # remaining, the past attended booking).
    assert s.plan_pass.used_credits == 1
    # Outcome exposes the cancelled bookings; no "preserved" concept
    # exists on the dataclass any more.
    assert set(outcome.cancelled_booking_ids) == {s.booking_a.id, s.booking_b.id}
    assert not hasattr(outcome, "preserved_booking_ids")


# ===========================================================================
# 5. Recovery restores access but does NOT recreate cancelled bookings
# ===========================================================================


def test_recovery_restores_access_but_not_cancelled_bookings(
    db, plan_with_bookings,
):
    s = plan_with_bookings
    # Suspend first.
    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()
    fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()
    db.refresh(s.plan_pass)
    assert s.plan_pass.status == AccessPassStatus.suspended
    db.refresh(s.booking_a)
    assert s.booking_a.status == BookingStatus.cancelled

    # Now recovery: a successful invoice.
    inv = _fake_paid_invoice(
        invoice_id=f"in_rec_{uuid.uuid4().hex[:8]}",
        subscription_id=s.subscription_id,
    )
    _do_invoice_succeeded(db, invoice=inv, event_livemode=False)
    db.commit()

    db.refresh(s.plan)
    db.refresh(s.plan_pass)
    db.refresh(s.booking_a)
    db.refresh(s.booking_b)

    # Plan back active, plan pass restored.
    assert s.plan.status == PurchasePlanStatus.active
    assert s.plan_pass.status == AccessPassStatus.active
    # Bookings still cancelled — no auto-recreate.
    assert s.booking_a.status == BookingStatus.cancelled
    assert s.booking_b.status == BookingStatus.cancelled
    # Credits are back to 1 (past booking only) — restoration happened
    # at suspension and recovery does not consume them again.
    assert s.plan_pass.used_credits == 1


# ===========================================================================
# 11. Regression — exhausted alternate pass gets NO quota bypass
# ===========================================================================


def _grant_membership(db, s) -> SpaceMembership:
    """Real SpaceMembership so ``book_event`` accepts the caller."""
    membership = SpaceMembership(
        id=_uid("sm"), user_id=s.member.id, space_id=s.space.id,
        status=SpaceMembershipStatus.active,
        role="learner", source="purchase",
    )
    db.add(membership)
    db.flush()
    db.commit()
    return membership


def _rebook(db, s, event) -> object:
    """Call the real ``book_event`` route function directly. Requires
    an active SpaceMembership. Returns the response or raises HTTPException.
    """
    return book_event(
        slug=s.space.slug, event_id=event.id,
        background_tasks=BackgroundTasks(),
        db=db, current_user=s.member,
    )


def test_exhausted_alternate_pass_cancels_and_blocks_rebooking(db, plan_with_bookings):
    """Alternate pass is active + covers the event date, but has ZERO
    remaining credits AND its weekly cap is already met (via a
    pre-existing booking on a separate same-week event). Suspension
    still cancels the plan booking; a fresh rebooking attempt via
    the real ``book_event`` route is refused for quota, proving the
    alternate pass's accounting stays honest.
    """
    s = plan_with_bookings
    _grant_membership(db, s)
    now = datetime.utcnow()

    # Alternate pass at total-cap: 1 total / 1 used, 1 per week / 1 used.
    alt = _grant_alt_pass(db, s, total_credits=1, credits_per_week=1)
    # Consume the alt pass with a booking on some OTHER series event so
    # ``used_credits`` and the per-week bucket are genuinely at the cap.
    other_event = Event(
        id=_uid("e"), space_id=s.space.id, created_by_id=s.creator.id,
        title="Other same-week session",
        starts_at=s.future_event_a.starts_at + timedelta(days=1),
        ends_at=s.future_event_a.starts_at + timedelta(days=1, hours=1),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=10,
        booking_access_type="included_with_series",
        series_id=s.series.id,
        gathering_type="workshop", attendance_format="online",
    )
    db.add(other_event)
    db.flush()
    consumer_booking = EventBooking(
        id=_uid("b"), event_id=other_event.id, user_id=s.member.id,
        status=BookingStatus.confirmed,
        booked_at=now, access_pass_id=alt.id, credits_used=1,
    )
    db.add(consumer_booking)
    alt.used_credits = 1
    db.flush()
    db.commit()

    # Suspend the plan.
    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()
    outcome = fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()

    db.refresh(s.booking_a)
    db.refresh(s.plan_pass)
    db.refresh(alt)

    # Plan booking cancelled + credit restored on the plan pass.
    assert s.booking_a.status == BookingStatus.cancelled
    assert s.plan_pass.used_credits == 1  # only the past-attended booking
    # Alternate pass counters unchanged by the release path.
    assert alt.used_credits == 1
    assert set(outcome.cancelled_booking_ids) >= {s.booking_a.id, s.booking_b.id}

    # Fresh rebooking attempt via the real route: alt pass is selected
    # (only active candidate) and refused for quota — proving quota
    # accounting is honest, no phantom "preserved" booking hid credits.
    with pytest.raises(HTTPException) as exc:
        _rebook(db, s, s.future_event_a)
    assert exc.value.status_code == 409
    # Reason may cite total or weekly — both are legitimate quota rejections.
    assert "session" in exc.value.detail or "limit" in exc.value.detail


# ===========================================================================
# 12. Regression — rebooking via alternate pass with headroom works
# ===========================================================================


def test_rebooking_via_alternate_pass_consumes_alt_credit(db, plan_with_bookings):
    """After suspension cancels the plan booking, the member calls
    the real ``book_event`` route. The alternate pass is selected,
    exactly one of its credits is consumed, and the cancelled
    plan-linked booking row is re-activated with the new
    ``access_pass_id`` pointing at the alternate — proving normal
    booking flow re-authorises correctly against the surviving pass.
    """
    s = plan_with_bookings
    _grant_membership(db, s)
    alt = _grant_alt_pass(db, s, total_credits=10, credits_per_week=1)
    assert alt.used_credits == 0

    # Suspend the plan (cancels s.booking_a and s.booking_b, restores
    # 2 credits on the plan pass).
    s.plan.status = PurchasePlanStatus.payment_problem
    s.plan.grace_expires_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()
    db.commit()
    fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()

    db.refresh(s.booking_a)
    db.refresh(s.plan_pass)
    assert s.booking_a.status == BookingStatus.cancelled
    plan_used_after_suspend = s.plan_pass.used_credits

    # Rebook the same event via the real route. book_event finds the
    # cancelled row and reactivates it with the new access_pass_id.
    resp = _rebook(db, s, s.future_event_a)
    db.commit()
    assert resp.status == "confirmed"

    db.refresh(s.booking_a)
    db.refresh(alt)
    db.refresh(s.plan_pass)

    # The rebooking row is now anchored to the alternate pass, exactly
    # one alt credit consumed, and the plan pass counter is untouched
    # by this booking (proving quota accounting is honest and no
    # double-counting occurred).
    assert s.booking_a.status == BookingStatus.confirmed
    assert s.booking_a.access_pass_id == alt.id
    assert s.booking_a.credits_used == 1
    assert alt.used_credits == 1
    assert s.plan_pass.used_credits == plan_used_after_suspend
