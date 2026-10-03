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
  * There are **two** readiness questions and they are not the same
    one. "Can I call the Stripe API?" needs a secret key.
    "Is the payment loop wired end to end?" also needs the webhook
    secret. Background jobs answer yes to the first and no to the
    second, legitimately and by design, so the client factories ask
    the API question and every checkout entry point asks the fuller
    one. Webhook signature verification is gated separately again, at
    the intake, by the secret it actually uses.
"""

from __future__ import annotations

import stripe

from app.core.config import settings


class StripeNotConfiguredError(RuntimeError):
    """Raised when a Stripe operation is attempted without the
    configuration it needs. Routes turn this into a 503 with an honest,
    machine-parseable body so the frontend can render an isolated "not
    configured" state (never a fake success).

    Two different shortfalls raise it, and the message says which:
    :func:`ensure_api_configured` wants a secret key, and
    :func:`ensure_configured` wants the whole payment loop."""


def api_is_configured() -> bool:
    """Whether this process can call the Stripe API. Secret key only."""
    return settings.stripe_api_enabled


def ensure_api_configured() -> None:
    """Raise ``StripeNotConfiguredError`` if there is no secret key.

    The right check for making an API call, and the reason this is
    separate from :func:`ensure_configured`. Both of the Connect
    sweepers run as crons with ``STRIPE_SECRET_KEY`` and deliberately
    without ``STRIPE_WEBHOOK_SECRET`` — a job receives no webhooks, so
    granting it the signing secret would be paying for a capability it
    does not have. Asking for the pair here refused to start them: the
    transfer sweeper failed in this module and never reached Stripe, so
    creator shares sat unsent while the cron reported a clean failure
    every fifteen minutes.

    The boot-time rules in ``config`` already drew this line — a job
    requires the secret key and not the webhook secret. This is the
    runtime half agreeing with them.
    """
    if not api_is_configured():
        raise StripeNotConfiguredError(
            "STRIPE_SECRET_KEY is not set in this environment. Stripe "
            "API operations are disabled."
        )


def is_configured() -> bool:
    """Whether the whole payment loop is wired — API out, webhook in.

    Mirrors ``settings.stripe_enabled``, and is exposed here so callers
    can avoid importing ``settings`` when all they need is the readiness
    signal."""
    return settings.stripe_enabled


def ensure_configured() -> None:
    """Raise ``StripeNotConfiguredError`` unless Stripe is *fully* wired.

    Stricter than :func:`ensure_api_configured` on purpose, and the
    right check before taking money: a Checkout Session created in an
    environment that cannot verify the completion webhook charges a
    member with no path to fulfilment. Callers that only read from or
    write to the API want the API check instead.
    """
    if not is_configured():
        raise StripeNotConfiguredError(
            "Stripe secret key or webhook secret is not set in this "
            "environment. Payment operations are disabled."
        )


def get_stripe():
    """Return the Stripe SDK module with ``api_key`` bound to the
    current environment's secret key. Callers use this instead of
    importing ``stripe`` directly so the key can never be forgotten.

    Raises :class:`StripeNotConfiguredError` when the secret key is
    unset. Binding a key needs the key and nothing else — webhook
    verification is a separate concern with a separate secret, checked
    where signatures are actually verified.
    """
    ensure_api_configured()
    stripe.api_key = settings.stripe_secret_key
    return stripe


def to_plain_dict(value: Any) -> dict[str, Any]:
    """A Stripe object as a plain, fully-recursive dict.

    Lives here because the alternative keeps being written by hand and
    keeps being written wrong. ``dict(stripe_object)`` looks obvious and
    is not: a ``StripeObject`` in stripe 15.x is not a mapping — no
    ``keys()``, no ``__iter__``, only ``__getitem__`` — so ``dict()``
    falls back to the legacy sequence protocol, asks for index ``0`` and
    raises ``KeyError: 0``. That is not a ``TypeError`` or a
    ``ValueError``, so the usual defensive ``except`` around it does not
    catch it either, and it surfaces as a 500 or a dead background job.

    ``to_dict_recursive()`` is the other trap. It reads like the right
    method and does not exist on this SDK version — only the private
    ``_to_dict_recursive`` does — so a ``hasattr`` guard on it is always
    False and every caller written that way silently takes the broken
    branch. The public method is ``to_dict()``, and it recurses by
    default.

    Recursion is required, not merely nice: callers hand the result to
    code that reads nested fields, and a shallow copy leaves
    StripeObjects one level down to fail later and further away.

    Plain dicts pass through untouched, and ``None`` becomes ``{}``.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, dict):
            return converted
    try:
        return dict(value)
    except (TypeError, ValueError, KeyError) as exc:  # pragma: no cover
        # Deliberately not ``StripeNotConfiguredError``: nothing about
        # configuration is wrong here, and callers translate that one
        # into a 503 "payments are off" the operator would then go
        # looking for in the wrong place.
        raise TypeError(
            f"cannot convert {type(value).__name__} to a dict"
        ) from exc


def stripe_field(value: Any, *path: str, default: Any = None) -> Any:
    """Read ``value[path[0]][path[1]]…``, returning ``default`` on any miss.

    Works on plain dicts and on ``StripeObject``, which supports ``in``
    and ``[]`` at every nesting level but does NOT expose ``.get()``.
    Never calls ``.get()``, so a StripeObject walked by this helper
    cannot re-hit the ``AttributeError: get`` boundary bug.

    Falls back to attribute access for a value supporting neither, so a
    hand-rolled test double reads the same way a real payload does.
    Every miss is quiet — callers decide whether ``None`` is a problem.
    """
    cur: Any = value
    for key in path:
        if cur is None:
            return default
        try:
            if key in cur:
                cur = cur[key]
            else:
                return default
        except TypeError:
            # Not a container at all. Attribute access or nothing.
            found = getattr(cur, key, default)
            if found is default:
                return default
            cur = found
        except KeyError:
            return default
    return cur


def invoice_subscription_id(invoice: Any) -> str | None:
    """The Subscription id linked to a Stripe Invoice payload.

    One definition for every surface that needs it. There were three:
    the finite-plan webhook handler, the finite-plan repair service, and
    — reading only the legacy field — creator billing. The third is how
    this ends up mattering: creator billing runs *first* on every
    invoice event, including a member's, so a shape it cannot read is
    not merely its own blind spot.

    Current Stripe API nests the link under ``parent``, discriminated by
    ``parent.type == 'subscription_details'``. Older versions exposed a
    top-level ``invoice.subscription``, and that remains the fallback —
    a redelivery of an event created under the previous shape must keep
    resolving.

    ``None`` for a non-subscription invoice (one-off, quote, unknown
    parent), which callers treat as "not one of ours, skip cleanly".
    Accepts a ``StripeObject`` or a plain dict.
    """
    parent_type = stripe_field(invoice, "parent", "type")
    if parent_type == "subscription_details":
        current = stripe_field(
            invoice, "parent", "subscription_details", "subscription",
        )
        if current:
            return current
    legacy = stripe_field(invoice, "subscription")
    if legacy:
        return legacy
    return None


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

    Raises :class:`StripeNotConfiguredError` when the secret key is
    unset. As with :func:`get_stripe`, constructing a client needs the
    key alone. The v2 webhook intake calls this *after* its own
    ``stripe_v2_webhooks_enabled`` gate, so that path still refuses
    without ``STRIPE_V2_WEBHOOK_SECRET``.
    """
    ensure_api_configured()
    return stripe.StripeClient(settings.stripe_secret_key)
