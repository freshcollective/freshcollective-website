"""The price the public About page quotes for a Collective's Pathways.

The production report
---------------------
Test Pathway sat at ``pricing_mode='payment_options'`` with a published
$2 Payment Option, and still carried ``price_cents=500`` in the legacy
column the mode switch left behind. The Collective About page rendered
"Pathways from $5 AUD".

Nothing was wrong with the derivation in ``spaces/routes.py`` — it reads
``pricing_mode`` and goes to the published Options for a payment-options
Pathway. The problem was that the derivation only ran for the Explore
listing (``PublicSpaceCard``), while ``GET /api/spaces/{slug}`` never
carried the field at all. With nothing authoritative in the payload, the
About page derived its own from ``pathway.price_cents``, which is
exactly the stale column.

The second report, same page
----------------------------
Test Connect Instalments is a published Option whose
``override_total_cents`` and ``calculated_total_cents`` are both NULL —
the normal state, because the commerce UI treats schedules as the
source of truth. Its whole price lives on a published schedule: two
weekly payments of $2, $4 committed. The first fix derived the price as
``COALESCE(override_total_cents, calculated_total_cents)``, so this
Option produced NULL and the About page fell back to "Paid pathways
available separately" for a Collective that plainly sells something.

The headline is now ``purchase_schedule_view.headline_price_cents`` —
the same projection the joining doors and the Series sidebar use. It
reports **total commitment**, so that Option's Collective headline is
$4, not the $2 instalment.

What this file covers
---------------------
* ``min_paid_price_cents_by_space`` — the rule itself, per pricing_mode,
  and per schedule shape.
* ``GET /api/spaces/{slug}`` now serves ``min_paid_pathway_price_cents``,
  so the page has a source of truth to read.
* The Explore listing still reports the same number, because both now
  call the one helper.

Handlers are invoked directly so the tests share the SAVEPOINT-wrapped
session the fixtures write into — the same pattern as
``test_public_spaces_slug_endpoint.py``.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.spaces import pathway_pricing
from app.spaces.routes import get_space, hydrate_public_space_cards


# The production numbers, kept verbatim.
STALE_LEGACY_CENTS = 500
PUBLISHED_OPTION_CENTS = 200
# Test Connect Instalments: 2 weekly payments of $2, $4 committed.
INSTALMENT_CENTS = 200
INSTALMENT_COUNT = 2
PLAN_TOTAL_CENTS = INSTALMENT_CENTS * INSTALMENT_COUNT   # 400


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway(
    db, space, *, pricing_mode: str, price_cents: int | None,
    status: str = "active", access_type: str = "one_time",
    title: str = "Test Pathway",
) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title,
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode=pricing_mode,
        price_cents=price_cents,
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _bare_option(
    db, space, pathway, *,
    name: str,
    calculated_total_cents: int | None,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
) -> PaymentOption:
    """An Option granting ``pathway``, with no schedules yet."""
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name=name,
        payment_type=PaymentOptionType.one_time,
        status=status,
        calculated_total_cents=calculated_total_cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    db.add(PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=opt.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    ))
    db.flush()
    return opt


def _published_option(
    db, space, pathway, *,
    cents: int = PUBLISHED_OPTION_CENTS,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
) -> PaymentOption:
    """A pay-in-full Option at ``cents``, with its authoring columns
    populated — the shape where ``effective_price_cents`` agrees with
    the schedule. Retained deliberately: the schedule-aware rewrite
    must not regress the Options that were already priced correctly."""
    opt = _bare_option(
        db, space, pathway,
        name=f"${cents // 100} Option",
        calculated_total_cents=cents,
        status=status,
    )
    db.add(PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=opt.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=cents,
        currency="AUD",
        position=0,
    ))
    db.flush()
    return opt


def _instalment_plan_option(
    db, space, pathway, *,
    instalment_cents: int = INSTALMENT_CENTS,
    count: int = INSTALMENT_COUNT,
    schedule_status: str = "published",
    option_total_cents: int | None = None,
) -> PaymentOption:
    """Test Connect Instalments, as production holds it.

    Both authoring columns NULL by default — the real state of this
    Option — so the price exists only on the schedule. The schedule is
    structurally valid for ``validate_recurring_installments_row``:
    equal instalments, a supported cadence, and a total that is exactly
    per-instalment x count.
    """
    opt = _bare_option(
        db, space, pathway,
        name="Test Connect Instalments",
        calculated_total_cents=option_total_cents,
    )
    db.add(PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=opt.id,
        name=f"{count} weekly payments",
        schedule_type="recurring_installments",
        status=schedule_status,
        total_amount_cents=instalment_cents * count,
        installment_amount_cents=instalment_cents,
        installment_count=count,
        interval="weekly",
        stripe_interval="week",
        stripe_interval_count=1,
        currency="AUD",
        position=0,
    ))
    db.flush()
    return opt


def _add_pay_in_full(db, option, *, cents: int, position: int = 1) -> None:
    """A second payment method on an existing Option."""
    db.add(PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=option.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=cents,
        currency="AUD",
        position=position,
    ))
    db.flush()


@pytest.fixture
def plans_checkoutable(monkeypatch):
    """Finite plans offered to members.

    ``_schedule_is_member_checkoutable`` gates recurring instalments on
    this flag, and the Collective headline honours that predicate — a
    price whose only payment method checkout would refuse is not a
    price. The flag defaults to False, so every instalment-plan
    assertion has to say which world it is in.
    """
    from app.core.config import settings
    monkeypatch.setattr(
        settings, "finite_plan_member_checkout_enabled", True,
    )


@pytest.fixture
def space(db, make_space):
    s = make_space(
        slug=f"about-pricing-{uuid.uuid4().hex[:8]}",
        status="active",
        is_public=True,
        auto_grant_role=None,
    )
    db.flush()
    return s


def _min_for(db, space) -> int | None:
    return pathway_pricing.min_paid_price_cents_for_space(db, space.id)


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


class TestTheDerivationItself:
    def test_the_reported_scenario_derives_two_dollars_not_five(
        self, db, space,
    ):
        """Stale legacy column beside a published $2 Option."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(db, space, pathway)

        assert _min_for(db, space) == PUBLISHED_OPTION_CENTS

    def test_a_legacy_pathway_uses_its_own_price(self, db, space):
        """The case that must keep working: no Options, legacy mode."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        assert _min_for(db, space) == 1800

    def test_a_payment_options_pathway_ignores_the_legacy_column(
        self, db, space,
    ):
        """price_cents=None is the normal state after a clean switch. The
        price must still be found, from the Option."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _published_option(db, space, pathway)

        assert _min_for(db, space) == PUBLISHED_OPTION_CENTS

    def test_draft_options_do_not_set_the_headline_price(self, db, space):
        """A price nobody can buy yet must not be advertised. With only a
        draft Option there is nothing purchasable to quote, and the stale
        legacy column must not fill the gap."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(
            db, space, pathway, status=PaymentOptionStatus.draft,
        )

        assert _min_for(db, space) is None

    def test_the_cheaper_of_two_modes_wins(self, db, space):
        """A Collective holding one Pathway of each mode advertises the
        cheaper door."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)
        options_pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Options Pathway",
        )
        _published_option(db, space, options_pathway)

        assert _min_for(db, space) == PUBLISHED_OPTION_CENTS

    def test_an_expensive_option_does_not_undercut_a_cheap_legacy(
        self, db, space,
    ):
        """The same comparison in the other direction."""
        _pathway(db, space, pricing_mode="legacy", price_cents=300)
        options_pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Options Pathway",
        )
        _published_option(db, space, options_pathway, cents=9900)

        assert _min_for(db, space) == 300

    def test_a_free_pathway_does_not_drag_the_minimum_to_zero(
        self, db, space,
    ):
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)
        _pathway(
            db, space, pricing_mode="legacy", price_cents=0,
            access_type="free", title="Free Pathway",
        )

        assert _min_for(db, space) == 1800

    def test_an_archived_pathway_is_not_priced(self, db, space):
        _pathway(
            db, space, pricing_mode="legacy", price_cents=100,
            status="archived", title="Archived Pathway",
        )

        assert _min_for(db, space) is None

    def test_nothing_paid_inside_returns_none(self, db, space):
        assert _min_for(db, space) is None

    def test_no_space_ids_is_an_empty_mapping(self, db):
        """Guard the batch helper's early return."""
        assert pathway_pricing.min_paid_price_cents_by_space(db, []) == {}


