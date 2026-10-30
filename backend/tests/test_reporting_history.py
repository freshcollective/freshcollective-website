"""The historical charts: buckets, populations, gaps and provenance.

What these tests are for
------------------------
The nightly job already stored a daily figure per metric. Turning that
into a chart introduces four new ways to publish a confidently wrong
number, and there is a test class per hazard:

* **Folding.** A week is the sum of its days for a flow and the last of
  its days for a snapshot. Getting that backwards produces a membership
  line that climbs by a factor of seven.
* **Boundaries.** Australian days, Monday weeks, 1 July financial years,
  and periods that have not finished yet. A column covering three days
  drawn beside one covering thirty-one is a false collapse.
* **Population.** Two independent classification dimensions, where the
  failure mode is a figure labelled "Production" that is actually
  everything — invisible to the reader by construction.
* **Gaps.** A day nobody rebuilt, a metric that cannot be reconstructed,
  and a genuinely quiet period are three different facts. Only the last
  one is a zero.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.core.periods import (
    DateRange,
    completed_reporting_date,
    group_buckets,
    reporting_date_bounds,
    resolve_history_range,
)
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.models.reporting_aggregate import MetricDaily
from app.reporting import aggregates, history
from app.reporting.classification import (
    DEMONSTRATION,
    INTERNAL_OPERATIONS,
    PRODUCTION,
    TEST,
)
from app.reporting.population import Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope

NOW = datetime(2026, 10, 31, 9, 0)
LAST = completed_reporting_date(NOW)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _join(db, user, space, joined_at=None, removed_at=None, status=None):
    m = SpaceMembership(
        id=_uid("sm"),
        user_id=user.id,
        space_id=space.id,
        role=SpaceRole.learner,
        status=status or SpaceMembershipStatus.active,
        joined_at=joined_at or datetime(2026, 1, 1),
        removed_at=removed_at,
    )
    db.add(m)
    db.flush()
    return m


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
        processing_fee_cents=200,
        stripe_mode="test",
        settled_at=datetime(2026, 10, 20, 3, 0),
    )
    d.update(over)
    t = PaymentTransaction(**d)
    db.add(t)
    db.flush()
    return t


def _store(db, key, day, value, *, provenance="observed", aggregation="additive"):
    db.add(MetricDaily(
        id=_uid("md"),
        metric_key=key,
        reporting_date=day,
        dimension=aggregates.PLATFORM_DIMENSION,
        aggregation=aggregation,
        value=value,
        provenance=provenance,
        computed_at=datetime.utcnow(),
    ))
    db.flush()


def _buckets(start, end, grouping, last_completed=None):
    return group_buckets(
        DateRange("test", start, end), grouping, last_completed or end,
    )


def _series(db, key, buckets, population=None):
    return history.build_series(
        db, key, platform_scope(), buckets,
        population=population or Population(PopulationView.all),
    )


# ---------------------------------------------------------------------------
# Folding daily rows into buckets
# ---------------------------------------------------------------------------

class TestAdditiveAndSnapshotFoldDifferently:
    def test_an_additive_flow_is_summed_across_its_days(self, db):
        for i in range(7):
            _store(db, "memberships_started", date(2026, 10, 5) + timedelta(days=i), 2)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        s = _series(db, "memberships_started", bs)
        assert len(s.points) == 1
        assert s.points[0].value == 14, "seven days of 2 should sum to 14"

    def test_a_snapshot_takes_the_last_day_and_never_the_sum(self, db):
        for i, v in enumerate((10, 11, 12, 13, 14, 15, 16)):
            _store(
                db, "unique_members", date(2026, 10, 5) + timedelta(days=i), v,
                aggregation="snapshot",
            )
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        s = _series(db, "unique_members", bs)
        assert s.points[0].value == 16, (
            "a weekly unique-member figure is the state at the end of the "
            "week, not the sum of seven daily counts"
        )
        assert s.points[0].value != 91

    def test_the_two_metrics_are_declared_the_way_the_fold_assumes(self):
        assert REGISTRY.get("memberships_started").aggregation.value == "additive"
        assert REGISTRY.get("unique_members").aggregation.value == "snapshot"

    def test_monthly_snapshot_is_the_last_day_of_the_month(self, db):
        _store(db, "unique_members", date(2026, 9, 1), 5, aggregation="snapshot")
        _store(db, "unique_members", date(2026, 9, 30), 9, aggregation="snapshot")
        bs = _buckets(date(2026, 9, 1), date(2026, 9, 30), "monthly")
        assert _series(db, "unique_members", bs).points[0].value == 9

    def test_a_non_storable_metric_is_recomputed_rather_than_folded(self, db):
        """A ratio has no stored dailies to add up, and must not be."""
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        s = _series(db, "memberships_per_member", bs)
        assert s.source == "recomputed"
        assert "never stored daily" in (s.qualifiers.get("recompute_note") or "")


# ---------------------------------------------------------------------------
# Boundaries and grouping
# ---------------------------------------------------------------------------

class TestDateBoundariesAndGrouping:
    def test_every_range_ends_on_the_last_completed_australian_day(self):
        for key in ("last_30_days", "last_3_months", "last_12_months", "this_fy"):
            assert resolve_history_range(key, NOW).ends_on == LAST, key

    def test_last_30_days_is_exactly_30_days(self):
        assert resolve_history_range("last_30_days", NOW).days == 30

    def test_months_are_calendar_months_not_fixed_day_counts(self):
        r = resolve_history_range("last_3_months", NOW)
        assert r.starts_on == date(2026, 7, 31)
        assert r.ends_on == date(2026, 10, 30)

    def test_the_financial_year_starts_on_1_july_and_is_labelled_australian(self):
        r = resolve_history_range("this_fy", NOW)
        assert r.starts_on == date(2026, 7, 1)
        assert r.label == "FY 2026-27"

    def test_a_financial_year_boundary_does_not_invert_the_range(self):
        """On 1 July the FY starts after the last completed day."""
        r = resolve_history_range("this_fy", datetime(2026, 7, 1, 9, 0))
        assert r.starts_on <= r.ends_on

    def test_weeks_begin_on_monday(self):
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 18), "weekly")
        assert [b.starts_on for b in bs] == [date(2026, 10, 5), date(2026, 10, 12)]
        assert date(2026, 10, 5).weekday() == 0

    def test_an_unfinished_period_is_marked_incomplete(self):
        bs = _buckets(
            date(2026, 10, 1), date(2026, 10, 15), "monthly",
            last_completed=date(2026, 10, 15),
        )
        assert bs[-1].complete is False

    def test_a_finished_period_is_marked_complete(self):
        bs = _buckets(
            date(2026, 9, 1), date(2026, 9, 30), "monthly",
            last_completed=date(2026, 10, 15),
        )
        assert bs[0].complete is True

    def test_a_bucket_clipped_by_the_range_says_so(self):
        """Three days of a month must not be drawn as a whole month."""
        bs = _buckets(date(2026, 7, 29), date(2026, 8, 31), "monthly")
        assert bs[0].clipped is True
        assert bs[0].days == 3
        assert bs[1].clipped is False
        assert bs[0].partial is True

    def test_buckets_never_reach_outside_the_requested_range(self):
        span_start, span_end = date(2026, 10, 7), date(2026, 10, 20)
        for grouping in ("daily", "weekly", "monthly"):
            for b in _buckets(span_start, span_end, grouping):
                assert b.starts_on >= span_start, grouping
                assert b.ends_on <= span_end, grouping

    def test_buckets_are_contiguous_and_cover_the_range_exactly_once(self):
        bs = _buckets(date(2026, 8, 3), date(2026, 10, 25), "weekly")
        assert bs[0].starts_on == date(2026, 8, 3)
        assert bs[-1].ends_on == date(2026, 10, 25)
        for earlier, later in zip(bs, bs[1:]):
            assert later.starts_on == earlier.ends_on + timedelta(days=1)

    def test_a_bucket_window_uses_australian_midnight_not_utc(self):
        """The UTC instants must match the stored dailies' own bounds."""
        b = _buckets(date(2026, 10, 5), date(2026, 10, 5), "daily")[0]
        w = history._bucket_window(b)
        assert (w.starts_at, w.ends_at) == reporting_date_bounds(date(2026, 10, 5))
        # Sydney is UTC+11 in October, so the local day starts the
        # previous afternoon in UTC. A naive UTC-midnight boundary would
        # put eleven hours of activity in the wrong day.
        assert w.starts_at.hour == 13

    def test_a_dst_transition_day_is_still_one_bucket(self):
        """Sydney springs forward on 4 October 2026 — a 23-hour day."""
        b = _buckets(date(2026, 10, 4), date(2026, 10, 4), "daily")[0]
        w = history._bucket_window(b)
        hours = (w.ends_at - w.starts_at).total_seconds() / 3600
        assert hours == 23, "the short day must not be padded to 24 hours"

    def test_an_invalid_grouping_is_refused(self):
        with pytest.raises(ValueError, match="Unknown grouping"):
            group_buckets(DateRange("x", date(2026, 1, 1), date(2026, 1, 2)), "hourly")

    def test_an_invalid_range_is_refused(self):
        with pytest.raises(ValueError, match="Unknown history range"):
            resolve_history_range("since_forever", NOW)


