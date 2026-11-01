"""The two metrics the Overview needed that did not already exist.

What these guard
----------------
Both exist because the obvious substitute is wrong in a way that
reads as plausible.

**New members is not new memberships.** Somebody who joins three
Collectives in a month is one person who arrived and three
memberships started. Answering "how many people joined" with the
membership flow overstates arrivals by exactly the amount of
enthusiasm a new member shows.

**Fresh Collective revenue is not gross Collective sales.** The two
differ by roughly an order of magnitude and most of the larger figure
is creators' money. Putting the wrong one on a management overview
would overstate the business dramatically.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

import app.models.community_care  # noqa: F401
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


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


JUNE = Window(
    starts_at=datetime(2026, 6, 1), ends_at=datetime(2026, 7, 1), label="June",
)


def _join(db, user, space, when):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=when,
    ))
    db.flush()


def ev(db, key, window=None, population=None):
    return REGISTRY.get(key).evaluate(
        db, platform_scope(), window or Window(),
        population or Population(PopulationView.all),
    )


class TestNewMembersAreNotNewMemberships:
    def test_one_person_joining_three_collectives_is_one_member(
        self, db, make_user, make_space,
    ):
        person = make_user()
        for _ in range(3):
            _join(db, person, make_space(reporting_class=PRODUCTION),
                  datetime(2026, 6, 10))

        assert ev(db, "members_joined", JUNE).value == 1
        # The flow beside it still counts rows, which is its job.
        assert ev(db, "memberships_started", JUNE).value == 3

    def test_it_separates_genuinely_new_people_from_existing_members(
        self, db, make_user, make_space,
    ):
        returning = make_user()
        _join(db, returning, make_space(reporting_class=PRODUCTION),
              datetime(2026, 1, 5))
        _join(db, returning, make_space(reporting_class=PRODUCTION),
              datetime(2026, 6, 10))

        brand_new = make_user()
        _join(db, brand_new, make_space(reporting_class=PRODUCTION),
              datetime(2026, 6, 12))

        v = ev(db, "members_joined", JUNE)
        assert v.value == 2
        assert v.qualifiers["first_time"] == 1
        assert v.qualifiers["already_a_member_elsewhere"] == 1

    def test_a_join_outside_the_window_is_not_counted(
        self, db, make_user, make_space,
    ):
        _join(db, make_user(), make_space(reporting_class=PRODUCTION),
              datetime(2026, 5, 31))
        assert ev(db, "members_joined", JUNE).value == 0

    def test_production_excludes_a_test_account(
        self, db, make_user, make_space,
    ):
        space = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), space, datetime(2026, 6, 10))
        _join(db, make_user(reporting_class=TEST), space,
              datetime(2026, 6, 11))

        assert ev(db, "members_joined", JUNE).value == 2
        assert ev(
            db, "members_joined", JUNE,
            Population(PopulationView.production),
        ).value == 1

    def test_production_excludes_a_demonstration_collective(
        self, db, make_user, make_space,
    ):
        _join(db, make_user(), make_space(reporting_class=PRODUCTION),
              datetime(2026, 6, 10))
        _join(db, make_user(), make_space(reporting_class=DEMONSTRATION),
              datetime(2026, 6, 10))
        assert ev(
            db, "members_joined", JUNE,
            Population(PopulationView.production),
        ).value == 1

    def test_it_is_never_summable(self):
        """Two months of distinct people do not add to a two-month figure."""
        from app.reporting.registry import Aggregation

        m = REGISTRY.get("members_joined")
        assert m.aggregation is Aggregation.distinct_count


class TestFreshCollectiveRevenue:
    def _sale(self, db, space, creator, payer, *, gross, fee, net, when):
        db.add(PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.succeeded,
            payer_user_id=payer.id, creator_user_id=creator.id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=gross, platform_fee_basis_points=1000,
            platform_fee_cents=fee, net_creator_amount_cents=net,
            processing_fee_cents=200, stripe_mode="test",
            created_at=when, settled_at=when,
        ))
        db.flush()

    def test_it_is_the_platform_share_not_the_gross(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        self._sale(
            db, space, creator, make_user(),
            gross=100_00, fee=10_00, net=90_00, when=datetime(2026, 6, 10),
        )

        revenue = ev(db, "fresh_collective_revenue_cents", JUNE).value
        gross = ev(db, "gross_collective_sales_cents", JUNE).value
        assert gross == 100_00
        # The platform's share only. The creator's 90.00 is not ours.
        assert revenue == 10_00
        assert revenue < gross

    def test_it_sums_its_two_declared_streams_and_says_so(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        self._sale(
            db, space, creator, make_user(),
            gross=100_00, fee=10_00, net=90_00, when=datetime(2026, 6, 10),
        )
        v = ev(db, "fresh_collective_revenue_cents", JUNE)
        fee = ev(db, "platform_fee_revenue_cents", JUNE).value
        subs = ev(db, "subscription_revenue_cents", JUNE).value
        assert v.value == (fee or 0) + (subs or 0)
        assert v.qualifiers["components"] == {
            "platform_fee_revenue_cents": fee,
            "subscription_revenue_cents": subs,
        }

    def test_contribution_is_this_less_processing(
        self, db, make_user, make_space,
    ):
        """The two money metrics must agree, not drift."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, reporting_class=PRODUCTION)
        self._sale(
            db, space, creator, make_user(),
            gross=100_00, fee=10_00, net=90_00, when=datetime(2026, 6, 10),
        )
        revenue = ev(db, "fresh_collective_revenue_cents", JUNE).value
        costs = ev(db, "processing_costs_cents", JUNE).value
        contribution = ev(db, "contribution_after_processing_cents", JUNE).value
        assert contribution == revenue - costs

    def test_the_ledger_keeps_a_demonstration_sale(
        self, db, make_user, make_space,
    ):
        """Real money moved. Narrowing to production shows a subset."""
        creator = make_user(role="creator")
        demo = make_space(creator=creator, reporting_class=DEMONSTRATION)
        self._sale(
            db, demo, creator, make_user(),
            gross=50_00, fee=5_00, net=45_00, when=datetime(2026, 6, 10),
        )
        complete = ev(db, "fresh_collective_revenue_cents", JUNE).value
        production = ev(
            db, "fresh_collective_revenue_cents", JUNE,
            Population(PopulationView.production),
        ).value
        assert complete == 5_00
        assert production == 0

    def test_it_is_platform_only(self):
        from app.reporting.scope import Access

        assert REGISTRY.get(
            "fresh_collective_revenue_cents"
        ).access is Access.platform_only

    def test_a_creator_scope_is_refused(self, db):
        from app.reporting.scope import Audience, ReportScope, ScopeDenied

        creator = ReportScope(audience=Audience.creator, user_id="u", space_ids=())
        with pytest.raises(ScopeDenied):
            REGISTRY.get("fresh_collective_revenue_cents").evaluate(
                db, creator, JUNE, Population(PopulationView.all),
            )