# ---------------------------------------------------------------------------
# Schedule-expressed prices — the Test Connect Instalments report
# ---------------------------------------------------------------------------


class TestAnOptionPricedOnlyByItsSchedule:
    """The authoring columns are NULL and the schedule carries the price.
    The old COALESCE produced NULL here, which is the whole bug."""

    def test_the_reported_option_prices_at_the_total_commitment(
        self, db, space, plans_checkoutable,
    ):
        """$4, not $2. The headline is what the member commits to, not
        what leaves their account on the first Friday."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway)

        assert _min_for(db, space) == PLAN_TOTAL_CENTS
        # The two numbers this must not produce: the stale legacy
        # column, and the per-instalment amount.
        assert _min_for(db, space) != STALE_LEGACY_CENTS
        assert _min_for(db, space) != INSTALMENT_CENTS

    def test_it_is_not_silence(self, db, space, plans_checkoutable):
        """Before the fix this returned None, and the About page said
        "Paid pathways available separately" — generic copy for a
        Collective with a published, buyable Option."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)

        assert _min_for(db, space) is not None

    def test_the_authoring_columns_really_are_null(
        self, db, space, plans_checkoutable,
    ):
        """The premise, asserted rather than assumed. If a future
        migration backfills these, this file should be revisited rather
        than trusted."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)

        assert option.override_total_cents is None
        assert option.calculated_total_cents is None
        assert option.effective_price_cents is None

    def test_a_discounted_pay_in_full_becomes_the_headline(
        self, db, space, plans_checkoutable,
    ):
        """``headline_price_cents`` prefers the pay-in-full total where
        one is offered, because that is the commitment people compare
        on. Mirrored here so the Collective headline cannot drift from
        the Option's own."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)
        _add_pay_in_full(db, option, cents=350)

        assert _min_for(db, space) == 350

    def test_pay_in_full_wins_even_when_it_is_the_dearer_method(
        self, db, space, plans_checkoutable,
    ):
        """The discriminating case. A cheaper pay-in-full also satisfies
        "cheapest wins", so it cannot tell the two rules apart; this
        can.

        ``headline_price_cents`` returns the pay-in-full total
        unconditionally when one is checkoutable, so a Collective whose
        Option offers a $4 plan and a $5 lump sum quotes $5. That is a
        real consequence of matching the canonical helper rather than
        minimising, and it is asserted rather than left to be
        discovered — the alternative would be a second, quietly
        different definition of the same price.
        """
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)
        _add_pay_in_full(db, option, cents=500)

        assert _min_for(db, space) == 500

    def test_the_cheapest_checkoutable_schedule_wins_without_pay_in_full(
        self, db, space, plans_checkoutable,
    ):
        """Two plans, no pay-in-full: the lower total is the headline."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)
        db.add(PaymentOptionSchedule(
            id=_uid("pos"),
            payment_option_id=option.id,
            name="4 weekly payments",
            schedule_type="recurring_installments",
            status="published",
            total_amount_cents=1200,
            installment_amount_cents=300,
            installment_count=4,
            interval="weekly",
            stripe_interval="week",
            stripe_interval_count=1,
            currency="AUD",
            position=1,
        ))
        db.flush()

        assert _min_for(db, space) == PLAN_TOTAL_CENTS

    def test_a_draft_schedule_is_not_a_price(
        self, db, space, plans_checkoutable,
    ):
        """Schedule-level status, not just Option-level. A plan the
        creator has not published yet cannot set the headline, and the
        stale legacy column must not fill the gap."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway, schedule_status="draft")

        assert _min_for(db, space) is None

    def test_a_structurally_invalid_plan_is_not_a_price(
        self, db, space, plans_checkoutable,
    ):
        """Same predicate the checkout endpoint enforces: a total that
        disagrees with per-instalment x count would 422 there, so it
        must not be advertised here."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)
        schedule = (
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.payment_option_id == option.id)
            .one()
        )
        schedule.total_amount_cents = 999      # != 200 x 2
        db.flush()

        assert _min_for(db, space) is None

    def test_a_single_payment_plan_is_not_a_price(
        self, db, space, plans_checkoutable,
    ):
        """``installment_count`` below 2 fails the row validator — a
        one-payment "plan" is a pay_in_full schedule."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway, count=1)

        assert _min_for(db, space) is None


