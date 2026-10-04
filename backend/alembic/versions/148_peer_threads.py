"""Private conversations between mutually-connected members.

Revision ID: 148
Revises: 147
Create Date: 2026-10-04

Ways to Connect 5c. Two new tables beside the existing creator↔member
``message_threads``, which is left completely untouched: it models a
Collective's creator talking to one of its members, and its rows,
queries and creator inbox all depend on ``space_id`` being present and
meaningful. See ``app/models/peer_messages.py``.

The pair is canonicalised — lower user id always in
``participant_a_user_id`` — so the UNIQUE constraint genuinely means one
conversation per pair rather than one per ordering. The CHECK makes
that an invariant of the row instead of a convention callers remember,
which is also what lets get-or-create be a single conflict-tolerant
insert rather than a read-then-write race.

Purely additive and empty on arrival: no existing row is read, altered
or migrated, and nothing backfills. Safe on production data.

Downgrade drops both tables, losing peer conversations — the honest
consequence of removing the feature, since there is nowhere else to
keep them. ``message_threads`` is unaffected either way.
"""

from alembic import op
import sqlalchemy as sa


revision = "148"
down_revision = "147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "peer_threads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "participant_a_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_b_user_id",
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
        sa.Column("last_message_at", sa.DateTime(timezone=False), nullable=True),
        sa.UniqueConstraint(
            "participant_a_user_id", "participant_b_user_id",
            name="uq_peer_threads_pair",
        ),
        sa.CheckConstraint(
            "participant_a_user_id < participant_b_user_id",
            name="ck_peer_threads_canonical_order",
        ),
    )
    op.create_index(
        "ix_peer_threads_participant_a", "peer_threads", ["participant_a_user_id"],
    )
    op.create_index(
        "ix_peer_threads_participant_b", "peer_threads", ["participant_b_user_id"],
    )

    op.create_table(
        "peer_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(),
            sa.ForeignKey("peer_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_peer_messages_thread_id", "peer_messages", ["thread_id"])
    op.create_index(
        "ix_peer_messages_thread_created",
        "peer_messages",
        ["thread_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_peer_messages_thread_created", table_name="peer_messages")
    op.drop_index("ix_peer_messages_thread_id", table_name="peer_messages")
    op.drop_table("peer_messages")
    op.drop_index("ix_peer_threads_participant_b", table_name="peer_threads")
    op.drop_index("ix_peer_threads_participant_a", table_name="peer_threads")
    op.drop_table("peer_threads")
