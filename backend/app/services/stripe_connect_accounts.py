"""The Stripe calls a creator's Connect account needs, and nothing else.

Same discipline as ``discount_stripe_sessions``: every function here is a
network call whose *failure mode* is part of the correctness argument, so
the exception types make the distinction explicit rather than leaving it
to error-message matching. Nothing here writes to the database, and
nothing here decides policy — it reports what Stripe said.

Which API for which question
----------------------------
v2 owns the account: its configuration, its capability statuses and its
requirement entries. v1 is used for exactly two things that have no v2
representation at all — the external-account list and
``settings.payouts`` — verified by retrieving the same account both ways
and finding no ``schedule``, ``delay_days``, ``external_account`` or
``bank`` anywhere in the v2 object.

Mode safety
-----------
An ``acct_…`` created under a test key is invisible to a live key and
vice versa: Stripe answers ``resource_missing``, which maps to
:class:`ConnectAccountNotFound` here. That is a real guard rather than a
convention, but it is the *second* one — callers must still refuse to use
a row whose ``stripe_mode`` differs from the current environment, because
"not found" is a poor way to learn you were about to cross modes.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.checkout.stripe_client import get_stripe, get_stripe_client
from app.core.config import settings

logger = logging.getLogger(__name__)

#: What to ask v2 for. Without ``include`` the capability statuses and
#: requirement entries are simply absent from the response, and the
#: projection would read an empty configuration as "restricted".
ACCOUNT_INCLUDES = [
    "configuration.recipient",
    "requirements",
    "defaults",
    "identity",
]


class ConnectError(RuntimeError):
    """Base for every failure in this module."""


class ConnectRejected(ConnectError):
    """Stripe understood the request and refused it.

    Terminal: retrying the identical request gets the identical answer.
    Carries Stripe's ``code`` where one was given so callers can branch
    on it without parsing prose. Authentication and permission failures
    land here too — Stripe did refuse, and retrying will not help; what
    needs fixing is the environment, not the timing.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ConnectUnavailable(ConnectError):
    """Stripe could not be asked, or gave an answer we cannot act on.

    The caller must treat this as "unknown", never as a negative result.
    Retryable. Nothing already stored should be overwritten on the
    strength of it.
    """


class ConnectAccountUnusable(ConnectError):
    """The account exists in FC's records but cannot be worked with."""


class ConnectAccountNotFound(ConnectAccountUnusable):
    """Stripe does not recognise this account id.

    Most often a genuine deletion — but also exactly what a mode mismatch
    looks like, so this is never evidence that an account never existed.
    """


class ConnectAccountClosed(ConnectAccountUnusable):
    """The account is closed. It cannot onboard and cannot receive money."""


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


_MISSING_CODES = frozenset({"resource_missing", "account_invalid"})
_CLOSED_MARKERS = ("closed", "rejected")


def _translate(exc: stripe.StripeError, *, what: str) -> ConnectError:
    """Map a Stripe exception onto this module's vocabulary.

    Split on "did Stripe answer?" first, because that is the distinction
    callers act on. Everything transport-shaped is retryable; everything
    Stripe decided is not.
    """
    code = getattr(exc, "code", None)

    if isinstance(exc, (stripe.APIConnectionError, stripe.RateLimitError)):
        return ConnectUnavailable(f"{what}: Stripe could not be reached: {exc}")

    if isinstance(exc, stripe.InvalidRequestError):
        if code in _MISSING_CODES:
            return ConnectAccountNotFound(f"{what}: {exc}")
        message = str(exc).lower()
        if any(marker in message for marker in _CLOSED_MARKERS):
            return ConnectAccountClosed(f"{what}: {exc}")
        return ConnectRejected(f"{what}: {exc}", code=code)

    if isinstance(exc, (stripe.PermissionError, stripe.AuthenticationError)):
        return ConnectRejected(f"{what}: {exc}", code=code or "not_permitted")

    if isinstance(exc, stripe.IdempotencyError):
        return ConnectRejected(f"{what}: {exc}", code=code or "idempotency_error")

    if isinstance(exc, stripe.APIError):
        # A 5xx from Stripe. Retryable, and we know nothing about whether
        # the write landed.
        return ConnectUnavailable(f"{what}: Stripe API error: {exc}")

    return ConnectUnavailable(f"{what}: unclassified Stripe error: {exc}")


