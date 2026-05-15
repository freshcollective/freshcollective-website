"""Add pricing and practice fields to pathways

Revision ID: 011
Revises: 010
Create Date: 2026-05-15
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE pathways
            ADD COLUMN IF NOT EXISTS access_type      TEXT NOT NULL DEFAULT 'free',
            ADD COLUMN IF NOT EXISTS price_cents      INTEGER,
            ADD COLUMN IF NOT EXISTS currency         TEXT NOT NULL DEFAULT 'AUD',
            ADD COLUMN IF NOT EXISTS billing_interval TEXT,
            ADD COLUMN IF NOT EXISTS practice_body    TEXT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS practice_body")
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS billing_interval")
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS currency")
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS price_cents")
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS access_type")
