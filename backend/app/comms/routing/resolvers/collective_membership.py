"""Resolvers for the paid Collective membership lifecycle.

Six events, all single-recipient: the member whose money and access
changed, carried as the event's ``actor_user_id``. Every member-facing
fact is resolved at emit time by
``services/collective_membership_emit.py``, so these only thread the
payload through — the same division the creator-subscription resolvers
use, and for the same reason: a resolver that re-derived prices from
live rows would describe today's catalogue rather than the agreement the
member actually holds.

The creator is deliberately **not** a recipient of any of them. These
are receipts and account notices addressed to the person whose card it
is; what the creator sees is their Payments received ledger, and
anything else about a member's billing is not theirs to be told.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


def _member(
    event: CommunicationEvent, human_reason: str, keys: tuple[str, ...],
) -> list[ResolvedRecipient]:
    if not event.actor_user_id:
        return []
    payload = event.payload or {}
    return [
        ResolvedRecipient(
            user_id=event.actor_user_id,
            role_in_event="member",
            human_reason=human_reason,
            template_context={k: payload.get(k) for k in keys},
        ),
    ]


#: Every message names the Collective and the terms the member agreed
#: to — never the creator's current advertised price.
#:
#: ``collective_timezone`` is here rather than on the one template that
#: needs it, because *every* membership message carries a date and all
#: of them were rendering it in UTC. A period ending at 14:00 on the
#: 20th is already the 21st in Melbourne, so members were being told a
#: date before the one they keep.
#:
#: Worth knowing how that survived review: the context is whitelisted
#: here, key by key, and a template asking for something absent from
#: this tuple silently gets ``None``. The first fix put the timezone in
#: the template and tested it with a hand-built context — proving the
#: template and not the pipeline. Anything added to a template's
#: expectations has to be added here too.
_COMMON = ("first_name", "collective_name", "collective_url", "amount_label",
           "interval_label", "membership_url", "collective_timezone")


@resolver_for("collective.membership.purchased")
class MembershipPurchasedResolver:
    event_type = "collective.membership.purchased"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "You joined a collective with a paid membership.",
            _COMMON + ("next_renewal_at", "one_time"),
        )


@resolver_for("collective.membership.renewed")
class MembershipRenewedResolver:
    event_type = "collective.membership.renewed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "A payment on your collective membership was received.",
            _COMMON + ("next_renewal_at", "period_label"),
        )


@resolver_for("collective.membership.payment_failed")
class MembershipPaymentFailedResolver:
    event_type = "collective.membership.payment_failed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "A payment on your collective membership could not be "
            "processed.",
            _COMMON + ("grace_expires_at",),
        )


@resolver_for("collective.membership.cancellation_scheduled")
class MembershipCancellationScheduledResolver:
    event_type = "collective.membership.cancellation_scheduled"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "Your collective membership is scheduled to end.",
            _COMMON + ("access_until",),
        )


@resolver_for("collective.membership.ended")
class MembershipEndedResolver:
    event_type = "collective.membership.ended"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "Your collective membership has ended.",
            _COMMON,
        )


@resolver_for("collective.membership.renewal_resumed")
class MembershipRenewalResumedResolver:
    event_type = "collective.membership.renewal_resumed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "You turned renewal back on for a collective membership.",
            _COMMON + ("next_renewal_at",),
        )


@resolver_for("collective.membership.payment_method_updated")
class MembershipPaymentMethodUpdatedResolver:
    event_type = "collective.membership.payment_method_updated"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "The card on your collective membership was changed.",
            _COMMON + ("next_renewal_at",),
        )


@resolver_for("collective.membership.reactivated")
class MembershipReactivatedResolver:
    event_type = "collective.membership.reactivated"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        return _member(
            event,
            "Your collective membership is active again.",
            _COMMON + ("next_renewal_at",),
        )
