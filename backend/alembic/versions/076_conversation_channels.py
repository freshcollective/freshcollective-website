"""Conversations → Channels.

Revision ID: 076
Revises: 075
Create Date: 2026-07-15

ADDITIVE + BACKFILL.

Introduces the Channel architecture. Every Conversation post now belongs
to a Channel; every existing collective gets one default `General`
Channel and every existing post is retrofitted into it.

New tables
----------

conversation_channels
    One row per Channel per collective. `channel_type` is a
    discriminator; the columns that follow only apply to certain types
    (pathway_id for pathway/intake, gathering_id for future gathering-
    linked Channels). `is_default=True` marks a collective's General
    Channel and is enforced unique per space.

channel_memberships
    Presence of a row grants a user access to a private Channel. Not
    used for open/pathway/intake Channels — those derive access from
    space membership or pathway enrolment.

Backfill
--------

For each `spaces` row (any status) we insert a General Channel with:

    channel_type          = 'open'
    is_default            = True
    slug                  = 'general'
    name                  = 'General'
    member_posting_allowed = True
    comments_allowed       = True
    polls_allowed          = True
    scheduling_allowed     = True
    show_in_navigation     = True

Then every `community_posts.channel_id` is set to that space's General.
Once the backfill completes, `channel_id` becomes NOT NULL — the schema
guarantees every future post is anchored to a Channel.

Rollback
--------

`downgrade()` drops the FK + column from community_posts, then drops
both new tables. It does NOT try to restore pre-migration state on
community_posts beyond dropping the pointer; the post rows themselves
are untouched throughout.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_channels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("space_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon_emoji", sa.String(length=8), nullable=True),
        # 'open' | 'private' | 'pathway' | 'intake' | 'gathering'
        # `intake` and `gathering` are accepted in the schema so future
        # features slot in without another migration; access-logic
        # implementation for those two is deferred.
        sa.Column("channel_type", sa.String(length=16), nullable=False,
                  server_default="open"),
        sa.Column("is_default", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("is_archived", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("archived_by", sa.String(), nullable=True),
        sa.Column("show_in_navigation", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("position", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("member_posting_allowed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("comments_allowed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("polls_allowed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("scheduling_allowed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        # Optional links to other primary entities. Nullable so the
        # single table cleanly holds every access model.
        sa.Column("pathway_id", sa.String(), nullable=True),
        sa.Column("gathering_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["archived_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pathway_id"], ["pathways.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("space_id", "slug", name="uq_conversation_channels_space_slug"),
    )
    op.create_index("ix_conversation_channels_space", "conversation_channels", ["space_id"])
    # Only one default Channel per space — Postgres partial unique index.
    op.execute(
        "CREATE UNIQUE INDEX ix_conversation_channels_space_default "
        "ON conversation_channels (space_id) WHERE is_default = true"
    )
    op.create_index("ix_conversation_channels_pathway", "conversation_channels",
                    ["pathway_id"])

    op.create_table(
        "channel_memberships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        # 'member' | 'moderator' — moderator flag reserved; current
        # code treats space creators/moderators as caretakers regardless.
        sa.Column("role", sa.String(length=16), nullable=False,
                  server_default="member"),
        # 'manual' | 'pathway' | 'intake' | 'admin'
        sa.Column("source", sa.String(length=16), nullable=False,
                  server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["conversation_channels.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_channel_memberships"),
    )
    op.create_index("ix_channel_memberships_user", "channel_memberships", ["user_id"])

    op.add_column(
        "community_posts",
        sa.Column("channel_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_community_posts_channel", "community_posts",
        "conversation_channels", ["channel_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_community_posts_channel", "community_posts", ["channel_id"])

    # ------------------------------------------------------------------
    # Backfill: create a General Channel per space, then assign posts.
    # Using raw SQL because ORM models aren't available inside Alembic.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO conversation_channels
            (id, space_id, name, slug, channel_type, is_default,
             show_in_navigation, position, member_posting_allowed,
             comments_allowed, polls_allowed, scheduling_allowed,
             created_at, updated_at)
        SELECT
            'gen-' || s.id, s.id, 'General', 'general', 'open', true,
            true, 0, true, true, true, true,
            NOW(), NOW()
        FROM spaces s
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE community_posts p
        SET channel_id = c.id
        FROM conversation_channels c
        WHERE p.space_id = c.space_id
          AND c.is_default = true
          AND p.channel_id IS NULL
        """
    )

    # Enforce the invariant now that every row has a channel.
    op.alter_column("community_posts", "channel_id", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_community_posts_channel", table_name="community_posts")
    op.drop_constraint("fk_community_posts_channel", "community_posts", type_="foreignkey")
    op.drop_column("community_posts", "channel_id")

    op.drop_index("ix_channel_memberships_user", table_name="channel_memberships")
    op.drop_table("channel_memberships")

    op.drop_index("ix_conversation_channels_pathway", table_name="conversation_channels")
    op.execute("DROP INDEX IF EXISTS ix_conversation_channels_space_default")
    op.drop_index("ix_conversation_channels_space", table_name="conversation_channels")
    op.drop_table("conversation_channels")
