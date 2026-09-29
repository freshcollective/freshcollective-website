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


# ---------------------------------------------------------------------------
# API version
# ---------------------------------------------------------------------------
#
# Fresh Collective never sets ``stripe.api_version``, which is easy to
# read as "we run on whatever the Stripe account's Dashboard default
# is". That is not what happens. ``stripe/__init__.py`` assigns
# ``api_version = _ApiVersion.CURRENT`` — the version the installed
# package was generated against — and ``_api_requestor`` sends it as a
# ``Stripe-Version`` header on every request. The account default never
# applies to a call made through this SDK.
#
# So the pinned package version in ``requirements.txt`` is what pins
# FC's API version, for checkout, webhooks, subscriptions and refunds
# alike. The constants below make that coupling explicit: the pin and
# the declared version are asserted against the installed library, so
# a dependency change cannot move the API version silently.
#
# Bumping the pin is an API-version migration. Update both constants in
# the same commit and read Stripe's changelog for the intervening
# versions; ``tests/test_stripe_api_version.py`` fails until they agree.

EXPECTED_STRIPE_PACKAGE_VERSION = "15.2.0"
EXPECTED_STRIPE_API_VERSION = "2026-05-27.dahlia"
# The date-suffixed name ("dahlia") is Stripe's major version. A change
# here alters request and response shapes across the whole API; a change
# to only the date part is additive by comparison. The two are treated
# differently below because the consequences differ by that much.
EXPECTED_STRIPE_API_MAJOR = "dahlia"


class StripeVersionMismatch(RuntimeError):
    """The installed Stripe SDK sends a different major API version than
    this code was written and tested against.

    Raised only for a *major* change, and deliberately at import/boot
    time rather than at the first payment. See
    :func:`assert_api_version` for why that is the safer failure."""


def installed_api_version() -> str:
    """The API version this process will actually send to Stripe.

    Read from the SDK rather than from our own constant, so callers and
    logs report what is true instead of what we intended."""
    return stripe.api_version


def installed_package_version() -> str:
    return stripe.VERSION


def api_version_major(version: str) -> str:
    """``"2026-05-27.dahlia"`` → ``"dahlia"``.

    Returns the whole string when there is no suffix, so an unfamiliar
    format is reported verbatim rather than silently parsed into
    something that happens to compare equal."""
    _, _, major = version.partition(".")
    return major or version


def api_version_discrepancies() -> list[str]:
    """Human-readable differences between what is installed and what
    this code declares. Empty when they agree.

    Returns rather than raises so both the boot-time check and the test
    suite can describe every difference at once instead of stopping at
    the first."""
    found: list[str] = []
    if installed_package_version() != EXPECTED_STRIPE_PACKAGE_VERSION:
        found.append(
            f"stripe-python is {installed_package_version()}, expected "
            f"{EXPECTED_STRIPE_PACKAGE_VERSION}"
        )
    if installed_api_version() != EXPECTED_STRIPE_API_VERSION:
        found.append(
            f"Stripe-Version is {installed_api_version()}, expected "
            f"{EXPECTED_STRIPE_API_VERSION}"
        )
    return found


def assert_api_version() -> list[str]:
    """Check the installed SDK against the declared version. Local only —
    reads two module attributes and makes no network call, so it cannot
    add a boot-time dependency on Stripe being reachable.

    Returns the discrepancy list so the caller can log it.

    Raises :class:`StripeVersionMismatch` for a **major** version change
    only. Refusing to boot under an unreviewed major version is the safer
    failure for a service that moves money: on Render a container that
    fails to start leaves the previous healthy deploy serving, so this
    blocks a bad deploy rather than causing an outage. Processing
    payments under changed request and response shapes has no equivalent
    safety net.

    A package-version or same-major date change is reported loudly and
    allowed to proceed. It still needs attention, but not at the cost of
    refusing to serve.
    """
    installed_major = api_version_major(installed_api_version())
    if installed_major != EXPECTED_STRIPE_API_MAJOR:
        raise StripeVersionMismatch(
            f"Stripe major API version is {installed_major!r}, but this "
            f"code is written for {EXPECTED_STRIPE_API_MAJOR!r} "
            f"(installed Stripe-Version {installed_api_version()}, "
            f"stripe-python {installed_package_version()}). Request and "
            "response shapes differ across a major version. Review "
            "Stripe's changelog, update EXPECTED_STRIPE_* in "
            "app/checkout/stripe_client.py, and re-run the payment tests "
            "before deploying."
        )
    return api_version_discrepancies()


def get_stripe_client() -> "stripe.StripeClient":
    """Return a ``StripeClient`` bound to this environment's secret key.

    Exists because the v2 API has no module-global call pattern at all.
    ``stripe.v2.core`` is importable, but its resource classes
    (``Account``, ``AccountLink``, ``EventDestination``) carry no
    ``create`` / ``retrieve`` / ``list`` classmethods — the only
    ``update`` on them is the inherited dict method, not an API call.
    Every v2 operation exists solely as a service on an instantiated
    client (``client.v2.core.accounts.create(...)``), so the
    ``stripe.X.create(...)`` idiom every FC v1 call site uses has no v2
    equivalent to reach for.

    Every v1 call site keeps using :func:`get_stripe` — this is an
    addition, not a migration, and the two can be used side by side in
    the same request.

    A client is cheap to construct and holds no connection state worth
    sharing, so this returns a new one per call rather than memoising a
    global whose key could go stale.

    Raises :class:`StripeNotConfiguredError` when the secret is unset.
    """
    ensure_configured()
    return stripe.StripeClient(settings.stripe_secret_key)
