"""Templates for collective-membership events.

R2A coverage: ``collective.invitation.sent`` — the email a
prospective member receives when a creator sends them an invitation
to a Collective. Content mirrors the tone of the legacy
``services/email_templates.py::invitation_email`` template so the
switch is invisible to the recipient.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT = "collective.invitation.sent"


@template_for(_EVENT, CHANNEL_EMAIL_TRANSACTIONAL)
class InvitationSentEmailTemplate:
    key = "collective.invitation.sent.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        ctx = recipient.template_context
        inviter_name    = ctx.get("inviter_name") or "A creator"
        collective_name = ctx.get("collective_name") or "a Collective"
        accept_url      = ctx.get("accept_url") or ""

        subject = f"{inviter_name} invited you to {collective_name}"

        body_text = (
            f"{inviter_name} has invited you to join {collective_name} on "
            "Fresh Collective — a place to gather, learn together, and stay "
            "connected.\n\n"
            "Follow the link below to accept the invitation and set up your "
            "account:\n"
            f"{accept_url}"
        )

        body_html = (
            f'<p>{inviter_name} has invited you to join '
            f'<strong>{collective_name}</strong> on Fresh Collective — a '
            "place to gather, learn together, and stay connected.</p>"
            f'<p><a href="{accept_url}">Accept the invitation</a> and set up '
            "your account.</p>"
        )

        return RenderedPayload(
            to="",  # decision pipeline fills recipient_address on the intent
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "collective_invitation_sent"},
        )
