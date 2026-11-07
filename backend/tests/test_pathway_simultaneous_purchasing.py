"""Stage 2B — a Pathway sold individually *and* through Payment Options.

The incident this exists to prevent
-----------------------------------
A Pathway sat on ``pricing_mode='legacy'`` with ``price_cents=500``
beside a published $2 Payment Option. Two records each claimed to be
the price, nothing arbitrated, and the till read the column — so the
Option was configured, displayed, and ignored at the till.

``pricing_mode`` fixed that by making the two mutually exclusive: a
published Option granting a Pathway moved the mode, and the direct door
refused from then on. Stage 2B removes the exclusivity, because §11
requires both doors to be sellable at once. So the protection cannot be
"only one price may exist" any more. It becomes: **each door names
itself, prices itself from its own rows, and says whether it is open.**

What the gate is, and why flipping it is boring
-----------------------------------------------
``pathway_multiple_purchase_options_enabled`` decides which column
answers "is the direct door open":

* shut — ``pricing_mode``, exactly as before.
* open — ``direct_purchase_enabled``.

The whole safety argument rests on one invariant: **while the gate is
shut, ``direct_purchase_enabled`` is a maintained mirror of the
pricing-mode rule.** Migration 183 backfilled it that way and
``sync_direct_offer_flag`` keeps it that way on every creator write. So
opening the gate swaps one expression for an equal one, and no
Pathway's behaviour changes on the day it is flipped. That invariant is
asserted directly in :class:`TestTheMirrorInvariant`, because every
other guarantee here is downstream of it.

``access_type='one_time'`` + ``price_cents > 0`` is deliberately *not*
enough to be an offer. It is true of every Pathway that was ever sold
directly, including those whose price the creator long ago stopped
intending to charge — production carries exactly that row. Inferring an
offer from it would put dormant prices back on sale the moment the gate
opened, which §13 forbids in as many words.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.services import pathway_direct_offer as offer
from app.services import purchase_arrangements as pa


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Builders — same shapes the resolver suite uses
# ---------------------------------------------------------------------------


def _pathway(
    db, space, *, price_cents: int | None = None, access_type: str = "one_time",
    pricing_mode: str = "legacy", status: str = "active",
    currency: str = "AUD", direct: bool | None = None,
    title: str = "Know Yourself",
) -> Pathway:
    """``direct`` defaults to the mirror rule, which is what every real
    row holds — a test that wants a divergent column states it."""
    if direct is None:
        direct = (
            pricing_mode != "payment_options"
            and access_type == "one_time"
            and bool(price_cents)
            and price_cents > 0
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
    db, space, *, name: str = "Three-Pathway Bundle",
    status=PaymentOptionStatus.published, position: int = 0,
    currency: str = "AUD",
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
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


def _grant_pathway(db, option, pathway) -> PaymentOptionGrant:
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
    """Stage 2B enabled. Instalment checkoutability is enabled with it
    so plan schedules are describable — otherwise every instalment
    assertion would be testing the *other* flag."""
    with patch(
        "app.core.config.settings.pathway_multiple_purchase_options_enabled",
        True,
    ), patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


@pytest.fixture
def stripe_configured(monkeypatch):
    """``settings.stripe_enabled`` is a computed property reading both
    secrets, so both are set rather than the property patched."""
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(_s, "stripe_webhook_secret", "whsec_dummy")


@pytest.fixture
def instalments_sellable():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


def _direct(db, pathway) -> pa.Arrangement | None:
    found = pa.arrangements_for(db, kind="pathway", experience_id=pathway.id)
    assert found is not None
    for a in found.arrangements:
        if a.source == "direct":
            return a
    return None


def _options(db, pathway) -> list[pa.Arrangement]:
    found = pa.arrangements_for(db, kind="pathway", experience_id=pathway.id)
    assert found is not None
    return [a for a in found.arrangements if a.source == "payment_option"]


# ===========================================================================
# The invariant everything else rests on
# ===========================================================================


class TestTheMirrorInvariant:
    """While the gate is shut, the new column and the old rule agree.

    If this class passes, opening the gate cannot change any Pathway's
    behaviour — which is the entire safety case for Stage 2B.
    """

    @pytest.mark.parametrize("mode,access,price", [
        ("legacy", "one_time", 500),
        ("legacy", "one_time", None),
        ("legacy", "one_time", 0),
        ("legacy", "free", None),
        ("legacy", "included", None),
        ("legacy", "included_with_offer", None),
        ("legacy", "subscription", 1900),
        ("payment_options", "one_time", 500),
        ("payment_options", "free", None),
        ("payment_options", "included_with_offer", None),
    ])
    def test_the_two_gates_agree_on_every_shape(
        self, db, space, mode, access, price,
    ):
        p = _pathway(
            db, space, pricing_mode=mode, access_type=access,
            price_cents=price,
        )
        shut = offer.direct_purchase_block_reason(p) is None
        with patch(
            "app.core.config.settings"
            ".pathway_multiple_purchase_options_enabled", True,
        ):
            open_ = offer.direct_purchase_block_reason(p) is None
        assert shut == open_, (
            f"{mode}/{access}/{price}: the gate changes behaviour"
        )

    def test_the_sync_reproduces_the_backfill_rule(self, db, space):
        """``sync_direct_offer_flag`` is what keeps the mirror true for
        rows written after migration 183 ran. A Pathway put on a direct
        price today must not lose it when the gate opens."""
        p = _pathway(
            db, space, access_type="included", price_cents=None, direct=False,
        )
        p.access_type = "one_time"
        p.price_cents = 4900
        offer.sync_direct_offer_flag(p)
        assert p.direct_purchase_enabled is True

        # And off again when the creator moves away from a direct price.
        p.access_type = "included_with_offer"
        offer.sync_direct_offer_flag(p)
        assert p.direct_purchase_enabled is False

    def test_the_sync_does_not_fight_the_creator_once_the_gate_is_open(
        self, db, space, gate_open,
    ):
        """With the gate open the creator's control owns the column, so
        the mirror must stand down — otherwise their choice would be
        overwritten by the next save."""
        p = _pathway(db, space, pricing_mode="payment_options",
                     price_cents=500, direct=True)
        offer.sync_direct_offer_flag(p)
        assert p.direct_purchase_enabled is True


# ===========================================================================
# §19 — Disabled
# ===========================================================================


class TestGateShut:
    def test_1_pricing_mode_remains_authoritative(self, db, space):
        p = _pathway(db, space, pricing_mode="payment_options", price_cents=500)
        assert (
            offer.direct_purchase_block_reason(p)
            == offer.REASON_REQUIRES_OPTION
        )

    def test_2_a_direct_only_pathway_still_sells(self, db, space):
        p = _pathway(db, space, price_cents=4900)
        assert offer.direct_purchase_is_available(p)

    def test_3_an_option_only_pathway_still_sells_through_its_option(
        self, db, space,
    ):
        p = _pathway(db, space, pricing_mode="payment_options",
                     access_type="included_with_offer")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        opts = _options(db, p)
        assert len(opts) == 1
        assert opts[0].available_for_new_purchase
        assert opts[0].total_amount_cents == 11900

    def test_4_a_dormant_direct_price_is_unpurchasable(self, db, space):
        """The production row: still ``one_time``, still priced, and
        behind an Option. It must stay shut."""
        p = _pathway(db, space, pricing_mode="payment_options",
                     access_type="one_time", price_cents=500)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)
        assert not offer.direct_purchase_is_available(p)

    def test_5_the_conflicting_price_scenario_stays_protected(self, db, space):
        """A$5 direct beside a A$2 Option — the original incident. With
        the gate shut exactly one door is open, and it is the Option's."""
        p = _pathway(db, space, pricing_mode="payment_options",
                     access_type="one_time", price_cents=500)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)

        assert not offer.direct_purchase_is_available(p)
        opts = _options(db, p)
        assert [a.total_amount_cents for a in opts] == [200]

    def test_6_member_facing_prices_are_unchanged(self, db, space):
        """Each arrangement still reports its own stored amount — no
        blending, no inference in either direction."""
        p = _pathway(db, space, price_cents=500)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)

        assert _direct(db, p).total_amount_cents == 500
        assert _options(db, p)[0].total_amount_cents == 200

    def test_7_the_resolver_answers_exactly_as_before(self, db, space):
        """The gate-shut resolver ignores ``direct_purchase_enabled``
        entirely, so a row with a contradictory column still answers
        the old way."""
        p = _pathway(db, space, price_cents=4900, direct=False)
        a = _direct(db, p)
        assert a is not None
        assert a.available_for_new_purchase, (
            "the gate-shut resolver read the Stage 2B column"
        )


