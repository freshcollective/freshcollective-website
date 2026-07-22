"""Community Phase 1 — expand post types, add @mentions, add threaded replies.

Revision ID: 072
Revises: 071
Create Date: 2026-07-14

ADDITIVE ONLY.

- Adds four new values to the `post_type_enum` — `poll`, `question`,
  `celebration`, `share`. Existing values stay valid.
- Adds `community_posts.mentioned_user_ids` (JSON list of user IDs).
- Adds `post_comments.mentioned_user_ids` (JSON list of user IDs).
- Adds `post_comments.parent_comment_id` (nullable self-FK) so a comment
  can mark itself as a reply to another comment; drives the "reply to
  your comment" notification without introducing deep visual nesting.
"""

from alembic import op
import sqlalchemy as sa


revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

_NEW_ENUM_VALUES = ("poll", "question", "celebration", "share")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction on
    # Postgres, so run each in its own autocommit block.
    with op.get_context().autocommit_block():
        for value in _NEW_ENUM_VALUES:
            op.execute(f"ALTER TYPE post_type_enum ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column(
        "community_posts",
        sa.Column(
            "mentioned_user_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "post_comments",
        sa.Column(
            "mentioned_user_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "post_comments",
        sa.Column(
            "parent_comment_id",
            sa.String(),
            sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_post_comments_parent",
        "post_comments",
        ["parent_comment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_comments_parent", table_name="post_comments")
    op.drop_column("post_comments", "parent_comment_id")
    op.drop_column("post_comments", "mentioned_user_ids")
    op.drop_column("community_posts", "mentioned_user_ids")
    # Enum-value removal in Postgres is unsafe; leave the added values
    # in place (they don't hurt existing data).
