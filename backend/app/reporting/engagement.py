"""Participation, measured from what people actually did.

Fresh Collective records no page views and no sessions, and nothing here
adds any. That turns out to be an advantage rather than a gap: it forces
engagement to mean *participation* — a deliberate act that left a
timestamped record — which is the thing worth knowing about anyway. A
member who opened the app and read for an hour is not measured here, and
a member who posted once is.

The primitive
-------------
``participation_events()`` is a UNION of the six acts that count, each
reduced to the same three columns: who, which Collective, and when.
Every engagement metric is then a question asked of that one relation,
which is what keeps "active member" meaning the same thing in a
platform-wide figure and in a single Collective's figure.

Six acts, deliberately
----------------------
Posting, commenting, reacting, attending a Gathering, completing a
Pathway step, and purchasing. Booking without attending is **not**
participation — it is intent, reported separately, and the gap between
the two is its own signal.

No composite score
------------------
Scores hide their weightings and stop being questionable, which is
exactly when they start being wrong. Counts and rates, each traceable to
the acts that produced it.

Privacy
-------
Only identifiers and timestamps are read. Post bodies, comment bodies,
Pathway reflections, exercise responses and message content are never
touched — the union selects no text column at all, and a test asserts
that.

Two timestamp decisions worth knowing
-------------------------------------
``event_bookings.attendance_marked_at`` is ``timestamptz`` while every
other timestamp in this database is naive UTC, so comparing it to a
window boundary would be resolved in the database session's timezone —
the same trap that put BI-1's ``recorded_at`` eleven hours out.
Attendance is therefore dated by the **Gathering's own ``starts_at``**,
which is naive like everything else and is also the more meaningful
answer: it is when the person actually attended, not when a creator got
round to marking the register.

``step_progress`` has no start timestamp, only ``completed_at``, so
time-to-complete is not available for any period and is not offered.
"""

from __future__ import annotations

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
)
from app.models.platform import (
    CommunityPost,
    Event,
    EventBooking,
    Pathway,
    PathwayStep,
    PostComment,
    PostReaction,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    StepProgress,
)
from app.reporting.dates import settlement_date
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    Metric,
    MetricValue,
    Window,
)
from app.reporting.population import ALL, Population
from app.reporting.scope import Access, ReportScope

#: The acts that count as participation, as reported in qualifiers so a
#: figure can always be broken down into what produced it.
PARTICIPATION_KINDS = (
    "conversation_post",
    "conversation_comment",
    "conversation_reaction",
    "gathering_attendance",
    "pathway_step",
    "purchase",
)


def participation_events():
    """``(user_id, space_id, occurred_at, kind)`` for every act of
    participation, as a selectable.

    Built with UNION ALL rather than UNION: duplicates across sources are
    impossible (an act appears in exactly one branch) and the distinct
    counting happens in the metrics that need it, where it is explicit.
    """
    posts = select(
        CommunityPost.author_id.label("user_id"),
        CommunityPost.space_id.label("space_id"),
        CommunityPost.created_at.label("occurred_at"),
        literal("conversation_post").label("kind"),
    )

    comments = (
        select(
            PostComment.author_id.label("user_id"),
            CommunityPost.space_id.label("space_id"),
            PostComment.created_at.label("occurred_at"),
            literal("conversation_comment").label("kind"),
        )
        .join(CommunityPost, CommunityPost.id == PostComment.post_id)
    )

    reactions = (
        select(
            PostReaction.user_id.label("user_id"),
            CommunityPost.space_id.label("space_id"),
            PostReaction.created_at.label("occurred_at"),
            literal("conversation_reaction").label("kind"),
        )
        .join(CommunityPost, CommunityPost.id == PostReaction.post_id)
    )

    # Attendance, dated by the Gathering rather than by when the register
    # was marked — see the module docstring.
    attendance = (
        select(
            EventBooking.user_id.label("user_id"),
            Event.space_id.label("space_id"),
            Event.starts_at.label("occurred_at"),
            literal("gathering_attendance").label("kind"),
        )
        .join(Event, Event.id == EventBooking.event_id)
        .where(EventBooking.attendance_status == "attended")
    )

    steps = (
        select(
            StepProgress.user_id.label("user_id"),
            Pathway.space_id.label("space_id"),
            StepProgress.completed_at.label("occurred_at"),
            literal("pathway_step").label("kind"),
        )
        .join(PathwayStep, PathwayStep.id == StepProgress.step_id)
        .join(Pathway, Pathway.id == PathwayStep.pathway_id)
        .where(StepProgress.completed_at.isnot(None))
    )

    purchases = select(
        PaymentTransaction.payer_user_id.label("user_id"),
        PaymentTransaction.space_id.label("space_id"),
        settlement_date().label("occurred_at"),
        literal("purchase").label("kind"),
    ).where(
        PaymentTransaction.payer_user_id.isnot(None),
        PaymentTransaction.status.in_(
            [
                PaymentTransactionStatus.succeeded.value,
                PaymentTransactionStatus.partially_refunded.value,
            ]
        ),
    )

    return union_all(
        posts, comments, reactions, attendance, steps, purchases
    ).subquery("participation")


