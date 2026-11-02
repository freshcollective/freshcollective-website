"""Let a creator hide the remaining-places count from the public page.

Revision ID: 176
Revises: 175
Create Date: 2026-11-02

Some Gatherings read better without a running count. A circle with
three places left can say so and fill; the same circle, early, saying
"11 of 12 remaining" tells a visitor nobody else is coming. That is a
presentation choice, so it belongs to the creator rather than to us.

What this column does NOT affect
--------------------------------
Capacity enforcement and ticket holds are untouched. The number is
still computed, still counted, still used to refuse a seat, and still
shown in full in Creator Studio. Only whether the *public* surface
prints it changes. Availability status — bookable, closed, Sold out —
also stays visible, because hiding "sold out" would send members to a
checkout that cannot succeed.

Why the default is True
-----------------------
Every existing Gathering currently shows its count, so True is the
value that changes nothing for anyone. A server-side default plus
NOT NULL means rows written by older code paths (and by anything that
omits the field) keep that behaviour rather than landing NULL and
making every read site handle a third state.
"""
from alembic import op
import sqlalchemy as sa

revision = "176"
down_revision = "175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "show_remaining_publicly",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "show_remaining_publicly")
