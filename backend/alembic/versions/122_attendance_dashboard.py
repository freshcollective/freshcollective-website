"""Attendance dashboard — auto-vs-manual absence + gathering completion.

Revision ID: 122
Revises: 121
Create Date: 2026-09-07

Extends the existing per-booking attendance columns
(``EventBooking.attendance_status`` / ``attendance_marked_at`` /
``attendance_marked_by`` from an earlier revision) with the two things
the new Creator Studio attendance dashboard needs:

  1. ``event_bookings.attendance_source VARCHAR(16) NULL`` — provenance
     of an absence. Values: ``manual`` | ``auto``. Only meaningful when
     ``attendance_status = 'no_show'``. On ``Finish`` we mark remaining
     unresolved bookings as ``no_show`` with ``source='auto'``; on
     ``Reopen`` only those auto rows revert to booked, so manual
     absences and check-ins are preserved across a finish/reopen
     round-trip. Column is NULLable and existing rows stay NULL
     (treated as ``manual`` at the service layer — the only path that
     could have set ``no_show`` before this revision was a human
     PATCH).

  2. ``events.attendance_completed_at TIMESTAMPTZ NULL`` — the moment
     the creator finalised the gathering's attendance. Presence of a
     non-NULL value flips the gathering into "completed" state:
     further per-booking PATCH mutations return 409 with an instruction
     to reopen. Reopen clears this column back to NULL.

  3. ``events.attendance_completed_by VARCHAR(36) NULL`` — user id of
     the acting host. Not a FK (matches ``attendance_marked_by`` on
     ``event_bookings``, which also stores the id without a FK
     constraint) — keeps this migration additive-only and avoids a
     rebuild on the ``users`` table.

Deployment notes:

  * Purely additive: three nullable columns, no index changes, no
    backfill, no data migration. Safe under the fc-api
    ``preDeployCommand: alembic upgrade head`` path with zero downtime.

  * Downgrade drops the three columns cleanly. Attendance data on
    ``event_bookings`` (status/marked_at/marked_by) is untouched by
    both upgrade and downgrade — those columns predate this revision.

  * The completion-state columns intentionally live on ``events`` (not
    a separate ``event_attendance_snapshots`` table) because the app
    computes summary numbers live from booking rows on every load; the
    ``completed_at`` column is the only piece of state a snapshot table
    would carry that ``events`` doesn't already, and a two-row model
    with only one column of new data is not worth the join cost.

Related decisions locked in this revision:

  * DB vocabulary stays ``attended`` / ``no_show`` / NULL for
    backwards compatibility with the two existing frontend callers
    (``EventManagePanel``, ``CreatorStudioLiteMobile``). The dashboard
    API surfaces ``attended`` / ``absent`` / ``booked``; a translation
    layer in the route accepts both vocabularies on write and always
    returns the DB values on read.
"""

from alembic import op
import sqlalchemy as sa


revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- event_bookings.attendance_source ----
    op.add_column(
        "event_bookings",
        sa.Column(
            "attendance_source",
            sa.String(length=16),
            nullable=True,
        ),
    )

    # ---- events.attendance_completed_at / attendance_completed_by ----
    op.add_column(
        "events",
        sa.Column(
            "attendance_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "attendance_completed_by",
            sa.String(length=36),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "attendance_completed_by")
    op.drop_column("events", "attendance_completed_at")
    op.drop_column("event_bookings", "attendance_source")
