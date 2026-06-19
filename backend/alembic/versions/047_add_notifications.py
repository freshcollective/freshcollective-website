"""add notifications table

Revision ID: 047
Revises: 046
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = '047'
down_revision = '046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('notification_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('url', sa.String(length=1000), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.text('now()')),
        sa.Column('read_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('email_sent_at', sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_user_is_read', 'notifications', ['user_id', 'is_read'])
    op.create_index('ix_notifications_user_created_at', 'notifications', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_notifications_user_created_at', table_name='notifications')
    op.drop_index('ix_notifications_user_is_read', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
