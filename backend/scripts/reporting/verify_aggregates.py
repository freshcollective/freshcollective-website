"""Check stored daily aggregates against the records they came from.

Recomputes each stored figure for a sample of reporting dates and
compares it with the row in ``metric_daily``. Read-only: it writes
nothing, changes nothing, and touches no financial record.

What it can and cannot check
----------------------------
**Reconstructable metrics are checked properly.** Membership counts,
money and participation are all derived from rows that carry their own
dates, so recomputing 15 August today gives the same answer the night
of 15 August would have given. A mismatch is a real defect.

**Observation-only metrics are skipped, and that is not a gap in the
check.** A Collective's status is one column with no history behind it,
so there is nothing to recompute a past day against — the stored row is
the only record that the day was ever seen. Verifying it would mean
overwriting it with today's count, which is exactly what the write-once
upsert exists to prevent. They are counted and reported as skipped.

Usage
-----
    python scripts/reporting/verify_aggregates.py                # 5 dates
    python scripts/reporting/verify_aggregates.py --dates 2026-07-01,2026-09-15
    python scripts/reporting/verify_aggregates.py --samples 10
    python scripts/reporting/verify_aggregates.py --platform-only

Exits non-zero if any stored figure disagrees with its source records.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")

import app.main  # noqa: F401,E402  — resolves string-referenced relationships
from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.platform import Space  # noqa: E402
from app.models.reporting_aggregate import MetricDaily  # noqa: E402
from app.reporting import aggregates  # noqa: E402
from app.reporting.registry import REGISTRY  # noqa: E402
from app.reporting.scope import platform_scope  # noqa: E402

logger = logging.getLogger("reporting.verify")


def _sample_dates(db, n: int) -> list[date]:
    """Spread `n` dates across the range that actually has rows."""
    lo, hi = db.execute(
        select(func.min(MetricDaily.reporting_date), func.max(MetricDaily.reporting_date))
    ).one()
    if lo is None:
        return []
    span = (hi - lo).days
    if n <= 1 or span == 0:
        return [hi]
    from datetime import timedelta

    return [lo + timedelta(days=round(span * i / (n - 1))) for i in range(n)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", type=str, default=None,
                        help="Comma-separated ISO dates. Overrides --samples.")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--platform-only", action="store_true",
                        help="Skip the per-Collective dimensions.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dates:
            days = [date.fromisoformat(d.strip()) for d in args.dates.split(",")]
        else:
            days = _sample_dates(db, args.samples)
        if not days:
            logger.error("No stored aggregates to verify.")
            return 2

        spaces = [] if args.platform_only else [
            (s.id, s.name) for s in db.query(Space).order_by(Space.created_at).all()
        ]
        logger.info(
            "verifying %d date(s) across %d Collective dimension(s) plus platform",
            len(days), len(spaces),
        )

        checked = skipped = missing = 0
        mismatches: list[str] = []

        for day in days:
            window = aggregates._window_for(  # noqa: SLF001 — the loader's own window
                next(iter(aggregates.storable_metrics())), day,
            )
            targets = [(aggregates.PLATFORM_DIMENSION, platform_scope(), "platform")]
            targets += [
                (aggregates.space_dimension(sid), aggregates._space_scope(sid), name)
                for sid, name in spaces
            ]

            for dimension, scope, label in targets:
                stored = {
                    r.metric_key: r
                    for r in db.query(MetricDaily).filter(
                        MetricDaily.reporting_date == day,
                        MetricDaily.dimension == dimension,
                    )
                }
                for metric in aggregates.storable_metrics():
                    if dimension != aggregates.PLATFORM_DIMENSION and (
                        "space_id" not in metric.dimensions
                    ):
                        continue
                    row = stored.get(metric.key)
                    if metric.observation_only:
                        skipped += 1
                        continue

                    w = aggregates._window_for(metric, day)  # noqa: SLF001
                    value = metric.evaluate(db, scope, w)
                    if value.value is None:
                        if row is not None:
                            mismatches.append(
                                f"{day} {label} {metric.key}: stored "
                                f"{row.value} but the source records now say "
                                f"nothing can be computed"
                            )
                        continue
                    if row is None:
                        missing += 1
                        mismatches.append(
                            f"{day} {label} {metric.key}: no stored row, "
                            f"source records give {int(value.value)}"
                        )
                        continue
                    checked += 1
                    if int(value.value) != int(row.value):
                        mismatches.append(
                            f"{day} {label} {metric.key}: stored {row.value}, "
                            f"source records give {int(value.value)}"
                        )

        logger.info(
            "checked %d figure(s); %d observation-only skipped; %d missing row(s)",
            checked, skipped, missing,
        )
        if mismatches:
            logger.error("MISMATCHES (%d):", len(mismatches))
            for m in mismatches[:60]:
                logger.error("  %s", m)
            if len(mismatches) > 60:
                logger.error("  ... and %d more", len(mismatches) - 60)
            return 1
        logger.info("OK — every stored figure matches its source records.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
