"""add profile_tagline to creator_profiles

Revision ID: 024
Revises: 023
Create Date: 2026-05-20

"""
from alembic import op
import sqlalchemy as sa

revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'creator_profiles',
        sa.Column('profile_tagline', sa.String(150), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('creator_profiles', 'profile_tagline')
