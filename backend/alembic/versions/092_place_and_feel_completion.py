"""Discovery pillar — complete Place & Feel.

Revision ID: 092
Revises: 091
Create Date: 2026-07-29

Adds the columns needed to complete the Place & Feel experience in
Creator Studio and to support automatic Place creation from a
location autocomplete picker.

  * ``places.latitude`` / ``places.longitude`` — coordinates
    captured from the picker at Place creation. Nullable to
    accommodate Places seeded manually before the picker existed.
  * ``places.timezone`` — IANA timezone identifier derived from the
    picker. Nullable for the same reason.
  * ``places.provider_place_id`` — the location provider's
    canonical id for this Place. Load-bearing: this is the
    deduplication key, per the location capture model. Unique
    across the table.
  * ``spaces.connection_style`` — 'online' (default) | 'in_person'
    | 'both'. Existing rows backfill to 'online', which is the
    safe interpretation because none of them have a Geographic
    Location today.

See
``docs/foundations/discovery-connection-belonging-location-model.md``.
"""

from alembic import op
import sqlalchemy as sa


revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Place coordinates + timezone + dedup key ─────────────────────
    op.add_column(
        "places",
        sa.Column("latitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("longitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("provider_place_id", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_places_provider_place_id",
        "places",
        ["provider_place_id"],
        unique=True,
    )

    # ── Space.connection_style ────────────────────────────────────────
    op.add_column(
        "spaces",
        sa.Column(
            "connection_style",
            sa.String(length=16),
            nullable=False,
            server_default="online",
        ),
    )
    op.create_check_constraint(
        "spaces_connection_style_check",
        "spaces",
        "connection_style IN ('online', 'in_person', 'both')",
    )


def downgrade() -> None:
    op.drop_constraint("spaces_connection_style_check", "spaces", type_="check")
    op.drop_column("spaces", "connection_style")

    op.drop_index("ix_places_provider_place_id", table_name="places")
    op.drop_column("places", "provider_place_id")
    op.drop_column("places", "timezone")
    op.drop_column("places", "longitude")
    op.drop_column("places", "latitude")
