"""Add 'resource' block type and resource_id FK to step + about blocks

Revision ID: 061
Revises: 060
Create Date: 2026-06-29

Adds a new block type for linking an existing collective Resource into a
pathway step or about page. The block stores only the FK; the card title,
description, type, and URL are read live from the linked SpaceResource so
edits flow through to every place the resource is referenced.

resource_id is nullable + ON DELETE SET NULL so removing a Resource leaves
the surrounding block as a harmless stub (members see nothing) rather than
cascading away other step content.
"""

from alembic import op
import sqlalchemy as sa


revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL enums need autocommit for ADD VALUE.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE step_block_type_enum ADD VALUE IF NOT EXISTS 'resource'")

    op.add_column(
        "pathway_step_blocks",
        sa.Column("resource_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pathway_step_blocks_resource_id",
        "pathway_step_blocks",
        "space_resources",
        ["resource_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "pathway_about_blocks",
        sa.Column("resource_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pathway_about_blocks_resource_id",
        "pathway_about_blocks",
        "space_resources",
        ["resource_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pathway_about_blocks_resource_id", "pathway_about_blocks", type_="foreignkey")
    op.drop_column("pathway_about_blocks", "resource_id")

    op.drop_constraint("fk_pathway_step_blocks_resource_id", "pathway_step_blocks", type_="foreignkey")
    op.drop_column("pathway_step_blocks", "resource_id")

    # PostgreSQL does not support removing enum values. The new 'resource'
    # value is harmless on downgrade — it just won't be used by app code.
