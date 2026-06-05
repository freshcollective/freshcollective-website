"""Add about_content to spaces

Revision ID: 038
Revises: 037
Create Date: 2026-06-04
"""
from alembic import op

revision = '038'
down_revision = '037'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE spaces ADD COLUMN about_content TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE spaces DROP COLUMN about_content")
