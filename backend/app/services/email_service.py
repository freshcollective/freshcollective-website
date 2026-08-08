"""Legacy email delivery entry point.

Every previous caller of ``email_service.send(...)`` and
``notification_email_html(...)`` continues to work unchanged. Internally
this module is now a thin shim over
:class:`app.comms.providers.resend.ResendProvider` — every send flows
through the Communications Layer's provider registry, and the
Resend-specific details live inside the provider.

Callers do not need to change during the M3–M15 transition:

* ``email_service.send(...)`` still accepts the same keyword arguments
  and still returns ``None`` (delivery errors are captured by the
  provider and never re-raised).
* ``notification_email_html(...)`` still returns rendered HTML.

New code should prefer emitting a communication event
(``app.comms.emit``) and letting the future intent / delivery layer
select the right provider; the shim below is retained only to keep
the current trigger sites simple during the shadow-rollout milestone.
"""

from __future__ import annotations

import logging

from app.comms.providers import get as get_provider
from app.comms.providers.base import RenderedPayload
from app.services.email_templates import render_email


logger = logging.getLogger(__name__)


class EmailService:
    """Thin wrapper around the Resend provider.

    Public signature unchanged from the pre-M3 version. Internally,
    every send is built into a :class:`RenderedPayload` and dispatched
    through :func:`app.comms.providers.get`.
    """

    def send(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        reply_to: str | None = None,
    ) -> None:
        """Send an email via the registered Resend provider.

        Behaviour preserved from before M3: config-missing skips are
        logged and swallowed; provider failures are logged and
        swallowed. Callers never see an exception.
        """
        provider = get_provider("resend")
        provider.send(
            RenderedPayload(
                to=to,
                subject=subject,
                body_html=html_body,
                reply_to=reply_to,
            )
        )


email_service = EmailService()


# ---------------------------------------------------------------------------
# Compatibility shim
#
# The legacy ``notification_email_html(title, message, url)`` signature is
# used by every existing notification trigger. Rather than migrate every
# caller in one go, the shim renders through the shared layout so every
# legacy trigger picks up the refreshed branding automatically. New code
# should call the concrete templates in
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
