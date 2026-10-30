"""One definition per metric, and the number comes with it.

The problem this solves is already in the codebase: two admin endpoints
compute "revenue in a period" from different columns — ``created_at`` in
``_compute_revenue_summary``, ``updated_at`` in the Mother World fields
of ``/platform/overview`` — so today's figure and this month's figure
disagree about the same payment. That is not carelessness; it is what
happens when two endpoints each write their own query for the same idea
six months apart.

A registry makes that impossible by construction. Each metric is declared
once, with its prose definition, its source, the timestamp it attributes
by, how it may be aggregated, what it cannot tell you yet, and who may
see it. The API returns that declaration beside the value, so "what does
this number mean and where does it come from" is answered by the
response rather than by a document that drifts.

What this module is **not**: a second financial ledger. The money metrics
read ``payment_transactions`` and reuse the arithmetic the payment system
already decided — gross, platform fee, creator net, refund reversals.
Nothing here re-prices anything.

Aggregation is a declared property, not an assumption
----------------------------------------------------
``ADDITIVE`` metrics may be summed across days. ``DISTINCT_COUNT``
metrics may not: thirty daily unique-member counts do not make a monthly
unique-member count, because the same person appears on many days. Those
are recomputed over the requested window from base rows, and
``aggregate_across`` refuses to add them. The same property is what makes
multi-Collective reporting safe — a member of three Collectives is one
unique member at the creator level, not three.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.reporting.population import ALL, DIMENSION as POPULATION_DIMENSION
from app.reporting.population import Population
from app.reporting.scope import Access, ReportScope


class Grain(str, enum.Enum):
    """What one value describes."""

    #: A state at a moment — "how many active Collectives right now".
    #: A period filter narrows what is counted, not when it is measured.
    snapshot = "snapshot"
    #: Activity within a window — "gross sales this month".
    period = "period"


class Aggregation(str, enum.Enum):
    #: Safe to sum across adjacent periods.
    additive = "additive"
    #: A count of distinct people or things. **Never summable** — must be
    #: recomputed over whatever window is asked for.
    distinct_count = "distinct_count"
    #: Derived from two other metrics. Recompute, never average.
    ratio = "ratio"
    #: A point-in-time state. Take the latest, never add.
    snapshot = "snapshot"


class DateBasis(str, enum.Enum):
    """Which timestamp attributes a row to a reporting period.

    The heart of the financial correction. One basis for everything is
    what produced the inconsistency; each metric now names its own.
    """

    #: Observed payment settlement, falling back to ``created_at`` for
    #: rows that predate BI-1. Results say which applied — see
    #: ``MetricValue.qualifiers['settlement_basis']``.
    payment_settled = "payment_settled"
    #: When money went back. A refund belongs to the period it happened
    #: in, so a closed month's revenue does not move afterwards.
    refunded = "refunded"
    #: When a payout was actually marked paid — a cash movement, which is
    #: a different question from what a creator has earned.
    payout_marked = "payout_marked"
    #: Row creation. Correct for things whose creation *is* the event.
    created = "created"
    #: A membership's own join date.
    membership_joined = "membership_joined"
    #: An append-only business event's ``occurred_at``.
    business_event = "business_event"
    #: Not time-attributed at all.
    none = "none"


class Availability(str, enum.Enum):
    #: Reliable for all history.
    full = "full"
    #: Reliable only from a point in time — typically BI-1 activation.
    from_instrumentation = "from_instrumentation"
    #: Computable, with a caveat the result carries.
    partial = "partial"


class Provenance(str, enum.Enum):
    """How a stored daily figure came to be known.

    Written into ``metric_daily.provenance`` and guarded by a CHECK
    constraint, so this enum and the constraint must agree. They did not
    once: ``observed_late`` was introduced with the observation-only
    snapshots and the constraint still listed two values, which failed
    the first nightly run with a ``CheckViolation``. The unit tests
    evaluated the metric without ever storing the result, so nothing
    noticed.

    ``test_reporting_schema_contract.py`` now inserts every member of
    this enum against the real database, which is the only check that
    could have caught it.
    """

    #: Measured directly, at the time it describes.
    observed = "observed"
    #: Measured directly but after the day it describes — a missed night
    #: repaired by the following one. The only observation that will ever
    #: exist for that day, and labelled rather than passed off as timely.
    observed_late = "observed_late"
    #: Worked out from current rows rather than from recorded events.
    #: Exact where the events exist, an approximation before that.
    reconstructed = "reconstructed"


class Unit(str, enum.Enum):
    """What kind of quantity a metric's number is.

    Separate from :class:`Aggregation` on purpose. Aggregation says how
    values combine; a unit says how one is *read*. Conflating them
    produced a real misreport: ``memberships_per_member`` aggregates as
    a ratio, the dashboard inferred "ratio means percentage", and 1.83
    memberships per person appeared as **183%**.

    A ratio of two unlike things is a rate and reads as a decimal. A
    ratio of a part to its whole is a proportion and reads as a
    percentage. Only the metric knows which it is, so it says.
    """

    #: A whole number of things — people, memberships, Collectives.
    count = "count"
    #: An integer number of cents, formatted as currency.
    money_cents = "money_cents"
    #: A part of a whole, between 0 and 1. Read as a percentage.
    proportion = "proportion"
    #: One quantity per another unlike quantity. Read as a decimal.
    rate = "rate"


@dataclass(frozen=True)
class Window:
    """A half-open ``[starts_at, ends_at)`` period in naive UTC.

    Produced by ``app.core.periods`` so the Australian financial year and
    the platform timezone are honoured in exactly one place. ``None`` on
    both sides means all time.
    """

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    label: str = "all time"

    @property
    def is_all_time(self) -> bool:
        return self.starts_at is None and self.ends_at is None


@dataclass
class MetricValue:
    """A number, and everything needed to trust it."""

    key: str
    value: int | float | None
    #: Set when the value could not be computed, instead of returning a
    #: misleading zero. A dashboard shows this rather than "0".
    unavailable_reason: str | None = None
    #: Facts about *this* result — which settlement basis applied, how
    #: many rows were excluded for a missing fee, and so on.
    qualifiers: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


@dataclass(frozen=True)
class Metric:
    """The authoritative declaration of one business metric."""

    key: str
    display_name: str
    #: Prose, written for the person reading the dashboard. Returned by
    #: the API beside the value.
    definition: str
    #: The table(s) the number actually comes from.
    source_of_truth: str
    grain: Grain
    aggregation: Aggregation
    date_basis: DateBasis
    access: Access
    availability: Availability
    #: What this metric cannot tell you, stated plainly. Shown next to
    #: the figure rather than discovered later.
    limitations: str | None = None
    #: How the number reads. Left unset it is inferred from the key —
    #: ``*_cents`` is money, anything else a count — which is right for
    #: every metric that does not say otherwise. A proportion or a rate
    #: must declare itself, because neither can be guessed from a value
    #: without being wrong half the time.
    unit: Unit | None = None
    #: True for a snapshot that can only ever be *observed*, never
    #: reconstructed from a past date.
    #:
    #: ``unique_members`` is reconstructable: membership rows carry
    #: ``joined_at`` and ``removed_at``, so last March's figure can be
    #: worked out today. A Collective's status is not — ``spaces.status``
    #: holds one value with no history behind it, and a creation date is
    #: not a publication date. Asked for a past day, such a metric
    #: returns unavailable rather than today's count wearing yesterday's
    #: date, and the daily row is written once by the run that genuinely
    #: observed the day rather than overwritten by every later rebuild.
    observation_only: bool = False
    #: Filters the calculation honours, beyond the period.
    dimensions: tuple[str, ...] = ()
    #: True when the value is about identifiable people and should not
    #: be exported casually. No metric exposes member-authored content.
    personal_data: bool = False
    compute: (
        Callable[[Session, ReportScope, Window, Population], MetricValue] | None
    ) = None

    @property
    def resolved_unit(self) -> Unit:
        """The declared unit, or the one the key implies."""
        if self.unit is not None:
            return self.unit
        return Unit.money_cents if self.key.endswith("_cents") else Unit.count

    @property
    def honours_population(self) -> bool:
        """Whether this metric filters by reporting classification.

        Declared, not detected. A metric that ignored a population
        filter while the surface above it displayed "Production" would
        be the worst failure available here — a figure labelled as a
        subset that is actually the whole, which no reader could catch.
        """
        return POPULATION_DIMENSION in self.dimensions

    def evaluate(
        self,
        db: Session,
        scope: ReportScope,
        window: Window,
        population: Population = ALL,
    ) -> MetricValue:
        """Check entitlement, then compute. The only way to get a value."""
        scope.require(self.access, self.key)
        if self.compute is None:  # pragma: no cover - guarded by a test
            return MetricValue(
                key=self.key,
                value=None,
                unavailable_reason="This metric has no calculation yet.",
            )
        if not population.is_all and not self.honours_population:
            # Unavailable rather than an exception, and rather than an
            # unfiltered number. A chart asking for eight metrics under
            # one filter should show a gap for the one that cannot
            # honour it, not fail the panel and not quietly mislabel.
            return MetricValue(
                key=self.key,
                value=None,
                unavailable_reason=(
                    f"{self.display_name} cannot be narrowed by reporting "
                    f"class, so there is no {population.label!r} figure for "
                    "it. Switch to All activity to see this metric."
                ),
                qualifiers=population.qualifiers(),
            )
        return self.compute(db, scope, window, population)


class MetricRegistry:
    """The catalogue. One instance, built at import time."""

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def add(self, metric: Metric) -> Metric:
        if metric.key in self._metrics:
            raise ValueError(f"duplicate metric key {metric.key!r}")
        self._metrics[metric.key] = metric
        return metric

    def get(self, key: str) -> Metric:
        try:
            return self._metrics[key]
        except KeyError:
            raise UnknownMetric(key) from None

    def all(self) -> list[Metric]:
        return [self._metrics[k] for k in sorted(self._metrics)]

    def visible_to(self, scope: ReportScope) -> list[Metric]:
        return [m for m in self.all() if scope.may_see(m.access)]

    def __contains__(self, key: object) -> bool:
        return key in self._metrics

    def __len__(self) -> int:
        return len(self._metrics)


class UnknownMetric(KeyError):
    """No metric is declared under that key."""


def aggregate_across(metric: Metric, values: list[int | float]) -> int | float:
    """Combine per-period values — only where that is meaningful.

    Exists to make the wrong thing raise. Summing daily unique members
    into a monthly figure is the single easiest way to publish a
    confidently wrong number, so a non-additive metric refuses rather
    than quietly double-counting a person who showed up on Tuesday and
    again on Thursday.
    """
    if metric.aggregation is Aggregation.additive:
        return sum(values)
    if metric.aggregation is Aggregation.snapshot:
        return values[-1] if values else 0
    raise NonAdditiveMetric(
        f"{metric.key!r} is {metric.aggregation.value} and cannot be combined "
        "by addition — recompute it over the whole window instead"
    )


class NonAdditiveMetric(TypeError):
    """Somebody tried to add up something that does not add up."""


#: The single registry instance. Populated by ``app.reporting.metrics``,
#: which is imported for its side effect at the bottom of that module.
REGISTRY = MetricRegistry()