class TestCheckoutabilityGatesTheHeadline:
    """A Collective must not advertise a price nobody can pay."""

    def test_with_member_plans_disabled_a_plan_only_option_is_silent(
        self, db, space,
    ):
        """No ``plans_checkoutable`` fixture: the flag is at its default
        False, as in an environment that has not completed the finite-plan
        rollout. The Option is published and the schedule is valid, but
        checkout would refuse it, so there is no price to quote.

        Deliberate, and the reason the headline runs through
        ``_schedule_is_member_checkoutable`` rather than reading totals
        directly."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway)

        assert _min_for(db, space) is None

    def test_the_flag_does_not_affect_pay_in_full(self, db, space):
        """Pay-in-full is always checkoutable, so the same Collective
        with a pay-in-full Option prices normally regardless."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _published_option(db, space, pathway)

        assert _min_for(db, space) == PUBLISHED_OPTION_CENTS

    def test_a_gathering_grant_plan_is_not_offered(
        self, db, space, make_event, plans_checkoutable,
    ):
        """``_option_supports_finite_member_checkout`` refuses a plan
        whose bundle includes a Gathering grant — the finite-plan path
        cannot fulfil one — so it is not a price either."""
        from app.models.payment_option_grant import GRANT_KIND_GATHERING

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)
        gathering = make_event(space=space)
        db.add(PaymentOptionGrant(
            id=_uid("pog"),
            payment_option_id=option.id,
            grant_kind=GRANT_KIND_GATHERING,
            event_id=gathering.id,
            position=1,
        ))
        db.flush()

        assert _min_for(db, space) is None


