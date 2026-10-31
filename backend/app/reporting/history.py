"""Turning stored daily figures into a chart.

Three jobs, and the second is the one that earns the module.

**Bucketing.** Daily rows fold into weeks and months according to the
metric's declared aggregation, never according to what the chart would
like. An additive flow sums; a snapshot takes the latest day in the
bucket. Nothing else is foldable, and ``aggregate_across`` in the
registry already refuses to try — so a distinct count or a ratio is
recomputed over each bucket's own window instead of being assembled from
daily rows that cannot be added.

**A gap is not a zero.** This is the whole reason the module exists
rather than a ``GROUP BY`` in the route. A missing day means one of
three different things — nobody has rebuilt it, the metric cannot be
reconstructed for it, or it genuinely has no activity — and only the
first two are gaps. A bucket with no stored days at all returns
``None`` with a reason, which the chart draws as a break in the line. A
bucket with *some* days missing returns the figure it can compute and
says how many days are behind it, because a week assembled from four
days is a real number about four days and a misleading one about seven.

**Provenance survives aggregation.** A week containing one
reconstructed day is not an observed week. The bucket takes the least
confident provenance of the days inside it, so a chart cannot present a
reconstruction as an observation by the act of grouping it.

Reading stored rows versus recomputing
--------------------------------------
Stored rows are the fast path and the default. Two things force a
recompute over the bucket's own window:

* the metric is not stored daily at all — a distinct count or a ratio;
* a **population filter** is in play. Stored rows are computed over
  every Collective and every account, so there is no filtered figure to
  read back. Recomputing is the only honest answer, and it is also why
  a filtered view is bounded more tightly than an unfiltered one.

A recompute asks the registry the same question the nightly job asks,
through ``Metric.evaluate``, so a filtered chart and the stored dailies
cannot drift apart in definition — only in population, which is the
thing the reader asked to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select

from app.core.periods import (
    Bucket,
    DateRange,
    completed_reporting_date,
    group_buckets,
    reporting_date_bounds,
    resolve_history_range,
)
from app.models.reporting_aggregate import MetricDaily
from app.reporting.aggregates import (
    PLATFORM_DIMENSION,
    space_dimension,
    store_eligible,
)
from app.reporting.population import ALL, Population
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Metric,
    Provenance,
    Window,
)
from app.reporting.scope import Audience, ReportScope, ScopeDenied

#: The most buckets one request will assemble. A guard against a
#: pathological ask — twelve months grouped daily under a population
#: filter is 365 metric evaluations per metric — not a statement about
#: what is meaningful. The route turns this into a 422 naming the
#: coarser grouping rather than quietly truncating the range, because a
#: silently shortened chart is indistinguishable from a quiet period.
MAX_BUCKETS = 400

#: The most series one request will assemble when fanning out across
#: Collectives. Sized for the Collectives page: six metrics across the
#: four Collectives the chart palette can distinguish. Deliberately one
#: request rather than one per panel — two requests seconds apart can
#: straddle midnight in Sydney and resolve different last-completed
#: days, which would put two charts on one page on different axes.
#:
#: It bounds the fan-out only. A platform request has always been one
#: series per metric and several pages ask for eight or more.
MAX_SERIES = 24

#: How confident a provenance is, least first. A bucket takes the
#: minimum of the days inside it.
_CONFIDENCE = {
    Provenance.reconstructed.value: 0,
    Provenance.observed_late.value: 1,
    Provenance.observed.value: 2,
}


@dataclass(frozen=True)
class Point:
    """One bucket's figure, and everything needed to draw it honestly."""

    label: str
    starts_on: date
    ends_on: date
    value: int | float | None = None
    provenance: str | None = None
    #: Set when there is no figure. The chart shows a break here; it
    #: must never substitute zero.
    unavailable_reason: str | None = None
    #: False when the bucket has not finished yet.
    complete: bool = True
    #: True when the range cut the bucket short of its natural span.
    clipped: bool = False
    #: Days inside the bucket with a stored figure, and days expected.
    #: Equal for a sound bucket; unequal says the number covers less
    #: ground than its label implies.
    days_present: int = 0
    days_expected: int = 0

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def partial_data(self) -> bool:
        """Whether some days inside this bucket have no stored figure."""
        return self.available and self.days_present < self.days_expected


@dataclass
class Series:
    """One metric across a range, with the provenance of the whole."""

    key: str
    display_name: str
    unit: str
    aggregation: str
    #: ``stored`` when folded from ``metric_daily``; ``recomputed`` when
    #: evaluated per bucket. Reported because it explains why a
    #: population-filtered chart can reach back further, or less far,
    #: than the unfiltered one beside it.
    source: str
    points: list[Point] = field(default_factory=list)
    definition: str = ""
    #: Where the figure comes from and which timestamp dates it — the
    #: registry's own declaration, carried through so the chart can
    #: answer "what is this" without a second copy of the answer.
    source_of_truth: str = ""
    date_basis: str = ""
    availability: str = ""
    limitations: str | None = None
    observation_only: bool = False
    qualifiers: dict = field(default_factory=dict)
    #: Set when this series is one Collective's figures rather than the
    #: platform's. The name travels with it so a chart comparing four
    #: Collectives can label its lines without a second lookup.
    collective_id: str | None = None
    collective_name: str | None = None

    @property
    def has_any_value(self) -> bool:
        return any(p.available for p in self.points)


