"""add scope and pathway_id to space_resources

Revision ID: 032
Revises: 031
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa

revision = '032'
down_revision = '031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'space_resources',
        sa.Column('scope', sa.String(20), nullable=False, server_default='general'),
    )
    op.add_column(
        'space_resources',
        sa.Column('pathway_id', sa.String(), nullable=True),
    )
    op.create_foreign_key(
        'fk_space_resources_pathway_id',
        'space_resources', 'pathways',
        ['pathway_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_space_resources_scope_status',
        'space_resources',
        ['space_id', 'scope', 'status'],
    )


def downgrade() -> None:
    op.drop_index('ix_space_resources_scope_status', table_name='space_resources')
    op.drop_constraint('fk_space_resources_pathway_id', 'space_resources', type_='foreignkey')
    op.drop_column('space_resources', 'pathway_id')
    op.drop_column('space_resources', 'scope')
