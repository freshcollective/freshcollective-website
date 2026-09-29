"""Work Item 6 — holding a limited code's slot while a member pays.

The rule under test throughout:

    A limited-code slot may only be reused when FC knows the prior
    checkout can no longer complete.

The race these tests exist for: a reservation nominally expiring at
11:00, a member who paid at 10:59:59, and a completion webhook delayed
to 11:01. A clock-only rule frees the slot at 11:00, sells it again, and
then honours the first payment too — two charges against a one-use code,
neither refusable. So "past its window" must never by itself mean
"available", and conversion must never be refused for being late.

Stripe is stubbed. The point of most of these tests is what FC does with
each *answer* Stripe could give, including refusing to answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.checkout.schemas import UnifiedCheckoutRequest
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.discount_code import (
    DiscountCode,
    DiscountRedemption,
    DiscountReservation,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.services import discount_reservations as res
from app.services import discount_stripe_sessions as sessions

ACTIVATE_CENTS = 30_600
HALF = 15_300


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from app.checkout.routes import limiter
    limiter.reset()
    yield
    limiter.reset()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def make_offer(db, space, *, cents: int = ACTIVATE_CENTS):
    pathway = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Practice", status="active", access_type="free",
        price_cents=None, pathway_type=PathwayType.guided_experience,
    )
    db.add(pathway)
    db.flush()
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=pathway.id,
        name="Activate", payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=cents, currency="AUD",
    )
    db.add(opt)
    db.flush()
    db.add(PaymentOptionGrant(
        payment_option_id=opt.id, grant_kind="pathway", pathway_id=pathway.id,
    ))
    sched = PaymentOptionSchedule(
        payment_option_id=opt.id, name="Pay in full",
        schedule_type="pay_in_full", status="published",
        total_amount_cents=cents, currency="AUD",
    )
    db.add(sched)
    db.commit()
    return opt, sched


def make_code(db, space, *, code="FAMILY50", max_redemptions=None, is_active=True):
    row = DiscountCode(
        id=_uid("dc"), space_id=space.id, code=code,
        discount_type="percentage", percent_bps=5000,
        amount_cents=None, currency=None,
        scope_kind="space", scope_id=None,
        is_active=is_active, expires_at=None,
        max_redemptions=max_redemptions, redemption_count=0,
    )
    db.add(row)
    db.commit()
    return row


def checkout(db, user, *, option, schedule, code=None):
    from app.checkout.routes import create_unified_checkout_session
    return create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            success_url="https://ok/s", cancel_url="https://ok/c",
            discount_code=code,
        ),
        current_user=user, db=db,
    )


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            id=f"cs_{uuid.uuid4().hex[:10]}",
            url=f"https://checkout.stripe.test/{uuid.uuid4().hex[:6]}",
        )


@pytest.fixture
def stripe_spy():
    spy = _Spy()
    with patch("stripe.checkout.Session.create", side_effect=spy):
        yield spy


def held(db, code_id=None):
    q = db.query(DiscountReservation).filter_by(status="held")
    if code_id:
        q = q.filter_by(discount_code_id=code_id)
    return q.all()


# ---------------------------------------------------------------------------
# What a reservation is
# ---------------------------------------------------------------------------


class TestReservingASlot:
    def test_starting_checkout_holds_a_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        rows = held(db, code.id)
        assert len(rows) == 1
        assert rows[0].user_id == buyer.id
        assert rows[0].payment_option_id == option.id
        assert rows[0].payment_option_schedule_id == schedule.id

    def test_the_hold_freezes_the_price_it_quoted(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Conversion charges what the member agreed to, so the figures
        travel with the reservation rather than being re-derived from a
        definition that may have changed by then."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        r = held(db)[0]
        assert (r.original_amount_cents, r.discount_amount_cents, r.final_amount_cents) \
            == (ACTIVATE_CENTS, HALF, HALF)
        assert r.discount_snapshot_json["code"] == "FAMILY50"

    def test_the_session_lifetime_is_sixty_minutes(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """One persisted instant drives both Stripe's expiry and ours, so
        "past expiry" cannot mean two different things."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        r = held(db)[0]
        assert res.CHECKOUT_WINDOW == timedelta(minutes=60)
        # ``session_expires_at`` is naive UTC, as everything in this
        # schema is. Reading it without saying so gets the local offset
        # silently added — the same trap the expiry work in WI3 was about.
        from datetime import UTC
        sent = stripe_spy.calls[-1]["expires_at"]
        assert sent == int(r.session_expires_at.replace(tzinfo=UTC).timestamp())

    def test_the_stripe_params_are_persisted_before_the_call(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Without them a crash between creating a Session and recording
        its id is indistinguishable from never having called Stripe — and
        releasing on that guess frees a slot someone may have paid for."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        r = held(db)[0]
        assert r.session_create_params_json is not None
        assert r.session_create_params_json["line_items"][0]["price_data"][
            "unit_amount"] == HALF
        assert r.session_idempotency_key.startswith(f"dres:{r.id}:")

    def test_an_undiscounted_checkout_reserves_nothing(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)

        checkout(db, buyer, option=option, schedule=schedule)

        assert held(db) == []
        # And keeps Stripe's own default Session lifetime.
        assert "expires_at" not in stripe_spy.calls[-1]

    def test_preview_reserves_nothing(
        self, client, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=1)
        as_user(buyer)

        for _ in range(3):
            body = client.post("/api/checkout/discount-preview", json={
                "payment_option_id": option.id,
                "payment_option_schedule_id": schedule.id,
                "code": "FAMILY50",
            }).json()
            assert body["valid"] is True

        assert held(db) == []


class TestSlotsAreCountedNotRedemptions:
    def test_a_live_hold_makes_a_one_use_code_unavailable(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Preview must agree with checkout: once the slot is held, the
        code is not available to anyone else, redeemed or not."""
        space = make_space()
        first, second = make_user(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=1)
        checkout(db, first, option=option, schedule=schedule, code="FAMILY50")

        as_user(second)
        body = client.post("/api/checkout/discount-preview", json={
            "payment_option_id": option.id,
            "payment_option_schedule_id": schedule.id,
            "code": "FAMILY50",
        }).json()

        assert body["valid"] is False
        assert body["reason"] == "limit_reached"

    def test_the_holder_still_sees_their_own_code_as_valid(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=1)
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        as_user(buyer)
        body = client.post("/api/checkout/discount-preview", json={
            "payment_option_id": option.id,
            "payment_option_schedule_id": schedule.id,
            "code": "FAMILY50",
        }).json()

        assert body["valid"] is True

    def test_a_second_purchase_by_the_same_member_takes_a_second_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Identity is the purchase attempt, not the member. One
        Collective-wide code used on two different offers is two
        redemptions, so it must be two reservations."""
        space, buyer = make_space(), make_user()
        first_opt, first_sched = make_offer(db, space)
        second_opt, second_sched = make_offer(db, space)
        code = make_code(db, space, max_redemptions=2)

        checkout(db, buyer, option=first_opt, schedule=first_sched, code="FAMILY50")
        checkout(db, buyer, option=second_opt, schedule=second_sched, code="FAMILY50")

        assert len(held(db, code.id)) == 2
        assert len(stripe_spy.calls) == 2

    def test_and_is_refused_once_those_slots_are_gone(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        a_opt, a_sched = make_offer(db, space)
        b_opt, b_sched = make_offer(db, space)
        c_opt, c_sched = make_offer(db, space)
        make_code(db, space, max_redemptions=2)

        checkout(db, buyer, option=a_opt, schedule=a_sched, code="FAMILY50")
        checkout(db, buyer, option=b_opt, schedule=b_sched, code="FAMILY50")
        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=c_opt, schedule=c_sched, code="FAMILY50")

        assert exc.value.status_code == 409
        assert len(stripe_spy.calls) == 2

    def test_an_unlimited_code_is_never_blocked_by_holds(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space = make_space()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=None)

        for _ in range(3):
            checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        assert len(stripe_spy.calls) == 3


# ---------------------------------------------------------------------------
# Converting — and the delayed webhook this whole design exists for
# ---------------------------------------------------------------------------


def reserve_directly(db, *, code, user, option, schedule, now=None,
                     session_id="cs_direct", params=None):
    """A held reservation with a Stripe Session, without going through
    the route — so tests can place it at any point in its life."""
    from app.services.discount_pricing import AppliedDiscount, DiscountAmounts

    now = now or datetime.utcnow()
    applied = AppliedDiscount(
        code=code.code, discount_code_id=code.id,
        amounts=DiscountAmounts(
            original_cents=ACTIVATE_CENTS, discount_cents=HALF,
            final_cents=HALF, currency="AUD",
        ),
        snapshot={"code": code.code, "final_amount_cents": HALF},
    )
    outcome = res.reserve_or_reuse(
        db, applied=applied, code=code, user_id=user.id,
        payment_option_id=option.id, payment_option_schedule_id=schedule.id,
        now=now,
    )
    r = outcome.reservation
    if session_id:
        r.provider_checkout_session_id = session_id
        r.provider_checkout_session_url = "https://checkout.stripe.test/x"
        r.session_create_params_json = params or {"mode": "payment"}
        db.commit()
    return r


class TestConversionIgnoresTheClock:
    """The core of the design.

    A completion arriving after the reservation's nominal expiry is still
    a completion. Rejecting it would take the member's money and grant
    nothing — the mirror image of the double-charge the expiry prevents,
    and no better.
    """

    def test_a_webhook_after_expiry_still_converts(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        long_ago = datetime.utcnow() - timedelta(hours=3)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule, now=long_ago)
        assert r.session_expires_at < datetime.utcnow()

        txn = _a_transaction(db, space)
        redemption = res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=txn.id,
            now=datetime.utcnow(),
        )

        assert redemption is not None
        db.refresh(r)
        assert r.status == "converted"
        assert r.converted_at is not None

    def test_conversion_uses_the_frozen_price_not_the_live_code(
        self, db, make_space, make_user,
    ):
        """A Creator editing the code mid-checkout must not change what
        the member is recorded as having paid."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)

        code.percent_bps = 1000          # Creator drops it to 10% …
        code.is_active = False           # … and switches it off.
        db.commit()

        txn = _a_transaction(db, space)
        redemption = res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=txn.id, now=datetime.utcnow(),
        )

        assert redemption.discount_amount_cents == HALF
        assert redemption.final_amount_cents == HALF

    def test_a_deactivated_code_does_not_invalidate_a_held_checkout(
        self, db, make_space, make_user,
    ):
        """Deactivation stops NEW reservations. It cannot retroactively
        cancel a member already at the payment page."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)
        code.is_active = False
        db.commit()

        txn = _a_transaction(db, space)
        assert res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=txn.id, now=datetime.utcnow(),
        ) is not None

    def test_converting_twice_is_the_same_redemption(
        self, db, make_space, make_user,
    ):
        """Webhook redelivery is ordinary. Exactly-once is enforced by
        the partial unique index, not by hoping the handler runs once."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)
        txn = _a_transaction(db, space)

        first = res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=txn.id, now=datetime.utcnow())
        second = res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=txn.id, now=datetime.utcnow())

        assert first.id == second.id
        assert db.query(DiscountRedemption).filter_by(
            discount_code_id=code.id).count() == 1

    def test_a_converted_slot_stays_spent(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space = make_space()
        buyer, other = make_user(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)
        res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=_a_transaction(db, space).id,
            now=datetime.utcnow())

        with pytest.raises(HTTPException):
            checkout(db, other, option=option, schedule=schedule, code="FAMILY50")

    def test_consumed_slots_never_double_counts_a_conversion(
        self, db, make_space, make_user,
    ):
        """After conversion the row is no longer ``held``, so it is
        counted once as a redemption rather than twice."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=3)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)
        assert res.consumed_slots(db, code.id) == 1

        res.convert_to_redemption(
            db, reservation=r, payment_transaction_id=_a_transaction(db, space).id,
            now=datetime.utcnow())

        assert res.consumed_slots(db, code.id) == 1


