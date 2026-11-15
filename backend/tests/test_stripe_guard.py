"""The guard that stops a test calling Stripe by accident.

Stage 5A.3c §4. This file exists to make the guard's own failure
visible: if an SDK upgrade moves the request funnel, or the autouse
fixture stops being applied, these tests fail rather than the suite
quietly regaining the ability to spend money.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stripe_guard.py
"""

from __future__ import annotations

import pytest
import stripe

from tests import stripe_guard


@pytest.fixture
def key_bound(monkeypatch):
    """A Stripe key bound on the module, as app code leaves it.

    ``_bind_key()`` sets ``stripe.api_key`` globally, so the first test
    that exercises any paying code path arms the SDK for every test
    after it in the same process. Without a key the SDK refuses before
    reaching the network, which looks like protection and is not — it
    is simply the state a suite is in until something binds one. These
    tests model the armed state, because that is the dangerous one.
    """
    monkeypatch.setattr(stripe, "api_key", "sk_test_guard_probe")


class TestAnOrdinaryTestCannotReachStripe:
    def test_a_resource_call_is_refused(self, key_bound):
        """The case that prompted all this: a forgotten mock."""
        with pytest.raises(stripe_guard.StripeCallInTest) as exc:
            stripe.Subscription.modify("sub_whatever", cancel_at_period_end=True)
        assert "mock Stripe" in str(exc.value)

    def test_a_different_resource_is_refused_too(self, key_bound):
        """One patch at the funnel, not a list of resources to maintain."""
        with pytest.raises(stripe_guard.StripeCallInTest):
            stripe.checkout.Session.create(mode="setup", customer="cus_x")

    def test_a_retrieve_is_refused(self, key_bound):
        with pytest.raises(stripe_guard.StripeCallInTest):
            stripe.Invoice.retrieve("in_x")

    def test_the_message_says_what_to_do(self, key_bound):
        with pytest.raises(stripe_guard.StripeCallInTest) as exc:
            stripe.Customer.create()
        text = str(exc.value)
        assert stripe_guard.OPT_IN_ENV in text
        assert stripe_guard.MARKER in text


class TestMockedCallsAreUnaffected:
    def test_a_patched_resource_still_works(self, monkeypatch, key_bound):
        """The guard sits under the SDK, so a mock above it is reached
        first — every existing payment test keeps working unchanged."""
        from types import SimpleNamespace
        monkeypatch.setattr(
            "stripe.Subscription.modify",
            lambda sid, **kw: SimpleNamespace(id=sid, **kw),
        )
        out = stripe.Subscription.modify("sub_1", cancel_at_period_end=True)
        assert out.id == "sub_1"
        assert out.cancel_at_period_end is True


class TestCredentialSafety:
    def test_a_live_key_is_refused(self, monkeypatch):
        """Raised, not skipped. A skipped test is easy to miss, and
        this is the situation that must be impossible to ignore."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_abc123")
        with pytest.raises(stripe_guard.LiveStripeCredentials) as exc:
            stripe_guard.assert_test_mode_credentials()
        assert "real money" in str(exc.value)

    def test_an_absent_key_is_refused(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_secret_key", "")
        with pytest.raises(stripe_guard.LiveStripeCredentials):
            stripe_guard.assert_test_mode_credentials()

    def test_a_test_key_is_accepted(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_abc123")
        stripe_guard.assert_test_mode_credentials()

    def test_a_publishable_key_is_not_a_secret_key(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "stripe_secret_key", "pk_test_abc123")
        with pytest.raises(stripe_guard.LiveStripeCredentials):
            stripe_guard.assert_test_mode_credentials()


class TestTheGuardIsActuallyArmed:
    def test_it_blocks_real_client_methods(self, monkeypatch):
        """Guards against passing vacuously: if an SDK upgrade renamed
        every client, blocking nothing would otherwise look like
        success."""
        blocked = stripe_guard.block_stripe(monkeypatch)
        assert blocked >= 1, (
            "the guard patched nothing — stripe's HTTP clients have "
            "moved and tests are no longer protected"
        )

    def test_a_test_supplied_client_is_left_alone(self, monkeypatch):
        """The reason the guard sits on the concrete clients rather
        than the SDK's request funnel: a stub that never touches the
        network must keep working."""
        from typing import Any, Mapping
        from stripe._http_client import HTTPClient

        class _Stub(HTTPClient):
            name = "stub"

            def request(self, method, url, headers, post_data=None, **kw):
                return '{"id": "cus_stub", "object": "customer"}', 200, {}

        stripe_guard.block_stripe(monkeypatch)
        client = stripe.StripeClient("sk_test_stub", http_client=_Stub())
        assert client.v1.customers.retrieve("cus_stub").id == "cus_stub"


@pytest.mark.stripe_provider
class TestTheOptInWorks:
    """Skipped unless ``FC_STRIPE_PROVIDER_TESTS=1``.

    Its presence in an ordinary run is the proof that opting in is
    deliberate: an unmarked run reports it as skipped rather than
    executing it.
    """

    def test_the_guard_is_lifted_and_the_key_is_test_mode(self):
        from app.core.config import settings
        assert (settings.stripe_secret_key or "").startswith("sk_test")
        # The network clients are their own again — not called,
        # because asserting the guard is lifted does not require
        # spending a request.
        from stripe._http_client import RequestsClient
        assert RequestsClient.request.__name__ != "_refuse"
