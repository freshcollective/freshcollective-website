"""A seen cursor can describe part of a category.

Revision ID: 157
Revises: 156
Create Date: 2026-10-16

Notifications 2.0, Phase 3.

Phase 2 stored one high-water mark per member per Collective per
category. That is enough while a section shows everything the count
counts, and Pathways does. Conversations does not: the page renders a
single Channel, and every other Channel the member can reach is also
counted.

A scalar cannot express a partial view. With unseen activity at
sequence 100 in Channel A and 95 in Channel B, visiting A and
advancing the category cursor to 100 puts 95 below the mark — so
Channel B's thread is silently counted as seen, having never been on
screen. The failure is invisible and permanent: nothing surfaces it
again.

``scope_key`` splits the mark where the interface splits the content.
For ``conversations`` it is the Channel id; for ``pathways`` and
``gatherings`` it is the empty string, which is exactly the Phase 2
behaviour those two already have.

Why empty string rather than NULL
---------------------------------
It is part of a uniqueness constraint and part of a join. In Postgres
NULLs are distinct, so a nullable column would let a member accumulate
unlimited duplicate unscoped cursors, and the join would need
``IS NOT DISTINCT FROM`` at every call site. A non-null default makes
both total.

Existing data
-------------
Rows written by Phase 2 are all unscoped, so the default backfills
them correctly and their meaning is unchanged. Production holds zero
cursor rows at the time of writing — nothing reads or writes them
until Phase 3's UI ships — so this is additive against an empty table.

Gatherings
----------
The second half of the same problem is fixed without any schema
change: the count now excludes Gatherings whose end time has passed,
matching what the Gatherings page actually renders. See
``activity_counts``.
"""

from alembic import op
import sqlalchemy as sa

revision = "157"
down_revision = "156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collective_activity_cursors",
        sa.Column(
            "scope_key",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    # The old constraint would now permit only one cursor per category
    # regardless of Channel, which is the bug this migration exists to
    # fix. Replaced rather than supplemented.
    op.drop_constraint(
        "ux_activity_cursor_member_scope",
        "collective_activity_cursors",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_activity_cursor_member_scope",
        "collective_activity_cursors",
        ["user_id", "collective_id", "category", "scope_key"],
    )


def downgrade() -> None:
    # Scoped rows cannot be collapsed back into one mark per category
    # without choosing which Channel's position to keep, and any choice
    # would mark unseen activity as seen. Delete them instead: a lost
    # cursor re-reports activity the member has already seen, which is
    # noise; a wrong cursor hides activity they have not, which is not
    # recoverable.
    op.execute(
        "DELETE FROM collective_activity_cursors WHERE scope_key <> ''"
    )
    op.drop_constraint(
        "ux_activity_cursor_member_scope",
        "collective_activity_cursors",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_activity_cursor_member_scope",
        "collective_activity_cursors",
        ["user_id", "collective_id", "category"],
    )
    op.drop_column("collective_activity_cursors", "scope_key")
