"""
Recognition — read-time derivation of what two people share.

Recognition is the first surface of the Discovery, Connection &
Belonging pillar (see
``docs/foundations/discovery-connection-belonging-v1.1.md``): the
calm, derived, ephemeral answer to the question "what do we share?"
It is deliberately distinct from Journey Together, which is an
intentional, mutual, persistent relationship graph opt-in.

Public API speaks the language of the product:

    Recognition                     — what one person shares with another
    RecognitionService.between(...) — recognitions between two people
    RecognitionService.for_user(...) — every person this user recognises

Private implementation speaks the language of the substrate — the raw
facts Recognition is derived from:

    _upcoming_shared_bookings(...)
    _shared_attended_gatherings(...)
    _shared_started_pathways(...)
    _active_shared_memberships(...)

Nothing is stored. Every call is a fresh read against the current
platform state so recognitions reflect the world as it is right now
(a person leaves a Collective, the Recognition disappears from the
next view).


The evidence model
------------------

A shared Collective is the **privacy and context boundary**, never the
evidence. Two people who merely belong to the same Collective share
nothing this service will surface, however small that Collective is.
The Collective still rides along on the result so a caller can say
*where* a shared experience belongs.

Evidence that does create a Recognition:

  * **An upcoming Gathering** both hold a ``confirmed`` booking for,
    while the Gathering itself is still ``active``. Valid until it
    starts — after that, a booking is only a statement of intent, and
    intent is not shared experience. A cancelled or archived Gathering
    is not something two people are about to share.

  * **A past Gathering both actually attended.** Requires the creator
    to have finalised attendance for that occurrence
    (``Event.attendance_completed_at``) *and* both bookings to be
    marked ``attended``. A ``no_show`` never counts, and an
    unfinalised Gathering is treated as unknown rather than assumed —
    we do not infer attendance from a booking. Sparse and truthful
    beats plentiful and wrong.

    Once attendance is finalised, the attendance mark outranks the
    booking's later lifecycle. A booking refunded, credited or
    administratively cancelled *after* the Gathering does not erase
    the fact that the person was in the room. Upcoming Gatherings
    still require a live ``confirmed`` booking, because nothing has
    happened yet for a mark to outrank.

  * **A Pathway both have genuinely started** — both enrolments
    ``active`` and both with at least one completed step in that
    Pathway. A Pathway is already a deliberate shared commitment, so
    once both have started there is no activity-recency expiry; the
    shared Pathway stands while both enrolments remain active.

Past co-attendance decays. A single shared attendance stays relevant
for ``RECENT_ATTENDANCE_DAYS``; two or more within
``REPEATED_ATTENDANCE_DAYS`` read as a pattern rather than a
coincidence and stay relevant for that longer window. Both are
internal constants — never a score, never a member-visible threshold.

``SharedGathering`` carries the recurrence linkage of its occurrence so
a later phrasing layer can recognise "you keep ending up at the same
Tuesday circle" without re-querying. Nothing here phrases anything.


Privacy & eligibility rules baked in from the beginning:

  * Suspended or cancelled accounts on *either* side yield an empty
    Recognition. Recognition never reveals a person who has stepped
    back from the platform.
  * Only ``active`` SpaceMemberships count. Paused or removed
    memberships are invisible.
  * Only ``active`` Enrollments count. Paused / completed enrolments
    are invisible.
  * Only ``confirmed`` bookings count towards an *upcoming*
    Gathering. Cancelled / pending-payment holds are invisible there.
    Past Gatherings are judged on the finalised attendance mark
    instead — see above.
  * Collectives whose ``status`` is not ``active``, whose
    ``closed_at`` is set (Community Care terminal outcome), or whose
    ``show_member_directory`` is ``False`` are excluded — including
    their pathways and gatherings. A Collective creator who has said
    "learners can't see each other" is telling us clearly that
    Recognition should not surface that co-membership either.
  * ``StepProgress.reflection_text`` is private journalling and is
    never read, matched on, or returned. Only *completed* step
    progress counts as having started a Pathway — a draft reflection
    creates a StepProgress row too, and private drafting must not make
    a member visible to anyone.

Every predicate is applied to both people, so ``between(a, b)`` and
``between(b, a)`` derive the same evidence by construction. The
symmetry tests pin that rather than trusting it.

Focused result objects, not ORM records, are returned by design — the
service is a boundary that hands the UI what it needs to render
without exposing internal schema shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.community_care.shared import is_user_cancelled, is_user_suspended
from app.models.platform import (
    BookingStatus,
    Enrollment,
    EnrollmentStatus,
    Event,
    EventBooking,
    Pathway,
    PathwayStep,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    StepProgress,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Internal tuning constants. Not exposed, not rendered, not a score.
# ---------------------------------------------------------------------------

#: A single past co-attendance stays relevant for this long.
RECENT_ATTENDANCE_DAYS = 90

#: Two or more past co-attendances read as a pattern and stay relevant
#: for this long instead.
REPEATED_ATTENDANCE_DAYS = 365

#: How many genuine shared attendances count as "repeated".
REPEATED_ATTENDANCE_MIN = 2

#: ``EventBooking.attendance_status`` is a plain column, not an enum.
#: The DB dialect is 'pending' | 'attended' | 'no_show' | NULL — see
#: ``app/creator/attendance.py`` for the API-facing translation.
_ATTENDED = "attended"

#: ``Event.status`` is likewise a plain column: 'active' | 'cancelled' |
#: 'archived'. 'active' is the platform-wide predicate for "this
#: Gathering is still on" — see ``app/spaces/routes.py`` and
#: ``app/services/gathering_tickets.py``.
_EVENT_ACTIVE = "active"


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

class SharedGatheringBasis(str, Enum):
    """Why a Gathering is shared — the two kinds are not interchangeable.

    ``UPCOMING`` is a shared intention: both hold a confirmed booking
    for something that has not happened yet. ``ATTENDED`` is a shared
    experience: both were marked present at something that has.

    Carried explicitly rather than re-derived from ``starts_at`` so a
    caller never has to compare against its own clock — which could
    disagree with the ``now`` this Recognition was derived against.
    """

    UPCOMING = "upcoming"
    ATTENDED = "attended"


@dataclass(frozen=True)
class SharedCollective:
    """One Collective two people are both active members of.

    Context, not evidence: a shared Collective never creates a
    Recognition on its own. It tells a caller where a shared Pathway or
    Gathering belongs, and where both people can already see each other.
    """

    collective_id: str
    slug: str
    name: str


@dataclass(frozen=True)
class SharedPathway:
    """One Pathway two people are both actively enrolled in and have
    both genuinely started."""

    pathway_id: str
    slug: str
    title: str
    collective_id: str


@dataclass(frozen=True)
class SharedGathering:
    """One Gathering two people share — either upcoming and booked by
    both, or past and attended by both.

    ``recurrence_series_id`` / ``series_id`` are carried so a later
    phrasing layer can tell repeated attendance at the same recurring
    Gathering apart from attendance at unrelated ones. Neither is
    interpreted here.
    """

    gathering_id: str
    title: str
    starts_at: datetime
    collective_id: str
    basis: SharedGatheringBasis
    recurrence_series_id: str | None = None
    series_id: str | None = None


@dataclass(frozen=True)
class Recognition:
    """Everything one person shares with another at read time.

    An empty Recognition (``is_empty``) is a valid result and means
    "these two people share nothing surfacable right now" — the caller
    should render nothing rather than a "no shared items" empty state.

    ``collectives`` is deliberately excluded from that emptiness test:
    co-membership is the boundary that makes Recognition permissible,
    not a thing worth surfacing. A Recognition carrying collectives and
    nothing else is empty, and callers drop it.
    """

    other_user_id: str
    collectives: tuple[SharedCollective, ...] = field(default_factory=tuple)
    pathways:    tuple[SharedPathway, ...]    = field(default_factory=tuple)
    gatherings:  tuple[SharedGathering, ...]  = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (self.pathways or self.gatherings)


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class RecognitionService:
    """Derives Recognition between people from the current platform state."""

    @classmethod
    def between(
        cls,
        db: Session,
        viewer_user_id: str,
        other_user_id: str,
        *,
        now: datetime | None = None,
    ) -> Recognition:
        """What does the viewer recognise with this other person?

        Returns an empty Recognition when either account is suspended
        or cancelled, when the two are the same person, or when no
        shared substrate exists that survives the privacy guards.

        ``now`` is injectable so time-window behaviour is deterministic
        under test. It defaults to ``datetime.utcnow()`` — naive UTC, to
        match ``Event.starts_at``, which is stored without a timezone.
        """
        now = now or datetime.utcnow()

        if viewer_user_id == other_user_id:
            return Recognition(other_user_id=other_user_id)

        viewer = db.get(User, viewer_user_id)
        other  = db.get(User, other_user_id)
        if viewer is None or other is None:
            return Recognition(other_user_id=other_user_id)
        if not _account_eligible(viewer) or not _account_eligible(other):
            return Recognition(other_user_id=other_user_id)

        visible_space_ids = _spaces_where_both_are_visible_members(
            db, viewer_user_id, other_user_id
        )
        if not visible_space_ids:
            # No collective in common survives the directory guard, so
            # nothing else (pathways / gatherings) can either — they
            # all live under a Collective, and the guard is applied at
            # the Collective level.
            return Recognition(other_user_id=other_user_id)

        collectives = _active_shared_memberships(db, visible_space_ids)
        pathways    = _shared_started_pathways(
            db, viewer_user_id, other_user_id, visible_space_ids
        )
        gatherings = (
            _upcoming_shared_bookings(
                db, viewer_user_id, other_user_id, visible_space_ids, now
            )
            + _shared_attended_gatherings(
                db, viewer_user_id, other_user_id, visible_space_ids, now
            )
        )
        return Recognition(
            other_user_id=other_user_id,
            collectives=collectives,
            pathways=pathways,
            gatherings=gatherings,
        )

    @classmethod
    def for_user(
        cls, db: Session, user_id: str, *, now: datetime | None = None
    ) -> list[Recognition]:
        """Every other person this user recognises, non-empty only.

        Candidates are drawn from the set of active co-members in
        Collectives that survive the directory guard, since Pathway
        and Gathering derivations both require an underlying visible
        Collective co-membership. Co-membership only makes a person a
        *candidate*; it never survives into the result on its own. The
        list order is stable (sorted by ``other_user_id``) so callers
        can rely on it.

        Fans out one ``between`` call per candidate, so query volume
        grows with the size of the viewer's Collectives. Acceptable
        while this service has no caller; it must be batched before
        anything serves it over HTTP.
        """
        now = now or datetime.utcnow()

        viewer = db.get(User, user_id)
        if viewer is None or not _account_eligible(viewer):
            return []

        candidate_ids = _visible_co_member_user_ids(db, user_id)

        results: list[Recognition] = []
        for other_id in sorted(candidate_ids):
            recog = cls.between(db, user_id, other_id, now=now)
            if not recog.is_empty:
                results.append(recog)
        return results


# ---------------------------------------------------------------------------
# Private substrate helpers — everything below speaks in the language of
# rows, statuses, and joins.
# ---------------------------------------------------------------------------

def _account_eligible(user: User) -> bool:
    """False when the user's account has been suspended or cancelled.

    Both states remove the user from Recognition entirely. Suspension
    is temporary but still a Fresh Collective decision that the person
    is not currently present in the community; cancellation is
    terminal.
    """
    return not (is_user_suspended(user) or is_user_cancelled(user))


def _spaces_where_both_are_visible_members(
    db: Session, viewer_id: str, other_id: str
) -> set[str]:
    """Space ids where both users are active members AND the Collective
    itself is visible (active status, not closed, member directory on).
    """
    viewer_membership = SpaceMembership.__table__.alias("viewer_membership")
    other_membership  = SpaceMembership.__table__.alias("other_membership")

    stmt = (
        select(Space.id)
        .join(viewer_membership, viewer_membership.c.space_id == Space.id)
        .join(other_membership,  other_membership.c.space_id  == Space.id)
        .where(
            viewer_membership.c.user_id == viewer_id,
            viewer_membership.c.status  == SpaceMembershipStatus.active,
            other_membership.c.user_id  == other_id,
            other_membership.c.status   == SpaceMembershipStatus.active,
            Space.status                == "active",
            Space.closed_at.is_(None),
            Space.show_member_directory.is_(True),
        )
    )
    return {row[0] for row in db.execute(stmt).all()}


def _visible_co_member_user_ids(db: Session, user_id: str) -> set[str]:
    """User ids of every other person who shares at least one visible
    Collective (active + not closed + directory on) with this user."""
    my_membership    = SpaceMembership.__table__.alias("my_membership")
    other_membership = SpaceMembership.__table__.alias("other_membership")

    stmt = (
        select(other_membership.c.user_id)
        .select_from(my_membership)
        .join(Space, Space.id == my_membership.c.space_id)
        .join(
            other_membership,
            and_(
                other_membership.c.space_id == my_membership.c.space_id,
                other_membership.c.user_id  != user_id,
            ),
        )
        .where(
            my_membership.c.user_id == user_id,
            my_membership.c.status  == SpaceMembershipStatus.active,
            other_membership.c.status == SpaceMembershipStatus.active,
            Space.status              == "active",
            Space.closed_at.is_(None),
            Space.show_member_directory.is_(True),
        )
        .distinct()
    )
    return {row[0] for row in db.execute(stmt).all()}


def _active_shared_memberships(
    db: Session, visible_space_ids: set[str]
) -> tuple[SharedCollective, ...]:
    """Convert the pre-computed visible-space id set into focused
    SharedCollective result objects. Sorted by name for stable UI.

    Context only — see ``SharedCollective``.
    """
    if not visible_space_ids:
        return ()
    rows = db.execute(
        select(Space.id, Space.slug, Space.name)
        .where(Space.id.in_(visible_space_ids))
        .order_by(Space.name)
    ).all()
    return tuple(
        SharedCollective(collective_id=r.id, slug=r.slug, name=r.name)
        for r in rows
    )


def _started_pathway_exists(user_id: str):
    """Correlated EXISTS: has this user completed at least one step of
    the Pathway in the enclosing query?

    Completed, not merely recorded. A StepProgress row is also written
    when a member saves a *draft* reflection, with ``completed_at``
    left NULL — counting that would make private journalling the thing
    that reveals a person, which is exactly what Recognition must never
    do. ``reflection_text`` itself is never touched.
    """
    return (
        select(StepProgress.id)
        .join(PathwayStep, PathwayStep.id == StepProgress.step_id)
        .where(
            PathwayStep.pathway_id == Pathway.id,
            StepProgress.user_id == user_id,
            StepProgress.completed_at.is_not(None),
        )
        .exists()
    )


def _shared_started_pathways(
    db: Session,
    viewer_id: str,
    other_id: str,
    visible_space_ids: set[str],
) -> tuple[SharedPathway, ...]:
    """Pathways where both users are ``active`` enrolled, both have
    genuinely started, and the parent Collective is in the visible set.

    No recency window. A Pathway is a deliberate shared commitment, not
    an incidental overlap — once both people are in it and both have
    begun, the shared Pathway stands until an enrolment stops being
    active.
    """
    if not visible_space_ids:
        return ()

    viewer_enrolment = Enrollment.__table__.alias("viewer_enrolment")
    other_enrolment  = Enrollment.__table__.alias("other_enrolment")

    stmt = (
        select(Pathway.id, Pathway.slug, Pathway.title, Pathway.space_id)
        .join(viewer_enrolment, viewer_enrolment.c.pathway_id == Pathway.id)
        .join(other_enrolment,  other_enrolment.c.pathway_id  == Pathway.id)
        .where(
            viewer_enrolment.c.user_id == viewer_id,
            viewer_enrolment.c.status  == EnrollmentStatus.active,
            other_enrolment.c.user_id  == other_id,
            other_enrolment.c.status   == EnrollmentStatus.active,
            Pathway.space_id.in_(visible_space_ids),
            _started_pathway_exists(viewer_id),
            _started_pathway_exists(other_id),
        )
        .order_by(Pathway.title)
    )
    return tuple(
        SharedPathway(
            pathway_id=r.id,
            slug=r.slug,
            title=r.title,
            collective_id=r.space_id,
        )
        for r in db.execute(stmt).all()
    )


def _upcoming_shared_bookings(
    db: Session,
    viewer_id: str,
    other_id: str,
    visible_space_ids: set[str],
    now: datetime,
) -> tuple[SharedGathering, ...]:
    """Gatherings that are still on, have not started yet, and that
    both users hold a ``confirmed`` booking for. Soonest first.

    Once ``starts_at`` passes, a booking stops being evidence of
    anything shared — whether either person actually came is a
    different question, answered by
    ``_shared_attended_gatherings``.

    A cancelled or archived Gathering is excluded: two people holding
    bookings for something that is not happening are not about to
    share anything.
    """
    if not visible_space_ids:
        return ()

    viewer_booking = EventBooking.__table__.alias("viewer_booking")
    other_booking  = EventBooking.__table__.alias("other_booking")

    stmt = (
        select(
            Event.id,
            Event.title,
            Event.starts_at,
            Event.space_id,
            Event.recurrence_series_id,
            Event.series_id,
        )
        .join(viewer_booking, viewer_booking.c.event_id == Event.id)
        .join(other_booking,  other_booking.c.event_id  == Event.id)
        .where(
            viewer_booking.c.user_id == viewer_id,
            viewer_booking.c.status  == BookingStatus.confirmed,
            other_booking.c.user_id  == other_id,
            other_booking.c.status   == BookingStatus.confirmed,
            Event.space_id.in_(visible_space_ids),
            Event.status == _EVENT_ACTIVE,
            Event.starts_at > now,
        )
        .order_by(Event.starts_at)
    )
    return tuple(
        _shared_gathering(r, SharedGatheringBasis.UPCOMING)
        for r in db.execute(stmt).all()
    )


def _shared_attended_gatherings(
    db: Session,
    viewer_id: str,
    other_id: str,
    visible_space_ids: set[str],
    now: datetime,
) -> tuple[SharedGathering, ...]:
    """Past Gatherings both users were actually marked present at.

    Requires the creator to have finalised attendance for the
    occurrence *and* both bookings to be ``attended``. An unfinalised
    Gathering yields nothing: we do not infer that a booking was
    honoured. A ``no_show`` — or a still-``pending`` mark — on either
    side yields nothing.

    Deliberately *not* filtered on ``EventBooking.status``. Once
    attendance is finalised, the mark is the record of what happened;
    a booking refunded, credited or cancelled afterwards is an
    administrative fact about payment, not evidence that the person
    was absent. Erasing a real shared experience over a later
    bookkeeping change would make Recognition less truthful, not
    more.

    Decay: a single shared attendance stays relevant for
    ``RECENT_ATTENDANCE_DAYS``. Reaching ``REPEATED_ATTENDANCE_MIN``
    within ``REPEATED_ATTENDANCE_DAYS`` makes it a pattern rather than
    a coincidence, and the whole set stays relevant for that longer
    window. Most recent first.
    """
    if not visible_space_ids:
        return ()

    viewer_booking = EventBooking.__table__.alias("viewer_booking")
    other_booking  = EventBooking.__table__.alias("other_booking")

    stmt = (
        select(
            Event.id,
            Event.title,
            Event.starts_at,
            Event.space_id,
            Event.recurrence_series_id,
            Event.series_id,
        )
        .join(viewer_booking, viewer_booking.c.event_id == Event.id)
        .join(other_booking,  other_booking.c.event_id  == Event.id)
        .where(
            viewer_booking.c.user_id == viewer_id,
            viewer_booking.c.attendance_status == _ATTENDED,
            other_booking.c.user_id  == other_id,
            other_booking.c.attendance_status == _ATTENDED,
            Event.space_id.in_(visible_space_ids),
            Event.attendance_completed_at.is_not(None),
            Event.starts_at <= now,
            Event.starts_at >= now - timedelta(days=REPEATED_ATTENDANCE_DAYS),
        )
        .order_by(Event.starts_at.desc())
    )
    rows = db.execute(stmt).all()

    if len(rows) >= REPEATED_ATTENDANCE_MIN:
        # A pattern. Everything inside the longer window stands.
        return tuple(
            _shared_gathering(r, SharedGatheringBasis.ATTENDED) for r in rows
        )

    # A single shared attendance. Relevant only while it is recent.
    recent_cutoff = now - timedelta(days=RECENT_ATTENDANCE_DAYS)
    return tuple(
        _shared_gathering(r, SharedGatheringBasis.ATTENDED)
        for r in rows
        if r.starts_at >= recent_cutoff
    )


def _shared_gathering(row, basis: SharedGatheringBasis) -> SharedGathering:
    """Both Gathering queries select the same columns; this keeps the
    mapping to the result object in one place."""
    return SharedGathering(
        gathering_id=row.id,
        title=row.title,
        starts_at=row.starts_at,
        collective_id=row.space_id,
        basis=basis,
        recurrence_series_id=row.recurrence_series_id,
        series_id=row.series_id,
    )
