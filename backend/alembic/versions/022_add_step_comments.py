"""Add step_comments table for per-step public discussion.

Revision ID: 022
Revises: 021
Create Date: 2026-05-20
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS step_comments (
            id          VARCHAR     NOT NULL PRIMARY KEY,
            step_id     VARCHAR     NOT NULL REFERENCES pathway_steps(id) ON DELETE CASCADE,
            author_id   VARCHAR     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body        TEXT        NOT NULL,
            is_visible  BOOLEAN     NOT NULL DEFAULT true,
            created_at  TIMESTAMP   NOT NULL DEFAULT now(),
            updated_at  TIMESTAMP   NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_step_comments_step_id
            ON step_comments (step_id);

        CREATE INDEX IF NOT EXISTS ix_step_comments_author_id
            ON step_comments (author_id);

        CREATE INDEX IF NOT EXISTS ix_step_comments_step_created
            ON step_comments (step_id, created_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_step_comments_step_created;
        DROP INDEX IF EXISTS ix_step_comments_author_id;
        DROP INDEX IF EXISTS ix_step_comments_step_id;
        DROP TABLE IF EXISTS step_comments;
    """)
