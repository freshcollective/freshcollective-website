"""
Fresh Collective — shared email templates.

One layout, many messages.

Every email Fresh Collective sends renders through :func:`render_email`
so the branding, spacing, footer copy and preferences link stay
consistent. Individual template functions (``password_reset_email``,
``invitation_email``, …) return an ``(subject, html)`` tuple ready to
hand to ``EmailService.send``.

Design principles kept small on purpose:

* Table-based markup — email clients (Outlook, Gmail's proxy, iOS
  Mail, all Fastmail variants) treat CSS flex/grid as decoration.
* Inline styles only — external stylesheets are stripped by many
  providers.
* Warm neutral background (``#F5F0E8`` ivory), white card, restrained
  teal accents. No hero images, no illustrations — the copy is the
  content.
* Preview text via a hidden preheader `<span>`.
* One primary call-to-action per email, rendered as a rounded pill
  button.
* Footer always links to Stay Connected preferences and identifies
  the sender.
"""

from __future__ import annotations

import html as _html

from app.core.config import settings

# ---------------------------------------------------------------------------
# Palette + text tokens — mirror the platform's editorial styling so
# emails feel like a natural extension of the Fresh Collective surface,
# without depending on any frontend module.
# ---------------------------------------------------------------------------

_BG_PAGE           = "#F5F0E8"    # ivory background
_BG_CARD           = "#FFFFFF"
_INK_HEADING       = "#0C1826"    # navy-950
_INK_BODY          = "#334155"    # slate-700
_INK_MUTED         = "#64748B"    # slate-500
_INK_ON_BUTTON     = "#FFFFFF"
_BORDER            = "#E8E8E5"
_ACCENT_1          = "#38A09E"
_ACCENT_2          = "#55B8B6"
_ACCENT_GRADIENT   = f"linear-gradient(135deg, {_ACCENT_1} 0%, {_ACCENT_2} 100%)"

