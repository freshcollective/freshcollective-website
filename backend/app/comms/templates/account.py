"""Templates for account category events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_IN_APP
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import template_for


_EVENT_PASSWORD_RESET_REQUESTED = "account.password_reset_requested"


@template_for(_EVENT_PASSWORD_RESET_REQUESTED, CHANNEL_EMAIL_TRANSACTIONAL)
class PasswordResetRequestedEmailTemplate:
    key = "account.password_reset_requested.email_transactional"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        reset_url = recipient.template_context.get("reset_url") or ""
        subject = "Reset your Fresh Collective password"
        body_text = (
            "You asked to reset your password.\n\n"
            f"Open this link to choose a new one:\n{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this message."
        )
        body_html = (
            "<p>You asked to reset your password.</p>"
            f'<p><a href="{reset_url}">Open this link to choose a new one</a>.</p>'
            "<p>If you didn't request this, you can safely ignore this message.</p>"
        )
        return RenderedPayload(
            to="",  # decision pipeline fills recipient_address on the intent
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            metadata={"notification_type": "password_reset_requested"},
        )


@template_for(_EVENT_PASSWORD_RESET_REQUESTED, CHANNEL_IN_APP)
class PasswordResetRequestedInAppTemplate:
    key = "account.password_reset_requested.in_app"
    version = "v1"

    def render(
        self, db: Session, event: CommunicationEvent, recipient: ResolvedRecipient,
    ) -> RenderedPayload:
        return RenderedPayload(
            to="",
            subject="Password reset requested",
            body_text="A password reset link was sent to your email.",
            metadata={"notification_type": "password_reset_requested"},
        )
