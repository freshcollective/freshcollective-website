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
from app.core.periods import VALID_PERIODS, resolve_period
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


def _definition(m: Metric) -> MetricDefinitionOut:
    return MetricDefinitionOut(
        key=m.key,
        display_name=m.display_name,
        definition=m.definition,
        source_of_truth=m.source_of_truth,
        grain=m.grain.value,
        aggregation=m.aggregation.value,
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


class HealthOut(BaseModel):
    #: False means business history is not being written at all.
    recording_enabled: bool
    #: None until the first event is recorded, which reads as "recording
    #: has not started" rather than "everything is broken".
    activation_floor: str | None = None
    events_total: int
    event_counts_by_type: dict[str, int]
    #: True when every reconciliation check passes.
    ok: bool
    total_missing: int
    checks: list[CheckOut] = []
    note: str | None = None


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
    from app.core.config import settings
    from app.services import business_event_reconciliation as recon

    report = recon.reconcile(db)
    counts = recon.event_counts_by_type(db)
    total = sum(counts.values())

    note = None
    if not settings.business_events_enabled:
        note = (
            "Recording is DISABLED. Business history is not being written, "
            "and the gap cannot be reconstructed later."
        )
    elif report.activation_floor is None:
        note = (
            "No events recorded yet. Recording is enabled, so this is "
            "expected until the first instrumented operation occurs."
        )

    return HealthOut(
        recording_enabled=settings.business_events_enabled,
        activation_floor=(
            report.activation_floor.isoformat() if report.activation_floor else None
        ),
        events_total=total,
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
        note=note,
    )
