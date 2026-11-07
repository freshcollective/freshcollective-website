"""Stage 2C — the member "Ways to join" cards for a Pathway.

What this is protecting
-----------------------
The page used to show one amount. With a A$59 direct price beside a
A$29 bundle, "From A$59" was wrong, and "From A$29" would have been
wrong in the other direction — a single headline cannot describe two
arrangements, so the fix is to stop trying and show the choices.

These tests are about the *list*: that every buyable arrangement is in
it, that nothing unbuyable is, that each entry carries its own price,
currency and checkout identity, and that the order is the creator's
rather than cheapest-first. What each arrangement actually charges at
the till is pinned by ``test_pathway_simultaneous_purchasing.py``; this
file does not re-assert it, because the builder reads the same resolver
and a second copy of that assertion would only ever agree with itself.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.spaces.pathway_arrangement_display import build_ways_to_join


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway(
    db, space, *, price_cents: int | None = None, access_type: str = "one_time",
    pricing_mode: str = "legacy", status: str = "active",
    currency: str = "AUD", direct: bool | None = None,
    title: str = "New Pathway for Moonlit Circle",
) -> Pathway:
    if direct is None:
        direct = (
            pricing_mode != "payment_options"
            and access_type == "one_time"
            and bool(price_cents) and price_cents > 0
        )
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status=status, access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode=pricing_mode, price_cents=price_cents,
        currency=currency, direct_purchase_enabled=direct,
    )
    db.add(p)
    db.flush()
    return p


def _option(
    db, space, *, name: str = "Test pathway bundle",
    status=PaymentOptionStatus.published, position: int = 0,
    currency: str = "AUD", description: str | None = None,
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name, description=description,
        payment_type=PaymentOptionType.one_time, status=status,
        currency=currency, position=position,
    )
    db.add(opt)
    db.flush()
    return opt


def _pay_in_full(db, option, *, cents: int, currency: str = "AUD",
                 status: str = "published", name: str = "Pay in full",
                 position: int = 0) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _instalments(db, option, *, each: int, count: int, interval: str = "week",
                 currency: str = "AUD", status: str = "published",
                 name: str = "Weekly payments", position: int = 1,
                 ) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        total_amount_cents=each * count,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval, stripe_interval_count=1,
        currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _grant(db, option, pathway) -> PaymentOptionGrant:
    g = PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=option.id, grant_kind="pathway",
        pathway_id=pathway.id,
    )
    db.add(g)
    db.flush()
    return g


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def gate_open():
    with patch(
        "app.core.config.settings.pathway_multiple_purchase_options_enabled",
        True,
    ), patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


def _cards(db, pathway):
    return build_ways_to_join(db, pathway=pathway)


# ---------------------------------------------------------------------------
# Single arrangement (§8)
# ---------------------------------------------------------------------------


class TestDirectPurchaseOnly:
    def test_one_card_with_its_own_price(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900)
        cards = _cards(db, p)
        assert len(cards) == 1
        [card] = cards
        assert card.source == "direct"
        assert card.price_cents == 5900
        assert card.currency == "AUD"
        assert card.schedules == []
        assert card.payment_option_id is None, (
            "a direct card must carry no Option identity to substitute"
        )

    def test_the_currency_is_the_pathways_own(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, currency="USD")
        [card] = _cards(db, p)
        assert card.currency == "USD"

    def test_included_titles_are_empty(self, db, space, gate_open):
        """A direct purchase grants this Pathway and nothing else, which
        the card says in words rather than in a list of one."""
        p = _pathway(db, space, price_cents=5900)
        [card] = _cards(db, p)
        assert card.included_titles == []
        assert card.is_bundle is False


class TestPaymentOptionOnly:
    def test_the_option_and_its_schedule(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, description="Testing multiple ways.")
        sch = _pay_in_full(db, opt, cents=2900)
        _grant(db, opt, p)

        [card] = _cards(db, p)
        assert card.source == "payment_option"
        assert card.name == "Test pathway bundle"
        assert card.description == "Testing multiple ways."
        assert card.payment_option_id == opt.id
        assert [s.id for s in card.schedules] == [sch.id]
        assert card.schedules[0].total_amount_cents == 2900
        assert card.schedules[0].is_member_checkoutable is True

    def test_it_names_what_it_includes(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        [card] = self._bundle_of_three(db, space, p)
        assert card.included_titles[0] == p.title, (
            "the Pathway being viewed leads the list"
        )
        assert "Know Yourself" in card.included_titles
        assert "Embrace Yourself" in card.included_titles
        assert card.is_bundle is True

    def _bundle_of_three(self, db, space, viewed):
        other_a = _pathway(db, space, access_type="included",
                           title="Know Yourself")
        other_b = _pathway(db, space, access_type="included",
                           title="Embrace Yourself")
        opt = _option(db, space, name="Personal Growth Collection")
        _pay_in_full(db, opt, cents=11900)
        for pw in (viewed, other_a, other_b):
            _grant(db, opt, pw)
        return _cards(db, viewed)

    def test_the_included_order_is_stable(self, db, space, gate_open):
        """The resolver returns ``included`` in grant *query* order,
        which is not deterministic — the Series equivalence test caught
        it flipping between runs. A card whose "Also includes" line
        reorders itself between page loads is a bug nobody can
        reproduce, so the viewed Pathway is pinned to the front."""
        p = _pathway(db, space, access_type="included_with_offer")
        first = self._bundle_of_three(db, space, p)[0].included_titles
        db.expire_all()
        second = build_ways_to_join(db, pathway=p)[0].included_titles
        assert first[0] == second[0] == p.title


# ---------------------------------------------------------------------------
# Simultaneous (§4, §5)
# ---------------------------------------------------------------------------


class TestBothArrangements:
    def _moonlit(self, db, space):
        p = _pathway(db, space, price_cents=5900, direct=True)
        opt = _option(db, space, name="Test pathway bundle")
        sch = _pay_in_full(db, opt, cents=2900)
        _grant(db, opt, p)
        return p, opt, sch

    def test_both_cards_appear(self, db, space, gate_open):
        p, opt, _sch = self._moonlit(db, space)
        cards = _cards(db, p)
        assert [c.source for c in cards] == ["direct", "payment_option"]
        assert cards[0].price_cents == 5900
        assert cards[1].schedules[0].total_amount_cents == 2900

    def test_each_keeps_its_own_price_and_identity(self, db, space, gate_open):
        """The guarantee that matters: neither card can be used to
        charge the other's amount, because the direct card carries no
        Option identity and the Option card carries no bare price."""
        p, opt, sch = self._moonlit(db, space)
        direct, option = _cards(db, p)

        assert direct.price_cents == 5900
        assert direct.payment_option_id is None
        assert direct.schedules == []

        assert option.price_cents is None
        assert option.payment_option_id == opt.id
        assert [s.id for s in option.schedules] == [sch.id]

    def test_the_order_is_not_by_price(self, db, space, gate_open):
        """A$29 is cheaper than A$59 and still comes second. Ordering is
        the resolver's — direct first, then the creator's own Option
        order — never a judgement about which is the better deal."""
        p, _opt, _sch = self._moonlit(db, space)
        cards = _cards(db, p)
        amounts = [
            c.price_cents if c.source == "direct"
            else c.schedules[0].total_amount_cents
            for c in cards
        ]
        assert amounts == [5900, 2900]

    def test_creator_option_order_is_preserved(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, direct=True)
        for i, name in enumerate(["Second", "First"]):
            # position is what the creator's Reorder control writes;
            # the names are deliberately the wrong way round
            # alphabetically so an accidental sort would show.
            opt = _option(db, space, name=name, position=1 - i)
            _pay_in_full(db, opt, cents=1000 + i)
            _grant(db, opt, p)

        cards = _cards(db, p)
        assert [c.name for c in cards[1:]] == ["First", "Second"]

    def test_different_currencies_are_not_blended(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, currency="USD", direct=True)
        opt = _option(db, space, currency="AUD")
        _pay_in_full(db, opt, cents=2900, currency="AUD")
        _grant(db, opt, p)

        direct, option = _cards(db, p)
        assert direct.currency == "USD"
        assert option.schedules[0].currency == "AUD"


class TestTheFiveDollarTwoDollarIncident:
    """Direct A$5, Option A$2 — the conflict ``pricing_mode`` existed
    to prevent, now presented rather than suppressed."""

    def test_both_display_with_their_own_amounts(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=500, direct=True)
        opt = _option(db, space, name="Programme Payment Plan")
        _pay_in_full(db, opt, cents=200)
        _grant(db, opt, p)

        direct, option = _cards(db, p)
        assert direct.price_cents == 500
        assert option.schedules[0].total_amount_cents == 200

    def test_no_single_amount_can_stand_for_the_pair(
        self, db, space, gate_open,
    ):
        """There is deliberately no field a surface could render as a
        headline — the builder returns a list, and the cheapest is not
        marked, so "From A$5" is not expressible from this payload."""
        p = _pathway(db, space, price_cents=500, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant(db, opt, p)

        cards = _cards(db, p)
        assert len(cards) == 2
        assert not any(hasattr(c, "headline_price_cents") for c in cards)


# ---------------------------------------------------------------------------
# Multiple schedules (§6)
# ---------------------------------------------------------------------------


class TestMultipleSchedules:
    def test_pay_in_full_and_a_plan_are_separate_actions(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, name="Personal Growth Programme")
        full = _pay_in_full(db, opt, cents=14000, position=0)
        plan = _instalments(db, opt, each=3500, count=4, position=1)
        _grant(db, opt, p)

        [card] = _cards(db, p)
        assert [s.id for s in card.schedules] == [full.id, plan.id]

        pif, instal = card.schedules
        assert pif.schedule_type == "pay_in_full"
        assert pif.total_amount_cents == 14000

        assert instal.schedule_type == "recurring_installments"
        assert instal.installment_amount_cents == 3500, "the first payment"
        assert instal.installment_count == 4
        assert instal.interval == "week"
        assert instal.total_amount_cents == 14000

    def test_the_first_payment_is_the_first_instalment(
        self, db, space, gate_open,
    ):
        """Not the schedule's stored ``upfront_amount_cents``: nothing
        collects that, so presenting it as a first charge would repeat
        a creator's mistake to a member as a fact."""
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        sch = _instalments(db, opt, each=3500, count=4)
        sch.upfront_amount_cents = 9900
        _grant(db, opt, p)
        db.flush()

        [card] = _cards(db, p)
        assert card.schedules[0].installment_amount_cents == 3500


