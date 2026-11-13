"""Stage 5A.1 — the membership billing foundation.

What is being protected
-----------------------
This stage introduces recurring charges, so most of what follows is
about what must *not* happen: nobody becomes a member by clicking, by
returning from Stripe, or by holding a ``pending`` row; a card being
charged cannot overturn a creator's removal; an existing free member is
never subscribed by anything other than their own deliberate checkout;
and an agreement's price cannot change under it.

The flag asymmetry is the subtlest part and has its own class. Opening a
subscription is gated; *servicing* one is not. A flag switched off after
a subscription exists must never leave its payments unrecorded — that
would be money taken with nothing written down.

Stripe is mocked throughout. Provider-level evidence is separate and
recorded in the report.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage5a1_membership_billing.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.collective_membership import (
    LIVE_STATUSES, CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import (
    PaymentTransaction, PaymentTransactionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import collective_membership_billing as billing
from app.services import collective_membership_eligibility as elig
from app.services import collective_membership_lifecycle as lifecycle
from app.services import membership_pricing_terms as terms
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    """Every test here runs with membership billing switched on.

    Monkeypatched rather than set globally, so the flag-OFF class below
    can turn it back off and the rest of the suite keeps testing the
    shipped default.
    """
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)


@pytest.fixture
def paid_space(db, make_space, make_user):
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    space.pricing_type = "paid_monthly"
    space.pricing_amount_cents = 2_900
    space.pricing_currency = "AUD"
    db.flush()
    return space


@pytest.fixture
def member(make_user):
    return make_user()


class _StripeSpy:
    """Stands in for Stripe, recording what it was asked to create."""

    def __init__(self):
        self.products, self.prices, self.sessions = [], [], []
        self.customers, self.expired, self.cancelled = [], [], []

    def product(self, **kw):
        self.products.append(kw)
        return SimpleNamespace(id=f"prod_{len(self.products)}")

    def price(self, **kw):
        self.prices.append(kw)
        return SimpleNamespace(id=f"price_{len(self.prices)}")

    def session(self, **kw):
        self.sessions.append(kw)
        n = len(self.sessions)
        return SimpleNamespace(id=f"cs_test_{n}", url=f"https://stripe.test/{n}")

    def customer(self, **kw):
        self.customers.append(kw)
        return SimpleNamespace(id=f"cus_test_{len(self.customers)}")


@pytest.fixture
def stripe_spy(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    spy = _StripeSpy()
    with patch("stripe.Product.create", side_effect=spy.product), \
         patch("stripe.Price.create", side_effect=spy.price), \
         patch("stripe.checkout.Session.create", side_effect=spy.session), \
         patch("stripe.Customer.create", side_effect=spy.customer):
        yield spy


def _open(db, space, member, **kw):
    return billing.open_membership_checkout(
        db, space=space, member=member,
        success_url="https://ok/s", cancel_url="https://ok/c",
        now=kw.pop("now", NOW), **kw,
    )


# ---------------------------------------------------------------------------
# What the server decides, not the client
# ---------------------------------------------------------------------------


class TestTheTermsComeFromTheCollective:
    def test_monthly_pricing_becomes_a_monthly_interval(self, paid_space):
        t = terms.resolve(paid_space)
        assert (t.interval, t.interval_count) == ("month", 1)
        assert t.amount_cents == 2_900
        assert t.currency == "AUD"

    def test_annual_pricing_becomes_a_yearly_interval(self, db, paid_space):
        paid_space.pricing_type = "paid_annual"
        paid_space.pricing_amount_cents = 29_000
        db.flush()
        t = terms.resolve(paid_space)
        assert t.interval == "year"
        assert t.amount_cents == 29_000

    @pytest.mark.parametrize("pricing_type", [
        "free", "invite_only", "coming_soon", "paid_one_time", "",
    ])
    def test_anything_else_is_refused_rather_than_guessed(
        self, db, paid_space, pricing_type,
    ):
        """``paid_one_time`` included deliberately: a one-off joining fee
        is a purchase, not a subscription, and reaching here with it is a
        routing mistake."""
        paid_space.pricing_type = pricing_type
        db.flush()
        with pytest.raises(HTTPException) as exc:
            terms.resolve(paid_space)
        assert exc.value.status_code == 409

    @pytest.mark.parametrize("amount", [None, 0, 49, -100])
    def test_an_unusable_amount_is_refused(self, db, paid_space, amount):
        paid_space.pricing_amount_cents = amount
        db.flush()
        with pytest.raises(HTTPException) as exc:
            terms.resolve(paid_space)
        assert exc.value.status_code == 409

    def test_a_missing_currency_is_refused(self, db, paid_space):
        paid_space.pricing_currency = ""
        db.flush()
        with pytest.raises(HTTPException):
            terms.resolve(paid_space)


class TestOpeningAnAgreement:
    def test_the_agreed_terms_are_frozen_onto_the_row(
        self, db, paid_space, member, stripe_spy,
    ):
        out = _open(db, paid_space, member)
        row = out.subscription
        assert row.status == CollectiveMembershipStatus.pending.value
        assert (row.amount_cents, row.currency, row.interval) == (
            2_900, "AUD", "month",
        )
        assert row.space_id == paid_space.id
        assert row.user_id == member.id

    def test_a_later_price_change_does_not_touch_the_agreement(
        self, db, paid_space, member, stripe_spy,
    ):
        """The §4 rule, and it holds because nothing re-reads the
        Collective after the row exists."""
        row = _open(db, paid_space, member).subscription
        paid_space.pricing_amount_cents = 3_900
        db.flush()
        db.refresh(row)
        assert row.amount_cents == 2_900

    def test_the_stripe_price_is_minted_from_the_collectives_amount(
        self, db, paid_space, member, stripe_spy,
    ):
        _open(db, paid_space, member)
        [price] = stripe_spy.prices
        assert price["unit_amount"] == 2_900
        assert price["currency"] == "aud"
        assert price["recurring"] == {"interval": "month", "interval_count": 1}

    def test_the_session_is_subscription_mode_and_discriminated(
        self, db, paid_space, member, stripe_spy,
    ):
        _open(db, paid_space, member)
        [sess] = stripe_spy.sessions
        assert sess["mode"] == "subscription"
        assert sess["metadata"]["purchase_type"] == "collective_membership"
        assert sess["metadata"]["space_id"] == paid_space.id
        # Carried onto the Subscription too, or a renewal arrives with
        # no way to tell which system owns it.
        assert sess["subscription_data"]["metadata"]["purchase_type"] == (
            "collective_membership"
        )

    def test_the_fee_context_is_frozen_at_subscribe(
        self, db, paid_space, member, stripe_spy,
    ):
        row = _open(db, paid_space, member).subscription
        assert row.creator_user_id == paid_space.creator_id
        assert row.platform_fee_basis_points >= 0
        assert row.payout_model is not None

    def test_nothing_is_granted_by_opening_checkout(
        self, db, paid_space, member, stripe_spy,
    ):
        _open(db, paid_space, member)
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == paid_space.id,
            SpaceMembership.user_id == member.id,
        ).count() == 0
        assert db.query(PaymentTransaction).count() == 0

    def test_two_paid_collectives_are_independent_agreements(
        self, db, paid_space, member, stripe_spy, make_space, make_user,
    ):
        other = make_space(creator=make_user(role="creator"))
        other.pricing_type = "paid_monthly"
        other.pricing_amount_cents = 4_900
        other.pricing_currency = "AUD"
        db.flush()

        a = _open(db, paid_space, member).subscription
        b = _open(db, other, member).subscription
        assert a.id != b.id
        assert a.amount_cents == 2_900 and b.amount_cents == 4_900
        assert a.stripe_price_id != b.stripe_price_id


class TestTheStripeCustomer:
    def test_a_member_who_was_never_a_creator_gets_one(
        self, db, paid_space, member, stripe_spy,
    ):
        row = _open(db, paid_space, member).subscription
        assert row.stripe_customer_id.startswith("cus_test_")
        assert len(stripe_spy.customers) == 1
        assert stripe_spy.customers[0]["metadata"]["fc_user_id"] == member.id

    def test_a_second_collective_reuses_the_same_customer(
        self, db, paid_space, member, stripe_spy, make_space, make_user,
    ):
        """One Customer per person: charges land on one Stripe account,
        and splitting a person would make them re-enter their card."""
        other = make_space(creator=make_user(role="creator"))
        other.pricing_type = "paid_monthly"
        other.pricing_amount_cents = 1_900
        other.pricing_currency = "AUD"
        db.flush()

        a = _open(db, paid_space, member).subscription
        b = _open(db, other, member).subscription
        assert a.stripe_customer_id == b.stripe_customer_id
        assert len(stripe_spy.customers) == 1


# ---------------------------------------------------------------------------
# Duplicates and stale quotes
# ---------------------------------------------------------------------------


class TestDuplicateAndRetryProtection:
    def test_the_same_quote_reuses_its_live_page(
        self, db, paid_space, member, stripe_spy,
    ):
        first = _open(db, paid_space, member)
        with patch.object(billing, "_inspect_session", return_value={
            "status": "open", "url": first.checkout_url,
        }):
            second = _open(db, paid_space, member)
        assert second.reused is True
        assert second.subscription.id == first.subscription.id
        assert len(stripe_spy.sessions) == 1, "no second payment page"

    def test_a_changed_price_supersedes_rather_than_reusing(
        self, db, paid_space, member, stripe_spy,
    ):
        """The Stage 4A lesson. Reuse is only safe for the *same*
        agreement, so every term is compared and not just the amount."""
        first = _open(db, paid_space, member).subscription
        paid_space.pricing_amount_cents = 3_900
        db.flush()

        with patch.object(billing, "_inspect_session", return_value={
            "status": "open", "url": "https://stripe.test/old",
        }), patch("stripe.checkout.Session.expire") as expire:
            second = _open(db, paid_space, member)

        assert second.reused is False
        assert second.subscription.id != first.id
        assert second.subscription.amount_cents == 3_900
        expire.assert_called_once()
        db.refresh(first)
        assert first.status == CollectiveMembershipStatus.failed.value

    @pytest.mark.parametrize("field,value", [
        ("pricing_type", "paid_annual"),
        ("pricing_currency", "USD"),
    ])
    def test_any_changed_term_supersedes(
        self, db, paid_space, member, stripe_spy, field, value,
    ):
        first = _open(db, paid_space, member).subscription
        setattr(paid_space, field, value)
        db.flush()
        with patch.object(billing, "_inspect_session", return_value={
            "status": "open", "url": "https://stripe.test/old",
        }), patch("stripe.checkout.Session.expire"):
            second = _open(db, paid_space, member)
        assert second.subscription.id != first.id

    def test_a_dead_page_is_replaced(
        self, db, paid_space, member, stripe_spy,
    ):
        first = _open(db, paid_space, member).subscription
        with patch.object(billing, "_inspect_session", return_value={
            "status": "expired", "url": None,
        }), patch("stripe.checkout.Session.expire"):
            second = _open(db, paid_space, member)
        assert second.subscription.id != first.id

    def test_an_unreadable_page_is_replaced_not_reused(
        self, db, paid_space, member, stripe_spy,
    ):
        """Unreadable is treated as unusable: a fresh page is safe, an
        unknown one is not."""
        first = _open(db, paid_space, member).subscription
        with patch.object(billing, "_inspect_session", return_value=None), \
             patch("stripe.checkout.Session.expire"):
            second = _open(db, paid_space, member)
        assert second.subscription.id != first.id

    def test_the_database_permits_only_one_live_agreement(
        self, db, paid_space, member, stripe_spy,
    ):
        """The partial unique index, not a handler remembering to look."""
        from sqlalchemy.exc import IntegrityError

        _open(db, paid_space, member)
        db.add(CollectiveMembership(
            id=_uid("cmem"), user_id=member.id, space_id=paid_space.id,
            status=CollectiveMembershipStatus.active.value,
            interval="month", interval_count=1, amount_cents=2_900,
            currency="AUD",
        ))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_the_index_predicate_matches_the_model(self, db):
        """Two places name the live statuses; if they disagree the
        database wins, so they must not."""
        from sqlalchemy import text
        ddl = db.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_collective_memberships_live'"
        )).scalar()
        for status in LIVE_STATUSES:
            assert f"'{status}'" in ddl, status
        for status in ("ended", "cancelled", "failed", "cancel_scheduled"):
            assert f"'{status}'" not in ddl, status


# ---------------------------------------------------------------------------
# Eligibility — §8, §14
# ---------------------------------------------------------------------------


class TestWhoMaySubscribe:
    def test_an_eligible_stranger_may(self, db, paid_space, member):
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    def test_a_free_collective_has_nothing_to_sell(
        self, db, paid_space, member,
    ):
        paid_space.pricing_type = "free"
        db.flush()
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_PAID

    def test_an_active_member_has_nothing_to_buy(
        self, db, paid_space, member,
    ):
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.active,
            source="joined", joined_at=NOW,
        ))
        db.flush()
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.ALREADY_ACTIVE

    def test_a_creator_removal_cannot_be_bought_past(
        self, db, paid_space, member,
    ):
        """§8 — a successful payment must never override a removal."""
        from app.services.membership_removal import REMOVAL_BY_CREATOR
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=NOW,
            removal_kind=REMOVAL_BY_CREATOR, removed_at=NOW,
            rejoin_blocked=True,
        ))
        db.flush()
        refusal = elig.refusal_for(db, user=member, space=paid_space)
        assert refusal is elig.NOT_ELIGIBLE
        assert refusal.status_code == 402

    def test_a_voluntary_departure_may_come_back_and_pay(
        self, db, paid_space, member,
    ):
        from app.services.membership_removal import REMOVAL_VOLUNTARY
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=NOW,
            removal_kind=REMOVAL_VOLUNTARY, removed_at=NOW,
        ))
        db.flush()
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    def test_a_historical_removal_of_unknown_provenance_is_refused(
        self, db, paid_space, member,
    ):
        """NULL ``removal_kind`` predates migration 166. Refusing keeps
        every moderation decision nobody wrote down in force."""
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=NOW, removed_at=NOW,
        ))
        db.flush()
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_ELIGIBLE

    def test_a_paused_membership_cannot_be_bought_past_either(
        self, db, paid_space, member,
    ):
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.paused,
            source="joined", joined_at=NOW,
        ))
        db.flush()
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_ELIGIBLE

    def test_an_auto_managed_collective_sells_no_membership(
        self, db, paid_space, member,
    ):
        # Only ``creator`` passes the column's CHECK.
        paid_space.auto_grant_role = "creator"
        db.flush()
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.AUTO_MANAGED

    def test_eligibility_never_consults_the_join_policy(self):
        """§8 — the two are composed by the route, not folded together,
        so an invite-only Collective keeps its own door."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(elig))
        names = {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert "join_policy" not in names

    def test_an_invitation_is_not_a_waiver(self, db, paid_space, member):
        """§14 — an invitation grants eligibility to join, never free
        access to something priced."""
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="invited", joined_at=NOW,
            removal_kind="voluntary", removed_at=NOW,
        ))
        db.flush()
        # Still priced: eligibility says yes, and the price still applies.
        assert elig.refusal_for(db, user=member, space=paid_space) is None
        assert terms.resolve(paid_space).amount_cents == 2_900


