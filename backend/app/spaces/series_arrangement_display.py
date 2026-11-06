"""Stage 1B.2B — the member Series "Ways to Join" list, from the resolver.

The same cards, the same prices, the same checkout. A different source
for the purchase-arrangement data behind them.

Why a second builder at all
---------------------------
``_member_purchasable_options_for_series`` answers "which Payment
Options can a member buy for this Series" by querying options, grants
and schedules and then applying the checkoutability predicate. That is
the fourth place in the system to have reconstructed what an experience
costs, and the reason the resolver exists.

This module produces the **same output shape** from
``arrangements_for``, so the endpoint can swap its source behind a flag
without the response — or the frontend, or checkout — changing at all.
The shadow comparison (Stage 1B.2A) is what earns the right to do that:
it has already shown the two agree across 18 Option/schedule shapes in
both states of the instalment flag, and in production.

What is *not* here
------------------
**Eligibility.** The resolver answers what the creator configured, not
who may buy it. ``viewer_holds_this_option`` and the recovery-plan state
stay with the endpoint, reading the viewer's AccessPasses exactly as
before. A member who already holds an Option is still not asked to buy
it again.

**Checkout.** Nothing here prices a purchase. It carries the
``payment_option_id`` and ``payment_option_schedule_id`` the member
hands back, unchanged, so the arrangement displayed is the arrangement
checkout re-derives and charges.

Mapping the legacy payload's shape
----------------------------------
The legacy payload has two behaviours worth naming, because matching
them is most of this module:

1. **Every published schedule ships**, including ones a member cannot
   complete, each carrying ``is_member_checkoutable``. The frontend
   filters on that flag and never on ``schedule_type``. So a draft
   schedule is dropped and an unbuyable published one is kept-but-false.
2. **The option only appears at all** when at least one of its
   schedules is checkoutable. An option whose every schedule is
   unavailable is absent, not greyed out.

The resolver describes everything and labels why, so the mapping is a
question of which reasons mean "drop the row", which mean "drop the
whole option", and which mean "show it, unbuyable". That table is
:data:`OPTION_LEVEL_REASONS` and :data:`HIDDEN_SCHEDULE_REASONS` below —
written out rather than inferred, because getting it wrong would either
hide an arrangement a member can buy or advertise one they cannot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.services.purchase_arrangements import (
    KIND_SERIES,
    REASON_OPTION_ARCHIVED,
    REASON_OPTION_DRAFT,
    REASON_SCHEDULE_DRAFT,
    REASON_UNSUPPORTED_INCLUSION,
    SOURCE_PAYMENT_OPTION,
    Arrangement,
    arrangements_for,
)

logger = logging.getLogger(__name__)

#: Reasons that disqualify the **whole Payment Option**, not one of its
#: schedules. The legacy query never returns these options at all —
#: draft and archived are filtered in SQL, and an option carrying a
#: Gathering grant is skipped by Stage 0's shared rule — so a
#: resolver-backed payload must omit them too rather than render a card
#: the member could not use.
OPTION_LEVEL_REASONS: frozenset[str] = frozenset({
    REASON_OPTION_DRAFT,
    REASON_OPTION_ARCHIVED,
    REASON_UNSUPPORTED_INCLUSION,
})

#: Reasons that hide a single schedule row. The legacy schedule query
#: is ``status == 'published'``, so a draft schedule is absent from the
#: payload entirely rather than present and unbuyable.
HIDDEN_SCHEDULE_REASONS: frozenset[str] = frozenset({
    REASON_SCHEDULE_DRAFT,
})


@dataclass(frozen=True)
class DisplaySchedule:
    """One payment method, in the member payload's own field names.

    Mirrors ``MemberPaymentOptionScheduleOut`` so the endpoint can
    construct that model from this without a translation step — and so
    a field added to one surfaces as a type error rather than as a
    silently missing value.
    """

    id: str
    name: str
    schedule_type: str
    total_amount_cents: int
    installment_amount_cents: int | None
    installment_count: int | None
    interval: str | None
    currency: str
    is_member_checkoutable: bool

    def as_payload(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule_type": self.schedule_type,
            "total_amount_cents": self.total_amount_cents,
            "installment_amount_cents": self.installment_amount_cents,
            "installment_count": self.installment_count,
            "interval": self.interval,
            "currency": self.currency,
            "is_member_checkoutable": self.is_member_checkoutable,
        }


@dataclass(frozen=True)
class DisplayOption:
    """One Payment Option card."""

    id: str
    name: str
    description: str | None
    allowance_per_week: int | None
    allowance_total: int | None
    included_titles: list[str]
    schedules: list[DisplaySchedule]


def _schedule_from(arrangement: Arrangement) -> DisplaySchedule:
    """One arrangement as one schedule row.

    ``total_amount_cents`` is coerced from ``None`` to ``0`` because the
    legacy ``schedule_view`` does the same (``schedule.total_amount_cents
    or 0``). Matching it matters: the shadow comparison normalises the
    same way, and a surface that showed ``null`` where the other showed
    ``0`` would be a difference in the payload with no difference in the
    price.

    ``installment_amount_cents`` is carried as the resolver reports it —
    which for a plan is what Stripe's subscription price actually
    charges. The schedule's stored ``upfront_amount_cents`` is
    deliberately *not* consulted: nothing collects it, and reporting it
    as a first charge was the discrepancy corrected in 7a21fab.
    """
    return DisplaySchedule(
        id=arrangement.payment_option_schedule_id or "",
        name=arrangement.schedule_name or "",
        schedule_type=arrangement.schedule_type,
        total_amount_cents=arrangement.total_amount_cents or 0,
        installment_amount_cents=arrangement.installment_amount_cents,
        installment_count=arrangement.installment_count,
        interval=arrangement.interval,
        currency=arrangement.currency,
        is_member_checkoutable=arrangement.available_for_new_purchase,
    )


def _allowances(arrangement: Arrangement, series_id: str) -> tuple[int | None, int | None]:
    """The Series-grant allowance this Option carries, for the card's
    "2/week · 20 total" line.

    Read from the ``IncludedExperience`` for *this* Series rather than
    the first grant on the Option, so a bundle covering two Series
    cannot print the wrong one's allowance.
    """
    for included in arrangement.included:
        if included.kind == KIND_SERIES and included.experience_id == series_id:
            return included.sessions_per_week, included.total_sessions
    return None, None


def _included_titles(arrangement: Arrangement, series_id: str) -> list[str]:
    """"Includes EMBODY Term 4 2026 · The EMBODY Practice".

    **The Series being viewed comes first**, then everything else in the
    resolver's order. Both halves of that matter:

    * The legacy builder starts its list with ``series.title`` and
      appends the other grant titles, so matching it keeps the card's
      text identical.
    * The resolver returns ``included`` in grant *query* order, which is
      not deterministic — an equivalence test caught this ordering
      flipping between runs. Depending on it would have shipped a card
      whose "Includes" line read differently depending on nothing a
      member could see.

    Leading with the Series is also simply the right sentence: the
    member is looking at that Series, and the rest is what comes with
    it.
    """
    titles = [inc.title for inc in arrangement.included if inc.title]
    this_series = [
        inc.title for inc in arrangement.included
        if inc.kind == KIND_SERIES
        and inc.experience_id == series_id
        and inc.title
    ]
    if not this_series:
        return titles
    head = this_series[0]
    return [head] + [t for t in titles if t != head]


def build_display_options(
    db: Session, *, series_id: str,
) -> list[DisplayOption]:
    """The Ways to Join cards for one Series, from the resolver.

    Order is the resolver's: the creator's own Option ``position``, then
    schedule ``position`` — the same ordering the legacy query applies,
    so the Reorder control in Creator Studio keeps working.
    """
    found = arrangements_for(db, kind=KIND_SERIES, experience_id=series_id)
    if found is None:
        return []

    # Group by Option, preserving the resolver's order.
    order: list[str] = []
    grouped: dict[str, list[Arrangement]] = {}
    dropped_options: set[str] = set()

    for arrangement in found.arrangements:
        if arrangement.source != SOURCE_PAYMENT_OPTION:
            # A Series carries no direct price. Defensive.
            continue
        option_id = arrangement.payment_option_id
        if option_id is None or arrangement.payment_option_schedule_id is None:
            continue
        if arrangement.unavailable_reason in OPTION_LEVEL_REASONS:
            dropped_options.add(option_id)
            continue
        if arrangement.unavailable_reason in HIDDEN_SCHEDULE_REASONS:
            continue
        if option_id not in grouped:
            grouped[option_id] = []
            order.append(option_id)
        grouped[option_id].append(arrangement)

    # An option disqualified by any one of its arrangements is
    # disqualified entirely — the reasons in OPTION_LEVEL_REASONS are
    # properties of the Option, so they apply to every schedule on it,
    # and a partial render would be a card the member cannot use.
    for option_id in dropped_options:
        grouped.pop(option_id, None)
    order = [o for o in order if o in grouped]
    if not order:
        return []

    # Descriptions are Collective prose rather than a property of an
    # arrangement, so they are read here rather than widened onto the
    # resolver. One query for the options the resolver already chose.
    descriptions = dict(
        db.query(PaymentOption.id, PaymentOption.description)
        .filter(PaymentOption.id.in_(order))
        .all()
    )

    out: list[DisplayOption] = []
    for option_id in order:
        arrangements = grouped[option_id]
        schedules = [_schedule_from(a) for a in arrangements]
        # The legacy payload omits an Option with nothing a member can
        # complete. Matching that is what keeps the two displays
        # identical for every existing arrangement.
        if not any(s.is_member_checkoutable for s in schedules):
            continue
        first = arrangements[0]
        per_week, total = _allowances(first, series_id)
        out.append(DisplayOption(
            id=option_id,
            name=first.name,
            description=descriptions.get(option_id),
            allowance_per_week=per_week,
            allowance_total=total,
            included_titles=_included_titles(first, series_id),
            schedules=schedules,
        ))
    return out


__all__ = [
    "HIDDEN_SCHEDULE_REASONS",
    "OPTION_LEVEL_REASONS",
    "DisplayOption",
    "DisplaySchedule",
    "build_display_options",
]
