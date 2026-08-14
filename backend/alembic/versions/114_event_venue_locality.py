"""Add an explicit member-safe ``venue_locality`` to Events.

Revision ID: 114
Revises: 113
Create Date: 2026-08-14

M1 (member Gatherings) introduced a runtime helper that split
``venue_address`` on commas and dropped digit-prefixed segments to
guess a member-safe locality. Browser review flagged that as too
fragile to serve as a privacy boundary — a Creator writing
``Unit 3, 42 Main Street, South Croydon, VIC`` would still leak
"Unit 3" and "Main Street" through the heuristic.

Fix: give the Creator an explicit, Creator-controlled field for the
member-safe "general location" (suburb + region). The full
``venue_address`` continues to hold the private street address
and remains attendee-gated on the endpoint response.

Backfill policy — deliberately conservative:
  * Only copy the existing ``venue_address`` into the new column
    when it is *unquestionably* safe: a single letter-led segment,
    or two comma-separated letter-led segments (``"South Croydon,
    VIC"`` shape). Everything else is left NULL — the Creator can
    fill it in once via Creator Studio.
  * Never copies an address that contains digits (street numbers /
    unit lines). Even conservative on multi-segment inputs — if a
    third segment exists (e.g. ``"Studio, South Croydon, VIC"``)
    the whole value is left for the Creator to review.

Downgrade drops the column.
"""

from alembic import op
import sqlalchemy as sa


revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("venue_locality", sa.String(160), nullable=True),
    )
    # Conservative backfill — see docstring.
    op.execute(
        """
        UPDATE events
           SET venue_locality = TRIM(venue_address)
         WHERE venue_locality IS NULL
           AND venue_address IS NOT NULL
           AND TRIM(venue_address) <> ''
           AND venue_address !~ '[0-9]'
           AND (
                array_length(string_to_array(venue_address, ','), 1) = 1
             OR array_length(string_to_array(venue_address, ','), 1) = 2
           )
        """
    )


def downgrade() -> None:
    op.drop_column("events", "venue_locality")