# ---------------------------------------------------------------------------
# A gap is not a zero
# ---------------------------------------------------------------------------

class TestMissingHistoryIsAGapNotAZero:
    def test_a_bucket_with_no_stored_days_is_unavailable(self, db):
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        p = _series(db, "memberships_started", bs).points[0]
        assert p.value is None
        assert p.available is False
        assert "No figure was recorded" in p.unavailable_reason

    def test_an_observation_only_metric_says_why_it_cannot_be_rebuilt(self, db):
        bs = _buckets(date(2026, 3, 2), date(2026, 3, 8), "weekly")
        p = _series(db, "active_collectives", bs).points[0]
        assert p.value is None
        assert "only be observed on the day" in p.unavailable_reason

    def test_a_partly_stored_bucket_reports_how_many_days_it_has(self, db):
        _store(db, "memberships_started", date(2026, 10, 5), 3)
        _store(db, "memberships_started", date(2026, 10, 6), 4)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        p = _series(db, "memberships_started", bs).points[0]
        assert p.value == 7
        assert (p.days_present, p.days_expected) == (2, 7)
        assert p.partial_data is True

    def test_a_fully_stored_bucket_is_not_flagged_partial(self, db):
        for i in range(7):
            _store(db, "memberships_started", date(2026, 10, 5) + timedelta(days=i), 1)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        p = _series(db, "memberships_started", bs).points[0]
        assert p.partial_data is False
        assert (p.days_present, p.days_expected) == (7, 7)

    def test_a_genuine_zero_is_a_value_not_a_gap(self, db):
        """A quiet week that was rebuilt is zero, and must read as zero."""
        for i in range(7):
            _store(db, "memberships_started", date(2026, 10, 5) + timedelta(days=i), 0)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        p = _series(db, "memberships_started", bs).points[0]
        assert p.value == 0
        assert p.available is True


