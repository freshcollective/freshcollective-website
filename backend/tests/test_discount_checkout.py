"""Work Item 4 — previewing a discount code, and charging the result.

Two surfaces, one authority. The preview endpoint answers "what would
this cost?" and the checkout endpoint decides what to charge, and both
reach the same figure through ``discount_application.resolve_discount``.
The tests below care mostly about that: not just that each surface is
right on its own, but that they cannot drift apart, and that the one
which takes money does not trust the one that merely answered a
question.

The reference shape is EMBODY's, verified against production: Activate
pay-in-full is $306, and a 50% code must preview and charge $153.

Redemption is NOT recorded here. A preview is a question and a checkout
session is an intention; neither is a purchase. Consuming a code at
either point would burn a limited code on a member who wandered off at
the Stripe page. That is Work Item 6's, and these tests assert the
ledger stays empty to keep it that way.
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
from app.checkout.schemas import DiscountPreviewRequest, UnifiedCheckoutRequest
from app.core.config import settings
from app.core.database import get_db
from app.core.money import MIN_PAID_CHARGE_CENTS
from app.main import app
from app.models.discount_code import DiscountCode, DiscountRedemption
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType


# EMBODY Activate, pay in full, as verified in production.
ACTIVATE_CENTS = 30_600
HALF_OF_ACTIVATE = 15_300


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """The preview endpoint is rate limited on purpose; a test run is not
    a brute-force attempt. Reset between tests so the limit stays real in
    production without making the suite order-dependent."""
    from app.checkout.routes import limiter
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _make_pathway(db, space) -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Practice", status="active", access_type="free",
        price_cents=None, pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def make_offer(db, space, *, cents: int = ACTIVATE_CENTS, currency: str = "AUD",
               schedule_type: str = "pay_in_full"):
    """A published, purchasable Payment Option with one Pathway grant.

    Mirrors the live EMBODY shape: one_time, priced on the schedule, with
    a grant so fulfilment has something to resolve.
    """
    pathway = _make_pathway(db, space)
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=pathway.id,
        name="Activate", payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=cents, currency=currency,
    )
    db.add(opt)
    db.flush()
    db.add(PaymentOptionGrant(
        payment_option_id=opt.id, grant_kind="pathway", pathway_id=pathway.id,
    ))
    sched = PaymentOptionSchedule(
        payment_option_id=opt.id, name="Pay in full",
        schedule_type=schedule_type, status="published",
        total_amount_cents=cents,
        installment_amount_cents=(3_060 if schedule_type != "pay_in_full" else None),
        installment_count=(10 if schedule_type != "pay_in_full" else None),
        currency=currency,
    )
    db.add(sched)
    db.commit()
    return opt, sched


def make_code(db, space, *, code: str = "FAMILY50", discount_type: str = "percentage",
              percent_bps: int | None = 5000, amount_cents: int | None = None,
              currency: str | None = None, is_active: bool = True,
              expires_at: datetime | None = None,
              max_redemptions: int | None = None,
              scope_kind: str = "space", scope_id: str | None = None) -> DiscountCode:
    row = DiscountCode(
        id=_uid("dc"), space_id=space.id, code=code,
        discount_type=discount_type, percent_bps=percent_bps,
        amount_cents=amount_cents, currency=currency,
        scope_kind=scope_kind, scope_id=scope_id,
        is_active=is_active, expires_at=expires_at,
        max_redemptions=max_redemptions, redemption_count=0,
    )
    db.add(row)
    db.commit()
    return row


def redeem(db, code: DiscountCode, space, *, times: int = 1):
    """Write ledger rows directly — fulfilment is Work Item 6, but this
    layer must already respect redemptions that exist."""
    for _ in range(times):
        txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            space_id=space.id, currency="AUD",
            gross_amount_cents=HALF_OF_ACTIVATE, platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=HALF_OF_ACTIVATE,
            net_platform_amount_cents=0, stripe_mode="test",
            payout_status=PayoutStatus.pending,
        )
        db.add(txn)
        db.flush()
        db.add(DiscountRedemption(
            id=_uid("dr"), discount_code_id=code.id, space_id=space.id,
            payment_transaction_id=txn.id,
            original_amount_cents=ACTIVATE_CENTS,
            discount_amount_cents=HALF_OF_ACTIVATE,
            final_amount_cents=HALF_OF_ACTIVATE, currency="AUD",
        ))
    db.commit()


def preview(client, *, option, schedule, code: str):
    return client.post("/api/checkout/discount-preview", json={
        "payment_option_id": option.id,
        "payment_option_schedule_id": schedule.id,
        "code": code,
    })


def checkout(db, user, *, option, schedule, code: str | None = None):
    from app.checkout.routes import create_unified_checkout_session
    return create_unified_checkout_session(
        UnifiedCheckoutRequest(
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            success_url="https://ok/success", cancel_url="https://ok/cancel",
            discount_code=code,
        ),
        current_user=user, db=db,
    )


class _StripeSpy:
    """Captures what would have been charged.

    The unit_amount on the line item is the only number Stripe is ever
    told, so asserting on it is asserting on what the member's card is
    actually presented with — not on an internal variable that happens
    to agree.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=f"cs_{uuid.uuid4().hex[:10]}",
                               url="https://checkout.stripe.test/x")

    @property
    def unit_amount(self) -> int:
        return self.calls[-1]["line_items"][0]["price_data"]["unit_amount"]

    @property
    def currency(self) -> str:
        return self.calls[-1]["line_items"][0]["price_data"]["currency"]


