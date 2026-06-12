"""fix users updated_at default

Revision ID: 046
Revises: 045
Create Date: 2026-06-12
"""
from alembic import op

revision = '046'
down_revision = '045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN updated_at DROP DEFAULT")
