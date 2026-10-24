"""Template Protocol + the canonical Fresh Collective email shell.

Two things live here:

* :class:`Template` — the Protocol every registered template satisfies.
* :func:`render_email_shell` — the one branded HTML shell every
  ``email_transactional`` template in the comms pipeline renders
  through.

The shell
---------

Adapted from ``app/services/email_templates.py::render_email``, which
remains in place for the legacy ``notification_service`` triggers that
have not yet been ported to the comms pipeline (P1 migrates the comms
side only). The visual treatment is deliberately identical so the two
paths are indistinguishable in an inbox during the transition.

Differences from the legacy renderer, all intentional:

* **No eyebrow.** The legacy shell accepted an ``eyebrow`` argument and
  rendered an uppercase letterspaced teal label above the heading.
  Fresh Collective does not use eyebrow labels; the parameter is not
  carried across.
* **Explicit greeting slot.** The greeting is a first-class argument
  rather than the caller's first body paragraph, so a template's
  greeting policy is visible at the call site and directly testable.
* **Conditional preferences link.** An email a member cannot turn off
  should not offer them a link to turn it off, so those templates pass
  ``show_preferences_link=False`` and get a sender-identifying footer
  instead. Each template states its own answer rather than deriving
  one, because the reason differs: Purchases is a locked category
  (``communication_channel_defaults.is_locked``), while the essential
  Account emails are locked per event in
  ``app.comms.registry.TRANSACTIONAL_EVENT_TYPES``.

  One known gap, deliberately left for a copy pass:
  ``account.welcome_after_signup`` became preference-controlled in
  migration 133 but still omits the link, so a member who can now
  decline the welcome email is not told so in it.

Escaping boundary
-----------------

**Every string argument is treated as untrusted plain text and is
HTML-escaped here.** Callers pass text, never markup — which is what
makes this function the single escaping boundary for the pipeline.
Interpolating a collective name, gathering title, post title or
member name into a caller-built ``<p>`` and passing that in would
double-escape the markup and render tags as literal text; the fix is
always to pass the value as its own plain-text paragraph.

Design constraints inherited from the legacy shell: table-based
markup, inline styles only, no external stylesheets, one primary call
to action.

The "no hero imagery" constraint was lifted for the Collective welcome
email, which carries its Collective's own artwork — see ``banner``.
Nothing else passes one, and the parameter is opt-in so every other
email keeps the plain card.
"""

from __future__ import annotations

import html as _html
from typing import Any, Protocol, Sequence

from sqlalchemy.orm import Session

from app.brand.email import brand_header_html
from app.comms.models import CommunicationEvent
from app.comms.providers.base import RenderedPayload
from app.comms.routing.resolver import ResolvedRecipient
from app.core.public_url import public_app_url


class Template(Protocol):
    """Renders a (event, recipient) pair to a :class:`RenderedPayload`
    ready to hand to a provider.

    Implementations declare :attr:`key` (unique per registry — the
    natural key is ``{event_type}.{channel}``), :attr:`version` (a
    semver-ish string bumped when subject/body semantics change), and
    :attr:`channel` (the channel this template renders for).
    """

    key: str
    version: str
    event_type: str
    channel: str

    def render(
        self,
        db: Session,
        event: CommunicationEvent,
        recipient: ResolvedRecipient,
    ) -> RenderedPayload: ...


# ---------------------------------------------------------------------------
# Palette + type tokens — mirrored from the legacy shell so both paths
# look identical in an inbox during the transition.
# ---------------------------------------------------------------------------

_BG_PAGE         = "#F5F0E8"    # ivory
_BG_CARD         = "#FFFFFF"
_INK_HEADING     = "#0C1826"    # navy-950
#: Width of the email card. Named so the banner cannot drift from
#: the table it sits in — a banner wider than the card overflows
#: on every client, and one narrower leaves a seam.
_CARD_PX         = 560
_INK_BODY        = "#334155"    # slate-700
_INK_MUTED       = "#64748B"    # slate-500
_INK_ON_BUTTON   = "#FFFFFF"
_BORDER          = "#E8E8E5"
_ACCENT_1        = "#38A09E"
_ACCENT_2        = "#55B8B6"
_ACCENT_GRADIENT = f"linear-gradient(135deg, {_ACCENT_1} 0%, {_ACCENT_2} 100%)"

