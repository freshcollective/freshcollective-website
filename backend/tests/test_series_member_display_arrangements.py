"""Stage 1B.2B — the member Ways to Join list, from the resolver.

The promise this stage has to keep is narrow and absolute: **a member
must read the price checkout will charge.** So the test that matters
most is not "does the new builder work" but "do the two builders
produce the identical payload" — asserted by serving the real endpoint
twice, once in each flag state, and comparing the whole response.

That shape is deliberate. A field-by-field test would pass while
quietly omitting a field; comparing the full JSON cannot. And it is the
same property the production shadow comparison measures, so a
disagreement here would be the same disagreement, caught earlier.

What is explicitly *not* changed by the flag, and is pinned here:
checkout identifiers (``payment_option_id`` and the schedule ``id``),
prices, schedules, ordering, and ``viewer_holds_this_option`` — the
member who already bought something is still not asked to buy it again,
because eligibility never moved into the resolver.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway, PathwayType, SpaceMembership


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _series(db, space, *, title="EMBODY Term 4 2026") -> EventSeries:
    s = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title, starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=70), status="published",
    )
    db.add(s)
    db.flush()
    return s


def _pathway(db, space, *, title="The EMBODY Practice") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="payment_options", currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, name="EMBODY Term Pass", description=None,
            status=PaymentOptionStatus.published, position=0,
            currency="AUD") -> PaymentOption:
    o = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name, description=description,
        payment_type=PaymentOptionType.one_time, status=status,
        currency=currency, position=position,
    )
    db.add(o)
    db.flush()
    return o


def _pay_in_full(db, option, *, cents, currency="AUD", status="published",
                 name="Pay in full", position=0) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _instalments(db, option, *, each, count, interval="week", total=None,
                 currency="AUD", status="published", name="Weekly payments",
                 position=1) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval, stripe_interval_count=1,
        total_amount_cents=total if total is not None else each * count,
        currency=currency, position=position,
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
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def member(db, space, make_user):
    """An active member — the Gatherings area is not reachable
    anonymously on a default Collective."""
    user = make_user(role="user")
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role="learner", status="active",
    ))
    db.flush()
    return user


@pytest.fixture
def ways_to_join(db, space, member):
    """Fetch the real Ways to Join payload in a given flag state."""
    def _go(series, *, resolver: bool, plans: bool = True):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: member
        client = TestClient(app)
        url = (
            f"/api/spaces/{space.slug}/gathering-series/"
            f"{series.slug}/payment-options"
        )
        try:
            with patch(
                "app.core.config.settings.purchase_arrangements_member_display",
                resolver,
            ), patch(
                "app.core.config.settings.finite_plan_member_checkout_enabled",
                plans,
            ):
                res = client.get(url)
            assert res.status_code == 200, res.text
            return res.json()
        finally:
            app.dependency_overrides.clear()

    return _go


@pytest.fixture
def both_ways(ways_to_join):
    """The payload each way round, for an equivalence assertion."""
    def _go(series, **kw):
        return (
            ways_to_join(series, resolver=False, **kw),
            ways_to_join(series, resolver=True, **kw),
        )
    return _go


def _embody(db, space, series, *, pathway=None):
    """EMBODY Term 4's real shape: A$180 in full, or 10 weekly A$18."""
    opt = _option(
        db, space, name="EMBODY Term Pass",
        description="One term of EMBODY, however you'd like to pay.",
    )
    _grant(db, opt, "event_series", series.id, sessions_per_week=2,
           total_sessions=20)
    if pathway is not None:
        _grant(db, opt, "pathway", pathway.id)
    full = _pay_in_full(db, opt, cents=18000)
    plan = _instalments(db, opt, each=1800, count=10, total=18000)
    return opt, full, plan


# ---------------------------------------------------------------------------
# 1. The two displays agree — the property this stage rests on
# ---------------------------------------------------------------------------


