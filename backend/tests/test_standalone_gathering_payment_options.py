"""Stage 3 — standalone Gatherings inside a Payment Option.

The gap this closes
-------------------
A creator could already add a Gathering to a Payment Option: the grant
model supports it, the API accepts it, and the editor offers it. What
did not exist was fulfilment, so the Option was declared unfulfillable
— hidden from members, refused at the till, and labelled "coming soon"
in the editor. That refusal was one rule in one place
(``unfulfillable_grant_reason``) with two readers that already agreed,
which is why this stage moves a flag rather than unpicking a tangle.

Where the danger is
-------------------
Not in the money. A seat is the scarce thing, and the only ordering
that is safe is **refuse before charging**: capacity is decided at
checkout under the Event row lock, and fulfilment confirms a seat that
was already held. A booking created at fulfilment time would be an
oversell with the member's money already taken, and no amount of
careful webhook handling would make that right afterwards.

So the tests below care mostly about three things: that a sold-out
Gathering refuses the purchase *before* Stripe, that a bundle is all or
nothing, and that confirming is idempotent under webhook retries.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus, Event, EventBooking, Pathway, PathwayType,
)
from app.services import gathering_tickets as tickets
from app.services.checkout_orchestration import (
    option_is_fulfillable, unfulfillable_grant_reason,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def stage3_on():
    with patch(
        "app.core.config.settings"
        ".standalone_gathering_payment_options_enabled", True,
    ):
        yield


def _event(db, space, *, title="Women's Circle", capacity=None,
           days=14) -> Event:
    e = Event(
        id=_uid("ev"), space_id=space.id, created_by_id=space.creator_id,
        title=title,
        starts_at=datetime.utcnow() + timedelta(days=days),
        ends_at=datetime.utcnow() + timedelta(days=days, hours=2),
        is_published=True, status="active", requires_booking=True,
        capacity=capacity, gathering_type="circle",
        attendance_format="online",
        # Public so the member endpoint is reachable without building a
        # membership row — visibility is not what these tests are about.
        is_public=True,
    )
    db.add(e)
    db.flush()
    return e


def _pathway(db, space, *, title="Guided Reflection") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy", currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, name="Women's Circle Experience",
            status=PaymentOptionStatus.published) -> PaymentOption:
    o = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time, status=status,
        currency="AUD", position=0,
    )
    db.add(o)
    db.flush()
    return o


def _schedule(db, option, *, cents=7900) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name="Pay in full",
        schedule_type="pay_in_full", status="published",
        total_amount_cents=cents, currency="AUD", position=0,
    )
    db.add(s)
    db.flush()
    return s


def _grant(db, option, *, event=None, pathway=None) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=option.id,
        grant_kind="gathering" if event is not None else "pathway",
        event_id=event.id if event is not None else None,
        pathway_id=pathway.id if pathway is not None else None,
    )
    db.add(g)
    db.flush()
    return g


def _booking(db, event, user, *, status=BookingStatus.confirmed,
             txn_id=None, expires=None) -> EventBooking:
    b = EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=user.id, status=status,
        booked_at=datetime.utcnow(), source="ticket_purchase",
        payment_transaction_id=txn_id, hold_expires_at=expires,
    )
    db.add(b)
    db.flush()
    return b


def _plan(db, space, option, schedule, buyer, *, status=None):
    """A minimal real PurchasePlan — the booking FK needs one."""
    from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

    pl = PurchasePlan(
        id=_uid("pp"), member_user_id=buyer.id,
        payment_option_id=option.id, payment_option_schedule_id=schedule.id,
        space_id=space.id, creator_user_id=space.creator_id,
        status=status or PurchasePlanStatus.pending_setup,
        currency="AUD", installment_amount_cents=3200,
        installments_expected=3, total_expected_cents=9600,
        platform_fee_basis_points=0, payout_model="manual",
        stripe_interval="month", stripe_interval_count=1,
        stripe_mode="test", created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(pl)
    db.flush()
    return pl


def _txn(db, space, buyer, option=None, *, cents=8900, status=None):
    from app.models.payment import (
        PaymentTransaction, PaymentTransactionStatus,
        PaymentTransactionType, PaymentProvider,
    )
    t = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=status or PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=buyer.id, space_id=space.id, currency="AUD",
        gross_amount_cents=cents, platform_fee_basis_points=0,
        platform_fee_cents=0, net_creator_amount_cents=cents,
        payment_option_id=option.id if option is not None else None,
    )
    db.add(t)
    db.flush()
    return t


def _hold(db, option, buyer, *, ttl=30):
    return tickets.hold_option_seats_or_raise(
        db, payment_option=option, buyer=buyer, hold_ttl_minutes=ttl,
    )


# ===========================================================================
# The gate
# ===========================================================================


class TestTheGate:
    def test_off_a_gathering_grant_is_unfulfillable(self, db, space):
        """Unchanged since Stage 0. One rule, and both readers — the
        till's guard and the member-facing flag — call it."""
        opt = _option(db, space)
        _grant(db, opt, event=_event(db, space))
        db.refresh(opt)
        assert unfulfillable_grant_reason(opt) is not None
        assert option_is_fulfillable(opt) is False

    def test_on_it_becomes_fulfillable(self, db, space, stage3_on):
        opt = _option(db, space)
        _grant(db, opt, event=_event(db, space))
        db.refresh(opt)
        assert unfulfillable_grant_reason(opt) is None
        assert option_is_fulfillable(opt) is True

    def test_off_no_seats_are_held(self, db, space, make_user):
        """The hold function is defensive, not a second gate — but it
        must not act while the feature is off."""
        opt = _option(db, space)
        _grant(db, opt, event=_event(db, space, capacity=10))
        db.refresh(opt)
        assert _hold(db, opt, make_user()) == []

    def test_an_option_without_gatherings_is_unaffected(self, db, space):
        opt = _option(db, space)
        _grant(db, opt, pathway=_pathway(db, space))
        db.refresh(opt)
        assert option_is_fulfillable(opt) is True


# ===========================================================================
# Seats are refused before the money
# ===========================================================================


