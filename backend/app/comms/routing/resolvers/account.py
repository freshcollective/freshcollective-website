"""Resolvers for account-related events.

M5b coverage: ``account.password_reset_requested`` — the single-
recipient locked-category example. The event's ``actor_user_id`` is
the recipient (they asked for the reset).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("account.password_reset_requested")
class PasswordResetRequestedResolver:
    event_type = "account.password_reset_requested"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="account_owner",
                human_reason="You requested a password reset for your account.",
                template_context={
                    "reset_url": (event.payload or {}).get("reset_url"),
                },
            ),
        ]