def earliest_reporting_date(db) -> date | None:
    """The oldest day the stored aggregates cover, if any.

    The floor for ``all_time``. Deliberately the stored floor rather
    than the oldest membership or payment: "all time" on these charts
    means all the history that has been *built*, and claiming to reach
    further would draw a flat line across years nobody has rebuilt. A
    bounded historical rebuild extends this honestly; nothing else
    should.
    """
    return db.execute(select(func.min(MetricDaily.reporting_date))).scalar()


def resolve(
    db,
    range_key: str,
    grouping: str,
    now: datetime | None = None,
) -> tuple[DateRange, list[Bucket]]:
    """The range and buckets a request resolves to."""
    span = resolve_history_range(
        range_key, now, earliest=earliest_reporting_date(db),
    )
    last_completed = completed_reporting_date(
        now if now is not None else datetime.utcnow()
    )
    return span, group_buckets(span, grouping, last_completed)


def _bucket_window(bucket: Bucket) -> Window:
    """The window one bucket is evaluated over.

    Both ends come from ``reporting_date_bounds``, so the UTC instants
    honour Australian midnight and daylight saving exactly as the stored
    dailies do. A snapshot metric reads ``ends_at`` as its as-at moment
    and so reports the state at the end of the bucket; an additive one
    sums across the whole span. One window, two correct readings,
    decided by the metric's declaration rather than by this module.
    """
    starts_at, _ = reporting_date_bounds(bucket.starts_on)
    _, ends_at = reporting_date_bounds(bucket.ends_on)
    return Window(starts_at, ends_at, bucket.label)


def _fold_provenance(values: list[str | None]) -> str | None:
    """The least confident provenance among a bucket's days."""
    known = [v for v in values if v in _CONFIDENCE]
    if not known:
        return None
    return min(known, key=lambda v: _CONFIDENCE[v])


def _stored_points(
    db, metric: Metric, buckets: list[Bucket], dimension: str,
) -> list[Point]:
    """Fold stored daily rows into buckets."""
    if not buckets:
        return []
    rows = db.execute(
        select(
            MetricDaily.reporting_date, MetricDaily.value, MetricDaily.provenance,
        ).where(
            MetricDaily.metric_key == metric.key,
            MetricDaily.dimension == dimension,
            MetricDaily.reporting_date >= buckets[0].starts_on,
            MetricDaily.reporting_date <= buckets[-1].ends_on,
        ).order_by(MetricDaily.reporting_date)
    ).fetchall()
    by_day = {d: (int(v), p) for d, v, p in rows}

    out: list[Point] = []
    for bucket in buckets:
        days = [
            by_day[d]
            for d in _days_in(bucket)
            if d in by_day
        ]
        base = dict(
            label=bucket.label,
            starts_on=bucket.starts_on,
            ends_on=bucket.ends_on,
            complete=bucket.complete,
            clipped=bucket.clipped,
            days_present=len(days),
            days_expected=bucket.days,
        )
        if not days:
            out.append(Point(
                **base,
                unavailable_reason=(
                    "No figure was recorded for any day in this period."
                    if not metric.observation_only else
                    "Not recorded for this period. This metric can only be "
                    "observed on the day, never reconstructed afterwards."
                ),
            ))
            continue

        if metric.aggregation is Aggregation.additive:
            value: int | float = sum(v for v, _ in days)
        else:  # snapshot — the latest day in the bucket, never a sum
            value = days[-1][0]

        out.append(Point(
            **base,
            value=value,
            provenance=_fold_provenance([p for _, p in days]),
        ))
    return out


def _days_in(bucket: Bucket) -> list[date]:
    from datetime import timedelta

    return [
        bucket.starts_on + timedelta(days=i)
        for i in range(bucket.days)
    ]


def _recomputed_points(
    db,
    metric: Metric,
    scope: ReportScope,
    buckets: list[Bucket],
    population: Population,
) -> list[Point]:
    """Evaluate the metric over each bucket's own window."""
    out: list[Point] = []
    for bucket in buckets:
        value = metric.evaluate(db, scope, _bucket_window(bucket), population)
        out.append(Point(
            label=bucket.label,
            starts_on=bucket.starts_on,
            ends_on=bucket.ends_on,
            value=value.value,
            provenance=value.qualifiers.get("provenance"),
            unavailable_reason=value.unavailable_reason,
            complete=bucket.complete,
            clipped=bucket.clipped,
            # A recomputed bucket is derived from base rows across the
            # whole span rather than from stored days, so there is no
            # per-day coverage to report. Saying "0 of 7 days" here
            # would describe the storage, not the figure.
            days_present=bucket.days,
            days_expected=bucket.days,
        ))
    return out


