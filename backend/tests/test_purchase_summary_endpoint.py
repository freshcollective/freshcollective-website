"""Stage 3E.3 — what did I just buy, asked safely.

A member returning from checkout lands on whichever page they started
from, and that page can only speak for itself: buying a bundle of a
Gathering and a Pathway, Sophie saw "You're in" on the Gathering and
no sign the Pathway existed.

The two things this endpoint has to get right are **whose purchase it
is** and **what is true now**. A Stripe session id is unguessable but
it is still a string in a URL — shoulder-surfed, pasted into a chat,
left in a history — so possession of the link is not ownership of the
purchase. And a refunded purchase must not keep insisting a cancelled
booking is confirmed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.checkout.routes import get_purchase_summary
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider, PaymentTransaction,
    PaymentTransactionStatus, PaymentTransactionType,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.platform import (
    BookingStatus, EntitlementStatus, Event, EventBooking, Pathway,
    PathwayEntitlement, PathwayType,
)
from app.services.purchase_fulfilment import (
    BookingIntent, EntitlementIntent, FulfilmentIntent, serialise_intent,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def space(make_space):
    return make_space()


def _pathway(db, space, *, title="New Pathway for Moonlit Circle"):
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy", currency="AUD",
    )
    db.add(p); db.flush()
    return p


def _event(db, space, *, title="Test Gathering — Payment Options", days=14):
    e = Event(
        id=_uid("ev"), space_id=space.id, created_by_id=space.creator_id,
        title=title, starts_at=datetime.utcnow() + timedelta(days=days),
        ends_at=datetime.utcnow() + timedelta(days=days, hours=2),
        is_published=True, status="active", requires_booking=True,
        capacity=5, gathering_type="circle", attendance_format="online",
        is_public=True,
    )
    db.add(e); db.flush()
    return e


def _option(db, space, *, name="Test Gathering Experience"):
    o = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published, currency="AUD", position=0,
    )
    db.add(o); db.flush()
    return o


def _purchase(
    db, space, buyer, *, option=None, pathway=None, event=None,
    session_id=None, status=PaymentTransactionStatus.succeeded,
    fulfilment=PaymentFulfilmentStatus.applied, gross=500,
):
    """A transaction carrying the snapshot the webhook wrote."""
    intent = FulfilmentIntent(
        entitlements=(
            (EntitlementIntent(
                pathway_id=pathway.id, starts_at=None, ends_at=None,
            ),) if pathway is not None else ()
        ),
        bookings=((BookingIntent(event_id=event.id),) if event else ()),
    )
    t = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=status, fulfilment_status=fulfilment,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=buyer.id, space_id=space.id, currency="AUD",
        gross_amount_cents=gross, platform_fee_basis_points=0,
        platform_fee_cents=0, net_creator_amount_cents=gross,
        payment_option_id=(option.id if option else None),
        provider_checkout_session_id=session_id or _uid("cs"),
        snapshot_grants_json=serialise_intent(intent),
    )
    db.add(t); db.flush()
    return t


def _get(db, user, session_id):
    return get_purchase_summary(
        session_id=session_id, current_user=user, db=db,
    )


# ===========================================================================
# Authorisation — the part that must not be wrong
# ===========================================================================


class TestOnlyTheBuyerCanSeeIt:
    def test_the_buyer_can(self, db, space, make_user):
        buyer = make_user()
        txn = _purchase(db, space, buyer, option=_option(db, space))
        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert out.transaction_id == txn.id

    def test_another_member_cannot(self, db, space, make_user):
        """404 rather than 403: a different status would confirm the
        purchase exists."""
        buyer = make_user()
        intruder = make_user()
        txn = _purchase(db, space, buyer, option=_option(db, space))

        with pytest.raises(HTTPException) as exc:
            _get(db, intruder, txn.provider_checkout_session_id)
        assert exc.value.status_code == 404

    def test_a_guessed_session_id_finds_nothing(self, db, space, make_user):
        with pytest.raises(HTTPException) as exc:
            _get(db, make_user(), "cs_test_guessed_value")
        assert exc.value.status_code == 404

    def test_an_unsubstituted_template_is_refused(
        self, db, space, make_user,
    ):
        """A free Option never reaches Stripe, so the placeholder comes
        back literally. It must not be looked up."""
        with pytest.raises(HTTPException) as exc:
            _get(db, make_user(), "{CHECKOUT_SESSION_ID}")
        assert exc.value.status_code == 404

    def test_an_empty_reference_is_refused(self, db, space, make_user):
        with pytest.raises(HTTPException):
            _get(db, make_user(), "")


class TestItOnlyReads:
    def test_repeated_reads_change_nothing(self, db, space, make_user):
        """Revisiting an old success URL must not grant, book or
        retry. Fulfilment belongs to the webhook."""
        buyer = make_user()
        ev = _event(db, space)
        txn = _purchase(
            db, space, buyer, option=_option(db, space), event=ev,
        )
        before_bookings = db.query(EventBooking).count()
        before_ents = db.query(PathwayEntitlement).count()

        for _ in range(3):
            _get(db, buyer, txn.provider_checkout_session_id)

        assert db.query(EventBooking).count() == before_bookings
        assert db.query(PathwayEntitlement).count() == before_ents


# ===========================================================================
# What it says
# ===========================================================================


class TestTheSummaryItself:
    def test_it_names_the_payment_option(self, db, space, make_user):
        buyer = make_user()
        txn = _purchase(
            db, space, buyer, option=_option(db, space),
        )
        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert out.option_name == "Test Gathering Experience"
        assert out.space_slug == space.slug

    def test_a_mixed_bundle_lists_both(self, db, space, make_user):
        """Sophie's purchase."""
        buyer = make_user()
        pw = _pathway(db, space)
        ev = _event(db, space)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        ))
        db.add(EventBooking(
            id=_uid("bk"), event_id=ev.id, user_id=buyer.id,
            status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
            source="payment_option",
        ))
        db.flush()
        txn = _purchase(
            db, space, buyer, option=_option(db, space),
            pathway=pw, event=ev,
        )

        out = _get(db, buyer, txn.provider_checkout_session_id)
        kinds = {i["kind"] for i in out.items}
        assert kinds == {"pathway", "gathering"}
        gathering = next(i for i in out.items if i["kind"] == "gathering")
        assert gathering["status"] == "Your place is confirmed"
        assert gathering["starts_at"] is not None

    def test_the_contents_come_from_the_purchase_not_the_option(
        self, db, space, make_user,
    ):
        """§8: a creator may edit the Payment Option afterwards. The
        member bought what they bought."""
        buyer = make_user()
        pw = _pathway(db, space, title="Bought Pathway")
        option = _option(db, space)
        txn = _purchase(db, space, buyer, option=option, pathway=pw)

        # The creator renames the Option and the Pathway afterwards.
        option.name = "Renamed Bundle"
        db.flush()

        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert [i["title"] for i in out.items] == ["Bought Pathway"]


