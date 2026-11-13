"""Sweep paid Collective membership agreements.

Four things, all of which webhooks normally handle and occasionally do
not:

  * a grace window that expired without recovery → end the agreement,
    at Stripe as well as locally, and pause the access it bought;
  * a cancelled-at-period-end agreement whose period has run out;
  * **a live agreement whose membership has already ended** — somebody
    left, was removed or was banned and the Stripe cancel did not take.
    This is the durable retry ``end_membership`` promises;
  * a Collective whose ``paid_membership_effective_at`` has arrived,
    pausing members with no paid agreement.

Charges nobody. Subscribes nobody. Emails nobody.

Idempotent under repeated runs: every branch checks the state it is
about to change, so a second pass does nothing and a run that dies
halfway leaves its completed work in place. Commits per row.

Usage::

    cd /home/lindsey/fc-merge/backend
    .venv/bin/python scripts/collective_membership_reconcile.py

Exit code:
    0 on success, including when nothing moved.
    1 on unexpected error, or when a departed member's billing still
      could not be stopped — that one is not a quiet failure.

Runtime config, matching the sibling reconcilers:
  * ``FC_SERVICE_ROLE=job``  — skips web-only Settings validators.
  * ``DATABASE_URL``         — same database as fc-api.
  * ``APP_ENV=production``   — for the Stripe-key-mode guard.

Unlike ``creator_subscription_grace_reconcile`` this script *does* call
Stripe, to cancel subscriptions that must stop charging, so it needs a
usable Stripe key.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Logging first, so anything the lines below emit is actually visible.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

# Then error reporting, before the app is imported. The first thing that
# can go wrong in a cron is ``Settings`` refusing to construct, and that
# happens at import time — so the reporter has to exist before it.
# ``app.core.observability`` imports nothing from ``app``, so this
# cannot affect import order. A missing ``SENTRY_DSN`` is a clean no-op.
from app.core.observability import (  # noqa: E402
    flush_sentry,
    init_sentry,
)

init_sentry("fc-collective-membership-reconciler")

logger = logging.getLogger("collective_membership_reconcile")


def main() -> int:
    # Importing the app registers every model, the way the sibling
    # reconcilers do. Without it SQLAlchemy cannot resolve the
    # cross-module relationships these queries join across.
    import app.main  # noqa: F401

    from app.core.database import SessionLocal
    from app.services.collective_membership_reconcile import (
        reconcile_collective_memberships,
    )

    db = SessionLocal()
    try:
        report = reconcile_collective_memberships(db)
    except Exception:
        logger.exception("membership reconcile: unexpected failure")
        return 1
    finally:
        db.close()

    for key, value in report.as_dict().items():
        if key != "errors":
            logger.info("  %-32s %s", key, value)
    for err in report.errors:
        logger.error("  %s", err)

    if report.billing_after_departure_failed:
        logger.error(
            "%d departed member(s) may still be billed — Stripe could not "
            "be reached. This needs a person.",
            report.billing_after_departure_failed,
        )
        return 1
    return 0


if __name__ == "__main__":
    # Flushed in a ``finally`` so the failure path reports too — a cron
    # can exit before the SDK's worker has sent anything, and the event
    # most worth having is from the run that just died. Bounded, and it
    # swallows its own errors: a Sentry outage must never turn a good
    # run into a failed cron.
    try:
        raise SystemExit(main())
    finally:
        flush_sentry()
