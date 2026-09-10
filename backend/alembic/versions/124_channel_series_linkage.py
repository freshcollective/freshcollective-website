"""Add ``series_id`` linkage to ``conversation_channels`` for
series-scoped Conversation Channels.

Revision ID: 124
Revises: 123
Create Date: 2026-09-10

Motivation
----------
Adds a third linkable-entity column alongside the existing
``pathway_id`` and ``gathering_id`` so a Conversation Channel can be
scoped to a specific ``EventSeries`` (e.g. "Term 4 2026"). Access to
the resulting channel is granted by the canonical Series-access rule
(``services.series_access.compute_series_access``): the viewer must
hold an active, not-yet-expired ``AccessPass`` whose
``eligible_series_id`` matches the channel's ``series_id``, plus be
an active ``SpaceMembership`` on the collective. Caretakers bypass.

Column shape
------------
Nullable String FK, matches the ``pathway_id`` column shape (added
by migration 076). ``ON DELETE SET NULL`` so deleting an
``EventSeries`` leaves the Conversation row intact — access simply
becomes "no one" until a caretaker re-links or archives the channel,
mirroring the historical behaviour for a Pathway deletion.

Backfill: none required. Every existing conversation_channels row is
left untouched with ``series_id = NULL``. New Series channels are
created via the existing ``POST /api/creator/spaces/{slug}/channels``
endpoint (extended in this same change to accept ``channel_type =
'series'`` + ``series_id``).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_channels",
        sa.Column("series_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversation_channels_series",
        "conversation_channels",
        "event_series",
        ["series_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversation_channels_series",
        "conversation_channels",
        ["series_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_channels_series",
        table_name="conversation_channels",
    )
    op.drop_constraint(
        "fk_conversation_channels_series",
        "conversation_channels",
        type_="foreignkey",
    )
    op.drop_column("conversation_channels", "series_id")
