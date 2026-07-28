"""Discovery, Connection & Belonging — Places scaffolding.

Revision ID: 091
Revises: 090
Create Date: 2026-07-26

Adds the data foundation for the Discovery, Connection & Belonging
pillar (see docs/foundations/discovery-connection-belonging-v1.1.md):

  * ``places``               — curated real-world places (city, sometimes
                                region). Editorial, not derived. Separate
                                from Atlas Locations.
  * ``space_places``         — many-to-many between Collectives and
                                Places. No primary/secondary ordering.
  * ``spaces.kind``          — 'standard' (default) | 'local_circle'.
                                Schema only; no behavioural branching
                                yet. Existing rows backfill to
                                'standard'.
  * ``users.home_place_id``  — nullable, opt-in FK to a Place. Schema
                                only; no profile UI yet.

The whole pillar is gated at the application layer by
``settings.discovery_pillar_enabled`` (default False), so schema shape
lands independently of any user-visible surface.
"""

from alembic import op
import sqlalchemy as sa


revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── places ────────────────────────────────────────────────────────
    op.create_table(
        "places",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("blurb", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'hidden')",
            name="places_status_check",
        ),
    )
    op.create_index("ix_places_slug", "places", ["slug"], unique=True)

    # ── space_places (join) ───────────────────────────────────────────
    op.create_table(
        "space_places",
        sa.Column(
            "space_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "place_id",
            sa.String(),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_space_places_place",
        "space_places",
        ["place_id"],
    )

    # ── spaces.kind ───────────────────────────────────────────────────
    op.add_column(
        "spaces",
        sa.Column(
            "kind",
            sa.String(length=24),
            nullable=False,
            server_default="standard",
        ),
    )
    op.create_check_constraint(
        "spaces_kind_check",
        "spaces",
        "kind IN ('standard', 'local_circle')",
    )

    # ── users.home_place_id ───────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "home_place_id",
            sa.String(),
            sa.ForeignKey("places.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_home_place_id",
        "users",
        ["home_place_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_home_place_id", table_name="users")
    op.drop_column("users", "home_place_id")

    op.drop_constraint("spaces_kind_check", "spaces", type_="check")
    op.drop_column("spaces", "kind")

    op.drop_index("ix_space_places_place", table_name="space_places")
    op.drop_table("space_places")

    op.drop_index("ix_places_slug", table_name="places")
    op.drop_table("places")