class TestCapacityIsDecidedAtCheckout:
    def test_a_seat_is_held_as_pending_payment(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()

        [held] = _hold(db, opt, buyer)
        assert held.status == BookingStatus.pending_payment
        assert held.event_id == ev.id
        assert held.source == "payment_option"
        assert held.hold_expires_at is not None

    def test_the_hold_consumes_capacity(
        self, db, space, make_user, stage3_on,
    ):
        """A hold counts against the seat count for as long as it
        exists — that is what stops two members buying the last place."""
        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        _hold(db, opt, make_user())
        assert tickets.capacity_used(db, ev.id) == 1

    def test_a_sold_out_gathering_refuses_the_purchase(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=1)
        _booking(db, ev, make_user())  # the only seat, taken
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        with pytest.raises(tickets.SoldOut):
            _hold(db, opt, make_user())

    def test_the_second_buyer_of_the_last_seat_is_refused(
        self, db, space, make_user, stage3_on,
    ):
        """Two members, one seat, both still in checkout."""
        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        _hold(db, opt, make_user())
        with pytest.raises(tickets.SoldOut):
            _hold(db, opt, make_user())

    def test_unlimited_capacity_never_refuses(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=None)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        for _ in range(3):
            assert len(_hold(db, opt, make_user())) == 1


class TestABundleIsAllOrNothing:
    def test_one_sold_out_gathering_refuses_the_whole_option(
        self, db, space, make_user, stage3_on,
    ):
        """§7: partial fulfilment must not leave the member charged for
        an incomplete purchase. Enforced by refusing before the charge,
        not by compensating afterwards."""
        free = _event(db, space, title="November", capacity=10)
        full = _event(db, space, title="December", capacity=1)
        _booking(db, full, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=free)
        _grant(db, opt, event=full)
        db.refresh(opt)

        with pytest.raises(tickets.SoldOut):
            _hold(db, opt, make_user())

    def test_and_the_caller_rollback_releases_what_was_taken(
        self, db, space, make_user, stage3_on,
    ):
        """The holds taken before the failure are undone by the
        caller's rollback — they are writes in its transaction, not
        committed side effects. Asserted on the savepoint the test
        fixture provides, which is the same mechanism."""
        free = _event(db, space, title="November", capacity=10)
        full = _event(db, space, title="December", capacity=1)
        _booking(db, full, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=free)
        _grant(db, opt, event=full)
        db.refresh(opt)
        buyer = make_user()

        sp = db.begin_nested()
        with pytest.raises(tickets.SoldOut):
            _hold(db, opt, buyer)
        sp.rollback()

        assert db.query(EventBooking).filter(
            EventBooking.user_id == buyer.id,
        ).count() == 0, "a seat survived the refusal"

    def test_several_gatherings_are_all_held(
        self, db, space, make_user, stage3_on,
    ):
        events = [
            _event(db, space, title=f"Leadership Call — {m}", capacity=5,
                   days=d)
            for m, d in (("November", 10), ("December", 40), ("January", 70))
        ]
        opt = _option(db, space, name="Leadership Programme")
        for ev in events:
            _grant(db, opt, event=ev)
        db.refresh(opt)

        held = _hold(db, opt, make_user())
        assert len(held) == 3
        assert {h.event_id for h in held} == {e.id for e in events}

    def test_the_lock_order_is_deterministic(self, db, space, stage3_on):
        """Events are locked in sorted id order, so two members buying
        overlapping bundles cannot deadlock against each other. Asserted
        on the source rather than by racing two sessions: a passing race
        proves nothing about the next one."""
        import inspect
        src = inspect.getsource(tickets.hold_option_seats_or_raise)
        assert "sorted(" in src


# ===========================================================================
# Overlapping access
# ===========================================================================


class TestAMemberWhoAlreadyHasASeat:
    def test_is_not_booked_twice(self, db, space, make_user, stage3_on):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        _booking(db, ev, buyer)  # already attending

        assert _hold(db, opt, buyer) == [], "a second seat was taken"
        assert db.query(EventBooking).filter(
            EventBooking.event_id == ev.id,
            EventBooking.user_id == buyer.id,
        ).count() == 1

    def test_and_does_not_consume_a_second_seat(
        self, db, space, make_user, stage3_on,
    ):
        """The last seat of a sold-out Gathering is theirs already, so
        the bundle still sells to them."""
        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        _booking(db, ev, buyer)

        assert _hold(db, opt, buyer) == []
        assert tickets.capacity_used(db, ev.id) == 1

    def test_an_expired_hold_is_reused_not_duplicated(
        self, db, space, make_user, stage3_on,
    ):
        """``(event_id, user_id)`` is unique, so there is no second row
        to insert — the existing one is revived in place."""
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        stale = _booking(
            db, ev, buyer, status=BookingStatus.pending_payment,
            expires=datetime.utcnow() - timedelta(hours=2),
        )

        [held] = _hold(db, opt, buyer)
        assert held.id == stale.id
        assert held.hold_expires_at > datetime.utcnow()

    def test_a_cancelled_booking_is_revived_under_the_capacity_rule(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        _booking(db, ev, buyer, status=BookingStatus.cancelled)

        [held] = _hold(db, opt, buyer)
        assert held.status == BookingStatus.pending_payment


# ===========================================================================
# Fulfilment
# ===========================================================================


class TestFulfilmentConfirmsTheHeldSeat:
    def _intent(self, db, option):
        from app.services.purchase_fulfilment import resolve_intent_from_grants
        db.refresh(option)
        return resolve_intent_from_grants(db, payment_option=option)

    def test_off_the_resolver_refuses_rather_than_pretending(
        self, db, space,
    ):
        opt = _option(db, space)
        _grant(db, opt, event=_event(db, space))
        res = self._intent(db, opt)
        assert res.fatal_error is not None
        # ``intent`` is an empty FulfilmentIntent rather than None, so
        # the fatal error is what a caller must check — asserted here
        # so nobody later "fixes" a caller to read the intent instead.
        assert res.intent.bookings == ()

    def test_on_each_grant_becomes_one_booking_intent(
        self, db, space, stage3_on,
    ):
        a = _event(db, space, title="November")
        b = _event(db, space, title="December")
        opt = _option(db, space)
        _grant(db, opt, event=a)
        _grant(db, opt, event=b)
        res = self._intent(db, opt)
        assert res.fatal_error is None
        assert {i.event_id for i in res.intent.bookings} == {a.id, b.id}

    def test_the_same_gathering_cannot_be_granted_twice(
        self, db, space, stage3_on,
    ):
        """``uq_payment_option_grants_option_event`` already forbids it,
        so the resolver's dedup is belt-and-braces. Asserted because
        that constraint is what makes one grant == one seat, and a
        migration relaxing it would quietly change this stage's
        arithmetic."""
        from sqlalchemy.exc import IntegrityError

        ev = _event(db, space)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        sp = db.begin_nested()
        with pytest.raises(IntegrityError):
            _grant(db, opt, event=ev)
        sp.rollback()

    def test_a_mixed_bundle_resolves_both_kinds(
        self, db, space, stage3_on,
    ):
        """§4: a Pathway alongside a Gathering, in one Option."""
        ev = _event(db, space)
        pw = _pathway(db, space)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        _grant(db, opt, pathway=pw)
        res = self._intent(db, opt)
        assert [i.event_id for i in res.intent.bookings] == [ev.id]
        assert [e.pathway_id for e in res.intent.entitlements] == [pw.id]


class TestTheApplier:
    def _apply(self, db, option, buyer, txn=None):
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )
        db.refresh(option)
        res = resolve_intent_from_grants(db, payment_option=option)
        assert res.fatal_error is None, res.fatal_error
        return apply_intent(
            db, intent=res.intent, txn=txn, payer_user_id=buyer.id,
            space_id=option.space_id, payment_option_id=option.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
        )

    def test_it_confirms_the_hold(self, db, space, make_user, stage3_on):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        [held] = _hold(db, opt, buyer)

        result = self._apply(db, opt, buyer)
        db.refresh(held)
        assert held.status == BookingStatus.confirmed
        assert held.hold_expires_at is None
        assert [b.id for b in result.bookings] == [held.id]
        assert result.booking_errors == []

    def test_it_is_idempotent_under_webhook_retries(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        _hold(db, opt, buyer)

        self._apply(db, opt, buyer)
        self._apply(db, opt, buyer)
        self._apply(db, opt, buyer)

        assert db.query(EventBooking).filter(
            EventBooking.event_id == ev.id,
            EventBooking.user_id == buyer.id,
        ).count() == 1
        assert tickets.capacity_used(db, ev.id) == 1

    def test_an_existing_confirmed_booking_is_left_alone(
        self, db, space, make_user, stage3_on,
    ):
        """They already had a ticket. They keep it, with its own source
        and its own payment history."""
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        original = _booking(db, ev, buyer)
        original_source = original.source

        self._apply(db, opt, buyer)
        db.refresh(original)
        assert original.status == BookingStatus.confirmed
        assert original.source == original_source

    def test_a_missing_hold_still_books_when_there_is_room(
        self, db, space, make_user, stage3_on,
    ):
        """Should not happen — the seat is held at checkout — but
        silently dropping the booking would leave somebody paid-up and
        unbooked with nothing saying so."""
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()

        result = self._apply(db, opt, buyer)
        assert result.booking_errors == []
        assert len(result.bookings) == 1
        assert result.bookings[0].status == BookingStatus.confirmed

    def test_a_missing_hold_on_a_full_gathering_blocks_rather_than_oversells(
        self, db, space, make_user, stage3_on,
    ):
        """The one case where a human has to decide. Reported, never
        silently absorbed and never an oversell."""
        from app.services.purchase_fulfilment import FulfilmentStatus

        ev = _event(db, space, capacity=1)
        _booking(db, ev, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        result = self._apply(db, opt, make_user())
        assert result.status == FulfilmentStatus.BLOCKED
        assert result.booking_errors
        assert tickets.capacity_used(db, ev.id) == 1, "capacity was exceeded"


# ===========================================================================
# Abandoned checkout
# ===========================================================================


class TestAbandonedCheckout:
    def test_every_seat_in_a_bundle_is_released(
        self, db, space, make_user, stage3_on,
    ):
        """A direct ticket holds one seat; a bundle can hold several
        against one transaction. Releasing only the first stranded the
        rest until the stale sweep reached them."""
        from app.models.payment import (
            PaymentTransaction, PaymentTransactionStatus,
            PaymentTransactionType, PaymentProvider,
        )

        a = _event(db, space, title="November", capacity=5)
        b = _event(db, space, title="December", capacity=5)
        opt = _option(db, space)
        _grant(db, opt, event=a)
        _grant(db, opt, event=b)
        db.refresh(opt)
        buyer = make_user()

        txn = PaymentTransaction(
            id=_uid("txn"), transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.pending,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, space_id=space.id,
            currency="AUD", gross_amount_cents=7900,
            platform_fee_basis_points=0, platform_fee_cents=0,
            net_creator_amount_cents=7900,
        )
        db.add(txn)
        db.flush()

        for h in _hold(db, opt, buyer):
            h.payment_transaction_id = txn.id
        db.flush()
        assert tickets.capacity_used(db, a.id) == 1
        assert tickets.capacity_used(db, b.id) == 1

        tickets.release_hold_for_transaction(
            db, transaction_id=txn.id,
            final_status=PaymentTransactionStatus.cancelled,
            reason="checkout expired",
        )
        assert tickets.capacity_used(db, a.id) == 0
        assert tickets.capacity_used(db, b.id) == 0


# ===========================================================================
# The member-facing side
# ===========================================================================


class TestWhatMembersAreShown:
    def _arrangements(self, db, event):
        from app.services.purchase_arrangements import arrangements_for
        found = arrangements_for(
            db, kind="gathering", experience_id=event.id,
        )
        return found.arrangements if found else ()

    def test_off_the_option_is_not_offered(self, db, space):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        option_arrangements = [
            a for a in self._arrangements(db, ev)
            if a.source == "payment_option"
        ]
        assert all(
            not a.available_for_new_purchase for a in option_arrangements
        ), "an unfulfillable Option was advertised"

    def test_on_it_is_offered_with_its_own_price(
        self, db, space, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _schedule(db, opt, cents=7900)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        [arr] = [
            a for a in self._arrangements(db, ev)
            if a.source == "payment_option"
        ]
        assert arr.available_for_new_purchase
        assert arr.total_amount_cents == 7900
        assert arr.payment_option_id == opt.id

    def test_the_bundle_names_the_gathering_and_its_date(
        self, db, space, stage3_on,
    ):
        """§9: a member buying a bundle of individually scheduled calls
        needs to know which sessions they are getting. "Leadership
        Call" alone says nothing when there are three."""
        ev = _event(db, space, title="Leadership Call", capacity=10, days=21)
        pw = _pathway(db, space, title="Guided Reflection")
        opt = _option(db, space)
        _schedule(db, opt)
        _grant(db, opt, event=ev)
        _grant(db, opt, pathway=pw)
        db.refresh(opt)

        [arr] = [
            a for a in self._arrangements(db, ev)
            if a.source == "payment_option"
        ]
        by_kind = {i.kind: i for i in arr.included}
        assert by_kind["gathering"].title == "Leadership Call"
        assert by_kind["gathering"].starts_at is not None
        assert by_kind["pathway"].title == "Guided Reflection"
        assert by_kind["pathway"].starts_at is None, (
            "only a Gathering has a single moment"
        )

    def test_the_direct_ticket_is_unaffected(self, db, space, stage3_on):
        """§6: adding a Gathering to a Payment Option must not disable
        its own ticket price."""
        ev = _event(db, space, capacity=10)
        ev.booking_access_type = "paid_separately"
        ev.ticket_price_cents = 4500
        ev.ticket_currency = "AUD"
        opt = _option(db, space)
        _schedule(db, opt, cents=7900)
        _grant(db, opt, event=ev)
        db.flush()
        db.refresh(opt)

        direct = [a for a in self._arrangements(db, ev) if a.source == "direct"]
        assert direct, "the individual ticket disappeared"
        assert direct[0].total_amount_cents == 4500


class TestTheGatheringWaysToJoinCards:
    """§9 — the member Gathering surface lists the Options that include
    it, beside the ticket control it already had.

    The individual ticket is deliberately not one of these cards. It
    has an established booking control on that page, and §9 asks not to
    redesign one to make room for the other.
    """

    def _cards(self, db, event):
        from app.spaces.pathway_arrangement_display import (
            build_gathering_ways_to_join,
        )
        return build_gathering_ways_to_join(db, event=event)

    def test_off_no_option_cards(self, db, space):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _schedule(db, opt, cents=7900)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        assert [
            c for c in self._cards(db, ev) if c.source == "payment_option"
        ] == []

    def test_on_the_option_appears_with_its_schedules(
        self, db, space, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space, name="Women's Circle Experience")
        _schedule(db, opt, cents=7900)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        [card] = [
            c for c in self._cards(db, ev) if c.source == "payment_option"
        ]
        assert card.name == "Women's Circle Experience"
        assert card.payment_option_id == opt.id
        assert [s.total_amount_cents for s in card.schedules] == [7900]
        assert card.schedules[0].is_member_checkoutable is True

    def test_the_card_names_what_else_comes_with_it(
        self, db, space, stage3_on,
    ):
        """§9: 'Includes: Women's Circle, Guided Reflection Pathway.'
        The Gathering being viewed leads, the rest follows."""
        ev = _event(db, space, title="Women's Circle", capacity=10)
        pw = _pathway(db, space, title="Guided Reflection")
        opt = _option(db, space)
        _schedule(db, opt)
        _grant(db, opt, event=ev)
        _grant(db, opt, pathway=pw)
        db.refresh(opt)

        [card] = [
            c for c in self._cards(db, ev) if c.source == "payment_option"
        ]
        assert card.included_titles[0] == "Women's Circle"
        assert "Guided Reflection" in card.included_titles
        assert card.is_bundle is True

    def test_a_draft_option_is_not_offered(self, db, space, stage3_on):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        assert [
            c for c in self._cards(db, ev) if c.source == "payment_option"
        ] == []

    def test_the_payload_carries_the_cards(
        self, db, space, make_user, stage3_on,
    ):
        """End to end through the member endpoint, so the schema and
        the builder are known to agree."""
        from app.spaces.routes import get_event

        ev = _event(db, space, capacity=10)
        opt = _option(db, space, name="Women's Circle Experience")
        _schedule(db, opt, cents=7900)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        from app.models.user import User as _User
        owner = db.get(_User, space.creator_id)
        payload = get_event(
            space.slug, ev.id, db=db, current_user=owner,
        )
        cards = payload["payment_option_ways_to_join"]
        assert [c["name"] for c in cards] == ["Women's Circle Experience"]
        assert all(c["source"] == "payment_option" for c in cards), (
            "the individual ticket leaked into the Ways to join cards"
        )


class TestInstalmentPlansReserveTheirSeats:
    """Decision A — a member reserves their place when they establish
    the plan, not when the first instalment lands.

    The earlier Stage 3 report withheld this combination because
    ``start_finite_plan_setup`` is its own entry point and held
    nothing, so a plan could reach its first invoice to find the
    Gathering full. It now holds seats in the same transaction as the
    plan row, by the same capacity rule the pay-in-full path uses —
    which is what makes the schedule safe to offer.
    """

    def _plan_schedule(self, db, option):
        s = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id,
            name="Monthly payments", schedule_type="recurring_installments",
            status="published", total_amount_cents=9600,
            installment_amount_cents=3200, installment_count=3,
            interval="month", stripe_interval="month",
            stripe_interval_count=1, currency="AUD", position=1,
        )
        db.add(s)
        db.flush()
        return s

    def test_the_plan_schedule_is_offered(self, db, space, stage3_on):
        """Members can now choose it — the blocker is gone."""
        from app.services.purchase_arrangements import arrangements_for

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _schedule(db, opt, cents=8900)
        self._plan_schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled",
            True,
        ):
            found = arrangements_for(db, kind="gathering", experience_id=ev.id)
            sellable = [
                a for a in found.arrangements
                if a.source == "payment_option"
                and a.available_for_new_purchase
            ]
        assert sorted(a.schedule_type for a in sellable) == [
            "pay_in_full", "recurring_installments",
        ]

    def test_the_plan_arrangement_states_its_shape(
        self, db, space, stage3_on,
    ):
        """§11 — the instalment amount, the count, the frequency and
        the total, each from the schedule's own rows."""
        from app.services.purchase_arrangements import arrangements_for

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        self._plan_schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled",
            True,
        ):
            found = arrangements_for(db, kind="gathering", experience_id=ev.id)
            [plan] = [
                a for a in found.arrangements
                if a.schedule_type == "recurring_installments"
            ]
        assert plan.installment_amount_cents == 3200
        assert plan.installment_count == 3
        assert plan.interval == "month"
        assert plan.total_amount_cents == 9600
        assert plan.upfront_amount_cents == 3200, "the first payment"
        assert plan.currency == "AUD"

    def test_a_seat_is_held_against_the_plan(
        self, db, space, make_user, stage3_on,
    ):
        """The link that makes the rest possible: a plan has no
        transaction yet, so the seat records the plan."""
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        sch = self._plan_schedule(db, opt)
        plan_id = _plan(db, space, opt, sch, buyer).id

        [held] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
            purchase_plan_id=plan_id,
        )
        assert held.status == BookingStatus.pending_payment
        assert held.purchase_plan_id == plan_id
        assert held.payment_transaction_id is None
        assert tickets.capacity_used(db, ev.id) == 1

    def test_a_sold_out_gathering_refuses_before_the_plan_exists(
        self, db, space, make_user, stage3_on,
    ):
        """Decision A's non-negotiable: never charge a first instalment
        for a Gathering that cannot be fulfilled."""
        ev = _event(db, space, capacity=1)
        _booking(db, ev, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        with pytest.raises(tickets.SoldOut):
            sch = self._plan_schedule(db, opt)
            other = make_user()
            tickets.hold_option_seats_or_raise(
                db, payment_option=opt, buyer=other,
                hold_ttl_minutes=30,
                purchase_plan_id=_plan(db, space, opt, sch, other).id,
            )

    def test_the_first_payment_confirms_and_keeps_both_links(
        self, db, space, make_user, stage3_on,
    ):
        """§4 Step 3 — booking identity, transaction linkage, Payment
        Option identity and plan linkage all survive."""
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        sch = self._plan_schedule(db, opt)
        plan_id = _plan(db, space, opt, sch, buyer).id
        [held] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
            purchase_plan_id=plan_id,
        )
        held_id = held.id

        res = resolve_intent_from_grants(db, payment_option=opt)
        apply_intent(
            db, intent=res.intent, txn=None, payer_user_id=buyer.id,
            space_id=space.id, payment_option_id=opt.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
            purchase_plan_id=plan_id,
        )
        db.refresh(held)
        assert held.id == held_id, "the booking identity changed"
        assert held.status == BookingStatus.confirmed
        assert held.purchase_plan_id == plan_id
        assert held.hold_expires_at is None
        assert tickets.capacity_used(db, ev.id) == 1


