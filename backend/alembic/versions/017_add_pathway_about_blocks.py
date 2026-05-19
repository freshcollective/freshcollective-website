"""Add pathway_about_blocks table for per-pathway About page content.

The table mirrors pathway_step_blocks but is linked to a pathway
instead of a step, enabling a flexible block-based About/sales page
for each pathway editable in Creator Studio.

Revision ID: 017
Revises: 016
Create Date: 2026-05-19
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # step_block_type_enum already created by migration 013 — reuse it.
    op.execute("""
        CREATE TABLE IF NOT EXISTS pathway_about_blocks (
            id VARCHAR NOT NULL,
            pathway_id VARCHAR NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            block_type step_block_type_enum NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            content TEXT,
            label VARCHAR(300),
            caption VARCHAR(500),
            embed_url VARCHAR(1000),
            media_asset_id VARCHAR REFERENCES creator_media_assets(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id)
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_pathway_about_blocks_pathway_id
            ON pathway_about_blocks (pathway_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_pathway_about_blocks_pathway_position
            ON pathway_about_blocks (pathway_id, position);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pathway_about_blocks;")
