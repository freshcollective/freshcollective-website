"""In-app notifications provider.

Writes into the existing ``notifications`` table via
``notification_service.create_notification``. The provider is the
long-term home for the in-app channel; ``create_notification`` remains
a public helper during the transition (Milestones 5–15) and will be
retired once every caller flows through the comms layer.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.comms.categories import CHANNEL_IN_APP
from app.comms.providers.base import (
    DeliveryProvider,
    HealthStatus,
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    now_utc,
)
from app.core.database import SessionLocal


logger = logging.getLogger(__name__)


class InAppProvider:
    """Persists a row in the ``notifications`` table.

    The recipient's user id is passed as ``payload.to``; ``subject``
    becomes the notification title; ``body_text`` (falling back to
    ``body_html``, then empty string) becomes the message body.
    ``metadata`` carries the ``notification_type`` and optional ``url``.

    Metadata keys read:

    * ``notification_type`` — required; the existing string key
      (e.g. ``"comment_reply"``, ``"gathering_reminder"``). Absence is
      a caller bug — we refuse rather than pick an arbitrary default.
    * ``url`` — optional; the click-through destination.
    """

    key: str = "in_app"
    capabilities: frozenset[str] = frozenset({CHANNEL_IN_APP})
    production_eligible: bool = True

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        # Injected so tests can substitute a bound-session factory.
        self._session_factory = session_factory

    def send(self, payload: RenderedPayload) -> ProviderResult:
        notif_type = payload.metadata.get("notification_type")
        if not notif_type or not isinstance(notif_type, str):
            logger.error(
                "InAppProvider.send called without a string "
                "metadata.notification_type (to=%s, subject=%s)",
                payload.to, payload.subject,
            )
            return ProviderResult(
                accepted=False,
                error_class="metadata_missing",
                error_detail="metadata.notification_type is required.",
            )
        url_val = payload.metadata.get("url")
        url: str | None = url_val if isinstance(url_val, str) else None
        message = payload.body_text or payload.body_html or ""

        # Local import to avoid pulling notification_service (and its
        # heavy graph of imports) into every process that touches the
        # comms package.
        from app.services.notification_service import create_notification

        db = self._session_factory()
        try:
            try:
                notif = create_notification(
                    db=db,
                    recipient_id=payload.to,
                    notification_type=notif_type,
                    title=payload.subject,
                    message=message,
                    url=url,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "InAppProvider failed to persist notification for %s",
                    payload.to,
                )
                return ProviderResult(
                    accepted=False,
                    error_class=type(exc).__name__,
                    error_detail=str(exc),
                )
            return ProviderResult(
                accepted=True,
                provider_message_id=notif.id,
            )
        finally:
            db.close()

    def health(self) -> ProviderHealth:
        # The DB is the health signal — a failure to obtain a session
        # is fatal for the app anyway, and re-checking on every call
        # adds no value. Milestone 3 reports HEALTHY unconditionally;
        # a future milestone may add a lightweight SELECT 1 probe with
        # a cached result.
        return ProviderHealth(
            status=HealthStatus.HEALTHY,
            checked_at=now_utc(),
        )


assert isinstance(InAppProvider(), DeliveryProvider)
