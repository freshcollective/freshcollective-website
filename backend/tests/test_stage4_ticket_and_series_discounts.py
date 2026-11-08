"""Stage 4 — discount codes on the two doors that are not the unified one.

A standalone Gathering ticket has its own hold, its own transaction and
its own Stripe Session; the Gathering Series entry point is a Payment
Option purchase wearing a different URL. Both now accept a code, and
both reach it through ``discount_checkout_hold`` rather than growing a
second reservation system — which is what §19 rules out and what the
source contract in ``test_discount_reservations`` pins.

The ticket door is the interesting one. Seats and slots are two
different scarce things, decided under two different row locks, and the
order they are taken in is part of the correctness argument: the code's
slot first, outside the Event lock, so two popular Gatherings sharing
one Collective-wide code cannot queue behind each other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_verified_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.discount_code import (
    DiscountCode,
    DiscountReservation,
    DiscountTargetKind,
    ReservationStatus,
)
from app.models.payment import PaymentTransaction
from app.models.platform import EventBooking

from tests.test_discount_checkout import _uid, make_code, stripe_spy  # noqa: F401


TICKET_CENTS = 4_500


@pytest.fixture(autouse=True)
def stage4_on(monkeypatch):
    monkeypatch.setattr(settings, "universal_discount_codes_enabled", True)


@pytest.fixture
def founding(db, make_user):
    """A creator whose plan permits paid selling at a 0% fee.

    Zero fee on purpose: it keeps the arithmetic assertions about the
    discount rather than about the fee schedule, which has its own
    tests. The fee *following* the discount is asserted separately
    below, where a non-zero rate is used deliberately.
    """
    def _make(slug: str = "founding-creator", bps: int = 0):
        creator = make_user(role="creator")
        plan = CreatorPlan(
            id=str(uuid4()), slug=slug, name=slug.replace("-", " ").title(),
            monthly_price_cents=0, currency="AUD",
            transaction_fee_basis_points=bps,
            is_active=True, collective_limit=1,
        )
        db.add(plan)
        db.flush()
        db.add(CreatorSubscription(
            id=str(uuid4()), user_id=creator.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=1),
            source="stripe_paid",
        ))
        db.flush()
        return creator
    return _make


@pytest.fixture
def buy_ticket(db):
    """POST the real ticket checkout as a verified buyer."""
    def _go(space, event, buyer, *, code: str | None = None):
        app.dependency_overrides[get_verified_current_user] = lambda: buyer
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app, raise_server_exceptions=False)
        body = {
            "success_url": "https://example.test/ok",
            "cancel_url": "https://example.test/no",
        }
        if code is not None:
            body["discount_code"] = code
        try:
            with patch(
                "app.core.config.settings.standalone_gathering_sales_enabled", True,
            ), patch(
                "app.core.config.settings.stripe_secret_key", "sk_test_dummy",
            ):
                return client.post(
                    f"/api/spaces/{space.slug}/events/{event.id}/checkout",
                    json=body,
                )
        finally:
            app.dependency_overrides.pop(get_verified_current_user, None)
            app.dependency_overrides.pop(get_db, None)
    return _go


# ---------------------------------------------------------------------------
# The standalone ticket door
# ---------------------------------------------------------------------------


class TestADiscountedGatheringTicket:

    def test_a_collective_wide_code_lowers_the_charge(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000)

        r = buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        assert r.status_code == 200, r.text
        assert stripe_spy.unit_amount == TICKET_CENTS // 2

    def test_the_transaction_records_the_discounted_gross_and_snapshot(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000)

        buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        assert txn.gross_amount_cents == TICKET_CENTS // 2
        assert (txn.discount_snapshot_json or {})["code"] == "FAMILY50"

    def test_the_fee_follows_the_discounted_amount(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """§12 — never the list price. An 8% fee on A$45 would be 360
        cents; on the A$22.50 actually taken it is 180."""
        creator = founding(slug="creator", bps=800)
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000)

        buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        txn = db.query(PaymentTransaction).one()
        assert txn.gross_amount_cents == 2_250
        assert txn.platform_fee_cents == 180
        assert txn.net_creator_amount_cents == 2_070

    def test_the_slot_is_held_against_the_gathering(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000)

        buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        r = db.query(DiscountReservation).one()
        assert r.target_kind == DiscountTargetKind.gathering.value
        assert r.target_id == event.id
        assert r.payment_option_id is None
        assert r.status == ReservationStatus.held.value

    def test_the_seat_is_still_held_and_capacity_still_decided_on_seats(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """A discount changes the amount charged, not the experiences
        granted (§15) and not how many there are to grant."""
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS, capacity=1)
        make_code(db, space, percent_bps=5000)

        buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        booking = db.query(EventBooking).one()
        assert booking.event_id == event.id

    def test_a_refused_seat_gives_the_slot_straight_back(
        self, db, make_space, make_user,
    ):
        """Seats are refused before money, and a refused seat means
        nothing can ever charge — so the code's slot goes back
        immediately rather than waiting out its window. Positive
        knowledge, which is the only basis on which a slot is released.

        Asserted at the boundary rather than through the HTTP route, for
        a harness reason worth recording. ``reserve_or_reuse`` commits,
        and the sold-out branch then calls ``db.rollback()``. In
        production that discards only the refused booking attempt, and
        the Event is a committed row that reloads fine. Under the test
        fixture — one transaction with a savepoint restarted on every
        commit — the same rollback unwinds past the fixture's own rows,
        and the route dies reading ``offer.event.id`` before it ever
        reaches the release. The behaviour under test is the release, so
        it is exercised where it actually lives.
        """
        from app.services.discount_checkout_hold import DiscountHold
        from app.services.discount_pricing import (
            AppliedDiscount, DiscountAmounts, build_snapshot,
        )
        from app.services.discount_reservations import (
            ReservationAttempt, reserve_or_reuse,
        )

        space, buyer = make_space(), make_user()
        code = make_code(db, space, percent_bps=5000, max_redemptions=1)
        applied = AppliedDiscount(
            code="FAMILY50", discount_code_id=code.id,
            amounts=DiscountAmounts(
                original_cents=TICKET_CENTS, discount_cents=TICKET_CENTS // 2,
                final_cents=TICKET_CENTS // 2, currency="AUD",
            ),
            snapshot={},
        )
        attempt = ReservationAttempt.for_direct(
            user_id=buyer.id, kind=DiscountTargetKind.gathering.value,
            target_id="evt_full",
        )
        outcome = reserve_or_reuse(
            db, applied=applied, code=code, attempt=attempt,
            now=datetime.utcnow(),
        )
        hold = DiscountHold(
            applied=applied, reservation=outcome.reservation, db=db,
        )

        hold.abandon(now=datetime.utcnow(), reason="seat_unavailable")

        db.expire_all()
        released = db.query(DiscountReservation).one()
        assert released.status == ReservationStatus.released.value
        assert released.release_reason == "seat_unavailable"

        # And the slot really is available again, which is the point.
        from app.services.discount_reservations import consumed_slots

        assert consumed_slots(db, code.id) == 0

    def test_the_ticket_door_releases_on_any_seat_refusal(self):
        """The release is wired to ``TicketCheckoutError``, not only to
        sold-out. Every refusal from that family means nothing can
        charge — a banned buyer, a cancelled Gathering, a closed booking
        window — so every one of them must hand the slot back.

        A source contract because the branch is the thing being
        asserted, and the harness cannot drive the rollback that reaches
        it (see the test above).
        """
        import inspect

        from app.spaces import routes as space_routes

        src = inspect.getsource(space_routes.create_gathering_ticket_checkout)

        # The handler that matters is the one wrapping the seat-taking
        # retry, not the two earlier ones — those run before any hold
        # exists (the sales gate and the offer load), and abandoning
        # there would be a reference to a variable that is not yet bound.
        # So the search starts after ``_take_hold`` is defined.
        _, after_hold = src.split("def _take_hold()", 1)
        marker = "except _gt.TicketCheckoutError as exc:"
        assert marker in after_hold
        branch = after_hold.split(marker, 1)[1].split("raise _map_ticket_error", 1)[0]
        assert "ticket_hold.abandon(" in branch
        assert "seat_unavailable" in branch

        # And the two earlier handlers deliberately do NOT abandon.
        before_hold = src.split("def _take_hold()", 1)[0]
        assert "abandon(" not in before_hold

    def test_a_ticket_without_a_code_is_unchanged(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)

        r = buy_ticket(space, event, make_user(role="user"))

        assert r.status_code == 200, r.text
        assert stripe_spy.unit_amount == TICKET_CENTS
        assert db.query(DiscountReservation).count() == 0
        assert db.query(PaymentTransaction).one().discount_snapshot_json is None

    def test_an_expired_code_is_refused_with_a_readable_reason(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(
            db, space, percent_bps=5000,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )

        r = buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        assert r.status_code == 409, r.text
        assert "expired" in r.json()["detail"]["message"].lower()
        assert stripe_spy.calls == []

    def test_an_option_scoped_code_does_not_reach_a_standalone_ticket(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """§4 — a code restricted to a bundle cannot be spent on a
        standalone ticket for a Gathering the bundle happens to
        include."""
        from tests.test_discount_checkout import make_offer

        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        option, _ = make_offer(db, space)
        make_code(
            db, space, code="BUNDLE20", percent_bps=2000,
            scope_kind="payment_option", scope_id=option.id,
        )

        r = buy_ticket(space, event, make_user(role="user"), code="BUNDLE20")

        assert r.status_code == 409, r.text
        assert stripe_spy.calls == []

    def test_the_code_is_case_insensitive_on_this_door_too(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, code="WELCOME20", percent_bps=2000)

        r = buy_ticket(space, event, make_user(role="user"), code="  welcome20 ")

        assert r.status_code == 200, r.text
        assert stripe_spy.unit_amount == 3_600

    def test_a_code_is_refused_while_the_flag_is_off(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000)

        r = buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "discount_codes_unavailable"
        assert stripe_spy.calls == []

    def test_a_plain_ticket_still_sells_while_the_flag_is_off(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy, monkeypatch,
    ):
        """§22's regression: the door is untouched when the feature is
        off."""
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)

        r = buy_ticket(space, event, make_user(role="user"))

        assert r.status_code == 200, r.text
        assert stripe_spy.unit_amount == TICKET_CENTS


# ---------------------------------------------------------------------------
# Usage limits across doors
# ---------------------------------------------------------------------------


class TestOneCodeAcrossSeveralDoors:

    def test_two_different_gatherings_take_two_slots(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """One Collective-wide code used on two different purchases is
        two uses — the attempt identity is per experience, not per
        member."""
        creator = founding()
        space = make_space(creator=creator)
        first = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        second = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000, max_redemptions=5)
        buyer = make_user(role="user")

        buy_ticket(space, first, buyer, code="FAMILY50")
        buy_ticket(space, second, buyer, code="FAMILY50")

        assert db.query(DiscountReservation).count() == 2

    def test_a_one_use_code_refuses_the_second_buyer_before_stripe(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """The race the reservation design exists for: the loser is
        refused before their card is touched, not after."""
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000, max_redemptions=1)

        buy_ticket(space, event, make_user(role="user"), code="FAMILY50")
        calls_after_first = len(stripe_spy.calls)

        r = buy_ticket(space, event, make_user(role="user"), code="FAMILY50")

        assert r.status_code == 409, r.text
        assert len(stripe_spy.calls) == calls_after_first

    def test_a_retry_of_the_same_ticket_reuses_its_own_hold(
        self, db, buy_ticket, founding, make_space, make_event, make_user,
        stripe_spy,
    ):
        """A member who reloads must not be told the code is fully used
        by their own reservation."""
        creator = founding()
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=TICKET_CENTS)
        make_code(db, space, percent_bps=5000, max_redemptions=1)
        buyer = make_user(role="user")

        buy_ticket(space, event, buyer, code="FAMILY50")
        r = buy_ticket(space, event, buyer, code="FAMILY50")

        assert r.status_code == 200, r.text
        assert db.query(DiscountReservation).count() == 1


# ---------------------------------------------------------------------------
# The Gathering Series door
# ---------------------------------------------------------------------------


class TestADiscountedGatheringSeriesPurchase:
    """§15: use the existing Series purchasing arrangement model, and do
    not introduce another direct Series checkout mechanism.

    So there is nothing Series-specific about the discount here — this
    is a Payment Option purchase, and the code goes through the same hold
    every other Option purchase uses. These tests exist to prove that
    rather than to describe a new path.
    """

    def _series(self, db, space, *, status: str = "published"):
        from app.models.platform import EventSeries

        s = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="Sunday Slow Down",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=60), status=status,
        )
        db.add(s)
        db.commit()
        return s

    def _series_option(self, db, space, series, *, cents: int = 9_900):
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        from app.models.payment_option_grant import PaymentOptionGrant
        from app.models.payment_option_schedule import PaymentOptionSchedule

        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="event_series", attaches_to_id=series.id,
            name="Term Pass", payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=cents, currency="AUD",
        )
        db.add(opt)
        db.flush()
        db.add(PaymentOptionGrant(
            payment_option_id=opt.id, grant_kind="event_series",
            series_id=series.id,
        ))
        sched = PaymentOptionSchedule(
            payment_option_id=opt.id, name="Pay in full",
            schedule_type="pay_in_full", status="published",
            total_amount_cents=cents, currency="AUD",
        )
        db.add(sched)
        db.commit()
        return opt, sched

    def _buy(self, db, user, *, series, option, schedule, code=None):
        from app.checkout.routes import create_gathering_series_checkout_session
        from app.checkout.schemas import GatheringSeriesCheckoutRequest

        return create_gathering_series_checkout_session(
            GatheringSeriesCheckoutRequest(
                series_id=series.id,
                payment_option_id=option.id,
                payment_option_schedule_id=schedule.id,
                success_url="https://ok/s", cancel_url="https://ok/c",
                discount_code=code,
            ),
            current_user=user, db=db,
        )

    def test_a_collective_wide_code_lowers_the_charge(
        self, db, make_space, make_user, stripe_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        space, buyer = make_space(), make_user()
        series = self._series(db, space)
        option, sched = self._series_option(db, space, series, cents=9_900)
        make_code(db, space, percent_bps=5000)

        self._buy(
            db, buyer, series=series, option=option, schedule=sched,
            code="FAMILY50",
        )

        assert stripe_spy.unit_amount == 4_950

    def test_the_slot_is_held_as_a_payment_option_purchase(
        self, db, make_space, make_user, stripe_spy, monkeypatch,
    ):
        """Not a ``gathering`` target — §15's point. A Series pass is an
        Option purchase, so it identifies as one."""
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        space, buyer = make_space(), make_user()
        series = self._series(db, space)
        option, sched = self._series_option(db, space, series)
        make_code(db, space, percent_bps=5000)

        self._buy(
            db, buyer, series=series, option=option, schedule=sched,
            code="FAMILY50",
        )

        r = db.query(DiscountReservation).one()
        assert r.target_kind == DiscountTargetKind.payment_option.value
        assert r.payment_option_id == option.id
        assert r.target_id is None

    def test_a_code_scoped_to_this_option_applies(
        self, db, make_space, make_user, stripe_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        space, buyer = make_space(), make_user()
        series = self._series(db, space)
        option, sched = self._series_option(db, space, series, cents=9_900)
        make_code(
            db, space, code="TERM20", percent_bps=2000,
            scope_kind="payment_option", scope_id=option.id,
        )

        self._buy(
            db, buyer, series=series, option=option, schedule=sched,
            code="TERM20",
        )

        assert stripe_spy.unit_amount == 7_920

    def test_an_undiscounted_series_purchase_is_unchanged(
        self, db, make_space, make_user, stripe_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        space, buyer = make_space(), make_user()
        series = self._series(db, space)
        option, sched = self._series_option(db, space, series, cents=9_900)

        self._buy(db, buyer, series=series, option=option, schedule=sched)

        assert stripe_spy.unit_amount == 9_900
        assert db.query(DiscountReservation).count() == 0

    def test_a_code_is_refused_while_the_flag_is_off(
        self, db, make_space, make_user, stripe_spy, monkeypatch,
    ):
        monkeypatch.setattr(settings, "universal_discount_codes_enabled", False)
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
        space, buyer = make_space(), make_user()
        series = self._series(db, space)
        option, sched = self._series_option(db, space, series)
        make_code(db, space, percent_bps=5000)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._buy(
                db, buyer, series=series, option=option, schedule=sched,
                code="FAMILY50",
            )

        assert exc.value.status_code == 400
        assert stripe_spy.calls == []
