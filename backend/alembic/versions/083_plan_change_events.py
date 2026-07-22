"""Audit trail for admin plan edits.

Revision ID: 083
Revises: 082
Create Date: 2026-07-18

Supports the "Edit plan" admin action on the Fresh Collective Plans
page. Whenever an admin edits a ``CreatorPlan``, a row is appended to
``plan_change_events`` recording who changed it, when, and a field-level
diff (before/after) of what changed. Enterprise / synthesised plans
(Organisation) are not backed by a DB row and cannot be edited, so they
never produce audit rows.

Changes:

1. New table ``plan_change_events``:
     id                     VARCHAR PK
     plan_id                VARCHAR NOT NULL FK creator_plans ON DELETE CASCADE
     changed_by_user_id     VARCHAR NULL FK users ON DELETE SET NULL
     changed_at             TIMESTAMP NOT NULL DEFAULT NOW()
     changes                JSON  NOT NULL  -- {field: {before, after}}

All changes are additive. The audit table is append-only; there is no
delete path in application code.
"""

from alembic import op
import sqlalchemy as sa


revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_change_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "plan_id", sa.String(),
            sa.ForeignKey("creator_plans.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "changed_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("changes", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plan_change_events")