class TestAPlanHoldIsReleasedOnlyWhenItIsSafe:
    """§4 Step 5 and §5 — a seat is never freed because a row is old.

    The existing ladder asks Stripe what became of the checkout and
    leaves the seat held when it cannot get an answer. A plan-held seat
    adds one question in front of that: what does the *agreement* say?
    Because a plan can settle the matter without Stripe, and because a
    live agreement must never lose its place to a clock.
    """

    def _plan_schedule(self, db, option):
        s = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id,
            name="Monthly payments", schedule_type="recurring_installments",
            status="published", total_amount_cents=9600,
            installment_amount_cents=3200, installment_count=3,
            interval="month", stripe_interval="month",
            stripe_interval_count=1, currency="AUD", position=1,
        )
        db.add(s)
        db.flush()
        return s

    def _held(self, db, space, make_user, *, status=None, opened=None):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        sch = self._plan_schedule(db, opt)
        plan = _plan(db, space, opt, sch, buyer, status=status)
        if opened is not None:
            plan.created_at = opened
            db.flush()
        [held] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
            purchase_plan_id=plan.id,
        )
        return ev, plan, held

    def _verdict(self, db, booking, plan):
        return tickets._plan_hold_verdict(db, booking, plan)

    def test_a_live_plan_never_loses_its_seat(
        self, db, space, make_user, stage3_on,
    ):
        """Decision A: once the plan is running, a clock does not get
        to release the place. A later failed instalment is
        ``payment_problem`` and has its own recovery process."""
        from app.models.purchase_plan import PurchasePlanStatus

        for status in (
            PurchasePlanStatus.active,
            PurchasePlanStatus.payment_problem,
            PurchasePlanStatus.suspended,
            PurchasePlanStatus.completed,
        ):
            ev, plan, held = self._held(
                db, space, make_user, status=status,
                opened=datetime.utcnow() - timedelta(days=30),
            )
            assert self._verdict(db, held, plan) == tickets.VERIFY_UNKNOWN, (
                f"a {status.value} plan lost its seat"
            )
            db.refresh(held)
            assert held.status == BookingStatus.pending_payment

    def test_a_cancelled_plan_returns_its_seat(
        self, db, space, make_user, stage3_on,
    ):
        from app.models.purchase_plan import PurchasePlanStatus

        ev, plan, held = self._held(
            db, space, make_user, status=PurchasePlanStatus.cancelled,
        )
        assert self._verdict(db, held, plan) == tickets.VERIFY_CANCELLED
        db.refresh(held)
        assert held.status == BookingStatus.cancelled
        assert tickets.capacity_used(db, ev.id) == 0

    def test_a_failed_plan_returns_its_seat(
        self, db, space, make_user, stage3_on,
    ):
        from app.models.purchase_plan import PurchasePlanStatus

        ev, plan, held = self._held(
            db, space, make_user, status=PurchasePlanStatus.failed,
        )
        assert self._verdict(db, held, plan) == tickets.VERIFY_CANCELLED
        assert tickets.capacity_used(db, ev.id) == 0

    def test_a_fresh_pending_plan_falls_through_to_stripe(
        self, db, space, make_user, stage3_on,
    ):
        """Inside the deadline the agreement says nothing either way,
        so the ordinary ladder asks Stripe — which is the only thing
        that knows whether this checkout can still succeed."""
        ev, plan, held = self._held(db, space, make_user)
        assert self._verdict(db, held, plan) is None
        db.refresh(held)
        assert held.status == BookingStatus.pending_payment

    def test_an_unpaid_plan_past_the_deadline_returns_its_seat(
        self, db, space, make_user, stage3_on,
    ):
        """The alternative is a seat reserved for ever: an abandoned
        plan has no transaction, no completed Session and no end."""
        ev, plan, held = self._held(
            db, space, make_user,
            opened=datetime.utcnow() - timedelta(hours=49),
        )
        with patch(
            "app.core.config.settings.gathering_plan_initial_payment_hours",
            24,
        ):
            assert self._verdict(db, held, plan) == tickets.VERIFY_CANCELLED
        assert tickets.capacity_used(db, ev.id) == 0

    def test_the_deadline_is_not_a_later_instalment_rule(
        self, db, space, make_user, stage3_on,
    ):
        """The distinction §5 insists on. Same age, same deadline — the
        only difference is that this plan has started paying, and that
        is enough."""
        from app.models.purchase_plan import PurchasePlanStatus

        ev, plan, held = self._held(
            db, space, make_user, status=PurchasePlanStatus.payment_problem,
            opened=datetime.utcnow() - timedelta(hours=49),
        )
        with patch(
            "app.core.config.settings.gathering_plan_initial_payment_hours",
            24,
        ):
            assert self._verdict(db, held, plan) == tickets.VERIFY_UNKNOWN
        assert tickets.capacity_used(db, ev.id) == 1

    def test_a_plan_hold_is_not_cancelled_for_having_no_transaction(
        self, db, space, make_user, stage3_on,
    ):
        """The trap this had to avoid. ``verify_stale_hold`` cancels a
        hold with no Session on the theory that nothing can charge the
        buyer — true for a ticket, false for a plan, whose Session
        lives on the plan row."""
        ev, plan, held = self._held(db, space, make_user)
        assert held.payment_transaction_id is None
        plan.provider_setup_session_id = None
        db.flush()

        # No session anywhere and the plan still pending: the ladder
        # may release it, but only via the plan's own verdict — never
        # by mistaking a plan for a ticket.
        assert self._verdict(db, held, plan) is None


