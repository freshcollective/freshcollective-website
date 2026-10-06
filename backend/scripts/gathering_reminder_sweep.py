"""Send 24-hour gathering reminders that have come due.

Runs one sweep and prints the outcome. Designed for the
``fc-gathering-reminders`` Render cron (every 15 minutes) but safe to
run ad-hoc or interactively.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/gathering_reminder_sweep.py [--dry-run]

--dry-run
    Lists the bookings that would be reminded without emitting any
    communication event or sending anything. Use this to preview a
    window before enabling the cron.

Idempotency is owned by the sweep, not by this script: each reminder
carries the dedupe key ``gathering_reminder_24h:{booking_id}``, so
running this twice — or overlapping with the cron — cannot double-send.

Exit code:
    0 on success, including when zero reminders were due.
    1 on unexpected error (never on an empty result).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Logging is configured first so that the line below is actually
# emitted. Without a handler installed, Python's last-resort handler
# drops anything below WARNING — and "SENTRY_DSN is not set" is an INFO
# line that matters most on the one deploy where it is true.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

# Error reporting starts here, before the app imports below, and that
# order is deliberate: the first thing that can go wrong in a cron is
# ``Settings`` refusing to construct, and that happens at import time.
# ``app.core.observability`` imports nothing from ``app``, so calling it
# first cannot affect import order or reintroduce a cycle.
#
# A missing ``SENTRY_DSN`` makes this a clean no-op, which is how every
# local and ad-hoc run behaves.
from app.core.observability import (  # noqa: E402
    flush_sentry,
    init_sentry,
)

init_sentry("fc-gathering-reminders")

# ruff: noqa: E402
# Full model registry load — same rationale as fip3_reconcile_grace.py.
# Importing app.main is a side-effect import that resolves every
# string-referenced SQLAlchemy relationship; it does not start uvicorn.
import app.main  # noqa: F401
from app.core.database import SessionLocal
from app.services.gathering_reminders import (
    find_due_bookings,
    sweep_due_reminders,
)


logger = logging.getLogger("gathering_reminder_sweep")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        if args.dry_run:
            due = find_due_bookings(db, now=now)
            logger.info(
                "gathering_reminder_sweep: DRY RUN — %d booking(s) due at %s",
                len(due), now.isoformat(),
            )
            for booking, event, space in due:
                logger.info(
                    "  would remind booking=%s user=%s gathering=%r starts_at=%s "
                    "collective=%r",
                    booking.id, booking.user_id, event.title,
                    event.starts_at.isoformat(),
                    getattr(space, "name", None),
                )
            return 0

        outcome = sweep_due_reminders(db, now=now)
        logger.info(
            "gathering_reminder_sweep: considered=%d emitted=%d deduped=%d "
            "skipped_preference=%d",
            outcome.considered, outcome.emitted, outcome.deduped,
            outcome.skipped_preference,
        )
        return 0
    except Exception:
        logger.exception("gathering_reminder_sweep: failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    # The flush is in a ``finally`` so it runs on the failure path too,
    # which is the path whose event matters most. It is bounded and
    # swallows its own errors, so it cannot change the exit code — a
    # Sentry outage must never turn a good run into a failed cron.
    try:
        raise SystemExit(main())
    finally:
        flush_sentry()
