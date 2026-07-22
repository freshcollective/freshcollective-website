"""Add banner_image_url to pathway_sections and pathway_steps

Revision ID: 059
Revises: 058
Create Date: 2026-06-21

Optional banner image per section + per step. Nullable so all existing
sections/steps render exactly as before. Resolved URL only (Media Library
or external https URL); validation lives in the API layer.
"""

from alembic import op
import sqlalchemy as sa


revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pathway_sections",
        sa.Column("banner_image_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "pathway_steps",
        sa.Column("banner_image_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pathway_steps", "banner_image_url")
    op.drop_column("pathway_sections", "banner_image_url")
