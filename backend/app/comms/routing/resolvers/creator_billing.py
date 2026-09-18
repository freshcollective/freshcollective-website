"""Resolvers for the creator monthly-subscription lifecycle.

All four events are single-recipient: the creator whose subscription
changed state, carried as the event's ``actor_user_id``. The emit
helpers in ``app/services/creator_billing_emit.py`` resolve every
member-facing fact at emit time, so these resolvers only thread the
payload through.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


def _recipients(
    event: CommunicationEvent, human_reason: str, keys: tuple[str, ...],
) -> list[ResolvedRecipient]:
    if not event.actor_user_id:
        return []
    payload = event.payload or {}
    return [
        ResolvedRecipient(
            user_id=event.actor_user_id,
            role_in_event="creator",
            human_reason=human_reason,
            template_context={k: payload.get(k) for k in keys},
        ),
    ]


_COMMON = ("first_name", "plan_label", "billing_url")


@resolver_for("creator.subscription.payment_failed")
class CreatorSubscriptionPaymentFailedResolver:
    event_type = "creator.subscription.payment_failed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _recipients(
            event,
            "A payment on your Fresh Collective Creator plan could not be "
            "processed.",
            _COMMON + ("grace_expires_at",),
        )


@resolver_for("creator.subscription.recovered")
class CreatorSubscriptionRecoveredResolver:
    event_type = "creator.subscription.recovered"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _recipients(
            event,
            "A payment on your Fresh Collective Creator plan was recovered.",
            _COMMON + ("current_period_end",),
        )


@resolver_for("creator.subscription.cancellation_scheduled")
class CreatorSubscriptionCancellationScheduledResolver:
    event_type = "creator.subscription.cancellation_scheduled"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _recipients(
            event,
            "Your Fresh Collective Creator plan is scheduled to end.",
            _COMMON + ("current_period_end",),
        )


@resolver_for("creator.subscription.cancelled")
class CreatorSubscriptionCancelledResolver:
    event_type = "creator.subscription.cancelled"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _recipients(
            event,
            "Your Fresh Collective Creator plan has ended.",
            _COMMON + ("ended_at",),
        )
