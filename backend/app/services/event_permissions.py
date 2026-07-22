"""Central access-control for Gatherings (Events).

Mirrors `app.services.channel_permissions` — every endpoint that
touches an Event booking or exposes sensitive detail (meeting link,
venue instructions) should route through here. Inline checks in
endpoints are a legacy pattern; new work funnels here so paid-ticket
support has a single place to extend when it lands.

The Public API returned by `can_book(...)` is a small enum so
endpoints can format a human message consistently. Everything else
returns a bool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.platform import (
    BookingStatus,
    EntitlementStatus,
    Event,
    EventBooking,
    PathwayEntitlement,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.gathering_types import normalise_access_type


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _is_caretaker(user: User | None, space: Space, db: Session) -> bool:
    if user is None:
        return False
    if user.role in ("admin", "creator"):
        return True
    row = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .first()
    )
    return row is not None


def _has_active_space_membership(user_id: str, space_id: str, db: Session) -> bool:
    return (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    ) is not None


def _has_confirmed_booking(user_id: str, event_id: str, db: Session) -> bool:
    return (
        db.query(EventBooking.id)
        .filter(
            EventBooking.user_id == user_id,
            EventBooking.event_id == event_id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    ) is not None


def _has_pathway_entitlement(user_id: str, pathway_id: str, db: Session) -> bool:
    return (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id == pathway_id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    ) is not None


# -----------------------------------------------------------------------------
# Visibility of sensitive detail
# -----------------------------------------------------------------------------


def can_view_event(
    user: User | None,
    event: Event,
    space: Space,
    db: Session,
) -> bool:
    """Can this user see the Gathering's basic detail page?

    Public + published events are visible to anyone. Otherwise the
    user needs a caretaker role or an active space membership.
    Draft + archived events are only visible to caretakers.
    """
    if not event.is_published or event.status in ("cancelled", "archived"):
        # Cancelled events remain viewable so registrants can see the
        # cancellation notice; caretakers see everything.
        if event.status == "cancelled":
            pass
        else:
            return _is_caretaker(user, space, db)
    if event.is_public:
        return True
    if user is None:
        return False
    if _is_caretaker(user, space, db):
        return True
    return _has_active_space_membership(user.id, space.id, db)


def can_view_meeting_link(
    user: User | None,
    event: Event,
    space: Space,
    db: Session,
) -> bool:
    """Meeting URL is sensitive — only registered attendees and
    caretakers may see it."""
    if user is None:
        return False
    if _is_caretaker(user, space, db):
        return True
    return _has_confirmed_booking(user.id, event.id, db)


def can_view_venue_details(
    user: User | None,
    event: Event,
    space: Space,
    db: Session,
) -> bool:
    """Full venue address + arrival instructions are shown only to
    registered attendees + caretakers. Non-attendees see the venue
    name as a rough locator only."""
    if user is None:
        return False
    if _is_caretaker(user, space, db):
        return True
    return _has_confirmed_booking(user.id, event.id, db)


# -----------------------------------------------------------------------------
# Booking gate
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BookingGate:
    """Outcome of `can_book`. `allowed=True` means the endpoint may
    proceed to create the booking (subject to capacity/window checks
    which stay in the endpoint since they need side-effects). When
    `allowed=False`, `reason` is a machine-readable slug and
    `message` is a member-facing string safe to surface in the UI."""
    allowed: bool
    reason: str = ""
    message: str = ""


_OK = BookingGate(allowed=True)


def can_book(
    user: User | None,
    event: Event,
    space: Space,
    db: Session,
) -> BookingGate:
    if user is None:
        return BookingGate(False, "auth_required",
                           "Please sign in to register for this gathering.")

    if not event.is_published:
        return BookingGate(False, "not_published",
                           "This gathering is not open for booking yet.")

    if event.status == "cancelled":
        return BookingGate(False, "cancelled",
                           "This gathering has been cancelled.")

    # Caretakers bypass access-type gating.
    if _is_caretaker(user, space, db):
        return _OK

    access = normalise_access_type(event.booking_access_type)

    # 'paid_separately' is a first-class business concept, but the
    # standalone-ticket checkout is not yet built. Bookings are
    # blocked with a clear message; caretakers may still add attendees
    # manually via the creator endpoint.
    if access == "paid_separately":
        return BookingGate(
            False, "paid_separately_pending",
            "Ticket sales for standalone paid Gatherings are coming soon.",
        )

    if access == "invitation_only":
        # No invitation infrastructure exists yet; treat as caretaker-
        # only until it ships.
        return BookingGate(
            False, "invitation_only",
            "This gathering is invitation only. Please contact the caretaker.",
        )

    # 'free' and 'included_with_collective' both require an active
    # space membership. 'included_with_pathway' additionally requires
    # a pathway entitlement.
    if not _has_active_space_membership(user.id, space.id, db):
        return BookingGate(False, "membership_required",
                           "You need to join this collective before booking.")

    if access == "included_with_pathway":
        pid = event.booking_required_pathway_id
        if pid is None:
            # Misconfigured — no linked pathway. Fall back to
            # collective-only rules so we never accidentally lock the
            # door for existing members.
            return _OK
        if _has_pathway_entitlement(user.id, pid, db):
            return _OK
        return BookingGate(
            False, "pathway_required",
            "You need access to the linked pathway to book this gathering.",
        )

    # 'free' and 'included_with_collective' — space membership is enough.
    return _OK


def can_cancel_booking(
    user: User | None,
    booking: EventBooking,
    event: Event,
    space: Space,
    db: Session,
) -> bool:
    if user is None:
        return False
    if _is_caretaker(user, space, db):
        return True
    return booking.user_id == user.id


# -----------------------------------------------------------------------------
# Bulk helpers for existing AccessPass logic — kept for compatibility
# -----------------------------------------------------------------------------


def find_eligible_access_pass(
    user_id: str,
    pathway_id: str | None,
    db: Session,
    now: datetime,
) -> AccessPass | None:
    """Return the AccessPass the caller would consume when booking a
    pathway-included gathering, or None. The AccessPass credit /
    weekly cap enforcement stays in the endpoint (it needs write
    access to the pass on booking); this helper is a read-only pick."""
    from sqlalchemy import or_
    if pathway_id is None:
        return None
    return (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == user_id,
            AccessPass.eligible_pathway_id == pathway_id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .order_by(AccessPass.created_at.desc())
        .first()
    )
