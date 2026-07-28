"""
Fresh Collective — email delivery via Resend.

Two responsibilities:

  * ``EmailService.send`` — the thin wrapper that puts a message on the
    wire (or skips gracefully in dev).
  * ``notification_email_html`` — kept as a **compatibility shim** so
    existing callers (``notification_service.py`` and
    ``notifications/routes.py``) keep working during the migration to
    the new template layouts in ``email_templates.py``. New callers
    should import from ``email_templates`` directly and use
    ``EmailService.send`` with the returned ``(subject, html)``.

Environment behaviour:

  * ``RESEND_API_KEY`` unset → send is skipped with a WARN log.
    Intended for local development; feature code stays clean.
  * ``RESEND_API_KEY`` set but ``EMAIL_FROM`` unset → send fails
    loudly with an ERROR log (no silent fallback to another domain).
    Delivery must be configured explicitly per environment.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.email_templates import render_email

logger = logging.getLogger(__name__)


class EmailService:
    """Thin wrapper around Resend email delivery."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        reply_to: str | None = None,
    ) -> None:
        """Send an email.

        Missing ``RESEND_API_KEY``: skip with WARN. Missing ``EMAIL_FROM``
        when the key IS set: skip with ERROR (never silently switch to a
        default domain). Every runtime failure is caught and logged so
        request handlers and background tasks never crash on delivery.

        ``to`` / ``subject`` / ``html_body`` / ``reply_to`` are
        keyword-only so a future audit trail (message id, correlation
        id) can be added without ambiguity at the call sites.
        """
        if not settings.resend_api_key:
            logger.warning(
                "RESEND_API_KEY is not set — skipping email to %s (subject: %s)",
                to, subject,
            )
            return

        sender = settings.email_from
        if not sender:
            logger.error(
                "EMAIL_FROM is not configured — refusing to send to %s (subject: %s). "
                "Set EMAIL_FROM to an RFC 5322 address on a verified Resend domain.",
                to, subject,
            )
            return

        payload: dict = {
            "from": sender,
            "to": [to],
            "subject": subject,
            "html": html_body,
        }
        # Prefer the explicit per-send override, then the environment default.
        # Absent both → Resend routes replies to the From header, which is
        # what most launches want.
        effective_reply_to = reply_to or settings.email_reply_to
        if effective_reply_to:
            payload["reply_to"] = effective_reply_to

        try:
            import resend  # type: ignore[import-untyped]
            resend.api_key = settings.resend_api_key
            resend.Emails.send(payload)
        except Exception:
            logger.exception("Failed to send email to %s (subject: %s)", to, subject)
            # Do not re-raise — email failure must not crash routes or background tasks


email_service = EmailService()


# ---------------------------------------------------------------------------
# Compatibility shim
#
# The legacy ``notification_email_html(title, message, url)`` signature is
# used by every existing notification trigger. Rather than migrate every
# caller in one go, the shim renders through the new shared layout so
# every legacy trigger picks up the refreshed branding automatically.
# New code should call the concrete templates in
# ``app.services.email_templates`` instead.
# ---------------------------------------------------------------------------

def notification_email_html(
    title: str,
    message: str,
    url: str | None,
    action_label: str = "View",
) -> str:
    return render_email(
        preheader=message[:150],
        heading=title,
        body_paragraphs=[message],
        action=(action_label, url) if url else None,
    )