class TestTheFallbackToTheOptionsOwnPrice:
    """``effective_price_cents`` is the last resort, not the first."""

    def test_an_option_with_no_schedules_uses_its_own_price(
        self, db, space,
    ):
        """A shape that should not occur for a purchasable Option, but
        which must degrade to a number rather than to silence."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _bare_option(
            db, space, pathway,
            name="Columns-only Option",
            calculated_total_cents=2500,
        )

        assert _min_for(db, space) == 2500

    def test_an_option_with_neither_is_silent_not_zero(self, db, space):
        """No schedules, no columns. Must not become a $0 headline."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _bare_option(
            db, space, pathway,
            name="Priceless Option",
            calculated_total_cents=None,
        )

        assert _min_for(db, space) is None

    def test_a_schedule_price_beats_the_option_columns(
        self, db, space, plans_checkoutable,
    ):
        """When both exist the schedule wins — it is what checkout
        charges. An Option whose stale columns disagree with its live
        schedule must quote the schedule."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(
            db, space, pathway, option_total_cents=9900,
        )

        assert _min_for(db, space) == PLAN_TOTAL_CENTS


class TestMixedCollectives:
    def test_a_plan_total_competes_with_a_legacy_price(
        self, db, space, plans_checkoutable,
    ):
        """One Pathway of each mode: the cheaper headline wins, and the
        plan's $4 total is what enters the comparison."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)
        options_pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Instalments Pathway",
        )
        _instalment_plan_option(db, space, options_pathway)

        assert _min_for(db, space) == PLAN_TOTAL_CENTS

    def test_a_cheaper_legacy_price_still_wins(
        self, db, space, plans_checkoutable,
    ):
        _pathway(db, space, pricing_mode="legacy", price_cents=300)
        options_pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Instalments Pathway",
        )
        _instalment_plan_option(db, space, options_pathway)

        assert _min_for(db, space) == 300

    def test_two_options_on_one_pathway_take_the_cheaper(
        self, db, space, plans_checkoutable,
    ):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)
        _published_option(db, space, pathway, cents=1000)

        assert _min_for(db, space) == PLAN_TOTAL_CENTS

    def test_one_option_selling_two_pathways_is_counted_once(
        self, db, space, plans_checkoutable,
    ):
        """The pairs join yields a row per (pathway, option). Collapsing
        to unique Options must not lose the space mapping."""
        first = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        second = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
            title="Second Pathway",
        )
        option = _instalment_plan_option(db, space, first)
        db.add(PaymentOptionGrant(
            id=_uid("pog"),
            payment_option_id=option.id,
            grant_kind="pathway",
            pathway_id=second.id,
        ))
        db.flush()

        assert _min_for(db, space) == PLAN_TOTAL_CENTS


