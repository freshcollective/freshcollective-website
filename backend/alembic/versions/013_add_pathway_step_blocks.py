"""Add pathway_step_blocks table

Revision ID: 013
Revises: 012
Create Date: 2026-05-16
"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE step_block_type_enum AS ENUM (
                'heading', 'text', 'image', 'video_embed', 'audio',
                'file_download', 'link', 'reflection_prompt', 'exercise',
                'callout', 'divider'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pathway_step_blocks (
            id VARCHAR NOT NULL,
            step_id VARCHAR NOT NULL REFERENCES pathway_steps(id) ON DELETE CASCADE,
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
        CREATE INDEX IF NOT EXISTS ix_pathway_step_blocks_step_id
            ON pathway_step_blocks (step_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_pathway_step_blocks_step_position
            ON pathway_step_blocks (step_id, position);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pathway_step_blocks;")
    op.execute("DROP TYPE IF EXISTS step_block_type_enum;")
