"""Resolver for the ``diagnostics.provider_probe`` event.

Used exclusively by the R1 dev-only test-send endpoint. The event's
``payload["recipient_email"]`` is the address the operator wants the
provider path to write to; ``event.actor_user_id`` is the user record
we hang the intent off (for ``ResolvedRecipient.user_id`` — the
decision pipeline requires one).

Kept in its own tiny resolver file so it never gets mistaken for a
member-facing production resolver.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("diagnostics.provider_probe")
class ProviderProbeResolver:
    event_type = "diagnostics.provider_probe"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        if not event.actor_user_id:
            return []
        payload = event.payload or {}
        target = payload.get("recipient_email")
        if not isinstance(target, str) or not target:
            return []
        return [
            ResolvedRecipient(
                user_id=event.actor_user_id,
                role_in_event="operator",
                human_reason=(
                    "Development-only provider probe — this delivery was "
                    "triggered from the internal /api/internal/comms/"
                    "dev-test-send endpoint."
                ),
                recipient_address_override=target,
                template_context={
                    "note": payload.get("note") or "",
                    "triggered_at_iso": payload.get("triggered_at_iso") or "",
                },
            ),
        ]