_FONT_STACK_SANS   = (
    "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', "
    "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_FONT_STACK_SERIF  = "Georgia, 'Times New Roman', Times, serif"


# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------

def _preferences_url() -> str:
    return f"{settings.frontend_origin.rstrip('/')}/settings/stay-connected"


def render_email(
    *,
    preheader: str,
    heading: str,
    body_paragraphs: list[str],
    action: tuple[str, str] | None = None,   # (label, url)
    eyebrow: str | None = None,              # optional small label above the heading
    signoff: str | None = None,              # optional italic single-line signoff
) -> str:
    """Produce the Fresh Collective email shell.

    ``body_paragraphs`` are rendered as separate `<p>` blocks so the
    caller doesn't have to think about tags. HTML in the caller's
    strings is escaped — pass URLs via ``action`` instead of embedding
    ``<a>`` in the body.
    """
    safe_preheader = _html.escape(preheader)
    safe_heading   = _html.escape(heading)
    safe_eyebrow   = _html.escape(eyebrow) if eyebrow else None
    safe_signoff   = _html.escape(signoff) if signoff else None

    paras_html = "\n".join(
        f'''
        <tr>
          <td style="padding:0 40px 16px 40px;">
            <p style="margin:0;font-size:15.5px;line-height:1.65;color:{_INK_BODY};
                      font-family:{_FONT_STACK_SANS};">
              {_html.escape(p)}
            </p>
          </td>
        </tr>'''
        for p in body_paragraphs
    )

    action_html = ""
    if action is not None:
        label, url = action
        safe_label = _html.escape(label)
        safe_url = _html.escape(url, quote=True)
        action_html = f'''
        <tr>
          <td align="center" style="padding:16px 40px 8px 40px;">
            <a href="{safe_url}"
               style="display:inline-block;background:{_ACCENT_GRADIENT};
                      color:{_INK_ON_BUTTON};text-decoration:none;
                      padding:14px 32px;border-radius:999px;
                      font-family:{_FONT_STACK_SANS};font-size:14.5px;
                      font-weight:600;letter-spacing:0.01em;">
              {safe_label}
            </a>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:0 40px 8px 40px;">
            <p style="margin:0;font-size:11.5px;line-height:1.5;
                      color:{_INK_MUTED};font-family:{_FONT_STACK_SANS};
                      word-break:break-all;">
              or copy this link:<br />
              <span style="color:{_INK_MUTED};">{safe_url}</span>
            </p>
          </td>
        </tr>'''

    signoff_html = ""
    if safe_signoff:
        signoff_html = f'''
        <tr>
          <td style="padding:8px 40px 24px 40px;">
            <p style="margin:0;font-size:14px;line-height:1.6;
                      color:{_INK_MUTED};font-family:{_FONT_STACK_SERIF};
                      font-style:italic;">
              {safe_signoff}
            </p>
          </td>
        </tr>'''

    eyebrow_html = ""
    if safe_eyebrow:
        eyebrow_html = f'''
        <p style="margin:0 0 6px 0;font-size:11px;font-weight:600;
                  color:{_ACCENT_1};font-family:{_FONT_STACK_SANS};
                  letter-spacing:0.16em;text-transform:uppercase;">
          {safe_eyebrow}
        </p>'''

    prefs_url = _html.escape(_preferences_url(), quote=True)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>{safe_heading}</title>
</head>
<body style="margin:0;padding:0;background:{_BG_PAGE};
             font-family:{_FONT_STACK_SANS};">
  <!-- Preheader: shown as inbox preview text, invisible in the body. -->
  <span style="display:none !important;visibility:hidden;opacity:0;
               color:transparent;height:0;width:0;overflow:hidden;">
    {safe_preheader}
  </span>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{_BG_PAGE};padding:48px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="max-width:560px;background:{_BG_CARD};
                      border-radius:20px;overflow:hidden;
                      border:1px solid {_BORDER};">

          <!-- Brand mark -->
          <tr>
            <td align="center" style="padding:36px 40px 8px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:{_ACCENT_GRADIENT};width:32px;
                             height:32px;border-radius:8px;
                             vertical-align:middle;" align="center">
                    <div style="width:12px;height:12px;background:#FFFFFF;
                                border-radius:2px;margin:0 auto;"></div>
                  </td>
                  <td style="padding-left:10px;vertical-align:middle;">
                    <span style="font-size:15px;font-weight:600;
                                 color:{_INK_HEADING};
                                 font-family:{_FONT_STACK_SANS};
                                 letter-spacing:-0.01em;">
                      Fresh Collective
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Heading + optional eyebrow -->
          <tr>
            <td style="padding:24px 40px 12px 40px;">
              {eyebrow_html}
              <h1 style="margin:0;font-size:26px;line-height:1.2;
                         color:{_INK_HEADING};font-family:{_FONT_STACK_SERIF};
                         font-weight:400;letter-spacing:-0.01em;">
                {safe_heading}
              </h1>
            </td>
          </tr>

          <!-- Body paragraphs -->
          {paras_html}

          {action_html}
          {signoff_html}

          <!-- Footer -->
          <tr>
            <td style="padding:24px 40px 32px 40px;
                       border-top:1px solid {_BORDER};
                       margin-top:8px;">
              <p style="margin:0 0 6px 0;font-size:12px;font-weight:600;
                        color:{_INK_MUTED};font-family:{_FONT_STACK_SANS};
                        letter-spacing:0.04em;">
                Fresh Collective
              </p>
              <p style="margin:0;font-size:11.5px;line-height:1.6;
                        color:{_INK_MUTED};font-family:{_FONT_STACK_SANS};">
                This email was sent because of your communication preferences.
                <a href="{prefs_url}"
                   style="color:{_ACCENT_1};text-decoration:underline;">
                  Manage your Stay Connected preferences
                </a>.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Concrete templates — each returns (subject, html)
# ---------------------------------------------------------------------------

def password_reset_email(*, reset_url: str) -> tuple[str, str]:
    subject = "Reset your Fresh Collective password"
    html = render_email(
        preheader="Reset your Fresh Collective password. This link expires in 30 minutes.",
        eyebrow="Password",
        heading="Reset your password",
        body_paragraphs=[
            "We received a request to reset the password for your Fresh Collective account. "
            "Follow the link below to choose a new one.",
            "The link expires in 30 minutes.",
            "If you didn't request this, you can safely ignore this email — your password won't change.",
        ],
        action=("Reset password", reset_url),
    )
    return subject, html


def invitation_email(
    *,
    inviter_name: str,
    collective_name: str,
    accept_url: str,
    personal_note: str | None = None,
) -> tuple[str, str]:
    subject = f"{inviter_name} invited you to {collective_name}"
    body: list[str] = [
        f"{inviter_name} has invited you to join {collective_name} on Fresh Collective — "
        "a place to gather, learn together, and stay connected.",
    ]
    if personal_note and personal_note.strip():
        body.append(f"\u201C{personal_note.strip()}\u201D")
    body.append("Follow the link below to accept the invitation and set up your account.")
    html = render_email(
        preheader=f"{inviter_name} invited you to {collective_name}.",
        eyebrow="Invitation",
        heading=f"Join {collective_name}",
        body_paragraphs=body,
        action=("Accept invitation", accept_url),
    )
    return subject, html


def booking_confirmation_email(
    *,
    member_name: str,
    gathering_title: str,
    starts_when: str,           # human-readable, pre-formatted in the caller's tz
    location_line: str,         # e.g. "Zoom link will be shared before the gathering"
    view_url: str,              # link back into the gathering page
    add_to_calendar_url: str | None = None,
) -> tuple[str, str]:
    subject = f"Booking confirmed: {gathering_title}"
    body = [
        f"Hi {member_name}, your place is held at {gathering_title}.",
        f"When: {starts_when}",
        f"Where: {location_line}",
    ]
    if add_to_calendar_url:
        body.append("You can add this to your calendar with the link below, or open the gathering to see full details.")
    html = render_email(
        preheader=f"Your booking for {gathering_title} on {starts_when} is confirmed.",
        eyebrow="Gathering",
        heading=gathering_title,
        body_paragraphs=body,
        action=("View gathering", view_url),
        signoff=(
            f"Add to calendar: {add_to_calendar_url}"
            if add_to_calendar_url else None
        ),
    )
    return subject, html


def creator_announcement_email(
    *,
    creator_name: str,
    collective_name: str,
    title: str,
    message: str,
    url: str | None = None,
) -> tuple[str, str]:
    subject = title
    body = [message]
    action = ("Open in Fresh Collective", url) if url else None
    html = render_email(
        preheader=f"An announcement from {creator_name} in {collective_name}.",
        eyebrow=f"Announcement · {collective_name}",
        heading=title,
        body_paragraphs=body,
        action=action,
        signoff=f"— {creator_name}",
    )
    return subject, html


def new_pathway_email(
    *,
    pathway_title: str,
    collective_name: str,
    pathway_url: str,
    lead_line: str | None = None,
) -> tuple[str, str]:
    subject = f"New pathway: {pathway_title}"
    body = [
        lead_line
        or f"A new pathway has been added to {collective_name} — take a look when you're ready.",
    ]
    html = render_email(
        preheader=f"A new pathway is available in {collective_name}.",
        eyebrow=f"Pathway · {collective_name}",
        heading=pathway_title,
        body_paragraphs=body,
        action=("Open pathway", pathway_url),
    )
    return subject, html


def reply_notification_email(
    *,
    replier_name: str,
    quote: str,
    reply_url: str,
    in_context: str,            # e.g. "in your reflection" or "on your post"
) -> tuple[str, str]:
    subject = f"{replier_name} replied {in_context}"
    body = [
        f"{replier_name} replied {in_context} on Fresh Collective:",
        f"\u201C{quote}\u201D",
    ]
    html = render_email(
        preheader=f"{replier_name} replied {in_context}.",
        eyebrow="Reply",
        heading=f"{replier_name} replied",
        body_paragraphs=body,
        action=("Open the conversation", reply_url),
    )
    return subject, html
