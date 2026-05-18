"""Add creator_media_assets table and enums

Revision ID: 012
Revises: 011
Create Date: 2026-05-16
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE media_type_enum AS ENUM (
                'image', 'video', 'audio', 'document', 'other'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE media_status_enum AS ENUM ('active', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS creator_media_assets (
            id                   TEXT PRIMARY KEY,
            space_id             TEXT NOT NULL
                                     REFERENCES spaces(id) ON DELETE CASCADE,
            uploaded_by_user_id  TEXT NOT NULL
                                     REFERENCES users(id) ON DELETE RESTRICT,
            title                TEXT NOT NULL,
            description          TEXT,
            original_filename    TEXT NOT NULL,
            stored_filename      TEXT NOT NULL,
            storage_path         TEXT NOT NULL,
            file_url             TEXT NOT NULL,
            mime_type            TEXT NOT NULL,
            media_type           media_type_enum NOT NULL,
            file_size_bytes      INTEGER NOT NULL,
            extension            TEXT NOT NULL,
            status               media_status_enum NOT NULL DEFAULT 'active',
            created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_creator_media_assets_space_id
            ON creator_media_assets (space_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_creator_media_assets_status
            ON creator_media_assets (status);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS creator_media_assets")
    op.execute("DROP TYPE IF EXISTS media_status_enum")
    op.execute("DROP TYPE IF EXISTS media_type_enum")
