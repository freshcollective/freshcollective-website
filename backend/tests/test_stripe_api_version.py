"""The Stripe API version FC runs on cannot move without a failing test.

Why this file exists
--------------------

FC sets no ``api_version`` anywhere in ``app/``, which reads like "we use
the Stripe account's Dashboard default". We don't. stripe-python assigns
``stripe.api_version`` from the version the package was generated against
and sends it as a ``Stripe-Version`` header on every request, so the
pinned package version *is* the API version behind checkout, webhooks,
subscriptions and refunds.

Before this, ``requirements.txt`` carried ``stripe>=10.0.0``: a rebuild
that resolved a newer stripe-python would have changed that version for
every FC request, with no code change and nothing in the diff to notice.
Every Stripe interaction in this suite is mocked, so such a change would
break nothing locally and everything in production.

These tests close that gap from three directions: the pin is exact, the
declared constants match the installed library, and the header the SDK
actually puts on the wire is the version we claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest
import stripe
from stripe._http_client import HTTPClient

from app.checkout.stripe_client import (
    EXPECTED_STRIPE_API_MAJOR,
    EXPECTED_STRIPE_API_VERSION,
    EXPECTED_STRIPE_PACKAGE_VERSION,
    StripeVersionMismatch,
    api_version_discrepancies,
    api_version_major,
    assert_api_version,
    get_stripe,
    get_stripe_client,
    installed_api_version,
    installed_package_version,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# The installed library is the one we declared
# ---------------------------------------------------------------------------


def test_installed_package_version_matches_declaration():
    assert installed_package_version() == EXPECTED_STRIPE_PACKAGE_VERSION, (
        "stripe-python was upgraded without updating "
        "EXPECTED_STRIPE_PACKAGE_VERSION. That changes the Stripe API "
        "version every FC request is sent under. Review Stripe's changelog "
        "for the intervening versions, update the constants in "
        "app/checkout/stripe_client.py, and re-run the payment tests."
    )


def test_installed_api_version_matches_declaration():
    assert installed_api_version() == EXPECTED_STRIPE_API_VERSION


def test_declared_major_agrees_with_declared_version():
    # Guards the constants against each other, so a partial edit (new
    # version, stale major) cannot pass.
    assert api_version_major(EXPECTED_STRIPE_API_VERSION) == EXPECTED_STRIPE_API_MAJOR


def test_no_discrepancies_on_a_correctly_pinned_install():
    assert api_version_discrepancies() == []
    assert assert_api_version() == []


# ---------------------------------------------------------------------------
# The pin is exact, not a floor
# ---------------------------------------------------------------------------


def test_requirements_pins_stripe_exactly():
    """A floor (``>=``) is what allowed the version to drift silently.

    Matched with a regex anchored to the dependency line rather than a
    substring search, so the explanatory comment block above the pin —
    which legitimately mentions the old ``stripe>=10.0.0`` — cannot make
    this pass or fail by accident.
    """
    lines = (BACKEND_ROOT / "requirements.txt").read_text().splitlines()
    dependency_lines = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    stripe_lines = [
        line for line in dependency_lines
        if re.match(r"^stripe\b", line)
    ]
    assert len(stripe_lines) == 1, f"expected one stripe requirement, got {stripe_lines}"
    assert stripe_lines[0] == f"stripe=={EXPECTED_STRIPE_PACKAGE_VERSION}", (
        f"stripe must be pinned exactly; found {stripe_lines[0]!r}"
    )


# ---------------------------------------------------------------------------
# What actually goes on the wire
# ---------------------------------------------------------------------------


class _HeaderCapturingClient(HTTPClient):
    """Stands in for the real HTTP client and records request headers.

    The claim this whole file rests on — that the SDK sends its pinned
    version as a ``Stripe-Version`` header on every request — is worth
    proving against the SDK rather than asserting from its source. No
    network: the stub answers with a minimal object of the right shape.
    """

    # Read by the requestor when it composes its client-telemetry
    # header, so the stub has to carry one.
    name = "header-capturing-stub"

    def __init__(self) -> None:
        super().__init__()
        self.captured: list[Mapping[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        post_data: Any = None,
        *,
        _usage: list[str] | None = None,
    ) -> tuple[str, int, Mapping[str, str]]:
        self.captured.append(dict(headers or {}))
        body = json.dumps({"id": "cus_stub", "object": "customer"})
        return body, 200, {"Content-Type": "application/json"}


def test_sdk_sends_the_declared_version_as_a_header():
    client_http = _HeaderCapturingClient()
    client = stripe.StripeClient("sk_test_stub", http_client=client_http)

    client.v1.customers.retrieve("cus_stub")

    assert client_http.captured, "no request was made"
    sent = client_http.captured[0]
    header = {k.lower(): v for k, v in sent.items()}.get("stripe-version")
    assert header == EXPECTED_STRIPE_API_VERSION, (
        f"the SDK sent Stripe-Version {header!r}; this code is written for "
        f"{EXPECTED_STRIPE_API_VERSION!r}"
    )


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------


def test_major_version_change_refuses_to_boot(monkeypatch):
    """A major change alters request and response shapes across the API.

    Refusing at boot is deliberate: on Render a container that fails to
    start leaves the previous healthy deploy serving, so this blocks a bad
    deploy. Discovering it at the first payment has no such safety net.
    """
    monkeypatch.setattr(stripe, "api_version", "2029-01-01.elderflower")
    with pytest.raises(StripeVersionMismatch) as excinfo:
        assert_api_version()
    message = str(excinfo.value)
    assert "elderflower" in message
    assert EXPECTED_STRIPE_API_MAJOR in message


def test_same_major_date_change_is_reported_but_not_fatal(monkeypatch):
    """Loud, not fatal — it still needs attention, but not at the cost of
    refusing to serve."""
    monkeypatch.setattr(stripe, "api_version", "2026-11-30.dahlia")
    notes = assert_api_version()
    assert any("Stripe-Version" in note for note in notes)


def test_package_drift_is_reported_but_not_fatal(monkeypatch):
    monkeypatch.setattr(stripe, "VERSION", "99.0.0")
    notes = assert_api_version()
    assert any("stripe-python" in note for note in notes)


def test_api_version_major_reports_an_unfamiliar_format_verbatim():
    # Better to surface a shape we don't recognise than to parse it into
    # something that happens to compare equal.
    assert api_version_major("not-a-version") == "not-a-version"


# ---------------------------------------------------------------------------
# The v1 path is untouched by the v2 addition
# ---------------------------------------------------------------------------


def test_get_stripe_still_returns_the_module_with_the_key_bound():
    """Every existing v1 call site depends on this exact behaviour."""
    returned = get_stripe()
    assert returned is stripe
    assert stripe.api_key  # bound, not cleared


def test_v2_has_no_module_global_call_pattern():
    """The reason the factory exists.

    ``stripe.v2.core`` imports fine, which makes it look as though FC's
    existing ``stripe.X.create(...)`` idiom would work. It does not: the
    v2 resource classes carry no API classmethods, so there is nothing to
    call without a client.
    """
    for name in ("Account", "AccountLink", "EventDestination"):
        resource = getattr(stripe.v2.core, name)
        for operation in ("create", "retrieve", "list"):
            assert not hasattr(resource, operation), (
                f"stripe.v2.core.{name}.{operation} now exists — the v2 "
                "surface may be reachable without a client, and "
                "get_stripe_client()'s rationale needs revisiting."
            )


def test_get_stripe_client_reaches_the_v2_account_services():
    client = get_stripe_client()
    assert hasattr(client.v2.core.accounts, "create")
    assert hasattr(client.v2.core.account_links, "create")
    assert hasattr(client.v2.core.event_destinations, "create")
