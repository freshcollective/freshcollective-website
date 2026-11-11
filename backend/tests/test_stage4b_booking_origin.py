"""Stage 4B — a place, and where it came from.

The production symptom. A member started an instalment checkout for
"Test Gathering Experience", a Payment Option bundling a Gathering and a
Pathway. That opens a seat hold, so the Gathering's booking went to
``pending_payment`` — and the *Individual ticket* card, which branches
on ``my_booking_status`` alone, showed "Payment in progress / Continue
checkout" for a purchase the member had never started. When the plan
completed, the same card read "Ticket purchased".

Neither claim was true, and the booking was never wrong: the seat is
real whichever arrangement earned it. Only its provenance was being
misreported, because one field was answering two different questions.

These tests pin the second question — *which arrangement produced this
place* — against rows written the way the real fulfilment paths write
them.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage4b_booking_origin.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider, PaymentTransaction,
    PaymentTransactionStatus, PaymentTransactionType, PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import BookingStatus, EventBooking
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.spaces import booking_origin as bo


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world(db, make_user, make_space, make_event):
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    event = make_event(space=space)
    option = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="event",
        attaches_to_id=event.id, name="Test Gathering Experience",
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
    return dict(member=member, creator=creator, space=space,
                event=event, option=option, sched=sched)


def _booking(db, world, **kw) -> EventBooking:
    row = EventBooking(
        id=_uid("bk"), event_id=world["event"].id,
        user_id=world["member"].id,
        status=kw.pop("status", BookingStatus.confirmed),
        booked_at=datetime.utcnow(),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _txn(db, world, *, txn_type, option_id=None) -> PaymentTransaction:
    row = PaymentTransaction(
        id=_uid("txn"), transaction_type=txn_type,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        space_id=world["space"].id, currency="AUD",
        gross_amount_cents=500, platform_fee_basis_points=0,
        payout_status=PayoutStatus.pending,
        payment_option_id=option_id,
    )
    db.add(row)
    db.flush()
    return row


def _plan(db, world) -> PurchasePlan:
    row = PurchasePlan(
        id=_uid("pplan"), member_user_id=world["member"].id,
        payment_option_id=world["option"].id,
        payment_option_schedule_id=world["sched"].id,
        space_id=world["space"].id, creator_user_id=world["creator"].id,
        status=PurchasePlanStatus.pending_setup, currency="AUD",
        installment_amount_cents=300, installments_expected=2,
        installments_paid=0, total_expected_cents=600,
        stripe_interval="month", stripe_interval_count=1,
    )
    db.add(row)
    db.flush()
    return row


class TestTheArrangementThatEarnedThePlace:
    def test_no_booking_has_no_origin(self, db):
        assert bo.resolve_booking_origin(db, None) is None

    def test_a_standalone_ticket_reads_as_a_direct_ticket(self, db, world):
        row = _booking(
            db, world, source="ticket_purchase",
            payment_transaction_id=_txn(
                db, world,
                txn_type=PaymentTransactionType.gathering_ticket_purchase,
            ).id,
        )
        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_DIRECT_TICKET

    def test_an_instalment_hold_reads_as_its_payment_option(self, db, world):
        """The exact production case: a seat held by a plan, before any
        payment exists. This is what was being shown as a pending
        standalone ticket purchase."""
        row = _booking(
            db, world, status=BookingStatus.pending_payment,
            source="payment_option",
            purchase_plan_id=_plan(db, world).id,
            hold_expires_at=datetime.utcnow() + timedelta(minutes=30),
        )

        origin = bo.resolve_booking_origin(db, row)
        assert origin.kind == bo.KIND_PAYMENT_OPTION
        assert origin.payment_option_id == world["option"].id
        assert origin.payment_option_name == "Test Gathering Experience"

    def test_a_completed_payment_option_purchase_names_its_option(
        self, db, world,
    ):
        row = _booking(
            db, world, source="payment_option",
            payment_transaction_id=_txn(
                db, world,
                txn_type=PaymentTransactionType.member_payment_option_purchase,
                option_id=world["option"].id,
            ).id,
        )

        origin = bo.resolve_booking_origin(db, row)
        assert origin.kind == bo.KIND_PAYMENT_OPTION
        assert origin.payment_option_name == "Test Gathering Experience"

    def test_a_series_pass_credit_reads_as_a_series_pass(self, db, world):
        # A pass-booked seat carries the pass it spent. Written
        # directly rather than through a fixture: the point is the
        # column, not how a pass comes to exist.
        from app.models.access_pass import (
            AccessPass, AccessPassStatus, AccessPassType,
        )
        ap = AccessPass(
            id=_uid("ap"), user_id=world["member"].id,
            space_id=world["space"].id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
        )
        db.add(ap)
        db.flush()
        row = _booking(db, world, source="member", access_pass_id=ap.id)

        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_SERIES_PASS

    @pytest.mark.parametrize("source", ["creator_manual", "creator_pass"])
    def test_a_caretaker_added_place_is_never_a_purchase(
        self, db, world, source,
    ):
        row = _booking(db, world, source=source)
        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_CREATOR_MANUAL

    def test_a_free_or_included_place_reads_as_other(self, db, world):
        row = _booking(db, world, source="member")
        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_OTHER


class TestRowsWrittenBeforeSourceCarriedThis:
    """``source`` is nullable and these columns are ``SET NULL`` on
    delete, so the fallback has to work rather than be decorative."""

    def test_a_plan_link_alone_still_names_the_option(self, db, world):
        row = _booking(
            db, world, source=None, purchase_plan_id=_plan(db, world).id,
        )
        origin = bo.resolve_booking_origin(db, row)
        assert origin.kind == bo.KIND_PAYMENT_OPTION
        assert origin.payment_option_id == world["option"].id

    def test_a_ticket_transaction_alone_still_reads_as_direct(
        self, db, world,
    ):
        row = _booking(
            db, world, source=None,
            payment_transaction_id=_txn(
                db, world,
                txn_type=PaymentTransactionType.gathering_ticket_purchase,
            ).id,
        )
        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_DIRECT_TICKET

    def test_an_unresolvable_row_says_other_rather_than_guessing(
        self, db, world,
    ):
        row = _booking(db, world, source=None)
        assert bo.resolve_booking_origin(db, row).kind == bo.KIND_OTHER


class TestThePayload:
    def test_only_a_payment_option_carries_option_fields(self, db, world):
        direct = bo.resolve_booking_origin(
            db, _booking(db, world, source="ticket_purchase"),
        ).as_payload()
        assert direct == {
            "kind": "direct_ticket",
            "payment_option_id": None,
            "payment_option_name": None,
        }
