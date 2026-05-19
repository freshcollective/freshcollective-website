"""Add section_position to pathway_steps for per-section ordering.

Revision ID: 015
Revises: 014
Create Date: 2026-05-19
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pathway_steps ADD COLUMN IF NOT EXISTS section_position INTEGER;")
    # Backfill: assign 0-based section_position within each section based on current global position order
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY section_id ORDER BY position) - 1 AS rn
            FROM pathway_steps
            WHERE section_id IS NOT NULL
        )
        UPDATE pathway_steps
        SET section_position = ranked.rn
        FROM ranked
        WHERE pathway_steps.id = ranked.id;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pathway_steps_section_position "
        "ON pathway_steps(section_id, section_position);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pathway_steps_section_position;")
    op.execute("ALTER TABLE pathway_steps DROP COLUMN IF EXISTS section_position;")
