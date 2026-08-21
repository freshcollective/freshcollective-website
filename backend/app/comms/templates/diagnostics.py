"""Template for the ``diagnostics.provider_probe`` event.

Renders a plainly-labelled diagnostic email so the recipient inbox
immediately signals "this is a provider-path proof, not a real
member communication". Kept in its own module to avoid any risk of
being mistaken for a production template.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT = "diagnostics.provider_probe"


@template_for(_EVENT, CHANNEL_EMAIL_TRANSACTIONAL)
class ProviderProbeEmailTemplate:
    key = "diagnostics.provider_probe.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        note = recipient.template_context.get("note") or ""
        triggered_at = recipient.template_context.get("triggered_at_iso") or ""

        subject = "Fresh Collective — provider path proof"

        body_text_parts = [
            "This is a diagnostic email from the Fresh Collective",
            "development environment.",
            "",
            "It was sent by the dev-only /api/internal/comms/dev-test-send",
            "endpoint to verify that the CommunicationEvent → resolver",
            "→ template → CommunicationIntent → CommunicationDelivery",
            "→ Resend path is wired end-to-end.",
            "",
            f"event_id:       {event.id}",
            f"event_type:     {event.event_type}",
            f"triggered_at:   {triggered_at}",
        ]
        if note:
            body_text_parts.extend(["", f"operator note:  {note}"])
        body_text_parts.extend([
            "",
            "If you received this in error, please ignore it — it is",
            "not a member-facing communication.",
        ])
        body_text = "\n".join(body_text_parts)

        body_html_parts = [
            "<p><strong>Fresh Collective — provider path proof</strong></p>",
            "<p>This is a diagnostic email from the Fresh Collective "
            "development environment.</p>",
            "<p>It was sent by the dev-only "
            "<code>/api/internal/comms/dev-test-send</code> endpoint to "
            "verify that the CommunicationEvent → resolver → template → "
            "CommunicationIntent → CommunicationDelivery → Resend path "
            "is wired end-to-end.</p>",
            "<pre style=\"font-family:ui-monospace,Menlo,monospace;"
            "font-size:12px;background:#f5f4ef;padding:12px;"
            "border-radius:8px\">"
            f"event_id:     {event.id}\n"
            f"event_type:   {event.event_type}\n"
            f"triggered_at: {triggered_at}"
            "</pre>",
        ]
        if note:
            body_html_parts.append(
                f"<p><em>operator note:</em> {note}</p>"
            )
        body_html_parts.append(
            "<p style=\"color:#888;font-size:12px\">If you received this "
            "in error, please ignore it — it is not a member-facing "
            "communication.</p>"
        )
        body_html = "\n".join(body_html_parts)

        return RenderedPayload(
            to="",  # decision pipeline / caller fills recipient_address
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "diagnostics_provider_probe"},
        )
