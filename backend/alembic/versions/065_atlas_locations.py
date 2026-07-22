"""The Atlas — curated Locations

Revision ID: 065
Revises: 064
Create Date: 2026-07-10

ADDITIVE ONLY.

Introduces The Atlas — the curated collection of Locations within the
Fresh Collective world (Atlas Volume I, Version 1.1, Chapters Nine + Ten).

Upgrade does three things:

  1. Creates the `locations` table. A Location is the curated place a
     collective lives inside. Managed exclusively by Fresh Collective
     administrators through the Admin Portal; never edited by creators.

  2. Adds a nullable `location_id` FK to `spaces`. Existing collectives
     are not migrated — the FK stays null until a creator chooses a
     Location. Everything downstream (Build Your Collective, reveal,
     Universe, My World, thumbnails) will eventually read from this
     relationship rather than from the per-collective `landscape_key`.

  3. Seeds twelve placeholder Locations so the Admin Portal has real
     rows to browse. Names and metadata are deliberately generic
     ("Location 01"…"Location 12"); real names and artwork will be
     authored inside the Admin Portal.

Downgrade drops the FK, the table, and the seed rows.
"""

from alembic import op
import sqlalchemy as sa


revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. locations table
    # -----------------------------------------------------------------------
    op.create_table(
        "locations",
        sa.Column("id", sa.String, primary_key=True),
        # url-friendly key — stable across renames of `name`.
        sa.Column("key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # 'active' visible to creators; 'hidden' available in admin only.
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="active"
        ),
        # Curated artwork — hero for the reveal / island, thumbnail for
        # card and thumbnail contexts. Both nullable until admins upload.
        sa.Column("hero_artwork_url", sa.String(500), nullable=True),
        sa.Column("thumbnail_artwork_url", sa.String(500), nullable=True),
        # Classification — open text so admins can shape the taxonomy
        # organically. No enum until we know what taxonomy has emerged.
        sa.Column("biome", sa.String(64), nullable=True),
        sa.Column("archipelago", sa.String(64), nullable=True),
        # Recommendation metadata — arrays of option keys (from the
        # existing atmosphere_options / colour_stories tables) plus a
        # free-form theme list.
        sa.Column("preferred_atmospheres", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("preferred_colour_stories", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("preferred_themes", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        # Display ordering in the Atlas grid.
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # -----------------------------------------------------------------------
    # 2. spaces.location_id — nullable FK; no data migration yet.
    # -----------------------------------------------------------------------
    op.add_column(
        "spaces",
        sa.Column("location_id", sa.String, nullable=True, index=True),
    )
    op.create_foreign_key(
        "fk_spaces_location_id",
        "spaces",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -----------------------------------------------------------------------
    # 3. Seed twelve placeholder Locations
    # -----------------------------------------------------------------------
    for i in range(1, 13):
        key = f"location-{i:02d}"
        name = f"Location {i:02d}"
        description = (
            "A curated Location in the Fresh Collective world. "
            "Name, artwork, and description are placeholders until authored in the Admin Portal."
        )
        op.execute(
            sa.text(
                "INSERT INTO locations (id, key, name, description, status, position) "
                "VALUES (:id, :key, :name, :description, 'active', :position)"
            ).bindparams(
                id=f"loc_{i:02d}",
                key=key,
                name=name,
                description=description,
                position=i,
            )
        )


def downgrade() -> None:
    op.drop_constraint("fk_spaces_location_id", "spaces", type_="foreignkey")
    op.drop_column("spaces", "location_id")
    op.drop_table("locations")