class TestTheTwoDisplaysAgree:
    def test_embody_full_payment_and_instalments(self, db, space, both_ways):
        """Scenarios 1 and 2 together, as they actually exist: one
        Option offering A$180 once or 10 weekly payments of A$18."""
        series = _series(db, space)
        _embody(db, space, series)

        legacy, resolver = both_ways(series)
        assert legacy == resolver, f"\nlegacy={legacy}\nresolver={resolver}"
        # And the figures are the real ones, not an empty agreement.
        assert len(resolver) == 1
        scheds = {s["schedule_type"]: s for s in resolver[0]["schedules"]}
        assert scheds["pay_in_full"]["total_amount_cents"] == 18000
        assert scheds["recurring_installments"]["installment_amount_cents"] == 1800
        assert scheds["recurring_installments"]["installment_count"] == 10
        assert scheds["recurring_installments"]["total_amount_cents"] == 18000
        assert scheds["recurring_installments"]["interval"] == "week"

    def test_a_bundle_including_a_pathway(self, db, space, both_ways):
        series = _series(db, space)
        pathway = _pathway(db, space)
        _embody(db, space, series, pathway=pathway)

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        # Order, not just membership. The resolver returns ``included``
        # in grant-query order, which is not deterministic — this
        # assertion is what caught the card's "Includes" line flipping
        # between runs. The Series being viewed leads.
        assert resolver[0]["included_titles"] == [
            "EMBODY Term 4 2026", "The EMBODY Practice",
        ]

    def test_multiple_arrangements_for_one_series(self, db, space, both_ways):
        """Scenario 3 — three Options, one with two schedules."""
        series = _series(db, space)
        for i, cents in enumerate((12000, 18000, 24000)):
            opt = _option(db, space, name=f"Pass {i}", position=i)
            _grant(db, opt, "event_series", series.id, sessions_per_week=1)
            _pay_in_full(db, opt, cents=cents)
            if i == 1:
                _instalments(db, opt, each=1800, count=10, total=18000)

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert [o["name"] for o in resolver] == ["Pass 0", "Pass 1", "Pass 2"]
        assert [len(o["schedules"]) for o in resolver] == [1, 2, 1]

    @pytest.mark.parametrize("currency", ["NZD", "GBP", "EUR", "USD"])
    def test_a_non_aud_currency(self, db, space, both_ways, currency):
        """Scenario 7. The payload carries the currency; no surface
        hardcodes dollars."""
        series = _series(db, space)
        opt = _option(db, space, currency=currency)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000, currency=currency)

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert resolver[0]["schedules"][0]["currency"] == currency

    def test_an_option_with_a_different_payment_configuration(
        self, db, space, both_ways,
    ):
        """Scenario 6 — a creator-managed arrangement on its own terms:
        fortnightly, six payments, an explicit total, no pay-in-full."""
        series = _series(db, space)
        opt = _option(db, space, name="Fortnightly pass")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1,
               total_sessions=12)
        sched = _instalments(
            db, opt, each=3000, count=6, total=18000, name="Every fortnight",
        )
        sched.stripe_interval_count = 2
        db.flush()

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        row = resolver[0]["schedules"][0]
        assert row["installment_amount_cents"] == 3000
        assert row["installment_count"] == 6
        assert row["total_amount_cents"] == 18000

    def test_instalments_behind_their_flag(self, db, space, both_ways):
        """With finite-plan checkout off, both displays ship the plan
        row unbuyable rather than hiding it — the frontend filters on
        the flag, never on ``schedule_type``."""
        series = _series(db, space)
        _embody(db, space, series)

        legacy, resolver = both_ways(series, plans=False)
        assert legacy == resolver
        scheds = {s["schedule_type"]: s for s in resolver[0]["schedules"]}
        assert scheds["pay_in_full"]["is_member_checkoutable"] is True
        assert scheds["recurring_installments"]["is_member_checkoutable"] is False
        # Still present, with its real figures.
        assert scheds["recurring_installments"]["installment_amount_cents"] == 1800


# ---------------------------------------------------------------------------
# 2. Unavailable and hidden arrangements
# ---------------------------------------------------------------------------


class TestWhatIsNotOffered:
    def test_a_draft_option_is_absent_from_both(self, db, space, both_ways):
        """Scenario 4."""
        series = _series(db, space)
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        legacy, resolver = both_ways(series)
        assert legacy == resolver == []

    def test_an_archived_option_is_absent_from_both(self, db, space, both_ways):
        series = _series(db, space)
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        legacy, resolver = both_ways(series)
        assert legacy == resolver == []

    def test_a_draft_schedule_is_absent_from_both(self, db, space, both_ways):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        _instalments(db, opt, each=1800, count=10, status="draft")

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert len(resolver[0]["schedules"]) == 1
        assert resolver[0]["schedules"][0]["schedule_type"] == "pay_in_full"

    def test_an_option_with_nothing_buyable_is_absent_from_both(
        self, db, space, both_ways,
    ):
        """An instalment-only Option with finite-plan checkout off has
        no completable schedule, so the card does not appear at all
        rather than appearing with a dead CTA."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _instalments(db, opt, each=1800, count=10)

        legacy, resolver = both_ways(series, plans=False)
        assert legacy == resolver == []

    def test_a_gathering_grant_removes_the_option_from_both(
        self, db, space, both_ways, make_event,
    ):
        """Stage 0's shared rule, still enforced on the member surface:
        the unified checkout refuses an Option carrying a Gathering
        grant, so neither display offers it."""
        series = _series(db, space)
        event = make_event(space=space, ticket_price_cents=2000)
        opt = _option(db, space, name="Pass plus a Gathering")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _grant(db, opt, "gathering", event.id)
        _pay_in_full(db, opt, cents=20000)

        legacy, resolver = both_ways(series)
        assert legacy == resolver == []

    def test_an_invalid_schedule_is_handled_the_same_way(
        self, db, space, both_ways,
    ):
        """total != per x count. Neither display offers it, and neither
        invents a price to show instead."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        _instalments(db, opt, each=1800, count=10, total=99999)

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        plan = next(
            (s for s in resolver[0]["schedules"]
             if s["schedule_type"] == "recurring_installments"),
            None,
        )
        assert plan is not None
        assert plan["is_member_checkoutable"] is False


