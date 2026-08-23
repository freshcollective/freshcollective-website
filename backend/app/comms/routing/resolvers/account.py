"""Resolvers for account-related events.

Covers:

* ``account.password_reset_requested`` (M5b) — the single-recipient
  locked-category example. The event's ``actor_user_id`` is the
  recipient (they asked for the reset).
* ``account.welcome_after_signup`` (R2B) — the transactional welcome
  email a new account receives once. The event's ``actor_user_id`` is
  the recipient (they just signed up).
* ``creator.plan_activated`` (R2B) — the transactional creator-plan
  activation email. Recipient is the creator whose plan just went
  inactive→active; the event's ``actor_user_id`` is that user.
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


@resolver_for("account.welcome_after_signup")
class WelcomeAfterSignupResolver:
    event_type = "account.welcome_after_signup"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        payload = event.payload or {}
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="account_owner",
                human_reason="You just created your Fresh Collective account.",
                template_context={
                    "first_name": payload.get("first_name") or "",
                    "next_url":   payload.get("next_url") or "",
                },
            ),
        ]


@resolver_for("creator.plan_activated")
class CreatorPlanActivatedResolver:
    event_type = "creator.plan_activated"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        payload = event.payload or {}
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="account_owner",
                human_reason=(
                    "Your Fresh Collective Creator plan is now active."
                ),
                template_context={
                    "first_name":       payload.get("first_name") or "",
                    "plan_name":        payload.get("plan_name") or "",
                    "was_reactivated":  bool(payload.get("was_reactivated")),
                    # Fresh creator → first-Collective ritual; else →
                    # Creator Studio directly. Sourced from persisted
                    # ``user.creator_onboarded_at`` at emit time.
                    "is_fresh_creator": bool(payload.get("is_fresh_creator")),
                    "next_url":         payload.get("next_url") or "",
                },
            ),
        ]