# ---------------------------------------------------------------------------
# Activation — the only thing that grants
# ---------------------------------------------------------------------------


def _pending(db, space, member, **kw):
    row = CollectiveMembership(
        id=_uid("cmem"), user_id=member.id, space_id=space.id,
        status=kw.pop("status", CollectiveMembershipStatus.pending.value),
        interval="month", interval_count=1,
        amount_cents=kw.pop("amount_cents", 2_900),
        currency=kw.pop("currency", "AUD"),
        creator_user_id=space.creator_id,
        platform_fee_basis_points=kw.pop("fee_bps", 1_000),
        payout_model="manual",
        stripe_subscription_id=kw.pop("stripe_subscription_id", None),
        stripe_checkout_session_id=kw.pop("session_id", None),
        created_at=NOW, updated_at=NOW,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _activate(db, row, **kw):
    return lifecycle.activate_from_first_invoice(
        db,
        subscription=row,
        invoice_id=kw.pop("invoice_id", _uid("in")),
        invoice_amount_cents=kw.pop("amount", 2_900),
        invoice_currency=kw.pop("currency", "AUD"),
        stripe_subscription_id=kw.pop("sub_id", "sub_test_1"),
        charge_id=kw.pop("charge_id", "ch_test_1"),
        payment_intent_id=kw.pop("pi", "pi_test_1"),
        period_start=kw.pop("period_start", NOW),
        period_end=kw.pop("period_end", NOW + timedelta(days=30)),
        now=kw.pop("now", NOW),
    )


class TestMembershipArrivesOnlyWithAVerifiedPayment:
    def test_a_verified_invoice_creates_the_membership(
        self, db, paid_space, member,
    ):
        row = _pending(db, paid_space, member)
        out = _activate(db, row)
        assert out.applied is True
        assert out.membership == "created"
        assert row.status == CollectiveMembershipStatus.active.value
        assert row.activated_at == NOW
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == paid_space.id,
            SpaceMembership.user_id == member.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        ).count() == 1

    def test_the_membership_is_sourced_as_a_purchase(
        self, db, paid_space, member,
    ):
        _activate(db, _pending(db, paid_space, member))
        row = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
        ).one()
        assert row.source == "purchase"

    def test_a_returning_member_is_reactivated_not_duplicated(
        self, db, paid_space, member,
    ):
        """§5 — one continuing membership relationship, however many
        agreements it has had."""
        from app.services.membership_removal import REMOVAL_VOLUNTARY
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=NOW - timedelta(days=90),
            removal_kind=REMOVAL_VOLUNTARY, removed_at=NOW - timedelta(days=5),
        ))
        db.flush()

        out = _activate(db, _pending(db, paid_space, member))
        assert out.membership == "reactivated"
        rows = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == paid_space.id,
            SpaceMembership.user_id == member.id,
        ).all()
        assert len(rows) == 1, "no second membership row"
        assert rows[0].status is SpaceMembershipStatus.active

    def test_payment_does_not_overturn_a_creator_removal(
        self, db, paid_space, member,
    ):
        """§10 — the money is recorded, access is not granted, and the
        case is named so it can be cancelled or refunded."""
        from app.services.membership_removal import REMOVAL_BY_CREATOR
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.removed,
            source="joined", joined_at=NOW,
            removal_kind=REMOVAL_BY_CREATOR, removed_at=NOW,
            rejoin_blocked=True,
        ))
        db.flush()

        out = _activate(db, _pending(db, paid_space, member))
        assert out.needs_attention is not None
        assert out.transaction is not None, "the payment is still recorded"
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        ).count() == 0

    def test_a_replayed_invoice_changes_nothing(self, db, paid_space, member):
        row = _pending(db, paid_space, member)
        inv = _uid("in")
        first = _activate(db, row, invoice_id=inv)
        second = _activate(db, row, invoice_id=inv)
        assert first.applied is True and second.applied is False
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.provider_invoice_id == inv,
        ).count() == 1
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
        ).count() == 1

    @pytest.mark.parametrize("amount", [2_800, 3_000, 0])
    def test_a_wrong_amount_is_refused_not_recorded(
        self, db, paid_space, member, amount,
    ):
        row = _pending(db, paid_space, member)
        with pytest.raises(lifecycle.AmountMismatch):
            _activate(db, row, amount=amount)
        assert db.query(PaymentTransaction).count() == 0

    def test_a_wrong_currency_is_refused(self, db, paid_space, member):
        row = _pending(db, paid_space, member)
        with pytest.raises(lifecycle.AmountMismatch):
            _activate(db, row, currency="USD")

    def test_the_period_is_recorded_on_the_payment(
        self, db, paid_space, member,
    ):
        """What a renewal will differ by, and nothing else."""
        start, end = NOW, NOW + timedelta(days=30)
        out = _activate(
            db, _pending(db, paid_space, member),
            period_start=start, period_end=end,
        )
        assert out.transaction.billing_period_start == start
        assert out.transaction.billing_period_end == end
        assert out.subscription.current_period_end == end