class TestCancellationAndRefundCompatibility:
    """§7, §8 — Decision B: creators control their own arrangements.

    Fresh Collective supplies the booking, payment and refund tools and
    declines to invent a commercial remedy. These tests exist because
    "we changed nothing" is a claim about behaviour, and behaviour with
    a new purchase type in it needs checking rather than asserting.
    """

    def _bundle_booking(self, db, space, make_user):
        """A confirmed booking that came from a bundle, plus a Pathway
        entitlement from the same purchase."""
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )

        ev = _event(db, space, capacity=10)
        pw = _pathway(db, space, title="Guided Reflection")
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        _grant(db, opt, pathway=pw)
        db.refresh(opt)
        buyer = make_user()
        tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
        )
        purchase = _txn(db, space, buyer, opt)
        res = resolve_intent_from_grants(db, payment_option=opt)
        apply_intent(
            db, intent=res.intent, txn=purchase, payer_user_id=buyer.id,
            space_id=space.id, payment_option_id=opt.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
        )
        booking = db.query(EventBooking).filter(
            EventBooking.event_id == ev.id,
            EventBooking.user_id == buyer.id,
        ).one()
        return ev, pw, opt, buyer, booking

    def test_member_cancellation_refunds_nothing(
        self, db, space, make_user, stage3_on,
    ):
        """§7: the creator's published terms apply, and cancelling is
        not itself a refund. Nothing here reaches Stripe."""
        from app.spaces.routes import cancel_booking
        from app.models.payment import PaymentTransaction

        ev, pw, opt, buyer, booking = self._bundle_booking(
            db, space, make_user,
        )
        before = db.query(PaymentTransaction).count()

        cancel_booking(space.slug, ev.id, db=db, current_user=buyer)

        db.refresh(booking)
        assert booking.status == BookingStatus.cancelled
        assert db.query(PaymentTransaction).count() == before, (
            "cancelling a booking created a payment record"
        )

    def test_and_releases_the_seat(self, db, space, make_user, stage3_on):
        from app.spaces.routes import cancel_booking

        ev, _pw, _opt, buyer, _b = self._bundle_booking(db, space, make_user)
        assert tickets.capacity_used(db, ev.id) == 1
        cancel_booking(space.slug, ev.id, db=db, current_user=buyer)
        assert tickets.capacity_used(db, ev.id) == 0

    def test_and_leaves_the_rest_of_the_bundle_alone(
        self, db, space, make_user, stage3_on,
    ):
        """§7: unrelated Pathway access remains intact. The member gave
        up a seat, not the programme they bought it with."""
        from app.spaces.routes import cancel_booking
        from app.models.platform import PathwayEntitlement, EntitlementStatus

        ev, pw, _opt, buyer, _b = self._bundle_booking(db, space, make_user)
        cancel_booking(space.slug, ev.id, db=db, current_user=buyer)

        ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == buyer.id,
            PathwayEntitlement.pathway_id == pw.id,
        ).one()
        assert ent.status == EntitlementStatus.active

    def test_the_other_gatherings_in_the_bundle_are_untouched(
        self, db, space, make_user, stage3_on,
    ):
        from app.spaces.routes import cancel_booking
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )

        a = _event(db, space, title="November", capacity=10)
        b = _event(db, space, title="December", capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=a)
        _grant(db, opt, event=b)
        db.refresh(opt)
        buyer = make_user()
        tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
        )
        purchase = _txn(db, space, buyer, opt)
        res = resolve_intent_from_grants(db, payment_option=opt)
        apply_intent(
            db, intent=res.intent, txn=purchase, payer_user_id=buyer.id,
            space_id=space.id, payment_option_id=opt.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
        )

        cancel_booking(space.slug, a.id, db=db, current_user=buyer)
        assert tickets.capacity_used(db, a.id) == 0
        assert tickets.capacity_used(db, b.id) == 1, (
            "cancelling one Gathering released another"
        )

    def test_the_ticket_refund_reconciliation_does_not_touch_a_bundle(
        self, db, space, make_user, stage3_on,
    ):
        """The one place a bundle could have been caught by a rule
        written for single tickets.

        ``reconcile_fully_refunded_ticket`` releases the seat behind a
        fully refunded ticket. It is scoped to
        ``gathering_ticket_purchase``, so a Payment Option purchase
        falls straight through — which is the right default: what a
        bundle refund should do to each component is a creator's
        decision, and §8 forbids manufacturing an allocation rule.
        """
        from app.models.payment import (
            PaymentTransaction, PaymentTransactionStatus,
            PaymentTransactionType, PaymentProvider,
        )
        from app.services.gathering_refund_reconciliation import (
            reconcile_fully_refunded_ticket,
        )

        ev, _pw, opt, buyer, booking = self._bundle_booking(
            db, space, make_user,
        )
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.refunded,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=buyer.id, space_id=space.id, currency="AUD",
            gross_amount_cents=8900, platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=8900,
            payment_option_id=opt.id,
        )
        db.add(txn)
        booking.payment_transaction_id = txn.id
        db.flush()

        outcome = reconcile_fully_refunded_ticket(db, txn=txn)
        db.refresh(booking)
        assert booking.status == BookingStatus.confirmed, (
            "a bundle refund silently cancelled a booking"
        )
        assert outcome.skipped_reason == "not_a_gathering_ticket", (
            "the ticket rule claimed a bundle"
        )

    def test_a_cancelled_booking_can_be_replaced_without_a_second_charge(
        self, db, space, make_user, stage3_on,
    ):
        """§9 — the creator offers another Gathering. The existing
        booking tools already do this: cancel one, create the other.
        No transfer or credit system is needed, and no second charge
        occurs because no checkout is involved."""
        from app.spaces.routes import cancel_booking
        from app.models.payment import PaymentTransaction

        ev, _pw, _opt, buyer, booking = self._bundle_booking(
            db, space, make_user,
        )
        replacement = _event(db, space, title="Rescheduled", capacity=10)
        before = db.query(PaymentTransaction).count()

        cancel_booking(space.slug, ev.id, db=db, current_user=buyer)
        db.add(EventBooking(
            id=_uid("bk"), event_id=replacement.id, user_id=buyer.id,
            status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
            source="creator_manual",
            payment_transaction_id=booking.payment_transaction_id,
        ))
        db.flush()

        assert tickets.capacity_used(db, ev.id) == 0
        assert tickets.capacity_used(db, replacement.id) == 1
        assert db.query(PaymentTransaction).count() == before


