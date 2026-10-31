"""One definition per metric, and the guards that keep it that way.

Three things are worth protecting here, and they are the three ways a
reporting system starts lying:

* **Attribution.** A sale belongs to the period it settled in, a refund
  to the period the money went back, a payout to the period it was paid.
  One timestamp for all three is what made two existing endpoints
  disagree about the same payment.
* **Aggregation.** Thirty daily unique-member counts do not make a
  monthly one. The registry declares which metrics add up and refuses to
  add the ones that do not.
* **Entitlement.** A creator may see their own members and earnings and
  must never see Fresh Collective's platform fee revenue or another
  creator's anything. That is enforced before the SQL runs, not by the
  caller remembering a filter.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

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
    PayoutStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    NonAdditiveMetric,
    Window,
    aggregate_across,
)
from app.reporting.scope import (
    Access,
    Audience,
    ScopeDenied,
    creator_scope,
    platform_scope,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


ALL_TIME = Window()


def val(db, key, scope=None, window=ALL_TIME):
    return REGISTRY.get(key).evaluate(db, scope or platform_scope(), window)


def _txn(db, *, space, creator, payer, gross=10000, fee=1000, net=9000, **over):
    d = dict(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=payer.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=1000,
        platform_fee_cents=fee,
        net_creator_amount_cents=net,
        stripe_mode="test",
    )
    d.update(over)
    t = PaymentTransaction(**d)
    db.add(t)
    db.flush()
    return t


def _join(db, user, space, role=SpaceRole.learner, joined_at=None):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id, role=role,
        status=SpaceMembershipStatus.active,
        joined_at=joined_at or datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------

class TestEveryMetricIsFullyDeclared:
    def test_each_metric_carries_all_ten_required_properties(self):
        """The contract: a number is never served without its meaning."""
        for m in REGISTRY.all():
            assert m.key and m.display_name, m.key
            assert m.definition and len(m.definition) > 30, (
                f"{m.key} needs a real business definition"
            )
            assert m.source_of_truth, m.key
            assert isinstance(m.grain, Grain), m.key
            assert isinstance(m.aggregation, Aggregation), m.key
            assert isinstance(m.date_basis, DateBasis), m.key
            assert isinstance(m.access, Access), m.key
            assert isinstance(m.availability, Availability), m.key
            assert m.compute is not None, f"{m.key} has no calculation"

    def test_a_partial_metric_explains_its_limitation(self):
        for m in REGISTRY.all():
            if m.availability is Availability.partial:
                assert m.limitations, (
                    f"{m.key} is partial but says nothing about why"
                )

    def test_non_additive_metrics_say_so(self):
        for m in REGISTRY.all():
            if m.aggregation in (Aggregation.distinct_count, Aggregation.ratio):
                assert m.limitations is not None or m.grain is Grain.snapshot, (
                    f"{m.key} is {m.aggregation.value} and should warn about it"
                )

    def test_keys_are_unique(self):
        assert len({m.key for m in REGISTRY.all()}) == len(REGISTRY)


# ---------------------------------------------------------------------------
# Aggregation behaviour
# ---------------------------------------------------------------------------

class TestAggregationRules:
    def test_money_adds_up(self):
        m = REGISTRY.get("gross_collective_sales_cents")
        assert aggregate_across(m, [100, 200, 300]) == 600

    def test_daily_active_members_cannot_be_summed_into_a_month(self):
        """The single easiest way to publish a confidently wrong number.

        ``active_members`` is a distinct count of people who did
        something, so thirty daily values do not make a month: the same
        person appears on many days.
        """
        m = REGISTRY.get("active_members")
        with pytest.raises(NonAdditiveMetric):
            aggregate_across(m, [5, 5, 5])

    def test_a_membership_snapshot_takes_the_latest_not_the_sum(self):
        """``unique_members`` is a snapshot — "how many, as at when" —
        so combining periods means taking the most recent, never adding."""
        m = REGISTRY.get("unique_members")
        assert aggregate_across(m, [10, 12, 11]) == 11

    def test_memberships_started_is_the_additive_flow(self):
        """The flow beside the snapshot, and it does add up."""
        m = REGISTRY.get("memberships_started")
        assert aggregate_across(m, [2, 3, 4]) == 9

    def test_a_ratio_cannot_be_summed(self):
        with pytest.raises(NonAdditiveMetric):
            aggregate_across(REGISTRY.get("memberships_per_member"), [1.5, 2.0])

    def test_a_snapshot_takes_the_latest(self):
        m = REGISTRY.get("outstanding_payouts_cents")
        assert aggregate_across(m, [100, 200, 50]) == 50


# ---------------------------------------------------------------------------
# People — the correction
# ---------------------------------------------------------------------------

class TestMembershipCounting:
    def test_one_person_in_three_collectives_is_one_member_and_three_memberships(
        self, db, make_user, make_space,
    ):
        """The distinction the old role-derived count could not make."""
        person = make_user()
        for _ in range(3):
            _join(db, person, make_space(creator=make_user(role="creator")))
        db.flush()
        assert val(db, "unique_members").value == 1
        assert val(db, "total_memberships").value == 3
        assert val(db, "memberships_per_member").value == 3.0

    def test_a_creator_who_joins_elsewhere_counts_as_a_member(
        self, db, make_user, make_space,
    ):
        """Role-derived counting excluded exactly this person."""
        creator = make_user(role="creator")
        other = make_space(creator=make_user(role="creator"))
        _join(db, creator, other)
        db.flush()
        assert val(db, "unique_members").value == 1
        assert val(db, "registered_creators").value >= 1

    def test_a_registered_user_who_joined_nothing_is_not_a_member(
        self, db, make_user,
    ):
        """And role-derived counting included exactly this person."""
        make_user()
        db.flush()
        assert val(db, "registered_users").value >= 1
        assert val(db, "unique_members").value == 0

    def test_multi_collective_members_counts_people_not_memberships(
        self, db, make_user, make_space,
    ):
        a, b = make_space(creator=make_user(role="creator")), make_space(
            creator=make_user(role="creator"))
        both, one = make_user(), make_user()
        _join(db, both, a); _join(db, both, b); _join(db, one, a)
        db.flush()
        assert val(db, "multi_collective_members").value == 1

    def test_a_removed_membership_stops_counting(self, db, make_user, make_space):
        space = make_space(creator=make_user(role="creator"))
        m = _join(db, make_user(), space)
        assert val(db, "unique_members").value == 1
        m.status = SpaceMembershipStatus.removed
        db.flush()
        assert val(db, "unique_members").value == 0

    def test_the_average_is_unavailable_rather_than_zero_with_no_members(self, db):
        v = val(db, "memberships_per_member")
        assert v.value is None
        assert v.available is False
        assert "no members" in v.unavailable_reason.lower()


# ---------------------------------------------------------------------------
# Financial attribution
# ---------------------------------------------------------------------------

class TestFinancialAttribution:
    def test_a_sale_lands_in_the_period_it_settled(
        self, db, make_user, make_space,
    ):
        """Not the period its row was created, nor last touched."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        payer = make_user()
        created = datetime(2026, 1, 10)
        settled = datetime(2026, 2, 15)
        _txn(
            db, space=space, creator=creator, payer=payer,
            created_at=created, settled_at=settled, settled_at_source="observed",
        )
        db.flush()

        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "gross_collective_sales_cents", window=jan).value == 0
        assert val(db, "gross_collective_sales_cents", window=feb).value == 10000

    def test_a_later_touch_does_not_move_a_sale(self, db, make_user, make_space):
        """The exact defect: ``updated_at`` moved historical revenue."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        settled = datetime(2026, 2, 15)
        t = _txn(
            db, space=space, creator=creator, payer=make_user(),
            created_at=settled, settled_at=settled, settled_at_source="observed",
        )
        db.flush()
        t.updated_at = datetime.utcnow()  # a refund, a payout mark, a fee backfill
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "gross_collective_sales_cents", window=feb).value == 10000

    def test_history_without_a_settlement_date_is_flagged_not_hidden(
        self, db, make_user, make_space,
    ):
        """A pre-BI-1 payment still counts, and the result says how."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(
            db, space=space, creator=creator, payer=make_user(),
            created_at=datetime(2025, 6, 1), settled_at=None,
        )
        db.flush()
        v = val(db, "gross_collective_sales_cents")
        assert v.value == 10000
        assert v.qualifiers["settlement_basis"] == "approximate"
        assert v.qualifiers["approximated_rows"] == 1
        assert "approximation_note" in v.qualifiers

    def test_a_window_spanning_the_boundary_reports_mixed(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             created_at=datetime(2026, 3, 2), settled_at=None)
        _txn(db, space=space, creator=creator, payer=make_user(),
             created_at=datetime(2026, 3, 3), settled_at=datetime(2026, 3, 3),
             settled_at_source="observed")
        db.flush()
        v = val(db, "gross_collective_sales_cents")
        assert v.qualifiers["settlement_basis"] == "mixed"
        assert v.qualifiers["observed_rows"] == 1
        assert v.qualifiers["approximated_rows"] == 1

    def test_a_refund_is_attributed_to_the_refund_date(
        self, db, make_user, make_space,
    ):
        """So a closed month's figures do not move afterwards."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(
            db, space=space, creator=creator, payer=make_user(),
            created_at=datetime(2026, 1, 5),
            settled_at=datetime(2026, 1, 5), settled_at_source="observed",
            status=PaymentTransactionStatus.partially_refunded,
            refunded_amount_cents=2500,
            last_refunded_at=datetime(2026, 3, 20),
        )
        db.flush()
        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        mar = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "Mar")
        assert val(db, "refunds_cents", window=jan).value == 0
        assert val(db, "refunds_cents", window=mar).value == 2500
        # The sale itself stays in January.
        assert val(db, "gross_collective_sales_cents", window=jan).value == 10000

    def test_a_payout_is_attributed_to_when_it_was_paid(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(
            db, space=space, creator=creator, payer=make_user(),
            created_at=datetime(2026, 1, 5),
            settled_at=datetime(2026, 1, 5), settled_at_source="observed",
            payout_status=PayoutStatus.paid,
            payout_marked_at=datetime(2026, 4, 2),
        )
        db.flush()
        apr = Window(datetime(2026, 4, 1), datetime(2026, 5, 1), "Apr")
        jan = Window(datetime(2026, 1, 1), datetime(2026, 2, 1), "Jan")
        assert val(db, "paid_out_cents", window=apr).value == 9000
        assert val(db, "paid_out_cents", window=jan).value == 0

    def test_earnings_and_paid_out_are_different_questions(
        self, db, make_user, make_space,
    ):
        """Earned is an obligation; paid out is a cash movement."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed",
             payout_status=PayoutStatus.pending)
        db.flush()
        assert val(db, "creator_earnings_cents").value == 9000
        assert val(db, "paid_out_cents").value == 0
        assert val(db, "outstanding_payouts_cents").value == 9000

    def test_gross_volume_is_not_fresh_collective_revenue(
        self, db, make_user, make_space,
    ):
        """The distinction that must never collapse."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed")
        db.flush()
        assert val(db, "gross_collective_sales_cents").value == 10000
        assert val(db, "platform_fee_revenue_cents").value == 1000
        assert val(db, "creator_earnings_cents").value == 9000

    def test_processing_costs_exclude_and_count_unknown_fees(
        self, db, make_user, make_space,
    ):
        """NULL means Stripe has not reported it — never estimated."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed",
             processing_fee_cents=320)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed",
             processing_fee_cents=None)
        db.flush()
        v = val(db, "processing_costs_cents")
        assert v.value == 320
        assert v.qualifiers["rows_without_a_known_fee"] == 1
        assert "lower bound" in v.qualifiers["fee_note"]

    def test_contribution_shows_its_components_and_refuses_the_word_profit(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed",
             processing_fee_cents=300)
        db.flush()
        v = val(db, "contribution_after_processing_cents")
        assert v.value == 1000 - 300
        assert set(v.qualifiers["components"]) == {
            "platform_fee_revenue_cents",
            "subscription_revenue_cents",
            "processing_costs_cents",
        }
        assert "not profit" in v.qualifiers["not_net_profit"].lower()
        m = REGISTRY.get("contribution_after_processing_cents")
        assert "NOT net profit" in m.definition

    def test_creator_subscription_revenue_is_not_gross_sales(
        self, db, make_user, make_space,
    ):
        """A creator's plan fee is FC's revenue, not Collective volume."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _txn(
            db, space=space, creator=creator, payer=creator,
            transaction_type=PaymentTransactionType.creator_subscription_payment,
            gross=4900, fee=0, net=0,
            settled_at=datetime.utcnow(), settled_at_source="observed",
        )
        db.flush()
        assert val(db, "subscription_revenue_cents").value == 4900
        assert val(db, "gross_collective_sales_cents").value == 0


# ---------------------------------------------------------------------------
# Scope — the Creator Studio foundation
# ---------------------------------------------------------------------------

class TestScopeEnforcement:
    def test_a_creator_scope_cannot_see_platform_fee_revenue(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _join(db, creator, space, role=SpaceRole.creator)
        db.commit()
        scope = creator_scope(db, creator.id)
        with pytest.raises(ScopeDenied):
            REGISTRY.get("platform_fee_revenue_cents").evaluate(db, scope, ALL_TIME)

    def test_a_creator_scope_may_see_their_own_earnings(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _join(db, creator, space, role=SpaceRole.creator)
        _txn(db, space=space, creator=creator, payer=make_user(),
             settled_at=datetime.utcnow(), settled_at_source="observed")
        db.commit()
        scope = creator_scope(db, creator.id)
        assert REGISTRY.get("creator_earnings_cents").evaluate(
            db, scope, ALL_TIME).value == 9000

    def test_one_creator_never_sees_another_creators_sales(
        self, db, make_user, make_space,
    ):
        """The property the whole scope mechanism exists for."""
        a, b = make_user(role="creator"), make_user(role="creator")
        a_space, b_space = make_space(creator=a), make_space(creator=b)
        _join(db, a, a_space, role=SpaceRole.creator)
        _join(db, b, b_space, role=SpaceRole.creator)
        _txn(db, space=a_space, creator=a, payer=make_user(), gross=5000,
             settled_at=datetime.utcnow(), settled_at_source="observed")
        _txn(db, space=b_space, creator=b, payer=make_user(), gross=7000,
             settled_at=datetime.utcnow(), settled_at_source="observed")
        db.commit()

        a_scope = creator_scope(db, a.id)
        assert REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, a_scope, ALL_TIME).value == 5000
        # And the platform sees both.
        assert val(db, "gross_collective_sales_cents").value == 12000

    def test_a_creator_managing_nothing_gets_zero_not_everything(
        self, db, make_user, make_space,
    ):
        """The failure mode an unfiltered query would produce."""
        stranger = make_user(role="creator")
        other = make_space(creator=make_user(role="creator"))
        _txn(db, space=other, creator=other.creator_id and make_user(role="creator"),
             payer=make_user(), gross=9999,
             settled_at=datetime.utcnow(), settled_at_source="observed")
        db.commit()
        scope = creator_scope(db, stranger.id)
        assert scope.space_ids == ()
        assert REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, scope, ALL_TIME).value == 0
        assert REGISTRY.get("unique_members").evaluate(db, scope, ALL_TIME).value == 0

    def test_a_moderator_is_scoped_to_what_they_moderate(
        self, db, make_user, make_space,
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        mod = make_user(role="creator")
        _join(db, mod, space, role=SpaceRole.moderator)
        db.commit()
        assert creator_scope(db, mod.id).space_ids == (space.id,)

    def test_multiple_collectives_do_not_double_count_a_shared_member(
        self, db, make_user, make_space,
    ):
        """A creator with two Collectives and one person in both."""
        creator = make_user(role="creator")
        a, b = make_space(creator=creator), make_space(creator=creator)
        _join(db, creator, a, role=SpaceRole.creator)
        _join(db, creator, b, role=SpaceRole.creator)
        shared = make_user()
        _join(db, shared, a); _join(db, shared, b)
        db.commit()
        scope = creator_scope(db, creator.id)
        # creator + shared = 2 unique people; 4 memberships.
        assert REGISTRY.get("unique_members").evaluate(db, scope, ALL_TIME).value == 2
        assert REGISTRY.get("total_memberships").evaluate(db, scope, ALL_TIME).value == 4

    def test_the_catalogue_hides_platform_only_metrics_from_a_creator(
        self, db, make_user,
    ):
        scope = creator_scope(db, make_user(role="creator").id)
        keys = {m.key for m in REGISTRY.visible_to(scope)}
        assert "platform_fee_revenue_cents" not in keys
        assert "subscription_revenue_cents" not in keys
        assert "contribution_after_processing_cents" not in keys
        assert "registered_users" not in keys
        assert "creator_earnings_cents" in keys
        assert "unique_members" in keys

    def test_platform_only_metrics_are_the_commercially_sensitive_ones(self):
        """A deliberate list, so a new metric cannot default to visible
        without somebody choosing that."""
        platform_only = {
            m.key for m in REGISTRY.all() if m.access is Access.platform_only
        }
        assert platform_only == {
            # Fresh Collective's own money, and platform-wide counts.
            "platform_fee_revenue_cents",
            "subscription_revenue_cents",
            "processing_costs_cents",
            "contribution_after_processing_cents",
            "registered_users",
            "registered_creators",
            # Engagement that is only meaningful across the whole platform,
            # or that would tell one creator about others.
            "active_creators",
            "overlap_vs_engagement",
            "engagement_by_theme",
            "retention_cohorts",
            # The creator journey. Platform-only for both reasons at
            # once: each stage is a count across every creator, and
            # telling one creator how many others reached the stage
            # they are stuck at is exactly the cross-creator comparison
            # this access level exists to prevent.
            "creator_accounts",
            "creators_registered",
            "creators_with_a_collective",
            "creators_with_a_member",
            "creators_earning",
            # Belonging. Platform-only because both are statements
            # about people across every Collective at once: who left
            # Fresh Collective rather than one of its communities, and
            # who is active in more than one. Either would tell a
            # creator about Collectives that are not theirs.
            "members_leaving_entirely",
            "multi_collective_participants",
        }

    def test_no_metric_reads_a_member_authored_column(self):
        """Counts and amounts only — never what anybody wrote.

        Checks ``source_of_truth``, which names the actual columns, and
        deliberately not the prose: a blunt substring scan over the
        definitions fails on "somebody" containing "body", which bans
        the word rather than the thing.
        """
        forbidden_columns = (
            "reflection_text",
            "exercise_responses",
            "direct_messages",
            "community_posts.body",
            "post_comments.body",
            "removal_reason",
            "removal_note",
            "community_care_case_notes",
            "password_hash",
        )
        for m in REGISTRY.all():
            src = m.source_of_truth.lower()
            for col in forbidden_columns:
                assert col not in src, f"{m.key} reads {col}"

    def test_no_metric_reads_a_member_authored_column_in_its_sql(self):
        """The same guarantee at the implementation level."""
        import inspect

        for m in REGISTRY.all():
            src = inspect.getsource(m.compute).lower()
            for col in (
                "reflection_text", "exerciseresponse", "directmessage",
                "removal_note", "password_hash", "casenote",
            ):
                assert col not in src, f"{m.key}'s calculation touches {col}"


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin(make_user):
    return make_user(role="admin")


def as_admin(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_admin_user] = lambda: user


class TestReportingApi:
    def test_the_catalogue_lists_every_metric_with_its_definition(
        self, client, admin,
    ):
        as_admin(admin)
        res = client.get("/api/admin/reporting/metrics")
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body) == len(REGISTRY)
        for row in body:
            for k in (
                "key", "display_name", "definition", "source_of_truth", "grain",
                "aggregation", "date_basis", "access", "availability",
            ):
                assert k in row, k

    def test_a_value_arrives_with_its_definition(self, client, admin):
        as_admin(admin)
        res = client.get(
            "/api/admin/reporting/query"
            "?keys=unique_members,total_memberships&period=this_month"
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["metrics"]) == 2
        for m in body["metrics"]:
            assert m["definition"]["definition"]
            assert m["definition"]["date_basis"]

    def test_it_returns_a_previous_period_for_comparison(self, client, admin):
        as_admin(admin)
        body = client.get(
            "/api/admin/reporting/query?keys=unique_members&period=this_month"
        ).json()
        assert body["comparison"] is not None
        assert body["comparison_metrics"] is not None

    def test_all_time_has_no_comparison_rather_than_a_fake_zero(
        self, client, admin,
    ):
        as_admin(admin)
        body = client.get(
            "/api/admin/reporting/query?keys=unique_members&period=all_time"
        ).json()
        assert body["comparison"] is None
        assert body["comparison_metrics"] is None

    def test_an_unknown_metric_is_a_404(self, client, admin):
        as_admin(admin)
        assert client.get(
            "/api/admin/reporting/query?keys=invented_metric"
        ).status_code == 404

    def test_an_invalid_period_is_a_422(self, client, admin):
        as_admin(admin)
        assert client.get(
            "/api/admin/reporting/query?keys=unique_members&period=yesterdayish"
        ).status_code == 422

    def test_every_reporting_route_requires_an_admin(self, client, make_user):
        app.dependency_overrides[get_current_user] = lambda: make_user(role="creator")
        for path in (
            "/api/admin/reporting/metrics",
            "/api/admin/reporting/query?keys=unique_members",
            "/api/admin/reporting/health",
        ):
            assert client.get(path).status_code in (401, 403), path


class TestRecordingHealthEndpoint:
    """No Render Shell required, ever again."""

    def test_it_reports_the_recorder_state_and_counts(self, client, admin):
        as_admin(admin)
        res = client.get("/api/admin/reporting/health")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["recording_enabled"] is True
        assert "event_counts_by_type" in body
        assert "collective.themes_changed" in body["event_counts_by_type"]
        assert isinstance(body["events_total"], int)

    def test_with_no_events_it_says_recording_has_not_started(
        self, client, admin, db,
    ):
        from sqlalchemy import text

        db.execute(text("DELETE FROM business_events"))
        db.flush()
        as_admin(admin)
        body = client.get("/api/admin/reporting/health").json()
        assert body["activation_floor"] is None
        assert body["ok"] is True
        assert "No events recorded yet" in body["note"]

    def test_a_disabled_recorder_is_reported_loudly(
        self, client, admin, monkeypatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "business_events_enabled", False)
        as_admin(admin)
        body = client.get("/api/admin/reporting/health").json()
        assert body["recording_enabled"] is False
        assert "DISABLED" in body["note"]

    def test_it_surfaces_reconciliation_checks(self, client, admin, db, make_user, make_space):
        from app.services import business_events as be

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        m = _join(db, make_user(), space)
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        db.flush()
        as_admin(admin)
        body = client.get("/api/admin/reporting/health").json()
        assert body["activation_floor"] is not None
        names = {c["name"] for c in body["checks"]}
        assert "memberships_without_a_start_event" in names
        assert "succeeded_payments_without_a_settlement" in names


class TestSnapshotsVersusFlows:
    """The distinction the aggregates depend on.

    BI-2 declared four metrics as snapshots while filtering them by a
    join or creation date, which made them flows the moment a period was
    supplied: ``/reporting/query?period=this_month&keys=unique_members``
    returned members who *joined* this month under the label "Unique
    members". These tests pin the corrected semantics, because the daily
    aggregate loader stores snapshots and flows differently and a
    mislabelled metric would be stored the wrong way.
    """

    def test_a_snapshot_counts_everyone_present_not_everyone_who_joined(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        old_member, new_member = make_user(), make_user()
        _join(db, old_member, space, joined_at=datetime(2026, 1, 5))
        _join(db, new_member, space, joined_at=datetime(2026, 3, 5))
        db.flush()

        march = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "Mar")
        # Both are members as at the end of March...
        assert val(db, "unique_members", window=march).value == 2
        # ...but only one joined during it.
        assert val(db, "memberships_started", window=march).value == 1

    def test_a_snapshot_before_somebody_joined_does_not_count_them(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        _join(db, make_user(), space, joined_at=datetime(2026, 3, 5))
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        assert val(db, "unique_members", window=feb).value == 0

    def test_a_departure_removes_them_from_later_snapshots_only(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        m = _join(db, make_user(), space, joined_at=datetime(2026, 1, 10))
        m.status = SpaceMembershipStatus.removed
        m.removed_at = datetime(2026, 3, 10)
        db.flush()
        feb = Window(datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")
        apr = Window(datetime(2026, 4, 1), datetime(2026, 5, 1), "Apr")
        assert val(db, "unique_members", window=feb).value == 1
        assert val(db, "unique_members", window=apr).value == 0

    def test_a_removal_with_no_date_is_excluded_from_every_snapshot(
        self, db, make_user, make_space,
    ):
        """We know it ended; we do not know when.

        Legacy rows predating the removal-provenance migration look like
        this, and counting them as present would be the wrong guess.
        """
        space = make_space(creator=make_user(role="creator"))
        m = _join(db, make_user(), space, joined_at=datetime(2026, 1, 10))
        m.status = SpaceMembershipStatus.removed
        m.removed_at = None
        db.flush()
        assert val(db, "unique_members").value == 0
        assert val(db, "unique_members", window=Window(
            datetime(2026, 2, 1), datetime(2026, 3, 1), "Feb")).value == 0

    def test_a_now_snapshot_counts_a_row_created_moments_ago(
        self, db, make_user,
    ):
        """``users.created_at`` is ``timestamp(3)``, so the stored value
        rounds and can read as marginally later than ``now()``. A "now"
        snapshot therefore applies no date predicate at all — every row
        that exists, exists now. This metric reported zero before that."""
        make_user()
        db.flush()
        v = val(db, "registered_users")
        assert v.value >= 1, (
            "a 'now' snapshot must not exclude a row created moments ago — "
            "users.created_at is timestamp(3) and rounds, so a date "
            "predicate against now() can place it in the future"
        )
        assert v.qualifiers["as_at"] == "now"

    def test_every_snapshot_metric_declares_snapshot_aggregation(self):
        """So the aggregate loader cannot store one as a flow."""
        from app.reporting.registry import Grain

        for m in REGISTRY.all():
            if m.grain is Grain.snapshot:
                assert m.aggregation is not Aggregation.additive, (
                    f"{m.key} is a snapshot declared additive — the daily "
                    "loader would store it as a flow and somebody would sum it"
                )

    def test_no_snapshot_metric_attributes_by_a_row_date(self):
        """A snapshot narrows the measurement date, not the rows."""
        from app.reporting.registry import DateBasis, Grain

        for m in REGISTRY.all():
            if m.grain is Grain.snapshot:
                assert m.date_basis is DateBasis.none, (
                    f"{m.key} is a snapshot but attributes by "
                    f"{m.date_basis.value}, which makes it a flow"
                )