class TestProvenanceSurvivesAggregation:
    def test_a_week_with_one_reconstructed_day_is_not_an_observed_week(self, db):
        days = [date(2026, 10, 5) + timedelta(days=i) for i in range(7)]
        for d in days:
            _store(db, "memberships_started", d, 1, provenance="observed")
        db.query(MetricDaily).filter(
            MetricDaily.reporting_date == days[3]
        ).update({"provenance": "reconstructed"})
        db.flush()
        bs = _buckets(days[0], days[-1], "weekly")
        assert _series(db, "memberships_started", bs).points[0].provenance == (
            "reconstructed"
        )

    def test_observed_late_outranks_reconstructed_but_not_observed(self, db):
        d0 = date(2026, 10, 5)
        _store(db, "memberships_started", d0, 1, provenance="observed")
        _store(db, "memberships_started", d0 + timedelta(days=1), 1,
               provenance="observed_late")
        bs = _buckets(d0, d0 + timedelta(days=6), "weekly")
        assert _series(db, "memberships_started", bs).points[0].provenance == (
            "observed_late"
        )

    def test_an_all_observed_week_stays_observed(self, db):
        for i in range(7):
            _store(db, "memberships_started", date(2026, 10, 5) + timedelta(days=i), 1)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        assert _series(db, "memberships_started", bs).points[0].provenance == "observed"

    def test_the_fold_knows_every_declared_provenance(self):
        from app.reporting.registry import Provenance
        assert set(history._CONFIDENCE) == {p.value for p in Provenance}, (
            "a new provenance must be ranked here or it folds to None"
        )


