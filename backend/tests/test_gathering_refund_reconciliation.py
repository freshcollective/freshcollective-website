"""A fully refunded Gathering ticket gives the seat back.

The gap
-------
``charge.refunded`` reconciled the money completely and the booking not
at all. A fully refunded $45 ticket left a **confirmed** booking
holding one of eighteen places and an **active** AccessPass granting
entry to a Gathering the member had been paid back for. With ticket
sales live, the first refund request would have needed a human to
remember to release the seat by hand.

What these tests pin is mostly restraint. The easy version of this
feature — "revoke access when money comes back" — would be wrong in
several directions at once, so most of what follows checks that a
refund does *not* reach a Series pass, a Pathway entitlement, a second
ticket, a Collective membership, an attendance record, or anybody
else's booking.

The creator still decides. Nothing here initiates a refund, and
cancelling a booking never triggers one — this runs only after Stripe
has confirmed money already went back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.access_pass import (
    AccessPass,
    AccessPassEvent,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import BookingStatus, EventBooking
from app.services.gathering_refund_reconciliation import (
    CANCELLATION_NOTE,
    reconcile_fully_refunded_ticket,
)
from app.services.gathering_tickets import capacity_used
from app.webhooks.refund_handlers import handle_charge_refunded


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# A fulfilled ticket purchase: transaction + confirmed booking + pass.
# Built to match what ``fulfil_ticket_purchase`` actually leaves behind.
# ---------------------------------------------------------------------------


@pytest.fixture
def sold_ticket(db, make_user, make_space, make_event):
    def _build(
        *, price_cents: int = 4500, fee_bps: int = 800,
        txn_type=PaymentTransactionType.gathering_ticket_purchase,
        booking_status=BookingStatus.confirmed,
        with_access_pass: bool = True,
        space=None, event=None, buyer=None,
    ):
        space = space or make_space()
        event = event or make_event(
            space=space, ticket_price_cents=price_cents, capacity=18,
        )
        buyer = buyer or make_user(role="user")
        fee = round(price_cents * fee_bps / 10000)

        txn = PaymentTransaction(
            id=_uid("txn"), space_id=space.id, payer_user_id=buyer.id,
            transaction_type=txn_type,
            payment_provider=PaymentProvider.stripe,
            status=PaymentTransactionStatus.succeeded,
            gross_amount_cents=price_cents, currency="AUD",
            platform_fee_basis_points=fee_bps, platform_fee_cents=fee,
            net_creator_amount_cents=price_cents - fee,
            net_platform_amount_cents=fee,
            payout_model="manual", payout_status=PayoutStatus.pending,
            provider_charge_id=_uid("ch"),
            provider_payment_intent_id=_uid("pi"),
        )
        db.add(txn)
        db.flush()

        booking = EventBooking(
            id=_uid("bk"), event_id=event.id, user_id=buyer.id,
            status=booking_status, payment_transaction_id=txn.id,
        )
        db.add(booking)
        db.flush()

        pass_row = None
        if with_access_pass:
            pass_row = AccessPass(
                id=_uid("ap"), user_id=buyer.id, space_id=space.id,
                payment_transaction_id=txn.id,
                pass_type=AccessPassType.event_ticket,
                status=AccessPassStatus.active,
                source=AccessPassSource.one_time_purchase,
                valid_from=datetime.utcnow(),
            )
            db.add(pass_row)
            db.flush()
            db.add(AccessPassEvent(
                access_pass_id=pass_row.id, event_id=event.id,
            ))
            booking.access_pass_id = pass_row.id
            db.flush()

        return {
            "space": space, "event": event, "buyer": buyer,
            "txn": txn, "booking": booking, "pass": pass_row,
            "price_cents": price_cents,
        }

    return _build


def _charge(sale, *, amount_refunded: int, refunded: bool) -> dict:
    return {
        "id": sale["txn"].provider_charge_id,
        "amount_refunded": amount_refunded,
        "refunded": refunded,
        "payment_intent": sale["txn"].provider_payment_intent_id,
    }


def _refund(db, sale, *, amount: int, full: bool) -> None:
    handle_charge_refunded(
        _charge(sale, amount_refunded=amount, refunded=full), db,
        provider_event_id=_uid("evt"),
        event_created=None, event_livemode=False,
    )


# ---------------------------------------------------------------------------
# Scenario A — full refund
# ---------------------------------------------------------------------------


class TestAFullRefundReleasesTheSeat:
    def test_the_booking_is_cancelled(self, db, sold_ticket):
        sale = sold_ticket()
        assert sale["booking"].status == BookingStatus.confirmed

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.cancelled
        assert sale["booking"].cancelled_at is not None
        assert CANCELLATION_NOTE in (sale["booking"].note or "")

    def test_the_place_goes_back_into_capacity(self, db, sold_ticket):
        """Through the existing predicate, not a second count. A
        cancelled booking stops consuming a seat because
        ``capacity_used`` counts confirmed + pending_payment."""
        sale = sold_ticket()
        assert capacity_used(db, sale["event"].id) == 1

        _refund(db, sale, amount=4500, full=True)

        assert capacity_used(db, sale["event"].id) == 0

    def test_the_tickets_access_pass_is_cancelled(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["pass"])
        assert sale["pass"].status == AccessPassStatus.cancelled

    def test_the_financial_record_survives_intact(self, db, sold_ticket):
        """The refund is history and must stay readable: what was
        charged, what was returned, what fee was reversed."""
        sale = sold_ticket()
        _refund(db, sale, amount=4500, full=True)

        txn = sale["txn"]
        db.refresh(txn)
        assert txn.gross_amount_cents == 4500
        assert txn.refunded_amount_cents == 4500
        assert txn.status == PaymentTransactionStatus.refunded
        assert txn.platform_fee_cents == 360
        assert txn.refunded_platform_fee_cents == 360
        assert txn.refunded_creator_amount_cents == 4140
        assert txn.platform_fee_basis_points == 800
        # The payout snapshot is not re-decided by a refund.
        assert txn.payout_model == "manual"

    def test_a_pending_payment_booking_is_also_released(self, db, sold_ticket):
        """A refund against a hold that never became confirmed. Rare,
        but it must not leave a seat consumed — a ``pending_payment``
        row counts against capacity exactly like a confirmed one."""
        sale = sold_ticket(booking_status=BookingStatus.pending_payment)
        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.cancelled
        assert sale["booking"].hold_expires_at is None
        assert capacity_used(db, sale["event"].id) == 0

    def test_a_refund_with_no_booking_is_harmless(self, db, sold_ticket):
        sale = sold_ticket(with_access_pass=False)
        db.delete(sale["booking"])
        db.flush()

        _refund(db, sale, amount=4500, full=True)  # must not raise

        db.refresh(sale["txn"])
        assert sale["txn"].status == PaymentTransactionStatus.refunded


# ---------------------------------------------------------------------------
# Scenario B — partial refund
# ---------------------------------------------------------------------------


class TestAPartialRefundChangesNothingButMoney:
    """A goodwill adjustment is not a cancellation. The member is still
    coming, and their place must still be theirs."""

    def test_the_booking_stays_confirmed(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=1000, full=False)

        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.confirmed
        assert sale["booking"].cancelled_at is None
        assert CANCELLATION_NOTE not in (sale["booking"].note or "")

    def test_the_seat_stays_occupied(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=1000, full=False)
        assert capacity_used(db, sale["event"].id) == 1

    def test_access_is_preserved(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=1000, full=False)

        db.refresh(sale["pass"])
        assert sale["pass"].status == AccessPassStatus.active

    def test_the_partial_refund_is_still_recorded(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=1000, full=False)

        db.refresh(sale["txn"])
        assert sale["txn"].refunded_amount_cents == 1000
        assert sale["txn"].status == PaymentTransactionStatus.partially_refunded

    def test_a_large_partial_refund_is_still_partial(self, db, sold_ticket):
        """$44 of $45 back, Stripe still says not fully refunded. One
        cent short is short — this must not be rounded into a
        cancellation."""
        sale = sold_ticket()
        _refund(db, sale, amount=4400, full=False)

        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.confirmed
        assert capacity_used(db, sale["event"].id) == 1


# ---------------------------------------------------------------------------
# Multiple refunds adding up
# ---------------------------------------------------------------------------


class TestPartialsThatBecomeAFullRefund:
    def test_the_seat_is_released_once_the_total_is_full(self, db, sold_ticket):
        sale = sold_ticket()

        _refund(db, sale, amount=2000, full=False)
        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.confirmed
        assert capacity_used(db, sale["event"].id) == 1

        _refund(db, sale, amount=4500, full=True)
        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.cancelled
        assert capacity_used(db, sale["event"].id) == 0

    def test_the_cancellation_happens_exactly_once(self, db, sold_ticket):
        """Three partials then the completing event, then a redelivery
        of it. One cancellation, one release, one timestamp."""
        sale = sold_ticket()
        for amount in (1000, 2000, 3000):
            _refund(db, sale, amount=amount, full=False)
        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        first_cancelled_at = sale["booking"].cancelled_at
        assert first_cancelled_at is not None
        note_count = (sale["booking"].note or "").count(CANCELLATION_NOTE)
        assert note_count == 1

        _refund(db, sale, amount=4500, full=True)
        db.refresh(sale["booking"])
        assert sale["booking"].cancelled_at == first_cancelled_at
        assert (sale["booking"].note or "").count(CANCELLATION_NOTE) == 1
        assert capacity_used(db, sale["event"].id) == 0


# ---------------------------------------------------------------------------
# Scenario D — idempotency and odd arrivals
# ---------------------------------------------------------------------------


class TestItSurvivesRepeatedAndLateEvents:
    def test_a_duplicate_webhook_is_a_no_op(self, db, sold_ticket):
        sale = sold_ticket()
        _refund(db, sale, amount=4500, full=True)
        db.refresh(sale["booking"])
        stamp = sale["booking"].cancelled_at

        for _ in range(3):
            _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.cancelled
        assert sale["booking"].cancelled_at == stamp
        assert (sale["booking"].note or "").count(CANCELLATION_NOTE) == 1
        assert capacity_used(db, sale["event"].id) == 0

    def test_an_already_cancelled_booking_keeps_its_own_timestamp(
        self, db, sold_ticket,
    ):
        """A member cancelled on Monday; the refund landed on Tuesday.
        The first cancellation is the true one — overwriting it would
        rewrite history to match a webhook's arrival."""
        sale = sold_ticket()
        earlier = datetime.utcnow() - timedelta(days=1)
        sale["booking"].status = BookingStatus.cancelled
        sale["booking"].cancelled_at = earlier
        sale["booking"].note = "cancelled by the member"
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        assert sale["booking"].cancelled_at == earlier
        assert sale["booking"].note == "cancelled by the member"
        assert CANCELLATION_NOTE not in (sale["booking"].note or "")

    def test_a_refund_after_the_gathering_still_reconciles(
        self, db, sold_ticket, make_space, make_event,
    ):
        """Refunds arrive late. A past Gathering's seat is worth
        nothing, but leaving an active pass and a confirmed booking
        behind would misreport what happened."""
        space = make_space()
        past = make_event(
            space=space, ticket_price_cents=4500, capacity=18,
            starts_at=datetime.utcnow() - timedelta(days=7),
            ends_at=datetime.utcnow() - timedelta(days=7) + timedelta(hours=2),
        )
        sale = sold_ticket(space=space, event=past)

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        db.refresh(sale["pass"])
        assert sale["booking"].status == BookingStatus.cancelled
        assert sale["pass"].status == AccessPassStatus.cancelled

    def test_an_out_of_order_event_does_not_release_the_seat(
        self, db, sold_ticket,
    ):
        """The existing monotonic guard returns before anything is
        written, so a stale smaller amount cannot undo a full refund —
        nor can it cancel a seat it never fully paid back."""
        sale = sold_ticket()
        _refund(db, sale, amount=1000, full=False)
        # A late-arriving earlier event.
        _refund(db, sale, amount=500, full=False)

        db.refresh(sale["txn"])
        db.refresh(sale["booking"])
        assert sale["txn"].refunded_amount_cents == 1000
        assert sale["booking"].status == BookingStatus.confirmed

    def test_a_pass_already_cancelled_is_left_alone(self, db, sold_ticket):
        sale = sold_ticket()
        sale["pass"].status = AccessPassStatus.cancelled
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["pass"])
        assert sale["pass"].status == AccessPassStatus.cancelled

    def test_a_used_pass_is_not_resurrected_or_rewritten(
        self, db, sold_ticket,
    ):
        """``used`` is a record of entry. Only an ``active`` pass is
        cancelled, so a pass the member already redeemed keeps saying
        so."""
        sale = sold_ticket()
        sale["pass"].status = AccessPassStatus.used
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["pass"])
        assert sale["pass"].status == AccessPassStatus.used