# ===========================================================================
# §19 — Enabled
# ===========================================================================


class TestGateOpen:
    def test_1_direct_only_pathway(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=4900)
        assert offer.direct_purchase_is_available(p)
        assert _direct(db, p).total_amount_cents == 4900
        assert _options(db, p) == []

    def test_2_option_only_pathway(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer",
                     price_cents=None)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        assert not offer.direct_purchase_is_available(p)
        assert len(_options(db, p)) == 1

    def test_3_direct_plus_one_option(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)

        assert offer.direct_purchase_is_available(p)
        assert _direct(db, p).total_amount_cents == 4900
        assert [a.total_amount_cents for a in _options(db, p)] == [11900]

    def test_4_direct_plus_multiple_options(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=4900, direct=True)
        for i, (name, cents) in enumerate(
            [("Three-Pathway Bundle", 11900), ("Everything", 29900)]
        ):
            opt = _option(db, space, name=name, position=i)
            _pay_in_full(db, opt, cents=cents)
            _grant_pathway(db, opt, p)

        assert _direct(db, p).total_amount_cents == 4900
        assert sorted(a.total_amount_cents for a in _options(db, p)) == [
            11900, 29900,
        ]

    def test_5_multiple_schedules_under_one_option(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=12000, position=0)
        _instalments(db, opt, each=3500, count=4, position=1)
        _grant_pathway(db, opt, p)

        opts = _options(db, p)
        assert len(opts) == 2, "one arrangement per schedule, never per Option"
        # Distinct identities, so a member naming one cannot be charged
        # the other.
        assert len({a.arrangement_id for a in opts}) == 2
        plan = next(a for a in opts if a.is_instalment_plan)
        assert plan.installment_amount_cents == 3500
        assert plan.installment_count == 4
        assert plan.total_amount_cents == 14000
        assert plan.upfront_amount_cents == 3500, (
            "the first charge is the first instalment"
        )

    def test_6_a_bundle_names_everything_it_includes(
        self, db, space, gate_open,
    ):
        """§15: do not imply a bundle grants only the Pathway being
        viewed."""
        a = _pathway(db, space, price_cents=4900, title="Pathway A")
        b = _pathway(db, space, price_cents=4900, title="Pathway B")
        opt = _option(db, space, name="Both Pathways")
        _pay_in_full(db, opt, cents=8900)
        _grant_pathway(db, opt, a)
        _grant_pathway(db, opt, b)

        arr = _options(db, a)[0]
        assert arr.is_bundle
        titles = [i.title for i in arr.included]
        assert "Pathway A" in titles and "Pathway B" in titles

    def test_7_pay_in_full_option(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        a = _options(db, p)[0]
        assert a.schedule_type == "pay_in_full"
        assert a.upfront_amount_cents == 11900
        assert not a.is_instalment_plan

    def test_8_instalment_option(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _instalments(db, opt, each=3500, count=4)
        _grant_pathway(db, opt, p)
        a = _options(db, p)[0]
        assert a.is_instalment_plan
        assert a.upfront_amount_cents == 3500
        assert a.total_amount_cents == 14000
        assert a.interval == "week"

    def test_10_an_unavailable_direct_purchase_says_why(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, price_cents=4900, direct=False)
        a = _direct(db, p)
        assert a is not None
        assert not a.available_for_new_purchase
        assert a.unavailable_reason == pa.REASON_DIRECT_PURCHASE_OFF

    def test_11_an_unavailable_option_says_why(self, db, space, gate_open):
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)

        # The direct door is unaffected by the Option's state.
        assert _direct(db, p).available_for_new_purchase
        for a in _options(db, p):
            assert not a.available_for_new_purchase

    def test_12_draft_and_archived_options(self, db, space, gate_open):
        p = _pathway(db, space, access_type="included_with_offer")
        draft = _option(db, space, name="Draft", status=PaymentOptionStatus.draft)
        _pay_in_full(db, draft, cents=1000)
        _grant_pathway(db, draft, p)
        arch = _option(
            db, space, name="Archived", status=PaymentOptionStatus.archived,
            position=1,
        )
        _pay_in_full(db, arch, cents=2000)
        _grant_pathway(db, arch, p)

        by_reason = {a.unavailable_reason for a in _options(db, p)}
        assert pa.REASON_OPTION_DRAFT in by_reason
        assert pa.REASON_OPTION_ARCHIVED in by_reason
        # An archived Option may still be the source of access somebody
        # already paid for.
        archived = [
            a for a in _options(db, p)
            if a.unavailable_reason == pa.REASON_OPTION_ARCHIVED
        ]
        assert archived and archived[0].is_historical_source

    def test_14_different_currencies_keep_their_own(
        self, db, space, gate_open,
    ):
        """Each arrangement carries its own currency. A USD Pathway
        beside an AUD bundle must not render as one number."""
        p = _pathway(db, space, price_cents=4900, currency="USD", direct=True)
        opt = _option(db, space, currency="AUD")
        _pay_in_full(db, opt, cents=11900, currency="AUD")
        _grant_pathway(db, opt, p)

        assert _direct(db, p).currency == "USD"
        assert _options(db, p)[0].currency == "AUD"

    def test_15_a_price_change_after_publication_is_reflected(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, price_cents=4900, direct=True)
        assert _direct(db, p).total_amount_cents == 4900
        p.price_cents = 6900
        db.flush()
        assert _direct(db, p).total_amount_cents == 6900

    def test_17_each_door_keeps_its_own_checkout_identity(
        self, db, space, gate_open,
    ):
        """The identity is what checkout re-derives the price from, so
        the direct arrangement must carry no Option identifiers and the
        Option arrangement must carry both."""
        p = _pathway(db, space, price_cents=500, direct=True)
        opt = _option(db, space)
        sch = _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)

        d = _direct(db, p)
        assert d.payment_option_id is None
        assert d.payment_option_schedule_id is None

        o = _options(db, p)[0]
        assert o.payment_option_id == opt.id
        assert o.payment_option_schedule_id == sch.id

    def test_20_an_arrangement_id_cannot_cross_experiences(
        self, db, space, gate_open,
    ):
        """§16: never substitute one checkout identity for another."""
        mine = _pathway(db, space, price_cents=500, direct=True)
        theirs = _pathway(db, space, price_cents=9900, direct=True)
        other_id = _direct(db, theirs).arrangement_id

        with pytest.raises(pa.ArrangementNotFound):
            pa.resolve_arrangement(
                db, kind="pathway", experience_id=mine.id,
                arrangement_id=other_id,
            )