# ---------------------------------------------------------------------------
# 3. Checkout compatibility — the identifiers
# ---------------------------------------------------------------------------


class TestCheckoutIdentifiersAreUnchanged:
    def test_the_option_and_schedule_ids_are_the_real_rows(
        self, db, space, ways_to_join,
    ):
        """What a member hands back is what checkout re-derives from.
        Substituting an identifier would be the one way this stage could
        charge somebody the wrong amount, so the ids are asserted
        against the database rows directly."""
        series = _series(db, space)
        opt, full, plan = _embody(db, space, series)

        payload = ways_to_join(series, resolver=True)
        assert payload[0]["id"] == opt.id
        assert {s["id"] for s in payload[0]["schedules"]} == {full.id, plan.id}

    def test_both_displays_name_the_same_identifiers(
        self, db, space, both_ways,
    ):
        series = _series(db, space)
        _embody(db, space, series)

        legacy, resolver = both_ways(series)
        def ids(payload):
            return {
                (o["id"], s["id"]) for o in payload for s in o["schedules"]
            }
        assert ids(legacy) == ids(resolver)

    def test_no_arrangement_identifier_leaks_into_the_payload(
        self, db, space, ways_to_join,
    ):
        """The resolver's own ``arrangement_id`` is internal to Stage 1A
        and is not a checkout identifier. It must not appear in a member
        payload, where it could be mistaken for one."""
        series = _series(db, space)
        _embody(db, space, series)

        import json
        body = json.dumps(ways_to_join(series, resolver=True))
        assert "arrangement_id" not in body
        assert "option:" not in body
        assert "direct:" not in body


# ---------------------------------------------------------------------------
# 4. Eligibility stays where it was
# ---------------------------------------------------------------------------


class TestAMemberWithAccessIsNotAskedAgain:
    def test_viewer_holds_this_option_is_set_in_both(
        self, db, space, member, both_ways,
    ):
        """Scenario 5. The resolver has no member in its question, so
        this had to keep being answered by the endpoint — and it is."""
        series = _series(db, space)
        opt, _full, _plan = _embody(db, space, series)
        db.add(AccessPass(
            id=_uid("ap"), user_id=member.id, space_id=space.id,
            payment_option_id=opt.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
            valid_from=datetime.utcnow(),
        ))
        db.flush()

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert resolver[0]["viewer_holds_this_option"] is True

    def test_a_member_without_access_is_still_offered_it(
        self, db, space, both_ways,
    ):
        series = _series(db, space)
        _embody(db, space, series)
        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert resolver[0]["viewer_holds_this_option"] is False

    def test_an_expired_pass_does_not_count_as_holding_it(
        self, db, space, member, both_ways,
    ):
        series = _series(db, space)
        opt, _f, _p = _embody(db, space, series)
        db.add(AccessPass(
            id=_uid("ap"), user_id=member.id, space_id=space.id,
            payment_option_id=opt.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
            valid_from=datetime.utcnow() - timedelta(days=100),
            valid_until=datetime.utcnow() - timedelta(days=1),
        ))
        db.flush()

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        assert resolver[0]["viewer_holds_this_option"] is False


# ---------------------------------------------------------------------------
# 5. The upfront discrepancy must not come back
# ---------------------------------------------------------------------------


