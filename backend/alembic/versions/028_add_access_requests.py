"""Add token to space_invitations and create space_access_requests table.

Revision ID: 028
Revises: 027
Create Date: 2026-05-22
"""

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add token column to space_invitations ──────────────────────────
    op.execute("""
        ALTER TABLE space_invitations
        ADD COLUMN IF NOT EXISTS token VARCHAR(64);
    """)
    # Backfill existing invitations with unique tokens
    op.execute("""
        UPDATE space_invitations
        SET token = gen_random_uuid()::varchar
        WHERE token IS NULL;
    """)
    op.execute("""
        ALTER TABLE space_invitations
        ALTER COLUMN token SET NOT NULL;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_space_invitations_token
        ON space_invitations(token);
    """)

    # ── 2. Create space_access_requests table ─────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS space_access_requests (
            id        TEXT PRIMARY KEY,
            space_id  TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            user_id   TEXT NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
            status    VARCHAR(20) NOT NULL DEFAULT 'pending',
            message   TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT space_access_requests_space_user_unique UNIQUE (space_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS ix_access_requests_space_id ON space_access_requests(space_id);
        CREATE INDEX IF NOT EXISTS ix_access_requests_user_id  ON space_access_requests(user_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS space_access_requests CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_space_invitations_token")
    op.execute("ALTER TABLE space_invitations DROP COLUMN IF EXISTS token")
