"""Add recurrence fields and public visibility to events

Revision ID: 034
Revises: 033
Create Date: 2026-06-04

"""
from alembic import op
import sqlalchemy as sa

revision = '034'
down_revision = '033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('events', sa.Column('recurrence_series_id', sa.String(36), nullable=True))
    op.add_column('events', sa.Column('recurrence_label', sa.Text(), nullable=True))
    op.add_column('events', sa.Column('recurrence_index', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column('recurrence_total', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'))

    op.create_index('ix_events_recurrence_series', 'events', ['recurrence_series_id'])


def downgrade() -> None:
    op.drop_index('ix_events_recurrence_series', table_name='events')
    op.drop_column('events', 'is_public')
    op.drop_column('events', 'recurrence_total')
    op.drop_column('events', 'recurrence_index')
    op.drop_column('events', 'recurrence_label')
    op.drop_column('events', 'recurrence_series_id')
