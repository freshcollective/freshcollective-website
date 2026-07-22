"""Locations — location_type (ATLAS | CORNERSTONE)

Revision ID: 067
Revises: 066
Create Date: 2026-07-12

ADDITIVE ONLY.

Adds `location_type` to `locations` so The Atlas can distinguish two
classes of Location:

  ATLAS       — available to creators when they choose a home for their
                collective.
  CORNERSTONE — reserved for Fresh Collective experiences (e.g. The
                Atlas Isles, The Grove). Never surfaced to creators.

All existing Locations default to ATLAS via the server default; no data
is lost. Migrating a Location to CORNERSTONE later is a single PATCH in
the Admin Portal.

No new tables, no permissions system — a simple string enum is enough
for now, per the Atlas v1.2 philosophy of "keep the implementation
simple".
"""

from alembic import op
import sqlalchemy as sa


revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column(
            "location_type",
            sa.String(16),
            nullable=False,
            server_default="ATLAS",
        ),
    )


def downgrade() -> None:
    op.drop_column("locations", "location_type")
