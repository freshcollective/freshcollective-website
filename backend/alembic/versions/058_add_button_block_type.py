"""Add 'button' to step_block_type_enum

Revision ID: 058
Revises: 057
Create Date: 2026-06-21

Adds a new block type for call-to-action buttons inside pathway step
content and pathway about pages. Style and new-tab behaviour are stored
in existing columns — see model docstring on PathwayStepBlock.
"""

from alembic import op


revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE step_block_type_enum ADD VALUE IF NOT EXISTS 'button'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values. See migration 057
    # for the same rationale.
    pass
