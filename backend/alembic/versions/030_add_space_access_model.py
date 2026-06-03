"""add space access model fields

Revision ID: 030
Revises: 029
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa

revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('spaces', sa.Column(
        'has_paid_internal_content',
        sa.Boolean(),
        nullable=False,
        server_default='false',
    ))
    op.add_column('spaces', sa.Column(
        'included_access_summary',
        sa.String(300),
        nullable=True,
    ))
    op.add_column('spaces', sa.Column(
        'paid_content_summary',
        sa.String(300),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('spaces', 'paid_content_summary')
    op.drop_column('spaces', 'included_access_summary')
    op.drop_column('spaces', 'has_paid_internal_content')
