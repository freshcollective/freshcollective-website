"""Derived reporting rows, and the record of the job that derives them.

Neither table is a source of truth. Every value here is reproducible from
the transactional tables by re-running the loader, which is what makes a
correction a recalculation rather than an edit — and what makes dropping
these tables a recoverable act, unlike ``business_events``.

See ``alembic/versions/172_reporting_aggregates.py`` for why this is one
table with an ``aggregation`` column rather than two tables, and why
distinct counts are deliberately absent.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetricDaily(Base):
    """One metric, one Australian calendar day, one dimension."""

    __tablename__ = "metric_daily"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    #: A key declared in ``app.reporting.registry.REGISTRY``.
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)

    #: A calendar day in the platform timezone, not UTC — a row labelled
    #: 30 October covers the Australian 30 October.
    reporting_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: ``'platform'`` or ``'space:<space_id>'``. One string rather than a
    #: nullable column, because PostgreSQL treats NULLs as distinct in a
    #: unique index and the loader's upsert would then duplicate rather
    #: than update the platform-wide rows.
    dimension: Mapped[str] = mapped_column(String(80), nullable=False)

    #: ``additive`` or ``snapshot``, copied from the registry when the row
    #: is written. Travels with the value so a reader cannot sum an
    #: end-of-day count.
    aggregation: Mapped[str] = mapped_column(String(16), nullable=False)

    value: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: ``observed`` or ``reconstructed``, for snapshots dated before
    #: business-event recording began. NULL for flows.
    provenance: Mapped[str | None] = mapped_column(String(16), nullable=True)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ux_metric_daily_key_date_dim",
            "metric_key", "reporting_date", "dimension",
            unique=True,
        ),
        Index("ix_metric_daily_date", "reporting_date"),
        Index("ix_metric_daily_dim_date", "dimension", "reporting_date"),
        CheckConstraint(
            "aggregation IN ('additive', 'snapshot')",
            name="ck_metric_daily_aggregation",
        ),
        CheckConstraint(
            "provenance IS NULL OR provenance IN ('observed', 'reconstructed')",
            name="ck_metric_daily_provenance",
        ),
    )


class ReportingJobRun(Base):
    """One execution of a reporting job.

    Exists so "is the reporting data fresh, and did last night's rebuild
    actually work" is answerable from World Management rather than from a
    Render Shell. A failed run leaves a row saying so, which is the
    difference between stale data and silently stale data.
    """

    __tablename__ = "reporting_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)

    #: ``running`` while in flight, then ``succeeded`` or ``failed``. A
    #: row left ``running`` means the process died without finishing —
    #: which the health view reports rather than ignoring.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    reporting_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    reporting_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    days_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    rows_written: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )

    #: A short, non-sensitive description. Never member or payment data —
    #: a monitoring table is not a place for either.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_reporting_job_runs_name_started", "job_name", "started_at"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_reporting_job_runs_status",
        ),
    )