# ---------------------------------------------------------------------------
# Access safety — the reason this is narrow
# ---------------------------------------------------------------------------


class TestItTouchesNothingElse:
    def test_only_this_gathering_is_affected(
        self, db, sold_ticket, make_space, make_event,
    ):
        """Two tickets to two Gatherings, same buyer, same Collective.
        Refunding one must not disturb the other."""
        space = make_space()
        buyer_space_event = make_event(
            space=space, ticket_price_cents=4500, capacity=18,
        )
        other_event = make_event(
            space=space, ticket_price_cents=3000, capacity=10,
        )
        refunded = sold_ticket(space=space, event=buyer_space_event)
        kept = sold_ticket(
            space=space, event=other_event, buyer=refunded["buyer"],
            price_cents=3000,
        )

        _refund(db, refunded, amount=4500, full=True)

        db.refresh(kept["booking"])
        db.refresh(kept["pass"])
        db.refresh(kept["txn"])
        assert kept["booking"].status == BookingStatus.confirmed
        assert kept["pass"].status == AccessPassStatus.active
        assert kept["txn"].status == PaymentTransactionStatus.succeeded
        assert kept["txn"].refunded_amount_cents == 0
        assert capacity_used(db, other_event.id) == 1

    def test_another_members_booking_on_the_same_gathering_is_untouched(
        self, db, sold_ticket, make_space, make_event,
    ):
        space = make_space()
        event = make_event(space=space, ticket_price_cents=4500, capacity=18)
        mine = sold_ticket(space=space, event=event)
        theirs = sold_ticket(space=space, event=event)
        assert capacity_used(db, event.id) == 2

        _refund(db, mine, amount=4500, full=True)

        db.refresh(theirs["booking"])
        assert theirs["booking"].status == BookingStatus.confirmed
        assert capacity_used(db, event.id) == 1

    def test_an_independent_series_pass_is_preserved(
        self, db, sold_ticket,
    ):
        """The member also holds a Series pass covering this Gathering.
        It was bought separately and must survive — found by payment
        transaction, never by user and event."""
        sale = sold_ticket()
        series_pass = AccessPass(
            id=_uid("ap"), user_id=sale["buyer"].id,
            space_id=sale["space"].id,
            # ``term_pass`` is the Series pass shape — a pass covering a
            # run of Gatherings, bought separately from any one ticket.
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
            valid_from=datetime.utcnow(),
        )
        db.add(series_pass)
        db.flush()
        db.add(AccessPassEvent(
            access_pass_id=series_pass.id, event_id=sale["event"].id,
        ))
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        db.refresh(series_pass)
        assert series_pass.status == AccessPassStatus.active

    def test_the_collective_membership_is_preserved(self, db, sold_ticket):
        """Buying a seat brings somebody into the Collective. Being
        refunded for one seat is not grounds for evicting them."""
        from app.models.platform import SpaceMembership

        sale = sold_ticket()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=sale["space"].id,
            user_id=sale["buyer"].id, role="learner", status="active",
        ))
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == sale["space"].id,
                SpaceMembership.user_id == sale["buyer"].id,
            )
            .first()
        )
        assert membership is not None
        assert membership.status == "active"

    def test_attendance_history_is_preserved(self, db, sold_ticket):
        """If a creator marked somebody present, they were present —
        whatever later happened to the money."""
        sale = sold_ticket()
        sale["booking"].attendance_status = "attended"
        sale["booking"].attendance_marked_at = datetime.utcnow()
        db.flush()

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        assert sale["booking"].attendance_status == "attended"
        assert sale["booking"].attendance_marked_at is not None

    @pytest.mark.parametrize(
        "txn_type",
        [
            PaymentTransactionType.member_pathway_purchase,
            PaymentTransactionType.member_series_pass_purchase,
            PaymentTransactionType.member_payment_option_purchase,
        ],
        ids=["pathway", "series_pass", "payment_option"],
    )
    def test_a_non_ticket_refund_reconciles_no_booking(
        self, db, sold_ticket, txn_type,
    ):
        """Financial refunds and access revocation are separated on
        purpose. This rule is for Gathering tickets only — a refunded
        Pathway purchase is somebody else's decision."""
        sale = sold_ticket(txn_type=txn_type)

        _refund(db, sale, amount=4500, full=True)

        db.refresh(sale["booking"])
        db.refresh(sale["pass"])
        assert sale["booking"].status == BookingStatus.confirmed
        assert sale["pass"].status == AccessPassStatus.active
        # The money still reconciled.
        db.refresh(sale["txn"])
        assert sale["txn"].status == PaymentTransactionStatus.refunded


