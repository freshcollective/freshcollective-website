"""What a subscription ending does to belonging — and what it must not.

The separation this module defends
----------------------------------
A financial agreement ending **pauses membership-derived access**. It
does not remove the member, does not erase their history, and is not a
moderation decision. ``SpaceMembership.paused`` says exactly that: not
active, recoverable, provenance intact — which is why it is used here
and ``removed`` is not. Using ``removed`` would destroy the
``removal_kind`` that ``may_rejoin`` depends on, and make resubscribing
look like a creator reversing themselves.

Access checks never read Stripe
-------------------------------
The 78 call sites that filter ``status == active`` are untouched and
know nothing about billing. The subscription drives the membership
column; the membership column drives access. That one-way linkage is
what keeps an invited, comped or creator-owned membership unaffected by
anybody's card.

Bookings
--------
Ending membership releases only future reservations whose **sole** basis
was membership. A seat bought with a ticket, a Series pass, a Pathway or
a Payment Option is somebody's property and survives — Stage 4B's
booking attribution is what makes the difference legible, and
``retained_reservations`` already makes a paid seat usable to a former
member.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import (
    BookingStatus, Event, EventBooking, Space, SpaceMembership,
    SpaceMembershipStatus,
)

logger = logging.getLogger(__name__)

#: Booking sources that mean "this seat exists because you belong here".
#: Everything else — a bought ticket, a Payment Option, a caretaker
#: adding somebody — is a claim of its own and is left alone.
MEMBERSHIP_ONLY_SOURCES: frozenset[str] = frozenset({"member"})


@dataclass(frozen=True)
class LapseOutcome:
    membership_paused: bool
    bookings_released: int
    skipped_reason: str | None = None


def _booking_has_independent_support(booking: EventBooking) -> bool:
    """Does anything other than membership hold this seat?

    Reads the attribution Stage 4B put on the row. A pass, a payment or
    a plan each means somebody has a claim that outlived their
    membership; ``creator_manual`` and ``creator_pass`` mean a caretaker
    put them there, which a lapsed card does not undo.
    """
    if booking.access_pass_id:
        return True
    if booking.payment_transaction_id:
        return True
    if booking.purchase_plan_id:
        return True
    source = (booking.source or "").strip()
    if source and source not in MEMBERSHIP_ONLY_SOURCES:
        return True
    return False


def release_membership_only_bookings(
    db: Session, *, user_id: str, space_id: str, now: datetime,
) -> int:
    """Release future seats that only membership was holding.

    Future only: a Gathering that has already happened is history, and
    rewriting attendance because a card later failed would falsify the
    record. Idempotent — an already-cancelled booking is skipped, so a
    reconciler may run this as often as it likes.

    Capacity follows automatically: ``capacity_used`` counts confirmed
    bookings and live holds, so cancelling the row frees the seat
    without any separate bookkeeping.
    """
    rows = (
        db.query(EventBooking)
        .join(Event, Event.id == EventBooking.event_id)
        .filter(
            EventBooking.user_id == user_id,
            Event.space_id == space_id,
            Event.starts_at > now,
            EventBooking.status.in_([
                BookingStatus.confirmed, BookingStatus.pending_payment,
            ]),
        )
        .all()
    )
    released = 0
    for booking in rows:
        if _booking_has_independent_support(booking):
            logger.info(
                "membership lapse: keeping booking=%s event=%s — "
                "supported independently (source=%s pass=%s txn=%s plan=%s)",
                booking.id, booking.event_id, booking.source,
                booking.access_pass_id, booking.payment_transaction_id,
                booking.purchase_plan_id,
            )
            continue
        booking.status = BookingStatus.cancelled
        booking.cancelled_at = now
        released += 1
        logger.info(
            "membership lapse: released booking=%s event=%s user=%s "
            "space=%s — membership was its only support",
            booking.id, booking.event_id, user_id, space_id,
        )
    if released:
        db.flush()
    return released


def pause_membership_for_lapse(
    db: Session, *,
    subscription: CollectiveMembership,
    now: datetime,
    release_bookings: bool = True,
) -> LapseOutcome:
    """The agreement has ended. Pause the belonging it was paying for.

    Deliberately narrow about what it will touch:

    * Only an ``active`` membership is paused. A ``removed`` one has
      already ended for a reason that outranks billing, and overwriting
      it would erase why.
    * The Collective's **owner is never paused**. Their access is
      management, not something they bought, and a creator locked out of
      their own Collective by their own pricing would be absurd.
    * A membership that did not come from this subscription is paused
      just the same — it is membership-derived access that has stopped
      being paid for, however it began. What is *not* touched is any
      purchased entitlement, which lives in its own tables.
    """
    space = db.query(Space).filter(Space.id == subscription.space_id).first()
    if space is not None and space.creator_id == subscription.user_id:
        logger.info(
            "membership lapse: not pausing the Collective's owner "
            "(user=%s space=%s)", subscription.user_id, subscription.space_id,
        )
        return LapseOutcome(False, 0, skipped_reason="collective_owner")

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == subscription.space_id,
            SpaceMembership.user_id == subscription.user_id,
        )
        .first()
    )
    if membership is None:
        return LapseOutcome(False, 0, skipped_reason="no_membership")

    status = (
        membership.status.value
        if hasattr(membership.status, "value") else str(membership.status)
    )
    if status == SpaceMembershipStatus.paused.value:
        # Already paused. Still sweep bookings — a previous run may have
        # paused and then failed partway.
        released = (
            release_membership_only_bookings(
                db, user_id=subscription.user_id,
                space_id=subscription.space_id, now=now,
            ) if release_bookings else 0
        )
        return LapseOutcome(False, released, skipped_reason="already_paused")
    if status != SpaceMembershipStatus.active.value:
        return LapseOutcome(False, 0, skipped_reason=f"status_{status}")

    membership.status = SpaceMembershipStatus.paused
    db.flush()
    logger.info(
        "membership lapse: paused membership user=%s space=%s (sub=%s)",
        subscription.user_id, subscription.space_id, subscription.id,
    )

    released = (
        release_membership_only_bookings(
            db, user_id=subscription.user_id,
            space_id=subscription.space_id, now=now,
        ) if release_bookings else 0
    )
    return LapseOutcome(True, released)


def reactivate_paused_membership(
    db: Session, *,
    subscription: CollectiveMembership,
    now: datetime,
) -> str:
    """Bring a subscription-lapsed membership back, and nothing else.

    Why this exists rather than widening
    ``membership_grant.ensure_membership_for_purchase``: that function
    deliberately skips a ``paused`` row with ``skipped_reason=
    "status_paused"``, and four other purchase paths share it. Teaching
    it to unpause would mean any purchase of anything could silently
    reverse a pause applied for a reason that had nothing to do with
    that purchase — including ``creator_eligibility``'s. So the narrow
    path is here, reached only by a verified membership payment for the
    same Collective.

    Readmission restrictions still hold. A ``removed`` membership is not
    unpaused by this at any price — ``ensure_membership_for_purchase``
    owns that case and refuses a creator's removal or an admin's
    revocation, which is correct and is left alone.
    """
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == subscription.space_id,
            SpaceMembership.user_id == subscription.user_id,
        )
        .first()
    )
    if membership is None:
        return "no_membership"
    status = (
        membership.status.value
        if hasattr(membership.status, "value") else str(membership.status)
    )
    if status == SpaceMembershipStatus.active.value:
        return "already_active"
    if status != SpaceMembershipStatus.paused.value:
        # ``removed`` and anything new. Not this function's business.
        return f"status_{status}"

    membership.status = SpaceMembershipStatus.active
    db.flush()
    logger.info(
        "collective membership: unpaused membership user=%s space=%s "
        "after payment (sub=%s)",
        subscription.user_id, subscription.space_id, subscription.id,
    )
    return "unpaused"


def end_subscription(
    db: Session, *,
    subscription: CollectiveMembership,
    reason: str,
    now: datetime,
    release_bookings: bool = True,
) -> LapseOutcome:
    """The paid period is over, or grace ran out. Stop everything.

    Cancels at Stripe as well as locally. Grace expiring is not the same
    as Stripe having given up — it may still be retrying on its own
    schedule — so the provider is told explicitly rather than assumed to
    have stopped.
    """
    from app.services.collective_membership_lifecycle import (
        cancel_subscription_now,
    )

    if subscription.status not in (
        CollectiveMembershipStatus.ended.value,
        CollectiveMembershipStatus.cancelled.value,
    ):
        cancel_subscription_now(
            db, subscription=subscription, reason=reason, now=now,
        )
        subscription.status = CollectiveMembershipStatus.ended.value
        subscription.ended_at = now
        subscription.updated_at = now
        db.flush()

        # Said only where access actually stops — never where a
        # cancellation is merely scheduled. Conflating the two is the
        # specific mistake the brief names.
        from app.services import collective_membership_emit as _emit

        _emit.emit_membership_ended(db, subscription=subscription)

    return pause_membership_for_lapse(
        db, subscription=subscription, now=now,
        release_bookings=release_bookings,
    )
