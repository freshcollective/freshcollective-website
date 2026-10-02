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

What this file covers
---------------------
* ``min_paid_price_cents_by_space`` — the rule itself, per pricing_mode.
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


def _published_option(
    db, space, pathway, *,
    cents: int = PUBLISHED_OPTION_CENTS,
    status: PaymentOptionStatus = PaymentOptionStatus.published,
) -> PaymentOption:
    """An Option granting ``pathway``, priced at ``cents``."""
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name=f"${cents // 100} Option",
        payment_type=PaymentOptionType.one_time,
        status=status,
        calculated_total_cents=cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    db.add(PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=opt.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=cents,
        currency="AUD",
    ))
    db.add(PaymentOptionGrant(
        id=_uid("pog"),
        payment_option_id=opt.id,
        grant_kind="pathway",
        pathway_id=pathway.id,
    ))
    db.flush()
    return opt


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
# The endpoint the About page actually reads
# ---------------------------------------------------------------------------


class TestTheDetailEndpointCarriesThePrice:
    def test_the_field_is_served_at_all(self, db, space):
        """The gap behind the bug: with nothing authoritative in the
        payload, the page had to invent its own number."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        assert resp.min_paid_pathway_price_cents == PUBLISHED_OPTION_CENTS

    def test_the_stale_column_is_still_in_the_payload_and_now_unread(
        self, db, space,
    ):
        """The frontend fix depends on this combination existing: the
        pathway summary still carries 500, and the Collective-level
        field says 200. A page reading the wrong one renders $5."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(db, space, pathway)

        resp = get_space(space.slug, db=db, current_user=None)

        summary = next(p for p in resp.pathways if p.id == pathway.id)
        assert summary.price_cents == STALE_LEGACY_CENTS
        assert resp.min_paid_pathway_price_cents == PUBLISHED_OPTION_CENTS

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
    def test_explore_and_about_quote_the_same_number(self, db, space):
        """They disagreed by design before: the listing used the shared
        derivation, the About page used its own. One helper now."""
        pathway = _pathway(
            db, space,
            pricing_mode="payment_options",
            price_cents=STALE_LEGACY_CENTS,
        )
        _published_option(db, space, pathway)

        [card] = hydrate_public_space_cards([space], db)
        detail = get_space(space.slug, db=db, current_user=None)

        assert card.min_paid_pathway_price_cents == PUBLISHED_OPTION_CENTS
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
