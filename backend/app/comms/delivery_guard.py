"""Refuse outbound email that should never leave the process.

Why this exists
---------------

On 2026-10-09 an automated test sent real email through the live Resend
account. No single component was wrong. The chain was:

* ``tests/test_booking_concurrency.py`` used committed fixtures, so the
  ``CommunicationEvent`` it created was visible to a fresh session.
* It called ``commit_reservations`` without ``background_tasks``, and
  ``schedule_routing_if_needed`` runs routing **synchronously** in that
  case rather than deferring it (``rollout.py``).
* ``gatherings`` is in the default ``comms_live_topics``, so the mode
  was ``live``, with no env var set anywhere.
* ``ResendProvider.send``'s only guard was the presence of an API key,
  and a live key sat in the developer's ``backend/.env``.

Nothing in that path consulted ``APP_ENV``. The sends went to
``@example.test`` addresses, which hard-bounce — the reputation cost
outlives the quota it consumed.

The lesson is not "remember to mock Resend in tests". It is that the
decision to contact a real provider was spread across four files and
owned by none of them. This module owns it.

The three layers
----------------

Checked in this order, because the earlier ones must not be escapable
by changing the later ones:

1. **Test process** — this module steps aside, because the automated
   suite is guarded at a better place: ``tests/conftest.py`` installs
   a tripwire over the Resend SDK's send functions, so reaching the
   network raises instead of sending. Blocking here as well would only
   break the comms tests that legitimately exercise dispatch against
   their own stub. See ``outbound_email_block``.
2. **Reserved domains** — ``.test``, ``.invalid``, ``.example``,
   ``.localhost`` and the ``example.{com,net,org}`` names are reserved
   by RFC 2606 / RFC 6761 and can never resolve. Refusing them is
   correct in *every* environment, production included: the only
   possible outcome of such a send is a hard bounce.
3. **Non-production environments** — development and staging do not
   reach a real provider unless someone asks for it explicitly, by
   setting ``FC_ALLOW_REAL_EMAIL=1``. That is the controlled method for
   deliberately testing real delivery; it is an env var rather than a
   code change so it leaves no trace to accidentally commit, and it
   cannot lift layer 1.

Production is deliberately untouched: with ``APP_ENV=production``, a
real recipient and no test-process markers, none of the three layers
fire and ``send`` behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings

# RFC 6761 reserved TLDs, plus RFC 2606's. Matched on the host part, so
# ``.test`` catches ``m0-abc@example.test`` and ``user@sub.dev.test``
# alike.
RESERVED_EMAIL_TLDS: tuple[str, ...] = (
    ".test",
    ".invalid",
    ".example",
    ".localhost",
)

# RFC 2606 §3 reserved second-level names. These *do* resolve in DNS but
# are reserved for documentation and will never belong to a member.
RESERVED_EMAIL_DOMAINS: tuple[str, ...] = (
    "example.com",
    "example.net",
    "example.org",
)

# Set by ``tests/conftest.py`` at import time — before the app is
# imported, so it covers collection, every test, and any thread a test
# spawns. An env var rather than a module flag precisely because
# background routing opens its own session on its own stack and would
# not see process-local state set by a fixture.
TEST_MODE_ENV_VAR = "FC_TEST_MODE"

# pytest sets this per test item. Belt and braces alongside
# ``FC_TEST_MODE``: either one alone is sufficient.
PYTEST_MARKER_ENV_VAR = "PYTEST_CURRENT_TEST"

# The explicit, controlled opt-in for deliberately testing real delivery
# from a non-production environment. Cannot lift the test-process block.
ALLOW_REAL_EMAIL_ENV_VAR = "FC_ALLOW_REAL_EMAIL"


@dataclass(frozen=True)
class DeliveryBlock:
    """Why a send was refused.

    ``error_class`` lands on the delivery row, so a blocked send is
    visible in the comms audit trail rather than silently absent.
    """

    error_class: str
    detail: str


def running_in_test_process() -> bool:
    """True when this process is running the automated test suite."""
    return bool(
        os.environ.get(TEST_MODE_ENV_VAR)
        or os.environ.get(PYTEST_MARKER_ENV_VAR)
    )


def real_delivery_opted_in() -> bool:
    """Whether a non-production environment has explicitly asked to
    reach the real provider."""
    return os.environ.get(ALLOW_REAL_EMAIL_ENV_VAR, "").strip().lower() in {
        "1", "true", "yes",
    }


def is_reserved_recipient(recipient: str | None) -> bool:
    """True for an address that can never belong to a real person."""
    if not recipient:
        return False
    _, _, host = recipient.rpartition("@")
    host = (host or recipient).strip().lower().rstrip(".")
    if not host:
        return False
    if any(host == name or host.endswith("." + name)
           for name in RESERVED_EMAIL_DOMAINS):
        return True
    # Both ``user@sub.example.test`` and the bare ``user@localhost``
    # count: a reserved TLD is reserved whether or not anything sits in
    # front of it.
    return any(
        host == tld.lstrip(".") or host.endswith(tld)
        for tld in RESERVED_EMAIL_TLDS
    )


def redact_recipient(recipient: str | None) -> str:
    """A recipient safe to put in a log line.

    This module's refusals are logged, and fc-api reports to Sentry,
    where a WARNING becomes a breadcrumb attached to whatever error
    comes next. A member's email address in a breadcrumb is exactly the
    leak the Phase 2 comms work went to some trouble to close, and the
    non-production refusal fires on every send in development, so the
    volume is not negligible.

    The domain is the whole diagnostic value here — "which reserved
    domain", "is this even a real address" — and the local part carries
    all of the identity, so only the domain survives.
    """
    if not recipient:
        return "(no recipient)"
    _, sep, host = recipient.rpartition("@")
    return f"***@{host}" if sep else "***"


def outbound_email_block(recipient: str | None) -> DeliveryBlock | None:
    """The single decision: may this email reach a real provider?

    Returns ``None`` to allow the send, or a ``DeliveryBlock`` naming
    the reason to refuse. Order matters — see the module docstring.
    """
    if running_in_test_process():
        # Deliberately defers rather than refusing here.
        #
        # The first version of this module blocked every send from a
        # test process. It broke 38 existing tests — the comms suite
        # (r1/r2a/r2b/r3) deliberately exercises the full
        # emit → intent → provider path with ``resend.Emails.send``
        # patched, and asserts the dispatch was accepted. Refusing at
        # this point made all of them fail, which was a strong hint
        # that the check was in the wrong place: a policy decision
        # inside the provider cannot tell a real send from one aimed
        # at a stub.
        #
        # So enforcement for tests sits at the egress boundary
        # instead. ``tests/conftest.py`` installs a tripwire over the
        # Resend SDK's own send functions, which raises if anything
        # reaches them. That is strictly stronger than refusing here —
        # it cannot be bypassed by a code path this module does not
        # know about — and it leaves a test free to patch the SDK with
        # its own stub, which is not a send at all.
        return None

    if is_reserved_recipient(recipient):
        return DeliveryBlock(
            "reserved_domain",
            "Refusing to send: the recipient uses a reserved domain "
            "(RFC 2606 / RFC 6761) that can never resolve, so the only "
            "possible outcome is a hard bounce.",
        )

    if settings.app_env != "production" and not real_delivery_opted_in():
        return DeliveryBlock(
            "non_production_env",
            f"Refusing to send: APP_ENV={settings.app_env!r} is not "
            f"'production'. Set {ALLOW_REAL_EMAIL_ENV_VAR}=1 to allow "
            "real delivery from this environment deliberately.",
        )

    return None


__all__ = [
    "ALLOW_REAL_EMAIL_ENV_VAR",
    "DeliveryBlock",
    "PYTEST_MARKER_ENV_VAR",
    "RESERVED_EMAIL_DOMAINS",
    "RESERVED_EMAIL_TLDS",
    "TEST_MODE_ENV_VAR",
    "is_reserved_recipient",
    "outbound_email_block",
    "real_delivery_opted_in",
    "redact_recipient",
    "running_in_test_process",
]
