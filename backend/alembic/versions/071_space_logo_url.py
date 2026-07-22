"""Optional collective logo — a subtle "hosted by" mark.

Revision ID: 071
Revises: 070
Create Date: 2026-07-14

ADDITIVE ONLY.

Adds `spaces.logo_url` — an optional URL for a small collective logo
shown beside the collective name in the header. The Location artwork
remains the primary visual identity; the logo is intentionally subtle.
"""

from alembic import op
import sqlalchemy as sa


revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("logo_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spaces", "logo_url")
