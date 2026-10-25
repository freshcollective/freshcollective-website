"""A reservation somebody paid for, after they have left the Collective.

Leaving a Collective preserves a confirmed Gathering booking — that was
the approved decision, and ``membership_removal`` cancels nothing. But
preserving a row is not the same as being able to use it:
``area_policies.AREA_DEFAULTS`` gates ``AREA_GATHERINGS`` on
``POLICY_MEMBERS``, so the Gatherings list and the Gathering page
answered 404 to the person holding the ticket. The booking was intact
and invisible.

This module is the exception that fixes that, and its whole design is
about being **narrow**:

* it is **not** a change to the area resolver. ``resolve_area_access``
  is untouched, so no Collective's Gatherings doorway opened, and no
  Pathway, Channel, member list or Offering became reachable. Three call
  sites consult this module; everything else still asks the resolver and
  still gets the same answer it did before.
* it is **per-reservation, not per-Collective**. The question is always
  "does this person hold a paid booking for *this* Gathering?" — so a
  former member sees the one Gathering they bought and nothing beside
  it. Leaving a Collective with ten Gatherings and a ticket to one
  reveals one.
* it **reads**. It creates no booking, revives no booking, and grants no
  new entitlement. ``book_event`` is deliberately not a caller, which is
  what stops the exception becoming a way back in through the
  turnstile.

What counts as paid for
-----------------------

Two shapes, both of which represent money the member actually spent:

``paid_separately`` + ``confirmed``
    A standalone ticket. ``confirmed`` is itself the evidence — a paid
    Gathering booking starts at ``pending_payment`` and only reaches
    ``confirmed`` when Stripe says the payment succeeded (see
    ``BookingStatus`` and ``gathering_tickets``), so there is no
    separate transaction to join against.

``access_pass_id IS NOT NULL`` + ``confirmed``
    A session reserved against a pass they bought — a term pass or
    class pass. The pass survives departure untouched, so the
    reservation it paid for should be reachable too.

A ``free`` or ``included_with_collective`` booking with no pass behind
it is membership-derived, not purchased, and is correctly lost on
departure. That boundary is the point: the exception restores access to
what was bought, not to what membership used to include.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.platform import (
    BookingStatus,
    Event,
    EventBooking,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
)

#: The access type whose bookings are bought one at a time.
PAID_SEPARATELY = "paid_separately"


def is_purchased_booking(booking: EventBooking, event: Event) -> bool:
    """Whether this confirmed booking represents a purchase.

    Takes both rows rather than querying, so the two callers that have
    already loaded them do not load them again.
    """
    status = getattr(booking.status, "value", booking.status)
    if status != BookingStatus.confirmed.value:
        return False
    if getattr(event, "booking_access_type", None) == PAID_SEPARATELY:
        return True
    return booking.access_pass_id is not None


def find_purchased_booking(
    db: Session, *, user_id: str | None, event: Event,
) -> EventBooking | None:
    """The caller's own paid booking for this Gathering, or ``None``.

    Scoped to ``user_id`` at the query, so there is no shape of this
    call that returns somebody else's reservation — the holder
    restriction is structural rather than a check after the fact.
    """
    if not user_id:
        return None
    booking = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event.id,
            EventBooking.user_id == user_id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    )
    if booking is None:
        return None
    return booking if is_purchased_booking(booking, event) else None


@dataclass(frozen=True)
class RetainedReservation:
    """One paid reservation in a Collective the holder has left."""

    event_id: str
    event_title: str
    starts_at: datetime
    ends_at: datetime | None
    space_slug: str
    space_name: str
    booking_id: str


def list_retained(
    db: Session, *, user_id: str, now: datetime,
) -> list[RetainedReservation]:
    """Upcoming paid reservations in Collectives this person has left.

    The "practical way to locate it" half of the exception. Deliberately
    only the left-behind ones: somebody who is still a member finds
    their Gatherings in the Collective's own Gatherings tab, and listing
    those here would put a second, competing surface in front of them.

    Only future Gatherings. A past one needs no route to attend it, and
    the attendance record is the creator's to keep rather than something
    to show a former member indefinitely.

    Ordered soonest first — the next thing they need to turn up to.
    """
    active_space_ids = {
        row[0]
        for row in db.query(SpaceMembership.space_id).filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
    }

    rows = (
        db.query(EventBooking, Event, Space)
        .join(Event, Event.id == EventBooking.event_id)
        .join(Space, Space.id == Event.space_id)
        .filter(
            EventBooking.user_id == user_id,
            EventBooking.status == BookingStatus.confirmed,
            Event.starts_at > now,
            Event.is_published.is_(True),
        )
        .order_by(Event.starts_at)
        .all()
    )

    retained: list[RetainedReservation] = []
    for booking, event, space in rows:
        if space.id in active_space_ids:
            continue
        if not is_purchased_booking(booking, event):
            continue
        # A Gathering the creator cancelled is not something to send
        # somebody to. The booking row stays; the listing does not
        # advertise it.
        if getattr(event, "status", "active") == "cancelled":
            continue
        retained.append(RetainedReservation(
            event_id=event.id,
            event_title=event.title,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            space_slug=space.slug,
            space_name=space.name,
            booking_id=booking.id,
        ))
    return retained


__all__ = [
    "PAID_SEPARATELY",
    "RetainedReservation",
    "find_purchased_booking",
    "is_purchased_booking",
    "list_retained",
]
