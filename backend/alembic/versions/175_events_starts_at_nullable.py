"""Allow a Gathering draft to exist before its dates are chosen.

Revision ID: 175
Revises: 174
Create Date: 2026-11-02

Duplicating a Gathering copies its configuration and deliberately does
**not** copy its dates — the whole point is a new session of the same
shape at a different time. ``events.starts_at`` was ``NOT NULL``, so
there was nowhere to put "not decided yet" except a placeholder date,
and a placeholder date in a column everything sorts and filters by is
a lie that other code will believe.

Why this is safe for the rows that already exist
------------------------------------------------
Nothing is backfilled and no existing row changes: dropping ``NOT
NULL`` widens what the column accepts and leaves every current value
alone. The constraint can be restored by the downgrade precisely
because no row is written NULL except a dateless draft, which is
unpublished by construction.

Why a NULL cannot leak into a member-facing surface
---------------------------------------------------
Every query that lists Gatherings to anybody either compares
``starts_at`` against a time — and SQL comparisons against NULL are
never true, so a dateless draft matches none of them — or filters
``is_published``, which a dateless draft never is. The guard is
belt-and-braces: ``publish`` refuses a Gathering without both dates,
so the only way a NULL reaches a member is if two independent rules
fail at once.

The downgrade would fail against a database holding a dateless draft,
which is correct rather than unfortunate: silently inventing a date
for one is exactly what this migration exists to avoid. It deletes
them instead — they are unpublished drafts with no bookings by
definition, since a Gathering cannot be booked before it has a time.
"""

from alembic import op
import sqlalchemy as sa

revision = "175"
down_revision = "174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "events",
        "starts_at",
        existing_type=sa.DateTime(timezone=False),
        nullable=True,
    )


def downgrade() -> None:
    # A dateless draft has no honest value to be given here. It is
    # unpublished and unbookable, so removing it loses nothing a
    # creator had committed to.
    op.execute(
        "DELETE FROM events WHERE starts_at IS NULL AND is_published = false"
    )
    op.alter_column(
        "events",
        "starts_at",
        existing_type=sa.DateTime(timezone=False),
        nullable=False,
    )
