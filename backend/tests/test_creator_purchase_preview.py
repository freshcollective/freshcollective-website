"""Stage 1B.1 — what the creator preview tells a creator.

The preview is the first consumer of the Stage 1A resolver, and the
first place the resolver's answer meets a question it deliberately does
not answer: *would checkout actually accept this today?*

Two live gates make those answers differ, and both are genuine:

* a Pathway on ``pricing_mode='payment_options'`` keeps a real
  ``price_cents``, and the resolver reports that direct arrangement —
  but ``POST /api/checkout/pathway`` refuses the option-less door for
  exactly that mode;
* a standalone Gathering ticket is configured correctly and
  ``ensure_sales_enabled_or_raise`` still refuses it while the two-key
  guard is unsatisfied.

What this file pins, therefore, is mostly *honesty*: the preview must
never call an arrangement purchasable that the till would refuse, must
never call a creator's finished configuration unfinished, and must keep
those two states distinguishable — because "you haven't set this up"
and "we aren't selling this yet" need different advice.

It also pins the two things that keep a read-only surface read-only:
the response carries no arrangement identifier (so nothing a member
could act on round-trips through it), and the endpoint is creator-only
and Collective-scoped.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

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
from app.models.platform import Pathway, PathwayType, SpaceMembership
from app.services.creator_purchase_preview import (
    REASON_GATHERING_SALES_DISABLED,
    REASON_PATHWAY_REQUIRES_OPTION,
)
from app.services.purchase_arrangements import (
    REASON_OPTION_ARCHIVED,
    REASON_OPTION_DRAFT,
    REASON_PRICE_NOT_SET,
    REASON_SCHEDULE_DRAFT,
    REASON_UNSUPPORTED_INCLUSION,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Rows. Local and minimal on purpose — the resolver's own suite owns the
# exhaustive shapes; these build only what a preview has to render.
# ---------------------------------------------------------------------------


def _pathway(
    db, space, *, price_cents=None, access_type="one_time",
    pricing_mode="legacy", status="active", title="Personal Leadership",
) -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status=status, access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode=pricing_mode, price_cents=price_cents, currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, name="Personal Leadership Bundle",
            status=PaymentOptionStatus.published, position=0) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time, status=status,
        currency="AUD", position=position,
    )
    db.add(opt)
    db.flush()
    return opt


def _pay_in_full(db, option, *, cents, status="published",
                 name="Pay in full", position=0) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency="AUD", position=position,
    )
    db.add(s)
    db.flush()
    return s


def _instalments(db, option, *, each, count, interval="week",
                 total=None, status="published", name="Payment plan",
                 position=1) -> PaymentOptionSchedule:
    """A finite instalment schedule that genuinely validates.

    ``stripe_interval`` / ``stripe_interval_count`` are required by
    ``validate_recurring_installments_row`` — without them the row is
    ``schedule_invalid`` and every availability assertion about it
    passes for the wrong reason. An earlier version of this helper
    omitted them, which made the Stage 1B.1 instalment tests weaker
    than they looked: they asserted the figures, which were right, and
    never noticed the schedule was unsellable.
    """
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval, stripe_interval_count=1,
        total_amount_cents=total if total is not None else each * count,
        currency="AUD", position=position,
    )
    db.add(s)
    db.flush()
    return s


def _grant(db, option, kind, target_id, **kw) -> PaymentOptionGrant:
    cols = {
        "pathway": "pathway_id", "event_series": "series_id",
        "gathering": "event_id", "offering": "offering_id",
    }
    g = PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=option.id, grant_kind=kind,
        **{cols[kind]: target_id}, **kw,
    )
    db.add(g)
    db.flush()
    return g


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_as(db):
    """TestClient authenticated as the given creator, pinned to the
    SAVEPOINT-scoped session."""
    def _install(user):
        app.dependency_overrides[get_creator_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app, follow_redirects=False)

    yield _install
    app.dependency_overrides.pop(get_creator_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def plan_guard_off():
    """Pin the creator-plan guard OFF for this module by default.

    Every test here builds a creator with no ``CreatorSubscription``,
    so with the guard on the plan gate would be the operative reason
    for every paid arrangement and would mask the configuration
    reasons these tests are about. Production runs the guard **on** —
    ``TestCreatorPlanEligibility`` below pins it on and builds real
    plan rows, so that dimension is covered deliberately rather than
    inherited from whatever the local ``.env`` happens to say.
    """
    with patch(
        "app.core.config.settings.creator_plan_guard_enabled", False,
    ):
        yield


@pytest.fixture
def plans_on():
    """The finite-plan member-checkout flag, on — otherwise every
    instalment schedule reports ``instalments_not_enabled`` and the
    instalment assertions would pass for the wrong reason."""
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


@pytest.fixture
def tickets_on():
    """Sales on, in Stripe test mode. ``stripe_mode`` is derived from
    the key prefix rather than set, so the key is what we patch."""
    with patch(
        "app.core.config.settings.standalone_gathering_sales_enabled", True,
    ), patch("app.core.config.settings.stripe_secret_key", "sk_test_x"):
        yield


@pytest.fixture
def tickets_off():
    with patch(
        "app.core.config.settings.standalone_gathering_sales_enabled", False,
    ):
        yield


def _get(client, space, kind, experience_id):
    return client.get(
        f"/api/creator/spaces/{space.slug}/purchase-preview/{kind}/{experience_id}"
    )


# ---------------------------------------------------------------------------
# 1. Security — who may ask
# ---------------------------------------------------------------------------


class TestWhoMayAsk:
    def test_the_route_is_creator_only(self):
        """Asserted on the dependency rather than by calling without
        credentials: the fixtures override the dependency, so a
        behavioural 401 here would prove only that the override was
        absent. The ladder in ``auth/dependencies`` is what makes this
        creator-only, and this is the assertion that it is still wired
        to it."""
        route = next(
            r for r in app.routes
            if getattr(r, "path", "") ==
            "/api/creator/spaces/{slug}/purchase-preview/{kind}/{experience_id}"
        )
        names = [d.call.__name__ for d in route.dependant.dependencies]
        assert "get_creator_user" in names, names

    def test_a_creator_sees_their_own_collective(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)

        r = _get(client_as(creator), space, "pathway", pathway.id)
        assert r.status_code == 200, r.text
        assert r.json()["experience_id"] == pathway.id

    def test_an_authorised_caretaker_sees_it(
        self, client_as, make_user, make_space, db,
    ):
        """``_get_managed_space`` admits an active creator/moderator
        membership, and the preview inherits that rather than inventing
        a narrower rule of its own."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        helper = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=helper.id,
            role="moderator", status="active",
        ))
        db.flush()
        pathway = _pathway(db, space, price_cents=4900)

        r = _get(client_as(helper), space, "pathway", pathway.id)
        assert r.status_code == 200, r.text

    def test_someone_with_no_role_in_the_collective_is_refused(
        self, client_as, make_user, make_space, db,
    ):
        """A member — or any creator who does not manage this
        Collective — is refused by the same guard every other creator
        route uses."""
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        outsider = make_user(role="user")
        pathway = _pathway(db, space, price_cents=4900)

        r = _get(client_as(outsider), space, "pathway", pathway.id)
        assert r.status_code == 403, r.text

    def test_another_collectives_experience_is_not_found(
        self, client_as, make_user, make_space, db,
    ):
        """The isolation test that matters: a real id, a real Option
        behind it, and a creator who legitimately manages *a*
        Collective — just not that one. 404 rather than 403 so the
        endpoint cannot be used to discover which ids exist."""
        mine = make_user(role="creator")
        my_space = make_space(creator=mine)
        theirs = make_user(role="creator")
        their_space = make_space(creator=theirs)
        their_pathway = _pathway(db, their_space, price_cents=9900)
        opt = _option(db, their_space, name="Their private bundle")
        _grant(db, opt, "pathway", their_pathway.id)
        _pay_in_full(db, opt, cents=9900)

        r = _get(client_as(mine), my_space, "pathway", their_pathway.id)
        assert r.status_code == 404, r.text
        assert "Their private bundle" not in r.text

    def test_an_unknown_id_is_a_clean_404(
        self, client_as, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        r = _get(client_as(creator), space, "pathway", "pw_does_not_exist")
        assert r.status_code == 404, r.text

    def test_an_unserved_kind_is_a_clean_404(
        self, client_as, make_user, make_space, db,
    ):
        """Series and Offerings are deliberately not served here —
        their own editors already present their Options clearly. The
        refusal must be a tidy 404, not a 500 from a missing model."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        for kind in ("event_series", "offering", "nonsense", "../etc"):
            r = _get(client_as(creator), space, kind, "whatever")
            assert r.status_code == 404, f"{kind}: {r.text}"


# ---------------------------------------------------------------------------
# 2. Pathways
# ---------------------------------------------------------------------------


class TestPathwayPreview:
    def test_a_direct_price_is_shown_as_an_individual_purchase(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        assert len(body["arrangements"]) == 1
        a = body["arrangements"][0]
        assert a["source"] == "direct"
        assert a["total_amount_cents"] == 4900
        assert a["currency"] == "AUD"
        assert a["schedule_type"] == "direct"
        assert a["available_for_new_purchase"] is True
        assert a["unavailable_reason"] is None
        assert a["is_bundle"] is False
        assert body["has_purchasable_arrangement"] is True

    def test_a_bundle_shows_each_schedule_with_its_own_price(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        """The requirement the whole stage rests on: $99 in full and
        3 x $33 are two arrangements, not one price with a note."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)
        opt = _option(db, space, name="Personal Leadership Bundle")
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)
        _instalments(db, opt, each=3300, count=3, total=9900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        rows = body["arrangements"]
        assert len(rows) == 3

        direct, full, plan = rows
        assert (direct["source"], direct["total_amount_cents"]) == ("direct", 4900)

        assert full["source"] == "payment_option"
        assert full["name"] == "Personal Leadership Bundle"
        assert full["schedule_type"] == "pay_in_full"
        assert full["total_amount_cents"] == 9900
        assert full["payment_option_id"] == opt.id

        assert plan["schedule_type"] == "recurring_installments"
        assert plan["installment_amount_cents"] == 3300
        assert plan["installment_count"] == 3
        assert plan["interval"] == "week"
        assert plan["total_amount_cents"] == 9900
        # What leaves the account first, which is not the total.
        assert plan["upfront_amount_cents"] == 3300
        # And it is genuinely sellable — asserted because the helper
        # once produced schedules that validated as invalid, which made
        # the figures above right and the arrangement unusable.
        assert full["available_for_new_purchase"] is True
        assert plan["available_for_new_purchase"] is True

    def test_a_bundle_says_what_else_it_includes(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900, title="Foundations")
        other = _pathway(db, space, price_cents=4900, title="Deepening")
        opt = _option(db, space, name="Both Pathways")
        _grant(db, opt, "pathway", pathway.id)
        _grant(db, opt, "pathway", other.id)
        _pay_in_full(db, opt, cents=8900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        bundle = next(a for a in body["arrangements"] if a["source"] == "payment_option")
        assert bundle["is_bundle"] is True
        titles = sorted(i["title"] for i in bundle["included"])
        assert titles == ["Deepening", "Foundations"]

    def test_a_draft_option_is_draft_not_available(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = next(a for a in body["arrangements"] if a["source"] == "payment_option")
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == REASON_OPTION_DRAFT
        # Not the platform's doing — the creator can publish it.
        assert a["blocked_by_platform"] is False
        assert a["configured_available"] is False
        assert body["has_purchasable_arrangement"] is False

    def test_a_draft_schedule_is_reported_against_the_schedule(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900, status="draft")

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = next(a for a in body["arrangements"] if a["source"] == "payment_option")
        assert a["unavailable_reason"] == REASON_SCHEDULE_DRAFT

    def test_an_archived_option_is_not_on_sale_but_is_still_a_source(
        self, client_as, make_user, make_space, db,
    ):
        """Archived Options keep historical purchasers' access —
        ``unlock_option_ids_for_pathway`` accepts ``archived`` for
        exactly that reason. The preview has to say both things: not
        sellable, still the origin of somebody's access."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = next(a for a in body["arrangements"] if a["source"] == "payment_option")
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == REASON_OPTION_ARCHIVED
        assert a["is_historical_source"] is True

    def test_a_price_the_creator_never_set_is_shown_as_unset(
        self, client_as, make_user, make_space, db,
    ):
        """Absent from the list would read as "nothing to do here".
        Present and unavailable is the truth, and actionable."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=None)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["unavailable_reason"] == REASON_PRICE_NOT_SET
        assert a["total_amount_cents"] is None
        assert a["blocked_by_platform"] is False

    def test_a_free_pathway_offers_nothing_to_buy(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="free", price_cents=None)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        assert body["arrangements"] == []
        assert body["access_type"] == "free"
        assert body["has_purchasable_arrangement"] is False

    def test_a_members_only_pathway_says_so(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included", price_cents=None)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        assert body["arrangements"] == []
        assert body["access_type"] == "included"

    def test_a_legacy_subscription_pathway_offers_no_arrangement(self, client_as, make_user, make_space, db):
        """Nothing sells a per-Pathway subscription — the checkout door
        accepts only ``one_time`` — so the resolver emits no
        arrangement for one. Pinned here because the creator copy for
        this state depends on the list being empty rather than
        containing something unavailable."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(
            db, space, access_type="subscription", price_cents=2000,
        )

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        assert body["arrangements"] == []
        assert body["access_type"] == "subscription"
        assert body["has_purchasable_arrangement"] is False

    def test_a_draft_pathway_is_not_purchasable(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900, status="draft")

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == "experience_unavailable"


# ---------------------------------------------------------------------------
# 3. The pricing_mode overlay — configured, yet refused
# ---------------------------------------------------------------------------


class TestTheLegacyPricingModeRestriction:
    """``pricing_mode='payment_options'`` closes the option-less
    checkout door with a 400. The resolver does not know that — on
    purpose — so the preview must, or it would advertise a price
    checkout refuses.

    This is the one place Stage 1B.1 reads ``pricing_mode``, and it
    reads it only to report the restriction.
    """

    def test_the_direct_price_is_configured_but_not_purchasable(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(
            db, space, price_cents=4900, pricing_mode="payment_options",
        )

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["source"] == "direct"
        # The price is still shown — the creator entered it and it is
        # still on the row.
        assert a["total_amount_cents"] == 4900
        # But not as something a member can complete.
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == REASON_PATHWAY_REQUIRES_OPTION
        # And distinguishably so: the configuration is complete.
        assert a["configured_available"] is True
        assert a["blocked_by_platform"] is True

    def test_the_option_beside_it_is_unaffected(
        self, client_as, make_user, make_space, db,
    ):
        """The Option branch of ``POST /api/checkout/pathway`` returns
        before ``pricing_mode`` is read, so an Option purchase is
        unaffected by the mode. The overlay must not spill onto it."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(
            db, space, price_cents=500, pricing_mode="payment_options",
        )
        opt = _option(db, space, name="The $2 Option")
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=200)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        direct, option = body["arrangements"]
        assert direct["available_for_new_purchase"] is False
        assert option["available_for_new_purchase"] is True
        assert option["total_amount_cents"] == 200
        assert option["blocked_by_platform"] is False
        # The incident's two prices, still distinct, still each their own.
        assert direct["total_amount_cents"] == 500
        assert body["has_purchasable_arrangement"] is True

    def test_legacy_mode_leaves_the_direct_price_purchasable(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900, pricing_mode="legacy")

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is True
        assert a["blocked_by_platform"] is False

    def test_the_preview_does_not_change_the_mode(
        self, client_as, make_user, make_space, db,
    ):
        """Reading must not write. The one-way switch stays where it
        was pointed."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(
            db, space, price_cents=4900, pricing_mode="payment_options",
        )
        _get(client_as(creator), space, "pathway", pathway.id)
        db.refresh(pathway)
        assert pathway.pricing_mode == "payment_options"
        assert pathway.price_cents == 4900


# ---------------------------------------------------------------------------
# 4. Standalone Gatherings
# ---------------------------------------------------------------------------


class TestGatheringPreview:
    def test_a_ticket_price_is_shown_as_an_individual_ticket(
        self, client_as, make_user, make_space, make_event, tickets_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=2000)

        body = _get(client_as(creator), space, "gathering", event.id).json()
        a = body["arrangements"][0]
        assert a["source"] == "direct"
        assert a["total_amount_cents"] == 2000
        assert a["currency"] == "AUD"
        assert a["available_for_new_purchase"] is True
        assert body["access_type"] == "paid_separately"

    def test_ticket_sales_switched_off_is_not_the_creators_mistake(
        self, client_as, make_user, make_space, make_event, tickets_off,
    ):
        """The $3,000 retreat case. The price is right, the Gathering is
        right, and the environment is not selling tickets — which the
        creator can do nothing about, so it must not be worded as a
        configuration error."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=300000)

        body = _get(client_as(creator), space, "gathering", event.id).json()
        a = body["arrangements"][0]
        assert a["total_amount_cents"] == 300000
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == REASON_GATHERING_SALES_DISABLED
        assert a["configured_available"] is True
        assert a["blocked_by_platform"] is True

    def test_the_two_key_live_guard_is_honoured_not_half_read(
        self, client_as, make_user, make_space, make_event,
    ):
        """``ensure_sales_enabled_or_raise`` is two-key: the flag alone
        is not enough in Stripe live mode. A preview that read only the
        first key would promise a sale the second key refuses."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=2000)

        with patch(
            "app.core.config.settings.standalone_gathering_sales_enabled", True,
        ), patch(
            "app.core.config.settings.stripe_secret_key", "sk_live_pretend",
        ), patch(
            "app.core.config.settings.standalone_gathering_live_confirmed", False,
        ):
            body = _get(client_as(creator), space, "gathering", event.id).json()

        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == REASON_GATHERING_SALES_DISABLED

    def test_an_option_including_a_gathering_is_not_purchasable(
        self, client_as, make_user, make_space, make_event, db,
        plans_on, tickets_on,
    ):
        """Stage 0's rule, surfaced. The retreat instalment plan is
        identifiable and must not look available — this is the explicit
        "do not make it look available just because the resolver can
        see it" requirement."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=300000)
        opt = _option(db, space, name="Retreat Instalment Plan")
        _grant(db, opt, "gathering", event.id)
        _instalments(db, opt, each=100000, count=3, total=300000)

        body = _get(client_as(creator), space, "gathering", event.id).json()
        plan = next(a for a in body["arrangements"] if a["source"] == "payment_option")
        assert plan["name"] == "Retreat Instalment Plan"
        assert plan["installment_amount_cents"] == 100000
        assert plan["installment_count"] == 3
        assert plan["available_for_new_purchase"] is False
        assert plan["unavailable_reason"] == REASON_UNSUPPORTED_INCLUSION
        # Not a platform overlay — the resolver already refused it, and
        # the reason the creator needs is the inclusion one.
        assert plan["blocked_by_platform"] is False

    def test_a_free_gathering_offers_nothing_to_buy(
        self, client_as, make_user, make_space, make_event, tickets_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(
            space=space, booking_access_type="included_with_collective",
            ticket_price_cents=None, ticket_currency=None,
        )

        body = _get(client_as(creator), space, "gathering", event.id).json()
        assert body["arrangements"] == []
        assert body["access_type"] == "included_with_collective"

    def test_a_legacy_access_value_is_reported_in_current_vocabulary(
        self, client_as, make_user, make_space, make_event, tickets_on,
    ):
        """Old rows hold ``all_members``. The client has copy for the
        current vocabulary only, so the preview normalises rather than
        handing over a value nothing can word."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(
            space=space, booking_access_type="all_members",
            ticket_price_cents=None, ticket_currency=None,
        )
        body = _get(client_as(creator), space, "gathering", event.id).json()
        assert body["access_type"] == "included_with_collective"

    def test_recurring_occurrences_are_previewed_one_at_a_time(
        self, client_as, make_user, make_space, make_event, tickets_on,
    ):
        """Independently recurring Gatherings are separate Event rows
        with their own prices and bookings. The preview answers for the
        row it was asked about and never aggregates a schedule — and
        ``recurrence_series_id`` is not ``series_id``."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        tag = _uid("rec")
        first = make_event(
            space=space, ticket_price_cents=2000,
            recurrence_series_id=tag, recurrence_index=1, recurrence_total=3,
        )
        second = make_event(
            space=space, ticket_price_cents=2500,
            recurrence_series_id=tag, recurrence_index=2, recurrence_total=3,
        )
        client = client_as(creator)

        a = _get(client, space, "gathering", first.id).json()
        b = _get(client, space, "gathering", second.id).json()

        assert len(a["arrangements"]) == 1
        assert len(b["arrangements"]) == 1
        assert a["arrangements"][0]["total_amount_cents"] == 2000
        assert b["arrangements"][0]["total_amount_cents"] == 2500
        assert a["experience_id"] != b["experience_id"]


# ---------------------------------------------------------------------------
# 5. A read-only surface stays read-only
# ---------------------------------------------------------------------------


class TestItIsOnlyAPreview:
    def test_no_arrangement_identifier_is_returned(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        """Stage 1B.1 is not a checkout path. The resolver's
        ``arrangement_id`` is what a purchase would name, so the
        preview does not carry one — there is nothing in this response
        a client could hand to a checkout endpoint.

        Also keeps internal ids out of a creator-facing payload, except
        the Option id the preview needs in order to link to its
        editor.
        """
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)
        sched = _instalments(db, opt, each=3300, count=3)

        r = _get(client_as(creator), space, "pathway", pathway.id)
        body = r.json()
        for a in body["arrangements"]:
            assert "arrangement_id" not in a
            assert "payment_option_schedule_id" not in a
        # Nor anywhere in the serialised response.
        assert "direct:pathway:" not in r.text
        assert sched.id not in r.text

    def test_the_preview_writes_nothing(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        """Asserted by reading the rows back rather than by trusting
        the service: the endpoint touches Pathway, Option, grant and
        schedule rows, and a preview that quietly normalised one of
        them would be a write dressed as a read."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)
        opt = _option(db, space, status=PaymentOptionStatus.published)
        _grant(db, opt, "pathway", pathway.id)
        full = _pay_in_full(db, opt, cents=9900)
        plan = _instalments(db, opt, each=3300, count=3)

        before = (
            pathway.price_cents, pathway.pricing_mode, pathway.access_type,
            opt.status, opt.currency,
            full.total_amount_cents, full.status,
            plan.installment_amount_cents, plan.installment_count, plan.status,
        )
        _get(client_as(creator), space, "pathway", pathway.id)
        for row in (pathway, opt, full, plan):
            db.refresh(row)
        after = (
            pathway.price_cents, pathway.pricing_mode, pathway.access_type,
            opt.status, opt.currency,
            full.total_amount_cents, full.status,
            plan.installment_amount_cents, plan.installment_count, plan.status,
        )
        assert before == after

    def test_every_reason_the_api_can_emit_is_a_known_constant(self):
        """The frontend maps reasons to copy. A reason with no copy
        would render as a raw code to a creator, so the set has to be
        closed and named in one place."""
        from app.services import creator_purchase_preview as preview
        from app.services import purchase_arrangements as resolver

        resolver_reasons = {
            getattr(resolver, n) for n in dir(resolver)
            if n.startswith("REASON_")
        }
        platform_reasons = set(preview.PLATFORM_REASONS)
        assert platform_reasons.isdisjoint(resolver_reasons), (
            "a platform reason is shadowing a resolver reason"
        )
        assert len(resolver_reasons | platform_reasons) == 14


# ---------------------------------------------------------------------------
# 6. Creator-plan eligibility — the Stage 1B.1 gap
# ---------------------------------------------------------------------------


class TestCreatorPlanEligibility:
    """The preview must refuse what checkout refuses.

    Stage 1B.1's overlay asked only whether Gathering ticket sales were
    switched on. It never asked whether the Collective had a Creator
    Plan — so a Collective with none showed its $45 ticket as
    **Available** while the ticket endpoint refused the sale. The same
    gap applied to a Pathway price and to every Payment Option
    arrangement, since ``orchestrate_paid_checkout`` and
    ``start_finite_plan_setup`` enforce the gate as well.

    These tests pin the guard **on**, which is how production runs.
    """

    @pytest.fixture
    def guard_on(self):
        with patch(
            "app.core.config.settings.creator_plan_guard_enabled", True,
        ):
            yield

    @staticmethod
    def _plan(db, slug: str, fee_bps: int = 800):
        from app.models.creator_billing import CreatorPlan

        row = CreatorPlan(
            id=_uid("cp"), slug=slug, name=slug.replace("-", " ").title(),
            monthly_price_cents=1900, currency="AUD",
            transaction_fee_basis_points=fee_bps,
            is_active=True, collective_limit=1,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def _subscribe(db, creator, plan):
        from datetime import datetime, timedelta

        from app.models.creator_billing import (
            CreatorSubscription,
            CreatorSubscriptionStatus,
        )

        sub = CreatorSubscription(
            id=_uid("cs"), user_id=creator.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow() - timedelta(days=1),
            source="stripe_paid",
        )
        db.add(sub)
        db.flush()
        return sub

    def test_no_plan_is_not_available(
        self, client_as, make_user, make_space, db, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=4900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == "creator_plan_not_configured"
        # Configuration is complete; the platform is the blocker.
        assert a["configured_available"] is True
        assert a["blocked_by_platform"] is True
        assert body["has_purchasable_arrangement"] is False

    def test_a_community_plan_is_not_available(
        self, client_as, make_user, make_space, db, guard_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        self._subscribe(db, creator, self._plan(db, "community", 0))
        pathway = _pathway(db, space, price_cents=4900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is False
        assert a["unavailable_reason"] == "creator_plan_forbids_paid_offers"
        assert a["blocked_by_platform"] is True

    @pytest.mark.parametrize("slug", ["creator", "pro", "founding-creator"])
    def test_a_paid_plan_stays_available(
        self, client_as, make_user, make_space, db, guard_on, slug,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        self._subscribe(db, creator, self._plan(db, slug))
        pathway = _pathway(db, space, price_cents=4900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["available_for_new_purchase"] is True, f"{slug}: {a}"
        assert a["unavailable_reason"] is None

    def test_a_gathering_ticket_follows_the_same_rule(
        self, client_as, make_user, make_space, make_event, db,
        guard_on, tickets_on,
    ):
        """Kelly's shape: sales flags on, ticket priced, and the plan
        is the only question left."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        client = client_as(creator)

        unplanned = _get(client, space, "gathering", event.id).json()
        assert unplanned["arrangements"][0]["unavailable_reason"] == (
            "creator_plan_not_configured"
        )

        self._subscribe(db, creator, self._plan(db, "creator"))
        planned = _get(client, space, "gathering", event.id).json()
        a = planned["arrangements"][0]
        assert a["available_for_new_purchase"] is True, a
        assert a["total_amount_cents"] == 4500

    def test_the_sales_flags_still_win_for_a_gathering(
        self, client_as, make_user, make_space, make_event, db,
        guard_on, tickets_off,
    ):
        """Checkout's order, mirrored: ``ensure_sales_enabled_or_raise``
        is the first line of the ticket endpoint, so a switched-off
        environment is the reason a member would be given even when the
        plan is also missing."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)

        body = _get(client_as(creator), space, "gathering", event.id).json()
        assert body["arrangements"][0]["unavailable_reason"] == (
            REASON_GATHERING_SALES_DISABLED
        )

    def test_an_option_arrangement_is_gated_too(
        self, client_as, make_user, make_space, db, guard_on, plans_on,
    ):
        """``orchestrate_paid_checkout`` and ``start_finite_plan_setup``
        both enforce the gate, so a bundle is no more purchasable than a
        direct price when the Collective has no plan."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)
        _instalments(db, opt, each=3300, count=3)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        assert len(body["arrangements"]) == 2
        for a in body["arrangements"]:
            assert a["available_for_new_purchase"] is False, a
            assert a["unavailable_reason"] == "creator_plan_not_configured"
            assert a["blocked_by_platform"] is True

    def test_a_free_pathway_is_never_plan_gated(
        self, client_as, make_user, make_space, db, guard_on,
    ):
        """Checkout's free path resolves its fee context through
        ``try_resolve_fee_context`` precisely so a Collective with no
        plan can still give things away. A zero-priced arrangement must
        not be reported as blocked."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, price_cents=0)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        if body["arrangements"]:
            a = body["arrangements"][0]
            assert a["unavailable_reason"] != "creator_plan_not_configured"

    def test_the_preview_and_the_till_agree_about_the_plan(
        self, client_as, make_user, make_space, make_event, db,
        guard_on, tickets_on,
    ):
        """The consistency requirement, asserted directly: for each
        plan state, what the preview says and what the ticket endpoint
        does must match."""
        from app.services.checkout_orchestration import (
            NoActiveCreatorPlanError,
            resolve_fee_context,
        )

        for slug, expect_available in (
            (None, False), ("community", False), ("creator", True),
        ):
            creator = make_user(role="creator")
            space = make_space(creator=creator)
            event = make_event(space=space, ticket_price_cents=4500)
            if slug is not None:
                self._subscribe(db, creator, self._plan(db, slug, 0))

            body = _get(client_as(creator), space, "gathering", event.id).json()
            preview_available = body["arrangements"][0][
                "available_for_new_purchase"
            ]

            # What the till would decide, from the same shared rule.
            try:
                ctx = resolve_fee_context(space, db)
                till_allows = ctx.permits_paid_offers
            except NoActiveCreatorPlanError:
                till_allows = False

            assert preview_available == till_allows == expect_available, (
                f"{slug}: preview={preview_available} till={till_allows}"
            )


# ---------------------------------------------------------------------------
# 7. The upfront amount Stripe actually charges
# ---------------------------------------------------------------------------


class TestTheFirstChargeIsWhatStripeCollects:
    """``PaymentOptionSchedule.upfront_amount_cents`` is settable in
    three creator editors and stored, and no billing code reads it:
    ``stripe_finite_plan`` builds the subscription price from
    ``installment_amount_cents`` at a fixed interval, and there is no
    separate deposit charge anywhere in the plan lifecycle.

    The resolver used to prefer the stored value when set, which meant
    the preview could show a creator a "first charge" that would never
    be collected. It now reports what Stripe charges and carries the
    configured deposit separately so the discrepancy can be named
    rather than hidden.
    """

    def test_a_normal_plan_reports_the_first_instalment(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        _instalments(db, opt, each=3780, count=10, total=37800)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["upfront_amount_cents"] == 3780
        assert a["installment_amount_cents"] == 3780
        assert a["installment_count"] == 10
        assert a["interval"] == "week"
        assert a["total_amount_cents"] == 37800
        assert a["unsupported_upfront_amount_cents"] is None

    def test_a_configured_deposit_is_not_reported_as_the_first_charge(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        """The correction. A $100 deposit on a 3 x $33 plan does not
        happen — Stripe charges $33 first — so $33 is the first charge
        and the $100 is carried as a discrepancy."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        sched = _instalments(db, opt, each=3300, count=3, total=9900)
        sched.upfront_amount_cents = 10000
        db.flush()

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["upfront_amount_cents"] == 3300, "the deposit was reported as real"
        assert a["unsupported_upfront_amount_cents"] == 10000
        # The rest of the commitment is untouched.
        assert a["installment_amount_cents"] == 3300
        assert a["installment_count"] == 3
        assert a["total_amount_cents"] == 9900
        # And it is still purchasable — the schedule is valid, the
        # deposit is simply not collected.
        assert a["available_for_new_purchase"] is True

    def test_a_deposit_equal_to_the_instalment_is_not_a_discrepancy(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        sched = _instalments(db, opt, each=3300, count=3, total=9900)
        sched.upfront_amount_cents = 3300
        db.flush()

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["upfront_amount_cents"] == 3300
        assert a["unsupported_upfront_amount_cents"] is None

    def test_pay_in_full_charges_its_total(
        self, client_as, make_user, make_space, db,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=9900)

        body = _get(client_as(creator), space, "pathway", pathway.id).json()
        a = body["arrangements"][0]
        assert a["upfront_amount_cents"] == 9900
        assert a["unsupported_upfront_amount_cents"] is None

    def test_the_schedule_row_is_not_rewritten(
        self, client_as, make_user, make_space, db, plans_on,
    ):
        """We are correcting the presentation, not the record. The
        stored deposit stays exactly where the creator put it."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space)
        _grant(db, opt, "pathway", pathway.id)
        sched = _instalments(db, opt, each=3300, count=3, total=9900)
        sched.upfront_amount_cents = 10000
        db.flush()

        _get(client_as(creator), space, "pathway", pathway.id)
        db.refresh(sched)
        assert sched.upfront_amount_cents == 10000
        assert sched.installment_amount_cents == 3300
        assert sched.total_amount_cents == 9900

    def test_stripe_still_prices_from_the_instalment(self):
        """The premise, pinned on the billing code rather than assumed:
        the subscription price is built from the instalment amount, and
        the schedule's upfront column is read nowhere in billing."""
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        builder = (root / "services" / "stripe_finite_plan.py").read_text()
        assert "unit_amount=plan.installment_amount_cents" in builder

        billing = [
            "services/stripe_finite_plan.py",
            "services/finite_plan_orchestration.py",
            "services/finite_plan_lifecycle.py",
            "webhooks/finite_plan_handlers.py",
        ]
        readers = []
        for rel in billing:
            path = root / rel
            if not path.exists():
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "upfront_amount_cents"
                ):
                    readers.append(rel)
        assert readers == [], (
            "billing now reads upfront_amount_cents — the resolver's "
            f"presentation correction needs revisiting: {readers}"
        )
