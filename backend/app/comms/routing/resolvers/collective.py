"""Resolvers for collective-membership events.

R2A coverage: ``collective.invitation.sent`` — one recipient (the
prospective member), addressed by the email the creator entered on
the draft invitation. The recipient almost never has a Fresh
Collective account yet, so we address them via
``recipient_address_override`` and fall back to the inviter's
user_id for ``ResolvedRecipient.user_id`` (the decision pipeline
requires a real id).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("collective.invitation.sent")
class InvitationSentResolver:
    event_type = "collective.invitation.sent"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        target = payload.get("recipient_email")
        if not isinstance(target, str) or not target:
            return []
        # A prospective member usually has no account yet. We need a
        # real user_id for the ResolvedRecipient (the decision layer
        # loads preferences off it); the inviter is the only party we
        # can be sure has one, and using them keeps the audit trail
        # honest ("this send was authorised by this inviter").
        pipeline_user_id = event.actor_user_id
        if not pipeline_user_id:
            return []
        return [
            ResolvedRecipient(
                user_id=pipeline_user_id,
                role_in_event="invitee",
                human_reason=(
                    "A creator invited you to join their Collective on "
                    "Fresh Collective."
                ),
                recipient_address_override=target,
                template_context={
                    "inviter_name":     payload.get("inviter_name") or "",
                    "collective_name":  payload.get("collective_name") or "",
                    "accept_url":       payload.get("accept_url") or "",
                },
            ),
        ]