class TestTheFirstChargeIsWhatStripeCollects:
    def test_a_stored_upfront_is_not_shown_as_the_first_charge(
        self, db, space, both_ways,
    ):
        """Scenario 8. ``PaymentOptionSchedule.upfront_amount_cents`` is
        settable and read by no billing code — Stripe charges the
        instalment amount. Reporting the deposit as a first charge was
        the discrepancy corrected in 7a21fab, and a new display is
        exactly where it could come back."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        sched = _instalments(db, opt, each=1800, count=10, total=18000)
        sched.upfront_amount_cents = 5000
        db.flush()

        legacy, resolver = both_ways(series)
        assert legacy == resolver
        row = resolver[0]["schedules"][0]
        assert row["installment_amount_cents"] == 1800
        assert row["total_amount_cents"] == 18000
        # The figure nothing collects appears nowhere.
        import json
        assert "5000" not in json.dumps(resolver)
        assert "upfront" not in json.dumps(resolver)


# ---------------------------------------------------------------------------
# 6. The flag itself
# ---------------------------------------------------------------------------


class TestTheFlag:
    def test_it_is_off_by_default(self):
        from app.core.config import Settings

        assert Settings.model_fields[
            "purchase_arrangements_member_display"
        ].default is False

    def test_the_legacy_builder_is_untouched_while_it_is_off(
        self, db, space, ways_to_join,
    ):
        """Off must mean the legacy path, not the new one producing the
        same answer. Asserted by watching the resolver-backed builder
        while serving the endpoint."""
        series = _series(db, space)
        _embody(db, space, series)

        with patch(
            "app.spaces.series_arrangement_display.build_display_options",
        ) as builder:
            payload = ways_to_join(series, resolver=False)
        builder.assert_not_called()
        assert len(payload) == 1

    def test_the_resolver_builder_is_used_when_it_is_on(
        self, db, space, ways_to_join,
    ):
        series = _series(db, space)
        _embody(db, space, series)

        from app.spaces import series_arrangement_display as mod

        real = mod.build_display_options
        calls: list[str] = []

        def _spy(db_, *, series_id):
            calls.append(series_id)
            return real(db_, series_id=series_id)

        with patch.object(mod, "build_display_options", _spy):
            payload = ways_to_join(series, resolver=True)
        assert calls == [series.id]
        assert len(payload) == 1

    def test_the_section_gate_agrees_with_the_display(
        self, db, space, member,
    ):
        """``has_purchasable`` on the Series detail decides whether the
        Ways to Join section renders at all. If it read the other
        source, the section could be shown empty or hidden while
        options exist."""
        series = _series(db, space)
        _embody(db, space, series)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: member
        client = TestClient(app)
        url = f"/api/spaces/{space.slug}/gathering-series/{series.slug}"
        try:
            for resolver in (False, True):
                with patch(
                    "app.core.config.settings"
                    ".purchase_arrangements_member_display", resolver,
                ):
                    res = client.get(url)
                assert res.status_code == 200, res.text
                assert res.json()["has_purchasable_options"] is True, resolver
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. It is a display, not a checkout
# ---------------------------------------------------------------------------


class TestItChangesNoPayment:
    def test_the_display_builder_writes_nothing(self):
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "spaces" / "series_arrangement_display.py"
        )
        tree = ast.parse(path.read_text())
        banned = {
            "commit", "flush", "add", "add_all", "delete", "merge",
            "with_for_update", "rollback",
        }
        found = sorted({
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr in banned
            and isinstance(n.value, ast.Name)
            and n.value.id == "db"
        })
        assert found == [], f"the display builder may mutate: {found}"

    def test_it_touches_no_stripe_and_no_checkout(self):
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "spaces" / "series_arrangement_display.py"
        )
        tree = ast.parse(path.read_text())
        imported = {
            (n.module or "").lower()
            for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        } | {
            alias.name.lower()
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for alias in n.names
        }
        for banned in ("stripe", "checkout"):
            assert not any(banned in name for name in imported), (
                f"the display builder imports {banned}: {sorted(imported)}"
            )

    def test_no_new_purchase_option_is_exposed(self, db, space, both_ways):
        """The flag must not reveal anything the legacy display withheld
        — asserted as a set comparison over every schedule either
        display considers buyable, across a deliberately awkward mix."""
        series = _series(db, space)
        good = _option(db, space, name="Buyable", position=0)
        _grant(db, good, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, good, cents=18000)

        draft = _option(db, space, name="Draft",
                        status=PaymentOptionStatus.draft, position=1)
        _grant(db, draft, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, draft, cents=9900)

        archived = _option(db, space, name="Archived",
                           status=PaymentOptionStatus.archived, position=2)
        _grant(db, archived, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, archived, cents=5000)

        legacy, resolver = both_ways(series)

        def buyable(payload):
            return {
                (o["id"], s["id"], s["total_amount_cents"])
                for o in payload for s in o["schedules"]
                if s["is_member_checkoutable"]
            }
        assert buyable(legacy) == buyable(resolver)
        assert len(buyable(resolver)) == 1
