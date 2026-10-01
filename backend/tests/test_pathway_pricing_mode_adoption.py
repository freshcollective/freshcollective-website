"""A Pathway sold by a Payment Option must stop being sold by price_cents.

The production report this file reproduces
------------------------------------------
Test Pathway sat at ``pricing_mode='legacy'`` with ``price_cents=500``.
A $2 Payment Option existed, its schedule said ``total_amount_cents=200``,
and a ``PaymentOptionGrant`` correctly linked the two. Member checkout
charged $5 anyway.

Nothing was wrong with the grant. Creating it wrote a
``payment_option_grants`` row and nothing else, and every consumer —
``checkout/routes.py`` and the "from" price in ``spaces/routes.py`` —
reads ``Pathway.pricing_mode``, not the grants. The Option was
configured, displayed, and ignored at the till.

The rule under test
-------------------
**A Pathway is in payment-options pricing as soon as a published Option
grants it.** Applied at the two deliberate acts that can complete that
pair, and nowhere else:

  * linking a Pathway to an Option that is already published
  * publishing an Option that already links a Pathway

Draft Options deliberately do not count — see
``TestDraftOptionsDoNotStrandALivePathway``. Nor do archived ones.
The reverse transition is deliberately absent — see
``TestRemovingOptionsLeavesTheModeExplicit``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_creator_user, None)


@pytest.fixture
def as_creator(client, make_user, make_space):
    """A creator and the Collective they own, authenticated."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    app.dependency_overrides[get_creator_user] = lambda: creator
    yield creator, space


def _legacy_pathway(db, space, *, price_cents: int = 500) -> Pathway:
    """The shape from the report: a paid Pathway on its own price."""
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Test Pathway",
        status="active",
        access_type="one_time",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy",
        price_cents=price_cents,
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, status=PaymentOptionStatus.published, cents=200) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="space",
        attaches_to_id=space.id,
        name="$2 Option",
        payment_type=PaymentOptionType.one_time,
        status=status,
        calculated_total_cents=cents,
        currency="AUD",
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("pos"),
        payment_option_id=opt.id,
        name="Pay in full",
        schedule_type="pay_in_full",
        status="published",
        total_amount_cents=cents,
        currency="AUD",
    )
    db.add(sched)
    db.flush()
    return opt


def _link(client, space, option, pathway):
    return client.post(
        f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}/grants",
        json={"grant_kind": "pathway", "pathway_id": pathway.id},
    )


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------