class TestStatusesAreReadLive:
    def test_a_cancelled_booking_says_so(self, db, space, make_user):
        """§12, the specific case: Sophie's refunded purchase must not
        keep claiming her place is confirmed."""
        buyer = make_user()
        ev = _event(db, space)
        db.add(EventBooking(
            id=_uid("bk"), event_id=ev.id, user_id=buyer.id,
            status=BookingStatus.cancelled, booked_at=datetime.utcnow(),
            cancelled_at=datetime.utcnow(), source="payment_option",
        ))
        db.flush()
        txn = _purchase(
            db, space, buyer, option=_option(db, space), event=ev,
            status=PaymentTransactionStatus.refunded,
        )

        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert out.state == "refunded"
        [item] = out.items
        assert "cancelled" in item["status"].lower()
        assert "confirmed" not in item["status"].lower()

    def test_retained_pathway_access_still_reads_as_ready(
        self, db, space, make_user,
    ):
        """The other half of that refund: access survived."""
        buyer = make_user()
        pw = _pathway(db, space)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=pw.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        ))
        db.flush()
        txn = _purchase(
            db, space, buyer, option=_option(db, space), pathway=pw,
            status=PaymentTransactionStatus.refunded,
        )
        out = _get(db, buyer, txn.provider_checkout_session_id)
        [item] = out.items
        assert item["status"] == "Your access is ready"