# ---------------------------------------------------------------------------
# Availability (§8)
# ---------------------------------------------------------------------------


class TestNothingUnbuyableIsOffered:
    def test_a_draft_option_is_absent(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, direct=True)
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _pay_in_full(db, opt, cents=2900)
        _grant(db, opt, p)
        assert [c.source for c in _cards(db, p)] == ["direct"]

    def test_an_archived_option_is_absent(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, direct=True)
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _pay_in_full(db, opt, cents=2900)
        _grant(db, opt, p)
        assert [c.source for c in _cards(db, p)] == ["direct"]

    def test_a_draft_schedule_is_absent(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900, status="draft")
        _grant(db, opt, p)
        assert _cards(db, p) == []

    def test_an_option_with_no_buyable_schedule_is_absent(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, price_cents=5900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900, status="draft")
        _grant(db, opt, p)
        cards = _cards(db, p)
        assert [c.source for c in cards] == ["direct"]
        assert all(c.schedules or c.source == "direct" for c in cards), (
            "an Option card was rendered with nothing to buy"
        )

    def test_a_dormant_direct_price_is_absent(self, db, space, gate_open):
        """The saved amount survives — Stage 2A made that the default —
        but it is not an offer until the creator says so."""
        p = _pathway(db, space, price_cents=5900, direct=False)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900)
        _grant(db, opt, p)
        assert [c.source for c in _cards(db, p)] == ["payment_option"]

    def test_a_draft_pathway_offers_nothing(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=5900, status="draft")
        assert _cards(db, p) == []

    def test_a_free_pathway_offers_nothing(self, db, space, gate_open):
        p = _pathway(db, space, access_type="free")
        assert _cards(db, p) == []

    def test_a_members_only_pathway_offers_nothing(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, access_type="included")
        assert _cards(db, p) == []

    def test_instalments_switched_off_hide_the_plan_not_the_option(
        self, db, space,
    ):
        """``finite_plan_member_checkout_enabled`` is off here. The
        pay-in-full row survives; the plan row does not, because the
        till would refuse it."""
        with patch(
            "app.core.config.settings"
            ".pathway_multiple_purchase_options_enabled", True,
        ), patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled",
            False,
        ):
            p = _pathway(db, space, access_type="included_with_offer")
            opt = _option(db, space)
            full = _pay_in_full(db, opt, cents=14000, position=0)
            _instalments(db, opt, each=3500, count=4, position=1)
            _grant(db, opt, p)

            [card] = _cards(db, p)
            assert [s.id for s in card.schedules] == [full.id]


class TestTheGateIsStillHonoured:
    def test_shut_a_dormant_price_behind_an_option_stays_hidden(
        self, db, space,
    ):
        """Stage 2B's protection, unchanged by the new presentation."""
        p = _pathway(db, space, pricing_mode="payment_options",
                     access_type="one_time", price_cents=500)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant(db, opt, p)
        assert [c.source for c in _cards(db, p)] == ["payment_option"]

    def test_shut_a_legacy_direct_price_still_shows(self, db, space):
        p = _pathway(db, space, price_cents=5900)
        assert [c.source for c in _cards(db, p)] == ["direct"]
