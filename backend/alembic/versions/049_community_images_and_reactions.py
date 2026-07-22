"""Add image_url to posts/comments, add post_reactions and comment_reactions tables

Revision ID: 049
Revises: 048
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # image_url on community_posts
    op.add_column(
        "community_posts",
        sa.Column("image_url", sa.String(500), nullable=True),
    )

    # image_url on post_comments
    op.add_column(
        "post_comments",
        sa.Column("image_url", sa.String(500), nullable=True),
    )

    # post_reactions
    op.create_table(
        "post_reactions",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("post_id", sa.String(), sa.ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("emoji", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("post_id", "user_id", "emoji", name="uq_post_reaction"),
    )

    # comment_reactions
    op.create_table(
        "comment_reactions",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("comment_id", sa.String(), sa.ForeignKey("post_comments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("emoji", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("comment_id", "user_id", "emoji", name="uq_comment_reaction"),
    )


def downgrade() -> None:
    op.drop_table("comment_reactions")
    op.drop_table("post_reactions")
    op.drop_column("post_comments", "image_url")
    op.drop_column("community_posts", "image_url")