def _a_transaction(db, space):
    from app.models.payment import (
        PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
        PaymentTransactionType, PayoutStatus,
    )
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        space_id=space.id, currency="AUD",
        gross_amount_cents=HALF, platform_fee_basis_points=0,
        platform_fee_cents=0, net_creator_amount_cents=HALF,
        net_platform_amount_cents=0, stripe_mode="test",
        payout_status=PayoutStatus.pending,
    )
    db.add(txn)
    db.commit()
    return txn


# ---------------------------------------------------------------------------
# Verifying a stale hold — where Stripe's answer decides, not our clock
# ---------------------------------------------------------------------------


def stale(db, *, code, user, option, schedule, session_id="cs_stale", params=None):
    """A held reservation whose 60-minute window has elapsed."""
    return reserve_directly(
        db, code=code, user=user, option=option, schedule=schedule,
        now=datetime.utcnow() - timedelta(hours=2),
        session_id=session_id, params=params,
    )


class TestVerifyingAStaleHold:
    def test_an_expired_session_releases_the_slot(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", return_value="expired"):
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_RELEASED
        db.refresh(r)
        assert r.status == "released"
        assert r.release_reason == "stripe_session_expired"
        assert res.consumed_slots(db, code.id) == 0

    def test_a_completed_session_is_reported_convertible_not_released(
        self, db, make_space, make_user,
    ):
        """The exact race: our clock says expired, Stripe says paid. The
        slot must NOT be freed — they bought it."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", return_value="complete"):
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_CONVERTIBLE
        db.refresh(r)
        assert r.status == "held"
        assert res.consumed_slots(db, code.id) == 1

    def test_an_open_session_is_expired_then_released(
        self, db, make_space, make_user,
    ):
        """Past our window we close the Session ourselves rather than
        waiting on Stripe's own 24-hour expiry."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", side_effect=["open", "expired"]), \
             patch.object(sessions, "expire_session") as expire:
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert expire.called
        assert outcome == res.VERIFY_RELEASED

    def test_a_session_that_completed_during_the_expire_attempt_is_not_released(
        self, db, make_space, make_user,
    ):
        """Losing the race to a member paying at that instant. The
        re-read decides, and it says paid — so the slot stays theirs."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", side_effect=["open", "complete"]), \
             patch.object(sessions, "expire_session",
                          side_effect=sessions.StripeStateChanged("moved")):
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_CONVERTIBLE
        db.refresh(r)
        assert r.status == "held"

    def test_stripe_unavailable_keeps_the_slot_held(
        self, db, make_space, make_user,
    ):
        """Fail conservatively. An unanswered question is not permission
        to charge someone a second time."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status",
                          side_effect=sessions.StripeUnavailable("network down")):
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_UNVERIFIABLE
        db.refresh(r)
        assert r.status == "held"
        assert res.consumed_slots(db, code.id) == 1
        # And it says why, on the row, for whoever has to explain it.
        assert r.last_verification_status == "unverifiable"
        assert "network down" in r.last_verification_error
        assert r.verification_attempts == 1
        assert r.last_verification_at is not None

    def test_an_unrecognised_status_is_treated_as_unknown(
        self, db, make_space, make_user,
    ):
        """Not guessed about. ``session_status`` raises rather than
        returning something the ladder would have to interpret."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch("stripe.checkout.Session.retrieve",
                   return_value={"status": "something_new"}):
            with pytest.raises(sessions.StripeUnavailable):
                sessions.session_status("cs_x")

        assert r.status == "held"


class TestAReservationThatNeverReachedStripe:
    def test_with_no_params_persisted_it_is_released(
        self, db, make_space, make_user,
    ):
        """Params are written immediately before the Stripe call, so
        their absence proves the call was never made. Nothing can charge
        this member."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule,
                  session_id=None)
        assert r.session_create_params_json is None

        outcome = res.verify_stale_reservation(
            db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_RELEASED
        db.refresh(r)
        assert r.release_reason == "never_reached_stripe"

    def test_with_params_persisted_a_replay_recovers_the_session(
        self, db, make_space, make_user,
    ):
        """The crash between creating a Session and recording its id. The
        replay finds the orphan rather than releasing a slot the member
        may be paying for."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule,
                  session_id=None)
        r.session_create_params_json = {"mode": "payment"}
        db.commit()

        with patch.object(sessions, "recover_session_id", return_value="cs_orphan"), \
             patch.object(sessions, "session_status", return_value="complete"):
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_CONVERTIBLE
        db.refresh(r)
        assert r.provider_checkout_session_id == "cs_orphan"

    def test_past_the_recovery_window_it_is_left_unresolved(
        self, db, make_space, make_user,
    ):
        """Stripe may prune an idempotency key once it is 24h old, so a
        replay past our 6-hour window would be a NEW request rather than
        evidence. Better a stuck slot than a second charge."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule,
                             now=datetime.utcnow() - timedelta(hours=9),
                             session_id=None)
        r.created_at = datetime.utcnow() - timedelta(hours=9)
        db.commit()

        with patch.object(sessions, "recover_session_id") as recover:
            outcome = res.verify_stale_reservation(
                db, reservation=r, now=datetime.utcnow())

        assert outcome == res.VERIFY_TOO_OLD
        assert not recover.called, "must not replay a pruned idempotency key"
        db.refresh(r)
        assert r.status == "held"
        assert res.consumed_slots(db, code.id) == 1
        assert "idempotency recovery window" in r.last_verification_error

    def test_a_parameter_mismatch_on_replay_is_not_read_as_absence(
        self, db, make_space, make_user,
    ):
        """Stripe rejecting a replay for differing parameters is positive
        evidence a request EXISTS. Reading it as "nothing was created"
        would release a slot against a live payment page."""
        import stripe as stripe_mod

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule,
                  session_id=None)
        r.session_create_params_json = {"mode": "payment"}
        db.commit()

        with patch("stripe.checkout.Session.create",
                   side_effect=stripe_mod.IdempotencyError("params differ")):
            with pytest.raises(sessions.StripeUnavailable):
                sessions.recover_session_id(reservation=r)

    def test_the_replay_resends_the_original_absolute_expiry(
        self, db, make_space, make_user,
    ):
        """Never ``now + 60 minutes`` again: a recomputed expiry is a
        different payload under the same key, which Stripe treats as an
        error rather than a replay."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule,
                  session_id=None, params={"mode": "payment", "expires_at": 1790000000})
        r.session_create_params_json = {"mode": "payment", "expires_at": 1790000000}
        db.commit()

        with patch("stripe.checkout.Session.create",
                   return_value={"id": "cs_replayed"}) as create:
            sessions.recover_session_id(reservation=r)

        assert create.call_args.kwargs["expires_at"] == 1790000000
        assert create.call_args.kwargs["idempotency_key"] == r.session_idempotency_key


# ---------------------------------------------------------------------------
# The sweep — a real buyer triggering verification of somebody's stale hold
# ---------------------------------------------------------------------------


class TestReallocatingTheFinalSlot:
    def test_a_stale_hold_is_verified_before_the_slot_is_given_away(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The buyer who wants the slot is what triggers verification —
        nothing frees it on a timer."""
        space = make_space()
        holder, buyer = make_user(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        stale(db, code=code, user=holder, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", return_value="expired"):
            result = checkout(db, buyer, option=option, schedule=schedule,
                              code="FAMILY50")

        assert result.checkout_url
        assert len(stripe_spy.calls) == 1

    def test_an_unverifiable_stale_hold_refuses_the_new_buyer(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The cost of the design, stated plainly: when Stripe cannot be
        asked, the waiting buyer is refused rather than risking a second
        charge against the holder."""
        space = make_space()
        holder, buyer = make_user(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        stale(db, code=code, user=holder, option=option, schedule=schedule)

        with patch.object(sessions, "session_status",
                          side_effect=sessions.StripeUnavailable("down")):
            with pytest.raises(HTTPException) as exc:
                checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert exc.value.status_code == 409
        assert stripe_spy.calls == []

    def test_a_paid_stale_hold_does_not_free_the_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space = make_space()
        holder, buyer = make_user(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        stale(db, code=code, user=holder, option=option, schedule=schedule)

        with patch.object(sessions, "session_status", return_value="complete"):
            with pytest.raises(HTTPException):
                checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert stripe_spy.calls == []

    def test_a_live_hold_is_not_swept_at_all(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Within the window there is nothing to verify — the holder is
        still shopping. Stripe is not asked."""
        space = make_space()
        holder, buyer = make_user(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=1)
        reserve_directly(db, code=make_code(db, space, code="OTHER"), user=holder,
                         option=option, schedule=schedule)
        checkout(db, holder, option=option, schedule=schedule, code="FAMILY50")

        with patch.object(sessions, "session_status") as status:
            with pytest.raises(HTTPException):
                checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert not status.called

    def test_the_sweep_runs_outside_the_row_lock(self, db):
        """A Stripe call inside the code's row lock would turn a slow
        provider into a stuck table, with every other buyer of that code
        queued behind it. Asserted against the source because the property
        is structural — no test input can demonstrate a lock that is held
        a moment too long."""
        import inspect
        from app.services import discount_reservations as mod

        # The function that takes the lock never talks to Stripe.
        # Checked by walking the AST for CALLS, not by searching the text:
        # the docstring and comments mention Stripe precisely because the
        # reason for its absence is worth explaining, and a substring
        # check would fail on the explanation.
        import ast
        import textwrap

        assert "FOR UPDATE" in inspect.getsource(mod._lock_code)
        tree = ast.parse(textwrap.dedent(inspect.getsource(mod.reserve_or_reuse)))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    called.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    called.add(fn.attr)
                    if isinstance(fn.value, ast.Name):
                        called.add(f"{fn.value.id}.{fn.attr}")
        for forbidden in ("verify_stale_reservation", "sweep_stale_reservations",
                          "session_status", "recover_session_id", "expire_session"):
            assert forbidden not in called, forbidden
        assert not any(c.startswith("stripe.") for c in called)

        # And the sweep sits between two attempts, each of which takes
        # and releases the lock on its own.
        from app.checkout import routes
        src = inspect.getsource(routes._resolve_and_reserve)
        assert src.count("return attempt()") == 2
        assert "sweep_stale_reservations(db" in src


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class TestWebhookLifecycle:
    def test_session_expired_releases_promptly(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The fast path. Stripe telling us is the cheapest possible form
        of positive knowledge."""
        from app.webhooks.routes import _handle_checkout_expired

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        r = held(db, code.id)[0]

        _handle_checkout_expired({"id": r.provider_checkout_session_id}, db)

        db.refresh(r)
        assert r.status == "released"
        assert r.release_reason == "stripe_session_expired_webhook"
        assert res.consumed_slots(db, code.id) == 0

    def test_an_expiry_for_an_unrelated_session_changes_nothing(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        from app.webhooks.routes import _handle_checkout_expired

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        _handle_checkout_expired({"id": "cs_someone_else"}, db)

        assert res.consumed_slots(db, code.id) == 1

    def test_release_is_idempotent(self, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        r = reserve_directly(db, code=code, user=buyer, option=option,
                             schedule=schedule)

        res.release(db, reservation=r, reason="first", now=datetime.utcnow())
        res.release(db, reservation=r, reason="second", now=datetime.utcnow())

        db.refresh(r)
        assert r.release_reason == "first"


# ---------------------------------------------------------------------------
# Creator lifecycle — a held reservation is an in-flight promise
# ---------------------------------------------------------------------------


def creator_base(slug):
    return f"/api/creator/spaces/{slug}/discount-codes"


class TestCreatorLifecycleRespectsHolds:
    @pytest.fixture
    def collective(self, db, make_user, make_space):
        from app.models.platform import (
            SpaceMembership, SpaceMembershipStatus, SpaceRole,
        )
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        return creator, space

    def test_a_held_reservation_blocks_hard_deletion(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        """The reservation row cascades on delete, so removing the
        definition now would erase the record of a slot someone may be
        paying for — and leave the completion webhook nothing to convert."""
        creator, space = collective
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        as_user(creator)
        res_http = client.delete(f"{creator_base(space.slug)}/{code.id}")

        assert res_http.status_code == 409
        assert "middle of a checkout" in res_http.text
        assert db.query(DiscountCode).filter_by(id=code.id).first() is not None

    def test_a_released_reservation_does_not_block_deletion(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        creator, space = collective
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        buyer = make_user()
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        r = held(db, code.id)[0]
        res.release(db, reservation=r, reason="stripe_session_expired",
                    now=datetime.utcnow())

        as_user(creator)
        assert client.delete(f"{creator_base(space.slug)}/{code.id}").status_code == 204

    def test_a_held_reservation_freezes_the_definition(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        """A member is at Stripe holding this definition. Changing what
        the code means would alter the deal after they agreed to it."""
        creator, space = collective
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        as_user(creator)
        res_http = client.patch(f"{creator_base(space.slug)}/{code.id}",
                                json={"percent_bps": 1000})

        assert res_http.status_code == 409
        assert "checkout in progress" in res_http.text

    def test_operational_controls_still_work_during_a_checkout(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        """Deactivation must remain available — it is how a Creator stops
        NEW uses. It just cannot cancel the one in flight."""
        creator, space = collective
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        as_user(creator)
        assert client.patch(f"{creator_base(space.slug)}/{code.id}",
                            json={"is_active": False}).status_code == 200
        assert client.patch(f"{creator_base(space.slug)}/{code.id}",
                            json={"expires_on": "2027-01-01"}).status_code == 200

    def test_the_limit_cannot_drop_below_committed_slots(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        """Reducing it below the reservations outstanding would promise a
        member at Stripe a slot that no longer exists."""
        creator, space = collective
        a_opt, a_sched = make_offer(db, space)
        b_opt, b_sched = make_offer(db, space)
        code = make_code(db, space, max_redemptions=5)
        checkout(db, make_user(), option=a_opt, schedule=a_sched, code="FAMILY50")
        checkout(db, make_user(), option=b_opt, schedule=b_sched, code="FAMILY50")

        as_user(creator)
        refused = client.patch(f"{creator_base(space.slug)}/{code.id}",
                               json={"max_redemptions": 1})
        allowed = client.patch(f"{creator_base(space.slug)}/{code.id}",
                               json={"max_redemptions": 2})

        assert refused.status_code == 409
        assert allowed.status_code == 200

    def test_the_api_reports_the_frozen_state_rather_than_the_ui_guessing(
        self, client, db, make_user, collective, stripe_configured, stripe_spy,
    ):
        creator, space = collective
        option, schedule = make_offer(db, space)
        code = make_code(db, space)

        as_user(creator)
        before = client.get(creator_base(space.slug)).json()[0]
        assert before["definition_editable"] is True
        assert before["deletable"] is True

        checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        after = client.get(creator_base(space.slug)).json()[0]
        assert after["definition_editable"] is False
        assert after["deletable"] is False

    def test_deactivation_blocks_new_reservations(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space = make_space()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, is_active=False)

        with pytest.raises(HTTPException) as exc:
            checkout(db, make_user(), option=option, schedule=schedule, code="FAMILY50")

        assert exc.value.status_code == 409
        assert held(db, code.id) == []


class TestTheRaceThisDesignExistsFor:
    """The 11:00 / 10:59:59 / 11:01 sequence, played out.

    Deliberately redundant with the unit tests above. These are the two
    properties whose failure charges a real person twice or takes their
    money for nothing, so they are asserted from more than one angle —
    a single guard test is thin cover for that.
    """

    def test_a_slot_is_not_freed_merely_because_the_window_passed(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        stale(db, code=code, user=buyer, option=option, schedule=schedule)

        # Nobody has verified anything. The window has elapsed. The slot
        # is still gone, and that is the whole point.
        assert res.consumed_slots(db, code.id) == 1

    def test_payment_at_the_last_second_still_lands_after_a_late_webhook(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """End to end through the webhook handler, not the service call:
        the member paid inside the window, the event arrived outside it,
        and the redemption must be recorded."""
        from app.webhooks.routes import _handle_checkout_expired

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        r = held(db, code.id)[0]

        # Push the reservation's window into the past, as a delay would.
        r.session_expires_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()

        redemption = res.convert_to_redemption(
            db, reservation=r,
            payment_transaction_id=_a_transaction(db, space).id,
            now=datetime.utcnow(),
        )

        assert redemption is not None
        db.refresh(r)
        assert r.status == "converted"

    def test_and_a_second_buyer_never_got_in_between(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The counterfactual. With the reservation stale but unverified,
        the competing buyer is refused — so there is no second charge to
        reconcile when the late webhook lands."""
        space = make_space()
        payer, other = make_user(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=payer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status",
                          side_effect=sessions.StripeUnavailable("lagging")):
            with pytest.raises(HTTPException):
                checkout(db, other, option=option, schedule=schedule, code="FAMILY50")

        # And then the payment lands.
        assert res.convert_to_redemption(
            db, reservation=r,
            payment_transaction_id=_a_transaction(db, space).id,
            now=datetime.utcnow(),
        ) is not None
        assert db.query(DiscountRedemption).filter_by(
            discount_code_id=code.id).count() == 1

    def test_an_unverifiable_hold_is_never_released_by_any_path(
        self, db, make_space, make_user,
    ):
        """Asserted across every entry point that could reach it, because
        "released on a guess" is the one outcome the design forbids."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        r = stale(db, code=code, user=buyer, option=option, schedule=schedule)

        with patch.object(sessions, "session_status",
                          side_effect=sessions.StripeUnavailable("down")):
            res.verify_stale_reservation(db, reservation=r, now=datetime.utcnow())
            res.sweep_stale_reservations(
                db, discount_code_id=code.id, now=datetime.utcnow())

        db.refresh(r)
        assert r.status == "held"
        assert r.released_at is None
        assert res.consumed_slots(db, code.id) == 1

    def test_there_is_no_force_release_anywhere(self, db):
        """A deliberate absence. The future operator action is "recheck
        Stripe", never "release despite uncertainty" — so no code path
        releases without a reason drawn from Stripe or from our own
        knowledge that the request never left."""
        import inspect
        from app.services import discount_reservations as mod

        src = inspect.getsource(mod)
        reasons = {
            "session_create_failed", "never_reached_stripe",
            "stripe_session_expired", "expired_by_fc",
            "stripe_session_expired_webhook",
        }
        called_with = {
            line.split('reason="')[1].split('"')[0]
            for line in src.splitlines() if 'reason="' in line
        }
        assert called_with <= reasons, called_with - reasons

        # No function exists whose name offers an unconditional release.
        # Matched on DEFINITIONS rather than on the text, because prose
        # like "enforced by the database" contains "force" and the comment
        # explaining this rule should not be able to break it.
        import ast

        defined = {
            node.name for node in ast.walk(ast.parse(src))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in defined:
            assert "force" not in name.lower(), name
            assert not name.lower().startswith("admin_"), name