def build_series(
    db,
    metric_key: str,
    scope: ReportScope,
    buckets: list[Bucket],
    *,
    population: Population = ALL,
    space_id: str | None = None,
    collective_name: str | None = None,
) -> Series:
    """One metric's chart series, platform-wide or for one Collective.

    ``space_id`` switches both halves of the calculation together, which
    is the point of doing it here rather than at the call site: the
    stored path reads that Collective's own daily rows, and the
    recomputed path evaluates against a scope restricted to it. Setting
    only one of the two would produce a chart labelled with one
    Collective and filled with the platform's figures — and under a
    population filter the recomputed path is the only path, so the bug
    would appear exactly when somebody narrowed to Production.
    """
    metric = REGISTRY.get(metric_key)
    scope.require(metric.access, metric.key)

    if space_id is not None:
        # A creator may only ask about Collectives they manage. These
        # routes are admin-only today; the check lives here so a
        # creator-facing route cannot be one forgotten WHERE away from
        # another creator's figures.
        if not scope.is_platform and space_id not in scope.space_ids:
            raise ScopeDenied(
                f"{metric.key!r} was asked for a Collective outside this scope"
            )
        if "space_id" not in metric.dimensions:
            return _platform_only_series(metric, buckets, space_id, collective_name)

    dimension = (
        space_dimension(space_id) if space_id is not None else PLATFORM_DIMENSION
    )
    series_scope = _one_collective(space_id) if space_id is not None else scope

    use_stored = store_eligible(metric) and population.is_all
    if use_stored:
        points = _stored_points(db, metric, buckets, dimension)
        source = "stored"
    else:
        points = _recomputed_points(
            db, metric, series_scope, buckets, population,
        )
        source = "recomputed"

    quals: dict = dict(population.qualifiers())
    if not population.is_all:
        quals["recompute_note"] = (
            "Recomputed for this population. The nightly aggregates are "
            "stored across every Collective and account, so a filtered "
            "figure has no stored row to read."
        )
    if source == "recomputed" and population.is_all and not store_eligible(metric):
        quals["recompute_note"] = (
            f"{metric.display_name} is {metric.aggregation.value} and is "
            "never stored daily — thirty daily figures would not add up to "
            "a monthly one. Recomputed over each period instead."
        )

    return Series(
        key=metric.key,
        display_name=metric.display_name,
        unit=metric.resolved_unit.value,
        aggregation=metric.aggregation.value,
        source=source,
        points=points,
        collective_id=space_id,
        collective_name=collective_name,
        definition=metric.definition,
        source_of_truth=metric.source_of_truth,
        date_basis=metric.date_basis.value,
        availability=metric.availability.value,
        limitations=metric.limitations,
        observation_only=metric.observation_only,
        qualifiers=quals,
    )


def _one_collective(space_id: str) -> ReportScope:
    """A platform-audience scope restricted to one Collective.

    Platform audience because the asker is an administrator entitled to
    every metric; restricted because the question is about one
    Collective. Those are different axes, and conflating them would
    either hide platform-only metrics from an admin or show a creator
    somebody else's.
    """
    return ReportScope(
        audience=Audience.platform, user_id=None, space_ids=(space_id,),
    )


def _platform_only_series(
    metric: Metric,
    buckets: list[Bucket],
    space_id: str,
    collective_name: str | None,
) -> Series:
    """A metric that has no per-Collective meaning, asked for one.

    Unavailable with a reason rather than an error or, worse, the
    platform figure repeated under each Collective's name — which is
    what a chart comparing Collectives on subscription revenue would
    otherwise show: four identical lines.
    """
    reason = (
        f"{metric.display_name} is measured for the platform as a whole and "
        "cannot be broken down by Collective."
    )
    return Series(
        key=metric.key,
        display_name=metric.display_name,
        unit=metric.resolved_unit.value,
        aggregation=metric.aggregation.value,
        source="recomputed",
        points=[
            Point(
                label=b.label,
                starts_on=b.starts_on,
                ends_on=b.ends_on,
                unavailable_reason=reason,
                complete=b.complete,
                clipped=b.clipped,
                days_expected=b.days,
            )
            for b in buckets
        ],
        collective_id=space_id,
        collective_name=collective_name,
        definition=metric.definition,
        source_of_truth=metric.source_of_truth,
        date_basis=metric.date_basis.value,
        availability=metric.availability.value,
        limitations=metric.limitations,
        observation_only=metric.observation_only,
        qualifiers={"platform_only_metric": reason},
    )


class TooManyBuckets(ValueError):
    """The requested range and grouping would exceed ``MAX_BUCKETS``."""
