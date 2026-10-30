"""Accept 'observed_late' as a metric_daily provenance

Revision ID: 174
Revises: 173
Create Date: 2026-10-30

Migration 172 created ``metric_daily`` with a provenance constraint
listing two values: ``observed`` and ``reconstructed``. Commit 71e6b8a
then introduced observation-only snapshots, whose provenance
distinguishes a figure taken on the day it describes from one taken a
night or two later because a run had been missed — ``observed`` and
``observed_late``. The constraint was not widened with it, so the first
nightly run failed:

    psycopg2.errors.CheckViolation
    ck_metric_daily_provenance
    metric_key=active_collectives reporting_date=2026-10-27
    provenance=observed_late

This widens the constraint to the three values
``app.reporting.registry.Provenance`` declares. The enum is the single
definition; this migration states the same list literally because a
migration is a historical record and must keep meaning what it meant
even after the enum changes again. The two are held together by
``tests/test_reporting_schema_contract.py``, which inserts every enum
member against the real database — the check that was missing.

Constraint only. No row is read, written or deleted, no column changes
type, and nothing financial is touched. Any ``metric_daily`` rows
already stored keep their values; the failed run wrote none of the
rejected rows, because the insert that violated the constraint aborted
its transaction.

The downgrade narrows the constraint again and refuses while any row is
``observed_late``, rather than silently rewriting a figure's provenance
to something it was not.
"""

from alembic import op
import sqlalchemy as sa

revision = "174"
down_revision = "173"
branch_labels = None
depends_on = None

_NEW = "('observed', 'observed_late', 'reconstructed')"
_OLD = "('observed', 'reconstructed')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_metric_daily_provenance", "metric_daily", type_="check",
    )
    op.create_check_constraint(
        "ck_metric_daily_provenance",
        "metric_daily",
        f"provenance IS NULL OR provenance IN {_NEW}",
    )


def downgrade() -> None:
    stuck = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM metric_daily WHERE provenance = 'observed_late'"
        )
    ).scalar()
    if stuck:
        raise RuntimeError(
            f"{stuck} stored figure(s) are marked 'observed_late'. Narrowing "
            "the constraint would mean relabelling them as something they "
            "are not — a late observation is not a timely one, and it is not "
            "reconstructed either. Delete or rebuild those rows first."
        )

    op.drop_constraint(
        "ck_metric_daily_provenance", "metric_daily", type_="check",
    )
    op.create_check_constraint(
        "ck_metric_daily_provenance",
        "metric_daily",
        f"provenance IS NULL OR provenance IN {_OLD}",
    )
