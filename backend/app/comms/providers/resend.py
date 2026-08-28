"""Resend — transactional email provider (outbound) and webhook
consumer (inbound).

Implements both :class:`~app.comms.providers.base.DeliveryProvider`
(``send``, ``health``) and :class:`~app.comms.webhooks.WebhookProvider`
(``verify_webhook``, ``parse_webhook``). The two responsibilities are
cleanly separated at the protocol level so send-only providers
(in_app, mock, capture) don't need to stub webhook methods — see
``app/comms/webhooks.py`` for the WebhookProvider protocol.

Configuration
-------------

* ``RESEND_API_KEY``       — required to send. When absent the provider
                             reports ``offline`` and returns a rejected
                             result without contacting Resend.
* ``EMAIL_FROM``           — required RFC 5322 address on a verified
                             Resend domain.
* ``EMAIL_REPLY_TO``       — optional default; per-payload override wins.
* ``RESEND_WEBHOOK_SECRET`` — required to verify inbound webhooks.
                             When unset the receiver refuses every
                             payload with a 401.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Mapping

from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
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


# Resend event type → normalised Fresh Collective event type.
_RESEND_EVENT_TYPE_MAP = {
    "email.sent":              "sent",
    "email.delivered":         "delivered",
    "email.delivery_delayed":  "other",
    "email.bounced":           "bounced",
    "email.complained":        "complained",
    "email.opened":            "opened",
    "email.clicked":           "clicked",
    "email.unsubscribed":      "unsubscribed",
    "contact.unsubscribed":    "unsubscribed",
}


class ResendProvider:
    """Sends transactional email via Resend and consumes Resend's
    Svix-format inbound webhooks."""

    key: str = "resend"
    capabilities: frozenset[str] = frozenset({CHANNEL_EMAIL_TRANSACTIONAL})
    production_eligible: bool = True

    # ── DeliveryProvider (outbound) ─────────────────────────────────

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
                "(subject: %s). Set EMAIL_FROM to an RFC 5322 address "
                "on a verified Resend domain.",
                payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class="config_missing",
                error_detail="EMAIL_FROM is not configured.",
            )

        if not payload.body_html and not payload.body_text:
            logger.error(
                "ResendProvider.send called with no body_html or "
                "body_text (to=%s, subject=%s)",
                payload.to, payload.subject,
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

        # Extract an idempotency key from payload.metadata. The
        # dispatch worker sets this to the intent id so a re-invocation
        # of the *same intent* (e.g. after a partial crash) cannot
        # cause Resend to accept a second copy of the same message.
        #
        # This header protects retries of the same intent only. Every
        # separate intent gets a new key by design, so two independent
        # emits legitimately produce two emails — that is not a bug.
        # Durable business-event deduplication lives at the database
        # layer via the CommunicationEvent (dedupe_key) and
        # CommunicationIntent (event × recipient × channel) natural
        # keys; Resend's own key retention is only 24 hours and is not
        # the authoritative dedupe surface.
        options: dict = {}
        idem_key = payload.metadata.get("idempotency_key") if payload.metadata else None
        if isinstance(idem_key, str) and idem_key:
            options["idempotency_key"] = idem_key

        try:
            import resend  # type: ignore[import-untyped]
            resend.api_key = settings.resend_api_key
            if options:
                result = resend.Emails.send(request, options)  # type: ignore[arg-type]
            else:
                result = resend.Emails.send(request)
        except Exception as exc:  # noqa: BLE001
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
        return ProviderHealth(
            status=HealthStatus.HEALTHY,
            checked_at=now_utc(),
        )

    # ── WebhookProvider (inbound) ───────────────────────────────────

    def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes,
    ) -> bool:
        secret = settings.resend_webhook_secret
        if not secret:
            logger.warning(
                "ResendProvider.verify_webhook: RESEND_WEBHOOK_SECRET "
                "is not set — rejecting inbound webhook."
            )
            return False
        from app.comms.webhooks import verify_svix_signature  # local — circular guard
        return verify_svix_signature(headers, raw_body, secret=secret)

    def check_webhook(
        self, headers: Mapping[str, str], raw_body: bytes,
    ) -> str:
        """R4 — return one of ``SIG_OK`` / ``SIG_MISSING_HEADERS`` /
        ``SIG_INVALID`` so the receiver route can pick the right HTTP
        4xx status (400 vs 401) when the payload is refused.

        Header presence is checked first (even when the secret is
        absent) so a caller missing ``svix-*`` headers always gets
        the "fix your request" 400 response instead of the misleading
        401 they'd see if the operator hadn't provisioned the secret
        yet. When the secret is unset but headers ARE present we
        return ``SIG_INVALID`` — the caller signed correctly, we just
        can't verify.
        """
        from app.comms.webhooks import (  # local — circular guard
            SIG_INVALID, SIG_MISSING_HEADERS, _header,
            check_svix_signature,
        )
        # Header presence check mirrors check_svix_signature's own
        # guard so behaviour is identical regardless of secret state.
        for hname in ("svix-id", "svix-timestamp", "svix-signature"):
            if not _header(headers, hname):
                return SIG_MISSING_HEADERS
        secret = settings.resend_webhook_secret
        if not secret:
            logger.warning(
                "ResendProvider.check_webhook: RESEND_WEBHOOK_SECRET "
                "is not set — rejecting inbound webhook."
            )
            return SIG_INVALID
        return check_svix_signature(headers, raw_body, secret=secret)

    def parse_webhook(
        self, headers: Mapping[str, str], raw_body: bytes,
    ):
        """Return a list of parsed :class:`WebhookEvent`. Unknown /
        malformed payloads produce an empty list so the receiver
        records an audit row without crashing.
        """
        from app.comms.webhooks import WebhookEvent, _header

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.exception("ResendProvider.parse_webhook: could not decode body")
            return []
        if not isinstance(payload, dict):
            return []
        raw_type = payload.get("type")
        if not isinstance(raw_type, str):
            return []

        normalised = _RESEND_EVENT_TYPE_MAP.get(raw_type, "other")
        return [
            WebhookEvent(
                provider_event_id=_header(headers, "svix-id"),
                event_type=normalised,
                provider_message_id=_extract_message_id(payload),
                recipient_address=(
                    _extract_recipient(payload)
                    if normalised in (
                        "bounced", "complained", "unsubscribed", "delivered",
                    )
                    else None
                ),
                bounce_class=(
                    _extract_bounce_class(payload) if normalised == "bounced" else None
                ),
                occurred_at=_parse_occurred_at(payload),
                raw=payload,
            ),
        ]


# ---------------------------------------------------------------------------
# Payload extraction helpers
# ---------------------------------------------------------------------------


def _extract_message_id(payload: dict) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    for key in ("email_id", "id", "message_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_recipient(payload: dict) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    to_field: Any = data.get("to")
    if isinstance(to_field, list) and to_field and isinstance(to_field[0], str):
        return to_field[0]
    if isinstance(to_field, str):
        return to_field
    email = data.get("email")
    if isinstance(email, str):
        return email
    return None


def _extract_bounce_class(payload: dict) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    bounce = data.get("bounce")
    if isinstance(bounce, dict):
        bt = bounce.get("type") or bounce.get("bounce_type")
        if isinstance(bt, str):
            lowered = bt.lower()
            if lowered in ("hard", "permanent"):
                return "hard"
            if lowered in ("soft", "transient"):
                return "soft"
    return None


def _parse_occurred_at(payload: dict) -> datetime | None:
    raw = payload.get("created_at") if isinstance(payload, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# Runtime protocol check — catches shape drift at import.
assert isinstance(ResendProvider(), DeliveryProvider)
