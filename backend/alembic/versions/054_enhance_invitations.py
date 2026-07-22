"""Enhance space_invitations with draft status and payment metadata

Revision ID: 054
Revises: 053
Create Date: 2026-06-19
"""

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sent_at NULL = draft (not yet emailed); non-null = email has been sent
    op.execute("""
        ALTER TABLE space_invitations
            ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS payment_option_id VARCHAR
                REFERENCES payment_options(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50)
                NOT NULL DEFAULT 'unpaid'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE space_invitations DROP COLUMN IF EXISTS sent_at")
    op.execute("ALTER TABLE space_invitations DROP COLUMN IF EXISTS payment_option_id")
    op.execute("ALTER TABLE space_invitations DROP COLUMN IF EXISTS payment_status")
