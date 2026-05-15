"""Add space_invitations table

Revision ID: 010
Revises: 009
Create Date: 2026-05-15
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # space_role_enum already exists from migration 003 — reuse it directly
    op.execute("""
        CREATE TABLE IF NOT EXISTS space_invitations (
            id              TEXT PRIMARY KEY,
            space_id        TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            email           TEXT NOT NULL,
            name            TEXT,
            role            space_role_enum NOT NULL DEFAULT 'learner',
            note            TEXT,
            invited_by_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT space_invitations_space_email_unique UNIQUE (space_id, email)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_space_invitations_space_id
        ON space_invitations(space_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_space_invitations_space_id")
    op.execute("DROP TABLE IF EXISTS space_invitations")