class TestTheMoney:
    def test_gross_fee_and_creator_earnings(self, db, paid_space, member):
        row = _pending(db, paid_space, member, fee_bps=1_000)
        txn = _activate(db, row).transaction
        assert txn.gross_amount_cents == 2_900
        assert txn.platform_fee_basis_points == 1_000
        assert txn.platform_fee_cents == 290
        assert txn.net_creator_amount_cents == 2_610

    def test_the_transaction_type_is_the_existing_one(
        self, db, paid_space, member,
    ):
        """Already in the enum, already labelled in admin reporting,
        already counted by BI revenue eligibility — so no enum
        migration and no reporting change."""
        txn = _activate(db, _pending(db, paid_space, member)).transaction
        assert txn.transaction_type is (
            PaymentTransactionType.member_collective_subscription
        )

    def test_it_is_attributed_to_the_collective_and_the_member(
        self, db, paid_space, member,
    ):
        txn = _activate(db, _pending(db, paid_space, member)).transaction
        assert txn.space_id == paid_space.id
        assert txn.payer_user_id == member.id
        assert txn.creator_user_id == paid_space.creator_id

    def test_the_frozen_fee_is_used_not_the_current_one(
        self, db, paid_space, member,
    ):
        """A creator changing plan does not re-rate an agreement."""
        row = _pending(db, paid_space, member, fee_bps=500)
        txn = _activate(db, row).transaction
        assert txn.platform_fee_basis_points == 500
        assert txn.platform_fee_cents == 145

    def test_a_connect_agreement_is_outside_manual_payouts(
        self, db, paid_space, member,
    ):
        from app.models.payment import PayoutStatus
        row = _pending(db, paid_space, member)
        row.payout_model = "connect"
        row.connect_destination_account_id = "acct_test"
        db.flush()
        txn = _activate(db, row).transaction
        assert txn.payout_status is PayoutStatus.not_applicable
        assert txn.connect_destination_account_id == "acct_test"

    def test_a_manual_agreement_is_queued_for_payout(
        self, db, paid_space, member,
    ):
        from app.models.payment import PayoutStatus
        txn = _activate(db, _pending(db, paid_space, member)).transaction
        assert txn.payout_status is PayoutStatus.pending


