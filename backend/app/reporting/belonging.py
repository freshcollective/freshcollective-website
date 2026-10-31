"""Whether people stay, come back, and find more than one home here.

Three behaviours that get conflated and are not interchangeable:
remaining a **member**, returning to **participate**, and belonging to
more than one Collective. A person can keep a membership for a year
without once opening it; another can leave a Collective and be more
present than ever in the one next door. The metrics here keep them
apart, and so does the page.

Membership and person are also kept apart
-----------------------------------------
"Did this membership survive" and "is this person still with Fresh
Collective" are different questions with different answers, and the
difference is the whole point of a platform of many Collectives.
Somebody who leaves one Collective and stays in another has not left.
Every retention figure here says which of the two it means.

What the records can and cannot say
-----------------------------------
``joined_at`` is reliable. ``removed_at`` is reliable **when it is
set** — and a membership marked removed with no removal date is a
departure whose date nobody recorded. Those rows are counted and
reported rather than guessed at or quietly dropped, because a
departure with an unknown date is not the same as no departure.

Before business-event recording began, rejoining overwrote the earlier
membership, so a person who left in March and returned in June looks
like somebody who never left. That inflates retention for any cohort
spanning that period, and it cannot be corrected after the fact — only
disclosed. Rejoins themselves are only knowable from the activation
date onwards, because that is when the event began being written.

None of this is a measure of belonging
--------------------------------------
Belonging is a feeling. These are behaviours that sometimes accompany
it, counted in aggregate, and the page says so. Nothing here reads a
message, a reflection, or the contents of a conversation, and nothing
labels a person as disengaged for participating less often than
somebody else.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.periods import completed_reporting_date, reporting_date_bounds
from app.models.business_event import BusinessEvent
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.reporting.population import (
    ALL,
    DIMENSION as POPULATION_DIMENSION,
    Population,
)
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    Metric,
    MetricValue,
    Unit,
    Window,
)
from app.reporting.scope import Access, ReportScope

#: How many join-months a cohort grid will return. A year of rows is
#: already more than a table can be read at a glance, and the oldest
#: cohorts are the least trustworthy — see the module docstring on
#: rejoining before business-event recording.
MAX_COHORTS = 12

#: How many months after a cohort to measure. Beyond this the grid is
#: mostly blank for a platform of this age.
MAX_OFFSETS = 6


def _narrow_memberships(q, population: Population, scope: ReportScope):
    """Scope and population, applied to a membership query."""
    allowed = scope.space_filter
    if allowed is not None:
        if not allowed:
            return q.where(False)
        q = q.where(SpaceMembership.space_id.in_(allowed))
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.where(SpaceMembership.space_id.in_(spaces))
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.where(SpaceMembership.user_id.notin_(excluded))
    return q


def _held_at(as_at: datetime):
    """Conditions for a membership being in force at a moment.

    A row marked removed with no removal date is excluded from every
    such snapshot — the membership ended and nobody wrote down when, so
    counting it as present would be a guess in the flattering
    direction.
    """
    from sqlalchemy import or_

    return (
        SpaceMembership.joined_at <= as_at,
        or_(
            SpaceMembership.status != SpaceMembershipStatus.removed,
            SpaceMembership.removed_at.isnot(None),
        ),
        or_(
            SpaceMembership.removed_at.is_(None),
            SpaceMembership.removed_at > as_at,
        ),
    )


def _undated_departures(db: Session, population: Population, scope: ReportScope) -> int:
    """Memberships known to have ended on an unknown date."""
    q = _narrow_memberships(
        select(func.count(SpaceMembership.id)).where(
            SpaceMembership.status == SpaceMembershipStatus.removed,
            SpaceMembership.removed_at.is_(None),
        ),
        population, scope,
    )
    return int(db.execute(q).scalar() or 0)


# ---------------------------------------------------------------------------
# Leaving
# ---------------------------------------------------------------------------

def _memberships_ended(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Memberships whose removal date falls in the period.

    Membership-level: somebody leaving two Collectives in a month is
    two endings and one person. ``members_leaving_entirely`` is the
    person-level figure beside it.
    """
    q = _narrow_memberships(
        select(func.count(SpaceMembership.id)).where(
            SpaceMembership.removed_at.isnot(None)
        ),
        population, scope,
    )
    if window.starts_at is not None:
        q = q.where(SpaceMembership.removed_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(SpaceMembership.removed_at < window.ends_at)

    undated = _undated_departures(db, population, scope)
    quals = dict(population.qualifiers())
    if undated:
        quals["departures_without_a_date"] = undated
        quals["undated_note"] = (
            f"{undated} membership(s) are marked as ended with no removal "
            "date recorded. They are real departures and cannot be placed "
            "in any period, so they are absent from every column here "
            "rather than assigned to a guess. This figure is a lower bound."
        )
    return MetricValue(
        key="memberships_ended",
        value=int(db.execute(q).scalar() or 0),
        qualifiers=quals,
    )


def _members_leaving_entirely(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """People who held a membership at the start and none at the end.

    The person-level counterpart to ``memberships_ended``, and the
    distinction that matters most on a platform of many Collectives:
    leaving one Collective while staying in another is not leaving
    Fresh Collective, and a figure that counted it as such would
    describe healthy exploration as churn.
    """
    if window.starts_at is None or window.ends_at is None:
        return MetricValue(
            key="members_leaving_entirely",
            value=None,
            unavailable_reason=(
                "Leaving is a change between two moments, so it is "
                "undefined for all time."
            ),
        )

    def people(as_at: datetime) -> set[str]:
        q = _narrow_memberships(
            select(func.distinct(SpaceMembership.user_id)).where(*_held_at(as_at)),
            population, scope,
        )
        return {r[0] for r in db.execute(q)}

    before = people(window.starts_at)
    after = people(window.ends_at)
    gone = before - after
    return MetricValue(
        key="members_leaving_entirely",
        value=len(gone),
        qualifiers={
            **population.qualifiers(),
            "members_at_start": len(before),
            "members_at_end": len(after),
            "basis": (
                "People holding at least one membership at the start of the "
                "period and none at the end. Leaving one Collective while "
                "remaining in another is not counted here."
            ),
        },
    )


def _memberships_rejoined(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Memberships reactivated in the period, from the recorded event.

    Read from ``business_events`` rather than reconstructed, because it
    cannot be reconstructed: rejoining used to overwrite the earlier
    membership row, so the only evidence a rejoin ever happened is the
    event written at the time. Before recording began there is none,
    and this returns unavailable for those periods rather than zero.
    """
    from app.services.business_event_reconciliation import activation_floor

    floor = activation_floor(db)
    if floor is None:
        return MetricValue(
            key="memberships_rejoined",
            value=None,
            unavailable_reason=(
                "Business-event recording has not begun, so no rejoin has "
                "ever been written down."
            ),
        )
    if window.ends_at is not None and window.ends_at <= floor:
        return MetricValue(
            key="memberships_rejoined",
            value=None,
            unavailable_reason=(
                "This period ends before business-event recording began. "
                "Rejoining overwrote the earlier membership, so whether "
                "anybody rejoined then cannot be established — which is "
                "not the same as nobody having done so."
            ),
        )

    q = select(func.count(BusinessEvent.id)).where(
        BusinessEvent.event_type == "membership_reactivated",
    )
    if window.starts_at is not None:
        q = q.where(BusinessEvent.occurred_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(BusinessEvent.occurred_at < window.ends_at)

    allowed = scope.space_filter
    if allowed is not None:
        if not allowed:
            q = q.where(False)
        else:
            q = q.where(BusinessEvent.space_id.in_(allowed))
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.where(BusinessEvent.space_id.in_(spaces))
    excluded = population.excluded_account_select()
    if excluded is not None:
        from sqlalchemy import or_

        q = q.where(
            or_(
                BusinessEvent.user_id.is_(None),
                BusinessEvent.user_id.notin_(excluded),
            )
        )

    quals = dict(population.qualifiers())
    if window.starts_at is not None and window.starts_at < floor:
        quals["partial_period_note"] = (
            "Part of this period predates business-event recording, so a "
            "rejoin before "
            f"{floor.date().isoformat()} is not in this figure."
        )
    return MetricValue(
        key="memberships_rejoined",
        value=int(db.execute(q).scalar() or 0),
        qualifiers=quals,
    )


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------

def _month_start(year: int, month: int) -> datetime:
    """Naive-UTC instant of local midnight on the 1st.

    Through ``reporting_date_bounds`` so the Australian day and
    daylight saving are honoured in the one place that knows about
    them — a cohort boundary is a local month boundary, not a UTC one.
    """
    return reporting_date_bounds(date(year, month, 1))[0]


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + n
    return total // 12, total % 12 + 1


def _membership_retention_cohorts(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Of the people who joined in month M, how many were still here later?

    Two retentions per cohort, because they answer different
    questions:

    * **in the Collective they joined** — did that membership survive;
    * **anywhere in Fresh Collective** — is the person still a member
      of something.

    The second is never smaller than the first, and the gap between
    them is people who moved rather than left.

    A milestone is reported only once the moment it measures has
    actually passed. A cohort that joined last month has no
    three-month figure, and that is ``null`` — not zero, and not a
    failure. Treating an unreached milestone as a miss is the single
    easiest way to make a growing platform look like a leaking one.
    """
    last_complete = completed_reporting_date(datetime.utcnow())

    first_join = db.execute(
        _narrow_memberships(
            select(func.min(SpaceMembership.joined_at)), population, scope,
        )
    ).scalar()
    if first_join is None:
        return MetricValue(
            key="membership_retention_cohorts",
            value=None,
            unavailable_reason="No memberships yet, so there are no cohorts.",
        )

    # Cohort months run from the first join to the last complete month,
    # capped so the payload stays readable.
    months: list[tuple[int, int]] = []
    y, m = first_join.year, first_join.month
    while (y, m) <= (last_complete.year, last_complete.month):
        months.append((y, m))
        y, m = _add_months(y, m, 1)
    months = months[-MAX_COHORTS:]

    cohorts = []
    for cy, cm in months:
        start = _month_start(cy, cm)
        ny, nm = _add_months(cy, cm, 1)
        end = _month_start(ny, nm)

        joined_rows = db.execute(
            _narrow_memberships(
                select(SpaceMembership.user_id, SpaceMembership.space_id).where(
                    SpaceMembership.joined_at >= start,
                    SpaceMembership.joined_at < end,
                ),
                population, scope,
            )
        ).fetchall()
        if not joined_rows:
            continue
        people = {r[0] for r in joined_rows}
        pairs = {(r[0], r[1]) for r in joined_rows}

        offsets: list[dict] = []
        for k in range(1, MAX_OFFSETS + 1):
            oy, om = _add_months(cy, cm, k + 1)
            as_at = _month_start(oy, om)
            if as_at.date() > last_complete:
                # The milestone has not arrived. Null, never zero.
                offsets.append({
                    "months_after": k,
                    "retained_in_collective": None,
                    "retained_anywhere": None,
                    "reached": False,
                })
                continue

            held = db.execute(
                _narrow_memberships(
                    select(
                        SpaceMembership.user_id, SpaceMembership.space_id
                    ).where(*_held_at(as_at)),
                    population, scope,
                )
            ).fetchall()
            still_pairs = {(r[0], r[1]) for r in held}
            still_people = {r[0] for r in held}
            offsets.append({
                "months_after": k,
                "retained_in_collective": len(pairs & still_pairs),
                "retained_anywhere": len(people & still_people),
                "reached": True,
            })

        cohorts.append({
            "cohort": f"{cy:04d}-{cm:02d}",
            "memberships_started": len(pairs),
            "people_joined": len(people),
            "offsets": offsets,
        })

    undated = _undated_departures(db, population, scope)
    return MetricValue(
        key="membership_retention_cohorts",
        value=len(cohorts),
        qualifiers={
            **population.qualifiers(),
            "cohorts": cohorts,
            "max_offsets": MAX_OFFSETS,
            "basis": (
                "A cohort is everyone who joined in that calendar month, "
                "Australian time. 'After N months' is measured at the start "
                "of the month N months after the cohort month ends, and is "
                "reported only once that moment has passed."
            ),
            "undated_departures": undated,
            "limitation": (
                "Reconstructed from membership rows. Rejoining overwrote "
                "the earlier membership before business-event recording "
                "began, so a person who left and came back during a cohort's "
                "life looks as though they never left — which overstates "
                "retention for the older cohorts and cannot be corrected "
                "after the fact."
                + (
                    f" A further {undated} membership(s) ended on a date "
                    "nobody recorded; they are treated as still held, which "
                    "overstates retention by at most that many."
                    if undated else ""
                )
            ),
        },
    )


# ---------------------------------------------------------------------------
# Belonging in more than one place
# ---------------------------------------------------------------------------

def _multi_collective_participants(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """People who participated in two or more Collectives in the period.

    Not the same as belonging to two — belonging is a membership and
    this is an act. Somebody in three Collectives who only ever posts
    in one is counted here as participating in one, which is the
    distinction the overlap figures cannot make.
    """
    from app.reporting.engagement import _scoped, _windowed, participation_events

    part = participation_events()
    q = select(part.c.user_id, func.count(func.distinct(part.c.space_id)))
    q = _windowed(_scoped(q.select_from(part), part, scope, population), part, window)
    rows = db.execute(q.group_by(part.c.user_id)).fetchall()
    return MetricValue(
        key="multi_collective_participants",
        value=sum(1 for _, n in rows if n > 1),
        qualifiers={
            **population.qualifiers(),
            "participated_anywhere": len(rows),
            "basis": (
                "Counts where somebody acted, not where they belong. A "
                "member of three Collectives who posts in one participated "
                "in one."
            ),
        },
    )


# ---------------------------------------------------------------------------

REGISTRY.add(Metric(
    key="memberships_ended",
    display_name="Memberships ended",
    definition=(
        "Memberships whose recorded removal date falls in the period. "
        "Counts memberships, not people — somebody leaving two Collectives "
        "is two endings."
    ),
    source_of_truth="space_memberships.removed_at",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.created,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "A membership marked as ended with no removal date cannot be "
        "placed in any period and is absent from every one of them, so "
        "this is a lower bound. The count of such rows travels with the "
        "figure."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    compute=_memberships_ended,
))

REGISTRY.add(Metric(
    key="members_leaving_entirely",
    display_name="People leaving Fresh Collective",
    definition=(
        "People who held at least one membership at the start of the "
        "period and none at the end. Leaving one Collective while "
        "remaining in another is not counted."
    ),
    source_of_truth="space_memberships.joined_at / removed_at, as-at both ends",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.none,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Rests on removal dates, so a departure nobody dated is invisible "
        "here and the figure is a lower bound. Undefined for all time, "
        "which has no two moments to compare."
    ),
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_members_leaving_entirely,
))

REGISTRY.add(Metric(
    key="memberships_rejoined",
    display_name="Memberships rejoined",
    definition=(
        "Memberships reactivated during the period, counted from the "
        "lifecycle event recorded at the time."
    ),
    source_of_truth="business_events where event_type = membership_reactivated",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.from_instrumentation,
    limitations=(
        "Only knowable from the day business-event recording began. "
        "Rejoining used to overwrite the earlier membership, so for "
        "periods before that the answer is unavailable rather than zero — "
        "nobody wrote it down, which is not evidence that nobody rejoined."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    compute=_memberships_rejoined,
))

REGISTRY.add(Metric(
    key="membership_retention_cohorts",
    display_name="Membership retention by joining month",
    definition=(
        "For each month, the people who joined in it and how many were "
        "still members later — both of the Collective they joined and of "
        "Fresh Collective anywhere."
    ),
    source_of_truth="space_memberships.joined_at / removed_at, reconstructed as-at",
    grain=Grain.snapshot,
    # The value is the number of cohorts; the grid is in the qualifiers,
    # and neither can be summed or averaged across periods.
    aggregation=Aggregation.distinct_count,
    unit=Unit.count,
    # ``none``, not ``membership_joined``. The grid is not attributed
    # to a reporting period at all — it describes the present state of
    # every past cohort, and the join date groups the rows rather than
    # placing the figure in a window. A snapshot that attributed by a
    # row date would be a flow wearing the wrong label.
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "Reconstructed from membership rows. Rejoining overwrote the "
        "earlier membership before business-event recording began, so a "
        "person who left and returned during a cohort's life looks as "
        "though they never left — the older cohorts overstate retention. "
        "A milestone is reported only once it has been reached; an "
        "unreached one is blank, never zero."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    personal_data=True,
    compute=_membership_retention_cohorts,
))

REGISTRY.add(Metric(
    key="multi_collective_participants",
    display_name="People participating in more than one Collective",
    definition=(
        "People who did something in two or more Collectives during the "
        "period. Participation, not membership."
    ),
    source_of_truth="the participation union — see app.reporting.engagement",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.platform_only,
    availability=Availability.from_instrumentation,
    limitations=(
        "Counts where somebody acted, not where they belong — read beside "
        "the membership overlap figures, which count the opposite. "
        "Non-additive: recompute over the window asked for."
    ),
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_multi_collective_participants,
))
