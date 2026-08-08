"""File-capture provider — writes each send to disk for QA inspection.

Replaces the ad-hoc workflow around
``backend/scripts/render_email_samples.py``. When routed to this
provider, an email or other rendered payload is written to
``backend/.qa-emails/`` as an HTML file so a designer or reviewer can
open it directly in a browser.

The target directory is created on demand and defaults are chosen so
the file is easy to find and identify:

    <timestamp>-<sanitised-subject-slug>.html
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from app.comms.categories import (
    CHANNEL_EMAIL_MARKETING,
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


logger = logging.getLogger(__name__)


_DEFAULT_TARGET = (
    Path(__file__).resolve().parent.parent.parent.parent / ".qa-emails"
)


def _slugify(value: str) -> str:
    """Filesystem-safe short slug from a subject line."""
    lowered = value.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug[:60] if slug else "untitled"


class CaptureProvider:
    """Persists each send to disk. Dev / QA only, never a production target.

    Sends never leave the machine. ``production_eligible = False`` is
    set so the routing layer (Milestone 4+) filters this provider out
    of production selection regardless of registration or channel
    coverage. Intended for local template review and QA snapshots.
    """

    key: str = "capture"
    capabilities: frozenset[str] = frozenset({
        CHANNEL_EMAIL_TRANSACTIONAL,
        CHANNEL_EMAIL_MARKETING,
    })
    # Dev / test / QA only. Never selected by the production routing layer.
    production_eligible: bool = False

    def __init__(self, target_dir: Path | None = None) -> None:
        self._target: Path = target_dir if target_dir is not None else _DEFAULT_TARGET

    def send(self, payload: RenderedPayload) -> ProviderResult:
        try:
            self._target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "CaptureProvider could not create target directory %s",
                self._target,
            )
            return ProviderResult(
                accepted=False,
                error_class=type(exc).__name__,
                error_detail=f"mkdir({self._target}): {exc}",
            )

        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        filename = f"{ts}-{_slugify(payload.subject)}.html"
        target_path = self._target / filename
        contents = payload.body_html or payload.body_text or ""
        try:
            target_path.write_text(contents, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "CaptureProvider failed to write %s", target_path,
            )
            return ProviderResult(
                accepted=False,
                error_class=type(exc).__name__,
                error_detail=str(exc),
            )
        return ProviderResult(
            accepted=True,
            provider_message_id=filename,
        )

    def health(self) -> ProviderHealth:
        # DEGRADED when the target directory exists but isn't writable;
        # HEALTHY otherwise. The mkdir on send() will surface a real
        # failure at that point.
        try:
            self._target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                status=HealthStatus.OFFLINE,
                checked_at=now_utc(),
                detail=f"cannot create target dir: {exc}",
            )
        return ProviderHealth(
            status=HealthStatus.HEALTHY,
            checked_at=now_utc(),
        )


assert isinstance(CaptureProvider(), DeliveryProvider)
