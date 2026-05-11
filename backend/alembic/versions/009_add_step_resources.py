"""Add step_resources table

Revision ID: 009
Revises: 008
Create Date: 2026-05-11
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS step_resources (
            id          TEXT PRIMARY KEY,
            step_id     TEXT NOT NULL REFERENCES pathway_steps(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT,
            resource_type TEXT NOT NULL DEFAULT 'link',
            url         TEXT,
            file_name   TEXT,
            file_size   INTEGER,
            mime_type   TEXT,
            position    INTEGER NOT NULL DEFAULT 0,
            is_downloadable BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_step_resources_step_position
        ON step_resources(step_id, position)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS step_resources")
