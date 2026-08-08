"""In-memory mock provider — dev / test only, never a production target.

Records every ``send()`` call in-order on the instance so tests can
assert on what was dispatched without going near a database or an
outbound HTTP call.

The default instance registered by ``providers._bootstrap`` serves
every channel so a test can point the routing layer at ``"mock"`` for
any channel without extra wiring. Tests may also instantiate a fresh
:class:`MockProvider` and inject it directly.

``production_eligible = False`` is set explicitly so the routing
layer (Milestone 4+) never selects this provider in a production
runtime, even if it is the only registered provider for a channel.
Delivery should be held or dropped rather than silently routed to a
provider that discards every message.
"""

from __future__ import annotations

from app.comms.categories import (
    CHANNEL_EMAIL_MARKETING,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
    CHANNEL_PUSH,
    CHANNEL_WEBHOOK_OUTBOUND,
)
from app.comms.providers.base import (
    DeliveryProvider,
    HealthStatus,
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    now_utc,
)


class MockProvider:
    """Records sends to an in-memory list. Serves every channel."""

    key: str = "mock"
    capabilities: frozenset[str] = frozenset({
        CHANNEL_IN_APP,
        CHANNEL_EMAIL_TRANSACTIONAL,
        CHANNEL_EMAIL_MARKETING,
        CHANNEL_PUSH,
        CHANNEL_WEBHOOK_OUTBOUND,
    })
    # Dev / test only. Never selected by the production routing layer.
    production_eligible: bool = False

    def __init__(self) -> None:
        self.sent: list[RenderedPayload] = []

    def send(self, payload: RenderedPayload) -> ProviderResult:
        self.sent.append(payload)
        return ProviderResult(
            accepted=True,
            provider_message_id=f"mock-{len(self.sent)}",
        )

    def reset(self) -> None:
        """Clear the recorded sends. Cheap for use between tests."""
        self.sent.clear()

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            status=HealthStatus.HEALTHY,
            checked_at=now_utc(),
            detail="mock provider — never fails",
        )


assert isinstance(MockProvider(), DeliveryProvider)
