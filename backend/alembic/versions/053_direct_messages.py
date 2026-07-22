"""Add message_threads and direct_messages tables

Revision ID: 053
Revises: 052
Create Date: 2026-06-19
"""

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE message_threads (
            id          VARCHAR     NOT NULL PRIMARY KEY,
            space_id    VARCHAR     NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            creator_id  VARCHAR     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            member_id   VARCHAR     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_thread_space_creator_member UNIQUE (space_id, creator_id, member_id)
        )
    """)
    op.execute("CREATE INDEX ix_message_threads_creator ON message_threads(creator_id)")
    op.execute("CREATE INDEX ix_message_threads_member  ON message_threads(member_id)")
    op.execute("CREATE INDEX ix_message_threads_space   ON message_threads(space_id)")

    op.execute("""
        CREATE TABLE direct_messages (
            id          VARCHAR     NOT NULL PRIMARY KEY,
            thread_id   VARCHAR     NOT NULL REFERENCES message_threads(id) ON DELETE CASCADE,
            sender_id   VARCHAR     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body        TEXT        NOT NULL,
            is_read     BOOLEAN     NOT NULL DEFAULT FALSE,
            read_at     TIMESTAMP,
            created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_direct_messages_thread ON direct_messages(thread_id)")
    op.execute("CREATE INDEX ix_direct_messages_thread_created ON direct_messages(thread_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS direct_messages")
    op.execute("DROP TABLE IF EXISTS message_threads")
