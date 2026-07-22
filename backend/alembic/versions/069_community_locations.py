"""Community Locations — a third location_type for Community (Free) collectives.

Revision ID: 069
Revises: 068
Create Date: 2026-07-14

ADDITIVE ONLY.

Introduces the `COMMUNITY` location_type: intentionally smaller, more
intimate gathering places available only to Community (Free) collectives.
Atlas Locations remain the premium worlds for Creator and Pro plans;
Cornerstones remain reserved for Fresh Collective. The frontend groups
Locations by type.

Seeds three placeholder Community Locations so the Admin Portal and the
Community-plan picker have real rows to browse:

    campfire-grove   🔥  Campfire Grove
    harvest-table    🍽️  Harvest Table
    festival-green   🌞  Festival Green

Positions are chosen high (500+) so they sort after the existing Atlas
seed and any Cornerstones authored to date.

No schema change: `location_type` is already a String(16). This migration
is data-only for the seed rows.

Downgrade removes the three seeded rows (only if untouched: still tagged
COMMUNITY and no collectives linked).
"""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4


revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


COMMUNITY_LOCATIONS = (
    {
        "key": "campfire-grove",
        "name": "Campfire Grove",
        "description": "Slow conversations beneath the trees.",
        "position": 500,
    },
    {
        "key": "harvest-table",
        "name": "Harvest Table",
        "description": "Where strangers become friends over a shared meal.",
        "position": 501,
    },
    {
        "key": "festival-green",
        "name": "Festival Green",
        "description": "A place where energy, celebration and community come alive.",
        "position": 502,
    },
)


def upgrade() -> None:
    bind = op.get_bind()
    for row in COMMUNITY_LOCATIONS:
        # Idempotent: skip if a Location with this key already exists.
        existing = bind.execute(
            sa.text("SELECT id FROM locations WHERE key = :k"),
            {"k": row["key"]},
        ).first()
        if existing:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO locations (
                    id, key, name, description, status, location_type,
                    hero_artwork_url, thumbnail_artwork_url,
                    biome, archipelago,
                    preferred_atmospheres, preferred_colour_stories, preferred_themes,
                    position
                ) VALUES (
                    :id, :key, :name, :description, 'active', 'COMMUNITY',
                    NULL, NULL,
                    NULL, NULL,
                    '[]', '[]', '[]',
                    :position
                )
                """
            ),
            {
                "id": str(uuid4()),
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "position": row["position"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for row in COMMUNITY_LOCATIONS:
        bind.execute(
            sa.text(
                """
                DELETE FROM locations
                 WHERE key = :k
                   AND location_type = 'COMMUNITY'
                   AND NOT EXISTS (
                     SELECT 1 FROM spaces s WHERE s.location_id = locations.id
                   )
                """
            ),
            {"k": row["key"]},
        )
