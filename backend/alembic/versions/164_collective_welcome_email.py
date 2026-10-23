"""Per-Collective email copy, and a welcome email each Collective can switch off.

Revision ID: 164
Revises: 163
Create Date: 2026-10-24

Two independent changes, both additive to existing rows.

1. ``communication_template_overrides.space_id``
--------------------------------------------------

The table was platform-wide by construction: ``UNIQUE(template_key,
slot_id)``, and ``load_overrides`` read every row for a key. A creator
customising their own Collective's welcome email therefore had nowhere
to put the copy.

``space_id`` adds that dimension, with NULL meaning *the platform
default* — so every existing row keeps its exact present meaning and
needs no backfill. Resolution reads the NULL row and overlays the
Collective's, which is how "Collective-specific overrides take
precedence over the platform default" falls out without a second table.

Why two partial indexes rather than one composite constraint
-------------------------------------------------------------

``UNIQUE(template_key, slot_id, space_id)`` would NOT hold the platform
default unique. Postgres treats NULLs as distinct in a unique index, so
two rows with ``space_id IS NULL`` for the same slot would both be
admitted — silently restoring the ambiguity this column exists to
remove, and in the one place (the platform default) where a duplicate
is worst.

So the old constraint is replaced by two partial unique indexes:

    uq_comm_tpl_override_platform  (template_key, slot_id) WHERE space_id IS NULL
    uq_comm_tpl_override_space     (template_key, slot_id, space_id) WHERE space_id IS NOT NULL

Same technique the codebase already uses for
``uq_creator_stripe_accounts_account_id`` and for the
``(event_type, dedupe_key)`` index on ``communication_events``.

ON DELETE CASCADE, deliberately
--------------------------------

A deleted Collective's custom copy has no meaning and no other owner —
unlike ``updated_by_user_id`` on the same table, which is SET NULL
because losing the admin account must not delete copy that still
applies platform-wide. Here the Collective *is* the scope, so the rows
go with it.

2. ``spaces.welcome_email_enabled``
-----------------------------------

NOT NULL, server default true, so **every Collective — existing and
new alike — starts enabled** without a backfill pass. That is the
stated decision: the distinction is not old Collective vs new
Collective, it is existing member vs person who joins from now on.

Nothing retrospective follows from this. The welcome email is emitted
only at the moment a first-time active membership is created, and
exactly once per (Collective, member) via the dedupe key
``collective_welcome:{space_id}:{user_id}``. Turning the flag on later
cannot produce a delayed send, because no event was ever emitted for
members who joined while it was off — the flag is read at emit time,
not at delivery time.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "164"
down_revision = "163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Per-Collective template overrides ──────────────────────────
    op.add_column(
        "communication_template_overrides",
        sa.Column("space_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_comm_tpl_override_space",
        "communication_template_overrides",
        "spaces",
        ["space_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The old constraint cannot coexist with per-Collective rows: it
    # would refuse a creator's override whenever the platform already
    # had one for the same slot.
    op.drop_constraint(
        "uq_comm_tpl_override_key_slot",
        "communication_template_overrides",
        type_="unique",
    )
    op.create_index(
        "uq_comm_tpl_override_platform",
        "communication_template_overrides",
        ["template_key", "slot_id"],
        unique=True,
        postgresql_where=sa.text("space_id IS NULL"),
    )
    op.create_index(
        "uq_comm_tpl_override_space",
        "communication_template_overrides",
        ["template_key", "slot_id", "space_id"],
        unique=True,
        postgresql_where=sa.text("space_id IS NOT NULL"),
    )
    op.create_index(
        "ix_comm_tpl_override_space",
        "communication_template_overrides",
        ["space_id"],
    )

    # ── 2. Per-Collective welcome-email switch ────────────────────────
    op.add_column(
        "spaces",
        sa.Column(
            "welcome_email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("spaces", "welcome_email_enabled")

    # Collective-scoped rows cannot survive the narrower constraint —
    # they would collide with the platform row for the same slot. They
    # are the rows this migration created the space for, so removing
    # them is the correct inverse rather than data loss of something
    # that predates it.
    op.execute(
        "DELETE FROM communication_template_overrides WHERE space_id IS NOT NULL"
    )
    op.drop_index(
        "ix_comm_tpl_override_space",
        table_name="communication_template_overrides",
    )
    op.drop_index(
        "uq_comm_tpl_override_space",
        table_name="communication_template_overrides",
    )
    op.drop_index(
        "uq_comm_tpl_override_platform",
        table_name="communication_template_overrides",
    )
    op.create_unique_constraint(
        "uq_comm_tpl_override_key_slot",
        "communication_template_overrides",
        ["template_key", "slot_id"],
    )
    op.drop_constraint(
        "fk_comm_tpl_override_space",
        "communication_template_overrides",
        type_="foreignkey",
    )
    op.drop_column("communication_template_overrides", "space_id")
