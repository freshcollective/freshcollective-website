"""Channels — system channels + type-driven identity.

Revision ID: 077
Revises: 076
Create Date: 2026-07-15

ADDITIVE + BACKFILL. No data loss.

What changes
------------

1. Adds `is_system` bool column to `conversation_channels` (default false).
   System channels (Start Here, General) cannot be archived, deleted, or
   type-converted. The schema tolerates non-system channels at every
   type — the "system" flag is an application-level guard.

2. Updates every existing General channel to `channel_type='general'`,
   `is_system=true`, `icon_emoji='🌍'`. The default flag remains so
   General stays the "no channel specified" fallback for post creation.

3. Creates a per-space Start Here channel: `channel_type='start_here'`,
   `is_system=true`, `icon_emoji='🌱'`, `slug='start-here'`. Positioned
   before General so it renders first in the member selector.

4. Moves every existing `community_posts.is_pinned=true` row into that
   space's Start Here channel. `is_pinned` is preserved on the rows so
   the caretaker's original curation intent stays visible.

Rollback
--------

`downgrade()` moves posts back to their General channel, deletes the
Start Here channel per space, reverts channel_type of General to 'open',
clears is_system, then drops the column. No post data is lost.
"""

from alembic import op
import sqlalchemy as sa


revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add is_system column.
    op.add_column(
        "conversation_channels",
        sa.Column(
            "is_system", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_conversation_channels_system", "conversation_channels", ["is_system"]
    )

    # 2. Reclassify existing General channels as system + typed 'general'.
    op.execute(
        """
        UPDATE conversation_channels
        SET
            channel_type = 'general',
            is_system    = true,
            icon_emoji   = COALESCE(icon_emoji, '🌍')
        WHERE is_default = true
        """
    )

    # 3. Create a Start Here channel per space (skip spaces that
    #    already have one from an earlier partial run).
    op.execute(
        """
        INSERT INTO conversation_channels
            (id, space_id, name, slug, channel_type, is_default,
             is_system, icon_emoji, show_in_navigation, position,
             member_posting_allowed, comments_allowed, polls_allowed,
             scheduling_allowed, created_at, updated_at,
             description)
        SELECT
            'sh-' || s.id, s.id, 'Start Here', 'start-here', 'start_here',
            false, true, '🌱', true, -10,
            true, true, false, true, NOW(), NOW(),
            'Welcome, introductions and the little things that help everyone find their feet here.'
        FROM spaces s
        WHERE NOT EXISTS (
            SELECT 1 FROM conversation_channels c
            WHERE c.space_id = s.id
              AND c.channel_type = 'start_here'
        )
        """
    )

    # 4. Move pinned posts into Start Here per space.
    op.execute(
        """
        UPDATE community_posts p
        SET channel_id = sh.id
        FROM conversation_channels sh
        WHERE p.is_pinned = true
          AND sh.space_id = p.space_id
          AND sh.channel_type = 'start_here'
        """
    )


def downgrade() -> None:
    # 4-reverse: move posts back to General.
    op.execute(
        """
        UPDATE community_posts p
        SET channel_id = g.id
        FROM conversation_channels g, conversation_channels sh
        WHERE p.channel_id = sh.id
          AND sh.channel_type = 'start_here'
          AND g.space_id = sh.space_id
          AND g.is_default = true
        """
    )

    # 3-reverse: drop Start Here channels.
    op.execute(
        "DELETE FROM conversation_channels WHERE channel_type = 'start_here'"
    )

    # 2-reverse: General → 'open' again.
    op.execute(
        """
        UPDATE conversation_channels
        SET channel_type = 'open', is_system = false
        WHERE is_default = true
        """
    )

    # 1-reverse: drop the column.
    op.drop_index(
        "ix_conversation_channels_system", table_name="conversation_channels"
    )
    op.drop_column("conversation_channels", "is_system")
