"""Members can block one another.

Revision ID: 149
Revises: 148
Create Date: 2026-10-04

Ways to Connect 5d. One additive, empty-on-arrival table. Nothing
existing is read, altered or migrated — in particular ``member_hellos``
is untouched: a block does not undo a hello, it outranks it.

Peer *reports* needed no schema change at all. ``community_care_cases``
already allows a null ``subject_space_id``, ``member_behaviour`` is
already a CHECK-permitted ``content_type``, ``subject_member_user_id``
already exists, and ``content_snapshot`` is already documented as "a
point-in-time copy of the reported content... kept for review and audit
even if the source is later edited or removed" — which is exactly what a
peer conversation reference needs to be. So the existing Community Care
framework carries peer reports as-is.

Downgrade drops the table, which removes every block. That is a real
consequence rather than a neutral rollback, so it is worth saying
plainly: rolling this back restores messaging between people who had
blocked each other.
"""

from alembic import op
import sqlalchemy as sa


revision = "149"
down_revision = "148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_blocks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "blocker_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blocked_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "blocker_user_id", "blocked_user_id", name="uq_member_blocks_pair",
        ),
        sa.CheckConstraint(
            "blocker_user_id <> blocked_user_id", name="ck_member_blocks_not_self",
        ),
    )
    op.create_index("ix_member_blocks_blocker", "member_blocks", ["blocker_user_id"])
    op.create_index("ix_member_blocks_blocked", "member_blocks", ["blocked_user_id"])


def downgrade() -> None:
    op.drop_index("ix_member_blocks_blocked", table_name="member_blocks")
    op.drop_index("ix_member_blocks_blocker", table_name="member_blocks")
    op.drop_table("member_blocks")
