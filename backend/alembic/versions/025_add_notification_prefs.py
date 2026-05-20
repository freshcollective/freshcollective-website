"""add space_member_notification_prefs table

Revision ID: 025
Revises: 024
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'space_member_notification_prefs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('space_id', sa.String(), nullable=False),
        # Email preferences
        sa.Column('weekly_digest_email',      sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('daily_digest_email',       sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('admin_broadcast_email',    sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('gathering_reminder_email', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('new_post_email',           sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('comment_reply_email',      sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('pathway_comment_email',    sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('new_pathway_email',        sa.Boolean(), nullable=False, server_default='true'),
        # Push preferences (TODO: wire up delivery when push system is implemented)
        sa.Column('push_enabled',             sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('push_gathering_reminders', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('push_replies',             sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('push_announcements',       sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('updated_at', sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'],  ['users.id'],  ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'space_id', name='notif_prefs_user_space_unique'),
    )
    op.create_index('ix_notif_prefs_user_space', 'space_member_notification_prefs', ['user_id', 'space_id'])


def downgrade() -> None:
    op.drop_index('ix_notif_prefs_user_space', table_name='space_member_notification_prefs')
    op.drop_table('space_member_notification_prefs')
