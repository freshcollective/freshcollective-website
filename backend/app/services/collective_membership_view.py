"""What one member may see and do about their own membership.

Why a view module rather than a serializer per route
----------------------------------------------------
Four surfaces ask almost the same question — the Collective About
page ("do I need to pay, and by when?"), the checkout return page
("did it work?"), Account Settings ("what am I paying, and what can I
change?"), and a resubscription prompt after a lapse. They differ in
where they appear, not in what is true. Writing the answer four times
is how a page ends up telling somebody their membership is active
while another page says it ended.

So the truth is assembled once, here, and the routes are thin.

Authoritative, and not from the Collective's list price
-------------------------------------------------------
Everything about money comes from the **agreement**, never from
``Space.pricing_amount_cents``. A creator who re-priced yesterday has
not re-priced anybody who already subscribed, so showing a member
today's list price would be showing them a number nobody will charge
them. The only place the Collective's own price is read is the offer
to somebody who does not yet hold an agreement — which is exactly
what they would be quoted.

What it never contains
----------------------
Stripe ids, customer ids, payment-method details, another member's
anything. The actions block says what this member may do; it is a
convenience for the UI and never the enforcement — every endpoint
re-asks for itself.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus, MANAGEABLE_STATUSES,
    is_one_time,
)
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.models.user import User
from app.services import collective_membership_access as access
from app.services import collective_membership_eligibility as elig
from app.spaces import membership_pricing

#: Statuses where a member is paying, or is expected to resume paying.
#: Used to decide whether to offer payment-method management.
_HAS_PAYMENT_METHOD_TO_MANAGE: frozenset[str] = frozenset({
    CollectiveMembershipStatus.active.value,
    CollectiveMembershipStatus.past_due.value,
    CollectiveMembershipStatus.cancel_scheduled.value,
})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def find_manageable(
    db: Session, *, user_id: str, space_id: str,
) -> CollectiveMembership | None:
    """The agreement this member could still act on, if any."""
    return (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.user_id == user_id,
            CollectiveMembership.space_id == space_id,
            CollectiveMembership.status.in_(sorted(MANAGEABLE_STATUSES)),
        )
        .order_by(CollectiveMembership.created_at.desc())
        .first()
    )


def find_latest(
    db: Session, *, user_id: str, space_id: str,
) -> CollectiveMembership | None:
    """The most recent agreement whatever its state.

    Used where the member needs to be told that something *ended* —
    a manageable lookup would answer "nothing here", which reads as
    "you never subscribed" and is not the same sentence.
    """
    return (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.user_id == user_id,
            CollectiveMembership.space_id == space_id,
        )
        .order_by(CollectiveMembership.created_at.desc())
        .first()
    )


def agreement_view(subscription: CollectiveMembership | None) -> dict | None:
    """The member's own agreement, in the terms they agreed to."""
    if subscription is None:
        return None
    one_time = is_one_time(subscription)
    return {
        "id": subscription.id,
        "status": subscription.status,
        "amount_cents": subscription.amount_cents,
        "currency": subscription.currency,
        "interval": subscription.interval,
        "interval_count": subscription.interval_count,
        # The field every surface branches on. A one-off joining fee
        # must never be shown with a renewal date, a cancel-renewal
        # action, or a card to keep current — each of those implies a
        # future charge that is not coming.
        "is_one_time": one_time,
        # One instant, two meanings, named for both so a page does not
        # have to decide what to call it: it is when the paid period
        # runs out, which is the renewal date unless renewal is off.
        "current_period_end": _iso(subscription.current_period_end),
        "cancel_at_period_end": bool(subscription.cancel_at_period_end),
        "renews_at": (
            None if (one_time or subscription.cancel_at_period_end)
            else _iso(subscription.current_period_end)
        ),
        "access_until": (
            _iso(subscription.current_period_end)
            if subscription.cancel_at_period_end else None
        ),
        # Only meaningful while recovery is running. Null the rest of
        # the time rather than a stale date from a cured failure.
        "grace_expires_at": (
            _iso(subscription.grace_expires_at)
            if subscription.status == CollectiveMembershipStatus.past_due.value
            else None
        ),
        "started_at": _iso(subscription.activated_at),
        "ended_at": _iso(subscription.ended_at),
    }


def membership_state(
    db: Session, *, user: User, space: Space,
) -> dict:
    """Everything one member needs to know about belonging here.

    Assembled from the membership row, the agreement and the
    Collective's own settings — in that order of authority.
    """
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .first()
    )
    member_status = (
        getattr(membership.status, "value", membership.status)
        if membership is not None else None
    )
    subscription = find_manageable(db, user_id=user.id, space_id=space.id)
    if subscription is None:
        subscription = find_latest(db, user_id=user.id, space_id=space.id)

    status = subscription.status if subscription is not None else None
    one_time = is_one_time(subscription)
    refusal = elig.refusal_for(db, user=user, space=space)
    is_owner = space.creator_id == user.id

    effective_at = space.paid_membership_effective_at
    transition_due = (
        effective_at is not None and effective_at <= datetime.utcnow()
    )

    return {
        "space": {
            "id": space.id,
            "slug": space.slug,
            "name": space.name,
        },
        "is_member": member_status == SpaceMembershipStatus.active.value,
        "membership_status": member_status,
        "is_owner": is_owner,
        # What somebody without an agreement would be quoted. Never
        # used to describe an agreement that already exists.
        "offer": {
            "pricing_type": space.pricing_type,
            "amount_cents": space.pricing_amount_cents,
            "currency": space.pricing_currency,
            "is_paid": membership_pricing.is_paid_membership(
                space.pricing_type,
            ),
            "subscribable": membership_pricing.transition_supported(
                space.pricing_type,
            ),
        },
        "transition": {
            "effective_at": _iso(effective_at),
            "effective_on": _iso(
                membership_pricing.transition_date_in_timezone(
                    effective_at, space.timezone,
                ),
            ),
            "has_passed": transition_due,
            # The member's own position: do they still have to do
            # something about this?
            "action_needed": (
                effective_at is not None
                and not is_owner
                and not access.holds_satisfying_agreement(
                    db, user_id=user.id, space_id=space.id,
                )
            ),
        },
        "subscription": agreement_view(subscription),
        "actions": {
            # ``refusal_for`` is the authority, asked rather than
            # re-derived: the checkout endpoint runs exactly this, so
            # a button shown here cannot lead to a door that refuses.
            "can_subscribe": refusal is None,
            "subscribe_refusal": None if refusal is None else refusal.code,
            # All three are about a *future* charge, so all three are
            # false for a fee that has already been paid in full.
            "can_cancel_renewal": not one_time and status in (
                CollectiveMembershipStatus.active.value,
                CollectiveMembershipStatus.past_due.value,
            ),
            "can_resume": not one_time and (
                status == CollectiveMembershipStatus.cancel_scheduled.value
            ),
            "can_update_payment_method": (
                not one_time
                and status in _HAS_PAYMENT_METHOD_TO_MANAGE
                and bool(subscription and subscription.stripe_subscription_id)
            ),
            "can_continue_checkout": (
                status == CollectiveMembershipStatus.pending.value
            ),
        },
    }