# ===========================================================================
# §19 — the critical regression scenario, stated as the brief states it
# ===========================================================================


class TestTheFiveDollarTwoDollarIncident:
    """Pathway direct price A$5. Payment Option price A$2."""

    def _setup(self, db, space, *, direct_on: bool):
        p = _pathway(
            db, space, access_type="one_time", price_cents=500,
            pricing_mode="legacy" if direct_on else "payment_options",
            direct=direct_on,
        )
        opt = _option(db, space, name="Programme Payment Plan")
        sch = _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)
        return p, opt, sch

    def test_enabled_the_member_sees_both_amounts(
        self, db, space, gate_open,
    ):
        p, _opt, _sch = self._setup(db, space, direct_on=True)
        assert _direct(db, p).total_amount_cents == 500
        assert _options(db, p)[0].total_amount_cents == 200

    def test_enabled_neither_amount_overrides_the_other(
        self, db, space, gate_open,
    ):
        """Resolved by identity, which is the whole mechanism: a client
        naming the A$2 Option cannot be handed A$5, and vice versa."""
        p, _opt, _sch = self._setup(db, space, direct_on=True)
        direct_id = _direct(db, p).arrangement_id
        option_id = _options(db, p)[0].arrangement_id
        assert direct_id != option_id

        a = pa.resolve_arrangement(
            db, kind="pathway", experience_id=p.id, arrangement_id=direct_id,
        )
        b = pa.resolve_arrangement(
            db, kind="pathway", experience_id=p.id, arrangement_id=option_id,
        )
        assert (a.source, a.total_amount_cents) == ("direct", 500)
        assert (b.source, b.total_amount_cents) == ("payment_option", 200)

    def test_enabled_both_routes_are_purchasable(self, db, space, gate_open):
        p, _opt, _sch = self._setup(db, space, direct_on=True)
        assert _direct(db, p).available_for_new_purchase
        assert _options(db, p)[0].available_for_new_purchase

    def test_disabled_the_dormant_five_dollars_is_never_exposed(
        self, db, space,
    ):
        p, _opt, _sch = self._setup(db, space, direct_on=False)
        assert not offer.direct_purchase_is_available(p)
        assert (
            offer.direct_purchase_block_reason(p)
            == offer.REASON_REQUIRES_OPTION
        )

    def test_disabled_the_option_is_still_the_only_price(self, db, space):
        p, _opt, _sch = self._setup(db, space, direct_on=False)
        assert [a.total_amount_cents for a in _options(db, p)] == [200]


