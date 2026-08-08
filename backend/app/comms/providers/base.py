"""Protocol + shared types for communications delivery providers.

The three cornerstone shapes:

* :class:`RenderedPayload` — the payload a provider is asked to deliver.
  Rendering (subject / body from templates) happens *before* the
  provider is called; providers do not know about templates.
* :class:`ProviderResult` — the outcome of a single ``send()`` attempt.
  Providers must return this rather than raise on delivery failure so
  the upstream worker can record it and decide whether to retry.
* :class:`ProviderHealth` — a snapshot of the provider's operational
  state. Deliberately a structured type from day one so future signals
  (latency, error rate, quota) can be added without breaking callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Payload + result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderedPayload:
    """A message ready to be handed to a provider.

    Providers pick the fields they need:

    * Email providers read ``to`` (email address), ``subject``,
      ``body_html`` (preferred) or ``body_text``, and optional
      ``reply_to``.
    * In-app providers read ``to`` (user id), ``subject`` (used as
      the notification title), ``body_text``, and pull
      ``notification_type`` + ``url`` from ``metadata``.
    * Push / webhook providers read ``to`` (device token / URL),
      ``subject``, ``body_text``, and provider-specific keys from
      ``metadata``.

    The payload is immutable so it can be safely retained in delivery
    records / logs. Rendering is a pure function of the event + the
    recipient + the template, so a payload can always be reproduced.
    """

    to: str
    subject: str
    body_html: str | None = None
    body_text: str | None = None
    reply_to: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    """The outcome of a single ``send()`` attempt.

    Providers *return* this rather than raising on failure. Delivery
    errors are ordinary business signals that the worker records against
    the intent and may retry — they must not crash the dispatch loop.

    :attr:`accepted` = True means the provider handed the message off
    successfully. It does not mean the message was *delivered* — that
    signal arrives asynchronously via a webhook and updates the intent.
    """

    accepted: bool
    provider_message_id: str | None = None
    error_class: str | None = None
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthStatus(StrEnum):
    """Coarse operational state. Every provider reports one of these.

    * ``healthy``  — ready to accept sends.
    * ``degraded`` — accepting sends but with reduced reliability
                     (elevated error rate, near quota, slow responses).
                     Callers may prefer another provider for the same
                     channel when available.
    * ``offline``  — not accepting sends. Missing configuration, hard
                     circuit-break, or provider outage. The delivery
                     worker should hold rather than drop.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass(frozen=True)
class ProviderHealth:
    """A snapshot of a provider's operational state.

    The shape is intentionally rich from day one so the API can grow
    without breaking callers:

    * ``status`` — the coarse verdict (:class:`HealthStatus`).
    * ``checked_at`` — when this snapshot was produced.
    * ``detail`` — a short human-readable explanation (e.g. "no api
                    key configured", "3 of last 10 sends failed").
    * ``metrics`` — a dict for structured numeric signals (latency
                    samples, error rate, quota remaining). Empty in
                    the initial implementation; providers can populate
                    it as they gain instrumentation without a schema
                    change.
    """

    status: HealthStatus
    checked_at: datetime
    detail: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)


def now_utc() -> datetime:
    """Provider health-check timestamp helper. UTC, timezone-aware."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# The Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DeliveryProvider(Protocol):
    """A pluggable delivery target.

    Implementations declare:

    * :attr:`key` — the unique registry key (``"resend"``,
      ``"in_app"``, ``"mailerlite"``, ...).
    * :attr:`capabilities` — the set of channels this provider serves.
      A single provider may serve several channels
      (e.g. a hypothetical Resend account that also handled marketing).
    * :attr:`production_eligible` — ``True`` for providers that may be
      selected as delivery targets in the production runtime;
      ``False`` for dev / test / QA providers (Mock, Capture) that
      must never receive real member traffic. The routing layer
      (Milestone 4+) filters on this flag before any selection
      strategy runs. Registered-but-not-eligible providers remain
      visible for admin diagnostics and test injection.

    And implement:

    * :meth:`send` — attempt one delivery. Returns a
      :class:`ProviderResult`; never raises on delivery failure.
    * :meth:`health` — report current operational state.

    Inbound webhook processing (bounce / complaint / opens / marketing
    events) is intentionally out of scope for this protocol in
    Milestone 3. It arrives in Milestone 6 as a separate protocol so
    providers that never receive webhooks aren't forced to stub an
    empty method.
    """

    key: str
    capabilities: frozenset[str]
    production_eligible: bool

    def send(self, payload: RenderedPayload) -> ProviderResult: ...

    def health(self) -> ProviderHealth: ...
