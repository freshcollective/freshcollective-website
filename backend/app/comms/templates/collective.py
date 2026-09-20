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
from app.comms.templates.base import render_email_shell
from app.comms.templates.editable import resolver_for
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

        r = resolver_for(db, self.key, {
            **ctx,
            "inviter_name": inviter_name,
            "collective_name": collective_name,
        })
        subject = r.text("subject")
        opening = r.text("body.opening")
        instruction = r.text("body.instruction")
        cta = r.text("cta_label")

        body_text = (
            f"{opening}\n\n"
            # The plain-text part introduces the bare URL, so the
            # instruction ends in a colon there rather than a full stop.
            f"{instruction.rstrip('.')}:\n"
            f"{accept_url}"
        )

        # No preferences link: the invitee usually has no account yet, so
        # there are no preferences for them to manage.
        body_html = render_email_shell(
            db=db,
            preheader=opening,
            heading=r.text("heading"),
            body_paragraphs=[opening, instruction],
            action=(cta, accept_url),
            show_preferences_link=False,
        )

        return RenderedPayload(
            to="",  # decision pipeline fills recipient_address on the intent
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "collective_invitation_sent"},
        )