def _to_dict(value: Any) -> dict[str, Any]:
    """Plain dict, so the projection layer never touches a StripeObject."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        raise ConnectUnavailable("Stripe returned an object we cannot read")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def create_recipient_account(
    *,
    display_name: str,
    contact_email: str | None,
    country: str,
    business_url: str | None = None,
) -> dict[str, Any]:
    """Create the account configuration Fresh Collective actually uses.

    ``recipient`` because FC is the merchant of record and the creator
    never processes a charge — Stripe documents this configuration for
    "Separate Charges & Transfers, or Destination Charges without
    ``on_behalf_of`` set", which is precisely FC's money path.

    ``dashboard: "express"`` gives creators a Stripe-hosted view of their
    payouts without FC building one, and it *requires* both
    responsibilities to be ``application`` — Stripe rejects any other
    combination with
    ``account_controller_express_dash_without_application_losses_or_fees``.
    So the three are one decision, not three.

    ``requirements_collector`` is deliberately not passed. Stripe sets it
    to ``"stripe"`` for an express dashboard, which is why FC cannot write
    identity, ToS or bank details and must hand the creator to hosted
    onboarding instead.

    ``business_url`` is included only when the caller has a real one. It
    gates *both* capabilities, so supplying it removes a requirement from
    every creator's flow — but Stripe validates it (``example.com`` is
    refused as ``url_invalid``), so inventing one would turn a helpful
    prefill into a failed create.
    """
    client = get_stripe_client()

    defaults: dict[str, Any] = {
        "responsibilities": {
            "fees_collector": "application",
            "losses_collector": "application",
        },
    }
    if business_url:
        defaults["profile"] = {"business_url": business_url}

    params: dict[str, Any] = {
        "display_name": display_name,
        "identity": {"country": country.lower(), "entity_type": "individual"},
        "configuration": {
            "recipient": {
                "capabilities": {
                    "stripe_balance": {"stripe_transfers": {"requested": True}},
                },
            },
        },
        "defaults": defaults,
        "dashboard": "express",
        "include": ACCOUNT_INCLUDES,
    }
    if contact_email:
        params["contact_email"] = contact_email

    try:
        account = client.v2.core.accounts.create(params)
    except stripe.StripeError as exc:
        logger.error("connect: account create failed: %s", exc)
        raise _translate(exc, what="creating a recipient account") from exc

    return _to_dict(account)


def retrieve_account(account_id: str) -> dict[str, Any]:
    """The v2 account, with everything the projection needs included."""
    client = get_stripe_client()
    try:
        account = client.v2.core.accounts.retrieve(
            account_id, {"include": ACCOUNT_INCLUDES},
        )
    except stripe.StripeError as exc:
        raise _translate(exc, what=f"retrieving account {account_id}") from exc
    return _to_dict(account)


def retrieve_legacy_account(account_id: str) -> dict[str, Any]:
    """The v1 account, for the two things v2 does not express.

    ``details_submitted`` separates "has not finished onboarding" from
    "finished, and Stripe has since asked for more".
    ``settings.payouts`` and ``external_accounts`` are the whole
    bank-payout picture, and neither appears in the v2 object.
    """
    api = get_stripe()
    try:
        account = api.Account.retrieve(account_id)
    except stripe.StripeError as exc:
        raise _translate(exc, what=f"retrieving legacy account {account_id}") from exc
    return _to_dict(account)


def is_closed(account: dict[str, Any]) -> bool:
    return bool(account.get("closed"))


# ---------------------------------------------------------------------------
# Hosted onboarding
# ---------------------------------------------------------------------------


def _account_link(
    *,
    account_id: str,
    use_case_type: str,
    return_url: str,
    refresh_url: str,
) -> str:
    client = get_stripe_client()
    options: dict[str, Any] = {
        "configurations": ["recipient"],
        # Ask for the minimum that unblocks the creator now, and let
        # Stripe come back for the rest when it actually needs it. A
        # creator who abandons onboarding because it asked for their whole
        # history is the common failure here.
        "collection_options": {"fields": "currently_due"},
        "refresh_url": refresh_url,
        "return_url": return_url,
    }
    try:
        link = client.v2.core.account_links.create({
            "account": account_id,
            "use_case": {"type": use_case_type, use_case_type: options},
        })
    except stripe.StripeError as exc:
        raise _translate(
            exc, what=f"creating a {use_case_type} link for {account_id}",
        ) from exc

    url = _to_dict(link).get("url")
    if not url:
        # A link without a URL is not something to hand a creator.
        raise ConnectUnavailable(
            f"Stripe returned an account link with no URL for {account_id}"
        )
    return str(url)


def create_onboarding_link(
    *, account_id: str, return_url: str, refresh_url: str,
) -> str:
    """A fresh Stripe-hosted onboarding URL.

    Returns the URL alone, deliberately: account links expire **five
    minutes** after creation (measured, not assumed), so there is nothing
    here worth storing and a stored one would usually be dead. Callers
    mint a new link per click, which is also why ``refresh_url`` is
    load-bearing rather than defensive — a creator who opens the page and
    hesitates will land on it.
    """
    return _account_link(
        account_id=account_id,
        use_case_type="account_onboarding",
        return_url=return_url,
        refresh_url=refresh_url,
    )


def create_update_link(
    *, account_id: str, return_url: str, refresh_url: str,
) -> str:
    """A hosted link for re-collection once Stripe raises new requirements.

    Distinct from onboarding: this is the path for an account that already
    submitted and has since been asked for more, so FC needs both rather
    than reusing one.
    """
    return _account_link(
        account_id=account_id,
        use_case_type="account_update",
        return_url=return_url,
        refresh_url=refresh_url,
    )


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------


def current_mode() -> str:
    """``'test'`` or ``'live'``, from the key this environment holds."""
    return settings.stripe_mode
