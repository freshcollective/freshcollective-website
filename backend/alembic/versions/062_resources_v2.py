"""Resources v2: many-to-many resource↔pathway + media metadata

Revision ID: 062
Revises: 061
Create Date: 2026-06-29

ADDITIVE ONLY. No existing rows are modified or deleted.

Upgrade does three things:

  1. Creates a new join table `space_resource_pathways` with composite PK
     (resource_id, pathway_id) and CASCADE on both FKs. Hosts the new
     many-to-many between SpaceResource and Pathway.

  2. Backfills the join table from existing data. Every space_resource
     row with scope='pathway' AND pathway_id IS NOT NULL gets one join
     row pointing at its current pathway. Resources currently marked
     scope='general' get NO join rows — an empty pathway set IS the
     "General" assignment in the new model. No resource loses its
     existing association.

  3. Adds `alt_text` and `tags` columns (both nullable String(500)) to
     creator_media_assets. No backfill needed.

What this migration does NOT do, by design:

  - Does NOT drop or alter space_resources.scope.
  - Does NOT drop or alter space_resources.pathway_id.
    (Kept so the previous code path keeps working and downgrade is loss-
    free. They become read-only fallbacks while the new model takes over;
    a follow-up migration in a later release can drop them once the new
    read paths are confirmed stable in production.)
  - Does NOT change space_resources.status. The new 'archived' value is
    just another string in an already-String column; validator change is
    code-only.
  - Does NOT touch any files on disk.

Downgrade is loss-free:

  - Drops alt_text, tags, the new join table, and its index.
  - scope and pathway_id were never touched, so reverting to the old code
    path leaves every resource exactly where it was before this migration
    ran. Any rows that were flipped to status='archived' by the new code
    would need to be manually reset to 'draft' before reverting the app
    code — but the data isn't destroyed and the column still accepts the
    value.
"""

from alembic import op
import sqlalchemy as sa


revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Join table for many-to-many resource ↔ pathway.
    op.create_table(
        "space_resource_pathways",
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("pathway_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["space_resources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pathway_id"],
            ["pathways.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("resource_id", "pathway_id"),
    )
    op.create_index(
        "ix_space_resource_pathways_pathway_id",
        "space_resource_pathways",
        ["pathway_id"],
    )

    # 2. Backfill: every existing pathway-scoped resource gets ONE join row.
    # General-scoped resources get NONE — empty join set = General.
    # ON CONFLICT DO NOTHING is defensive; PK guarantees uniqueness anyway.
    op.execute(
        """
        INSERT INTO space_resource_pathways (resource_id, pathway_id, created_at)
        SELECT id, pathway_id, NOW()
        FROM space_resources
        WHERE scope = 'pathway' AND pathway_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    # 3. Brand Library: optional metadata fields. Nullable, no backfill.
    op.add_column(
        "creator_media_assets",
        sa.Column("alt_text", sa.String(500), nullable=True),
    )
    op.add_column(
        "creator_media_assets",
        sa.Column("tags", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_media_assets", "tags")
    op.drop_column("creator_media_assets", "alt_text")
    op.drop_index(
        "ix_space_resource_pathways_pathway_id",
        table_name="space_resource_pathways",
    )
    op.drop_table("space_resource_pathways")
