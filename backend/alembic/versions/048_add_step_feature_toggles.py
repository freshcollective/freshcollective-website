"""Add reflection_enabled and discussion_enabled to pathway_steps

Revision ID: 048
Revises: 047
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = '048'
down_revision = '047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'pathway_steps',
        sa.Column('reflection_enabled', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column(
        'pathway_steps',
        sa.Column('discussion_enabled', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade() -> None:
    op.drop_column('pathway_steps', 'discussion_enabled')
    op.drop_column('pathway_steps', 'reflection_enabled')