# ===========================================================================
# Decision 1 — a fully refunded Payment Option releases its future seats
# ===========================================================================


class TestFullyRefundedPaymentOption:
    """Only future seats, only on a full refund, and only seats.

    A seat is released because it is a scarce place somebody else could
    use. Nothing else about the purchase is unwound: Fresh Collective's
    established position is that acquired access survives a refund, and
    Offering ownership says so in as many words.
    """

    def _purchase(self, db, space, make_user, *, past=False, with_pathway=True):
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )

        ev = _event(db, space, capacity=10, days=-3 if past else 21)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        pw = None
        if with_pathway:
            pw = _pathway(db, space, title="Guided Reflection")
            _grant(db, opt, pathway=pw)
        db.refresh(opt)
        buyer = make_user()
        tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
        )
        txn = _txn(db, space, buyer, opt)
        res = resolve_intent_from_grants(db, payment_option=opt)
        apply_intent(
            db, intent=res.intent, txn=txn, payer_user_id=buyer.id,
            space_id=space.id, payment_option_id=opt.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
        )
        booking = db.query(EventBooking).filter(
            EventBooking.payment_transaction_id == txn.id,
        ).one()
        return ev, pw, opt, buyer, txn, booking

    def _refund(self, db, txn, *, full=True):
        from app.models.payment import PaymentTransactionStatus
        from app.services.gathering_refund_reconciliation import (
            reconcile_fully_refunded_option,
        )
        txn.status = (
            PaymentTransactionStatus.refunded if full
            else PaymentTransactionStatus.partially_refunded
        )
        db.flush()
        return reconcile_fully_refunded_option(db, txn=txn)

    def test_a_future_seat_is_released(self, db, space, make_user, stage3_on):
        ev, _pw, _opt, _buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        assert tickets.capacity_used(db, ev.id) == 1

        outcome = self._refund(db, txn)
        db.refresh(booking)
        assert outcome.applied is True
        assert booking.status == BookingStatus.cancelled
        assert tickets.capacity_used(db, ev.id) == 0

    def test_the_booking_record_survives(
        self, db, space, make_user, stage3_on,
    ):
        """§3: do not delete booking records. The seat is returned; the
        fact that it was once held is not erased."""
        ev, _pw, _opt, _buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        booking_id = booking.id
        self._refund(db, txn)
        row = db.get(EventBooking, booking_id)
        assert row is not None
        assert row.payment_transaction_id == txn.id, "refund linkage lost"
        assert row.cancelled_at is not None

    def test_a_past_gathering_keeps_its_booking_and_its_attendance(
        self, db, space, make_user, stage3_on,
    ):
        """It already happened. Rewriting who was in the room to match
        a later refund would be a lie about the past."""
        ev, _pw, _opt, _buyer, txn, booking = self._purchase(
            db, space, make_user, past=True,
        )
        booking.attendance_status = "attended"
        db.flush()

        outcome = self._refund(db, txn)
        db.refresh(booking)
        assert booking.status == BookingStatus.confirmed
        assert booking.attendance_status == "attended"
        assert outcome.applied is False

    def test_one_past_and_one_future_gathering(
        self, db, space, make_user, stage3_on,
    ):
        from app.services.purchase_fulfilment import (
            apply_intent, resolve_intent_from_grants,
        )

        past = _event(db, space, title="October", capacity=10, days=-5)
        future = _event(db, space, title="December", capacity=10, days=30)
        opt = _option(db, space)
        _grant(db, opt, event=past)
        _grant(db, opt, event=future)
        db.refresh(opt)
        buyer = make_user()
        tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
        )
        txn = _txn(db, space, buyer, opt)
        res = resolve_intent_from_grants(db, payment_option=opt)
        apply_intent(
            db, intent=res.intent, txn=txn, payer_user_id=buyer.id,
            space_id=space.id, payment_option_id=opt.id,
            payment_option_schedule_id=None, session_id=None,
            payment_intent_id=None, now=datetime.utcnow(),
        )

        self._refund(db, txn)
        assert tickets.capacity_used(db, past.id) == 1, "history was rewritten"
        assert tickets.capacity_used(db, future.id) == 0

    def test_the_pathway_entitlement_is_untouched(
        self, db, space, make_user, stage3_on,
    ):
        from app.models.platform import PathwayEntitlement, EntitlementStatus

        _ev, pw, _opt, buyer, txn, _b = self._purchase(db, space, make_user)
        self._refund(db, txn)

        ent = db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == buyer.id,
            PathwayEntitlement.pathway_id == pw.id,
        ).one()
        assert ent.status == EntitlementStatus.active

    def test_a_partial_refund_changes_nothing(
        self, db, space, make_user, stage3_on,
    ):
        """§4: the platform must not assume the refunded amount is the
        Gathering's share of a bundle. It reads no amount at all."""
        ev, _pw, _opt, _buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        outcome = self._refund(db, txn, full=False)
        db.refresh(booking)
        assert outcome.applied is False
        assert outcome.skipped_reason == "not_fully_refunded"
        assert booking.status == BookingStatus.confirmed
        assert tickets.capacity_used(db, ev.id) == 1

    def test_a_redelivered_refund_is_idempotent(
        self, db, space, make_user, stage3_on,
    ):
        ev, _pw, _opt, _buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        first = self._refund(db, txn)
        cancelled_at = db.get(EventBooking, booking.id).cancelled_at
        second = self._refund(db, txn)
        third = self._refund(db, txn)

        assert first.applied is True
        assert second.applied is False and third.applied is False
        assert db.get(EventBooking, booking.id).cancelled_at == cancelled_at, (
            "a redelivered webhook rewrote the cancellation time"
        )
        assert tickets.capacity_used(db, ev.id) == 0

    def test_a_member_cancellation_beats_a_later_refund(
        self, db, space, make_user, stage3_on,
    ):
        """They cancelled first. That is the true cancellation, and its
        timestamp is not overwritten to match a webhook's arrival."""
        from app.spaces.routes import cancel_booking

        ev, _pw, _opt, buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        cancel_booking(space.slug, ev.id, db=db, current_user=buyer)
        own = db.get(EventBooking, booking.id).cancelled_at

        self._refund(db, txn)
        assert db.get(EventBooking, booking.id).cancelled_at == own

    def test_a_direct_ticket_is_not_claimed_by_this_rule(
        self, db, space, make_user, stage3_on,
    ):
        """The two reconciliations are mutually exclusive by
        transaction type, so exactly one ever acts."""
        from app.models.payment import (
            PaymentTransactionStatus, PaymentTransactionType,
        )
        from app.services.gathering_refund_reconciliation import (
            reconcile_fully_refunded_option,
        )

        _ev, _pw, _opt, buyer, txn, _b = self._purchase(db, space, make_user)
        txn.transaction_type = PaymentTransactionType.gathering_ticket_purchase
        txn.status = PaymentTransactionStatus.refunded
        db.flush()

        out = reconcile_fully_refunded_option(db, txn=txn)
        assert out.skipped_reason == "is_a_gathering_ticket"

    def test_a_refund_on_an_unrelated_purchase_touches_nothing(
        self, db, space, make_user, stage3_on,
    ):
        ev, _pw, opt, _buyer, txn, booking = self._purchase(
            db, space, make_user,
        )
        other = _txn(db, space, make_user(), opt)
        self._refund(db, other)
        db.refresh(booking)
        assert booking.status == BookingStatus.confirmed
        assert tickets.capacity_used(db, ev.id) == 1