# ---------------------------------------------------------------------------
# Classification populations
# ---------------------------------------------------------------------------

class TestPopulationFiltersBothDimensions:
    def _world(self, db, make_user, make_space):
        prod = make_space(reporting_class=PRODUCTION)
        demo = make_space(reporting_class=DEMONSTRATION)
        unclassified = make_space()
        real = make_user()
        fixture = make_user(reporting_class=TEST)
        return prod, demo, unclassified, real, fixture

    def test_a_test_account_does_not_inflate_production_membership(
        self, db, make_user, make_space,
    ):
        """The case the whole feature exists for."""
        prod, _demo, _unc, real, fixture = self._world(db, make_user, make_space)
        _join(db, real, prod)
        _join(db, fixture, prod)

        everything = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.all))
        production = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        assert everything.value == 2
        assert production.value == 1, (
            "a test account in a production Collective must leave the "
            "production member count"
        )

    def test_an_unclassified_account_is_counted_provisionally(
        self, db, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), prod)
        v = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        assert v.value == 1

    def test_the_provisional_inclusion_is_reported_as_a_number(
        self, db, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), prod)
        _join(db, make_user(reporting_class=PRODUCTION), prod)
        v = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        assert v.value == 2
        assert v.qualifiers["unclassified_accounts"] == 1
        assert "provisionally" in v.qualifiers["unclassified_accounts_note"]

    def test_an_unclassified_collective_is_not_folded_into_production(
        self, db, make_user, make_space,
    ):
        unclassified = make_space()
        _join(db, make_user(), unclassified)
        v = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        assert v.value == 0, (
            "classification.py refuses to assume unclassified means "
            "production, and the population filter must not overrule it"
        )

    def test_each_class_can_be_inspected_on_its_own(
        self, db, make_user, make_space,
    ):
        for name in (PRODUCTION, INTERNAL_OPERATIONS, DEMONSTRATION, TEST):
            _join(db, make_user(), make_space(reporting_class=name))
        for name in (INTERNAL_OPERATIONS, DEMONSTRATION, TEST):
            v = REGISTRY.get("unique_members").evaluate(
                db, platform_scope(), Window(), Population.parse(name))
            assert v.value == 1, name

    def test_the_two_dimensions_are_independent(self, db, make_user, make_space):
        """A real account in a demonstration Collective, and the reverse."""
        demo = make_space(reporting_class=DEMONSTRATION)
        prod = make_space(reporting_class=PRODUCTION)
        _join(db, make_user(), demo)
        _join(db, make_user(reporting_class=TEST), prod)
        prod_members = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        demo_members = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window(), Population.parse(DEMONSTRATION))
        assert prod_members.value == 0
        assert demo_members.value == 1

    def test_a_metric_that_cannot_be_narrowed_is_unavailable_not_unfiltered(self, db):
        """The worst available failure, prevented by declaration."""
        m = REGISTRY.get("active_members")
        assert not m.honours_population
        v = m.evaluate(
            db, platform_scope(), Window(), Population(PopulationView.production))
        assert v.value is None
        assert "cannot be narrowed by reporting class" in v.unavailable_reason

    def test_every_growth_and_money_metric_on_the_two_pages_can_be_narrowed(self):
        charted = (
            "unique_members", "total_memberships", "memberships_started",
            "members_in_one_collective", "members_in_two_collectives",
            "members_in_three_plus_collectives", "multi_collective_members",
            "platform_fee_revenue_cents", "subscription_revenue_cents",
            "gross_collective_sales_cents", "creator_earnings_cents",
            "paid_out_cents", "processing_costs_cents",
            "contribution_after_processing_cents", "refunds_cents",
        )
        missing = [k for k in charted if not REGISTRY.get(k).honours_population]
        assert not missing, f"charted but cannot be narrowed: {missing}"

    def test_a_filtered_series_is_recomputed_not_read_from_stored_rows(self, db):
        _store(db, "memberships_started", date(2026, 10, 5), 99)
        bs = _buckets(date(2026, 10, 5), date(2026, 10, 11), "weekly")
        s = _series(db, "memberships_started", bs,
                    Population(PopulationView.production))
        assert s.source == "recomputed"
        assert s.points[0].value != 99, (
            "stored rows cover every Collective, so a production series "
            "must not read them"
        )
        assert "no stored row to read" in s.qualifiers["recompute_note"]