# ---------------------------------------------------------------------------
# Webhook routing
# ---------------------------------------------------------------------------


class TestTheWebhookClaimsOnlyItsOwnEvents:
    def test_it_claims_an_object_carrying_its_discriminator(self):
        assert handlers.owns_event(
            {"metadata": {"purchase_type": "collective_membership"}}
        ) is True

    @pytest.mark.parametrize("purchase_type", [
        "creator_subscription", "finite_plan_setup", "standalone_gathering",
    ])
    def test_it_never_claims_another_systems_event(self, purchase_type):
        assert handlers.owns_event(
            {"metadata": {"purchase_type": purchase_type}}
        ) is False

    def test_it_never_claims_an_unlabelled_event(self):
        assert handlers.owns_event({}) is False
        assert handlers.owns_event({"metadata": {}}) is False

    def test_it_reads_the_subscription_metadata_on_an_invoice(self):
        """Which is where Stripe copies it for renewal events."""
        assert handlers.owns_event({
            "subscription_details": {
                "metadata": {"purchase_type": "collective_membership"},
            },
        }) is True

    def test_checkout_completion_links_stripe_but_grants_nothing(
        self, db, paid_space, member,
    ):
        row = _pending(db, paid_space, member, session_id="cs_test_x")
        handlers.handle_checkout_completed({
            "id": "cs_test_x",
            "subscription": "sub_linked",
            "customer": "cus_linked",
            "metadata": {
                "purchase_type": "collective_membership",
                "collective_membership_id": row.id,
            },
        }, db, event_id="evt_1")
        db.refresh(row)
        assert row.stripe_subscription_id == "sub_linked"
        assert row.status == CollectiveMembershipStatus.pending.value
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
        ).count() == 0, "a captured card is not a membership"

    def test_an_invoice_activates_through_the_handler(
        self, db, paid_space, member,
    ):
        row = _pending(db, paid_space, member)
        handlers.handle_invoice_payment_succeeded({
            "id": "in_test_1",
            "amount_paid": 2_900,
            "currency": "aud",
            "subscription": "sub_test_1",
            "charge": "ch_1",
            "payment_intent": "pi_1",
            "lines": {"data": [{"period": {
                "start": int(NOW.timestamp()),
                "end": int((NOW + timedelta(days=30)).timestamp()),
            }}]},
            "metadata": {
                "purchase_type": "collective_membership",
                "collective_membership_id": row.id,
            },
        }, db, event_id="evt_2")
        db.refresh(row)
        assert row.status == CollectiveMembershipStatus.active.value
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        ).count() == 1

    def test_a_late_invoice_for_a_cancelled_agreement_does_not_revive_it(
        self, db, paid_space, member,
    ):
        row = _pending(
            db, paid_space, member,
            status=CollectiveMembershipStatus.cancelled.value,
        )
        handlers.handle_invoice_payment_succeeded({
            "id": "in_late", "amount_paid": 2_900, "currency": "aud",
            "metadata": {
                "purchase_type": "collective_membership",
                "collective_membership_id": row.id,
            },
        }, db, event_id="evt_3")
        db.refresh(row)
        assert row.status == CollectiveMembershipStatus.cancelled.value
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
        ).count() == 0

    def test_an_unknown_agreement_is_logged_not_crashed(self, db):
        assert handlers.handle_invoice_payment_succeeded(
            {"id": "in_orphan", "metadata": {
                "purchase_type": "collective_membership",
                "collective_membership_id": "cmem_nope",
            }}, db, event_id="evt_4",
        ) is True