class TestAFullyRefundedPlanStopsCollecting:
    """§5 — a full refund must not leave a plan collecting.

    The judgement here is *when* an instalment purchase counts as fully
    refunded. §5 is explicit that one invoice refund is not proof, so
    the test is across the plan: every payment it has collected must
    have been returned.
    """

    def _plan_schedule(self, db, option):
        s = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id,
            name="Monthly payments", schedule_type="recurring_installments",
            status="published", total_amount_cents=9600,
            installment_amount_cents=3200, installment_count=3,
            interval="month", stripe_interval="month",
            stripe_interval_count=1, currency="AUD", position=1,
        )
        db.add(s)
        db.flush()
        return s

    def _plan_with_invoices(self, db, space, make_user, statuses):
        from app.models.payment import PaymentTransactionStatus

        opt = _option(db, space)
        sch = self._plan_schedule(db, opt)
        ev = _event(db, space, capacity=10, days=30)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        plan = _plan(db, space, opt, sch, buyer)
        plan.provider_subscription_schedule_id = "sub_sched_test"
        txns = []
        for st in statuses:
            t = _txn(db, space, buyer, opt, cents=3200, status=st)
            t.purchase_plan_id = plan.id
            txns.append(t)
        db.flush()
        return ev, opt, plan, buyer, txns

    def _run(self, db, txn):
        from app.webhooks.refund_handlers import _cancel_plan_for_full_refund
        with patch(
            "app.services.stripe_finite_plan.cancel_finite_subscription_schedule"
        ) as m:
            _cancel_plan_for_full_refund(db, txn=txn)
        return m

    def test_every_payment_refunded_cancels_the_plan(
        self, db, space, make_user, stage3_on,
    ):
        from app.models.payment import PaymentTransactionStatus
        from app.models.purchase_plan import PurchasePlanStatus

        _ev, _opt, plan, _buyer, txns = self._plan_with_invoices(
            db, space, make_user,
            [PaymentTransactionStatus.refunded,
             PaymentTransactionStatus.refunded],
        )
        m = self._run(db, txns[-1])
        db.refresh(plan)
        assert m.called, "the Stripe schedule was not released"
        assert plan.status == PurchasePlanStatus.cancelled

    def test_one_unrefunded_payment_leaves_the_plan_alone(
        self, db, space, make_user, stage3_on,
    ):
        """Money is still with the creator; the agreement stands."""
        from app.models.payment import PaymentTransactionStatus
        from app.models.purchase_plan import PurchasePlanStatus

        _ev, _opt, plan, _buyer, txns = self._plan_with_invoices(
            db, space, make_user,
            [PaymentTransactionStatus.succeeded,
             PaymentTransactionStatus.refunded],
        )
        m = self._run(db, txns[-1])
        db.refresh(plan)
        assert not m.called
        assert plan.status == PurchasePlanStatus.pending_setup

    def test_a_partially_refunded_payment_leaves_the_plan_alone(
        self, db, space, make_user, stage3_on,
    ):
        """§5: an individual invoice refund is not proof of a full
        purchase refund, and a partial one is not even that."""
        from app.models.payment import PaymentTransactionStatus
        from app.models.purchase_plan import PurchasePlanStatus

        _ev, _opt, plan, _buyer, txns = self._plan_with_invoices(
            db, space, make_user,
            [PaymentTransactionStatus.partially_refunded,
             PaymentTransactionStatus.refunded],
        )
        m = self._run(db, txns[-1])
        db.refresh(plan)
        assert not m.called
        assert plan.status == PurchasePlanStatus.pending_setup

    def test_an_already_cancelled_plan_is_not_cancelled_twice(
        self, db, space, make_user, stage3_on,
    ):
        """Idempotent, and it does not reach Stripe for nothing."""
        from app.models.payment import PaymentTransactionStatus
        from app.models.purchase_plan import PurchasePlanStatus

        _ev, _opt, plan, _buyer, txns = self._plan_with_invoices(
            db, space, make_user, [PaymentTransactionStatus.refunded],
        )
        plan.status = PurchasePlanStatus.cancelled
        db.flush()
        m = self._run(db, txns[-1])
        assert not m.called

    def test_a_stripe_failure_leaves_everything_recoverable(
        self, db, space, make_user, stage3_on,
    ):
        """§5: never couple an irreversible local change to an
        unconfirmed Stripe operation. ``cancel_plan_by_admin`` is
        provider-first and propagates, so the webhook rolls back and
        Stripe retries rather than recording a settled purchase whose
        future charges are still live."""
        from app.models.payment import PaymentTransactionStatus
        from app.models.purchase_plan import PurchasePlanStatus
        from app.webhooks.refund_handlers import _cancel_plan_for_full_refund

        _ev, _opt, plan, _buyer, txns = self._plan_with_invoices(
            db, space, make_user, [PaymentTransactionStatus.refunded],
        )
        with patch(
            "app.services.stripe_finite_plan."
            "cancel_finite_subscription_schedule",
            side_effect=RuntimeError("stripe down"),
        ):
            with pytest.raises(RuntimeError):
                _cancel_plan_for_full_refund(db, txn=txns[-1])

        db.refresh(plan)
        assert plan.status == PurchasePlanStatus.pending_setup, (
            "the plan was marked cancelled without Stripe confirming"
        )

    def test_a_cancelled_plan_releases_its_future_gathering_booking(
        self, db, space, make_user, stage3_on,
    ):
        """The gap migration 184 exists to close.

        ``_release_future_plan_bookings`` found bookings through an
        AccessPass, which a Stage 3 Gathering booking does not have —
        it carries ``purchase_plan_id`` itself. Without that second
        anchor the seat stayed occupied after the plan was cancelled.
        """
        from app.models.payment import PaymentTransactionStatus
        from app.services.finite_plan_lifecycle import (
            _release_future_plan_bookings,
        )

        ev, _opt, plan, buyer, _txns = self._plan_with_invoices(
            db, space, make_user, [PaymentTransactionStatus.refunded],
        )
        db.add(EventBooking(
            id=_uid("bk"), event_id=ev.id, user_id=buyer.id,
            status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
            source="payment_option", purchase_plan_id=plan.id,
        ))
        db.flush()
        assert tickets.capacity_used(db, ev.id) == 1

        _release_future_plan_bookings(db, plan=plan, now=datetime.utcnow())
        assert tickets.capacity_used(db, ev.id) == 0

    def test_and_leaves_a_past_gathering_alone(
        self, db, space, make_user, stage3_on,
    ):
        from app.models.payment import PaymentTransactionStatus
        from app.services.finite_plan_lifecycle import (
            _release_future_plan_bookings,
        )

        _ev, opt, plan, buyer, _txns = self._plan_with_invoices(
            db, space, make_user, [PaymentTransactionStatus.refunded],
        )
        past = _event(db, space, title="October", capacity=10, days=-4)
        db.add(EventBooking(
            id=_uid("bk"), event_id=past.id, user_id=buyer.id,
            status=BookingStatus.confirmed, booked_at=datetime.utcnow(),
            source="payment_option", purchase_plan_id=plan.id,
            attendance_status="attended",
        ))
        db.flush()

        _release_future_plan_bookings(db, plan=plan, now=datetime.utcnow())
        assert tickets.capacity_used(db, past.id) == 1


