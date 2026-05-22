"""Add themes column to spaces table.

themes is a JSONB array of controlled theme strings chosen by the creator.
Existing collectives are backfilled with sensible defaults.

Revision ID: 026
Revises: 025
Create Date: 2026-05-20
"""

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE spaces
        ADD COLUMN IF NOT EXISTS themes JSONB NOT NULL DEFAULT '[]'::jsonb;
    """)

    # Backfill existing collectives
    op.execute("""
        UPDATE spaces
        SET themes = '["Inner Work","Leadership","Reflection"]'::jsonb
        WHERE slug = 'the-natural-leader-hub';
    """)
    op.execute("""
        UPDATE spaces
        SET themes = '["Movement","Wellbeing","Inner Work"]'::jsonb
        WHERE slug = 'embody';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE spaces DROP COLUMN IF EXISTS themes;")
