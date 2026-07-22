"""Add 'columns' block type

Revision ID: 088
Revises: 087
Create Date: 2026-07-19

Adds a new step block type for a multi-column layout container.
Content lives in the existing ``content`` text column as a JSON
envelope, so no additional columns or tables are needed.
"""

from alembic import op


revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL enums need autocommit for ADD VALUE.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE step_block_type_enum ADD VALUE IF NOT EXISTS 'columns'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values. The new 'columns'
    # value is harmless on downgrade — it just won't be used by app code.
    pass
