"""Add onboarding fields to users table

Revision ID: 008
Revises: 007
Create Date: 2026-05-11
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS interests TEXT
    """)

    # All existing users pre-date the onboarding feature — mark them complete
    # so they are not forced through the flow on next login.
    op.execute("""
        UPDATE users
        SET onboarding_completed_at = NOW()
        WHERE onboarding_completed_at IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS onboarding_completed_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS interests")
