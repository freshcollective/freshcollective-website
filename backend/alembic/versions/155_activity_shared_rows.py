"""Activity rows can describe a piece of content rather than a person.

Revision ID: 155
Revises: 154
Create Date: 2026-10-14

Notifications 2.0, Phase 1. ``activities`` was built per-recipient: one
row per member per event. For Collective activity that multiplies badly
— a single post in a 500-member Collective writes 500 rows, and
publishing becomes a bulk insert inside the creator's request.

A shared row says the same thing once. One activity describes one piece
of content; who may see it is decided when it is read, from the
permissions that already govern the content itself. Per-member seen
state arrives in Phase 2 as a small cursor table, not as a row per
member per item.

``recipient_user_id`` therefore becomes nullable rather than going
away. NULL means "this is about content"; a value still means "this is
about you", which remains the right shape for events that genuinely
happen per member — a drip step opening, a payment failing. The two
kinds coexist in one table on purpose, so Phase 1 does not foreclose
the per-member work deferred to a later phase.

Why an explicit dedupe_key
--------------------------
Publishing can be retried, double-clicked or raced. The key makes one
piece of content produce one row, enforced by the database rather than
by a SELECT-then-insert that races precisely when it matters.

A partial unique index on a single column, rather than a composite over
the nullable entity ids: in Postgres NULLs are distinct, so a composite
containing them would not deduplicate at all. The key is also readable
in a log line, and it mirrors ``communication_events``, which has used
the same mechanism successfully since migration 097.

Backwards compatibility
-----------------------
Every change is additive or a relaxation. Dropping NOT NULL cannot
invalidate an existing row; the new columns are nullable; the unique
index only applies to rows that opt in by setting a key. Nothing is
rewritten and nothing is deleted.
"""

from alembic import op
import sqlalchemy as sa

revision = "155"
down_revision = "154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "activities",
        "recipient_user_id",
        existing_type=sa.String(),
        nullable=True,
    )
    op.add_column(
        "activities",
        sa.Column("series_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_activities_series_id",
        "activities",
        "event_series",
        ["series_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "activities",
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ux_activities_dedupe",
        "activities",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    # Shared-row reads now; per-category counts from Phase 2. Added here
    # so the same table is not altered twice for one feature.
    op.create_index(
        "ix_activities_collective_category_created",
        "activities",
        ["collective_id", "category", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activities_collective_category_created", table_name="activities")
    op.drop_index("ux_activities_dedupe", table_name="activities")
    op.drop_column("activities", "dedupe_key")
    op.drop_constraint("fk_activities_series_id", "activities", type_="foreignkey")
    op.drop_column("activities", "series_id")
    # Only safe while no shared rows exist. A shared row has no
    # recipient, so restoring NOT NULL would fail — deliberately. Delete
    # the shared rows first if this must be reversed after Phase 1 has
    # produced any.
    op.alter_column(
        "activities",
        "recipient_user_id",
        existing_type=sa.String(),
        nullable=False,
    )
