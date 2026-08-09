"""Library — folders across the two asset stores.

Revision ID: 103
Revises: 102
Create Date: 2026-08-09

Adds a single ``space_library_folders`` table and a nullable
``folder_id`` FK on both existing asset tables. This is the storage
foundation for the unified Library — one creator-facing surface that
aggregates the existing ``creator_media_assets`` and ``space_resources``
tables under one set of folders.

No data migration is required. Every existing asset lands in "All
items" (folder_id NULL) until a creator explicitly moves it.

Folders are flat (no nesting) in v1. If creators outgrow the flat
model, a later migration can add ``parent_folder_id`` without
breaking anything.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_library_folders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_space_library_folders_space_position",
        "space_library_folders",
        ["space_id", "position"],
    )

    # Attach folder to the two asset tables. Both are optional — items
    # without a folder simply appear in "All items". ON DELETE SET NULL
    # so deleting a folder empties it back to "All items" rather than
    # cascading a delete through creator content.
    op.add_column(
        "creator_media_assets",
        sa.Column(
            "folder_id", sa.String(), nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_creator_media_assets_folder_id",
        source_table="creator_media_assets",
        referent_table="space_library_folders",
        local_cols=["folder_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_creator_media_assets_folder_id",
        "creator_media_assets",
        ["folder_id"],
    )

    op.add_column(
        "space_resources",
        sa.Column(
            "folder_id", sa.String(), nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_space_resources_folder_id",
        source_table="space_resources",
        referent_table="space_library_folders",
        local_cols=["folder_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_space_resources_folder_id",
        "space_resources",
        ["folder_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_space_resources_folder_id", table_name="space_resources")
    op.drop_constraint(
        "fk_space_resources_folder_id", "space_resources", type_="foreignkey",
    )
    op.drop_column("space_resources", "folder_id")

    op.drop_index(
        "ix_creator_media_assets_folder_id", table_name="creator_media_assets",
    )
    op.drop_constraint(
        "fk_creator_media_assets_folder_id",
        "creator_media_assets", type_="foreignkey",
    )
    op.drop_column("creator_media_assets", "folder_id")

    op.drop_index(
        "ix_space_library_folders_space_position",
        table_name="space_library_folders",
    )
    op.drop_table("space_library_folders")