def _scoped(q, part, scope: ReportScope):
    if scope.is_platform:
        return q
    if not scope.space_ids:
        return q.where(literal(False))
    return q.where(part.c.space_id.in_(scope.space_ids))


def _windowed(q, part, window: Window):
    if window.starts_at is not None:
        q = q.where(part.c.occurred_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(part.c.occurred_at < window.ends_at)
    return q


def _active_people(
    db: Session, scope: ReportScope, window: Window, *, creators_only: bool = False,
) -> int:
    part = participation_events()
    q = select(func.count(func.distinct(part.c.user_id))).select_from(part)
    q = _windowed(_scoped(q, part, scope), part, window)
    if creators_only:
        from app.models.user import User

        q = q.where(
            part.c.user_id.in_(select(User.id).where(User.role == "creator"))
        )
    return int(db.execute(q).scalar() or 0)


# ---------------------------------------------------------------------------
# Active people
# ---------------------------------------------------------------------------

def _active_members(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    part = participation_events()
    total = _active_people(db, scope, window)
    by_kind = db.execute(
        _windowed(
            _scoped(
                select(part.c.kind, func.count(func.distinct(part.c.user_id)))
                .select_from(part)
                .group_by(part.c.kind),
                part,
                scope,
            ),
            part,
            window,
        )
    ).fetchall()
    return MetricValue(
        key="active_members",
        value=total,
        qualifiers={
            # Per-kind distinct counts, which do NOT sum to the total —
            # one person posting and attending appears in both. Reported
            # so a figure can be explained, not so it can be added up.
            "distinct_people_by_kind": {k: int(n) for k, n in by_kind},
            "note": (
                "Per-kind counts overlap and must not be summed. A person "
                "who posted and attended appears under both."
            ),
        },
    )


REGISTRY.add(Metric(
    key="active_members",
    display_name="Active members",
    definition=(
        "Distinct people who participated in the period — posted, commented "
        "or reacted in a Conversation, attended a Gathering, completed a "
        "Pathway step, or made a purchase. Booking without attending does "
        "not count; viewing a page is not recorded at all."
    ),
    source_of_truth=(
        "union of community_posts, post_comments, post_reactions, "
        "event_bookings (attended), step_progress, payment_transactions"
    ),
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations=(
        "Non-additive: a 30-day figure must be recomputed over 30 days, "
        "never summed from daily figures. Measures participation, not "
        "visits — no page views or sessions are recorded."
    ),
    dimensions=("space_id",),
    personal_data=True,
    compute=_active_members,
))


def _active_creators(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creators who participated, plus those who published.

    Publishing is a creator's characteristic act and lives in
    ``activities`` rather than in the participation union, so it is
    counted here as well — a creator who published a Pathway and did
    nothing else was certainly active.
    """
    from app.models.activity import Activity

    part = participation_events()
    q = select(func.distinct(part.c.user_id)).select_from(part)
    participating = {
        r[0] for r in db.execute(_windowed(_scoped(q, part, scope), part, window))
    }

    pub = select(func.distinct(Activity.actor_user_id)).where(
        Activity.actor_user_id.isnot(None),
        Activity.event_type.in_([
            "pathway_published", "pathway_step_released",
            "conversation_created", "gathering_created",
        ]),
    )
    if window.starts_at is not None:
        pub = pub.where(Activity.created_at >= window.starts_at)
    if window.ends_at is not None:
        pub = pub.where(Activity.created_at < window.ends_at)
    if not scope.is_platform:
        if not scope.space_ids:
            pub = pub.where(literal(False))
        else:
            pub = pub.where(Activity.collective_id.in_(scope.space_ids))
    publishing = {r[0] for r in db.execute(pub)}

    from app.models.user import User

    candidates = participating | publishing
    if not candidates:
        return MetricValue(key="active_creators", value=0)
    creators = {
        r[0]
        for r in db.execute(
            select(User.id).where(User.id.in_(candidates), User.role == "creator")
        )
    }
    return MetricValue(
        key="active_creators",
        value=len(creators),
        qualifiers={"published_in_period": len(publishing & creators)},
    )


REGISTRY.add(Metric(
    key="active_creators",
    display_name="Active creators",
    definition=(
        "Distinct creators who participated or published in the period. "
        "Publishing counts on its own — a creator who released a Pathway "
        "and did nothing else was active."
    ),
    source_of_truth="participation union + activities (publishing events)",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.platform_only,
    availability=Availability.full,
    limitations="Non-additive across periods.",
    personal_data=True,
    compute=_active_creators,
))


def _returning_participants(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """People active in this window *and* the one before it.

    The signal membership counts cannot give: whether participation is a
    habit or a single visit.
    """
    if window.is_all_time:
        return MetricValue(
            key="returning_participants",
            value=None,
            unavailable_reason=(
                "Returning participation needs two adjacent periods, so it "
                "is undefined for all time."
            ),
        )
    length = window.ends_at - window.starts_at
    previous = Window(window.starts_at - length, window.starts_at, "previous")

    part = participation_events()

    def people(w: Window) -> set[str]:
        q = select(func.distinct(part.c.user_id)).select_from(part)
        return {r[0] for r in db.execute(_windowed(_scoped(q, part, scope), part, w))}

    now_set, before_set = people(window), people(previous)
    both = now_set & before_set
    return MetricValue(
        key="returning_participants",
        value=len(both),
        qualifiers={
            "active_this_period": len(now_set),
            "active_previous_period": len(before_set),
            "return_rate": (
                round(len(both) / len(before_set), 3) if before_set else None
            ),
        },
    )


REGISTRY.add(Metric(
    key="returning_participants",
    display_name="Returning participants",
    definition=(
        "People who participated in this period and also in the immediately "
        "preceding period of the same length."
    ),
    source_of_truth="participation union, two adjacent windows",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations=(
        "Undefined for all time, which needs no comparison period. "
        "Non-additive."
    ),
    dimensions=("space_id",),
    personal_data=True,
    compute=_returning_participants,
))


# ---------------------------------------------------------------------------
# Participation volume
# ---------------------------------------------------------------------------

def _participation_acts(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    part = participation_events()
    rows = db.execute(
        _windowed(
            _scoped(
                select(part.c.kind, func.count())
                .select_from(part)
                .group_by(part.c.kind),
                part, scope,
            ),
            part, window,
        )
    ).fetchall()
    by_kind = {k: int(n) for k, n in rows}
    return MetricValue(
        key="participation_acts",
        value=sum(by_kind.values()),
        qualifiers={"by_kind": {k: by_kind.get(k, 0) for k in PARTICIPATION_KINDS}},
    )


REGISTRY.add(Metric(
    key="participation_acts",
    display_name="Participation acts",
    definition=(
        "Total acts of participation in the period, broken down by kind. "
        "Counts acts, not people — one person posting ten times is ten."
    ),
    source_of_truth="participation union",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.full,
    dimensions=("space_id",),
    compute=_participation_acts,
))


def _gathering_attendance(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Attended versus booked, which is the interesting comparison."""
    q = (
        select(
            func.count(EventBooking.id),
            func.sum(
                func.cast(EventBooking.attendance_status == "attended", __import__(
                    "sqlalchemy").Integer)
            ),
        )
        .select_from(EventBooking)
        .join(Event, Event.id == EventBooking.event_id)
    )
    if window.starts_at is not None:
        q = q.where(Event.starts_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(Event.starts_at < window.ends_at)
    if not scope.is_platform:
        if not scope.space_ids:
            q = q.where(literal(False))
        else:
            q = q.where(Event.space_id.in_(scope.space_ids))
    booked, attended = db.execute(q).one()
    booked, attended = int(booked or 0), int(attended or 0)
    return MetricValue(
        key="gathering_attendance",
        value=attended,
        qualifiers={
            "booked": booked,
            "attendance_rate": round(attended / booked, 3) if booked else None,
            "note": (
                "Attendance is only known for Gatherings whose register was "
                "marked. An unmarked Gathering reads as zero attended, which "
                "is indistinguishable from nobody coming."
            ),
        },
    )


REGISTRY.add(Metric(
    key="gathering_attendance",
    display_name="Gathering attendance",
    definition=(
        "Bookings marked attended, for Gatherings held in the period, with "
        "the booked total and attendance rate alongside."
    ),
    source_of_truth="event_bookings.attendance_status joined to events.starts_at",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "Depends on a creator marking the register. An unmarked Gathering is "
        "indistinguishable from an unattended one."
    ),
    dimensions=("space_id",),
    compute=_gathering_attendance,
))


def _pathway_steps_completed(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    q = (
        select(
            func.count(StepProgress.id),
            func.count(func.distinct(StepProgress.user_id)),
        )
        .select_from(StepProgress)
        .join(PathwayStep, PathwayStep.id == StepProgress.step_id)
        .join(Pathway, Pathway.id == PathwayStep.pathway_id)
        .where(StepProgress.completed_at.isnot(None))
    )
    if window.starts_at is not None:
        q = q.where(StepProgress.completed_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(StepProgress.completed_at < window.ends_at)
    if not scope.is_platform:
        if not scope.space_ids:
            q = q.where(literal(False))
        else:
            q = q.where(Pathway.space_id.in_(scope.space_ids))
    steps, people = db.execute(q).one()
    return MetricValue(
        key="pathway_steps_completed",
        value=int(steps or 0),
        qualifiers={"distinct_members": int(people or 0)},
    )


REGISTRY.add(Metric(
    key="pathway_steps_completed",
    display_name="Pathway steps completed",
    definition=(
        "Pathway steps marked complete in the period, with the number of "
        "distinct members who completed them."
    ),
    source_of_truth="step_progress.completed_at",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "There is no start timestamp on a step, so time-to-complete is not "
        "available for any period."
    ),
    dimensions=("space_id",),
    compute=_pathway_steps_completed,
))


# ---------------------------------------------------------------------------
# Rates and relationships
# ---------------------------------------------------------------------------

def _participation_rate(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Active members as a share of the people who could have been.

    The denominator is unique members, not memberships — otherwise a
    person in three Collectives would make the platform look three times
    less engaged than it is.
    """
    active = _active_people(db, scope, window)
    members = REGISTRY.get("unique_members").evaluate(db, scope, Window()).value or 0
    if not members:
        return MetricValue(
            key="participation_rate",
            value=None,
            unavailable_reason="No members yet, so there is no rate to report.",
        )
    return MetricValue(
        key="participation_rate",
        value=round(active / members, 3),
        qualifiers={"active_members": active, "unique_members": members},
    )


REGISTRY.add(Metric(
    key="participation_rate",
    display_name="Participation rate",
    definition=(
        "Active members in the period divided by unique members. The "
        "denominator counts people, not memberships, so someone in three "
        "Collectives does not depress it threefold."
    ),
    source_of_truth="derived from active_members and unique_members",
    grain=Grain.period,
    aggregation=Aggregation.ratio,
    date_basis=DateBasis.business_event,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations="A ratio — recompute it, never average two periods.",
    dimensions=("space_id",),
    compute=_participation_rate,
))


def _overlap_vs_engagement(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Does belonging to several Collectives predict participating more?

    Returns the participation rate split by how many Collectives a
    person belongs to. One of the few questions that needs the whole
    platform to answer honestly, so it is platform-only.
    """
    part = participation_events()
    counts = (
        select(
            SpaceMembership.user_id.label("user_id"),
            func.count(func.distinct(SpaceMembership.space_id)).label("n"),
        )
        .where(SpaceMembership.status == SpaceMembershipStatus.active)
        .group_by(SpaceMembership.user_id)
        .subquery()
    )
    active_q = select(func.distinct(part.c.user_id)).select_from(part)
    active_q = _windowed(active_q, part, window)
    active = {r[0] for r in db.execute(active_q)}

    rows = db.execute(select(counts.c.user_id, counts.c.n)).fetchall()
    buckets: dict[str, dict[str, int]] = {}
    for user_id, n in rows:
        label = "1" if n == 1 else ("2" if n == 2 else "3+")
        b = buckets.setdefault(label, {"members": 0, "active": 0})
        b["members"] += 1
        if user_id in active:
            b["active"] += 1
    for b in buckets.values():
        b["rate"] = round(b["active"] / b["members"], 3) if b["members"] else None
    return MetricValue(
        key="overlap_vs_engagement",
        value=len(active),
        qualifiers={"by_membership_count": buckets},
    )


REGISTRY.add(Metric(
    key="overlap_vs_engagement",
    display_name="Membership overlap versus engagement",
    definition=(
        "Participation rate split by how many Collectives a person belongs "
        "to — whether belonging to several predicts participating more."
    ),
    source_of_truth="participation union + space_memberships",
    grain=Grain.period,
    aggregation=Aggregation.ratio,
    date_basis=DateBasis.business_event,
    access=Access.platform_only,
    availability=Availability.full,
    limitations=(
        "Needs the whole platform to answer honestly, so it is not offered "
        "at Collective scope."
    ),
    personal_data=True,
    compute=_overlap_vs_engagement,
))


def _engagement_by_theme(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Active members per theme.

    Themes are multi-select, so a Collective with three themes
    contributes to three buckets and the totals exceed the platform
    figure. Said here rather than left to be discovered.
    """
    part = participation_events()
    # DISTINCT on the whole row rather than ``func.distinct`` on one
    # column — the latter is not valid SQL in a multi-column select.
    q = (
        select(Space.themes, part.c.user_id)
        .select_from(part)
        .join(Space, Space.id == part.c.space_id)
        .distinct()
    )
    q = _windowed(_scoped(q, part, scope), part, window)
    buckets: dict[str, set[str]] = {}
    for themes, user_id in db.execute(q):
        for theme in themes or ["(none)"]:
            buckets.setdefault(theme, set()).add(user_id)
    return MetricValue(
        key="engagement_by_theme",
        value=sum(len(v) for v in buckets.values()),
        qualifiers={
            "active_members_by_theme": {k: len(v) for k, v in sorted(buckets.items())},
            "note": (
                "Themes are multi-select, so a Collective counts under each "
                "of its themes and these figures sum to more than the "
                "platform total."
            ),
        },
    )


REGISTRY.add(Metric(
    key="engagement_by_theme",
    display_name="Engagement by theme",
    definition=(
        "Distinct active members per Collective theme. Themes are "
        "multi-select, so the buckets overlap and sum to more than the "
        "platform total."
    ),
    source_of_truth="participation union joined to spaces.themes",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.platform_only,
    availability=Availability.full,
    limitations=(
        "Multi-select dimension: counts by theme exceed the number of "
        "Collectives and the number of active members."
    ),
    compute=_engagement_by_theme,
))


def _retention_cohorts(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Of the members who first joined in month M, how many are still active?

    Built on ``space_memberships.joined_at`` for the cohort and the
    participation union for activity. Honest about its own floor: a
    cohort is only as trustworthy as the history behind it, and
    membership *departures* were destroyed by rejoining before BI-1, so
    cohorts spanning that period understate churn.
    """
    rows = db.execute(
        select(
            func.date_trunc("month", SpaceMembership.joined_at).label("cohort"),
            func.count(func.distinct(SpaceMembership.user_id)),
        )
        .where(SpaceMembership.joined_at.isnot(None))
        .group_by("cohort")
        .order_by("cohort")
    ).fetchall()
    if not rows:
        return MetricValue(
            key="retention_cohorts",
            value=None,
            unavailable_reason="No memberships yet, so there are no cohorts.",
        )

    part = participation_events()
    active_q = select(func.distinct(part.c.user_id)).select_from(part)
    active_q = _windowed(_scoped(active_q, part, scope), part, window)
    active = {r[0] for r in db.execute(active_q)}

    cohorts = []
    for cohort, size in rows:
        members = {
            r[0]
            for r in db.execute(
                select(func.distinct(SpaceMembership.user_id)).where(
                    func.date_trunc("month", SpaceMembership.joined_at) == cohort
                )
            )
        }
        still = len(members & active)
        cohorts.append({
            "cohort": cohort.strftime("%Y-%m") if cohort else None,
            "joined": int(size),
            "active_in_period": still,
            "rate": round(still / size, 3) if size else None,
        })
    return MetricValue(
        key="retention_cohorts",
        value=len(cohorts),
        qualifiers={
            "cohorts": cohorts,
            "limitation": (
                "Departures were overwritten by rejoining before business-"
                "event recording began, so cohorts spanning that period "
                "understate churn. Cohorts from BI-1 onwards are complete."
            ),
        },
    )


REGISTRY.add(Metric(
    key="retention_cohorts",
    display_name="Retention cohorts",
    definition=(
        "For each month of first joining, how many of that cohort "
        "participated in the reporting period."
    ),
    source_of_truth="space_memberships.joined_at + participation union",
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.membership_joined,
    access=Access.platform_only,
    availability=Availability.from_instrumentation,
    limitations=(
        "Departures were destroyed by rejoining before BI-1, so cohorts "
        "spanning that period understate churn."
    ),
    personal_data=True,
    compute=_retention_cohorts,
))
