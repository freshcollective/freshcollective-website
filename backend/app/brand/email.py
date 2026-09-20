"""The brand header both email renderers share.

Two shells send Fresh Collective email — the comms pipeline's
``app/comms/templates/base.py`` and the legacy
``app/services/email_templates.py``, which still serves the paths that
have not migrated. They have always carried byte-identical brand
markup by careful copying. This module makes that structural: one
function, imported by both, so the two cannot drift and a change to
how Fresh Collective signs its email is a single edit.

What replaced what
------------------

Both shells drew the brand as CSS: a 32px teal rounded square holding
a smaller white square, beside the words "Fresh Collective". It was a
placeholder that outlived its welcome, and it is gone.

The header now renders the approved primary lockup as an image. Not
the compact mark — Fresh Collective has no approved compact artwork
yet, and the two things this file will not do are invent one or shrink
the full lockup into a mark-sized slot. The full lockup at a size
where its wordmark is readable is the honest option available today.

Email constraints, and why each one is here
-------------------------------------------

* **A raster image at an absolute https URL.** SVG is unsupported or
  stripped by Gmail, Outlook for Windows and Yahoo; base64 ``data:``
  URIs are stripped by Gmail; a CSS ``background-image`` is ignored by
  Outlook's Word renderer. An ``<img>`` with a real URL is the only
  treatment that works everywhere.
* **Explicit ``width`` and ``height`` attributes.** Outlook for
  Windows ignores CSS sizing, and without the attributes it renders
  the artwork at its intrinsic 500px.
* **``alt="Fresh Collective"``.** Most clients block remote images by
  default, so for a large share of recipients the alt text *is* the
  brand. It also means the header degrades to the sender's name rather
  than to a broken-image icon.
* **``border="0"`` and ``display:block``.** Older Outlook draws a
  border on a linked image; inline images inherit a baseline gap that
  ``display:block`` removes.
* **Served at 2× the rendered size.** The artwork is 500px and renders
  at 240px, so it stays sharp on a retina display without a second
  asset.

Where the URL comes from
------------------------

``app.brand.resolver``, the same resolver the admin screen and the
site use. An admin upload wins when it is safe to send — the resolver
returns a public URL only for artwork under the unauthenticated
``platform-artwork/`` prefix — and the approved bundled default is
used otherwise. A presigned or session-gated URL can never reach an
inbox, because the resolver withholds it rather than handing back
something that 403s for every recipient.
"""

from __future__ import annotations

import contextvars
import html as _html
import logging

from sqlalchemy.orm import Session

from app.brand.resolver import bundled_default_public_url, resolve_for_email


# The role the email header uses. A named constant because the day the
# compact marks are approved, the decision about whether email moves to
# "mark + live text" is a change to this line and the markup below it —
# not a hunt through two renderers.
EMAIL_HEADER_ROLE = "primary_light_logo"

# Rendered size. Chosen by rendering the real shell at 140, 168, 200
# and 240 and looking at all four: 240 read as an illustration rather
# than a letterhead — the dragonfly was larger than the heading and
# pushed the call to action down the card — while 140 lost the
# wordmark. 200 is where the logo reads as the sender rather than as
# the subject. On a 560px card that is 36% of the width, and with the
# artwork's own 33% margin the visible lockup is about 24% — the
# proportion a brand header usually takes.
#
# The wordmark is 3% of the canvas, so 200px puts its cap height at
# 6px: comfortable on the retina displays most mail is read on, and
# legible at 1x. The 32px placeholder this replaced would have given
# 1px, which is why the old header needed live text beside it to say
# who the email was from.
EMAIL_LOGO_PX = 200

_FONT_STACK_SANS = (
    "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', "
    "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_INK_HEADING = "#0C1826"

logger = logging.getLogger(__name__)


# Admin preview renders through the real template and the real shell —
# that is the guarantee ``app/admin/email_templates.py`` is built on —
# but it does so without a session, so the brand header would resolve
# to the bundled default even when an upload exists. This ContextVar
# lets the preview endpoint supply the URL it already resolved, so the
# preview and the send agree about the logo as well as the copy.
_preview_logo: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fc_email_brand_logo", default=None,
)


class preview_brand_logo:
    """Force the header URL for the duration of one render."""

    def __init__(self, url: str | None) -> None:
        self._url = url
        self._token = None

    def __enter__(self) -> "preview_brand_logo":
        self._token = _preview_logo.set(self._url)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _preview_logo.reset(self._token)


def email_logo_url(db: Session | None = None) -> str | None:
    """Absolute, publicly-fetchable URL for the email header lockup.

    ``db`` may be ``None`` — several render paths (admin preview, the
    dev probe, unit tests) have no session, and they correctly get the
    approved bundled default.
    """
    forced = _preview_logo.get()
    if forced:
        return forced
    if db is not None:
        try:
            uploaded = resolve_for_email(db, EMAIL_HEADER_ROLE)
        except Exception:
            # A database problem must never stop an email going out —
            # the same rule the editable-copy resolver follows. The
            # approved bundled artwork is always available without a
            # session, so the worst case is an email that shows the
            # default logo rather than an admin's replacement.
            logger.exception(
                "brand: could not resolve the email logo — using the "
                "approved bundled default",
            )
        else:
            if uploaded:
                return uploaded
    return bundled_default_public_url(EMAIL_HEADER_ROLE)


def brand_header_html(
    db: Session | None = None,
    brand_logo_url: str | None = None,
) -> str:
    """The brand row, ready to drop into either shell's card table.

    ``brand_logo_url`` short-circuits resolution; the admin preview
    passes the URL it already resolved so a preview cannot disagree
    with a real send.

    With no artwork resolvable at all — which should not happen, since
    the primary role has an approved bundled default — this falls back
    to the name set as live text. An email that cannot show its logo
    must still say who it is from.
    """
    url = brand_logo_url or email_logo_url(db)

    if not url:
        return f'''
          <tr>
            <td align="center" style="padding:36px 40px 8px 40px;">
              <span style="font-size:17px;font-weight:600;
                           color:{_INK_HEADING};
                           font-family:{_FONT_STACK_SANS};
                           letter-spacing:-0.01em;">
                Fresh Collective
              </span>
            </td>
          </tr>'''

    safe_url = _html.escape(url, quote=True)
    return f'''
          <tr>
            <td align="center" style="padding:20px 40px 0 40px;">
              <img src="{safe_url}" alt="Fresh Collective"
                   width="{EMAIL_LOGO_PX}" height="{EMAIL_LOGO_PX}" border="0"
                   style="display:block;margin:0 auto;border:0;outline:none;
                          text-decoration:none;
                          width:{EMAIL_LOGO_PX}px;height:{EMAIL_LOGO_PX}px;
                          max-width:100%;" />
            </td>
          </tr>'''
