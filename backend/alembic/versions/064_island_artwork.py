"""Island artwork — url, status, prompt, version, generated_at on Space

Revision ID: 064
Revises: 063
Create Date: 2026-07-10

ADDITIVE ONLY.

Adds the five fields the Build Your Place experience needs to swap the
procedural SVG fallback for an uploaded or externally-generated island
artwork per collective:

  island_artwork_url             (nullable) — public URL of the artwork
  island_artwork_status          — 'not_started' | 'generating' | 'ready' | 'failed'
  island_artwork_prompt          (nullable) — the structured prompt used
  island_artwork_version         — bumps every time a new artwork is uploaded
  island_artwork_generated_at    (nullable) — timestamp of latest ready artwork

The procedural SVG remains the fallback whenever status != 'ready'.
"""

from alembic import op
import sqlalchemy as sa


revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spaces", sa.Column("island_artwork_url", sa.String(500), nullable=True))
    op.add_column(
        "spaces",
        sa.Column(
            "island_artwork_status",
            sa.String(24),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column("spaces", sa.Column("island_artwork_prompt", sa.Text(), nullable=True))
    op.add_column(
        "spaces",
        sa.Column(
            "island_artwork_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "spaces",
        sa.Column("island_artwork_generated_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spaces", "island_artwork_generated_at")
    op.drop_column("spaces", "island_artwork_version")
    op.drop_column("spaces", "island_artwork_prompt")
    op.drop_column("spaces", "island_artwork_status")
    op.drop_column("spaces", "island_artwork_url")
