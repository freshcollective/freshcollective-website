"""Mutual "Say hello" between members.

Revision ID: 147
Revises: 146
Create Date: 2026-10-04

Ways to Connect 5b. One new table, nothing altered: a hello is a
directed row, and the four product states (none / outgoing / incoming /
mutual) are read off the presence of the two possible rows rather than
stored in a status column. See ``app/models/connections.py`` for why
that shape was chosen over an undirected pair row.

Purely additive and empty on arrival, so it is safe on existing
production data — there is no backfill and nothing to rewrite. The
unique constraint is what makes a repeat click idempotent under
concurrency, so it is part of the correctness of the feature rather
than an optimisation.

Downgrade drops the table. That loses hellos, which is the honest
consequence of removing the feature; there is nowhere else to keep
them.
"""

from alembic import op
import sqlalchemy as sa


revision = "147"
down_revision = "146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_hellos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "from_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_user_id",
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
            "from_user_id", "to_user_id", name="uq_member_hellos_pair",
        ),
        sa.CheckConstraint(
            "from_user_id <> to_user_id", name="ck_member_hellos_not_self",
        ),
    )
    # The unique constraint covers (from_user_id, to_user_id) lookups.
    # Card rendering also asks "who said hello to me", which is keyed on
    # the recipient alone.
    op.create_index("ix_member_hellos_to_user", "member_hellos", ["to_user_id"])


def downgrade() -> None:
    op.drop_index("ix_member_hellos_to_user", table_name="member_hellos")
    op.drop_table("member_hellos")
