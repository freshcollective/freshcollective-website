"""Channels — rename General → Common Room + 🏡 icon.

Revision ID: 078
Revises: 077
Create Date: 2026-07-15

ADDITIVE / RENAME. No data loss. Reversible.

Terminology refinement. The internal identifiers stay put:

    channel_type = 'general'        (unchanged — used in permission logic)
    slug         = 'general'        (unchanged — external URLs)
    is_default   = true             (unchanged — post routing fallback)

Only the visible surface changes:

    name         'General'  →  'Common Room'
    icon_emoji   '🌍'       →  '🏡'
    description  ⋯          →  'Where everyday conversations naturally unfold.'

The `description` update is defensive: only rewrites rows that still
carry a NULL description, so a caretaker's custom copy isn't clobbered.
"""

from alembic import op


revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE conversation_channels
        SET
            name        = 'Common Room',
            icon_emoji  = '🏡',
            description = COALESCE(description, 'Where everyday conversations naturally unfold.')
        WHERE is_system = true
          AND channel_type = 'general'
          AND name = 'General'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE conversation_channels
        SET
            name       = 'General',
            icon_emoji = '🌍'
        WHERE is_system = true
          AND channel_type = 'general'
          AND name = 'Common Room'
        """
    )
