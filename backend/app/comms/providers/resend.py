"""Resend — transactional email provider.

Wraps the same call the previous ``EmailService.send`` made, moved
behind the :class:`~app.comms.providers.base.DeliveryProvider`
protocol. The legacy ``EmailService.send()`` public function stays as
a thin shim delegating here so no existing caller changes.

Configuration:

* ``RESEND_API_KEY`` — required to send. When absent, the provider
  reports ``offline`` and returns a rejected result without contacting
  Resend. Intended for local development.
* ``EMAIL_FROM``    — required RFC 5322 address on a verified Resend
  domain. When absent (but the API key is set), sends are rejected
  loudly rather than silently rerouted.
* ``EMAIL_REPLY_TO`` — optional default; per-payload ``reply_to`` wins.
"""

from __future__ import annotations

import logging

from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
)
from app.comms.providers.base import (
    DeliveryProvider,
    HealthStatus,
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    now_utc,
)
from app.core.config import settings


logger = logging.getLogger(__name__)


class ResendProvider:
    """Sends transactional email via the Resend HTTP API."""

    key: str = "resend"
    capabilities: frozenset[str] = frozenset({CHANNEL_EMAIL_TRANSACTIONAL})
    production_eligible: bool = True

    def send(self, payload: RenderedPayload) -> ProviderResult:
        if not settings.resend_api_key:
            logger.warning(
                "RESEND_API_KEY is not set — skipping email to %s (subject: %s)",
                payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class="config_missing",
                error_detail="RESEND_API_KEY is not set.",
            )

        sender = settings.email_from
        if not sender:
            logger.error(
                "EMAIL_FROM is not configured — refusing to send to %s "
                "(subject: %s). Set EMAIL_FROM to an RFC 5322 address on a "
                "verified Resend domain.",
                payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class="config_missing",
                error_detail="EMAIL_FROM is not configured.",
            )

        # Resend requires an html or text body. If neither is present,
        # this is a caller bug; refuse rather than send an empty email.
        if not payload.body_html and not payload.body_text:
            logger.error(
                "ResendProvider.send called with no body_html or body_text "
                "(to=%s, subject=%s)", payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class="empty_body",
                error_detail="RenderedPayload has no body_html or body_text.",
            )

        request: dict = {
            "from": sender,
            "to": [payload.to],
            "subject": payload.subject,
        }
        if payload.body_html:
            request["html"] = payload.body_html
        if payload.body_text:
            request["text"] = payload.body_text

        effective_reply_to = payload.reply_to or settings.email_reply_to
        if effective_reply_to:
            request["reply_to"] = effective_reply_to

        try:
            import resend  # type: ignore[import-untyped]
            resend.api_key = settings.resend_api_key
            result = resend.Emails.send(request)
        except Exception as exc:  # noqa: BLE001 — provider failure is a signal
            logger.exception(
                "Failed to send email to %s (subject: %s)",
                payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class=type(exc).__name__,
                error_detail=str(exc),
            )

        message_id: str | None = None
        if isinstance(result, dict):
            id_val = result.get("id")
            if isinstance(id_val, str):
                message_id = id_val
        return ProviderResult(accepted=True, provider_message_id=message_id)

    def health(self) -> ProviderHealth:
        if not settings.resend_api_key:
            return ProviderHealth(
                status=HealthStatus.OFFLINE,
                checked_at=now_utc(),
                detail="RESEND_API_KEY is not set.",
            )
        if not settings.email_from:
            return ProviderHealth(
                status=HealthStatus.OFFLINE,
                checked_at=now_utc(),
                detail="EMAIL_FROM is not configured.",
            )
        # Milestone 3 does not probe the Resend HTTP API — a live probe
        # would add latency and quota use on every health call. When
        # provider metrics land (future milestone) the ``metrics`` dict
        # will carry rolling error rate + latency samples and the
        # verdict can escalate to DEGRADED without a call.
        return ProviderHealth(
            status=HealthStatus.HEALTHY,
            checked_at=now_utc(),
        )


# Runtime protocol check — a plain assert here catches shape drift at
# import time rather than at first send.
assert isinstance(ResendProvider(), DeliveryProvider)