@pytest.fixture
def stripe_spy():
    spy = _StripeSpy()
    with patch("stripe.checkout.Session.create", side_effect=spy):
        yield spy


# ---------------------------------------------------------------------------
# Preview — the valid cases
# ---------------------------------------------------------------------------


class TestPreviewingAValidCode:
    def test_a_percentage_code_halves_the_embody_price(self, client, db, make_space, make_user):
        """The reference case: Activate $306, 50% off, $153 to pay."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        res = preview(client, option=option, schedule=schedule, code="FAMILY50")

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is True
        assert body["original_amount_cents"] == 30_600
        assert body["discount_amount_cents"] == 15_300
        assert body["final_amount_cents"] == 15_300
        assert body["currency"] == "AUD"

    def test_a_fixed_dollar_code_takes_its_amount_off(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, code="FIFTYOFF", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=5_000, currency="AUD")
        as_user(buyer)

        res = preview(client, option=option, schedule=schedule, code="FIFTYOFF")

        body = res.json()
        assert body["valid"] is True
        assert body["discount_amount_cents"] == 5_000
        assert body["final_amount_cents"] == 25_600

    def test_the_three_figures_always_balance(self, client, db, make_space, make_user):
        """Whatever the arithmetic, the member must be able to read the
        preview as a sum that adds up."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=9_999)
        make_code(db, space, percent_bps=3_333)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="FAMILY50").json()

        assert (body["original_amount_cents"] - body["discount_amount_cents"]
                == body["final_amount_cents"])

    def test_no_code_is_consumed_by_looking(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        as_user(buyer)

        for _ in range(3):
            assert preview(client, option=option, schedule=schedule,
                           code="FAMILY50").json()["valid"] is True

        assert db.query(DiscountRedemption).filter_by(discount_code_id=code.id).count() == 0

    def test_the_code_comes_back_normalised(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="  family50 ").json()

        assert body["code"] == "FAMILY50"


class TestCaseAndWhitespaceDoNotMatter:
    """A code is read off a flyer and typed by a person."""

    @pytest.mark.parametrize("typed", [
        "FAMILY50", "family50", "Family50", "  FAMILY50  ", "\tfamily50\n",
    ])
    def test_it_is_accepted_however_it_was_typed(
        self, client, db, make_space, make_user, typed,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code=typed).json()

        assert body["valid"] is True, typed
        assert body["final_amount_cents"] == HALF_OF_ACTIVATE

    def test_and_charged_however_it_was_typed(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code="  fAmIlY50 ")

        assert stripe_spy.unit_amount == HALF_OF_ACTIVATE


# ---------------------------------------------------------------------------
# Preview — the refusals
# ---------------------------------------------------------------------------


class TestPreviewingACodeThatCannotBeUsed:
    """Each refusal is a 200 carrying a reason.

    Not a 4xx: an unrecognised code is a normal answer to a reasonable
    question, and a frontend that saw 404 could not distinguish it from a
    dropped request.
    """

    def _refusal(self, client, option, schedule, code="FAMILY50"):
        res = preview(client, option=option, schedule=schedule, code=code)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["valid"] is False
        # Nothing to render, so nothing is sent.
        assert body["final_amount_cents"] is None
        assert body["message"]
        return body

    def test_an_unknown_code(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        as_user(buyer)

        assert self._refusal(client, option, schedule, "NOPE")["reason"] == "not_found"

    def test_a_switched_off_code(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, is_active=False)
        as_user(buyer)

        assert self._refusal(client, option, schedule)["reason"] == "inactive"

    def test_an_expired_code(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, expires_at=datetime.utcnow() - timedelta(minutes=1))
        as_user(buyer)

        assert self._refusal(client, option, schedule)["reason"] == "expired"

    def test_a_code_that_expires_in_a_moment_still_works(
        self, client, db, make_space, make_user,
    ):
        """The boundary is exclusive; a code is usable right up to it."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, expires_at=datetime.utcnow() + timedelta(seconds=30))
        as_user(buyer)

        assert preview(client, option=option, schedule=schedule,
                       code="FAMILY50").json()["valid"] is True

    def test_a_fully_used_code(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=2)
        redeem(db, code, space, times=2)
        as_user(buyer)

        assert self._refusal(client, option, schedule)["reason"] == "limit_reached"

    def test_a_code_with_room_left_is_fine(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=2)
        redeem(db, code, space, times=1)
        as_user(buyer)

        assert preview(client, option=option, schedule=schedule,
                       code="FAMILY50").json()["valid"] is True

    def test_the_limit_is_read_from_the_ledger_not_the_cached_column(
        self, client, db, make_space, make_user,
    ):
        """``DiscountCode.redemption_count`` is a cache and is not
        maintained until fulfilment lands. A cache reading low would let a
        limited code over-redeem, which is the one thing the limit exists
        to prevent — so the count comes from the rows."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)
        redeem(db, code, space, times=1)
        # The cached column still says zero...
        db.refresh(code)
        assert code.redemption_count == 0
        as_user(buyer)

        # ...and the code is refused anyway.
        assert self._refusal(client, option, schedule)["reason"] == "limit_reached"

    def test_a_code_from_another_collective(self, client, db, make_space, make_user):
        """Reported as unrecognised. Saying "that belongs to someone else"
        would confirm another Creator's code exists to anyone who guessed
        it."""
        theirs, mine = make_space(), make_space()
        buyer = make_user()
        option, schedule = make_offer(db, mine)
        make_code(db, theirs, code="THEIRS50")
        as_user(buyer)

        body = self._refusal(client, option, schedule, "THEIRS50")
        assert body["reason"] == "not_found"
        assert "not recognised" in body["message"].lower()

    def test_a_code_scoped_to_a_different_offer(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        other_option, _ = make_offer(db, space)
        make_code(db, space, scope_kind="payment_option", scope_id=other_option.id)
        as_user(buyer)

        assert self._refusal(client, option, schedule)["reason"] == "wrong_payment_option"

    def test_a_code_scoped_to_this_offer_works(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, scope_kind="payment_option", scope_id=option.id)
        as_user(buyer)

        assert preview(client, option=option, schedule=schedule,
                       code="FAMILY50").json()["valid"] is True

    def test_a_fixed_code_in_the_wrong_currency(self, client, db, make_space, make_user):
        """A $50-off code cannot take 50 off a price denominated in
        something else — the number would be meaningless."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, currency="AUD")
        make_code(db, space, code="USD50", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=5_000, currency="USD")
        as_user(buyer)

        assert self._refusal(client, option, schedule, "USD50")["reason"] == "currency_mismatch"

    def test_a_percentage_code_crosses_currencies_happily(
        self, client, db, make_space, make_user,
    ):
        """Half of a price is half of it whatever the currency."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, currency="USD", cents=10_000)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="FAMILY50").json()
        assert body["valid"] is True
        assert body["final_amount_cents"] == 5_000
        assert body["currency"] == "USD"

    def test_a_code_worth_more_than_the_offer(self, client, db, make_space, make_user):
        """Free access is a complimentary pass, arranged deliberately —
        not something a fixed-amount code produces as a side effect when
        the price drops below it. Same stance as the 99% ceiling."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=4_000)
        make_code(db, space, code="BIG", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=9_000, currency="AUD")
        as_user(buyer)

        assert self._refusal(client, option, schedule, "BIG")["reason"] == "not_purchasable"

    def test_a_code_on_an_already_free_offer(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=0)
        make_code(db, space)
        as_user(buyer)

        body = self._refusal(client, option, schedule)
        assert body["reason"] == "not_purchasable"
        assert "already free" in body["message"].lower()

    def test_a_blank_code_is_simply_unrecognised(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        as_user(buyer)

        assert self._refusal(client, option, schedule, "   ")["reason"] == "not_found"


class TestPreviewAccess:
    def test_it_needs_a_verified_member(self, client, db, make_space, make_user):
        """Codes are guessable by design — they are meant to be typed.
        Sign-in puts a name against every attempt."""
        space = make_space()
        option, schedule = make_offer(db, space)
        app.dependency_overrides.pop(get_verified_current_user, None)
        app.dependency_overrides.pop(get_current_user, None)

        res = preview(client, option=option, schedule=schedule, code="FAMILY50")

        assert res.status_code in (401, 403)

    def test_a_missing_offer_is_a_404_not_a_verdict(
        self, client, db, make_space, make_user,
    ):
        """Shape problems are still errors. Only the code's validity is
        expressed as a 200 with a reason."""
        buyer = make_user()
        as_user(buyer)

        res = client.post("/api/checkout/discount-preview", json={
            "payment_option_id": "po_missing",
            "payment_option_schedule_id": "pos_missing",
            "code": "FAMILY50",
        })

        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Checkout — the charge follows the code
# ---------------------------------------------------------------------------


class TestCheckoutChargesTheDiscountedAmount:
    def test_embody_activate_at_half_price(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The reference case, end to end: $306 becomes $153 on the card."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert stripe_spy.unit_amount == 15_300
        assert stripe_spy.currency == "aud"

    def test_without_a_code_the_full_price_is_charged(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code=None)

        assert stripe_spy.unit_amount == ACTIVATE_CENTS

    def test_the_ledger_records_what_was_charged(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        result = checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        txn = db.query(PaymentTransaction).filter_by(id=result.transaction_id).one()
        assert txn.gross_amount_cents == HALF_OF_ACTIVATE
        # Stripe and the ledger agree, because both came from one number.
        assert txn.gross_amount_cents == stripe_spy.unit_amount

    def test_a_fixed_dollar_code_is_charged(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, code="FIFTYOFF", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=5_000, currency="AUD")

        checkout(db, buyer, option=option, schedule=schedule, code="FIFTYOFF")

        assert stripe_spy.unit_amount == 25_600

    def test_the_platform_fee_is_charged_on_the_discounted_amount(
        self, db, make_space, make_user, stripe_configured, stripe_spy, monkeypatch,
    ):
        """Fresh Collective takes its share of money that actually moved,
        not of a list price the member never paid.

        This asserts what the fee is charged ON, not how it rounds.
        The rounding rule belongs to ``checkout_orchestration`` and is
        production behaviour older than discount codes; discounting
        lowers the base and changes nothing else. A rate and amount that
        divide exactly are used deliberately, so this test cannot start
        failing if that unrelated rule is ever revisited.
        """
        from app.services import checkout_orchestration as orch

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)

        real = orch.resolve_fee_context
        monkeypatch.setattr(orch, "resolve_fee_context", lambda space, db: SimpleNamespace(
            **{**real(space, db).__dict__, "fee_bps": 1000},
        ))

        result = checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        txn = db.query(PaymentTransaction).filter_by(id=result.transaction_id).one()
        # 10% of $153, not 10% of $306 — both divide exactly.
        assert txn.platform_fee_cents == 1_530
        assert txn.net_creator_amount_cents == HALF_OF_ACTIVATE - 1_530

    def test_the_fee_base_is_the_amount_stripe_was_told_to_charge(
        self, db, make_space, make_user, stripe_configured, stripe_spy, monkeypatch,
    ):
        """Stated as a relationship rather than a number, so it holds
        whatever the fee rule does: the fee is a share of the line item
        the member is presented with."""
        from app.services import checkout_orchestration as orch

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)

        real = orch.resolve_fee_context
        monkeypatch.setattr(orch, "resolve_fee_context", lambda space, db: SimpleNamespace(
            **{**real(space, db).__dict__, "fee_bps": 1000},
        ))

        result = checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        txn = db.query(PaymentTransaction).filter_by(id=result.transaction_id).one()
        assert txn.gross_amount_cents == stripe_spy.unit_amount
        assert txn.platform_fee_cents == round(
            stripe_spy.unit_amount * txn.platform_fee_basis_points / 10_000,
        )
        # And that base is the discounted amount, not the list price.
        assert stripe_spy.unit_amount < ACTIVATE_CENTS

    def test_the_snapshot_explains_the_charge_later(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Written at the moment the price was decided, so the charge can
        still be read back after the code is edited or deleted."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)

        result = checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        snap = db.query(PaymentTransaction).filter_by(
            id=result.transaction_id).one().discount_snapshot_json
        assert snap["code"] == "FAMILY50"
        assert snap["discount_code_id"] == code.id
        assert snap["original_amount_cents"] == ACTIVATE_CENTS
        assert snap["discount_amount_cents"] == HALF_OF_ACTIVATE
        assert snap["final_amount_cents"] == HALF_OF_ACTIVATE

    def test_the_snapshot_survives_the_code_being_deleted(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)
        result = checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        db.delete(code)
        db.commit()

        snap = db.query(PaymentTransaction).filter_by(
            id=result.transaction_id).one().discount_snapshot_json
        assert snap["final_amount_cents"] == HALF_OF_ACTIVATE

    def test_an_undiscounted_purchase_records_no_snapshot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)

        result = checkout(db, buyer, option=option, schedule=schedule)

        assert db.query(PaymentTransaction).filter_by(
            id=result.transaction_id).one().discount_snapshot_json is None


class TestCheckoutDoesNotRecordRedemption:
    """Opening a checkout session is an intention, not a purchase.

    Recording a *redemption* here would burn a limited code on a member
    who closed the Stripe tab. Redemption is written when payment
    succeeds, which is Work Item 6; until then the ledger stays empty.

    This is not the same as leaving the final slot unguarded — see
    :class:`TestTheFinalSlotIsNotYetGuarded` for what Work Item 4
    deliberately does not solve, and why the answer cannot be a refusal
    after payment.
    """

    def test_no_redemption_row_is_written(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert db.query(DiscountRedemption).filter_by(
            discount_code_id=code.id).count() == 0

    def test_the_cached_count_is_not_touched_either(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        db.refresh(code)
        assert code.redemption_count == 0


class TestTheFinalSlotIsNotYetGuarded:
    """A known gap, recorded so it is not mistaken for finished work.

    Two checkout sessions can currently exist against a single-use code,
    because nothing is written until payment succeeds. The test below
    pins that as *current behaviour*, not as intended behaviour.

    The fix is NOT to refuse the loser at fulfilment. By then the card
    has been charged, and a member holding a completed payment they must
    be refunded for is a worse outcome than the double-spend it was
    meant to prevent. The competing checkout has to be stopped BEFORE
    Stripe takes any money.

    Work Item 6 therefore owes an atomic pre-payment reservation:

      * preview reserves nothing — it is a question, asked freely;
      * starting a real checkout reserves a slot;
      * live reservations count against ``max_redemptions`` alongside
        redemptions, so the limit reflects money in flight;
      * an abandoned or expired checkout releases its slot;
      * a successful payment converts reservation → redemption exactly
        once, and never double-counts as both;
      * a competing checkout for the last slot is refused before Stripe
        is called at all;
      * deactivating a code stops new reservations;
      * a code with live reservations cannot be hard-deleted out from
        under them.

    Until that exists, a single-use code oversold by a simultaneous
    second buyer is a real possibility, and this file does not pretend
    otherwise.
    """

    def test_two_sessions_can_currently_open_against_one_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Current behaviour, pinned so the reservation work has a
        starting point that fails visibly when it lands."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, max_redemptions=1)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert len(stripe_spy.calls) == 2

    def test_nothing_in_work_item_4_reserves_a_slot(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The reservation concept does not exist yet. Asserted so that
        adding it cannot be mistaken for a no-op refactor: this test is
        expected to be rewritten by Work Item 6, not deleted quietly."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert db.query(DiscountRedemption).filter_by(
            discount_code_id=code.id).count() == 0
        db.refresh(code)
        assert code.redemption_count == 0


# ---------------------------------------------------------------------------
# Checkout revalidates — the preview is not evidence
# ---------------------------------------------------------------------------


class TestCheckoutRevalidatesIndependently:
    """A preview is a statement about an earlier moment.

    Between reading a page and clicking buy, a code can expire, be
    switched off, or be taken by someone else. Checkout therefore asks
    again rather than trusting what the member was shown — and the
    client never sends an amount for it to trust in the first place.
    """

    def _valid_preview_then(self, client, db, space, buyer, option, schedule, mutate):
        as_user(buyer)
        assert preview(client, option=option, schedule=schedule,
                       code="FAMILY50").json()["valid"] is True
        mutate()
        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        return exc.value

    def test_a_code_switched_off_in_between(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)

        def switch_off():
            code.is_active = False
            db.commit()

        err = self._valid_preview_then(client, db, space, buyer, option, schedule, switch_off)

        assert err.status_code == 409
        assert "no longer active" in err.detail.lower()
        # Refused before Stripe — no session, no charge.
        assert stripe_spy.calls == []

    def test_a_code_that_expired_in_between(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, expires_at=datetime.utcnow() + timedelta(seconds=30))

        def expire():
            code.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        err = self._valid_preview_then(client, db, space, buyer, option, schedule, expire)

        assert err.status_code == 409
        assert "expired" in err.detail.lower()
        assert stripe_spy.calls == []

    def test_a_code_taken_by_someone_else_in_between(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space, max_redemptions=1)

        err = self._valid_preview_then(
            client, db, space, buyer, option, schedule,
            lambda: redeem(db, code, space, times=1),
        )

        assert err.status_code == 409
        assert "limit" in err.detail.lower()
        assert stripe_spy.calls == []

    def test_a_code_deleted_in_between(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        code = make_code(db, space)

        def delete():
            db.delete(code)
            db.commit()

        err = self._valid_preview_then(client, db, space, buyer, option, schedule, delete)

        assert err.status_code == 409
        assert stripe_spy.calls == []

    def test_a_price_raised_in_between_is_discounted_from_the_new_price(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Checkout re-reads the price too, not just the code. The member
        is charged half of what the offer costs now, and the preview they
        saw does not bind the charge."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)
        assert preview(client, option=option, schedule=schedule,
                       code="FAMILY50").json()["final_amount_cents"] == 15_300

        schedule.total_amount_cents = 40_000
        db.commit()

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert stripe_spy.unit_amount == 20_000

    def test_a_code_from_another_collective_is_refused_at_checkout_too(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Isolation is not a preview-only courtesy."""
        theirs, mine = make_space(), make_space()
        buyer = make_user()
        option, schedule = make_offer(db, mine)
        make_code(db, theirs, code="THEIRS50")

        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="THEIRS50")

        assert exc.value.status_code == 409
        assert stripe_spy.calls == []

    def test_an_unknown_code_is_refused_rather_than_ignored(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Charging full price to someone who typed a code and was not
        told it failed is the silent-wrong-answer case."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)

        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="NOPE")

        assert exc.value.status_code == 409
        assert stripe_spy.calls == []


class TestTheClientCannotDictateThePrice:
    """The only thing a client sends is the code."""

    def test_the_request_has_nowhere_to_put_an_amount(self):
        fields = set(UnifiedCheckoutRequest.model_fields)
        assert "discount_code" in fields
        for forbidden in (
            "discount_amount_cents", "final_amount_cents", "original_amount_cents",
            "amount_cents", "price_cents",
        ):
            assert forbidden not in fields

    def test_a_smuggled_amount_is_ignored_by_the_schema(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Even if a client sends one, it is not a field, so it cannot
        reach the charge."""
        from app.checkout.routes import create_unified_checkout_session

        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space)

        create_unified_checkout_session(
            UnifiedCheckoutRequest.model_validate({
                "payment_option_id": option.id,
                "payment_option_schedule_id": schedule.id,
                "success_url": "https://ok/s", "cancel_url": "https://ok/c",
                "discount_code": "FAMILY50",
                "final_amount_cents": 1,
            }),
            current_user=buyer, db=db,
        )

        assert stripe_spy.unit_amount == HALF_OF_ACTIVATE

    def test_preview_and_checkout_reach_the_same_figure(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The property the whole design turns on."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=3_333)
        as_user(buyer)

        shown = preview(client, option=option, schedule=schedule,
                        code="FAMILY50").json()["final_amount_cents"]
        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert stripe_spy.unit_amount == shown


# ---------------------------------------------------------------------------
# What this work item does not do
# ---------------------------------------------------------------------------


class TestOutOfScopePathsRefuseRatherThanPretend:
    def test_a_payment_plan_will_not_take_a_code_yet(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Discounting instalments means deciding how an uneven split is
        represented to Stripe, which has not been decided. Accepting the
        code and charging full price would be the silent wrong answer."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, schedule_type="recurring_installments")
        make_code(db, space)

        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert exc.value.status_code == 400
        assert "pay in full" in exc.value.detail.lower()
        assert stripe_spy.calls == []

    def test_a_free_offer_refuses_a_code_rather_than_dropping_it(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=0)
        make_code(db, space)

        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert exc.value.status_code == 409
        assert "already free" in exc.value.detail.lower()

    def test_a_free_offer_without_a_code_still_works(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=0)

        result = checkout(db, buyer, option=option, schedule=schedule)

        assert result.free is True
        assert stripe_spy.calls == []


# ---------------------------------------------------------------------------
# The smallest charge we can actually take
# ---------------------------------------------------------------------------


class TestADiscountCannotLeaveTooLittleToCharge:
    """Below a floor, a payment provider simply refuses.

    Left unguarded that arrives as a provider error at the moment of
    purchase — a 502 where the member expected a payment page. The floor
    is checked in ``resolve_discount``, which is the one place preview
    and checkout share, so both refuse identically and neither can reach
    Stripe with an amount it will not take.

    The discount is never trimmed to fit. A code that silently stopped
    being worth what it says would be the system telling a small lie on
    the Creator's behalf; refusing says the true thing instead.
    """

    def test_exactly_the_floor_is_fine(self, client, db, make_space, make_user):
        """100 minor units is chargeable, so it is allowed. The boundary
        is inclusive on the usable side."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=200)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="FAMILY50").json()

        assert body["valid"] is True
        assert body["final_amount_cents"] == MIN_PAID_CHARGE_CENTS

    def test_one_cent_under_the_floor_is_refused(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=199)
        make_code(db, space, code="NEARLYALL", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=100, currency="AUD")
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="NEARLYALL").json()

        assert body["valid"] is False
        assert body["final_amount_cents"] is None
        assert body["reason"] == "below_minimum"

    def test_a_percentage_discount_crossing_the_floor(self, client, db, make_space, make_user):
        """$1.50 at half off leaves 75c — real money, but not takeable."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=150)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="FAMILY50").json()

        assert body["reason"] == "below_minimum"

    def test_a_fixed_discount_crossing_the_floor(self, client, db, make_space, make_user):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=250)
        make_code(db, space, code="TWODOLLAR", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=200, currency="AUD")
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="TWODOLLAR").json()

        assert body["reason"] == "below_minimum"

    def test_the_reason_tells_the_member_what_the_floor_is(
        self, client, db, make_space, make_user,
    ):
        """Useful rather than merely correct: "too little to charge" with
        no number leaves nobody able to act on it."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=150)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        message = preview(client, option=option, schedule=schedule,
                          code="FAMILY50").json()["message"]

        assert "1.00" in message
        assert "AUD" in message

    def test_it_is_distinct_from_a_code_that_charges_nothing(
        self, client, db, make_space, make_user,
    ):
        """Two different problems with two different fixes — a smaller
        discount, versus a feature that does not exist — so they must not
        arrive under one word."""
        space, buyer = make_space(), make_user()
        as_user(buyer)

        too_small, small_sched = make_offer(db, space, cents=150)
        make_code(db, space, code="HALF", percent_bps=5000)
        nothing_left, nothing_sched = make_offer(db, space, cents=4_000)
        make_code(db, space, code="BIGGER", discount_type="fixed_amount",
                  percent_bps=None, amount_cents=9_000, currency="AUD")

        assert preview(client, option=too_small, schedule=small_sched,
                       code="HALF").json()["reason"] == "below_minimum"
        assert preview(client, option=nothing_left, schedule=nothing_sched,
                       code="BIGGER").json()["reason"] == "not_purchasable"

    def test_checkout_refuses_it_independently(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """Not merely a preview courtesy — checkout reaches the same
        refusal through the same resolver, before Stripe is called."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=150)
        make_code(db, space, percent_bps=5000)

        with pytest.raises(HTTPException) as exc:
            checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert exc.value.status_code == 409
        assert "smallest payment" in exc.value.detail.lower()
        assert stripe_spy.calls == []

    def test_preview_and_checkout_agree_on_the_boundary(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The property that matters: one cent apart, both surfaces flip
        together. They share a resolver, so they cannot disagree."""
        space, buyer = make_space(), make_user()
        as_user(buyer)

        # 200c at half off → exactly the floor. Allowed by both.
        ok_opt, ok_sched = make_offer(db, space, cents=200)
        make_code(db, space, code="HALF", percent_bps=5000)
        assert preview(client, option=ok_opt, schedule=ok_sched,
                       code="HALF").json()["valid"] is True
        checkout(db, buyer, option=ok_opt, schedule=ok_sched, code="HALF")
        assert stripe_spy.unit_amount == MIN_PAID_CHARGE_CENTS

        # 198c at half off → 99c. Refused by both.
        low_opt, low_sched = make_offer(db, space, cents=198)
        assert preview(client, option=low_opt, schedule=low_sched,
                       code="HALF").json()["reason"] == "below_minimum"
        with pytest.raises(HTTPException):
            checkout(db, buyer, option=low_opt, schedule=low_sched, code="HALF")

    def test_the_discount_is_refused_not_quietly_trimmed(
        self, client, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The tempting alternative — shrink the discount so the charge
        clears the floor — would charge a member more than the code
        promised, without telling anyone. Assert it does not happen."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=150)
        make_code(db, space, percent_bps=5000)
        as_user(buyer)

        body = preview(client, option=option, schedule=schedule, code="FAMILY50").json()
        assert body["valid"] is False
        # No amounts at all — nothing a client could render as a price.
        assert body["discount_amount_cents"] is None
        assert body["final_amount_cents"] is None

        with pytest.raises(HTTPException):
            checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")
        assert stripe_spy.calls == []


class TestTheFloorOnlyConcernsDiscounts:
    """A low-priced offer that nobody discounts is untouched.

    The floor is a rule about what a discount may leave, not a new
    minimum price for Payment Options. Adding one of those is a separate
    question about existing offers, and is not decided here.
    """

    def test_an_undiscounted_cheap_offer_still_checks_out(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space, cents=150)

        checkout(db, buyer, option=option, schedule=schedule)

        assert stripe_spy.unit_amount == 150

    def test_an_ordinary_discounted_purchase_is_unaffected(
        self, db, make_space, make_user, stripe_configured, stripe_spy,
    ):
        """The reference case still behaves exactly as before."""
        space, buyer = make_space(), make_user()
        option, schedule = make_offer(db, space)
        make_code(db, space, percent_bps=5000)

        checkout(db, buyer, option=option, schedule=schedule, code="FAMILY50")

        assert stripe_spy.unit_amount == HALF_OF_ACTIVATE
