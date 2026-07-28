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

    _active_shared_memberships(...)
    _active_shared_enrolments(...)
    _confirmed_shared_bookings(...)

Nothing is stored. Every call is a fresh read against the current
platform state so recognitions reflect the world as it is right now
(a person leaves a Collective, the Recognition disappears from the
next view).

Privacy & eligibility rules baked in from the beginning:

  * Suspended or cancelled accounts on *either* side yield an empty
    Recognition. Recognition never reveals a person who has stepped
    back from the platform.
  * Only ``active`` SpaceMemberships count. Paused or removed
    memberships are invisible.
  * Only ``active`` Enrollments count. Paused / completed enrolments
    are invisible.
  * Only ``confirmed`` bookings count. Cancelled / pending-payment
    holds are invisible.
  * Collectives whose ``status`` is not ``active``, whose
    ``closed_at`` is set (Community Care terminal outcome), or whose
    ``show_member_directory`` is ``False`` are excluded — including
    their pathways and gatherings. A Collective creator who has said
    "learners can't see each other" is telling us clearly that
    Recognition should not surface that co-membership either.

Focused result objects, not ORM records, are returned by design — the
service is a boundary that hands the UI what it needs to render
without exposing internal schema shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SharedCollective:
    """One Collective two people are both active members of."""

    collective_id: str
    slug: str
    name: str


@dataclass(frozen=True)
class SharedPathway:
    """One Pathway two people are both actively enrolled in."""

    pathway_id: str
    slug: str
    title: str
    collective_id: str


@dataclass(frozen=True)
class SharedGathering:
    """One Gathering two people both have confirmed bookings for."""

    gathering_id: str
    title: str
    starts_at: datetime
    collective_id: str


@dataclass(frozen=True)
class Recognition:
    """Everything one person shares with another at read time.

    An empty Recognition (``is_empty``) is a valid result and means
    "these two people share nothing surfacable right now" — the caller
    should render nothing rather than a "no shared items" empty state.
    """

    other_user_id: str
    collectives: tuple[SharedCollective, ...] = field(default_factory=tuple)
    pathways:    tuple[SharedPathway, ...]    = field(default_factory=tuple)
    gatherings:  tuple[SharedGathering, ...]  = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (self.collectives or self.pathways or self.gatherings)


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class RecognitionService:
    """Derives Recognition between people from the current platform state."""

    @classmethod
    def between(
        cls, db: Session, viewer_user_id: str, other_user_id: str
    ) -> Recognition:
        """What does the viewer recognise with this other person?

        Returns an empty Recognition when either account is suspended
        or cancelled, when the two are the same person, or when no
        shared substrate exists that survives the privacy guards.
        """
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
        pathways    = _active_shared_enrolments(
            db, viewer_user_id, other_user_id, visible_space_ids
        )
        gatherings  = _confirmed_shared_bookings(
            db, viewer_user_id, other_user_id, visible_space_ids
        )
        return Recognition(
            other_user_id=other_user_id,
            collectives=collectives,
            pathways=pathways,
            gatherings=gatherings,
        )

    @classmethod
    def for_user(cls, db: Session, user_id: str) -> list[Recognition]:
        """Every other person this user recognises, non-empty only.

        Candidates are drawn from the set of active co-members in
        Collectives that survive the directory guard, since Pathway
        and Gathering derivations both require an underlying visible
        Collective co-membership. The list order is stable
        (sorted by ``other_user_id``) so callers can rely on it.
        """
        viewer = db.get(User, user_id)
        if viewer is None or not _account_eligible(viewer):
            return []

        candidate_ids = _visible_co_member_user_ids(db, user_id)

        results: list[Recognition] = []
        for other_id in sorted(candidate_ids):
            recog = cls.between(db, user_id, other_id)
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
    SharedCollective result objects. Sorted by name for stable UI."""
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


def _active_shared_enrolments(
    db: Session,
    viewer_id: str,
    other_id: str,
    visible_space_ids: set[str],
) -> tuple[SharedPathway, ...]:
    """Pathways where both users are ``active`` enrolled and the
    parent Collective is in the visible set."""
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


def _confirmed_shared_bookings(
    db: Session,
    viewer_id: str,
    other_id: str,
    visible_space_ids: set[str],
) -> tuple[SharedGathering, ...]:
    """Gatherings where both users hold a ``confirmed`` booking and
    the parent Collective is in the visible set."""
    if not visible_space_ids:
        return ()

    viewer_booking = EventBooking.__table__.alias("viewer_booking")
    other_booking  = EventBooking.__table__.alias("other_booking")

    stmt = (
        select(Event.id, Event.title, Event.starts_at, Event.space_id)
        .join(viewer_booking, viewer_booking.c.event_id == Event.id)
        .join(other_booking,  other_booking.c.event_id  == Event.id)
        .where(
            viewer_booking.c.user_id == viewer_id,
            viewer_booking.c.status  == BookingStatus.confirmed,
            other_booking.c.user_id  == other_id,
            other_booking.c.status   == BookingStatus.confirmed,
            Event.space_id.in_(visible_space_ids),
        )
        .order_by(Event.starts_at)
    )
    return tuple(
        SharedGathering(
            gathering_id=r.id,
            title=r.title,
            starts_at=r.starts_at,
            collective_id=r.space_id,
        )
        for r in db.execute(stmt).all()
    )