class TestPurchaseStates:
    def test_a_pending_payment_is_not_called_fulfilled(
        self, db, space, make_user,
    ):
        buyer = make_user()
        txn = _purchase(
            db, space, buyer, option=_option(db, space),
            status=PaymentTransactionStatus.pending,
            fulfilment=PaymentFulfilmentStatus.pending,
        )
        assert _get(db, buyer, txn.provider_checkout_session_id).state == "pending"

    def test_paid_but_not_yet_applied_is_its_own_state(
        self, db, space, make_user,
    ):
        """The window between the charge and the grants landing. Saying
        "ready" here is a promise we cannot keep."""
        buyer = make_user()
        txn = _purchase(
            db, space, buyer, option=_option(db, space),
            status=PaymentTransactionStatus.succeeded,
            fulfilment=PaymentFulfilmentStatus.pending,
        )
        assert _get(db, buyer, txn.provider_checkout_session_id).state == "fulfilling"

    def test_a_failed_payment_is_not_a_purchase(
        self, db, space, make_user,
    ):
        buyer = make_user()
        txn = _purchase(
            db, space, buyer, option=_option(db, space),
            status=PaymentTransactionStatus.failed,
            fulfilment=PaymentFulfilmentStatus.pending,
        )
        assert _get(db, buyer, txn.provider_checkout_session_id).state == "failed"

    def test_a_fulfilled_purchase_says_so(self, db, space, make_user):
        buyer = make_user()
        txn = _purchase(db, space, buyer, option=_option(db, space))
        assert _get(db, buyer, txn.provider_checkout_session_id).state == "fulfilled"


class TestPaymentArrangement:
    def test_pay_in_full_reports_what_was_paid(
        self, db, space, make_user,
    ):
        buyer = make_user()
        txn = _purchase(
            db, space, buyer, option=_option(db, space), gross=8000,
        )
        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert out.payment_mode == "single"
        assert out.amount_cents == 8000
        assert out.installments_expected is None

    def test_an_instalment_purchase_reports_the_whole_plan(
        self, db, space, make_user,
    ):
        """§9: a first instalment must not read as a programme paid
        for. Every figure comes from the PurchasePlan."""
        from app.models.payment_option_schedule import PaymentOptionSchedule
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

        buyer = make_user()
        option = _option(db, space)
        sch = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id, name="Monthly",
            schedule_type="recurring_installments", status="published",
            total_amount_cents=9000, installment_amount_cents=4500,
            installment_count=2, interval="month", stripe_interval="month",
            stripe_interval_count=1, currency="AUD", position=0,
        )
        db.add(sch)
        plan = PurchasePlan(
            id=_uid("pp"), member_user_id=buyer.id,
            payment_option_id=option.id, payment_option_schedule_id=sch.id,
            space_id=space.id, creator_user_id=space.creator_id,
            status=PurchasePlanStatus.active, currency="AUD",
            installment_amount_cents=4500, installments_expected=2,
            installments_paid=1, total_expected_cents=9000,
            platform_fee_basis_points=0, payout_model="manual",
            stripe_interval="month", stripe_interval_count=1,
            stripe_mode="test",
        )
        db.add(plan); db.flush()
        txn = _purchase(db, space, buyer, option=option, gross=4500)
        txn.purchase_plan_id = plan.id
        db.flush()

        out = _get(db, buyer, txn.provider_checkout_session_id)
        assert out.payment_mode == "plan"
        assert out.amount_cents == 4500, "the instalment, not the total"
        assert out.installments_expected == 2
        assert out.installments_paid == 1
        assert out.total_expected_cents == 9000
        assert out.interval == "month"