class TestMoneyIsNeverFilteredAwayFromTheLedger:
    def test_a_demonstration_charge_stays_in_the_complete_ledger(
        self, db, make_user, make_space,
    ):
        demo = make_space(reporting_class=DEMONSTRATION)
        creator = make_user(role="creator")
        _txn(db, space=demo, creator=creator, payer=make_user(), gross=5000)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")

        complete = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.all))
        production = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.production))
        assert complete.value == 5000, "real money must remain in the ledger view"
        assert production.value == 0

    def test_the_production_view_says_it_is_a_subset(self, db, make_user, make_space):
        demo = make_space(reporting_class=DEMONSTRATION)
        _txn(db, space=demo, creator=make_user(role="creator"), payer=make_user())
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.production))
        assert "subset of the ledger, not the ledger" in v.qualifiers["population_note"]
        assert v.qualifiers["rows_outside_population"] == 1
        assert "still in the complete ledger" in v.qualifiers["population_empty_note"]

    def test_a_deleted_payer_does_not_drop_a_real_payment(
        self, db, make_user, make_space,
    ):
        """``payer_user_id`` is ON DELETE SET NULL. A bare NOT IN would
        evaluate to NULL for such a row and silently remove it."""
        prod = make_space(reporting_class=PRODUCTION)
        _txn(db, space=prod, creator=make_user(role="creator"),
             payer=make_user(), payer_user_id=None, gross=7000)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        v = REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.production))
        assert v.value == 7000

    def test_a_test_account_purchase_leaves_production_business_performance(
        self, db, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        creator = make_user(role="creator")
        _txn(db, space=prod, creator=creator, payer=make_user(), gross=1000)
        _txn(db, space=prod, creator=creator,
             payer=make_user(reporting_class=TEST), gross=9000)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.all)
        ).value == 10000
        assert REGISTRY.get("gross_collective_sales_cents").evaluate(
            db, platform_scope(), window, Population(PopulationView.production)
        ).value == 1000