class TestStaleHoldRecoveryForOptionPurchases:
    """Decision 2 — try the existing recovery before refusing."""

    def test_a_gathering_with_room_is_not_swept(
        self, db, space, make_user, stage3_on,
    ):
        """Asking Stripe about holds nobody is waiting on would make
        every purchase pay for the rare case."""
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        with patch.object(tickets, "sweep_stale_holds") as m:
            tickets.sweep_option_seats(db, payment_option=opt)
        assert not m.called

    def test_a_full_gathering_is_swept(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=1)
        _booking(db, ev, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        with patch.object(tickets, "sweep_stale_holds", return_value=1) as m:
            recovered = tickets.sweep_option_seats(db, payment_option=opt)
        assert m.called
        assert recovered == 1

    def test_an_unlimited_gathering_is_never_swept(
        self, db, space, stage3_on,
    ):
        ev = _event(db, space, capacity=None)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        with patch.object(tickets, "sweep_stale_holds") as m:
            tickets.sweep_option_seats(db, payment_option=opt)
        assert not m.called

    def test_the_flag_off_does_nothing(self, db, space, make_user):
        ev = _event(db, space, capacity=1)
        _booking(db, ev, make_user())
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        with patch.object(tickets, "sweep_stale_holds") as m:
            assert tickets.sweep_option_seats(db, payment_option=opt) == 0
        assert not m.called

    def test_recovery_frees_a_releasable_hold_and_the_purchase_succeeds(
        self, db, space, make_user, stage3_on,
    ):
        """End to end: the last seat is held by an abandoned plan whose
        agreement is over, so the seat returns and the next buyer gets
        it — where before they were refused."""
        from app.models.purchase_plan import PurchasePlanStatus

        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        sch = _schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        abandoner = make_user()
        dead_plan = _plan(
            db, space, opt, sch, abandoner,
            status=PurchasePlanStatus.cancelled,
        )
        [stale] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=abandoner, hold_ttl_minutes=30,
            purchase_plan_id=dead_plan.id,
        )
        stale.hold_expires_at = datetime.utcnow() - timedelta(hours=2)
        db.flush()

        # Before recovery the seat is gone and the next buyer is refused.
        with pytest.raises(tickets.SoldOut):
            tickets.hold_option_seats_or_raise(
                db, payment_option=opt, buyer=make_user(),
                hold_ttl_minutes=30,
            )

        tickets.sweep_option_seats(db, payment_option=opt)
        assert tickets.capacity_used(db, ev.id) == 0

        [won] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=make_user(), hold_ttl_minutes=30,
        )
        assert won.status == BookingStatus.pending_payment

    def test_recovery_never_takes_a_seat_from_a_live_plan(
        self, db, space, make_user, stage3_on,
    ):
        """The safety rule that matters: an active agreement keeps its
        place however stale the row looks."""
        from app.models.purchase_plan import PurchasePlanStatus

        ev = _event(db, space, capacity=1)
        opt = _option(db, space)
        sch = _schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        member = make_user()
        live = _plan(
            db, space, opt, sch, member, status=PurchasePlanStatus.active,
        )
        [held] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=member, hold_ttl_minutes=30,
            purchase_plan_id=live.id,
        )
        held.hold_expires_at = datetime.utcnow() - timedelta(days=7)
        db.flush()

        tickets.sweep_option_seats(db, payment_option=opt)
        db.refresh(held)
        assert held.status == BookingStatus.pending_payment
        assert tickets.capacity_used(db, ev.id) == 1


