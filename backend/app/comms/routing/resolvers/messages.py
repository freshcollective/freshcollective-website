"""Resolvers for direct-message events.

M5b coverage: ``dm.message.sent`` — the recipient is the thread's
other participant, carried in the event payload as ``recipient_id``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("dm.message.sent")
class DirectMessageResolver:
    event_type = "dm.message.sent"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        recipient_id = payload.get("recipient_id")
        if not recipient_id:
            return []
        sender_name = payload.get("sender_name") or "a member"
        return [
            ResolvedRecipient(
                user_id=recipient_id,
                role_in_event="thread_participant",
                human_reason=f"{sender_name} sent you a message.",
                template_context={
                    "sender_name": sender_name,
                    "thread_id": payload.get("thread_id"),
                    "excerpt": payload.get("excerpt"),
                },
            ),
        ]
