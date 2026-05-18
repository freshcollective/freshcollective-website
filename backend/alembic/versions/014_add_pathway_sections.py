"""add pathway sections

Revision ID: 014
Revises: 013
Create Date: 2026-05-19
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS pathway_sections (
            id          TEXT        PRIMARY KEY,
            pathway_id  TEXT        NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            title       TEXT        NOT NULL,
            position    INTEGER     NOT NULL DEFAULT 0,
            created_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP   NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_pathway_sections_pathway_position
            ON pathway_sections(pathway_id, position);
    """)
    op.execute("""
        ALTER TABLE pathway_steps
            ADD COLUMN IF NOT EXISTS section_id TEXT
            REFERENCES pathway_sections(id) ON DELETE SET NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_pathway_steps_section
            ON pathway_steps(section_id);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pathway_steps_section;")
    op.execute("ALTER TABLE pathway_steps DROP COLUMN IF EXISTS section_id;")
    op.execute("DROP INDEX IF EXISTS ix_pathway_sections_pathway_position;")
    op.execute("DROP TABLE IF EXISTS pathway_sections;")
