"""Every value the reporting code can emit, inserted into the real table.

Why this file exists
--------------------
The first nightly reporting run failed on a ``CheckViolation``. The
observation-only snapshots introduced a third provenance,
``observed_late``, and ``ck_metric_daily_provenance`` still listed two.

Nothing caught it, and the reason is worth stating plainly. The unit
tests asserted that the metric *returned* ``observed_late`` — they
evaluated it and read the qualifier. Not one of them stored the result.
A constraint only fails on INSERT, so a test that never inserts can pass
while production cannot write a single row.

So these tests do the only thing that could have caught it: for each
constrained column, they take the vocabulary from the code and insert
every member of it. A value the code can produce and the database will
not accept fails here rather than at 02:00 in Sydney.

The same shape of bug is possible for any enum-and-constraint pair, so
each one on the reporting tables is covered, including the column widths
— a ``String(16)`` that a 20-character value would silently truncate or
reject is the same failure wearing different clothes.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DataError, IntegrityError

from app.models.business_event import BusinessEvent
from app.models.reporting_aggregate import MetricDaily, ReportingJobRun
from app.reporting import aggregates
from app.reporting.registry import REGISTRY, Aggregation, Provenance
from app.services.business_events import BusinessEventType, SubjectType

JOB_STATUSES = ("running", "succeeded", "failed")


def _row(db, **over):
    d = dict(
        id=str(uuid.uuid4()),
        metric_key="total_collectives",
        reporting_date=date(2026, 10, 27),
        dimension=aggregates.PLATFORM_DIMENSION,
        aggregation=Aggregation.snapshot.value,
        value=5,
        provenance=Provenance.observed.value,
        computed_at=datetime.utcnow(),
    )
    d.update(over)
    r = MetricDaily(**d)
    db.add(r)
    db.flush()
    return r


# ---------------------------------------------------------------------------
# provenance — the one that failed
# ---------------------------------------------------------------------------

class TestEveryProvenanceCanBeStored:
    @pytest.mark.parametrize(
        "provenance", [p.value for p in Provenance], ids=lambda v: v,
    )
    def test_the_database_accepts_it(self, db, provenance):
        """Derived from the enum, so adding a member without widening the
        constraint fails here the moment it is added."""
        r = _row(db, provenance=provenance, id=str(uuid.uuid4()))
        assert r.provenance == provenance

    def test_observed_late_specifically(self, db):
        """The exact insert that failed in production, as reported:
        active_collectives / 2026-10-27 / platform / snapshot / 5 /
        observed_late."""
        r = _row(
            db,
            metric_key="active_collectives",
            reporting_date=date(2026, 10, 27),
            dimension="platform",
            aggregation="snapshot",
            value=5,
            provenance="observed_late",
        )
        assert r.provenance == "observed_late"

    def test_a_flow_may_have_no_provenance(self, db):
        assert _row(db, provenance=None).provenance is None

    def test_an_invented_provenance_is_still_refused(self, db):
        """Widening the constraint must not have turned it off."""
        with pytest.raises(IntegrityError):
            _row(db, provenance="vibes")

    def test_every_provenance_fits_the_column(self):
        width = MetricDaily.__table__.c.provenance.type.length
        for p in Provenance:
            assert len(p.value) <= width, (
                f"{p.value!r} is {len(p.value)} chars and the column is {width}"
            )

    def test_the_constraint_lists_exactly_the_enum(self, db):
        """Read the constraint back out of the database and compare.

        Belt and braces beside the inserts above: this one fails if the
        constraint grows a value the enum does not have, which inserting
        can never detect.
        """
        sql = db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_metric_daily_provenance'"
            )
        ).scalar()
        assert sql, "the provenance constraint is missing entirely"
        # PostgreSQL renders the IN list as an ARRAY with casts, so pull
        # the quoted literals out rather than splitting on punctuation.
        quoted = set(re.findall(r"'([a-z_]+)'", sql))
        assert quoted == {p.value for p in Provenance}, (
            f"constraint allows {sorted(quoted)}, enum declares "
            f"{sorted(p.value for p in Provenance)}"
        )


# ---------------------------------------------------------------------------
# The other constrained columns, same treatment
# ---------------------------------------------------------------------------

class TestEveryAggregationThatCanBeStoredCanBeStored:
    @pytest.mark.parametrize(
        "metric",
        [m for m in REGISTRY.all() if aggregates.store_eligible(m)],
        ids=lambda m: m.key,
    )
    def test_each_storable_metrics_aggregation_is_accepted(self, db, metric):
        """``store_eligible`` decides what the nightly writes. If it ever
        admits an aggregation the constraint rejects, every run fails on
        that metric."""
        _row(db, metric_key=metric.key, aggregation=metric.aggregation.value)

    def test_a_non_storable_aggregation_is_refused(self, db):
        with pytest.raises(IntegrityError):
            _row(db, aggregation=Aggregation.ratio.value)


class TestKeysAndDimensionsFit:
    def test_every_metric_key_fits_the_column(self):
        width = MetricDaily.__table__.c.metric_key.type.length
        for m in REGISTRY.all():
            assert len(m.key) <= width, f"{m.key} exceeds {width}"

    def test_a_collective_dimension_fits_the_column(self, db, make_space):
        """``space:<id>`` is built per Collective, so the longest real id
        decides whether the column is wide enough."""
        width = MetricDaily.__table__.c.dimension.type.length
        dim = aggregates.space_dimension(make_space().id)
        assert len(dim) <= width, f"{dim} is {len(dim)} chars, column is {width}"
        _row(db, dimension=dim)

    def test_an_over_long_dimension_is_refused_rather_than_truncated(self, db):
        """A silently truncated dimension would collide with another
        Collective's rows under the unique index — two Collectives
        sharing one trend line."""
        width = MetricDaily.__table__.c.dimension.type.length
        with pytest.raises((DataError, IntegrityError)):
            _row(db, dimension="space:" + "x" * width)


class TestJobRunStatuses:
    @pytest.mark.parametrize("status", JOB_STATUSES)
    def test_each_status_the_job_writes_is_accepted(self, db, status):
        run = ReportingJobRun(
            id=str(uuid.uuid4()),
            job_name=aggregates.JOB_NAME,
            status=status,
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.flush()
        assert run.status == status

    def test_an_invented_status_is_refused(self, db):
        with pytest.raises(IntegrityError):
            db.add(ReportingJobRun(
                id=str(uuid.uuid4()),
                job_name=aggregates.JOB_NAME,
                status="probably_fine",
                started_at=datetime.utcnow(),
            ))
            db.flush()

    def test_the_job_name_fits_the_column(self):
        width = ReportingJobRun.__table__.c.job_name.type.length
        assert len(aggregates.JOB_NAME) <= width


# ---------------------------------------------------------------------------
# business_events — the reporting surface's one remaining CHECK
# ---------------------------------------------------------------------------

def _event(db, **over):
    """A business event row, written the way the producer writes one.

    A core insert rather than the ORM, and rather than
    ``business_events.record`` — the latter would pin each subject type
    to the event types that happen to use it today, and the former sends
    an explicit NULL for ``sequence_number`` instead of leaving the
    column to its sequence. The point here is the constrained column,
    not the callers.
    """
    d = dict(
        id=str(uuid.uuid4()),
        event_type=BusinessEventType.membership_started.value,
        occurred_at=datetime.utcnow(),
        recorded_at=datetime.utcnow(),
        subject_type=SubjectType.membership.value,
        subject_id=str(uuid.uuid4()),
        payload={},
        dedupe_key=str(uuid.uuid4()),
    )
    d.update(over)
    db.execute(BusinessEvent.__table__.insert().values(**d))
    return db.execute(
        text("SELECT subject_type FROM business_events WHERE id = :i"),
        {"i": d["id"]},
    ).scalar()


class TestEverySubjectTypeCanBeStored:
    """The same treatment as provenance, for the same reason.

    ``business_events`` is written on the membership and payment paths,
    so an enum that outgrows ``ck_business_events_subject_type`` would
    fail somewhere far more exposed than a nightly job. It is the only
    CHECK on this surface that had no insert behind it.
    """

    @pytest.mark.parametrize(
        "subject_type", [s.value for s in SubjectType], ids=lambda v: v,
    )
    def test_the_database_accepts_it(self, db, subject_type):
        assert _event(db, subject_type=subject_type) == subject_type

    def test_an_invented_subject_type_is_refused(self, db):
        with pytest.raises(IntegrityError):
            _event(db, subject_type="galaxy")

    def test_the_constraint_lists_exactly_the_enum(self, db):
        sql = db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_business_events_subject_type'"
            )
        ).scalar()
        assert sql, "the subject_type constraint is missing entirely"
        quoted = set(re.findall(r"'([a-z_]+)'", sql))
        assert quoted == {s.value for s in SubjectType}, (
            f"constraint allows {sorted(quoted)}, enum declares "
            f"{sorted(s.value for s in SubjectType)}"
        )

    def test_every_subject_type_fits_the_column(self):
        width = BusinessEvent.__table__.c.subject_type.type.length
        for s in SubjectType:
            assert len(s.value) <= width, (
                f"{s.value!r} is {len(s.value)} chars and the column is {width}"
            )

    def test_every_event_type_fits_the_column(self):
        """Unconstrained by a CHECK, but a width is a constraint too."""
        width = BusinessEvent.__table__.c.event_type.type.length
        for e in BusinessEventType:
            assert len(e.value) <= width, (
                f"{e.value!r} is {len(e.value)} chars and the column is {width}"
            )


# ---------------------------------------------------------------------------
# The nightly job, end to end — storing, not just computing
# ---------------------------------------------------------------------------

class TestTheNightlyLookbackActuallyWrites:
    """The gap that let the failure through.

    Every existing test either evaluated a metric without storing it, or
    stored one day. The production job stores a three-day range and
    commits, which is where the constraint bit. These run that.
    """

    def _lookback(self):
        from app.core.periods import completed_reporting_date

        last = completed_reporting_date(datetime.utcnow())
        first = last - timedelta(days=aggregates.DEFAULT_LOOKBACK_DAYS - 1)
        return first, last

    def test_the_default_three_day_lookback_completes(
        self, db, make_space, make_user,
    ):
        space = make_space()
        first, last = self._lookback()
        result = aggregates.rebuild_range(db, first, last, space_ids=[space.id])
        assert not result.failed, result.error
        assert result.rows_written > 0
        assert len(result.days) == aggregates.DEFAULT_LOOKBACK_DAYS

    def test_it_writes_both_an_on_time_and_a_late_observation(
        self, db, make_space,
    ):
        """The three-day lookback spans exactly the two cases: the last
        completed day is observed, the two before it are observed_late.
        Both must be storable or the run dies partway."""
        space = make_space()
        first, last = self._lookback()
        result = aggregates.rebuild_range(db, first, last, space_ids=[space.id])
        assert not result.failed, result.error
        db.expire_all()

        stored = {
            p["provenance"]
            for p in aggregates.series(db, "total_collectives", first, last)
        }
        assert "observed" in stored
        assert "observed_late" in stored, (
            "the lookback should produce a late observation — the value "
            "that failed in production"
        )

    def test_a_historical_day_outside_the_grace_is_skipped_not_fatal(
        self, db, make_space,
    ):
        """An unavailable Collective count must not take the run down,
        and must not be stored as a zero either."""
        space = make_space()
        old = date(2026, 1, 15)
        result = aggregates.rebuild_range(db, old, old, space_ids=[space.id])
        assert not result.failed, result.error
        assert any("collectives" in s for s in result.days[0].skipped)
        db.expire_all()
        assert aggregates.series(db, "total_collectives", old, old) == []
        # The financial rows for that day are still written.
        assert aggregates.series(
            db, "gross_collective_sales_cents", old, old,
        ) != []

    def test_rerunning_the_whole_range_is_safe_and_changes_nothing(
        self, db, make_space,
    ):
        """Idempotency over the real range, after a failure. Re-running
        must not duplicate, and must not replace an observation."""
        space = make_space()
        first, last = self._lookback()
        aggregates.rebuild_range(db, first, last, space_ids=[space.id])
        db.expire_all()
        before = {
            (p["date"], p["value"], p["provenance"])
            for p in aggregates.series(db, "total_collectives", first, last)
        }
        count_before = db.execute(
            text("SELECT count(*) FROM metric_daily")
        ).scalar()

        second = aggregates.rebuild_range(db, first, last, space_ids=[space.id])
        assert not second.failed, second.error
        db.expire_all()

        after = {
            (p["date"], p["value"], p["provenance"])
            for p in aggregates.series(db, "total_collectives", first, last)
        }
        count_after = db.execute(
            text("SELECT count(*) FROM metric_daily")
        ).scalar()

        assert after == before, "a rerun changed a recorded observation"
        assert count_after == count_before, "a rerun duplicated rows"
        assert second.rows_preserved > 0


class TestAFailedRunStaysVisible:
    def test_a_failure_is_recorded_as_failed_and_not_hidden(self, db, make_space):
        """Data Health reads the last run and the last *successful* run
        separately, so a failure after a success must still show. The
        production run failed this way and must remain visible."""
        import app.reporting.aggregates as agg

        make_space()
        first, last = date(2026, 10, 27), date(2026, 10, 27)

        original = agg.rebuild_day

        def boom(*a, **kw):
            raise RuntimeError("CheckViolation, as it happens")

        agg.rebuild_day = boom
        try:
            result = agg.rebuild_range(db, first, last)
        finally:
            agg.rebuild_day = original

        assert result.failed
        db.expire_all()
        run = agg.last_run(db)
        assert run is not None
        assert run.status == "failed"
        assert run.error

    def test_a_later_success_does_not_erase_the_failure(self, db, make_space):
        """Two rows, not one overwritten. The health view's distinction
        between 'last run' and 'last successful run' depends on it."""
        import app.reporting.aggregates as agg

        space = make_space()
        first, last = date(2026, 10, 27), date(2026, 10, 27)

        original = agg.rebuild_day
        agg.rebuild_day = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("first attempt")
        )
        try:
            agg.rebuild_range(db, first, last)
        finally:
            agg.rebuild_day = original

        agg.rebuild_range(db, first, last, space_ids=[space.id])
        db.expire_all()

        rows = db.execute(
            text(
                "SELECT status FROM reporting_job_runs "
                "WHERE job_name = :j ORDER BY started_at"
            ),
            {"j": agg.JOB_NAME},
        ).fetchall()
        statuses = [r.status for r in rows]
        assert "failed" in statuses
        assert "succeeded" in statuses


class TestNoOtherReportingColumnIsUnguarded:
    def test_every_check_constraint_on_the_reporting_tables_is_covered(self, db):
        """A roll-call, so a constraint added later is noticed.

        If this fails, a new CHECK exists that no test above inserts
        against — which is exactly the state that let the nightly job
        fail.
        """
        known = {
            "ck_metric_daily_provenance",
            "ck_metric_daily_aggregation",
            "ck_reporting_job_runs_status",
            "ck_business_events_subject_type",
        }
        found = {
            r.conname
            for r in db.execute(
                text(
                    "SELECT conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "WHERE c.contype = 'c' AND t.relname IN "
                    "('metric_daily', 'reporting_job_runs', 'business_events')"
                )
            )
        }
        assert found == known, (
            f"unreviewed CHECK constraint(s): {sorted(found - known)}; "
            f"missing: {sorted(known - found)}"
        )

    def test_the_tables_exist_with_the_columns_the_code_writes(self, db):
        cols = {c["name"] for c in inspect(db.get_bind()).get_columns("metric_daily")}
        assert {
            "metric_key", "reporting_date", "dimension",
            "aggregation", "value", "provenance", "computed_at",
        } <= cols
