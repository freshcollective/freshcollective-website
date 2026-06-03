"""add space pricing fields

Revision ID: 029
Revises: 028
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa

revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pricing_type: free | paid_one_time | paid_monthly | paid_annual | invite_only | coming_soon
    op.add_column('spaces', sa.Column(
        'pricing_type',
        sa.String(20),
        nullable=False,
        server_default='free',
    ))
    # Amount in cents (e.g. 4900 = $49.00)
    op.add_column('spaces', sa.Column(
        'pricing_amount_cents',
        sa.Integer,
        nullable=True,
    ))
    op.add_column('spaces', sa.Column(
        'pricing_currency',
        sa.String(10),
        nullable=False,
        server_default='AUD',
    ))
    op.add_column('spaces', sa.Column(
        'pricing_note',
        sa.String(300),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('spaces', 'pricing_note')
    op.drop_column('spaces', 'pricing_currency')
    op.drop_column('spaces', 'pricing_amount_cents')
    op.drop_column('spaces', 'pricing_type')
