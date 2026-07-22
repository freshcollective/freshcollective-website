"""Community Phase 1 — Polls schema.

Revision ID: 073
Revises: 072
Create Date: 2026-07-14

ADDITIVE ONLY.

Introduces three tables that make Poll a first-class Community post type:

- `polls`             — one row per Poll post. `post_id` is both PK and
                        FK to `community_posts.id`; deleting the post
                        cascades the poll away with it.
- `poll_options`      — the option list (min two enforced at API layer).
- `poll_votes`        — one row per user × option. UNIQUE constraint
                        prevents double-voting on the same option;
                        single-choice enforcement is done at the API
                        layer by deleting the user's other votes on
                        the same poll.

No result caching / vote counts stored — small polls counted at read
time with a GROUP BY, kept indexed by poll_id for cheap aggregation.
"""

from alembic import op
import sqlalchemy as sa


revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "polls",
        sa.Column("post_id", sa.String(), primary_key=True),
        sa.Column("allow_multiple", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("show_results_before_vote", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("closes_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["community_posts.id"],
                                ondelete="CASCADE"),
    )

    op.create_table(
        "poll_options",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("poll_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.post_id"],
                                ondelete="CASCADE"),
    )
    op.create_index("ix_poll_options_poll", "poll_options",
                    ["poll_id", "position"])

    op.create_table(
        "poll_votes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("poll_id", sa.String(), nullable=False),
        sa.Column("option_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.post_id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["option_id"], ["poll_options.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("poll_id", "option_id", "user_id",
                            name="uq_poll_votes_option_user"),
    )
    op.create_index("ix_poll_votes_poll", "poll_votes", ["poll_id"])
    op.create_index("ix_poll_votes_poll_user", "poll_votes",
                    ["poll_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_poll_votes_poll_user", table_name="poll_votes")
    op.drop_index("ix_poll_votes_poll", table_name="poll_votes")
    op.drop_table("poll_votes")
    op.drop_index("ix_poll_options_poll", table_name="poll_options")
    op.drop_table("poll_options")
    op.drop_table("polls")
