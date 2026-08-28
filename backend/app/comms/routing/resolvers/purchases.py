"""Resolvers for member money/access lifecycle events.

R3 coverage — five events, all single-recipient (the paying member).
The event's ``actor_user_id`` is the member; the payload carries
member-facing context resolved at emit time so the template does
not need to re-query the domain graph.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


def _base_context(event: CommunicationEvent) -> dict:
    """Common template context every purchase-lifecycle template needs.
    Emit sites populate the payload; resolvers thread it through."""
    p = event.payload or {}
    return {
        "first_name":      p.get("first_name") or "",
        "experience_name": p.get("experience_name") or "",
        "member_url":      p.get("member_url") or "",
        "amount_cents":    p.get("amount_cents"),
        "currency":        (p.get("currency") or "").upper(),
    }


@resolver_for("purchase.completed")
class PurchaseCompletedResolver:
    event_type = "purchase.completed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        p = event.payload or {}
        ctx = _base_context(event)
        ctx.update({
            # 'single' | 'plan'
            "payment_mode":          p.get("payment_mode") or "single",
            "installments_paid":     p.get("installments_paid"),
            "installments_expected": p.get("installments_expected"),
        })
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="buyer",
                human_reason=(
                    "You completed a purchase on Fresh Collective."
                ),
                template_context=ctx,
            ),
        ]


@resolver_for("payment.instalment_failed")
class PaymentInstalmentFailedResolver:
    event_type = "payment.instalment_failed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        p = event.payload or {}
        ctx = _base_context(event)
        ctx.update({
            "grace_expires_at":      p.get("grace_expires_at") or "",
            "repair_url":            p.get("repair_url") or "",
            "installments_paid":     p.get("installments_paid"),
            "installments_expected": p.get("installments_expected"),
        })
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="buyer",
                human_reason=(
                    "There is a problem with a payment on your payment plan."
                ),
                template_context=ctx,
            ),
        ]


@resolver_for("access.suspended")
class AccessSuspendedResolver:
    event_type = "access.suspended"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        p = event.payload or {}
        ctx = _base_context(event)
        ctx.update({
            "repair_url":            p.get("repair_url") or "",
            "installments_paid":     p.get("installments_paid"),
            "installments_expected": p.get("installments_expected"),
        })
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="buyer",
                human_reason=(
                    "Your access has been paused because a payment could "
                    "not be recovered in time."
                ),
                template_context=ctx,
            ),
        ]


@resolver_for("payment.recovered")
class PaymentRecoveredResolver:
    event_type = "payment.recovered"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        p = event.payload or {}
        ctx = _base_context(event)
        ctx.update({
            # True when access had actually been suspended before this
            # recovery; False when the recovery landed inside the grace
            # window (access never lapsed). Drives copy branching.
            "was_suspended":         bool(p.get("was_suspended")),
            "installments_paid":     p.get("installments_paid"),
            "installments_expected": p.get("installments_expected"),
        })
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="buyer",
                human_reason=(
                    "A previously failed payment on your payment plan "
                    "has been recovered."
                ),
                template_context=ctx,
            ),
        ]


@resolver_for("purchase.plan_completed")
class PurchasePlanCompletedResolver:
    event_type = "purchase.plan_completed"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        p = event.payload or {}
        ctx = _base_context(event)
        ctx.update({
            "installments_paid":     p.get("installments_paid"),
            "installments_expected": p.get("installments_expected"),
            "total_paid_cents":      p.get("total_paid_cents"),
        })
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="buyer",
                human_reason=(
                    "You have finished paying for a Fresh Collective "
                    "payment plan."
                ),
                template_context=ctx,
            ),
        ]
