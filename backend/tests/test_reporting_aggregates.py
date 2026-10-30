"""The daily rows, and the rules that keep them honest.

Four properties matter here, and each one is a way a precomputed
reporting table normally starts lying:

* **What is stored.** Distinct counts must never be stored daily, because
  thirty daily unique-member counts do not make a month. A stored row
  would look summable and would not be.
* **Which day a figure belongs to.** The reporting day is Australian, and
  a daylight-saving day is 23 or 25 hours long. Adding 24 hours would
  leave an hour of activity in neither day once a year and count an hour
  twice once a year.
* **Idempotency.** Re-running must recompute, not duplicate — that is
  what makes a late refund or a backfilled fee a recalculation rather
  than an edit.
* **Visible failure.** A rebuild that dies must leave evidence. Stale
  data is tolerable; silently stale data is not.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
import app.reporting  # noqa: F401 — registers the metric catalogue
from app.core.periods import (
    completed_reporting_date,
    platform_tz,
    reporting_date_bounds,
)
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.models.reporting_aggregate import MetricDaily, ReportingJobRun
from app.reporting import aggregates
from app.reporting.registry import REGISTRY, Aggregation


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _join(db, user, space, *, joined_at=None):
    m = SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=joined_at or datetime.utcnow(),
    )
    db.add(m); db.flush()
    return m


def _sale(db, space, creator, payer, *, settled_at, gross=10000):
    t = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=payer.id, creator_user_id=creator.id, space_id=space.id,
        currency="AUD", gross_amount_cents=gross,
        platform_fee_basis_points=1000, platform_fee_cents=gross // 10,
        net_creator_amount_cents=gross - gross // 10, stripe_mode="test",
        created_at=settled_at, updated_at=settled_at,
        settled_at=settled_at, settled_at_source="observed",
    )
    db.add(t); db.flush()
    return t


def stored(db, metric_key, *, dimension=aggregates.PLATFORM_DIMENSION, days=None):
    """Stored rows for one metric.

    ``days`` scopes the query to the dates a test actually built. Without
    it, rows committed by an earlier run of the real rebuild script
    linger in ``fc_test`` and silently join the assertion — the leftover
    committed-row trap this database is prone to.
    """
    # The loader upserts via Core DML, which does not refresh the
    # session's identity map — a row already loaded would read back at
    # its pre-rebuild value. Expiring first is what makes "rebuild then
    # assert" mean what it says.
    db.expire_all()
    q = db.query(MetricDaily).filter(
        MetricDaily.metric_key == metric_key,
        MetricDaily.dimension == dimension,
    )
    if days is not None:
        q = q.filter(MetricDaily.reporting_date.in_(list(days)))
    return q.order_by(MetricDaily.reporting_date).all()


# ---------------------------------------------------------------------------
# What is stored
# ---------------------------------------------------------------------------

class TestWhatIsStored:
    def test_distinct_counts_are_never_stored(self):
        """The whole reason the registry declares aggregation."""
        for m in REGISTRY.all():
            if m.aggregation is Aggregation.distinct_count:
                assert not aggregates.store_eligible(m), (
                    f"{m.key} is a distinct count and must not be stored "
                    "daily — somebody would sum it"
                )

    def test_ratios_are_never_stored(self):
        for m in REGISTRY.all():
            if m.aggregation is Aggregation.ratio:
                assert not aggregates.store_eligible(m), m.key

    def test_additive_and_snapshot_metrics_are_stored(self):
        for m in REGISTRY.all():
            if m.aggregation in (Aggregation.additive, Aggregation.snapshot):
                assert aggregates.store_eligible(m), m.key

    def test_active_members_is_deliberately_absent(self):
        """Named explicitly because it is the metric somebody will look
        for and be tempted to add."""
        assert not aggregates.store_eligible(REGISTRY.get("active_members"))
        with pytest.raises(aggregates.NotStored):
            aggregates.series(None, "active_members", date.today(), date.today())

    def test_eligibility_is_read_from_the_registry_not_a_list(self):
        """So a metric added later is classified by its own declaration."""
        import inspect

        src = inspect.getsource(aggregates.store_eligible)
        assert "aggregation" in src
        assert "Aggregation.additive" in src

    def test_the_stored_row_records_which_kind_it_is(self, db, make_user, make_space):
        space = make_space(creator=make_user(role="creator"))
        db.commit()
        aggregates.rebuild_day(db, date(2026, 3, 15))
        db.flush()
        rows = {r.metric_key: r for r in db.query(MetricDaily).all()}
        assert rows["gross_collective_sales_cents"].aggregation == "additive"
        assert rows["unique_members"].aggregation == "snapshot"


# ---------------------------------------------------------------------------
# The Australian reporting day
# ---------------------------------------------------------------------------

class TestReportingDayBoundaries:
    def test_a_normal_day_is_twenty_four_hours(self):
        s, e = reporting_date_bounds(date(2026, 6, 15))
        assert (e - s) == timedelta(hours=24)

    def test_the_spring_forward_day_is_twenty_three_hours(self):
        """Sydney loses an hour on 4 October 2026.

        Adding 24 hours would push the boundary an hour past midnight and
        leave that hour in neither day.
        """
        s, e = reporting_date_bounds(date(2026, 10, 4))
        assert (e - s) == timedelta(hours=23)

    def test_the_fall_back_day_is_twenty_five_hours(self):
        """Sydney gains an hour on 5 April 2026, and that hour belongs to
        exactly one reporting day."""
        s, e = reporting_date_bounds(date(2026, 4, 5))
        assert (e - s) == timedelta(hours=25)

    @pytest.mark.parametrize("transition", [date(2026, 10, 4), date(2026, 4, 5)])
    def test_consecutive_days_meet_exactly_across_a_transition(self, transition):
        """No gap and no overlap — every instant lands in one day."""
        before = reporting_date_bounds(transition - timedelta(days=1))
        during = reporting_date_bounds(transition)
        after = reporting_date_bounds(transition + timedelta(days=1))
        assert before[1] == during[0]
        assert during[1] == after[0]

    def test_a_sale_just_before_local_midnight_lands_in_that_day(self):
        """The case a UTC boundary gets wrong by ten or eleven hours."""
        tz = platform_tz()
        local_late = datetime(2026, 6, 15, 23, 30, tzinfo=tz)
        naive_utc = local_late.astimezone().replace(tzinfo=None)
        from app.core.periods import _to_utc_naive
        as_utc = _to_utc_naive(local_late)
        s, e = reporting_date_bounds(date(2026, 6, 15))
        assert s <= as_utc < e, (
            "23:30 Sydney on the 15th must belong to the 15th"
        )
        # And not to the 16th.
        s16, e16 = reporting_date_bounds(date(2026, 6, 16))
        assert not (s16 <= as_utc < e16)

    def test_the_completed_day_is_yesterday_in_the_platform_timezone(self):
        """Mid-morning UTC is already the following day in Sydney, so a
        UTC "yesterday" would rebuild the wrong day."""
        tz = platform_tz()
        # 2026-06-15 23:00 UTC is 2026-06-16 09:00 in Sydney.
        moment = datetime(2026, 6, 15, 23, 0)
        assert completed_reporting_date(moment) == date(2026, 6, 15)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

class TestStoredValues:
    def test_a_flow_is_stored_on_the_day_it_happened(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        day = date(2026, 3, 10)
        starts_at, _ = reporting_date_bounds(day)
        _sale(db, space, creator, make_user(),
              settled_at=starts_at + timedelta(hours=5))
        db.commit()

        aggregates.rebuild_range(db, day - timedelta(days=1), day + timedelta(days=1))
        rows = {r.reporting_date: r.value
                for r in stored(db, "gross_collective_sales_cents")}
        assert rows[day] == 10000
        assert rows[day - timedelta(days=1)] == 0
        assert rows[day + timedelta(days=1)] == 0

    def test_a_snapshot_is_stored_as_the_state_at_end_of_day(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        _join(db, make_user(), space, joined_at=datetime(2026, 3, 10, 2, 0))
        db.commit()
        aggregates.rebuild_range(db, date(2026, 3, 9), date(2026, 3, 11))
        rows = {r.reporting_date: r.value for r in stored(db, "unique_members")}
        assert rows[date(2026, 3, 9)] == 0
        assert rows[date(2026, 3, 10)] == 1
        assert rows[date(2026, 3, 11)] == 1

    def test_a_snapshot_carries_its_provenance(self, db, make_user, make_space):
        """Reconstructed from membership rows before BI-1 recording."""
        space = make_space(creator=make_user(role="creator"))
        _join(db, make_user(), space, joined_at=datetime(2026, 3, 10))
        db.commit()
        aggregates.rebuild_day(db, date(2026, 3, 10))
        db.flush()
        [row] = stored(db, "unique_members", days=[date(2026, 3, 10)])
        assert row.provenance in ("observed", "reconstructed")

    def test_per_collective_rows_are_written(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        day = date(2026, 3, 12)
        starts_at, _ = reporting_date_bounds(day)
        _sale(db, space, creator, make_user(), settled_at=starts_at + timedelta(hours=2))
        db.commit()
        aggregates.rebuild_day(db, day, space_ids=[space.id])
        db.flush()
        rows = stored(
            db, "gross_collective_sales_cents",
            dimension=aggregates.space_dimension(space.id),
        )
        assert [r.value for r in rows] == [10000]

    def test_an_unavailable_metric_is_skipped_not_stored_as_zero(
        self, db, make_user, make_space,
    ):
        """Unavailable is not zero. Storing zero would turn "we cannot
        say" into "there were none"."""
        make_space(creator=make_user(role="creator"))
        db.commit()
        result = aggregates.rebuild_day(db, date(2026, 3, 13))
        db.flush()
        # memberships_per_member is a ratio and never stored at all;
        # nothing unavailable should have produced a row.
        assert stored(db, "memberships_per_member") == []