# ---------------------------------------------------------------------------
# The service's own contract
# ---------------------------------------------------------------------------


class TestTheServiceRefusesRatherThanGuesses:
    def test_it_reports_why_it_did_nothing(self, db, sold_ticket):
        sale = sold_ticket()
        # Succeeded, not refunded.
        outcome = reconcile_fully_refunded_ticket(db, txn=sale["txn"])
        assert outcome.applied is False
        assert outcome.skipped_reason == "not_fully_refunded"

    def test_it_refuses_a_non_ticket_transaction_by_type(
        self, db, sold_ticket,
    ):
        sale = sold_ticket(txn_type=PaymentTransactionType.member_pathway_purchase)
        sale["txn"].status = PaymentTransactionStatus.refunded
        db.flush()
        outcome = reconcile_fully_refunded_ticket(db, txn=sale["txn"])
        assert outcome.skipped_reason == "not_a_gathering_ticket"

    def test_it_reports_an_already_cancelled_booking_distinctly(
        self, db, sold_ticket,
    ):
        sale = sold_ticket(booking_status=BookingStatus.cancelled)
        sale["txn"].status = PaymentTransactionStatus.refunded
        db.flush()
        outcome = reconcile_fully_refunded_ticket(db, txn=sale["txn"])
        assert outcome.applied is False
        assert outcome.skipped_reason == "booking_already_cancelled"
        assert outcome.booking_id == sale["booking"].id

    def test_it_handles_a_ticket_with_no_access_pass(self, db, sold_ticket):
        """Older rows, or a fulfilment that predates the pass. The seat
        still comes back."""
        sale = sold_ticket(with_access_pass=False)
        sale["txn"].status = PaymentTransactionStatus.refunded
        db.flush()

        outcome = reconcile_fully_refunded_ticket(db, txn=sale["txn"])
        assert outcome.applied is True
        assert outcome.access_pass_id is None
        db.refresh(sale["booking"])
        assert sale["booking"].status == BookingStatus.cancelled

    def test_it_makes_no_stripe_calls(self, db, sold_ticket):
        """Reconciliation is bookkeeping. It never asks Stripe for
        anything and never sends it anything — a refund it reacted to
        has already happened."""
        from unittest.mock import patch

        sale = sold_ticket()
        with patch("stripe.Refund.create") as create, \
             patch("stripe.Refund.retrieve") as retrieve:
            _refund(db, sale, amount=4500, full=True)
        create.assert_not_called()
        retrieve.assert_not_called()

    def test_it_never_initiates_a_refund_from_a_cancellation(self):
        """The product rule, asserted on the module: the creator
        decides. Nothing here calls into refund creation, so cancelling
        a booking can never cause money to move."""
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "gathering_refund_reconciliation.py"
        )
        tree = ast.parse(path.read_text())
        names = {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        }
        for forbidden in ("Refund", "create_refund", "refund_payment"):
            assert forbidden not in names, forbidden
        # And it imports nothing from Stripe at all.
        imported = {
            (n.module or "").lower()
            for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        } | {
            alias.name.lower()
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for alias in n.names
        }
        assert not any("stripe" in name for name in imported), imported
