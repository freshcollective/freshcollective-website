"""Admin overrides for editable email copy.

Revision ID: 132
Revises: 131
Create Date: 2026-09-19

Motivation
----------
Backs World Management → Communications → Email Templates. Fresh
Collective's own wording stays in code; this table holds only the slots
an admin has actually rewritten, so an untouched template costs nothing
and reset-to-default is a DELETE rather than a copy of the default back
over itself.

Key-value rather than a ``subject / heading / greeting / body`` column
layout, because three templates branch into entirely different copy
(creator plan activation, booking confirmation, purchase confirmation)
and several carry two or three separately-resettable paragraphs. Rows
express both without a migration each time copy is restructured.

``default_fingerprint`` records a hash of the code default at save
time. When a later deploy improves that default the hash stops
matching, which is how the admin UI can surface "the Fresh Collective
default has changed since this was customised". It never drives an
automatic overwrite.

Safety
------
* Additive only — one new table, no changes to existing ones.
* Empty on creation, so rendering is unchanged until an admin saves
  something: the resolver falls back to code defaults for every slot
  with no row.
* ``updated_by_user_id`` is ON DELETE SET NULL rather than CASCADE —
  removing an admin account must not silently delete the copy they
  wrote.
* Reversible: ``downgrade`` drops the table. Any saved overrides are
  lost and every email returns to its code default, which is a safe
  resting state rather than a broken one.
"""

import sqlalchemy as sa
from alembic import op


revision = "132"
down_revision = "131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_template_overrides",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("template_key", sa.String(length=160), nullable=False),
        sa.Column("slot_id", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("default_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "template_key", "slot_id", name="uq_comm_tpl_override_key_slot",
        ),
    )
    op.create_index(
        "ix_comm_tpl_override_key",
        "communication_template_overrides",
        ["template_key"],
    )
    op.create_index(
        "ix_communication_template_overrides_updated_by_user_id",
        "communication_template_overrides",
        ["updated_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_template_overrides_updated_by_user_id",
        table_name="communication_template_overrides",
    )
    op.drop_index(
        "ix_comm_tpl_override_key",
        table_name="communication_template_overrides",
    )
    op.drop_table("communication_template_overrides")
