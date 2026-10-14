"""Per-member seen state for shared Collective activity.

Revision ID: 156
Revises: 155
Create Date: 2026-10-15

Notifications 2.0, Phase 2. Two additions, both inert until the
endpoints that read them ship.

``collective_activity_cursors``
-------------------------------
One row per member per Collective per category, holding a high-water
mark. "Visiting clears what was presented" is literally a high-water
mark, so the cursor is the rule rather than a mechanism standing in
for it. A member with no row has seen nothing since they joined, which
is the correct answer and costs no write — rows are created on first
advance, not on joining.

``activities.sequence_number``
------------------------------
Why this column exists, since it looks redundant beside ``created_at``:
``created_at`` defaults to ``now()``, and in PostgreSQL ``now()`` is
the *transaction* timestamp. Every row written in one commit therefore
carries a byte-identical value, which already happens — a Pathway
published together with its immediate steps, or ``scheduled_publisher``
releasing several posts in one go.

A cursor of ``created_at > seen_through`` cannot distinguish those
rows. A panel that renders five of seven rows stamped T advances to T
and permanently clears the two it never presented, silently and with
no trace. An identity column gives a unique, monotonic total order, so
the comparison is exact and ties cannot arise.

``communication_events.sequence_number`` already uses this exact
pattern, so it is the house answer to this problem rather than a new
idea.

Cost and safety
---------------
Adding an identity column backfills existing rows, which rewrites the
table — the one operation here that is not metadata-only. ``activities``
held a single row in production when this was written, so it is
instantaneous. If that is ever untrue, split it: add nullable,
backfill in batches, then set NOT NULL.

Everything else is additive. Nothing is rewritten, nothing is deleted,
and no existing query reads either addition.
"""

from alembic import op
import sqlalchemy as sa

revision = "156"
down_revision = "155"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column(
            "sequence_number",
            sa.BigInteger(),
            sa.Identity(always=False, start=1),
            nullable=False,
        ),
    )
    # Counting reads one Collective and one category at a time and
    # compares the sequence against a cursor, so this is the shape the
    # predicate wants. It supersedes nothing — the created_at index
    # still serves the ordered feed.
    op.create_index(
        "ix_activities_collective_category_seq",
        "activities",
        ["collective_id", "category", "sequence_number"],
    )

    op.create_table(
        "collective_activity_cursors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collective_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        # The legible mark. Kept because a support question is always
        # "when did they last look", never "which integer".
        sa.Column("seen_through", sa.DateTime(timezone=False), nullable=False),
        # The authoritative one. Every comparison uses this.
        sa.Column("seen_through_seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('conversations', 'pathways', 'gatherings')",
            name="ck_activity_cursor_category",
        ),
        sa.UniqueConstraint(
            "user_id",
            "collective_id",
            "category",
            name="ux_activity_cursor_member_scope",
        ),
    )
    # Every read is "this member's cursors", for one Collective or all
    # of them at once.
    op.create_index(
        "ix_activity_cursors_user",
        "collective_activity_cursors",
        ["user_id", "collective_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_cursors_user", table_name="collective_activity_cursors")
    op.drop_table("collective_activity_cursors")
    op.drop_index(
        "ix_activities_collective_category_seq", table_name="activities"
    )
    op.drop_column("activities", "sequence_number")
