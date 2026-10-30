"""Daily reporting aggregates, and a record of the job that builds them.

Why store anything at all
-------------------------
Reporting currently computes every figure live. That is correct and will
stay correct, but a dashboard asking for twelve months of trend lines
would scan the transaction tables twelve times per panel. These two
tables let the common case read a precomputed row while leaving the
transactional tables the only source of truth — nothing here is a second
ledger, and every value is reproducible from the data it came from.

One table, with the aggregation written into it
----------------------------------------------
``metric_daily`` holds additive flows *and* point-in-time snapshots, and
records which kind each row is. Two tables would mean two loaders and two
chances to diverge, which is the lesson of BI-2: the same payment was
attributed to two different months because two endpoints each wrote their
own query. Here the ``aggregation`` column travels with the value, so a
reader cannot mistake an end-of-day membership count for something it may
add up.

Distinct counts are deliberately **not** stored. Thirty daily
unique-member counts do not make a monthly figure — the same person
appears on many days — so those are always recomputed over the window
asked for. Storing them would create a row that looks summable and is
not, which is the single easiest way to publish a confidently wrong
number.

``dimension`` is one string
---------------------------
``'platform'`` or ``'space:<id>'``, never a nullable column. A unique
index over a nullable column treats NULLs as distinct in PostgreSQL, so
the upsert the loader relies on would silently insert duplicates for the
platform-wide rows instead of updating them.

Reporting dates are Australian
------------------------------
``reporting_date`` is a calendar day in the platform timezone, not UTC.
A figure labelled 30 October covers the Australian 30 October, which is
the day the person reading the dashboard means. The loader derives the
UTC bounds through ``app.core.periods.reporting_date_bounds``, which
localises both midnights rather than adding 24 hours — a daylight-saving
day is 23 or 25 hours long.

Revision ID: 172
Revises: 171
"""
from alembic import op
import sqlalchemy as sa


revision = "172"
down_revision = "171"
branch_labels = None
depends_on = None


AGGREGATIONS = ("additive", "snapshot")
PROVENANCES = ("observed", "reconstructed")
JOB_STATUSES = ("running", "succeeded", "failed")


def upgrade() -> None:
    op.create_table(
        "metric_daily",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("metric_key", sa.String(64), nullable=False),
        # A calendar day in the platform timezone. See the module docstring.
        sa.Column("reporting_date", sa.Date(), nullable=False),
        # 'platform' or 'space:<space_id>'. Never nullable — see above.
        sa.Column("dimension", sa.String(80), nullable=False),
        # Copied from the registry at write time, so a reader cannot treat
        # a snapshot as a flow.
        sa.Column("aggregation", sa.String(16), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        # For snapshots reconstructed from current rows rather than from
        # recorded events. NULL for flows, which are always observed.
        sa.Column("provenance", sa.String(16), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The upsert target. Also the read path for a trend line.
    op.create_index(
        "ux_metric_daily_key_date_dim",
        "metric_daily",
        ["metric_key", "reporting_date", "dimension"],
        unique=True,
    )
    op.create_index(
        "ix_metric_daily_date", "metric_daily", ["reporting_date"],
    )
    op.create_index(
        "ix_metric_daily_dim_date", "metric_daily", ["dimension", "reporting_date"],
    )
    op.create_check_constraint(
        "ck_metric_daily_aggregation",
        "metric_daily",
        "aggregation IN ('additive', 'snapshot')",
    )
    op.create_check_constraint(
        "ck_metric_daily_provenance",
        "metric_daily",
        "provenance IS NULL OR provenance IN ('observed', 'reconstructed')",
    )

    op.create_table(
        "reporting_job_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("reporting_date_from", sa.Date(), nullable=True),
        sa.Column("reporting_date_to", sa.Date(), nullable=True),
        sa.Column("days_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        # Short and non-sensitive. A failing run records what went wrong
        # without copying member or payment data into a monitoring table.
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_reporting_job_runs_name_started",
        "reporting_job_runs",
        ["job_name", "started_at"],
    )
    op.create_check_constraint(
        "ck_reporting_job_runs_status",
        "reporting_job_runs",
        "status IN ('running', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    # Safe to drop: every row is derived and can be rebuilt from the
    # transactional tables by re-running the job. Unlike
    # ``business_events``, nothing here is irrecoverable.
    op.drop_index("ix_reporting_job_runs_name_started", table_name="reporting_job_runs")
    op.drop_constraint(
        "ck_reporting_job_runs_status", "reporting_job_runs", type_="check",
    )
    op.drop_table("reporting_job_runs")

    op.drop_constraint("ck_metric_daily_provenance", "metric_daily", type_="check")
    op.drop_constraint("ck_metric_daily_aggregation", "metric_daily", type_="check")
    op.drop_index("ix_metric_daily_dim_date", table_name="metric_daily")
    op.drop_index("ix_metric_daily_date", table_name="metric_daily")
    op.drop_index("ux_metric_daily_key_date_dim", table_name="metric_daily")
    op.drop_table("metric_daily")
