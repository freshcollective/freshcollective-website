"""No test reaches Stripe unless it says so, out loud, in test mode.

The gap this closes
-------------------
Stage 5A.3b found it the hard way: a test that exercised a cancellation
without mocking ``stripe.Subscription.modify`` called the **real**
test-mode API, and only failed because the subscription id it invented
did not exist there. Had the id happened to be real, the test would
have modified a live test-mode subscription and passed.

Payment code is exactly where that is least acceptable, and the suite
already holds the precedent: email is guarded at the SDK boundary
rather than in the provider, so a forgotten mock cannot send to a real
address. This is the same discipline for money.

Where the block is placed, and why not higher
---------------------------------------------
On the **HTTP clients that actually open a socket** —
``RequestsClient.request`` and its siblings — rather than on the SDK's
internal request funnel.

The first attempt did patch the funnel,
``_APIRequestor.request``, and it was too blunt: it broke
``test_stripe_api_version.py``, which injects its own stub HTTP client
to read the ``Stripe-Version`` header off a request that never leaves
the process. That test was always safe, and a guard that fails safe
tests teaches people to switch guards off.

Patching the concrete clients draws the line where it belongs. A test
that supplies its own ``http_client`` overrides ``request`` on its own
class and is untouched; a test that forgot to mock anything gets the
default client and is stopped. The distinction is exactly "would this
have reached Stripe".

These are private paths, and that is survivable precisely because
``test_stripe_guard.py`` asserts the block actually blocks. An SDK
upgrade that moves them fails that test loudly rather than quietly
disarming the guard — which is the failure mode worth engineering
against.
"""

from __future__ import annotations

import os

#: Set to ``1`` to let a marked test talk to Stripe. Deliberately
#: awkward: provider validation is an occasional, deliberate act.
OPT_IN_ENV = "FC_STRIPE_PROVIDER_TESTS"

#: The marker a test must carry as well. Both are required — an
#: env var alone would arm every test in the run, and a marker alone
#: would let a casual ``pytest -k`` reach the network.
MARKER = "stripe_provider"


class StripeCallInTest(AssertionError):
    """A test tried to call Stripe without asking."""


class LiveStripeCredentials(AssertionError):
    """A provider test was pointed at a live key."""


def assert_test_mode_credentials() -> None:
    """Refuse to proceed unless the configured key is test mode.

    Checked before any provider call rather than trusting the
    environment to be what it usually is. A live secret key reaches
    real customers and real money, so this raises rather than skips —
    a skipped test is easy to miss, and the whole point is that this
    situation must be impossible to ignore.
    """
    from app.core.config import settings

    key = (settings.stripe_secret_key or "").strip()
    if not key:
        raise LiveStripeCredentials(
            "provider validation needs a Stripe test key; none is configured"
        )
    if not key.startswith("sk_test"):
        raise LiveStripeCredentials(
            "refusing to run provider validation against a key that is not "
            "sk_test — this would touch real customers and real money"
        )


def opted_in() -> bool:
    return os.environ.get(OPT_IN_ENV, "").strip() in {"1", "true", "yes"}


#: Every concrete client the SDK might reach the network through.
#: Named rather than discovered so an SDK that adds one fails the
#: guard's own test instead of silently gaining an unguarded path.
_NETWORK_CLIENTS = (
    "RequestsClient", "UrlFetchClient", "PycurlClient",
    "HTTPXClient", "AIOHTTPClient", "NoImportFoundAsyncClient",
)

#: The methods on those clients that put bytes on the wire.
_NETWORK_METHODS = (
    "request", "request_stream",
    "request_async", "request_stream_async",
)


def block_stripe(monkeypatch) -> int:
    """Cut this test off from the network, for its duration.

    Returns how many client methods were blocked, so the guard's own
    test can assert it found something to block rather than passing
    vacuously against an SDK that renamed everything.
    """
    from stripe import _http_client

    def _refuse(*args, **kwargs):
        raise StripeCallInTest(
            "This test tried to call the Stripe API.\n\n"
            "Tests must mock Stripe — see the _StripeDouble fixtures in "
            "tests/test_stage5a3b_membership_member_experience.py, or "
            "patch the specific resource method you are exercising.\n\n"
            "If this test is deliberate provider validation, mark it "
            f"@pytest.mark.{MARKER} and run with {OPT_IN_ENV}=1."
        )

    blocked = 0
    for class_name in _NETWORK_CLIENTS:
        client_cls = getattr(_http_client, class_name, None)
        if client_cls is None:
            continue
        for method in _NETWORK_METHODS:
            # ``raising=False`` for methods a given client does not
            # define; only its own are replaced, so a subclass that
            # overrides ``request`` — a test's stub — keeps its own.
            if method in client_cls.__dict__:
                monkeypatch.setattr(client_cls, method, _refuse)
                blocked += 1
    return blocked
