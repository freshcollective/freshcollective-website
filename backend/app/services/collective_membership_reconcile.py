"""Catching what the webhooks missed.

Webhooks are not guaranteed to arrive once, in order, or at all. Most of
the time they do, and this sweep finds nothing. The cases it exists for
are the ones where silence costs money or access:

``grace_expired``
    A renewal failed, the window passed and nothing recovered. Ends the
    agreement — **at Stripe as well as locally**, because grace expiring
    is Fresh Collective's policy and not Stripe giving up; it may still
    be retrying.

``period_elapsed``
    A cancellation was scheduled and the paid period has run out.
    Stripe's own ``customer.subscription.deleted`` normally does this;
    this is the backstop for when it does not arrive.

``billing_after_departure``
    **The one that matters most.** A membership has ended — left,
    removed or banned — and the agreement is still live. Either the
    Stripe cancel failed at the time or an agreement was opened after.
    Retried here, which is the durable recovery ``end_membership``
    promises when it cannot reach Stripe.

``paid_transition``
    A Collective's ``paid_membership_effective_at`` has passed and a
    member has no paid agreement. Their membership pauses. Nobody is
    charged and nobody is subscribed: the creator told their members,
    and those who did not subscribe lose membership-derived access.

Safe to run as often as the schedule likes. Every branch checks the
state it is about to change, so a second pass over the same row does
nothing, and a run that dies halfway leaves the rows it already fixed
fixed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import (
    Space, SpaceMembership, SpaceMembershipStatus,
)
from app.services import collective_membership_access as access
from app.services import collective_membership_lifecycle as lifecycle

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    grace_expired: int = 0
    period_elapsed: int = 0
    billing_after_departure: int = 0
    billing_after_departure_failed: int = 0
    transitions_paused: int = 0
    bookings_released: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "grace_expired": self.grace_expired,
            "period_elapsed": self.period_elapsed,
            "billing_after_departure": self.billing_after_departure,
            "billing_after_departure_failed":
                self.billing_after_departure_failed,
            "transitions_paused": self.transitions_paused,
            "bookings_released": self.bookings_released,
            "errors": self.errors,
        }


def _sweep_grace_expired(
    db: Session, *, now: datetime, report: ReconcileReport,
) -> None:
    rows = (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.status
            == CollectiveMembershipStatus.past_due.value,
            CollectiveMembership.grace_expires_at.isnot(None),
            CollectiveMembership.grace_expires_at < now,
        )
        .all()
    )
    for sub in rows:
        # Read before the attempt. After ``db.rollback()`` these
        # attributes are expired and reloading them can raise, which
        # would lose the very error being reported.
        sub_id = sub.id
        try:
            outcome = access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=now,
            )
            report.grace_expired += 1
            report.bookings_released += outcome.bookings_released
            db.commit()
        except Exception as exc:
            db.rollback()
            report.errors.append(f"grace_expired {sub_id}: {exc}")
            logger.exception(
                "membership reconcile: could not end lapsed sub=%s", sub_id,
            )


def _sweep_period_elapsed(
    db: Session, *, now: datetime, report: ReconcileReport,
) -> None:
    rows = (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.status
            == CollectiveMembershipStatus.cancel_scheduled.value,
            CollectiveMembership.current_period_end.isnot(None),
            CollectiveMembership.current_period_end < now,
        )
        .all()
    )
    for sub in rows:
        sub_id = sub.id
        try:
            outcome = access.end_subscription(
                db, subscription=sub, reason="paid_period_ended", now=now,
            )
            report.period_elapsed += 1
            report.bookings_released += outcome.bookings_released
            db.commit()
        except Exception as exc:
            db.rollback()
            report.errors.append(f"period_elapsed {sub_id}: {exc}")
            logger.exception(
                "membership reconcile: could not close expired sub=%s", sub_id,
            )


def _sweep_billing_after_departure(
    db: Session, *, now: datetime, report: ReconcileReport,
) -> None:
    """Live agreements whose membership has already ended.

    The retry behind ``end_membership``'s promise. A failure here is
    logged as an ERROR and counted, never swallowed: it means somebody
    who has left is still being charged.
    """
    rows = (
        db.query(CollectiveMembership, SpaceMembership)
        .join(
            SpaceMembership,
            (SpaceMembership.user_id == CollectiveMembership.user_id)
            & (SpaceMembership.space_id == CollectiveMembership.space_id),
        )
        .filter(
            CollectiveMembership.status.in_(
                sorted(lifecycle._CANCELLABLE_STATUSES)
            ),
            SpaceMembership.status == SpaceMembershipStatus.removed,
        )
        .all()
    )
    for sub, membership in rows:
        sub_id, user_id, space_id = sub.id, sub.user_id, sub.space_id
        try:
            lifecycle.cancel_subscription_now(
                db, subscription=sub,
                reason="reconcile:membership_already_ended", now=now,
            )
            report.billing_after_departure += 1
            logger.warning(
                "membership reconcile: stopped billing that outlived a "
                "departure sub=%s user=%s space=%s",
                sub_id, user_id, space_id,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            report.billing_after_departure_failed += 1
            report.errors.append(f"billing_after_departure {sub_id}: {exc}")
            logger.exception(
                "membership reconcile: STILL cannot stop billing for a "
                "departed member sub=%s user=%s space=%s",
                sub_id, user_id, space_id,
            )


def _sweep_paid_transitions(
    db: Session, *, now: datetime, report: ReconcileReport,
) -> None:
    """Collectives whose paid-membership date has arrived.

    Pauses members who have no live paid agreement. Charges nobody,
    subscribes nobody, and emails nobody — the creator owns that
    conversation, and by this point they have had it.

    The Collective's owner is never paused; ``pause_membership_for_lapse``
    refuses that case, so this does not have to remember to.
    """
    spaces = (
        db.query(Space)
        .filter(
            Space.paid_membership_effective_at.isnot(None),
            Space.paid_membership_effective_at <= now,
        )
        .all()
    )
    for space in spaces:
        members = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        )
        space_id, space_slug = space.id, space.slug
        for membership in members:
            member_user_id = membership.user_id
            if member_user_id == space.creator_id:
                continue
            paid = (
                db.query(CollectiveMembership.id)
                .filter(
                    CollectiveMembership.user_id == membership.user_id,
                    CollectiveMembership.space_id == space.id,
                    CollectiveMembership.status.in_([
                        CollectiveMembershipStatus.active.value,
                        CollectiveMembershipStatus.past_due.value,
                        CollectiveMembershipStatus.cancel_scheduled.value,
                    ]),
                )
                .first()
            )
            if paid is not None:
                continue
            try:
                # A synthetic agreement carrying only the identity the
                # pause needs. Nothing is written for it — this member
                # never had an agreement, which is precisely why they
                # are being paused.
                stand_in = CollectiveMembership(
                    id="reconcile-transition",
                    user_id=membership.user_id,
                    space_id=space.id,
                    status=CollectiveMembershipStatus.ended.value,
                    interval="month", interval_count=1,
                    amount_cents=1, currency="AUD",
                )
                outcome = access.pause_membership_for_lapse(
                    db, subscription=stand_in, now=now,
                )
                if outcome.membership_paused:
                    report.transitions_paused += 1
                report.bookings_released += outcome.bookings_released
                db.commit()
            except Exception as exc:
                db.rollback()
                report.errors.append(
                    f"paid_transition {space_slug}/{member_user_id}: {exc}"
                )
                logger.exception(
                    "membership reconcile: transition pause failed "
                    "space=%s user=%s", space_id, member_user_id,
                )


def reconcile_collective_memberships(
    db: Session, *, now: datetime | None = None,
) -> ReconcileReport:
    """Run every sweep. Commits per row, so one bad row cannot undo the rest."""
    now = now or datetime.utcnow()
    report = ReconcileReport()
    _sweep_grace_expired(db, now=now, report=report)
    _sweep_period_elapsed(db, now=now, report=report)
    _sweep_billing_after_departure(db, now=now, report=report)
    _sweep_paid_transitions(db, now=now, report=report)
    logger.info("membership reconcile: %s", report.as_dict())
    return report
