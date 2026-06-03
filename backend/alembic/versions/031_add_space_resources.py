"""add space_resources table

Revision ID: 031
Revises: 030
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa

revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'space_resources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('space_id', sa.String(), nullable=False),
        sa.Column('created_by_id', sa.String(), nullable=True),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(20), nullable=False, server_default='link'),
        sa.Column('url', sa.String(2000), nullable=True),
        sa.Column('file_name', sa.String(300), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_space_resources_space_id', 'space_resources', ['space_id'])
    op.create_index('ix_space_resources_space_status', 'space_resources', ['space_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_space_resources_space_status', 'space_resources')
    op.drop_index('ix_space_resources_space_id', 'space_resources')
    op.drop_table('space_resources')