class TestFinancialConsistencyUnderAPopulation:
    def test_contribution_is_its_components_under_the_same_population(
        self, db, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        demo = make_space(reporting_class=DEMONSTRATION)
        creator = make_user(role="creator")
        _txn(db, space=prod, creator=creator, payer=make_user(), fee=1500)
        _txn(db, space=demo, creator=creator, payer=make_user(), fee=4000)
        window = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")

        for pop in (PopulationView.all, PopulationView.production):
            p = Population(pop)
            fee = REGISTRY.get("platform_fee_revenue_cents").evaluate(
                db, platform_scope(), window, p).value or 0
            subs = REGISTRY.get("subscription_revenue_cents").evaluate(
                db, platform_scope(), window, p).value or 0
            costs = REGISTRY.get("processing_costs_cents").evaluate(
                db, platform_scope(), window, p).value or 0
            total = REGISTRY.get("contribution_after_processing_cents").evaluate(
                db, platform_scope(), window, p).value
            assert total == fee + subs - costs, pop

    def test_contribution_is_never_called_profit(self):
        m = REGISTRY.get("contribution_after_processing_cents")
        assert "profit" not in m.display_name.lower()
        assert "not" in m.definition.lower() or "excludes" in (
            (m.limitations or "") + m.definition).lower()

    def test_subscription_revenue_is_narrowed_by_account_class_only(self, db):
        m = REGISTRY.get("subscription_revenue_cents")
        v = m.evaluate(
            db, platform_scope(),
            Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct"),
            Population(PopulationView.production))
        assert "account class only" in v.qualifiers["population_basis"]

    def test_refunds_disclose_the_single_refund_date_limitation(self, db):
        v = REGISTRY.get("refunds_cents").evaluate(
            db, platform_scope(),
            Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct"))
        assert "most recent refund date" in v.qualifiers["note"]

    def test_refunds_are_attributed_to_the_refund_date_not_the_sale_date(
        self, db, make_user, make_space,
    ):
        space = make_space(reporting_class=PRODUCTION)
        _txn(
            db, space=space, creator=make_user(role="creator"), payer=make_user(),
            status=PaymentTransactionStatus.refunded,
            settled_at=datetime(2026, 9, 10, 3, 0),
            refunded_amount_cents=5000,
            last_refunded_at=datetime(2026, 10, 10, 3, 0),
        )
        sept = Window(datetime(2026, 9, 1), datetime(2026, 10, 1), "sep")
        octo = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
        assert REGISTRY.get("refunds_cents").evaluate(
            db, platform_scope(), sept).value == 0
        assert REGISTRY.get("refunds_cents").evaluate(
            db, platform_scope(), octo).value == 5000


# ---------------------------------------------------------------------------
# Membership overlap
# ---------------------------------------------------------------------------

class TestOverlapBucketsPartitionTheMembers:
    def _spread(self, db, make_user, make_space):
        spaces = [make_space(reporting_class=PRODUCTION) for _ in range(4)]
        one = make_user()
        two = make_user()
        three = make_user()
        _join(db, one, spaces[0])
        for s in spaces[:2]:
            _join(db, two, s)
        for s in spaces[:3]:
            _join(db, three, s)
        return spaces, (one, two, three)

    def test_each_member_appears_in_exactly_one_bucket(
        self, db, make_user, make_space,
    ):
        self._spread(db, make_user, make_space)
        vals = {
            k: REGISTRY.get(k).evaluate(db, platform_scope(), Window()).value
            for k in (
                "members_in_one_collective",
                "members_in_two_collectives",
                "members_in_three_plus_collectives",
            )
        }
        assert vals == {
            "members_in_one_collective": 1,
            "members_in_two_collectives": 1,
            "members_in_three_plus_collectives": 1,
        }

    def test_the_buckets_sum_to_unique_members(self, db, make_user, make_space):
        self._spread(db, make_user, make_space)
        total = REGISTRY.get("unique_members").evaluate(
            db, platform_scope(), Window()).value
        buckets = sum(
            REGISTRY.get(k).evaluate(db, platform_scope(), Window()).value
            for k in (
                "members_in_one_collective",
                "members_in_two_collectives",
                "members_in_three_plus_collectives",
            )
        )
        assert buckets == total == 3

    def test_overlap_is_reconstructed_as_at_a_past_date(
        self, db, make_user, make_space,
    ):
        """The fix: this family used to ignore the window entirely."""
        a, b = make_space(reporting_class=PRODUCTION), make_space(
            reporting_class=PRODUCTION)
        person = make_user()
        _join(db, person, a, joined_at=datetime(2026, 1, 10))
        _join(db, person, b, joined_at=datetime(2026, 6, 10))

        march = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "mar")
        july = Window(datetime(2026, 7, 1), datetime(2026, 8, 1), "jul")
        key = "members_in_one_collective"
        assert REGISTRY.get(key).evaluate(db, platform_scope(), march).value == 1
        assert REGISTRY.get(key).evaluate(db, platform_scope(), july).value == 0
        assert REGISTRY.get("members_in_two_collectives").evaluate(
            db, platform_scope(), july).value == 1

    def test_multi_collective_members_agrees_with_the_buckets(
        self, db, make_user, make_space,
    ):
        self._spread(db, make_user, make_space)
        multi = REGISTRY.get("multi_collective_members").evaluate(
            db, platform_scope(), Window())
        assert multi.value == 2
        assert multi.qualifiers["buckets"] == {
            "one": 1, "two": 1, "three_plus": 1,
        }

    def test_overlap_counts_only_collectives_inside_the_population(
        self, db, make_user, make_space,
    ):
        prod = make_space(reporting_class=PRODUCTION)
        demo = make_space(reporting_class=DEMONSTRATION)
        person = make_user()
        _join(db, person, prod)
        _join(db, person, demo)
        production = Population(PopulationView.production)
        assert REGISTRY.get("members_in_one_collective").evaluate(
            db, platform_scope(), Window(), production).value == 1, (
            "within the production population this person belongs to one "
            "production Collective, not two"
        )
        assert REGISTRY.get("members_in_two_collectives").evaluate(
            db, platform_scope(), Window(), Population(PopulationView.all)
        ).value == 1

    def test_a_removed_membership_leaves_the_bucket_at_a_later_date(
        self, db, make_user, make_space,
    ):
        a, b = make_space(reporting_class=PRODUCTION), make_space(
            reporting_class=PRODUCTION)
        person = make_user()
        _join(db, person, a, joined_at=datetime(2026, 1, 10))
        _join(db, person, b, joined_at=datetime(2026, 1, 10),
              removed_at=datetime(2026, 5, 1),
              status=SpaceMembershipStatus.removed)
        march = Window(datetime(2026, 3, 1), datetime(2026, 4, 1), "mar")
        july = Window(datetime(2026, 7, 1), datetime(2026, 8, 1), "jul")
        assert REGISTRY.get("members_in_two_collectives").evaluate(
            db, platform_scope(), march).value == 1
        assert REGISTRY.get("members_in_one_collective").evaluate(
            db, platform_scope(), july).value == 1

    def test_the_buckets_are_snapshots_so_a_week_is_never_their_sum(self):
        for k in (
            "members_in_one_collective", "members_in_two_collectives",
            "members_in_three_plus_collectives", "multi_collective_members",
        ):
            assert REGISTRY.get(k).aggregation.value == "snapshot", k


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------

import pytest as _pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth.dependencies import get_admin_user, get_current_user  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402

HISTORY = "/api/admin/reporting/history"


@_pytest.fixture
def client(db, make_user):
    admin = make_user(role="admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestTheHistoryEndpoint:
    def test_it_returns_a_series_per_requested_metric(self, client):
        r = client.get(HISTORY, params={
            "keys": "unique_members,memberships_started",
            "range": "last_3_months", "grouping": "monthly",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert [s["key"] for s in body["series"]] == [
            "unique_members", "memberships_started",
        ]

    def test_points_align_one_to_one_with_the_buckets(self, client):
        body = client.get(HISTORY, params={
            "keys": "unique_members", "range": "last_30_days",
            "grouping": "weekly",
        }).json()
        labels = [b["label"] for b in body["buckets"]]
        for s in body["series"]:
            assert [p["label"] for p in s["points"]] == labels

    def test_the_definition_and_limitations_travel_with_the_series(self, client):
        body = client.get(HISTORY, params={"keys": "total_memberships"}).json()
        s = body["series"][0]
        assert s["definition"]
        assert s["limitations"], (
            "the registry's limitation must reach the chart, not stay in "
            "the backend"
        )

    def test_the_population_note_is_returned_for_display(self, client):
        body = client.get(HISTORY, params={
            "keys": "unique_members", "population": "production",
        }).json()
        assert body["population"]["key"] == "production"
        assert "Unclassified Collectives are excluded" in body["population"]["note"]

    def test_the_default_population_is_the_complete_ledger(self, client):
        body = client.get(HISTORY, params={"keys": "unique_members"}).json()
        assert body["population"]["key"] == "all"

    def test_control_options_come_from_the_backend_vocabularies(self, client):
        body = client.get(HISTORY, params={"keys": "unique_members"}).json()
        opts = body["options"]
        assert [r["key"] for r in opts["ranges"]] == [
            "last_30_days", "last_3_months", "last_12_months",
            "this_fy", "all_time",
        ]
        assert opts["groupings"] == ["daily", "weekly", "monthly"]
        assert {p["key"] for p in opts["populations"]} == {
            "all", "production", "internal_operations", "demonstration",
            "test", "unclassified",
        }
        assert all(p["note"] for p in opts["populations"])

    def test_incomplete_and_clipped_buckets_are_flagged_in_the_payload(self, client):
        body = client.get(HISTORY, params={
            "keys": "memberships_started", "range": "last_3_months",
            "grouping": "monthly",
        }).json()
        assert any(not b["complete"] or b["clipped"] for b in body["buckets"]), (
            "a three-month range grouped monthly always has a partial end"
        )

    def test_an_unknown_metric_is_404(self, client):
        assert client.get(HISTORY, params={"keys": "vibes"}).status_code == 404

    def test_an_unknown_range_is_422(self, client):
        r = client.get(HISTORY, params={"keys": "unique_members", "range": "ever"})
        assert r.status_code == 422
        assert "Valid:" in r.json()["detail"]

    def test_an_unknown_grouping_is_422(self, client):
        r = client.get(HISTORY, params={
            "keys": "unique_members", "grouping": "hourly"})
        assert r.status_code == 422

    def test_an_unknown_population_is_422(self, client):
        r = client.get(HISTORY, params={
            "keys": "unique_members", "population": "pretend"})
        assert r.status_code == 422

    def test_no_keys_is_422(self, client):
        assert client.get(HISTORY, params={"keys": " "}).status_code == 422

    def test_too_many_buckets_names_a_coarser_grouping_rather_than_truncating(
        self, client,
    ):
        r = client.get(HISTORY, params={
            "keys": "unique_members", "range": "last_12_months",
            "grouping": "daily",
        })
        if r.status_code == 422:
            assert "Group by weekly instead" in r.json()["detail"]
        else:
            # Fewer stored days than a year, so the range collapsed.
            assert len(r.json()["buckets"]) <= history.MAX_BUCKETS

    def test_a_metric_that_cannot_be_narrowed_reports_a_reason_per_point(
        self, client,
    ):
        body = client.get(HISTORY, params={
            "keys": "active_members", "population": "production",
            "range": "last_30_days", "grouping": "weekly",
        }).json()
        points = body["series"][0]["points"]
        assert points, "the series must still have buckets to draw a gap in"
        assert all(p["value"] is None for p in points)
        assert all(
            "cannot be narrowed by reporting class" in p["unavailable_reason"]
            for p in points
        )