class TestTheHeadlineMatchesTheCanonicalHelper:
    def test_the_collective_quotes_what_the_option_quotes(
        self, db, space, plans_checkoutable,
    ):
        """Not a third definition of Option headline price: the same
        ``headline_price_cents`` the joining doors and Series sidebar
        call, asserted side by side so a future divergence fails here."""
        from app.spaces.purchase_schedule_view import (
            headline_price_cents,
            published_schedules_by_option,
            schedule_view,
        )

        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        option = _instalment_plan_option(db, space, pathway)

        schedules = published_schedules_by_option(db, [option.id])[option.id]
        canonical = headline_price_cents(
            [schedule_view(s, option) for s in schedules], option,
        )

        assert canonical == PLAN_TOTAL_CENTS
        assert _min_for(db, space) == canonical


# ---------------------------------------------------------------------------
# The endpoint the About page actually reads
# ---------------------------------------------------------------------------


class TestTheDetailEndpointCarriesThePrice:
    def test_the_reported_collective_is_served_four_dollars(
        self, db, space, plans_checkoutable,
    ):
        """The whole chain, end to end: stale legacy 500 on a
        payment-options Pathway, a published 2 x $2 plan, and the
        endpoint the About page reads reports 400."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == PLAN_TOTAL_CENTS

    def test_the_field_is_served_at_all(self, db, space):
        """The gap behind the first bug: with nothing authoritative in
        the payload, the page had to invent its own number."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == PUBLISHED_OPTION_CENTS

    def test_the_stale_column_is_still_in_the_payload_and_now_unread(
        self, db, space, plans_checkoutable,
    ):
        """The frontend fix depends on this combination existing: the
        pathway summary still carries 500, and the Collective-level
        field says 400. A page reading the wrong one renders $5."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        summary = next(p for p in resp.pathways if p.id == pathway.id)
        assert summary.price_cents == STALE_LEGACY_CENTS
        assert resp.min_paid_pathway_price_cents == PLAN_TOTAL_CENTS

    def test_a_legacy_collective_is_served_its_own_price(self, db, space):
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == 1800

    def test_nothing_paid_inside_serves_none(self, db, space):
        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents is None


# ---------------------------------------------------------------------------
# Both surfaces, one answer
# ---------------------------------------------------------------------------


class TestTheListingAndTheDetailAgree:
    def test_explore_and_about_quote_the_same_number(
        self, db, space, plans_checkoutable,
    ):
        """They disagreed by design before: the listing used the shared
        derivation, the About page used its own. One helper now — and
        the schedule-aware rewrite moved both at once."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway)

        [card] = hydrate_public_space_cards([space], db)
        detail = get_space(space.slug, db=db, current_user=None)

        assert card.min_paid_pathway_price_cents == PLAN_TOTAL_CENTS
        assert (
            detail.min_paid_pathway_price_cents
            == card.min_paid_pathway_price_cents
        )

    def test_the_listing_is_unchanged_for_a_legacy_collective(
        self, db, space,
    ):
        """The refactor moved the query; it must not have altered it."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        [card] = hydrate_public_space_cards([space], db)

        assert card.min_paid_pathway_price_cents == 1800
        assert card.derived_has_paid_internal_content is True


# ---------------------------------------------------------------------------
# "Has paid content" is the same question as "has a price to show"
# ---------------------------------------------------------------------------


class TestDerivedHasPaidInternalContent:
    """``SpaceResponse.derived_has_paid_internal_content`` used to scan
    the Pathway summaries for ``price_cents > 0`` — the same stale-column
    mistake the About page made, one layer down.

    It mattered more than the price did. The frontend gates the whole
    "Included / Paid separately" block on
    ``has_paid_internal_content || derived_has_paid_internal_content``,
    so a False here hides the section that the corrected price is
    rendered inside. Test Pathway only escaped it because its stale 500
    happens to be non-zero.
    """

    def test_a_schedule_priced_pathway_has_paid_content(
        self, db, space, plans_checkoutable,
    ):
        """The reported shape: NULL legacy column, published $4 plan.
        The old rule said False — no paid content — and hid the block."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == PLAN_TOTAL_CENTS
        assert resp.derived_has_paid_internal_content is True

    def test_the_old_rule_would_have_said_no_here(
        self, db, space, plans_checkoutable,
    ):
        """Stated as the counterfactual, so the regression is legible:
        every Pathway summary in this payload has ``price_cents=None``,
        which is exactly what the old predicate scanned for."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        assert all(p.price_cents is None for p in resp.pathways)
        assert resp.derived_has_paid_internal_content is True

    def test_no_checkoutable_paid_schedule_means_no_paid_content(
        self, db, space, plans_checkoutable,
    ):
        """The inverse. A payment-options Pathway whose Option has only
        a draft schedule sells nothing, so there is nothing to announce
        — and the stale legacy column must not resurrect the claim."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway, schedule_status="draft")

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents is None
        assert resp.derived_has_paid_internal_content is False

    def test_a_stale_price_with_no_published_option_is_not_paid_content(
        self, db, space,
    ):
        """The other direction of the old bug, which mattered less
        loudly but was just as wrong: a Pathway switched to
        payment-options with no Option yet still carried 500, so the old
        rule claimed paid content for something nobody could buy."""
        _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents is None
        assert resp.derived_has_paid_internal_content is False

    def test_a_legacy_paid_pathway_still_has_paid_content(self, db, space):
        """Preserved, now routed through the derived minimum rather than
        a second scan of the same rows."""
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == 1800
        assert resp.derived_has_paid_internal_content is True

    def test_a_free_collective_has_no_paid_content(self, db, space):
        _pathway(
            db, space, pricing_mode="legacy", price_cents=0,
            access_type="free",
        )

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.derived_has_paid_internal_content is False

    def test_a_collective_with_no_pathways_at_all(self, db, space):
        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.derived_has_paid_internal_content is False

    def test_the_flag_tracks_the_price_exactly(
        self, db, space, plans_checkoutable,
    ):
        """The stated semantic, asserted as an equivalence rather than
        case by case, across every shape above."""
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        option = _instalment_plan_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)
        cents = resp.min_paid_pathway_price_cents
        assert resp.derived_has_paid_internal_content == (
            cents is not None and cents > 0
        )

        # Withdraw the only payment method and re-ask. Both must move
        # together — a flag that can disagree with the price is how the
        # section ends up hiding its own contents.
        schedule = (
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.payment_option_id == option.id)
            .one()
        )
        schedule.status = "draft"
        db.flush()

        resp = get_space(space.slug, db=db, current_user=None)
        cents = resp.min_paid_pathway_price_cents
        assert cents is None
        assert resp.derived_has_paid_internal_content == (
            cents is not None and cents > 0
        )

    def test_reading_the_flag_costs_no_query(
        self, db, space, plans_checkoutable,
    ):
        """The field is a property evaluated at serialisation time, so a
        DB read inside it would run per response — and on the detail
        endpoint, after the route had already derived the same number."""
        from sqlalchemy import event

        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)
        resp = get_space(space.slug, db=db, current_user=None)

        n = 0

        def _on_execute(*_args, **_kwargs):
            nonlocal n
            n += 1

        event.listen(db.get_bind(), "before_cursor_execute", _on_execute)
        try:
            # Both the property and a full serialisation, which is what
            # FastAPI actually does to build the response body.
            assert resp.derived_has_paid_internal_content is True
            dumped = resp.model_dump()
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", _on_execute)

        assert dumped["derived_has_paid_internal_content"] is True
        assert n == 0, f"{n} queries issued while serialising the flag"