_FONT_STACK_SANS = (
    "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', "
    "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_FONT_STACK_SERIF = "Georgia, 'Times New Roman', Times, serif"


def preferences_url() -> str:
    """Absolute URL of the member's Stay Connected preferences page."""
    return public_app_url("/settings/stay-connected")


def _esc_text(value: str) -> str:
    """Escape a string destined for *element content*.

    ``quote=False`` because quotes carry no meaning between tags —
    escaping them would turn every apostrophe in the copy into
    ``&#x27;`` for no security benefit. Attribute values still use
    ``quote=True``; see ``_esc_attr``.
    """
    return _html.escape(value, quote=False)


def _esc_attr(value: str) -> str:
    """Escape a string destined for a double-quoted attribute value."""
    return _html.escape(value, quote=True)


def render_email_shell(
    *,
    preheader: str,
    heading: str,
    body_paragraphs: Sequence[str],
    greeting: str | None = None,
    # (url, alt) for a landscape image across the top of the card,
    # under the Fresh Collective logo and above the heading. Passed as
    # two plain strings rather than as markup because this module is
    # the single escaping boundary — see the module docstring.
    banner: tuple[str, str] | None = None,
    action: tuple[str, str] | None = None,   # (label, url)
    signoff: str | None = None,
    # How the sign-off is set. "muted" is the Fresh Collective
    # flourish every platform email has always used: small, grey, a
    # deliberate step down from the message.
    #
    # "body" is for a sign-off somebody WROTE. A creator's signature
    # is part of their message, not a footnote to it, so it is set at
    # body size and body colour — still italic, because that is what
    # makes it read as a signature rather than another paragraph.
    #
    # Opt-in rather than a change of default: five existing templates
    # pass a Fresh Collective sign-off through this argument and none
    # of them should change appearance.
    signoff_style: str = "muted",
    show_preferences_link: bool = True,
    db: Any = None,
    brand_logo_url: str | None = None,
) -> str:
    """Wrap plain-text content in the Fresh Collective email shell.

    ``body_paragraphs`` are rendered as separate ``<p>`` blocks. Every
    argument is escaped — pass the CTA destination via ``action``
    rather than embedding an anchor in the body.

    ``show_preferences_link`` controls only the preferences sentence.
    The sender-identifying footer is always rendered.

    ``db`` is threaded through only so the brand header can resolve an
    admin-uploaded logo; passing ``None`` yields the approved bundled
    artwork, which is the correct answer for previews and tests rather
    than a degraded one. ``brand_logo_url`` short-circuits that lookup
    for callers that have already resolved it.
    """
    banner_html = ""
    if banner is not None and banner[0]:
        banner_url, banner_alt = banner
        # Conventions are brand/email.py's, which documents why each
        # one is needed: a raster at an absolute https URL (SVG and
        # data: URIs are stripped by major clients), an explicit
        # ``width`` attribute because Outlook for Windows ignores CSS
        # sizing, ``border="0"`` because older Outlook draws a border,
        # and ``display:block`` to kill the inline baseline gap.
        #
        # Height is deliberately left to the image. A fixed height
        # would need a crop to avoid distortion, and Outlook's Word
        # renderer ignores ``object-fit`` — so it would squash the
        # artwork rather than crop it. Proportional scaling keeps the
        # landscape composition intact in every client.
        #
        # Full-bleed to the card edge rather than inset to the 40px
        # text gutter: this is the Collective's own world, and it
        # reads as a window rather than as an illustration dropped
        # into a letter.
        banner_html = f'''
          <tr>
            <td style="padding:20px 0 0 0;font-size:0;line-height:0;">
              <img src="{_esc_attr(banner_url)}" alt="{_esc_attr(banner_alt)}"
                   width="{_CARD_PX}" border="0"
                   style="display:block;width:100%;max-width:{_CARD_PX}px;
                          height:auto;border:0;outline:none;
                          text-decoration:none;" />
            </td>
          </tr>'''

    safe_preheader = _esc_text(preheader)
    safe_heading   = _esc_text(heading)
    safe_greeting  = _esc_text(greeting) if greeting else None
    safe_signoff   = _esc_text(signoff) if signoff else None

    greeting_html = ""
    if safe_greeting:
        greeting_html = f'''
        <tr>
          <td style="padding:0 40px 16px 40px;">
            <p style="margin:0;font-size:15.5px;line-height:1.65;color:{_INK_BODY};
                      font-family:{_FONT_STACK_SANS};">
              {safe_greeting}
            </p>
          </td>
        </tr>'''

    paras_html = "\n".join(
        f'''
        <tr>
          <td style="padding:0 40px 16px 40px;">
            <p style="margin:0;font-size:15.5px;line-height:1.65;color:{_INK_BODY};
                      font-family:{_FONT_STACK_SANS};">
              {_esc_text(p)}
            </p>
          </td>
        </tr>'''
        for p in body_paragraphs
        if p and p.strip()
    )

    action_html = ""
    if action is not None:
        label, url = action
        safe_label = _esc_text(label)
        safe_url = _esc_attr(url)
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
        # Line breaks survive.
        #
        # A signature is written as lines — "With warmth," then the
        # name — and HTML collapses the newline between them, so the
        # default sign-off arrived as one run-on line. Escaped first,
        # then the newlines become <br />: the replacement runs over
        # text that is already safe, so it cannot introduce markup.
        signoff_body = safe_signoff.replace("\n", "<br />")
        if signoff_style == "body":
            signoff_css = (
                f"margin:0;font-size:15.5px;line-height:1.65;"
                f"color:{_INK_BODY};font-family:{_FONT_STACK_SERIF};"
                f"font-style:italic;"
            )
            # Clear of the message above it, the way a signature sits
            # under a letter rather than against it.
            signoff_pad = "padding:16px 40px 24px 40px;"
        else:
            signoff_css = (
                f"margin:0;font-size:14px;line-height:1.6;"
                f"color:{_INK_MUTED};font-family:{_FONT_STACK_SERIF};"
                f"font-style:italic;"
            )
            signoff_pad = "padding:8px 40px 24px 40px;"
        signoff_html = f'''
        <tr>
          <td style="{signoff_pad}">
            <p style="{signoff_css}">
              {signoff_body}
            </p>
          </td>
        </tr>'''

    prefs_html = ""
    if show_preferences_link:
        prefs_url = _esc_attr(preferences_url())
        prefs_html = f'''
              <p style="margin:0;font-size:11.5px;line-height:1.6;
                        color:{_INK_MUTED};font-family:{_FONT_STACK_SANS};">
                This email was sent because of your communication preferences.
                <a href="{prefs_url}"
                   style="color:{_ACCENT_1};text-decoration:underline;">
                  Manage your Stay Connected preferences
                </a>.
              </p>'''

    brand_header = brand_header_html(db, brand_logo_url)

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
        <table role="presentation" width="{_CARD_PX}" cellpadding="0" cellspacing="0"
               style="max-width:{_CARD_PX}px;background:{_BG_CARD};
                      border-radius:20px;overflow:hidden;
                      border:1px solid {_BORDER};">

          <!-- Brand — see app/brand/email.py; shared with the
               legacy renderer so the two cannot drift. -->
          {brand_header}
          {banner_html}

          <!-- Heading -->
          <tr>
            <td style="padding:24px 40px 12px 40px;">
              <h1 style="margin:0;font-size:26px;line-height:1.2;
                         color:{_INK_HEADING};font-family:{_FONT_STACK_SERIF};
                         font-weight:400;letter-spacing:-0.01em;">
                {safe_heading}
              </h1>
            </td>
          </tr>

          {greeting_html}

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
              </p>{prefs_html}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


__all__ = [
    "RenderedPayload",
    "Template",
    "preferences_url",
    "render_email_shell",
]