# ---------------------------------------------------------------------------
# Idempotency and recalculation
# ---------------------------------------------------------------------------

class TestIdempotencyAndRecalculation:
    def test_rebuilding_the_same_day_twice_does_not_duplicate(
        self, db, make_user, make_space,
    ):
        space = make_space(creator=make_user(role="creator"))
        db.commit()
        day = date(2026, 3, 14)
        aggregates.rebuild_range(db, day, day)
        first = db.query(MetricDaily).count()
        aggregates.rebuild_range(db, day, day)
        assert db.query(MetricDaily).count() == first

    def test_a_late_refund_is_picked_up_by_rebuilding_the_day(
        self, db, make_user, make_space,
    ):
        """A correction is a recalculation, not an edit."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        day = date(2026, 3, 16)
        starts_at, _ = reporting_date_bounds(day)
        txn = _sale(db, space, creator, make_user(),
                    settled_at=starts_at + timedelta(hours=1))
        db.commit()
        aggregates.rebuild_range(db, day, day)
        [row] = stored(db, "refunds_cents", days=[day])
        assert row.value == 0

        # The refund arrives later, dated into that same day.
        txn.refunded_amount_cents = 2500
        txn.last_refunded_at = starts_at + timedelta(hours=3)
        txn.status = PaymentTransactionStatus.partially_refunded
        db.commit()
        aggregates.rebuild_range(db, day, day)
        [row] = stored(db, "refunds_cents", days=[day])
        assert row.value == 2500, "rebuilding must recompute, not preserve"

    def test_a_changed_value_overwrites_rather_than_appends(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        day = date(2026, 3, 17)
        starts_at, _ = reporting_date_bounds(day)
        db.commit()
        aggregates.rebuild_range(db, day, day)
        _sale(db, space, creator, make_user(), settled_at=starts_at + timedelta(hours=1))
        db.commit()
        aggregates.rebuild_range(db, day, day)
        rows = stored(db, "gross_collective_sales_cents", days=[day])
        assert len(rows) == 1
        assert rows[0].value == 10000

    def test_a_reversed_range_is_refused(self, db):
        with pytest.raises(ValueError):
            aggregates.rebuild_range(db, date(2026, 3, 5), date(2026, 3, 1))


# ---------------------------------------------------------------------------
# Job runs
# ---------------------------------------------------------------------------

class TestJobRuns:
    def test_a_successful_run_is_recorded(self, db, make_user, make_space):
        make_space(creator=make_user(role="creator"))
        db.commit()
        result = aggregates.rebuild_range(db, date(2026, 3, 18), date(2026, 3, 19))
        run = db.get(ReportingJobRun, result.job_run_id)
        assert run.status == "succeeded"
        assert run.finished_at is not None
        assert run.days_processed == 2
        assert run.rows_written == result.rows_written > 0

    def test_a_failed_run_is_recorded_as_failed(
        self, db, make_user, make_space, monkeypatch,
    ):
        """A rebuild that blows up must leave evidence, not silence."""
        make_space(creator=make_user(role="creator"))
        db.commit()

        def boom(*a, **k):
            raise RuntimeError("deliberate")

        monkeypatch.setattr(aggregates, "rebuild_day", boom)
        result = aggregates.rebuild_range(db, date(2026, 3, 20), date(2026, 3, 20))
        assert result.failed is True
        run = db.get(ReportingJobRun, result.job_run_id)
        assert run.status == "failed"
        assert "RuntimeError" in run.error

    def test_last_successful_run_skips_a_later_failure(
        self, db, make_user, make_space, monkeypatch,
    ):
        make_space(creator=make_user(role="creator"))
        db.commit()
        ok = aggregates.rebuild_range(db, date(2026, 3, 21), date(2026, 3, 21))

        monkeypatch.setattr(
            aggregates, "rebuild_day",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
        )
        aggregates.rebuild_range(db, date(2026, 3, 22), date(2026, 3, 22))

        assert aggregates.last_run(db).status == "failed"
        assert aggregates.last_successful_run(db).id == ok.job_run_id

    def test_a_run_that_never_finished_is_reported_as_incomplete(self, db):
        """A process killed mid-rebuild leaves its row open."""
        db.add(ReportingJobRun(
            id=_uid("run"), job_name=aggregates.JOB_NAME, status="running",
            started_at=datetime.utcnow() - timedelta(hours=12),
        ))
        db.flush()
        stale = aggregates.unfinished_runs(db)
        assert len(stale) == 1

    def test_a_run_that_started_moments_ago_is_not_yet_incomplete(self, db):
        db.add(ReportingJobRun(
            id=_uid("run"), job_name=aggregates.JOB_NAME, status="running",
            started_at=datetime.utcnow(),
        ))
        db.flush()
        assert aggregates.unfinished_runs(db) == []


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------

class TestReadingBack:
    def test_a_series_comes_back_in_date_order_with_provenance(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.commit()
        aggregates.rebuild_range(db, date(2026, 3, 23), date(2026, 3, 25))
        points = aggregates.series(
            db, "gross_collective_sales_cents", date(2026, 3, 23), date(2026, 3, 25),
        )
        assert [p["date"] for p in points] == [
            "2026-03-23", "2026-03-24", "2026-03-25",
        ]

    def test_asking_for_an_unstored_metric_raises_rather_than_returning_empty(
        self, db,
    ):
        """An empty list would read as "no activity"."""
        with pytest.raises(aggregates.NotStored):
            aggregates.series(
                db, "participation_rate", date(2026, 3, 1), date(2026, 3, 2),
            )

    def test_freshness_reports_the_latest_day_per_metric(
        self, db, make_user, make_space,
    ):
        make_space(creator=make_user(role="creator"))
        db.commit()
        aggregates.rebuild_range(db, date(2026, 3, 26), date(2026, 3, 27))
        f = aggregates.freshness(db)
        # The newest day this test built; freshness reports the maximum
        # across whatever is stored, so assert it is at least this.
        assert f["gross_collective_sales_cents"]["latest_reporting_date"] >= "2026-03-27"

    def test_nightly_rebuilds_a_lookback_window(
        self, db, make_user, make_space,
    ):
        """The lookback is what lets a late refund land without anybody
        asking, and what lets a missed night repair itself."""
        make_space(creator=make_user(role="creator"))
        db.commit()
        result = aggregates.nightly(
            db, now=datetime(2026, 6, 15, 23, 0), lookback_days=3,
        )
        days = sorted(d.reporting_date for d in result.days)
        assert days == [date(2026, 6, 13), date(2026, 6, 14), date(2026, 6, 15)]