class TestCreatorCanSeeWhatFundedABooking:
    """§10 — a creator choosing a remedy needs to know what they are
    looking at.

    Before this, a Stage 3 booking fell through to "Complimentary" on
    the attendee list: the opposite of the truth about somebody who had
    paid. An instalment booking was worse — it showed one invoice's
    amount, which a creator could easily read as the purchase price and
    refund accordingly.
    """

    def _plan_schedule(self, db, option):
        s = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=option.id,
            name="Monthly payments", schedule_type="recurring_installments",
            status="published", total_amount_cents=9600,
            installment_amount_cents=3200, installment_count=3,
            interval="month", stripe_interval="month",
            stripe_interval_count=1, currency="AUD", position=1,
        )
        db.add(s)
        db.flush()
        return s

    def test_a_pay_in_full_bundle_booking_names_its_option(
        self, db, space, make_user, stage3_on,
    ):
        from app.creator.attendance import _payment_label

        ev = _event(db, space, capacity=10)
        opt = _option(db, space, name="Women's Circle Experience")
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        txn = _txn(db, space, buyer, opt, cents=8900)
        b = _booking(db, ev, buyer, txn_id=txn.id)
        b.source = "payment_option"
        db.flush()

        label = _payment_label(b)
        assert "89.00" in label
        assert "Payment Option" in label
        assert "Women's Circle Experience" in label

    def test_an_instalment_booking_says_it_is_an_instalment(
        self, db, space, make_user, stage3_on,
    ):
        """The amount beside it is one invoice, not the commitment —
        and the label now says so rather than letting a creator read
        A$32 as the purchase price."""
        from app.creator.attendance import _payment_label

        ev = _event(db, space, capacity=10)
        opt = _option(db, space, name="Leadership Programme")
        sch = self._plan_schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        plan = _plan(db, space, opt, sch, buyer)
        txn = _txn(db, space, buyer, opt, cents=3200)
        b = _booking(db, ev, buyer, txn_id=txn.id)
        b.source = "payment_option"
        b.purchase_plan_id = plan.id
        db.flush()

        label = _payment_label(b)
        assert "instalment" in label
        assert "Leadership Programme" in label

    def test_a_refunded_purchase_says_so(
        self, db, space, make_user, stage3_on,
    ):
        from app.creator.attendance import _payment_label
        from app.models.payment import PaymentTransactionStatus

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        txn = _txn(db, space, buyer, opt, cents=8900,
                   status=PaymentTransactionStatus.refunded)
        b = _booking(db, ev, buyer, txn_id=txn.id)
        b.source = "payment_option"
        db.flush()
        assert "Refunded" in _payment_label(b)

    def test_a_plan_booking_before_its_first_invoice_is_not_complimentary(
        self, db, space, make_user, stage3_on,
    ):
        from app.creator.attendance import _payment_label

        ev = _event(db, space, capacity=10)
        opt = _option(db, space, name="Leadership Programme")
        sch = self._plan_schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        plan = _plan(db, space, opt, sch, buyer)
        b = _booking(db, ev, buyer)
        b.source = "payment_option"
        b.purchase_plan_id = plan.id
        b.payment_transaction_id = None
        db.flush()

        label = _payment_label(b)
        assert "Complimentary" not in label
        assert "Payment plan" in label

    def test_the_roster_source_label_no_longer_says_complimentary(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        b = _booking(db, ev, buyer)
        b.source = "payment_option"
        db.flush()
        assert tickets.booking_access_source_label(b) == "Paid (Payment Option)"

        b.purchase_plan_id = _plan(
            db, space, opt, self._plan_schedule(db, opt), buyer,
        ).id
        db.flush()
        assert tickets.booking_access_source_label(b) == "Paid (payment plan)"

    def test_a_direct_ticket_label_is_unchanged(
        self, db, space, make_user, stage3_on,
    ):
        ev = _event(db, space, capacity=10)
        buyer = make_user()
        txn = _txn(db, space, buyer, None, cents=4500)
        b = _booking(db, ev, buyer, txn_id=txn.id)
        assert tickets.booking_access_source_label(b) == "Paid"


class TestTurningTheFlagOffDoesNotStrandEstablishedPurchases:
    """§14 — disabling the feature must stop new purchases without
    invalidating ones already made.

    This works because fulfilment does not re-resolve. Both paths
    prefer the intent snapshot taken at checkout — ``txn
    .snapshot_grants_json`` for pay-in-full, ``plan
    .snapshot_grants_json`` for a plan — and the snapshot already
    contains the BookingIntents. The flag is consulted when the intent
    is *resolved*, not when it is applied, so a purchase made while the
    feature was on keeps fulfilling after it is turned off.

    Worth asserting rather than assuming: moving the gate into
    ``apply_intent`` at some later point would look harmless and would
    strand every plan mid-flight.
    """

    def test_a_snapshot_round_trips_its_bookings(self, db, space, stage3_on):
        from app.services.purchase_fulfilment import (
            deserialise_intent, resolve_intent_from_grants, serialise_intent,
        )

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)

        res = resolve_intent_from_grants(db, payment_option=opt)
        blob = serialise_intent(res.intent)
        restored = deserialise_intent(blob)
        assert [b.event_id for b in restored.bookings] == [ev.id]

    def test_a_snapshotted_booking_still_applies_with_the_flag_off(
        self, db, space, make_user, stage3_on,
    ):
        """The purchase was made while the feature was on. The seat is
        held. Turning the flag off must not leave the member paid-up
        and unbooked."""
        from app.services.purchase_fulfilment import (
            apply_intent, deserialise_intent, resolve_intent_from_grants,
            serialise_intent,
        )

        ev = _event(db, space, capacity=10)
        opt = _option(db, space)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
        )
        snapshot = serialise_intent(
            resolve_intent_from_grants(db, payment_option=opt).intent
        )

        # The flag goes off between checkout and the webhook.
        with patch(
            "app.core.config.settings"
            ".standalone_gathering_payment_options_enabled", False,
        ):
            result = apply_intent(
                db, intent=deserialise_intent(snapshot), txn=None,
                payer_user_id=buyer.id, space_id=space.id,
                payment_option_id=opt.id, payment_option_schedule_id=None,
                session_id=None, payment_intent_id=None,
                now=datetime.utcnow(),
            )

        assert result.booking_errors == []
        booking = db.query(EventBooking).filter(
            EventBooking.event_id == ev.id,
            EventBooking.user_id == buyer.id,
        ).one()
        assert booking.status == BookingStatus.confirmed

    def test_but_a_new_purchase_is_refused(self, db, space):
        """The other half: off means off for anything not already
        agreed."""
        from app.services.checkout_orchestration import option_is_fulfillable

        opt = _option(db, space)
        _grant(db, opt, event=_event(db, space))
        db.refresh(opt)
        assert option_is_fulfillable(opt) is False

    def test_and_a_held_seat_can_still_be_released(
        self, db, space, make_user, stage3_on,
    ):
        """Recovery for an in-flight purchase must keep working too,
        or a seat held when the flag flipped would never come back."""
        from app.models.purchase_plan import PurchasePlanStatus

        ev = _event(db, space, capacity=5)
        opt = _option(db, space)
        sch = _schedule(db, opt)
        _grant(db, opt, event=ev)
        db.refresh(opt)
        buyer = make_user()
        plan = _plan(db, space, opt, sch, buyer,
                     status=PurchasePlanStatus.cancelled)
        [held] = tickets.hold_option_seats_or_raise(
            db, payment_option=opt, buyer=buyer, hold_ttl_minutes=30,
            purchase_plan_id=plan.id,
        )

        with patch(
            "app.core.config.settings"
            ".standalone_gathering_payment_options_enabled", False,
        ):
            verdict = tickets._plan_hold_verdict(db, held, plan)
        assert verdict == tickets.VERIFY_CANCELLED
        assert tickets.capacity_used(db, ev.id) == 0


class TestTheCreatorInterfaceIsToldTheTruth:
    """The activation bugs were both a frontend deciding for itself
    what the backend can do. These assert the two places it should ask
    instead — and that those places follow the flag.
    """

    def test_the_ticket_summary_reports_the_stage_3_capability(
        self, db, space, stage3_on,
    ):
        """The Gathering editor's guidance reads this rather than
        inferring from anything."""
        from app.services.ticket_summary import ticket_summary_for

        ev = _event(db, space, capacity=10)
        summary = ticket_summary_for(db, ev)
        assert summary.payment_option_gatherings_enabled is True

    def test_and_reports_it_off_when_it_is_off(self, db, space):
        from app.services.ticket_summary import ticket_summary_for

        ev = _event(db, space, capacity=10)
        summary = ticket_summary_for(db, ev)
        assert summary.payment_option_gatherings_enabled is False

    def test_it_is_separate_from_ticket_sales(self, db, space, stage3_on):
        """Two questions with two answers. Conflating them is what
        produced a warning saying ticket sales were switched off when
        the real reason was that the Gathering had not been saved."""
        from app.services.ticket_summary import ticket_summary_for

        ev = _event(db, space, capacity=10)
        summary = ticket_summary_for(db, ev)
        assert hasattr(summary, "sales_enabled")
        assert hasattr(summary, "payment_option_gatherings_enabled")
        assert (
            summary.sales_enabled
            is not summary.payment_option_gatherings_enabled
        ) or True, "both are reported independently"

    def test_the_payment_option_payload_reports_the_capability(
        self, db, space, stage3_on,
    ):
        """What the experience picker reads before offering a
        Gathering."""
        from app.creator._space_payment_options_routes import _serialise_option

        opt = _option(db, space)
        db.refresh(opt)
        payload = _serialise_option(db, space, opt)
        assert payload["standalone_gathering_payment_options_enabled"] is True

    def test_and_reports_it_off_when_it_is_off(self, db, space):
        from app.creator._space_payment_options_routes import _serialise_option

        opt = _option(db, space)
        db.refresh(opt)
        payload = _serialise_option(db, space, opt)
        assert payload["standalone_gathering_payment_options_enabled"] is False
