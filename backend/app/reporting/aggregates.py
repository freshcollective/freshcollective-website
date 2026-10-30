"""Building the daily reporting rows, and saying so when it fails.

What gets stored, and what deliberately does not
-----------------------------------------------
Only metrics the registry declares ``additive`` or ``snapshot``.

* **Additive flows** are stored as that day's value and summed across
  days by the reader.
* **Snapshots** are stored as the value *as at the end* of that day, and
  the reader takes the latest rather than adding.
* **Distinct counts and ratios are never stored.** Thirty daily
  unique-member counts do not make a monthly figure, because the same
  person appears on many days. A stored row would look summable and
  would not be, so those are always recomputed over the window asked
  for. ``store_eligible`` is the single place that decides, and it reads
  the registry rather than a list kept in step by hand.

Idempotency
-----------
Every write is ``ON CONFLICT (metric_key, reporting_date, dimension)``.
For almost everything the conflict action is ``DO UPDATE`` — the house
pattern. Re-running a day recomputes and overwrites it, which is what
makes a correction a recalculation: a refund recorded late, a backfilled
Stripe fee, or a fixed metric definition is handled by rebuilding the
affected dates rather than by editing a stored number.

Observations are the exception
------------------------------
A metric the registry marks ``observation_only`` cannot be recomputed for
a past day, only *looked at* on the day. Its conflict action is therefore
``DO NOTHING``: the stored row was written by the run that genuinely saw
that day, and a rebuild a month later has nothing better to offer — it
would only replace a true observation with the current count wearing an
old date. Recomputation and observation want opposite behaviour from the
same upsert, so the registry's declaration decides which one applies.

Failure is recorded, not swallowed
----------------------------------
A run writes a ``reporting_job_runs`` row before it starts and closes it
as ``succeeded`` or ``failed``. A process that dies leaves the row
``running``, which the health view reports as incomplete. The distinction
that matters is between data that is stale and data that is *silently*
stale.

Each day commits on its own, so a failure halfway through a long rebuild
keeps the days already done. The job is therefore resumable by re-running
it over the same range.

One caveat for callers: the upsert is Core DML, so a session that has
already loaded a ``MetricDaily`` row will not see the new value without
expiring it. Request-scoped readers never hit this; a long-lived session
that rebuilds and then reads must call ``expire_all()`` first.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.periods import completed_reporting_date, reporting_date_bounds
from app.models.reporting_aggregate import MetricDaily, ReportingJobRun
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Metric,
    Window,
)
from app.reporting.scope import platform_scope

logger = logging.getLogger(__name__)

JOB_NAME = "reporting_nightly"

#: How many days one invocation will rebuild without being asked to.
#: A bound rather than a limit on correctness — a longer rebuild is an
#: explicit range.
DEFAULT_LOOKBACK_DAYS = 3

PLATFORM_DIMENSION = "platform"


def space_dimension(space_id: str) -> str:
    return f"space:{space_id}"


def store_eligible(metric: Metric) -> bool:
    """Whether this metric's daily value may be stored.

    Reads the registry rather than a hand-kept list, so a metric added
    later is classified by its own declaration. Distinct counts and
    ratios are excluded by design — see the module docstring.
    """
    return metric.aggregation in (Aggregation.additive, Aggregation.snapshot)


def storable_metrics() -> list[Metric]:
    return [m for m in REGISTRY.all() if store_eligible(m)]


@dataclass
class DayResult:
    reporting_date: date
    rows_written: int = 0
    skipped: list[str] = field(default_factory=list)
    #: Observations already on record for this day, left untouched.
    #: Not a failure and not a write — a third outcome that would
    #: otherwise be invisible.
    preserved: list[str] = field(default_factory=list)


@dataclass
class RebuildResult:
    job_run_id: str
    days: list[DayResult] = field(default_factory=list)
    failed: bool = False
    error: str | None = None

    @property
    def rows_written(self) -> int:
        return sum(d.rows_written for d in self.days)

    @property
    def rows_preserved(self) -> int:
        """Observations already on record, left as they were."""
        return sum(len(d.preserved) for d in self.days)


def _window_for(metric: Metric, day: date) -> Window:
    """The window a metric is evaluated over for one reporting day.

    A flow is measured *across* the day. A snapshot is measured *at the
    end* of it, and the registry's snapshot metrics read
    ``window.ends_at`` as their as-at moment — so both kinds take the
    same bounds and interpret them differently, which is exactly what the
    ``aggregation`` declaration is for.
    """
    starts_at, ends_at = reporting_date_bounds(day)
    return Window(starts_at, ends_at, day.isoformat())


def rebuild_day(
    db: Session, day: date, *, space_ids: list[str] | None = None,
) -> DayResult:
    """Recompute and upsert every storable metric for one local day.

    Does not commit — the caller owns the transaction boundary, so a
    range rebuild can commit per day and stay resumable.
    """
    result = DayResult(reporting_date=day)
    scope = platform_scope()

    for metric in storable_metrics():
        window = _window_for(metric, day)
        try:
            value = metric.evaluate(db, scope, window)
        except Exception as exc:  # pragma: no cover - defensive
            # One metric failing must not abandon the rest of the day:
            # a partial day with a recorded skip is more useful than no
            # day at all, and the skip is reported.
            logger.exception(
                "reporting: %s failed for %s", metric.key, day.isoformat(),
            )
            result.skipped.append(f"{metric.key}: {type(exc).__name__}")
            continue

        if value.value is None:
            # Unavailable is not zero. Storing a zero here would turn
            # "we cannot say" into "there were none".
            result.skipped.append(f"{metric.key}: unavailable")
            continue

        written = _upsert(
            db,
            metric_key=metric.key,
            reporting_date=day,
            dimension=PLATFORM_DIMENSION,
            aggregation=metric.aggregation.value,
            value=int(value.value),
            provenance=value.qualifiers.get("provenance"),
            write_once=metric.observation_only,
        )
        if written:
            result.rows_written += 1
        else:
            # An observation already on record for this day. Left alone,
            # which is the point of write-once.
            result.preserved.append(f"{metric.key}")

    # Per-Collective rows, for the comparisons World Insights needs and
    # for creator-scoped reporting later. Only metrics that declare a
    # ``space_id`` dimension — the rest are platform-level by nature.
    for space_id in space_ids or []:
        sp_scope = _space_scope(space_id)
        for metric in storable_metrics():
            if "space_id" not in metric.dimensions:
                continue
            window = _window_for(metric, day)
            try:
                value = metric.evaluate(db, sp_scope, window)
            except Exception as exc:  # pragma: no cover - defensive
                result.skipped.append(
                    f"{metric.key}@{space_id}: {type(exc).__name__}"
                )
                continue
            if value.value is None:
                continue
            written = _upsert(
                db,
                metric_key=metric.key,
                reporting_date=day,
                dimension=space_dimension(space_id),
                aggregation=metric.aggregation.value,
                value=int(value.value),
                provenance=value.qualifiers.get("provenance"),
                write_once=metric.observation_only,
            )
            if written:
                result.rows_written += 1
            else:
                result.preserved.append(f"{metric.key}@{space_id}")

    return result


def _space_scope(space_id: str):
    """A scope restricted to one Collective.

    Built directly rather than through ``creator_scope`` because this is
    the loader computing a per-Collective row, not a creator asking a
    question — there is no user whose permissions to resolve.
    """
    from app.reporting.scope import Audience, ReportScope

    return ReportScope(
        audience=Audience.platform, user_id=None, space_ids=(space_id,),
    )


def _upsert(
    db: Session,
    *,
    metric_key: str,
    reporting_date: date,
    dimension: str,
    aggregation: str,
    value: int,
    provenance: str | None,
    write_once: bool = False,
) -> bool:
    """Store one daily figure. Returns whether a row was written.

    ``write_once`` protects an observation from a later rebuild. The
    return value matters because of it: a skipped conflict is not a row
    written, and a run that reported it as one would overstate what it
    did.
    """
    stmt = pg_insert(MetricDaily.__table__).values(
        id=str(uuid.uuid4()),
        metric_key=metric_key,
        reporting_date=reporting_date,
        dimension=dimension,
        aggregation=aggregation,
        value=value,
        provenance=provenance,
        computed_at=datetime.utcnow(),
    )
    index = ["metric_key", "reporting_date", "dimension"]
    if write_once:
        stmt = stmt.on_conflict_do_nothing(index_elements=index)
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=index,
            set_={
                "value": value,
                "aggregation": aggregation,
                "provenance": provenance,
                "computed_at": datetime.utcnow(),
            },
        )
    return bool(db.execute(stmt).rowcount)


def rebuild_range(
    db: Session,
    date_from: date,
    date_to: date,
    *,
    space_ids: list[str] | None = None,
    job_name: str = JOB_NAME,
) -> RebuildResult:
    """Rebuild every day in ``[date_from, date_to]`` inclusive.

    Commits after each day so a failure keeps the completed work and the
    job can simply be re-run over the same range.
    """
    if date_to < date_from:
        raise ValueError("date_to is before date_from")

    run_id = str(uuid.uuid4())
    db.add(ReportingJobRun(
        id=run_id,
        job_name=job_name,
        status="running",
        started_at=datetime.utcnow(),
        reporting_date_from=date_from,
        reporting_date_to=date_to,
    ))
    db.commit()

    result = RebuildResult(job_run_id=run_id)
    day = date_from
    try:
        while day <= date_to:
            result.days.append(rebuild_day(db, day, space_ids=space_ids))
            db.commit()
            day += timedelta(days=1)
    except Exception as exc:
        db.rollback()
        result.failed = True
        result.error = f"{type(exc).__name__}: {exc}"[:500]
        _close_run(
            db, run_id, status="failed", result=result, error=result.error,
        )
        logger.exception("reporting: rebuild failed on %s", day.isoformat())
        return result

    _close_run(db, run_id, status="succeeded", result=result)
    return result


def _close_run(
    db: Session,
    run_id: str,
    *,
    status: str,
    result: RebuildResult,
    error: str | None = None,
) -> None:
    run = db.get(ReportingJobRun, run_id)
    if run is None:  # pragma: no cover - defensive
        return
    run.status = status
    run.finished_at = datetime.utcnow()
    run.days_processed = len(result.days)
    run.rows_written = result.rows_written
    if error:
        run.error = error
    skipped = [s for d in result.days for s in d.skipped]
    if skipped and not error:
        # Recorded on the run rather than raised: a day where one metric
        # was unavailable still succeeded, and the detail belongs where
        # somebody monitoring will see it.
        run.error = ("skipped: " + "; ".join(skipped[:10]))[:500]
    db.commit()


def nightly(
    db: Session, *, now: datetime | None = None, lookback_days: int | None = None,
) -> RebuildResult:
    """What the cron runs.

    Rebuilds the last completed Australian day plus a short lookback, so
    a late-arriving refund or a backfilled Stripe fee is picked up without
    anybody asking. The lookback is why re-running is cheap and why a
    missed night repairs itself the following one.
    """
    now = now or datetime.utcnow()
    last_day = completed_reporting_date(now)
    lookback = (
        DEFAULT_LOOKBACK_DAYS if lookback_days is None else lookback_days
    )
    first_day = last_day - timedelta(days=max(0, lookback - 1))
    space_ids = [r[0] for r in db.execute(_all_space_ids())]
    return rebuild_range(db, first_day, last_day, space_ids=space_ids)


def _all_space_ids():
    from app.models.platform import Space

    return select(Space.id)


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------

def freshness(db: Session) -> dict:
    """How current the stored aggregates are, per metric.

    Reported rather than assumed. A dashboard that silently shows stale
    numbers is worse than one that says when it was last rebuilt.
    """
    rows = db.execute(
        select(
            MetricDaily.metric_key,
            func.max(MetricDaily.reporting_date),
            func.max(MetricDaily.computed_at),
        )
        .where(MetricDaily.dimension == PLATFORM_DIMENSION)
        .group_by(MetricDaily.metric_key)
    ).fetchall()
    return {
        key: {
            "latest_reporting_date": latest.isoformat() if latest else None,
            "computed_at": computed.isoformat() if computed else None,
        }
        for key, latest, computed in rows
    }


def last_run(db: Session, *, job_name: str = JOB_NAME) -> ReportingJobRun | None:
    return db.execute(
        select(ReportingJobRun)
        .where(ReportingJobRun.job_name == job_name)
        .order_by(ReportingJobRun.started_at.desc())
        .limit(1)
    ).scalars().first()


def last_successful_run(
    db: Session, *, job_name: str = JOB_NAME,
) -> ReportingJobRun | None:
    return db.execute(
        select(ReportingJobRun)
        .where(
            ReportingJobRun.job_name == job_name,
            ReportingJobRun.status == "succeeded",
        )
        .order_by(ReportingJobRun.started_at.desc())
        .limit(1)
    ).scalars().first()


def unfinished_runs(db: Session, *, older_than_hours: int = 6) -> list[ReportingJobRun]:
    """Runs still marked ``running`` long enough to be dead.

    A process killed mid-rebuild leaves its row open. Reporting that as
    incomplete is the difference between stale data and silently stale
    data.
    """
    cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
    return list(
        db.execute(
            select(ReportingJobRun).where(
                ReportingJobRun.status == "running",
                ReportingJobRun.started_at < cutoff,
            )
        ).scalars()
    )


def series(
    db: Session,
    metric_key: str,
    date_from: date,
    date_to: date,
    *,
    dimension: str = PLATFORM_DIMENSION,
) -> list[dict]:
    """A stored trend line, with each point's provenance.

    Refuses a metric the loader does not store, rather than returning an
    empty list that would read as "no activity".
    """
    metric = REGISTRY.get(metric_key)
    if not store_eligible(metric):
        raise NotStored(
            f"{metric_key!r} is {metric.aggregation.value} and is never stored "
            "daily — recompute it over the window you need instead"
        )
    rows = db.execute(
        select(
            MetricDaily.reporting_date, MetricDaily.value, MetricDaily.provenance,
        )
        .where(
            MetricDaily.metric_key == metric_key,
            MetricDaily.dimension == dimension,
            MetricDaily.reporting_date >= date_from,
            MetricDaily.reporting_date <= date_to,
        )
        .order_by(MetricDaily.reporting_date)
    ).fetchall()
    return [
        {"date": d.isoformat(), "value": int(v), "provenance": p}
        for d, v, p in rows
    ]


class NotStored(KeyError):
    """A metric that is deliberately never stored daily."""
