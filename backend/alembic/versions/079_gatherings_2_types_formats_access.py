"""Gatherings 2.0 — types, attendance formats, venues, access vocabulary.

Revision ID: 079
Revises: 078
Create Date: 2026-07-15

ADDITIVE + BACKFILL. No data loss. Existing bookings, entitlements,
recurring series, gathering Channels and iCal URLs continue to work.

New columns on `events`
-----------------------

  gathering_type       varchar(32) NOT NULL default 'other'
  attendance_format    varchar(16) NOT NULL default 'online'
  venue_name           varchar(200) NULL
  venue_address        text         NULL
  access_instructions  text         NULL

Rename in vocabulary (data-only rewrite, column name unchanged)
---------------------------------------------------------------

  booking_access_type: 'all_members'      → 'included_with_collective'
                       'pathway_required' → 'included_with_pathway'

`booking_access_type` stays as the column name so downstream code
doesn't need to be touched in the same migration. The application
layer normalises through `services.gathering_types.normalise_access_type`.

Backfill of attendance_format from legacy `location_type`
---------------------------------------------------------

  'in_person'      → 'in_person'
  'zoom'           → 'online'
  'async_recorded' → 'online'   (Type will read 'live_online' or 'other')

Everything is reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add columns.
    op.add_column(
        "events",
        sa.Column("gathering_type", sa.String(length=32),
                  nullable=False, server_default="other"),
    )
    op.add_column(
        "events",
        sa.Column("attendance_format", sa.String(length=16),
                  nullable=False, server_default="online"),
    )
    op.add_column(
        "events",
        sa.Column("venue_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("venue_address", sa.Text(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("access_instructions", sa.Text(), nullable=True),
    )

    # 2. Backfill attendance_format from the existing location_type
    #    enum. Older rows carry sensible defaults thanks to the
    #    server_default above; this pass makes in-person events
    #    accurate immediately.
    op.execute(
        """
        UPDATE events
        SET attendance_format = 'in_person'
        WHERE location_type = 'in_person'
        """
    )

    # 3. Widen booking_access_type — legacy column was varchar(20)
    #    which can't hold 'included_with_collective' (24 chars).
    op.alter_column(
        "events", "booking_access_type",
        type_=sa.String(length=32),
        existing_type=sa.String(length=20),
        existing_nullable=True,
    )

    # 4. Rewrite booking_access_type vocabulary. Old rows use
    #    'all_members' and 'pathway_required'; new code uses the
    #    Access Type set. Column name unchanged.
    op.execute(
        """
        UPDATE events
        SET booking_access_type = 'included_with_collective'
        WHERE booking_access_type = 'all_members' OR booking_access_type IS NULL
        """
    )
    op.execute(
        """
        UPDATE events
        SET booking_access_type = 'included_with_pathway'
        WHERE booking_access_type = 'pathway_required'
        """
    )


def downgrade() -> None:
    # Reverse the access vocabulary rewrite.
    op.execute(
        """
        UPDATE events
        SET booking_access_type = 'pathway_required'
        WHERE booking_access_type = 'included_with_pathway'
        """
    )
    op.execute(
        """
        UPDATE events
        SET booking_access_type = 'all_members'
        WHERE booking_access_type = 'included_with_collective'
        """
    )

    op.alter_column(
        "events", "booking_access_type",
        type_=sa.String(length=20),
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )

    op.drop_column("events", "access_instructions")
    op.drop_column("events", "venue_address")
    op.drop_column("events", "venue_name")
    op.drop_column("events", "attendance_format")
    op.drop_column("events", "gathering_type")
