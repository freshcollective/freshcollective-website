"""Add container_style to pathway_step_blocks and pathway_about_blocks

Revision ID: 060
Revises: 059
Create Date: 2026-06-28

Optional soft-coloured container wrapper for individual content blocks.
Nullable so all existing blocks render exactly as before. Values are one
of the palette keys (teal | gold | blue | rose | sage | grey | lilac |
orange); NULL means no container. Validation lives in the API layer.
"""

from alembic import op
import sqlalchemy as sa


revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pathway_step_blocks",
        sa.Column("container_style", sa.String(32), nullable=True),
    )
    op.add_column(
        "pathway_about_blocks",
        sa.Column("container_style", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pathway_about_blocks", "container_style")
    op.drop_column("pathway_step_blocks", "container_style")