# ===========================================================================
# §19 — at the till. The amount Stripe is asked for is the one that
# matters; everything above is description.
# ===========================================================================


def _mock_session(session_id: str):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=session_id, url="https://checkout.stripe.test/x",
    )


def _buy_direct(db, buyer, pathway):
    """Drive the real till with an option-less request — the direct
    door — and return the mock so the charge can be read off it."""
    from app.checkout.routes import create_pathway_checkout_session
    from app.checkout.schemas import PathwayCheckoutRequest

    sid = f"cs_{uuid.uuid4().hex[:16]}"
    with patch("stripe.checkout.Session.create") as m:
        m.return_value = _mock_session(sid)
        res = create_pathway_checkout_session(
            PathwayCheckoutRequest(
                pathway_id=pathway.id,
                success_url="https://ok/s", cancel_url="https://ok/c",
            ),
            current_user=buyer, db=db,
        )
    return m, res, sid


class TestTheTill:
    def test_18_direct_purchase_charges_the_direct_price(
        self, db, space, make_user, stripe_configured, gate_open,
    ):
        """A$5 direct beside a A$2 Option, gate open, direct selected:
        Stripe must be asked for 500 and not 200."""
        p = _pathway(db, space, price_cents=500, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)
        buyer = make_user()

        m, res, sid = _buy_direct(db, buyer, p)
        assert res.checkout_url

        line = m.call_args.kwargs["line_items"][0]
        amount = line["price_data"]["unit_amount"]
        assert amount == 500, (
            "the till charged something other than the direct price"
        )

        from app.models.payment import PaymentTransaction
        [txn] = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_checkout_session_id == sid)
            .all()
        )
        assert txn.gross_amount_cents == 500
        assert txn.pathway_id == p.id

    def test_the_till_refuses_a_dormant_price_with_the_gate_open(
        self, db, space, make_user, stripe_configured, gate_open,
    ):
        """§13: both rows existing is not an offer."""
        p = _pathway(db, space, price_cents=500, direct=False)
        buyer = make_user()
        with pytest.raises(HTTPException) as exc:
            _buy_direct(db, buyer, p)
        assert exc.value.status_code == 400
        assert "not sold individually" in exc.value.detail

    def test_the_till_refuses_a_dormant_price_with_the_gate_shut(
        self, db, space, make_user, stripe_configured,
    ):
        p = _pathway(db, space, pricing_mode="payment_options",
                     price_cents=500)
        buyer = make_user()
        with pytest.raises(HTTPException) as exc:
            _buy_direct(db, buyer, p)
        assert exc.value.status_code == 400
        assert "payment option" in exc.value.detail.lower()

    def test_an_option_no_longer_closes_the_direct_door(
        self, db, space, make_user, stripe_configured, gate_open,
    ):
        """§11, at the till. Publishing a bundle must not silently take
        a creator's individual price off sale."""
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        buyer = make_user()

        m, _res, _sid = _buy_direct(db, buyer, p)
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "unit_amount"
        ] == 4900

    def test_16_an_existing_purchaser_is_not_asked_to_buy_again(
        self, db, space, make_user, stripe_configured, gate_open,
    ):
        """The duplicate guard predates Stage 2B and must keep working
        with both doors open — §15's "do not prompt members to
        repurchase access they already hold", enforced rather than
        merely displayed."""
        from app.models.platform import PathwayEntitlement, EntitlementStatus
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        buyer = make_user()
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=p.id,
            space_id=space.id, source="one_time_purchase",
            status=EntitlementStatus.active,
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            _buy_direct(db, buyer, p)
        assert exc.value.status_code == 409

    def test_20_a_price_removed_mid_session_is_refused_not_substituted(
        self, db, space, make_user, stripe_configured, gate_open,
    ):
        """The member was shown A$5, the creator switched the offer off,
        and the member pressed Buy. The till must refuse rather than
        reach for the Option's A$2."""
        p = _pathway(db, space, price_cents=500, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant_pathway(db, opt, p)
        buyer = make_user()

        p.direct_purchase_enabled = False
        db.flush()

        with pytest.raises(HTTPException) as exc:
            _buy_direct(db, buyer, p)
        assert exc.value.status_code == 400

        from app.models.payment import PaymentTransaction
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.pathway_id == p.id,
        ).count() == 0, "a refused purchase left a transaction behind"

    def test_9_an_archived_option_purchaser_keeps_access(
        self, db, space, make_user, gate_open,
    ):
        """§17: an entitlement is never removed because another source
        appeared or went away. Opening the direct door must not disturb
        somebody who bought through a since-archived bundle."""
        from app.models.platform import PathwayEntitlement, EntitlementStatus
        from app.services.pathway_access import compute_pathway_access
        from app.models.platform import SpaceMembership, SpaceMembershipStatus
        from datetime import datetime

        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _pay_in_full(db, opt, cents=11900)
        _grant_pathway(db, opt, p)
        buyer = make_user()
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, pathway_id=p.id,
            space_id=space.id, source="included",
            status=EntitlementStatus.active,
        ))
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=buyer.id,
            role="learner", status=SpaceMembershipStatus.active,
            source="purchase", joined_at=datetime.utcnow(),
        ))
        db.flush()

        assert compute_pathway_access(buyer, p, space, db, as_member=True)


