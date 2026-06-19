"""
Email delivery via Resend.

If RESEND_API_KEY is not set, all send attempts are gracefully skipped
with a warning log — this allows the notification system to work in
development without any email configuration.
"""
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def notification_email_html(title: str, message: str, url: str | None, action_label: str = "View") -> str:
    """Return a clean minimal HTML email body."""
    button_html = ""
    if url:
        button_html = f"""
        <tr>
          <td align="center" style="padding: 24px 0 8px 0;">
            <a href="{url}"
               style="display:inline-block;background:linear-gradient(135deg,#38A09E,#55B8B6);
                      color:#ffffff;text-decoration:none;padding:12px 28px;
                      border-radius:10px;font-size:14px;font-weight:600;">
              {action_label}
            </a>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#F5F5F2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F5F2;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:16px;overflow:hidden;
                      border:1px solid #E8E8E5;max-width:560px;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#38A09E,#55B8B6);padding:28px 36px;">
              <span style="font-size:16px;font-weight:700;color:#ffffff;letter-spacing:-0.02em;">
                Fresh Collective
              </span>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:36px 36px 8px 36px;">
              <h1 style="margin:0 0 12px 0;font-size:20px;font-weight:700;
                         color:#0D1B2A;letter-spacing:-0.02em;">{title}</h1>
              <p style="margin:0;font-size:15px;line-height:1.6;color:#4A5568;">{message}</p>
            </td>
          </tr>
          {button_html}
          <!-- Footer -->
          <tr>
            <td style="padding:28px 36px 32px 36px;border-top:1px solid #F0F0ED;margin-top:16px;">
              <p style="margin:0;font-size:12px;color:#9CA3AF;line-height:1.5;">
                You're receiving this because you're a member of Fresh Collective.
                Manage your notification preferences in your collective settings.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


class EmailService:
    """Thin wrapper around Resend email delivery."""

    def send(self, to: str, subject: str, html_body: str) -> None:
        """Send an email. Silently no-ops if RESEND_API_KEY is not configured."""
        if not settings.resend_api_key:
            logger.warning(
                "RESEND_API_KEY is not set — skipping email to %s (subject: %s)", to, subject
            )
            return

        try:
            import resend  # type: ignore[import-untyped]
            resend.api_key = settings.resend_api_key
            resend.Emails.send({
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html_body,
            })
        except Exception:
            logger.exception("Failed to send email to %s (subject: %s)", to, subject)
            # Do not re-raise — email failure must not crash routes or background tasks


email_service = EmailService()
