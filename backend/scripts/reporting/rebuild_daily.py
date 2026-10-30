"""Nightly reporting rebuild. What ``fc-reporting-nightly`` runs.

Rebuilds the last completed Australian calendar day plus a short
lookback, so a refund recorded late or a Stripe fee backfilled after the
fact is picked up without anybody asking — and so a missed night repairs
itself the following one.

Idempotent: every write is an upsert keyed on (metric, date, dimension),
so running it twice, or over a range already built, recomputes and
overwrites rather than duplicating.

Usage
-----
    python scripts/reporting/rebuild_daily.py                 # nightly
    python scripts/reporting/rebuild_daily.py --days 30       # longer lookback
    python scripts/reporting/rebuild_daily.py --from 2026-01-01 --to 2026-01-31
    python scripts/reporting/rebuild_daily.py --dry-run       # report, write nothing

Exits non-zero on failure so the cron is recorded as failed by Render as
well as in ``reporting_job_runs``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# This script lives one level deeper than the other cron entry points
# (scripts/reporting/ rather than scripts/), so the backend root is two
# parents up. Render runs it with rootDir=backend, where ``app`` is not
# importable without this.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Logging first, so the observability line below is actually emitted —
# without a handler installed, Python's last-resort handler drops
# anything below WARNING, and "SENTRY_DSN is not set" is an INFO line
# that matters most on the one deploy where it is true.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

# Error reporting starts before the app imports below, deliberately: the
# first thing that can go wrong in a cron is ``Settings`` refusing to
# construct, and that happens at import time. A missing ``SENTRY_DSN``
# makes this a clean no-op, which is how every local run behaves.
from app.core.observability import (  # noqa: E402
    flush_sentry,
    init_sentry,
)

init_sentry("fc-reporting-nightly")

# ruff: noqa: E402
# Side-effect import that resolves every string-referenced SQLAlchemy
# relationship. Does not start uvicorn.
import app.main  # noqa: F401
from app.core.database import SessionLocal
from app.core.periods import completed_reporting_date, platform_tz
from app.reporting import aggregates

logger = logging.getLogger("reporting.rebuild")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=None,
                        help="Lookback in days from the last completed day.")
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be rebuilt and write nothing.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        last_day = completed_reporting_date(datetime.utcnow())
        if args.date_from or args.date_to:
            if not (args.date_from and args.date_to):
                logger.error("--from and --to must be given together")
                return 2
            first = date.fromisoformat(args.date_from)
            last = date.fromisoformat(args.date_to)
        else:
            lookback = args.days or aggregates.DEFAULT_LOOKBACK_DAYS
            from datetime import timedelta
            last = last_day
            first = last - timedelta(days=max(0, lookback - 1))

        storable = [m.key for m in aggregates.storable_metrics()]
        logger.info(
            "reporting timezone=%s last_completed_day=%s range=%s..%s metrics=%d",
            platform_tz(), last_day, first, last, len(storable),
        )

        if args.dry_run:
            days = (last - first).days + 1
            space_count = len(list(db.execute(aggregates._all_space_ids())))
            per_space = [
                m.key for m in aggregates.storable_metrics()
                if "space_id" in m.dimensions
            ]
            logger.info(
                "DRY RUN — would rebuild %d day(s): %d platform rows/day plus "
                "%d Collective(s) x %d metric(s). Nothing written.",
                days, len(storable), space_count, len(per_space),
            )
            logger.info("storable metrics: %s", ", ".join(sorted(storable)))
            return 0

        space_ids = [r[0] for r in db.execute(aggregates._all_space_ids())]
        result = aggregates.rebuild_range(db, first, last, space_ids=space_ids)
        if result.failed:
            logger.error("rebuild FAILED: %s", result.error)
            return 1
        logger.info(
            "rebuild ok: run=%s days=%d rows=%d",
            result.job_run_id, len(result.days), result.rows_written,
        )
        skipped = [s for d in result.days for s in d.skipped]
        if skipped:
            # Not a failure. A metric that is unavailable for a day is a
            # fact about the data, and it is recorded on the run.
            logger.info("skipped (unavailable or errored): %s", "; ".join(skipped[:20]))
        return 0
    except Exception:
        # Reported AND non-zero. A fatal error that logs and returns 0
        # leaves Render believing the night went fine, which is the one
        # outcome worse than a failed cron.
        logger.exception("reporting rebuild: fatal")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    # The flush sits in a ``finally`` so it runs on the failure path too,
    # which is the path whose event matters most. It is bounded and
    # swallows its own errors, so it cannot change the exit code — a
    # Sentry outage must never turn a good run into a failed cron.
    try:
        raise SystemExit(main())
    finally:
        flush_sentry()
