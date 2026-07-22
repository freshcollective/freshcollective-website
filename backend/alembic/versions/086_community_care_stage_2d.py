"""Community Care — Stage 2D schema additions.

Revision ID: 086
Revises: 085
Create Date: 2026-07-19

Stage 2D introduces Resolution Outcomes and the operational Case
Summary. Schema additions are minimal — the resolution outcome kinds
were already reserved in Stage 2A's ACTION_KINDS tuple, and Stage 2A
already added ``users.cancelled_at`` / ``creator_cancelled_at`` /
``spaces.closed_at``. Stage 2D adds the linkage columns from those
cancellation/closure states back to the specific Community Care
action row that issued them (so the audit trail explains why the
state exists) plus the operational ``case_summary`` field.

Additions:

1. ``community_care_cases.case_summary`` — a working operational
   summary written by an admin. Editable while the case is open,
   required before any final resolution, and included in future
   reporting. Distinct from Stage 2A's ``resolution_summary`` which
   captures the moment-of-close snapshot.

2. ``users.cancelled_by_action_id`` — FK to the resolution action
   that cancelled the account. Nullable (existing rows have no
   cancellation).

3. ``users.creator_cancelled_by_action_id`` — same pattern for
   creator-role cancellation.

4. ``spaces.closed_by_action_id`` — same pattern for collective
   closure.

Every column is nullable to preserve every pre-existing row.
Reversible via ``downgrade()``.
"""

from alembic import op
import sqlalchemy as sa


revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Case summary (operational record)
    op.add_column(
        "community_care_cases",
        sa.Column("case_summary", sa.Text(), nullable=True),
    )

    # 2 + 3. User cancellation linkage
    op.add_column(
        "users",
        sa.Column(
            "cancelled_by_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "creator_cancelled_by_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 4. Space closure linkage
    op.add_column(
        "spaces",
        sa.Column(
            "closed_by_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("spaces", "closed_by_action_id")
    op.drop_column("users", "creator_cancelled_by_action_id")
    op.drop_column("users", "cancelled_by_action_id")
    op.drop_column("community_care_cases", "case_summary")