class TestBothPublicSurfacesAgreeOnPaidContent:
    """``PublicSpaceCard`` already derived the flag from presence in the
    shared price mapping, which is the same rule. These assert the two
    answers match rather than merely resembling each other."""

    def test_they_agree_for_a_schedule_priced_collective(
        self, db, space, plans_checkoutable,
    ):
        pathway = _pathway(
            db, space, pricing_mode="payment_options", price_cents=None,
        )
        _instalment_plan_option(db, space, pathway)

        [card] = hydrate_public_space_cards([space], db)
        detail = get_space(space.slug, db=db, current_user=None)

        assert card.derived_has_paid_internal_content is True
        assert (
            detail.derived_has_paid_internal_content
            == card.derived_has_paid_internal_content
        )

    def test_they_agree_when_nothing_is_buyable(
        self, db, space, plans_checkoutable,
    ):
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _instalment_plan_option(db, space, pathway, schedule_status="draft")

        [card] = hydrate_public_space_cards([space], db)
        detail = get_space(space.slug, db=db, current_user=None)

        assert card.derived_has_paid_internal_content is False
        assert (
            detail.derived_has_paid_internal_content
            == card.derived_has_paid_internal_content
        )

    def test_they_agree_for_a_legacy_collective(self, db, space):
        _pathway(db, space, pricing_mode="legacy", price_cents=1800)

        [card] = hydrate_public_space_cards([space], db)
        detail = get_space(space.slug, db=db, current_user=None)

        assert card.derived_has_paid_internal_content is True
        assert (
            detail.derived_has_paid_internal_content
            == card.derived_has_paid_internal_content
        )


