"""ONE-OFF: prove an error reaches the fc-api Sentry project.

Run this once from a Render shell after ``SENTRY_DSN`` is set on that
service. It sends exactly one synthetic error through the real
``init_sentry()`` and the real scrubber, then exits.

One script, any component. ``--component`` names which process is
pretending to fail, so a cron can be verified with the same evidence
and the same fake secrets as fc-api — the component tag is the only
difference between them, and proving the tag arrives is half the point.

Why a script and not an endpoint
--------------------------------
A ``/sentry-debug`` route would be a permanent, reachable way to make
the production API raise. This leaves nothing behind: no route, no
mounted surface, nothing a stranger can hit. The only way to run it is
to already be inside the service.

What it proves
--------------
  1. The event reaches the fc-api project at all — DSN, network, CSP
     irrelevance, the lot.
  2. ``environment``, ``release`` and the ``component`` tag arrive
     correctly. Release comes from ``RENDER_GIT_COMMIT``.
  3. The scrubber works on real data paths, because this deliberately
     carries fake secrets through every channel the scrubber covers:
     an exception message, ``extra``, a tag, a breadcrumb, and a user
     record.

Every "secret" below is a literal constant in this file — a fake
address at ``.invalid`` (a reserved TLD that can never resolve) and
obvious ``FAKE_…`` strings. Nothing is read from the environment, so
this cannot print or transmit a real secret.

Usage, from the service's own Render shell::

    python scripts/sentry_smoke_test.py
    python scripts/sentry_smoke_test.py --component fc-refund-reconciler

A cron service has a shell of its own, and that is the one to use: it
is the environment that carries that job's ``APP_ENV`` and its own copy
of ``SENTRY_DSN``. Running the cron's component name from the fc-api
shell would prove the tag and nothing else.

Exit codes::

    0  one event was submitted and flushed
    1  SENTRY_DSN is not set, the component is unknown, or the flush
       timed out

Then, in Sentry: open the fc-api project, find the newest issue, and
confirm the heading is the synthetic one and that **none** of
``test@example.invalid``, ``FAKE_SENTRY_TEST_TOKEN`` or
``Bearer FAKE_TOKEN`` appears anywhere in it — not in the message, the
tags, the extra data, the breadcrumbs or the user.

Delete the issue afterwards; it is noise.

Not scheduled, not imported by anything, absent from render.yaml.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("FC_SERVICE_ROLE", "job")

# ruff: noqa: E402
from app.core.observability import init_sentry

#: Every process that reports to the fc-api Sentry project: the API and
#: the seven crons, each tagged with its own Render service name.
#: ``test_cron_observability`` asserts this agrees with render.yaml, so
#: a new service cannot be verified under a name Sentry has never seen.
COMPONENTS = (
    "fc-api",
    "fc-fip3-grace-reconciler",
    "fc-refund-reconciler",
    "fc-creator-subscription-grace-reconciler",
    "fc-creator-grant-expiry",
    "fc-gathering-reminders",
    "fc-connect-transfer-sweeper",
    "fc-connect-recovery-sweeper",
)

#: Fake, and recognisable as fake. ``.invalid`` is reserved by RFC 2606
#: and can never resolve, so this address cannot reach anyone.
FAKE_EMAIL = "test@example.invalid"
FAKE_TOKEN = "FAKE_SENTRY_TEST_TOKEN"
FAKE_BEARER = "Bearer FAKE_TOKEN"

MARKER = "Sentry smoke test — synthetic, safe to delete"


class SentrySmokeTestError(RuntimeError):
    """Deliberate. Its name is the point — it should be unmistakable in
    the issue list, and unmistakably not a real failure."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentry smoke test.")
    parser.add_argument(
        "--component", default="fc-api", choices=COMPONENTS,
        help="which process this event should be tagged as (default fc-api)",
    )
    args = parser.parse_args()
    component = args.component

    if not init_sentry(component):
        print(
            "SENTRY_DSN is not set in this shell, so nothing was sent.\n"
            f"Set it on the {component} service first, let the service "
            "pick it up, then run this again.",
            file=sys.stderr,
        )
        return 1

    import sentry_sdk

    print(f"environment : {os.environ.get('APP_ENV') or '(unset)'}")
    print(f"release     : {os.environ.get('RENDER_GIT_COMMIT') or '(unset)'}")
    print(f"component   : {component}")
    print()

    # Fake secrets through every channel the scrubber covers, so a
    # missing redaction is visible rather than theoretical.
    sentry_sdk.add_breadcrumb(
        category="smoke-test",
        message=f"breadcrumb carrying reset_url=https://example.invalid/r?token={FAKE_TOKEN}",
        level="info",
    )
    scope = sentry_sdk.get_isolation_scope()
    scope.set_user({"id": "smoke-test-user", "email": FAKE_EMAIL})
    scope.set_tag("smoke_test_token", FAKE_TOKEN)
    scope.set_extra("authorization", FAKE_BEARER)
    scope.set_extra("reset_url", f"https://example.invalid/reset?token={FAKE_TOKEN}")
    scope.set_extra("harmless_detail", "this one should survive")

    try:
        raise SentrySmokeTestError(
            f"{MARKER}. Contact {FAKE_EMAIL} with token={FAKE_TOKEN} — "
            f"all three of those must be redacted in Sentry."
        )
    except SentrySmokeTestError:
        event_id = sentry_sdk.capture_exception()

    flushed = sentry_sdk.flush(timeout=10)
    print(f"event id    : {event_id}")
    print()
    if event_id is None:
        print("The SDK did not accept the event. Check the DSN.", file=sys.stderr)
        return 1
    if flushed is False:
        print(
            "Submitted, but the flush timed out — the event may still "
            "arrive. Check Sentry before re-running.",
            file=sys.stderr,
        )
        return 1

    print("Sent. In the fc-api Sentry project, confirm the newest issue:")
    print("  * is titled SentrySmokeTestError")
    print(f"  * carries environment={os.environ.get('APP_ENV') or '(unset)'} "
          f"and release={(os.environ.get('RENDER_GIT_COMMIT') or '(unset)')[:12]}")
    print(f"  * has tag component={component}")
    print("  * contains 'this one should survive' in its extra data")
    print(f"  * contains NO occurrence of {FAKE_EMAIL}, {FAKE_TOKEN}, "
          f"or {FAKE_BEARER}")
    print("  * shows a user id but no user email")
    print()
    print("Then delete the issue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
