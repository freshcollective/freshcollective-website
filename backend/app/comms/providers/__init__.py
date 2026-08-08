"""Communications delivery providers.

A provider is a pluggable delivery adapter that implements the
:class:`~app.comms.providers.base.DeliveryProvider` protocol. Providers
own the details of talking to a specific external system (Resend for
transactional email, MailerLite for marketing email, FCM/APNs for push,
etc.) or the internal in-app notifications table.

The comms layer treats providers as interchangeable. Domain code never
imports a specific provider directly — it looks one up by key or
capability via the registry helpers below.

Usage::

    from app.comms.providers import get, providers_for_channel
    from app.comms.categories import Channel

    resend = get("resend")
    email_providers = providers_for_channel(Channel.EMAIL_TRANSACTIONAL)

Registration happens once at import time via :func:`_bootstrap`. Tests
can call :func:`reset_registry` to start from an empty state and
:func:`register` to install fakes.
"""

from __future__ import annotations

from typing import Iterable

from app.comms.categories import ALL_CHANNELS
from app.comms.providers.base import (
    DeliveryProvider,
    HealthStatus,
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
)


__all__ = [
    "DeliveryProvider",
    "HealthStatus",
    "ProviderHealth",
    "ProviderResult",
    "RenderedPayload",
    "register",
    "get",
    "all_providers",
    "providers_for_channel",
    "production_providers_for_channel",
    "reset_registry",
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, DeliveryProvider] = {}


def register(provider: DeliveryProvider) -> None:
    """Register a provider under its ``key``.

    Raises :class:`ValueError` if the key is already taken — deliberate
    strictness, since silently overwriting a provider would mask real
    configuration bugs. Tests that need to swap a provider should call
    :func:`reset_registry` first.
    """
    if provider.key in _REGISTRY:
        raise ValueError(
            f"Provider {provider.key!r} is already registered. "
            f"Call reset_registry() first if you're swapping providers."
        )
    _REGISTRY[provider.key] = provider


def get(key: str) -> DeliveryProvider:
    """Look up a provider by key. Raises :class:`KeyError` on miss."""
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise KeyError(
            f"Provider {key!r} is not registered. Registered providers: "
            f"{sorted(_REGISTRY.keys())}"
        ) from exc


def all_providers() -> tuple[DeliveryProvider, ...]:
    """Every registered provider, in insertion order."""
    return tuple(_REGISTRY.values())


def providers_for_channel(channel: str) -> tuple[DeliveryProvider, ...]:
    """Every registered provider that declares support for a channel.

    Order is insertion order — the first-registered provider for a
    channel is the default at selection time (M5 will introduce
    explicit per-topic provider preferences).

    Includes non-production providers (Mock, Capture) — useful for
    admin diagnostics. Production routing should call
    :func:`production_providers_for_channel` instead.
    """
    if channel not in ALL_CHANNELS:
        raise ValueError(
            f"Unknown channel: {channel!r}. Expected one of {ALL_CHANNELS}."
        )
    return tuple(p for p in _REGISTRY.values() if channel in p.capabilities)


def production_providers_for_channel(channel: str) -> tuple[DeliveryProvider, ...]:
    """Every production-eligible provider that serves a channel.

    Filters out providers that set ``production_eligible = False``
    (Mock, Capture). The routing layer in Milestone 4+ uses this
    entry point exclusively so dev-only providers can never
    intercept a real member's traffic.
    """
    return tuple(
        p for p in providers_for_channel(channel) if getattr(p, "production_eligible", True)
    )


def reset_registry() -> None:
    """Empty the registry. Intended for tests only."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _bootstrap() -> None:
    """Register the built-in providers. Called once at package import.

    Kept as a module-level function so tests can call it explicitly
    after :func:`reset_registry` when they want the real providers back.
    """
    # Imports are local so a broken third-party dependency (e.g. Resend
    # unavailable) doesn't kill the whole comms package on import — the
    # failing provider simply isn't registered.
    from app.comms.providers.resend import ResendProvider
    from app.comms.providers.inapp import InAppProvider
    from app.comms.providers.mock import MockProvider
    from app.comms.providers.capture import CaptureProvider

    register(ResendProvider())
    register(InAppProvider())
    register(MockProvider())
    register(CaptureProvider())


_bootstrap()
