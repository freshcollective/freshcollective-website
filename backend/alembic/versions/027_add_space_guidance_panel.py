"""Add creator-managed guidance panel fields to spaces.

Six nullable text columns that power the Important sidebar panel shown on
member-facing collective pages (Community, Members). Nullable so existing
collectives continue to work without migration-time data entry.

Revision ID: 027
Revises: 026
Create Date: 2026-05-21
"""

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE spaces
        ADD COLUMN IF NOT EXISTS guidance_start_title TEXT,
        ADD COLUMN IF NOT EXISTS guidance_start_body  TEXT,
        ADD COLUMN IF NOT EXISTS guidance_focus_title TEXT,
        ADD COLUMN IF NOT EXISTS guidance_focus_body  TEXT,
        ADD COLUMN IF NOT EXISTS guidance_links_title TEXT,
        ADD COLUMN IF NOT EXISTS guidance_links_body  TEXT;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE spaces
        DROP COLUMN IF EXISTS guidance_start_title,
        DROP COLUMN IF EXISTS guidance_start_body,
        DROP COLUMN IF EXISTS guidance_focus_title,
        DROP COLUMN IF EXISTS guidance_focus_body,
        DROP COLUMN IF EXISTS guidance_links_title,
        DROP COLUMN IF EXISTS guidance_links_body;
    """)