class TestLinkingAPublishedOptionAdoptsPaymentOptionsPricing:
    def test_the_reported_scenario_no_longer_leaves_the_pathway_on_legacy(
        self, client, as_creator, db,
    ):
        """Pathway at legacy/$5, published $2 Option, grant links them."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space, cents=200)

        r = _link(client, space, option, pathway)

        assert r.status_code == 201, r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

    def test_the_grant_itself_is_still_written(self, client, as_creator, db):
        """The fix adds a write; it must not replace the original one."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        option = _option(db, space)

        _link(client, space, option, pathway)

        grants = (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.pathway_id == pathway.id)
            .all()
        )
        assert len(grants) == 1
        assert grants[0].payment_option_id == option.id

    def test_price_cents_is_left_alone(self, client, as_creator, db):
        """Only the mode changes. The old price stays on the row so a
        creator who reverts gets back what they had."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space)

        _link(client, space, option, pathway)

        db.refresh(pathway)
        assert pathway.price_cents == 500

    def test_a_second_grant_is_harmless(self, client, as_creator, db):
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        first = _option(db, space)
        second = _option(db, space)

        assert _link(client, space, first, pathway).status_code == 201
        assert _link(client, space, second, pathway).status_code == 201

        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"


class TestCheckoutNoLongerFallsBackToTheLegacyPrice:
    def test_option_less_checkout_is_refused_instead_of_charging_price_cents(
        self, client, as_creator, db, make_user,
    ):
        """The point of the whole fix. Before it, this request built a
        Stripe session for $5. Now the pathway is in payment-options
        mode, so ``checkout/routes.py`` refuses and asks for a choice."""
        from app.auth.dependencies import get_verified_current_user

        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space, cents=200)
        _link(client, space, option, pathway)
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

        member = make_user(role="user")
        app.dependency_overrides[get_verified_current_user] = lambda: member
        try:
            r = client.post(
                "/api/checkout/pathway",
                json={
                    "pathway_id": pathway.id,
                    "success_url": "https://example.com/ok",
                    "cancel_url": "https://example.com/no",
                },
            )
        finally:
            app.dependency_overrides.pop(get_verified_current_user, None)

        assert r.status_code == 400, r.text
        assert "payment option" in r.text.lower()

    def test_the_member_pathway_read_reports_payment_options_mode(
        self, client, as_creator, db, make_user,
    ):
        """The rendered surface, not just the till. The overview
        response carries ``pricing_mode`` straight from the column, so
        this is what decides whether the member UI offers Options or a
        single legacy price."""
        from app.auth.dependencies import get_current_user

        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space, cents=200)
        _link(client, space, option, pathway)

        member = make_user(role="user")
        app.dependency_overrides[get_current_user] = lambda: member
        try:
            r = client.get(
                f"/api/spaces/{space.slug}/pathways/{pathway.slug}/overview"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert r.status_code == 200, r.text
        assert r.json()["pricing_mode"] == "payment_options"

    def test_the_checkout_fallback_itself_is_unchanged_for_legacy_pathways(
        self, client, as_creator, db,
    ):
        """A Pathway nobody linked an Option to keeps its legacy price
        and its legacy path. The fix must not widen to these."""
        _creator, space = as_creator
        untouched = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space)
        other = _legacy_pathway(db, space, price_cents=900)

        _link(client, space, option, other)

        db.refresh(untouched)
        assert untouched.pricing_mode == "legacy"
        assert untouched.price_cents == 500


# ---------------------------------------------------------------------------
# What must NOT flip
# ---------------------------------------------------------------------------


class TestDraftOptionsDoNotStrandALivePathway:
    def test_linking_a_draft_option_leaves_the_pathway_selling(
        self, client, as_creator, db,
    ):
        """Grants are added while an Option is still a draft — that is
        the authoring order the editor encourages. Flipping here would
        take a live Pathway off sale for as long as the creator takes
        to finish building the Option: the mode would say "choose an
        Option" while none is published to choose."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space, status=PaymentOptionStatus.draft)

        assert _link(client, space, option, pathway).status_code == 201

        db.refresh(pathway)
        assert pathway.pricing_mode == "legacy"

    def test_publishing_that_draft_completes_the_switch(
        self, client, as_creator, db,
    ):
        """The other half of the rule: whichever act completes the pair
        of "published Option" and "grants this Pathway" does the flip."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        option = _option(db, space, status=PaymentOptionStatus.draft)
        _link(client, space, option, pathway)
        db.refresh(pathway)
        assert pathway.pricing_mode == "legacy"

        r = client.patch(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}",
            json={"status": "published"},
        )

        assert r.status_code == 200, r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

    def test_an_unrelated_patch_changes_nothing(self, client, as_creator, db):
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        option = _option(db, space, status=PaymentOptionStatus.draft)
        _link(client, space, option, pathway)

        r = client.patch(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}",
            json={"name": "Renamed while still a draft"},
        )

        assert r.status_code == 200, r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "legacy"


class TestArchivedOptionsAreNotEvidence:
    def test_a_historical_grant_from_an_archived_option_moves_nothing(
        self, client, as_creator, db,
    ):
        """"Some Option once granted this" is not the rule. Only a
        published one is."""
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        option = _option(db, space, status=PaymentOptionStatus.archived)

        _link(client, space, option, pathway)

        db.refresh(pathway)
        assert pathway.pricing_mode == "legacy"


class TestOtherGrantKindsAreNotPathways:
    def test_a_series_grant_does_not_touch_any_pathway_pricing(
        self, client, as_creator, db, make_user,
    ):
        from datetime import datetime, timedelta

        from app.models.platform import EventSeries

        _creator, space = as_creator
        pathway = _legacy_pathway(db, space, price_cents=500)
        starts = datetime.utcnow() + timedelta(days=7)
        series = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="Term 4",
            starts_at=starts, ends_at=starts + timedelta(days=60),
            status="published",
        )
        db.add(series)
        db.flush()
        option = _option(db, space)

        r = client.post(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}/grants",
            json={"grant_kind": "event_series", "series_id": series.id},
        )

        assert r.status_code == 201, r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "legacy"


# ---------------------------------------------------------------------------
# The documented non-behaviour
# ---------------------------------------------------------------------------


class TestRemovingOptionsLeavesTheModeExplicit:
    """Removing the last Option does NOT revert the Pathway to legacy.

    The intended rule, written down so a future reader knows this is a
    decision and not an oversight: **pricing mode is a deliberate
    setting, and only a deliberate act changes it back.** Auto-reverting
    would silently revive a stale ``price_cents`` the creator stopped
    intending to charge — reviving a price is worse than showing none.
    The creator reverts explicitly from Pathway settings, where choosing
    any Access option already writes ``pricing_mode='legacy'``.
    """

    def test_deleting_the_last_grant_leaves_payment_options_mode(
        self, client, as_creator, db,
    ):
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        option = _option(db, space)
        created = _link(client, space, option, pathway).json()
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

        r = client.delete(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/"
            f"{option.id}/grants/{created['id']}"
        )

        assert r.status_code in (200, 204), r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

    def test_archiving_the_last_option_leaves_payment_options_mode(
        self, client, as_creator, db,
    ):
        _creator, space = as_creator
        pathway = _legacy_pathway(db, space)
        option = _option(db, space)
        _link(client, space, option, pathway)
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"

        r = client.patch(
            f"/api/creator/spaces/{space.slug}/commerce/payment-options/{option.id}",
            json={"status": "archived"},
        )

        assert r.status_code == 200, r.text
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"
