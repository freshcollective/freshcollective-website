"""The shared reporting API.

Every value returned here comes with its own definition. That is the
point: "what does this number mean and where does it come from" is
answered by the response, not by a document that drifts out of step with
the query.

Two audiences, one engine. These routes resolve a platform scope because
they sit under ``/api/admin``; a creator-facing release adds routes that
resolve a creator scope and calls the same registry. No second reporting
engine, and no chance of the two disagreeing — because there is only one
set of definitions.

Authorisation is structural rather than conventional. The scope is built
by a dependency from the authenticated user, metrics declare whether a
creator may see them at all, and ``Metric.evaluate`` refuses a mismatch
before any SQL runs. A creator-scoped request for platform fee revenue
cannot succeed, however the caller phrases it.

Also here: the event-recording health view, brought forward from BI-3.
Establishing whether business history is being recorded required two
Render Shell sessions and a hand-built gzip blob during BI-1 — which is
not a thing anyone should have to do twice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.periods import (
    HISTORY_RANGE_LABELS,
    VALID_GROUPINGS,
    VALID_HISTORY_RANGES,
    VALID_PERIODS,
    resolve_period,
)
from app.models.user import User
from app.reporting import engagement as _engagement  # noqa: F401 — populates REGISTRY
from app.reporting import metrics as _metrics  # noqa: F401 — populates REGISTRY
from app.reporting.registry import (
    REGISTRY,
    Metric,
    MetricValue,
    UnknownMetric,
    Window,
)
from app.reporting import history as _history
from app.reporting.population import (
    Population,
    UnknownPopulation,
    view_options,
)
from app.reporting.scope import ReportScope, ScopeDenied, platform_scope

router = APIRouter(prefix="/api/admin/reporting", tags=["admin-reporting"])


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

def admin_scope(admin: User = Depends(get_admin_user)) -> ReportScope:
    """A platform scope, derived from an authenticated administrator.

    The only scope these routes can produce. A creator scope is built by
    ``scope.creator_scope`` from the Collectives they manage, and will be
    wired to creator-facing routes in a later release.
    """
    return platform_scope(user_id=admin.id)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

class MetricDefinitionOut(BaseModel):
    key: str
    display_name: str
    definition: str
    source_of_truth: str
    grain: str
    aggregation: str
    #: How the number reads: count, money_cents, proportion or rate.
    unit: str
    #: True when a past day cannot be reconstructed, only observed.
    #: A trend line for one of these begins when recording began.
    observation_only: bool
    date_basis: str
    access: str
    availability: str
    limitations: str | None = None
    dimensions: list[str] = []
    personal_data: bool = False


class MetricValueOut(BaseModel):
    key: str
    value: float | int | None = None
    available: bool = True
    unavailable_reason: str | None = None
    qualifiers: dict = {}
    #: The definition travels with the number, deliberately.
    definition: MetricDefinitionOut


class PeriodOut(BaseModel):
    label: str
    starts_at: str | None = None
    ends_at: str | None = None


class MetricResultOut(BaseModel):
    period: PeriodOut
    comparison: PeriodOut | None = None
    metrics: list[MetricValueOut]
    #: Same metrics over the previous comparable window. Absent for
    #: all-time, where there is nothing to compare against — never a
    #: fabricated zero.
    comparison_metrics: list[MetricValueOut] | None = None


class HistoryPointOut(BaseModel):
    label: str
    starts_on: str
    ends_on: str
    value: float | int | None = None
    available: bool = True
    unavailable_reason: str | None = None
    provenance: str | None = None
    #: False while the period is still running.
    complete: bool = True
    #: True when the range cut the period short of its natural span.
    clipped: bool = False
    #: Days behind the figure, and days the label implies. Unequal means
    #: the number covers less ground than it appears to.
    days_present: int = 0
    days_expected: int = 0
    partial_data: bool = False


class HistorySeriesOut(BaseModel):
    key: str
    display_name: str
    unit: str
    aggregation: str
    #: ``stored`` or ``recomputed`` — see ``app.reporting.history``.
    source: str
    definition: str = ""
    #: The table(s) the number comes from, and which timestamp places it
    #: in a period. Returned so the chart's own "what does this mean"
    #: disclosure can answer it from the registry rather than from a
    #: caption somebody wrote once and nobody updated.
    source_of_truth: str = ""
    date_basis: str = ""
    availability: str = ""
    limitations: str | None = None
    observation_only: bool = False
    qualifiers: dict = {}
    points: list[HistoryPointOut] = []


class HistoryBucketOut(BaseModel):
    label: str
    starts_on: str
    ends_on: str
    complete: bool = True
    clipped: bool = False


class HistoryRangeOut(BaseModel):
    key: str
    label: str
    starts_on: str
    ends_on: str
    days: int


class PopulationOut(BaseModel):
    key: str
    label: str
    note: str


class ControlOptionsOut(BaseModel):
    """What the shared history control may offer.

    Returned with the data rather than hardcoded in the frontend. The
    ranges, groupings and populations all come from the backend's own
    vocabularies, so a class added to ``classification`` appears in the
    control without a second list to keep in step — which is the same
    reason the period selector reads its options from here.
    """

    ranges: list[dict]
    groupings: list[str]
    populations: list[dict]


class HistoryResultOut(BaseModel):
    range: HistoryRangeOut
    grouping: str
    population: PopulationOut
    buckets: list[HistoryBucketOut]
    series: list[HistorySeriesOut]
    options: ControlOptionsOut


def _definition(m: Metric) -> MetricDefinitionOut:
    return MetricDefinitionOut(
        key=m.key,
        display_name=m.display_name,
        definition=m.definition,
        source_of_truth=m.source_of_truth,
        grain=m.grain.value,
        aggregation=m.aggregation.value,
        unit=m.resolved_unit.value,
        observation_only=m.observation_only,
        date_basis=m.date_basis.value,
        access=m.access.value,
        availability=m.availability.value,
        limitations=m.limitations,
        dimensions=list(m.dimensions),
        personal_data=m.personal_data,
    )


def _value_out(m: Metric, v: MetricValue) -> MetricValueOut:
    return MetricValueOut(
        key=v.key,
        value=v.value,
        available=v.available,
        unavailable_reason=v.unavailable_reason,
        qualifiers=v.qualifiers,
        definition=_definition(m),
    )


def _window_from(bounds) -> Window:
    return Window(
        starts_at=bounds.starts_at, ends_at=bounds.ends_at, label=bounds.label,
    )


def _period_out(w: Window) -> PeriodOut:
    return PeriodOut(
        label=w.label,
        starts_at=w.starts_at.isoformat() if w.starts_at else None,
        ends_at=w.ends_at.isoformat() if w.ends_at else None,
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@router.get("/metrics", response_model=list[MetricDefinitionOut])
def list_metrics(scope: ReportScope = Depends(admin_scope)):
    """Every metric this scope may ask for, with its full definition.

    The catalogue a dashboard reads to know what it can show, and the
    reference answering "what is this figure" without a round trip.
    """
    return [_definition(m) for m in REGISTRY.visible_to(scope)]


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

@router.get("/query", response_model=MetricResultOut)
def query_metrics(
    keys: str = Query(
        ...,
        description="Comma-separated metric keys, from /metrics.",
    ),
    period: str = Query("this_month", description=f"One of {list(VALID_PERIODS)}"),
    compare: bool = Query(
        True, description="Also compute the previous comparable period.",
    ),
    db: Session = Depends(get_db),
    scope: ReportScope = Depends(admin_scope),
):
    """Compute several metrics over one period, with a comparison.

    Batched because a dashboard panel wants eight figures for the same
    window, and eight round trips would each resolve the period
    separately — which is how two surfaces start disagreeing.
    """
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Valid: {list(VALID_PERIODS)}.",
        )

    requested = [k.strip() for k in keys.split(",") if k.strip()]
    if not requested:
        raise HTTPException(status_code=422, detail="No metric keys supplied.")

    selected: list[Metric] = []
    for key in requested:
        try:
            selected.append(REGISTRY.get(key))
        except UnknownMetric:
            raise HTTPException(
                status_code=404, detail=f"Unknown metric {key!r}.",
            ) from None

    current_bounds, previous_bounds = resolve_period(period)  # type: ignore[arg-type]
    current = _window_from(current_bounds)

    def evaluate(window: Window) -> list[MetricValueOut]:
        out: list[MetricValueOut] = []
        for m in selected:
            try:
                out.append(_value_out(m, m.evaluate(db, scope, window)))
            except ScopeDenied as exc:
                # 403 rather than a quiet omission: a caller asking for
                # something it may not see should be told, not handed a
                # short list it might mistake for a complete one.
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        return out

    comparison = _window_from(previous_bounds) if previous_bounds else None
    return MetricResultOut(
        period=_period_out(current),
        comparison=_period_out(comparison) if comparison else None,
        metrics=evaluate(current),
        comparison_metrics=(
            evaluate(comparison) if (comparison and compare) else None
        ),
    )


# ---------------------------------------------------------------------------
# Event-recording health
# ---------------------------------------------------------------------------

class CheckOut(BaseModel):
    name: str
    ok: bool
    missing: int
    pre_activation: int
    unreconstructable: int
    sample_ids: list[str] = []
    note: str | None = None


class JobRunOut(BaseModel):
    job_name: str
    status: str
    started_at: str
    finished_at: str | None = None
    reporting_date_from: str | None = None
    reporting_date_to: str | None = None
    days_processed: int = 0
    rows_written: int = 0
    #: Short and non-sensitive. Never member or payment data.
    error: str | None = None


class AggregateFreshnessOut(BaseModel):
    #: Oldest "latest day" across stored metrics — the honest answer to
    #: "how current is the reporting data", since a trend is only as
    #: fresh as its least fresh series.
    oldest_latest_reporting_date: str | None = None
    newest_latest_reporting_date: str | None = None
    metrics_stored: int = 0
    rows_total: int = 0
    per_metric: dict[str, dict] = {}


class HealthOut(BaseModel):
    #: False means business history is not being written at all.
    recording_enabled: bool
    #: None until the first event is recorded, which reads as "recording
    #: has not started" rather than "everything is broken".
    activation_floor: str | None = None
    events_total: int
    #: The most recent event of any type. A long quiet stretch is normal
    #: on a small platform and is NOT an instrumentation failure, so this
    #: is reported as a fact rather than judged.
    latest_event_at: str | None = None
    event_counts_by_type: dict[str, int]
    #: True when every reconciliation check passes.
    ok: bool
    total_missing: int
    checks: list[CheckOut] = []
    #: Daily aggregate freshness and the jobs that produce it.
    aggregates: AggregateFreshnessOut = AggregateFreshnessOut()
    last_run: JobRunOut | None = None
    last_successful_run: JobRunOut | None = None
    #: Runs still marked running long after they started — a process that
    #: died mid-rebuild. The difference between stale and silently stale.
    incomplete_runs: list[JobRunOut] = []
    note: str | None = None


@router.get("/history", response_model=HistoryResultOut)
def metric_history(
    keys: str = Query(..., description="Comma-separated metric keys."),
    range: str = Query(
        "last_3_months", description=f"One of {list(VALID_HISTORY_RANGES)}",
    ),
    grouping: str = Query(
        "weekly", description=f"One of {list(VALID_GROUPINGS)}",
    ),
    population: str = Query(
        "all", description="Reporting-class population. 'all' for the ledger.",
    ),
    db: Session = Depends(get_db),
    scope: ReportScope = Depends(admin_scope),
):
    """Several metrics as time series over one range and grouping.

    Batched for the same reason ``/query`` is: a chart panel wants two
    or three lines on one axis, and resolving the range separately per
    line is how two charts on one page start disagreeing about where
    October begins.

    Everything the caller needs to render honestly comes back with the
    numbers — each bucket's completeness, each point's provenance, and
    the population's own prose. A client cannot accidentally draw a
    reconstruction as an observation, because it is told which it has.
    """
    if range not in VALID_HISTORY_RANGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid range {range!r}. Valid: {list(VALID_HISTORY_RANGES)}.",
        )
    if grouping not in VALID_GROUPINGS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid grouping {grouping!r}. Valid: {list(VALID_GROUPINGS)}."
            ),
        )
    try:
        pop = Population.parse(population)
    except UnknownPopulation:
        raise HTTPException(
            status_code=422, detail=f"Unknown population {population!r}.",
        ) from None

    requested = [k.strip() for k in keys.split(",") if k.strip()]
    if not requested:
        raise HTTPException(status_code=422, detail="No metric keys supplied.")

    for key in requested:
        if key not in REGISTRY:
            raise HTTPException(
                status_code=404, detail=f"Unknown metric {key!r}.",
            )

    span, buckets = _history.resolve(db, range, grouping)
    if len(buckets) > _history.MAX_BUCKETS:
        # Named alternative rather than a silent truncation: a chart
        # quietly cut from twelve months to four would look like the
        # business stopped in June.
        coarser = "weekly" if grouping == "daily" else "monthly"
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(buckets)} periods exceeds the {_history.MAX_BUCKETS} "
                f"this endpoint will assemble. Group by {coarser} instead, "
                "or ask for a shorter range."
            ),
        )

    try:
        series = [
            _history.build_series(db, key, scope, buckets, population=pop)
            for key in requested
        ]
    except ScopeDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return HistoryResultOut(
        range=HistoryRangeOut(
            key=range,
            label=span.label,
            starts_on=span.starts_on.isoformat(),
            ends_on=span.ends_on.isoformat(),
            days=span.days,
        ),
        grouping=grouping,
        population=PopulationOut(
            key=pop.view.value, label=pop.label, note=pop.note,
        ),
        buckets=[
            HistoryBucketOut(
                label=b.label,
                starts_on=b.starts_on.isoformat(),
                ends_on=b.ends_on.isoformat(),
                complete=b.complete,
                clipped=b.clipped,
            )
            for b in buckets
        ],
        series=[
            HistorySeriesOut(
                key=s.key,
                display_name=s.display_name,
                unit=s.unit,
                aggregation=s.aggregation,
                source=s.source,
                definition=s.definition,
                source_of_truth=s.source_of_truth,
                date_basis=s.date_basis,
                availability=s.availability,
                limitations=s.limitations,
                observation_only=s.observation_only,
                qualifiers=s.qualifiers,
                points=[
                    HistoryPointOut(
                        label=p.label,
                        starts_on=p.starts_on.isoformat(),
                        ends_on=p.ends_on.isoformat(),
                        value=p.value,
                        available=p.available,
                        unavailable_reason=p.unavailable_reason,
                        provenance=p.provenance,
                        complete=p.complete,
                        clipped=p.clipped,
                        days_present=p.days_present,
                        days_expected=p.days_expected,
                        partial_data=p.partial_data,
                    )
                    for p in s.points
                ],
            )
            for s in series
        ],
        options=ControlOptionsOut(
            ranges=[
                {"key": k, "label": HISTORY_RANGE_LABELS[k]}
                for k in VALID_HISTORY_RANGES
            ],
            groupings=list(VALID_GROUPINGS),
            populations=view_options(),
        ),
    )


@router.get("/health", response_model=HealthOut)
def recording_health(
    db: Session = Depends(get_db),
    _: ReportScope = Depends(admin_scope),
):
    """Is business history actually being recorded, and is it complete?

    Read-only. Answers in one request what BI-1 needed a Render Shell and
    a hand-built diagnostic to establish:

    * whether the recorder is switched on,
    * how many events exist, by type,
    * and whether any business operation has happened without its event.

    Exceptions are bounded below by the activation floor, so the years
    before BI-1 are reported as ``pre_activation`` rather than as tens of
    thousands of failures.
    """
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from app.core.config import settings
    from app.models.business_event import BusinessEvent
    from app.models.reporting_aggregate import MetricDaily
    from app.reporting import aggregates
    from app.services import business_event_reconciliation as recon

    report = recon.reconcile(db)
    counts = recon.event_counts_by_type(db)
    total = sum(counts.values())
    latest_event = db.execute(
        _select(_func.max(BusinessEvent.occurred_at))
    ).scalar()

    def _run_out(run) -> JobRunOut | None:
        if run is None:
            return None
        return JobRunOut(
            job_name=run.job_name,
            status=run.status,
            started_at=run.started_at.isoformat(),
            finished_at=run.finished_at.isoformat() if run.finished_at else None,
            reporting_date_from=(
                run.reporting_date_from.isoformat()
                if run.reporting_date_from else None
            ),
            reporting_date_to=(
                run.reporting_date_to.isoformat()
                if run.reporting_date_to else None
            ),
            days_processed=run.days_processed,
            rows_written=run.rows_written,
            error=run.error,
        )

    per_metric = aggregates.freshness(db)
    latest_dates = [
        v["latest_reporting_date"] for v in per_metric.values()
        if v["latest_reporting_date"]
    ]
    rows_total = db.execute(
        _select(_func.count()).select_from(MetricDaily)
    ).scalar() or 0
    fresh = AggregateFreshnessOut(
        oldest_latest_reporting_date=min(latest_dates) if latest_dates else None,
        newest_latest_reporting_date=max(latest_dates) if latest_dates else None,
        metrics_stored=len(per_metric),
        rows_total=int(rows_total),
        per_metric=per_metric,
    )

    incomplete = [_run_out(r) for r in aggregates.unfinished_runs(db)]
    last = _run_out(aggregates.last_run(db))
    last_ok = _run_out(aggregates.last_successful_run(db))

    # Notes are ordered worst-first, and a quiet period is never one of
    # them: no activity on a small platform is normal, and calling it a
    # failure would train somebody to ignore this panel.
    note = None
    if not settings.business_events_enabled:
        note = (
            "Recording is DISABLED. Business history is not being written, "
            "and the gap cannot be reconstructed later."
        )
    elif incomplete:
        note = (
            f"{len(incomplete)} reporting run(s) started and never finished. "
            "The stored aggregates may be incomplete."
        )
    elif last is not None and last.status == "failed":
        note = (
            "The most recent reporting rebuild failed. Stored aggregates are "
            "stale until it succeeds; re-running the job is safe."
        )
    elif report.activation_floor is None:
        # Ranked above "never rebuilt" on purpose: there is nothing to
        # aggregate until something has been recorded, so this is the
        # more fundamental fact and the one worth saying first.
        note = (
            "No events recorded yet. Recording is enabled, so this is "
            "expected until the first instrumented operation occurs."
        )
    elif last_ok is None and last is None:
        note = (
            "The reporting rebuild has never run, so no daily aggregates "
            "exist yet. Live metrics are unaffected."
        )

    return HealthOut(
        recording_enabled=settings.business_events_enabled,
        activation_floor=(
            report.activation_floor.isoformat() if report.activation_floor else None
        ),
        events_total=total,
        latest_event_at=latest_event.isoformat() if latest_event else None,
        event_counts_by_type=counts,
        ok=report.ok,
        total_missing=report.total_missing,
        checks=[
            CheckOut(
                name=c.name,
                ok=c.ok,
                missing=c.missing,
                pre_activation=c.pre_activation,
                unreconstructable=c.unreconstructable,
                sample_ids=c.sample_ids,
                note=c.note,
            )
            for c in report.checks
        ],
        aggregates=fresh,
        last_run=last,
        last_successful_run=last_ok,
        incomplete_runs=incomplete,
        note=note,
    )
