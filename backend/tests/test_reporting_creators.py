"""The creator journey: four stages, and who is at each.

What these guard
----------------
The funnel's whole value is that it narrows — registered, then
building, then attracting, then earning — and every way it can go wrong
makes it narrow incorrectly. A stage that counted Collectives rather
than people would let one creator with three Collectives outnumber
three creators with one each. A stage that read today's state for a
past date would draw a flat line and call it history. A test account
joining a real Collective would promote its creator to "attracting"
without anybody having arrived.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_admin_user, get_current_user
from app.core.database import get_db
from app.main import app
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.reporting.classification import DEMONSTRATION, PRODUCTION, TEST
from app.reporting.population import Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope

CREATORS = "/api/admin/reporting/creators"
STAGES = (
    "creators_with_a_collective",
    "creators_with_a_member",
    "creators_earning",
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db, make_user):
    admin = make_user(role="admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def _join(db, user, space, joined_at=None, removed_at=None):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner,
        status=(
            SpaceMembershipStatus.removed if removed_at
            else SpaceMembershipStatus.active
        ),
        joined_at=joined_at or datetime(2026, 1, 1),
        removed_at=removed_at,
    ))
    db.flush()


def _pay(db, space, creator, payer, *, when, gross=10000, net=9000):
    db.add(PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=payer.id, creator_user_id=creator.id, space_id=space.id,
        currency="AUD", gross_amount_cents=gross,
        platform_fee_basis_points=1000, platform_fee_cents=1000,
        net_creator_amount_cents=net, processing_fee_cents=200,
        stripe_mode="test", created_at=when, settled_at=when,
    ))
    db.flush()


def val(db, key, window=None, population=None):
    return REGISTRY.get(key).evaluate(
        db, platform_scope(), window or Window(),
        population or Population(PopulationView.all),
    ).value


# ---------------------------------------------------------------------------

class TestTheStagesNarrow:
    def test_each_stage_counts_people_not_collectives(
        self, db, make_user, make_space,
    ):
        """One creator with three Collectives is one creator."""
        creator = make_user(role="creator")
        for _ in range(3):
            make_space(creator=creator, reporting_class=PRODUCTION)
        assert val(db, "creators_with_a_collective") == 1

    def test_a_creator_who_built_nothing_is_not_building(self, db, make_user):
        make_user(role="creator")
        assert val(db, "creators_with_a_collective") == 0

    def test_the_stages_narrow_rather_than_sum(self, db, make_user, make_space):
        building = make_user(role="creator")
        make_space(creator=building, reporting_class=PRODUCTION)

        attracting = make_user(role="creator")
        s2 = make_space(creator=attracting, reporting_class=PRODUCTION)
        _join(db, make_user(), s2)

        earning = make_user(role="creator")
        s3 = make_space(creator=earning, reporting_class=PRODUCTION)
        _join(db, make_user(), s3)
        _pay(db, s3, earning, make_user(), when=datetime(2026, 6, 1))

        assert val(db, "creators_with_a_collective") == 3
        assert val(db, "creators_with_a_member") == 2
        assert val(db, "creators_earning") == 1

    def test_every_stage_is_a_snapshot(self):
        for key in STAGES:
            assert REGISTRY.get(key).aggregation.value == "snapshot", key

    def test_registrations_are_a_flow_beside_the_snapshot(self):
        assert REGISTRY.get("creators_registered").aggregation.value == "additive"
        assert REGISTRY.get("registered_creators").aggregation.value == "snapshot"


class TestTheJourneyHasRealHistory:
    def test_a_stage_is_reconstructed_as_at_a_past_date(
        self, db, make_user, make_space,
    ):
        """Not today's figures drawn backwards."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        space.created_at = datetime(2026, 5, 1)
        db.flush()
        _join(db, make_user(), space, joined_at=datetime(2026, 8, 10))

        june = Window(datetime(2026, 6, 1), datetime(2026, 7, 1), "jun")
        sept = Window(datetime(2026, 9, 1), datetime(2026, 10, 1), "sep")
        assert val(db, "creators_with_a_collective", june) == 1
        assert val(db, "creators_with_a_member", june) == 0, (
            "nobody had joined by June"
        )
        assert val(db, "creators_with_a_member", sept) == 1

    def test_a_collective_built_later_is_absent_from_an_earlier_date(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        space.created_at = datetime(2026, 9, 15)
        db.flush()
        june = Window(datetime(2026, 6, 1), datetime(2026, 7, 1), "jun")
        assert val(db, "creators_with_a_collective", june) == 0
        assert val(db, "creators_with_a_collective") == 1

    def test_earning_is_dated_by_settlement(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        space.created_at = datetime(2026, 1, 1)
        db.flush()
        _pay(db, space, creator, make_user(), when=datetime(2026, 9, 10))
        aug = Window(datetime(2026, 8, 1), datetime(2026, 9, 1), "aug")
        octo = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert val(db, "creators_earning", aug) == 0
        assert val(db, "creators_earning", octo) == 1

    def test_a_member_who_left_is_not_counted_afterwards(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        space.created_at = datetime(2026, 1, 1)
        db.flush()
        _join(db, make_user(), space,
              joined_at=datetime(2026, 2, 1), removed_at=datetime(2026, 5, 1))
        march = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "mar")
        july = Window(datetime(2026, 7, 1), datetime(2026, 8, 1), "jul")
        assert val(db, "creators_with_a_member", march) == 1
        assert val(db, "creators_with_a_member", july) == 0

    def test_publishing_is_deliberately_not_a_stage(self):
        """``spaces.status`` has no history, so a published-stage would
        be the one step of the funnel nobody could trust."""
        assert "creators_with_a_published_collective" not in REGISTRY


class TestClassificationAppliesToTheJourney:
    def test_a_test_member_does_not_promote_a_creator_to_attracting(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        _join(db, make_user(reporting_class=TEST), space)
        production = Population(PopulationView.production)
        assert val(db, "creators_with_a_member") == 1
        assert val(db, "creators_with_a_member", None, production) == 0, (
            "nobody real has arrived"
        )

    def test_a_test_creator_is_out_of_the_production_funnel(
        self, db, make_user, make_space,
    ):
        fixture = make_user(role="creator", reporting_class=TEST)
        make_space(creator=fixture, reporting_class=PRODUCTION)
        production = Population(PopulationView.production)
        assert val(db, "creators_with_a_collective") == 1
        assert val(db, "creators_with_a_collective", None, production) == 0

    def test_a_demonstration_collective_is_out_of_the_production_funnel(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        make_space(creator=creator, reporting_class=DEMONSTRATION)
        assert val(
            db, "creators_with_a_collective", None,
            Population(PopulationView.production),
        ) == 0

    def test_every_stage_can_be_narrowed(self):
        for key in (*STAGES, "creators_registered"):
            assert REGISTRY.get(key).honours_population, key


class TestTheCreatorsListing:
    def test_it_reports_the_furthest_stage_reached(
        self, db, client, make_user, make_space,
    ):
        earning = make_user(role="creator", name="Kelly Hamilton")
        space = make_space(creator=earning, name="Nourish Connect Thrive",
                           reporting_class=PRODUCTION)
        _join(db, make_user(), space)
        _pay(db, space, earning, make_user(), when=datetime(2026, 9, 1))

        rows = client.get(CREATORS).json()
        kelly = next(r for r in rows if r["name"] == "Kelly Hamilton")
        assert kelly["stage"] == "earning"
        assert kelly["collectives"] == ["Nourish Connect Thrive"]
        assert kelly["members"] == 1
        assert kelly["earned_cents"] == 9000

    def test_a_creator_who_built_nothing_is_registered(self, client, make_user):
        make_user(role="creator", name="Signed up only")
        rows = client.get(CREATORS).json()
        row = next(r for r in rows if r["name"] == "Signed up only")
        assert row["stage"] == "registered"
        assert row["collectives"] == []

    def test_founder_operated_is_distinguishable_from_independent(
        self, db, client, make_user, make_space,
    ):
        founder = make_user(role="admin", name="Founder")
        make_space(creator=founder, name="EMBODY", reporting_class=PRODUCTION)
        independent = make_user(role="creator", name="Kelly Hamilton")
        make_space(creator=independent, name="NCT", reporting_class=PRODUCTION)

        rows = {r["name"]: r for r in client.get(CREATORS).json()}
        assert rows["Kelly Hamilton"]["founder_operated"] is False
        # The founder operates Collectives from an account holding the
        # admin role. They belong in this list, marked as what they are
        # — an earlier version filtered on ``role == 'creator'`` and
        # dropped them, so the founder-operated table read "none in
        # this classification" with two sitting in front of the reader.
        assert "Founder" in rows, (
            "an operator is a creator here however their role column reads"
        )
        assert rows["Founder"]["founder_operated"] is True
        assert rows["Founder"]["collectives"] == ["EMBODY"]

    def test_founder_operated_has_one_definition(self):
        """It was declared inside the outstanding-payouts breakdown."""
        from app.reporting import metrics
        from app.reporting.creators import founder_operated_space_ids

        source = metrics.__file__
        with open(source) as fh:
            body = fh.read()
        assert "founder_operated_space_ids()" in body
        assert body.count("User.role == UserRole.admin.value") == 0, (
            "the definition must not be repeated"
        )
        assert founder_operated_space_ids() is not None

    def test_test_identities_stay_out_of_production_but_remain_reachable(
        self, client, make_user,
    ):
        make_user(role="creator", name="Fixture creator", reporting_class=TEST)
        production = {
            r["name"]
            for r in client.get(CREATORS, params={"population": "production"}).json()
        }
        everything = {r["name"] for r in client.get(CREATORS).json()}
        assert "Fixture creator" not in production
        assert "Fixture creator" in everything

    def test_an_unknown_population_is_422(self, client):
        assert client.get(
            CREATORS, params={"population": "pretend"}
        ).status_code == 422

    def test_the_listing_carries_no_score(self, client, make_user):
        make_user(role="creator", name="Someone")
        row = client.get(CREATORS).json()[0]
        assert "score" not in " ".join(row.keys()).lower()


class TestFounderOperatedIsVisible:
    """The defect the review found.

    The founder's account holds the ``admin`` role and operates EMBODY
    and Life in Full Colour. Both the listing and the journey metrics
    filtered on ``role == 'creator'``, so two production Collectives
    and their operator were invisible to the whole Creators section —
    the funnel undercounted and the founder-operated table read "none
    in this classification" with two sitting in front of the reader.

    An earlier test asserted the absence as correct behaviour, which is
    how it survived. Role is what an account may *do*; operating a
    Collective is what it has done, and this section asks the second.
    """

    def _world(self, db, make_user, make_space):
        founder = make_user(role="admin", name="Lindsey",
                            reporting_class=PRODUCTION)
        make_space(creator=founder, name="EMBODY", reporting_class=PRODUCTION)
        make_space(creator=founder, name="Life in Full Colour",
                   reporting_class=PRODUCTION)
        kelly = make_user(role="creator", name="Kelly Hamilton",
                          reporting_class=PRODUCTION)
        make_space(creator=kelly, name="Nourish Connect Thrive",
                   reporting_class=PRODUCTION)
        return founder, kelly

    def test_an_administrator_who_operates_collectives_is_listed(
        self, db, client, make_user, make_space,
    ):
        self._world(db, make_user, make_space)
        rows = {r["name"]: r for r in client.get(
            CREATORS, params={"population": "production"}).json()}
        assert "Lindsey" in rows, "the founder operates two Collectives"
        assert rows["Lindsey"]["founder_operated"] is True
        assert rows["Lindsey"]["collectives"] == [
            "EMBODY", "Life in Full Colour",
        ]

    def test_the_founder_operated_group_is_not_empty(
        self, db, client, make_user, make_space,
    ):
        self._world(db, make_user, make_space)
        rows = client.get(CREATORS, params={"population": "production"}).json()
        founders = [r for r in rows if r["founder_operated"]]
        assert len(founders) == 1
        assert founders[0]["name"] == "Lindsey"

    def test_independent_creators_are_still_independent(
        self, db, client, make_user, make_space,
    ):
        self._world(db, make_user, make_space)
        rows = {r["name"]: r for r in client.get(
            CREATORS, params={"population": "production"}).json()}
        assert rows["Kelly Hamilton"]["founder_operated"] is False

    def test_the_journey_counts_the_founders_collectives(
        self, db, make_user, make_space,
    ):
        self._world(db, make_user, make_space)
        production = Population(PopulationView.production)
        assert val(db, "creators_with_a_collective", None, production) == 2, (
            "two operators have built Collectives, not one"
        )

    def test_the_funnel_still_narrows(self, db, make_user, make_space):
        """A base that excluded the founder let it widen instead."""
        self._world(db, make_user, make_space)
        production = Population(PopulationView.production)
        order = [
            "creator_accounts",
            "creators_with_a_collective",
            "creators_with_a_member",
            "creators_earning",
        ]
        values = [val(db, k, None, production) for k in order]
        for earlier, later in zip(values, values[1:]):
            assert earlier >= later, f"funnel widened: {dict(zip(order, values))}"

    def test_the_funnel_base_is_wider_than_the_creator_role_alone(
        self, db, make_user, make_space,
    ):
        self._world(db, make_user, make_space)
        production = Population(PopulationView.production)
        assert val(db, "registered_creators", None, production) == 1
        assert val(db, "creator_accounts", None, production) == 2, (
            "the founder holds an admin role and still operates Collectives"
        )

    def test_a_creator_who_has_built_nothing_is_still_in_the_base(
        self, db, make_user,
    ):
        make_user(role="creator", name="Signed up only")
        assert val(db, "creator_accounts") == 1
        assert val(db, "creators_with_a_collective") == 0

    def test_a_test_classified_operator_is_still_excluded_from_production(
        self, db, client, make_user, make_space,
    ):
        """Widening the population must not weaken the classification."""
        fixture = make_user(role="admin", name="Fixture admin",
                            reporting_class=TEST)
        make_space(creator=fixture, name="Sandbox", reporting_class=PRODUCTION)
        names = {r["name"] for r in client.get(
            CREATORS, params={"population": "production"}).json()}
        assert "Fixture admin" not in names


class TestEarningsSayWhoseTheyAre:
    def test_earnings_split_founder_operated_from_independent(
        self, db, make_user, make_space,
    ):
        founder = make_user(role="admin")
        founder_space = make_space(creator=founder, reporting_class=PRODUCTION)
        kelly = make_user(role="creator")
        kelly_space = make_space(creator=kelly, reporting_class=PRODUCTION)
        _pay(db, founder_space, founder, make_user(),
             when=datetime(2026, 10, 10), net=7000)
        _pay(db, kelly_space, kelly, make_user(),
             when=datetime(2026, 10, 10), net=3000)

        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = REGISTRY.get("creator_earnings_cents").evaluate(
            db, platform_scope(), window,
        )
        assert v.value == 10000, "the total is still what creators earned"
        assert v.qualifiers["by_operator_cents"] == {
            "founder_operated": 7000,
            "independent": 3000,
        }

    def test_the_split_sums_to_the_total(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        _pay(db, space, creator, make_user(), when=datetime(2026, 10, 5), net=4200)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = REGISTRY.get("creator_earnings_cents").evaluate(
            db, platform_scope(), window,
        )
        split = v.qualifiers["by_operator_cents"]
        assert split["founder_operated"] + split["independent"] == v.value

    def test_only_earnings_carry_the_split(self, db):
        """Gross sales and payouts are not creator-attributed figures."""
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        for key in ("gross_collective_sales_cents", "platform_fee_revenue_cents"):
            v = REGISTRY.get(key).evaluate(db, platform_scope(), window)
            assert "by_operator_cents" not in v.qualifiers, key


class TestCardsRespectTheirStatedPopulation:
    """A page headed "Production" showed production trends above
    whole-platform figures, and nothing said which was which."""

    def test_query_narrows_by_population(
        self, db, client, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        demo = make_space(reporting_class=DEMONSTRATION)
        creator = make_user(role="creator")
        _pay(db, prod, creator, make_user(), when=datetime(2026, 10, 5), net=1000)
        _pay(db, demo, creator, make_user(), when=datetime(2026, 10, 5), net=9000)

        def earnings(population):
            body = client.get("/api/admin/reporting/query", params={
                "keys": "creator_earnings_cents",
                "period": "all_time", "population": population,
            }).json()
            return body["metrics"][0]["value"], body["population"]["key"]

        everything, pop_all = earnings("all")
        production, pop_prod = earnings("production")
        assert (pop_all, pop_prod) == ("all", "production")
        assert everything == 10000
        assert production == 1000

    def test_the_default_is_the_complete_ledger(self, client):
        body = client.get("/api/admin/reporting/query", params={
            "keys": "creator_earnings_cents", "period": "all_time",
        }).json()
        assert body["population"]["key"] == "all"

    def test_an_unknown_population_is_422(self, client):
        assert client.get("/api/admin/reporting/query", params={
            "keys": "unique_members", "population": "pretend",
        }).status_code == 422

    def test_the_result_says_which_population_it_describes(self, client):
        body = client.get("/api/admin/reporting/query", params={
            "keys": "unique_members", "population": "production",
        }).json()
        assert body["population"]["label"] == "Production"
        assert "subset of the ledger" in body["population"]["note"]
