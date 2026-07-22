"""Platform Artwork — a small, named collection of shared interface assets.

Revision ID: 070
Revises: 069
Create Date: 2026-07-14

ADDITIVE ONLY.

Introduces the `platform_artwork` table for artwork owned by the
platform itself — the "Explore Collectives" dashboard tile, the
"Creator Studio" dashboard tile, and any future shared interface
images. Distinct from Location artwork, which belongs to Atlas
Locations.

Schema is intentionally simple: one row per stable artwork key,
holding the hero image URL and an auto-generated thumbnail URL.
New artwork keys are added by writing a row; no schema change is
required to add a new kind of platform artwork.
"""

from alembic import op
import sqlalchemy as sa


revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_artwork",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_artwork")
