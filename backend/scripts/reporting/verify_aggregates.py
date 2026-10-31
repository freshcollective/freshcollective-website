"""Check stored daily aggregates against the records they came from.

Recomputes each stored figure for a sample of reporting dates and
compares it with the row in ``metric_daily``. Read-only: it writes
nothing, changes nothing, and touches no financial record.

Findings are program output, not log events
-------------------------------------------
This matters more than it sounds. The first run of this script put
about sixty Sentry issues into the production queue, because every
finding went through ``logger.error`` and the Sentry logging
integration turns ERROR into an event. A diagnostic that reports
problems is *expected* to report problems; routing those findings
through the error channel makes each one an incident, and an
incident queue full of expected output is an incident queue nobody
reads.

So the report goes to stdout. The logging system carries only what an
operator needs in Render's log stream, and ``logger.exception`` is
reserved for the thing that genuinely is an incident: this script
falling over. Nothing about global Sentry behaviour changes — the
distinction is simply drawn in the right place.

The four outcomes, kept apart
-----------------------------
**Mismatch.** A stored figure disagrees with the records it came from.
A real defect, and the only thing that fails the run.

**Gap.** The metric has rows on other dates but none here. Also a real
defect — something was skipped — and also fails the run.

**Never built.** The metric has no stored rows at all, anywhere. Not a
defect: it was added after the last rebuild and has simply never been
loaded. Reported with the command that fixes it, and does not fail the
run unless ``--strict`` says so.

**Skipped.** Observation-only metrics, whose stored row is the only
record that the day was ever seen, so there is nothing to recompute
them against — "verifying" one would mean overwriting it with today's
count. Metrics that are never stored daily are skipped for the same
reason in reverse: there is no row to check.

Usage
-----
    python scripts/reporting/verify_aggregates.py                # 5 dates
    python scripts/reporting/verify_aggregates.py --dates 2026-07-01,2026-09-15
    python scripts/reporting/verify_aggregates.py --samples 10
    python scripts/reporting/verify_aggregates.py --platform-only
    python scripts/reporting/verify_aggregates.py --strict       # fail on never-built
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
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
from app.reporting.scope import platform_scope  # noqa: E402

logger = logging.getLogger("reporting.verify")

REBUILD_HINT = (
    "python scripts/reporting/rebuild_daily.py --from <first> --to <last>"
)


@dataclass
class Findings:
    """Everything the run saw, kept in its own category."""

    checked: int = 0
    skipped_observation: int = 0
    skipped_unstored: int = 0
    mismatches: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    never_built: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def failed(self) -> bool:
        """Only genuine defects fail. A never-built metric is not one."""
        return bool(self.mismatches or self.gaps)


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
    return [lo + timedelta(days=round(span * i / (n - 1))) for i in range(n)]


def _metrics_with_no_rows(db) -> set[str]:
    """Storable metrics that have never been loaded, anywhere.

    The difference between "this was skipped" and "this has not been
    built yet", which the first version of this script could not tell
    apart — it reported four metrics added after the last rebuild as a
    hundred and twenty-five mismatches.
    """
    stored = {
        r[0] for r in db.execute(select(MetricDaily.metric_key).distinct())
    }
    return {m.key for m in aggregates.storable_metrics() if m.key not in stored}


def verify(db, days: list[date], spaces: list[tuple[str, str]]) -> Findings:
    """Compare every stored figure for these dates with its source."""
    found = Findings()
    unloaded = _metrics_with_no_rows(db)

    for day in days:
        targets = [(aggregates.PLATFORM_DIMENSION, platform_scope(), "platform")]
        targets += [
            (aggregates.space_dimension(sid), aggregates._space_scope(sid), name)
            for sid, name in spaces
        ]

        for dimension, scope, label in targets:
            per_space = dimension != aggregates.PLATFORM_DIMENSION
            stored = {
                r.metric_key: r
                for r in db.query(MetricDaily).filter(
                    MetricDaily.reporting_date == day,
                    MetricDaily.dimension == dimension,
                )
            }
            for metric in aggregates.storable_metrics():
                if per_space and "space_id" not in metric.dimensions:
                    continue
                if metric.observation_only:
                    found.skipped_observation += 1
                    continue

                row = stored.get(metric.key)
                value = metric.evaluate(
                    db, scope, aggregates._window_for(metric, day),
                )

                if value.value is None:
                    if row is not None:
                        found.mismatches.append(
                            f"{day}  {label}  {metric.key}: stored "
                            f"{row.value}, but the source records now say "
                            f"nothing can be computed"
                        )
                    continue

                if row is None:
                    if metric.key in unloaded:
                        found.never_built[metric.key] += 1
                    else:
                        found.gaps.append(
                            f"{day}  {label}  {metric.key}: no stored row, "
                            f"source records give {int(value.value)} "
                            f"(this metric has rows on other dates)"
                        )
                    continue

                found.checked += 1
                if int(value.value) != int(row.value):
                    found.mismatches.append(
                        f"{day}  {label}  {metric.key}: stored {row.value}, "
                        f"source records give {int(value.value)}"
                    )
    return found


def report(found: Findings, days: list[date], spaces: int) -> None:
    """Print the findings. Deliberately ``print``, not ``logger``.

    Routing these through logging is what turned a verification run
    into sixty production incidents.
    """
    out = print
    out("")
    out("=" * 68)
    out(f"  Aggregate verification — {len(days)} date(s), "
        f"{spaces} Collective dimension(s) plus platform")
    out("=" * 68)
    out(f"  checked against source records : {found.checked}")
    out(f"  mismatched                     : {len(found.mismatches)}")
    out(f"  missing (gap in a built metric): {len(found.gaps)}")
    out(f"  not yet built                  : {sum(found.never_built.values())}")
    out(f"  skipped, observation-only      : {found.skipped_observation}")
    out("")

    if found.mismatches:
        out(f"  MISMATCHED — a stored figure disagrees with its source "
            f"({len(found.mismatches)}):")
        for line in found.mismatches[:40]:
            out(f"    {line}")
        if len(found.mismatches) > 40:
            out(f"    (+{len(found.mismatches) - 40} more of the same kind)")
        out("")

    if found.gaps:
        out(f"  MISSING — built elsewhere but absent here ({len(found.gaps)}):")
        for line in found.gaps[:40]:
            out(f"    {line}")
        if len(found.gaps) > 40:
            out(f"    (+{len(found.gaps) - 40} more of the same kind)")
        out("")

    if found.never_built:
        total = sum(found.never_built.values())
        out(f"  NOT YET BUILT — {total} figure(s) across "
            f"{len(found.never_built)} metric(s).")
        out("    These have no stored rows anywhere, so they were added")
        out("    after the last rebuild rather than skipped by it. Not a")
        out("    defect; they need loading:")
        for key in sorted(found.never_built):
            out(f"      {key}  ({found.never_built[key]} figure(s) here)")
        out("")
        out(f"    {REBUILD_HINT}")
        out("")

    if found.failed:
        out("  RESULT: FAILED — stored figures disagree with their source.")
    elif found.never_built:
        out("  RESULT: OK — every stored figure matches. Some metrics are")
        out("          not built yet; see above.")
    else:
        out("  RESULT: OK — every stored figure matches its source records.")
    out("=" * 68)
    out("")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", type=str, default=None,
                        help="Comma-separated ISO dates. Overrides --samples.")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--platform-only", action="store_true",
                        help="Skip the per-Collective dimensions.")
    parser.add_argument("--strict", action="store_true",
                        help="Also fail when a metric has never been built.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dates:
            days = [date.fromisoformat(d.strip()) for d in args.dates.split(",")]
        else:
            days = _sample_dates(db, args.samples)
        if not days:
            logger.warning("No stored aggregates to verify.")
            return 2

        spaces = [] if args.platform_only else [
            (s.id, s.name) for s in db.query(Space).order_by(Space.created_at).all()
        ]
        logger.info(
            "verifying %d date(s) across %d Collective dimension(s) plus platform",
            len(days), len(spaces),
        )

        found = verify(db, days, spaces)
        report(found, days, len(spaces))

        if found.failed:
            return 1
        if args.strict and found.never_built:
            return 1
        return 0
    except Exception:
        # The one thing here that genuinely is an incident: the check
        # itself fell over, so nothing was verified. This reaches
        # Sentry, and should.
        logger.exception("aggregate verification: fatal")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
