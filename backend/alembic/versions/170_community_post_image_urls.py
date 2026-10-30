"""Let a Conversation post carry more than one image.

``community_posts.image_url`` holds a single URL, so sharing several
photographs meant publishing one post and adding the rest as replies.

The smallest extension that supports several without disturbing what
exists: one nullable JSON column beside the old one. No data migration
and no backfill — a post written before this column exists keeps its
``image_url`` and reads back as a one-image post, because every read
path resolves ``image_urls or [image_url]``. New posts write both: the
list, and the first image into ``image_url`` so any surface still
reading the old column is unaffected.

A JSON list rather than a child table because a post carries at most
five URLs, they are always read with the post and never queried on
their own, and ``mentioned_user_ids`` two columns away already stores
a list this way. A table would add a join and a second write path for
no question it could answer better.

Revision ID: 170
Revises: 169
"""
from alembic import op
import sqlalchemy as sa


revision = "170"
down_revision = "169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "community_posts",
        sa.Column("image_urls", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    # Safe: every post's first image is still in ``image_url``, so
    # dropping this column loses the extra images and nothing else.
    op.drop_column("community_posts", "image_urls")