# ===========================================================================
# The Collective headline — "Pathways from $X"
# ===========================================================================


class TestTheCollectiveHeadline:
    """The ``Pathways from $X`` figure on Explore and the public About
    page. It keyed each Pathway by ``pricing_mode``, which was right
    while the two were exclusive and wrong once they are not: a Pathway
    with a live A$49 price and a cheaper A$29 bundle would have
    advertised whichever one its mode happened to name.
    """

    def _min(self, db, space):
        from app.spaces.pathway_pricing import min_paid_price_cents_for_space
        return min_paid_price_cents_for_space(db, space.id)

    def test_shut_a_legacy_pathway_advertises_its_own_price(
        self, db, space, instalments_sellable,
    ):
        p = _pathway(db, space, price_cents=4900)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900)
        _grant_pathway(db, opt, p)
        # Unchanged: the Option was ignored at the till in legacy mode,
        # so advertising A$29 would have been a promise nothing kept.
        assert self._min(db, space) == 4900

    def test_shut_an_option_pathway_advertises_the_option(
        self, db, space, instalments_sellable,
    ):
        p = _pathway(db, space, pricing_mode="payment_options",
                     access_type="one_time", price_cents=4900)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900)
        _grant_pathway(db, opt, p)
        assert self._min(db, space) == 2900

    def test_open_the_cheaper_of_two_live_doors_wins(
        self, db, space, gate_open,
    ):
        p = _pathway(db, space, price_cents=4900, direct=True)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900)
        _grant_pathway(db, opt, p)
        assert self._min(db, space) == 2900, (
            "the headline missed a cheaper live bundle"
        )

    def test_open_a_dormant_price_is_not_advertised(
        self, db, space, gate_open,
    ):
        """The direct price is off; only the Option may be quoted."""
        p = _pathway(db, space, access_type="one_time", price_cents=500,
                     pricing_mode="payment_options", direct=False)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=2900)
        _grant_pathway(db, opt, p)
        assert self._min(db, space) == 2900

    def test_open_a_direct_only_pathway_still_advertises_its_price(
        self, db, space, gate_open,
    ):
        _pathway(db, space, price_cents=4900, direct=True)
        assert self._min(db, space) == 4900
