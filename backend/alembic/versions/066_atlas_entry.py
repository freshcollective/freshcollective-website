"""Locations — atlas_entry rich text column

Revision ID: 066
Revises: 065
Create Date: 2026-07-10

ADDITIVE ONLY.

Adds `atlas_entry` to the `locations` table — the multi-paragraph "story
of the Location" that admins compose in the Admin Portal (Atlas Volume I,
v1.1). Separate from `description`, which stays as the concise summary
used throughout the platform wherever a short reading is needed.

The classification columns (biome, archipelago, preferred_atmospheres,
preferred_colour_stories, preferred_themes) are kept in the schema for
data safety. The Admin UI no longer exposes them; if recommendation
metadata is required in the future, it will live somewhere else.
"""

from alembic import op
import sqlalchemy as sa


revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("atlas_entry", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "atlas_entry")
