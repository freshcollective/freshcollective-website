"""Community Phase 2 — scheduled posts.

Revision ID: 074
Revises: 073
Create Date: 2026-07-14

ADDITIVE ONLY.

Extends `community_posts` with the minimum needed for reliable
server-side scheduling:

  publication_status         'published' | 'scheduled'
  scheduled_for              nullable timestamp (when to publish)
  scheduling_timezone        display timezone the creator chose
  published_at               timestamp the post actually went live
  notifications_processed_at idempotency marker so publication
                             notifications fire exactly once

Existing rows are backfilled as `published`, with `published_at` and
`notifications_processed_at` set to `created_at` — legacy posts had
already fired their notifications, and the marker prevents the
publisher loop from re-firing them.

`scheduled_for` gets an index so the publisher's periodic scan of
"posts due to publish" stays cheap even as history grows.
"""

from alembic import op
import sqlalchemy as sa


revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "community_posts",
        sa.Column(
            "publication_status",
            sa.String(length=16),
            nullable=False,
            server_default="published",
        ),
    )
    op.add_column(
        "community_posts",
        sa.Column("scheduled_for", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column("scheduling_timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column(
            "notifications_processed_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )

    # Backfill: every pre-existing post is already live and has already
    # notified its recipients (or was created before notifications
    # existed). Mark both timestamps so the publisher never re-processes.
    op.execute(
        "UPDATE community_posts "
        "SET published_at = created_at, "
        "    notifications_processed_at = created_at "
        "WHERE published_at IS NULL"
    )

    op.create_index(
        "ix_community_posts_scheduled_for",
        "community_posts",
        ["scheduled_for"],
    )
    # Composite index so the publisher's "find due posts" scan can hit
    # the smallest possible index range.
    op.create_index(
        "ix_community_posts_status_scheduled",
        "community_posts",
        ["publication_status", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_community_posts_status_scheduled", table_name="community_posts")
    op.drop_index("ix_community_posts_scheduled_for", table_name="community_posts")
    op.drop_column("community_posts", "notifications_processed_at")
    op.drop_column("community_posts", "published_at")
    op.drop_column("community_posts", "scheduling_timezone")
    op.drop_column("community_posts", "scheduled_for")
    op.drop_column("community_posts", "publication_status")