# ---------------------------------------------------------------------------
# §16 — a subscription can be stopped
# ---------------------------------------------------------------------------


class TestAnAuthorisedCancellationExists:
    def test_it_cancels_at_stripe_and_locally(self, db, paid_space, member):
        row = _pending(
            db, paid_space, member, stripe_subscription_id="sub_cancel_me",
        )
        with patch("stripe.Subscription.delete") as delete:
            lifecycle.cancel_subscription_now(
                db, subscription=row, reason="operator_test_cleanup", now=NOW,
            )
        delete.assert_called_once_with("sub_cancel_me")
        assert row.status == CollectiveMembershipStatus.cancelled.value
        assert row.cancelled_reason == "operator_test_cleanup"
        assert row.ended_at == NOW

    def test_it_is_idempotent(self, db, paid_space, member):
        row = _pending(
            db, paid_space, member, stripe_subscription_id="sub_x",
        )
        with patch("stripe.Subscription.delete"):
            lifecycle.cancel_subscription_now(
                db, subscription=row, reason="first", now=NOW,
            )
            lifecycle.cancel_subscription_now(
                db, subscription=row, reason="second",
                now=NOW + timedelta(days=1),
            )
        assert row.cancelled_reason == "first", "original audit preserved"

    def test_an_already_absent_stripe_subscription_is_success(
        self, db, paid_space, member,
    ):
        import stripe as _stripe
        row = _pending(db, paid_space, member, stripe_subscription_id="sub_g")
        with patch(
            "stripe.Subscription.delete",
            side_effect=_stripe.InvalidRequestError(
                "No such subscription: sub_g", "id",
            ),
        ):
            lifecycle.cancel_subscription_now(
                db, subscription=row, reason="cleanup", now=NOW,
            )
        assert row.status == CollectiveMembershipStatus.cancelled.value

    def test_a_stripe_failure_leaves_local_state_alone(
        self, db, paid_space, member,
    ):
        """Provider first: marking it cancelled while Stripe kept
        billing is the one ordering worth protecting against."""
        import stripe as _stripe
        row = _pending(db, paid_space, member, stripe_subscription_id="sub_e")
        with patch(
            "stripe.Subscription.delete",
            side_effect=_stripe.APIConnectionError("network"),
        ):
            with pytest.raises(_stripe.StripeError):
                lifecycle.cancel_subscription_now(
                    db, subscription=row, reason="cleanup", now=NOW,
                )
        assert row.status == CollectiveMembershipStatus.pending.value

    def test_cancelling_the_money_does_not_end_the_belonging(
        self, db, paid_space, member,
    ):
        """Two different decisions with different rules. Stage 5A.2 owns
        the second."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(lifecycle.cancel_subscription_now))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "SpaceMembership" not in names
        assert "membership_grant" not in names


# ---------------------------------------------------------------------------
# The flag — and the asymmetry that matters
# ---------------------------------------------------------------------------


class TestWithBillingSwitchedOff:
    @pytest.fixture(autouse=True)
    def billing_off(self, monkeypatch):
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )

    def test_the_shipped_default_is_off(self):
        from app.core.config import Settings
        assert Settings().paid_collective_membership_enabled is False

    def test_no_new_subscription_can_be_opened(
        self, db, paid_space, member,
    ):
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_AVAILABLE

    def test_free_joining_is_untouched(self, db, make_space, make_user):
        from app.spaces.routes import join_space
        space = make_space()
        space.pricing_type = "free"
        db.flush()
        join_space(space.slug, db=db, current_user=make_user(),
                   background_tasks=None)

    def test_an_existing_agreement_is_still_serviced(
        self, db, paid_space, member,
    ):
        """The asymmetry, and it is required. An agreement that exists
        must keep being processed whatever the flag says — money taken
        with nothing written down is the one outcome worse than the
        feature being unavailable."""
        row = _pending(db, paid_space, member)
        out = _activate(db, row)
        assert out.applied is True
        assert row.status == CollectiveMembershipStatus.active.value
        assert db.query(PaymentTransaction).count() == 1

    def test_the_webhook_handlers_never_read_the_flag(self):
        """Structural, because this is the property that makes an
        already-created subscription safe to leave running."""
        import ast
        import inspect

        from app.webhooks import collective_membership_handlers as h
        for module in (h, lifecycle):
            tree = ast.parse(inspect.getsource(module))
            names = {
                n.attr for n in ast.walk(tree)
                if isinstance(n, ast.Attribute)
            }
            assert "paid_collective_membership_enabled" not in names, (
                module.__name__
            )

    def test_an_existing_agreement_can_still_be_cancelled(
        self, db, paid_space, member,
    ):
        row = _pending(db, paid_space, member, stripe_subscription_id="sub_o")
        with patch("stripe.Subscription.delete"):
            lifecycle.cancel_subscription_now(
                db, subscription=row, reason="flag_off_cleanup", now=NOW,
            )
        assert row.status == CollectiveMembershipStatus.cancelled.value

    def test_creator_subscriptions_are_untouched_by_any_of_this(self):
        """Nothing in this stage writes to the creator billing system."""
        import ast
        import inspect

        from app.webhooks import collective_membership_handlers as h
        for module in (billing, lifecycle, elig, terms, h):
            src = inspect.getsource(module)
            tree = ast.parse(src)
            assigned = {
                t.attr for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Attribute)
            }
            # ``billing`` reads CreatorSubscription.stripe_customer_id to
            # reuse a Customer; it must never write one.
            assert not {
                a for a in assigned if "creator_subscription" in a.lower()
            }, module.__name__


# ---------------------------------------------------------------------------
# Nothing happens to existing members
# ---------------------------------------------------------------------------


class TestExistingMembersAreNeverSubscribed:
    def test_a_free_member_of_a_newly_paid_collective_keeps_access(
        self, db, paid_space, member,
    ):
        """§13 — the transition is designed, not running. A creator
        switching to paid neither charges nor subscribes anybody."""
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=paid_space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.active,
            source="joined", joined_at=NOW - timedelta(days=30),
        ))
        db.flush()
        paid_space.paid_membership_effective_at = NOW + timedelta(days=60)
        db.flush()

        row = db.query(SpaceMembership).filter(
            SpaceMembership.user_id == member.id,
        ).one()
        assert row.status is SpaceMembershipStatus.active
        assert db.query(CollectiveMembership).count() == 0
        assert db.query(PaymentTransaction).count() == 0

    def test_nothing_in_this_stage_reads_the_effective_date_to_act(self):
        """The column exists for Stage 5A.2. If something started
        pausing members on it now, that would be this stage doing
        something it was told not to."""
        import ast
        import inspect

        from app.webhooks import collective_membership_handlers as h
        for module in (billing, lifecycle, elig, terms, h):
            names = {
                n.attr for n in ast.walk(ast.parse(inspect.getsource(module)))
                if isinstance(n, ast.Attribute)
            }
            assert "paid_membership_effective_at" not in names, (
                module.__name__
            )

    def test_no_sweep_or_pausing_exists_yet(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(lifecycle))
        names = {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert "paused" not in names


# ---------------------------------------------------------------------------
# The shape Stripe actually sends
# ---------------------------------------------------------------------------


class TestTheRealInvoicePayloadShape:
    """Found by driving a real test-mode invoice through the handler.

    On ``2026-05-27.dahlia`` — the version this account serves — an
    invoice has **no top-level ``subscription``** and carries both the
    subscription id and the subscription's metadata under
    ``parent.subscription_details``. Read against the flat shape alone,
    ``owns_event`` would have missed every renewal and the agreement
    would never have recorded its Stripe subscription id, leaving
    nothing to cancel.

    The fixture below is the real structure, trimmed.
    """

    REAL = {
        "id": "in_real",
        "amount_paid": 2_900,
        "currency": "aud",
        "status": "paid",
        "billing_reason": "subscription_create",
        "parent": {
            "type": "subscription_details",
            "quote_details": None,
            "subscription_details": {
                "subscription": "sub_real",
                "metadata": {
                    "purchase_type": "collective_membership",
                    "collective_membership_id": "cmem_real",
                    "space_id": "s_real",
                    "member_user_id": "u_real",
                },
            },
        },
        "lines": {"data": [{
            "period": {"start": 1794549769, "end": 1797141769},
            "parent": {"subscription_item_details": {
                "subscription": "sub_real", "proration": False,
            }},
        }]},
    }

    def test_it_is_recognised(self):
        assert handlers.owns_event(self.REAL) is True

    def test_the_subscription_id_is_found(self):
        assert handlers._subscription_id_from(self.REAL) == "sub_real"

    def test_there_is_no_top_level_subscription_to_rely_on(self):
        """The assumption that broke. Pinned so a future simplification
        back to ``obj['subscription']`` fails here."""
        assert "subscription" not in self.REAL

    def test_the_legacy_flat_shape_still_works(self):
        legacy = {
            "id": "in_old", "subscription": "sub_old",
            "subscription_details": {
                "metadata": {"purchase_type": "collective_membership"},
            },
        }
        assert handlers.owns_event(legacy) is True
        assert handlers._subscription_id_from(legacy) == "sub_old"

    def test_another_systems_invoice_is_still_not_claimed(self):
        foreign = {
            "id": "in_creator",
            "parent": {"subscription_details": {
                "subscription": "sub_c",
                "metadata": {"purchase_type": "creator_subscription"},
            }},
        }
        assert handlers.owns_event(foreign) is False

    def test_activation_records_the_subscription_id_from_the_real_shape(
        self, db, paid_space, member,
    ):
        """The consequence of the bug, asserted end to end: without the
        id there is nothing to cancel and no way to match a renewal."""
        row = _pending(db, paid_space, member)
        payload = {
            **self.REAL,
            "parent": {
                "type": "subscription_details",
                "subscription_details": {
                    "subscription": "sub_recorded",
                    "metadata": {
                        "purchase_type": "collective_membership",
                        "collective_membership_id": row.id,
                    },
                },
            },
        }
        handlers.handle_invoice_payment_succeeded(
            payload, db, event_id="evt_real",
        )
        db.refresh(row)
        assert row.stripe_subscription_id == "sub_recorded"
        assert row.status == CollectiveMembershipStatus.active.value

    def test_an_invoice_reports_payment_by_status_not_a_boolean(self):
        """The legacy boolean ``paid`` is gone on this API version. Our
        handler never read it — the event type is the verification —
        but this pins the observation."""
        assert "paid" not in self.REAL
        assert self.REAL["status"] == "paid"


# ---------------------------------------------------------------------------
# The dispatcher actually reaches us
# ---------------------------------------------------------------------------


class TestTheRouterRoutesMembershipInvoices:
    """The first attempt at this never fired.

    ``invoice.payment_succeeded`` is already caught by an earlier
    ``elif event_type in ("invoice.paid", "invoice.payment_succeeded")``,
    so a separate ``elif`` for it was unreachable dead code — membership
    would never have activated, and no unit test of the handler would
    have noticed, because the handler itself was fine.

    These tests assert the *wiring*, which is what was broken.
    """

    @staticmethod
    def _code() -> str:
        """Router source with comments stripped.

        The comments explain this very bug at length, so a raw
        substring check fails on its own documentation — the same trap
        twice over.
        """
        import inspect
        import re

        from app.webhooks.routes import stripe_webhook
        src = inspect.getsource(stripe_webhook)
        return "\n".join(
            line for line in src.splitlines()
            if not re.match(r"\s*#", line)
        )

    def test_the_claim_lives_inside_the_branch_that_receives_the_event(self):
        src = self._code()
        tuple_branch = src.index(
            'event_type in ("invoice.paid", "invoice.payment_succeeded")'
        )
        claim = src.index("_cmem_handlers.handle_invoice_payment_succeeded")
        next_branch = src.index("elif event_type ==", tuple_branch)
        assert tuple_branch < claim < next_branch, (
            "the membership claim must sit inside the tuple branch that "
            "actually receives invoice.payment_succeeded"
        )

    def test_there_is_no_second_unreachable_invoice_branch(self):
        src = self._code()
        assert 'elif event_type == "invoice.payment_succeeded"' not in src, (
            "unreachable behind the tuple branch above it"
        )

    def test_a_membership_invoice_never_reaches_the_other_two_systems(self):
        """Claimed in the ``if``, so creator billing and the finite-plan
        handler sit in the ``else`` and cannot see it."""
        src = self._code()
        claim = src.index("_cmem_handlers.handle_invoice_payment_succeeded")
        creator = src.index("_handle_creator_invoice_paid(", claim)
        between = src[claim:creator]
        assert "else:" in between, (
            "the other systems must be in the else branch"
        )

    def test_checkout_completion_is_claimed_before_creator_billing(self):
        src = self._code()
        ours = src.index("_cmem_handlers.handle_checkout_completed")
        creator = src.index('purchase_type") == "creator_subscription"')
        assert ours < creator