# ---------------------------------------------------------------------------
# Query cost on the busiest public endpoint
# ---------------------------------------------------------------------------


class TestTheListingDoesNotGoQuadratic:
    def test_query_count_is_flat_in_the_number_of_collectives(
        self, db, make_space, plans_checkoutable,
    ):
        """Explore lists every public Collective at once, and the
        headline now needs schedules and grants per Option rather than
        one COALESCE. Those are bulk-loaded; this pins that.

        Asserts a constant, not a small number: the count must not grow
        with the Collectives, which is the failure mode an eager load
        prevents.
        """
        from sqlalchemy import event

        space_ids: list[str] = []
        for n in range(6):
            s = make_space(
                slug=f"cost-{n}-{uuid.uuid4().hex[:8]}",
                status="active", is_public=True, auto_grant_role=None,
            )
            db.flush()
            pathway = _pathway(
                db, s, pricing_mode="payment_options", price_cents=None,
            )
            _instalment_plan_option(db, s, pathway)
            # Ids, not instances: the measurement below expires the
            # session, and touching an expired Space would refresh it
            # and count as one of the queries under test.
            space_ids.append(s.id)

        def _count_for(subset: list[str]) -> int:
            # Cold start. Without this the grants written above are
            # still warm in the identity map, no lazy load fires, and
            # the test would pass with or without the eager load —
            # measuring nothing. Production always reads cold.
            db.expire_all()

            n = 0

            def _on_execute(*_args, **_kwargs):
                nonlocal n
                n += 1

            event.listen(db.get_bind(), "before_cursor_execute", _on_execute)
            try:
                result = pathway_pricing.min_paid_price_cents_by_space(
                    db, subset,
                )
            finally:
                event.remove(
                    db.get_bind(), "before_cursor_execute", _on_execute,
                )
            # The work must actually have happened, or a zero-query
            # "win" would pass this test.
            assert len(result) == len(subset)
            assert set(result.values()) == {PLAN_TOTAL_CENTS}
            return n

        for_two = _count_for(space_ids[:2])
        for_six = _count_for(space_ids)

        assert for_two == for_six, (
            f"query count grew with the Collective count: "
            f"{for_two} for 2, {for_six} for 6 — an eager load is missing"
        )
