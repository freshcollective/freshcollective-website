#!/usr/bin/env python3
"""Create (or inspect) the Accounts v2 event destination.

Run by hand, once per Stripe mode. Deliberately **not** wired into
application startup: creating a delivery destination is a one-off
administrative act, and doing it on boot would mean every deploy, every
replica and every local run racing to create or mutate one.

    python scripts/create_connect_event_destination.py --list
    python scripts/create_connect_event_destination.py --create

Stripe returns the signing secret **only** in the create response. This
script prints it once, to stdout, and never writes it to a file, a log or
the database. Copy it into ``STRIPE_V2_WEBHOOK_SECRET`` for the
environment and do not commit it. If it is lost, delete the destination
and create a new one — there is no way to read it back.

The payload is ``thin`` on purpose. A thin notification carries
identifiers and FC re-fetches the account, which is what you want for
account status: the state you act on is current as of the read, not as of
delivery. A ``snapshot`` destination would let FC skip the fetch at the
cost of acting on a payload that was already stale, and against a shape
Stripe may evolve.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checkout.stripe_client import get_stripe_client  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.webhooks.connect_routes import SUPPORTED_EVENTS  # noqa: E402

# Sorted so the request is stable across runs and diffs are readable.
ENABLED_EVENTS = sorted(SUPPORTED_EVENTS)


def _endpoint_url() -> str:
    return f"{settings.resolved_public_app_url}/api/webhooks/stripe/v2"


def _list() -> int:
    client = get_stripe_client()
    page = client.v2.core.event_destinations.list({"limit": 20})
    if not page.data:
        print("No event destinations exist in this Stripe mode.")
        return 0
    for destination in page.data:
        d = json.loads(str(destination))
        print(f"- {d.get('id')}  name={d.get('name')!r}")
        print(f"    status        : {d.get('status')}")
        print(f"    event_payload : {d.get('event_payload')}")
        print(f"    url           : {(d.get('webhook_endpoint') or {}).get('url')}")
        print(f"    events        : {len(d.get('enabled_events') or [])}")
        for event in d.get("enabled_events") or []:
            print(f"        {event}")
    return 0


def _create(url: str) -> int:
    client = get_stripe_client()
    name = settings.stripe_v2_event_destination_name

    existing = client.v2.core.event_destinations.list({"limit": 100})
    for destination in existing.data:
        d = json.loads(str(destination))
        if d.get("name") == name:
            print(
                f"A destination named {name!r} already exists ({d.get('id')}).\n"
                "Refusing to create a second one — two destinations would "
                "deliver every event twice.\n"
                "Its signing secret cannot be read back; delete it and re-run "
                "this script if the secret has been lost.",
                file=sys.stderr,
            )
            return 1

    destination = client.v2.core.event_destinations.create({
        "name": name,
        "description": "Fresh Collective — creator Connect account lifecycle",
        "type": "webhook_endpoint",
        # Identifiers, not state. FC re-fetches the account.
        "event_payload": "thin",
        "enabled_events": ENABLED_EVENTS,
        "webhook_endpoint": {"url": url},
        # The secret is returned only here, and only if asked for.
        "include": ["webhook_endpoint.signing_secret"],
    })

    d = json.loads(str(destination))
    secret = (d.get("webhook_endpoint") or {}).get("signing_secret")

    print(f"Created event destination {d.get('id')}")
    print(f"  mode          : {settings.stripe_mode}")
    print(f"  name          : {d.get('name')}")
    print(f"  url           : {url}")
    print(f"  event_payload : {d.get('event_payload')}")
    print(f"  status        : {d.get('status')}")
    print("  enabled events:")
    for event in d.get("enabled_events") or []:
        print(f"      {event}")
    print()
    if secret:
        print("Signing secret — shown once, and never stored by this script:")
        print()
        print(f"    STRIPE_V2_WEBHOOK_SECRET={secret}")
        print()
        print("Set it on the environment now. Stripe will not show it again.")
    else:
        print(
            "WARNING: Stripe did not return a signing secret. The destination "
            "exists but cannot be verified against — delete it and re-run.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="show existing destinations")
    group.add_argument("--create", action="store_true", help="create FC's destination")
    parser.add_argument(
        "--url",
        default=None,
        help=f"override the endpoint URL (default: {_endpoint_url()})",
    )
    args = parser.parse_args()

    print(f"Stripe mode: {settings.stripe_mode}", file=sys.stderr)

    if args.list:
        return _list()

    url = args.url or _endpoint_url()
    if not url.startswith("https://"):
        print(
            f"Refusing to register {url!r} — Stripe requires https, and a "
            "local URL could never receive a delivery. Pass --url with the "
            "deployed API host.",
            file=sys.stderr,
        )
        return 1
    return _create(url)


if __name__ == "__main__":
    raise SystemExit(main())
