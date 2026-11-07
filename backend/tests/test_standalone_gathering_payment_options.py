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
