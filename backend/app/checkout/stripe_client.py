"""Shared Stripe client init.

The existing paid-Pathway checkout route sets ``stripe.api_key`` ad-hoc
before every Session creation (``app/checkout/routes.py:133``). Stage 2
adds a second and third call site (Creator subscriptions, and later
Collective memberships), so we centralise the API-key wiring in one
place. This module owns exactly two responsibilities:

  * telling the Stripe SDK which API key to use for this request
  * telling callers whether Stripe is configured at all

Business logic — Session creation, PurchaseIntent validation, webhook
processing — deliberately lives elsewhere. This module is a thin
adapter over the SDK, nothing more.

Design notes
------------

  * ``stripe.api_key`` is a *module-level global* on the SDK, so
    calling it once per request is idempotent and cheap. We do not
    memoise it further.
  * ``ensure_configured()`` raises the domain error
    ``StripeNotConfiguredError`` (not ``HTTPException``) so that
    service-layer callers stay framework-agnostic. Route handlers
    translate this into a 503.
"""

from __future__ import annotations

import stripe

from app.core.config import settings


class StripeNotConfiguredError(RuntimeError):
    """Raised when a Stripe operation is attempted without a configured
    ``STRIPE_SECRET_KEY`` / ``STRIPE_WEBHOOK_SECRET`` pair. Routes turn
    this into a 503 with an honest, machine-parseable body so the
    frontend can render an isolated "not configured" state (never a
    fake success)."""


def is_configured() -> bool:
    """Cheap boolean check — mirrors ``settings.stripe_enabled`` and
    is exposed here so callers can avoid importing ``settings`` when
    all they need is the readiness signal."""
    return settings.stripe_enabled


def ensure_configured() -> None:
    """Raise ``StripeNotConfiguredError`` if Stripe is not fully wired
    for this environment. Call at the top of any function that will
    hit the Stripe SDK."""
    if not is_configured():
        raise StripeNotConfiguredError(
            "Stripe secret key or webhook secret is not set in this "
            "environment. Payment operations are disabled."
        )


def get_stripe():
    """Return the Stripe SDK module with ``api_key`` bound to the
    current environment's secret key. Callers use this instead of
    importing ``stripe`` directly so the key can never be forgotten.

    Raises :class:`StripeNotConfiguredError` when the secret is unset.
    """
    ensure_configured()
    stripe.api_key = settings.stripe_secret_key
    return stripe
