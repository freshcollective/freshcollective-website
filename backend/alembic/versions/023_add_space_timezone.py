"""add timezone to spaces

Revision ID: 023
Revises: 022
Create Date: 2026-05-20

"""
from alembic import op
import sqlalchemy as sa

revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'spaces',
        sa.Column(
            'timezone',
            sa.String(100),
            nullable=False,
            server_default='Australia/Melbourne',
        ),
    )


def downgrade() -> None:
    op.drop_column('spaces', 'timezone')
