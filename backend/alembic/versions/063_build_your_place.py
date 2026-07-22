"""Build Your Place — landscape, atmosphere, colour, elements + drafts

Revision ID: 063
Revises: 062
Create Date: 2026-07-09

Introduces the schema for the Build Your Place creator experience — the
guided ritual that replaces the old "create a space" form. The Atlas
(Volume I) frames a collective as a place, not a form; this migration
teaches the database that vocabulary.

ADDITIVE ONLY. No existing rows are modified or destroyed.

Upgrade:

  1. Adds seven new nullable columns to `spaces` — the four aesthetic
     identity fields (landscape_key, atmosphere_keys, colour_story_key,
     element_keys), the two prose fields (identity_statement,
     welcome_message), and a `visibility` enum-like string with three
     values: 'public' | 'link' | 'private'. Backfill: existing rows get
     visibility='public' when is_public=true, else 'private'. The old
     is_public column is preserved and continues to work for read paths
     that haven't migrated yet.

     Also adds `archipelago_hint` — kept for future clustering. Not
     exposed in UI yet; the taxonomy will grow naturally.

  2. Creates four configurable option tables — landscape_options,
     atmosphere_options, colour_stories, element_options. All follow the
     same shape: id, key (unique), name, position, is_active. Landscape
     adds a whisper + motif_key; colour stories carry a palette JSON with
     primary/secondary/accent/background hex values; elements carry a
     glyph_key. New options land as seed rows; no code changes required.

  3. Seeds all four tables from Atlas v1.0 vocabulary. Colour palettes are
     a first pass — subject to review before locking into Atlas v1.1.

  4. Creates `space_drafts` — one in-progress draft per creator. Draft
     data is a single JSON blob so evolving the flow doesn't require
     migrations.

Downgrade is loss-free: drops the new columns, tables, and seed rows.
"""

from alembic import op
import sqlalchemy as sa


revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. New columns on `spaces`
    # -----------------------------------------------------------------------
    op.add_column("spaces", sa.Column("landscape_key", sa.String(64), nullable=True))
    op.add_column("spaces", sa.Column("atmosphere_keys", sa.JSON(), nullable=True))
    op.add_column("spaces", sa.Column("colour_story_key", sa.String(64), nullable=True))
    op.add_column("spaces", sa.Column("element_keys", sa.JSON(), nullable=True))
    op.add_column("spaces", sa.Column("identity_statement", sa.Text(), nullable=True))
    op.add_column("spaces", sa.Column("welcome_message", sa.Text(), nullable=True))
    op.add_column("spaces", sa.Column("archipelago_hint", sa.String(64), nullable=True))
    op.add_column(
        "spaces",
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="public",
        ),
    )
    # Backfill visibility from existing is_public
    op.execute(
        """
        UPDATE spaces
        SET visibility = CASE WHEN is_public = true THEN 'public' ELSE 'private' END
        """
    )

    # -----------------------------------------------------------------------
    # 2. Option tables
    # -----------------------------------------------------------------------
    op.create_table(
        "landscape_options",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("whisper", sa.String(300), nullable=True),
        sa.Column("motif_key", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
    )

    op.create_table(
        "atmosphere_options",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
    )

    op.create_table(
        "colour_stories",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("palette", sa.JSON, nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
    )

    op.create_table(
        "element_options",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("glyph_key", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
    )

    # -----------------------------------------------------------------------
    # 3. Seed data
    # -----------------------------------------------------------------------
    _seed_landscapes()
    _seed_atmospheres()
    _seed_colour_stories()
    _seed_elements()

    # -----------------------------------------------------------------------
    # 4. Draft table
    # -----------------------------------------------------------------------
    op.create_table(
        "space_drafts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "user_id",
            sa.String,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("data", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
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


def downgrade() -> None:
    op.drop_table("space_drafts")
    op.drop_table("element_options")
    op.drop_table("colour_stories")
    op.drop_table("atmosphere_options")
    op.drop_table("landscape_options")
    op.drop_column("spaces", "visibility")
    op.drop_column("spaces", "archipelago_hint")
    op.drop_column("spaces", "welcome_message")
    op.drop_column("spaces", "identity_statement")
    op.drop_column("spaces", "element_keys")
    op.drop_column("spaces", "colour_story_key")
    op.drop_column("spaces", "atmosphere_keys")
    op.drop_column("spaces", "landscape_key")


# ---------------------------------------------------------------------------
# Seed data — Atlas v1.0 vocabulary
# ---------------------------------------------------------------------------

def _row(key: str) -> str:
    return f"land_{key}"  # id prefix helper — reused below via literal strings

def _seed_landscapes() -> None:
    entries = [
        ("ancient_forest",     "Ancient Forest",       "Old growth, moss, sunlight through leaves."),
        ("coastal_shores",     "Coastal Shores",       "Salt air, driftwood, a slow tide."),
        ("wildflower_meadows", "Wildflower Meadows",   "Colour scattered like poems."),
        ("mountain_ranges",    "Mountain Ranges",      "Sky room. Ridgelines and silence."),
        ("wetlands",           "Wetlands",             "Reeds bend. Water thinks in reflections."),
        ("rolling_farmland",   "Rolling Farmland",     "Fields, fences, honest weather."),
        ("woodland",           "Woodland",             "Younger trees, longer paths."),
        ("island_sanctuary",   "Island Sanctuary",     "A place set apart, held by water."),
        ("desert",             "Desert",               "Wide sky, warm ground, honest stars."),
        ("highlands",          "Highlands",            "Wind-tempered hills. Slower time."),
        ("snowfields",         "Snowfields",           "White quiet. Air that clears the mind."),
        ("reefs",              "Reefs",                "Colour beneath the surface. Life in every corner."),
        ("fjords_icefields",   "Fjords & Icefields",   "Ancient water, cathedral cliffs."),
        ("canyons",            "Canyons",              "Layers of time in stone."),
        ("waterfalls_lagoons", "Waterfalls & Lagoons", "Falling water. Green rooms."),
        ("village",            "Village",              "Warm doors, shared tables."),
    ]
    for i, (key, name, whisper) in enumerate(entries):
        op.execute(
            sa.text(
                "INSERT INTO landscape_options (id, key, name, whisper, motif_key, position, is_active) "
                "VALUES (:id, :key, :name, :whisper, :motif, :position, true)"
            ).bindparams(
                id=f"land_{key}",
                key=key,
                name=name,
                whisper=whisper,
                motif=key,
                position=i,
            )
        )


def _seed_atmospheres() -> None:
    words = [
        "Calm", "Playful", "Grounded", "Reflective", "Joyful", "Hopeful",
        "Curious", "Creative", "Adventurous", "Nurturing", "Brave", "Warm",
        "Peaceful",
    ]
    for i, name in enumerate(words):
        key = name.lower()
        op.execute(
            sa.text(
                "INSERT INTO atmosphere_options (id, key, name, position, is_active) "
                "VALUES (:id, :key, :name, :position, true)"
            ).bindparams(id=f"atm_{key}", key=key, name=name, position=i)
        )


def _seed_colour_stories() -> None:
    # First-pass palettes for Atlas review. Each carries primary,
    # secondary, accent, background. Background is a light/canvas wash
    # for most; the Midnight and Deep Ocean palettes are night-mode
    # by design (dark background, warm accent).
    import json
    stories = [
        ("earth_moss",         "Earth & Moss",       "#5C4A33", "#6D7A48", "#C7A97A", "#F5EFE3"),
        ("ocean_sand",         "Ocean & Sand",       "#3A6B7A", "#91B4B9", "#D9BE95", "#EEF3F3"),
        ("midnight",           "Midnight",           "#3F4A73", "#7C86A6", "#C4A868", "#131B33"),
        ("sunrise",            "Sunrise",            "#D97A3F", "#F1B370", "#C3557F", "#FFF5E6"),
        ("wildflowers",        "Wildflowers",        "#7A4C7C", "#C3707F", "#E5B14A", "#F5EDF2"),
        ("sage_stone",         "Sage & Stone",       "#7B8770", "#A5A198", "#C4A97A", "#EFEEE8"),
        ("autumn",             "Autumn",             "#944D32", "#C68050", "#6B7239", "#F5E6D0"),
        ("forest",             "Forest",             "#2C5A3E", "#6B8C5A", "#C69E5E", "#E9EDE0"),
        ("moonlight_silver",   "Moonlight & Silver", "#4A5A6B", "#8FA0B0", "#E5E1D3", "#ECEEF2"),
        ("ember_clay",         "Ember & Clay",       "#A64526", "#C97A50", "#E5B685", "#F4E4D6"),
        ("rose_sage",          "Rose & Sage",        "#B87A85", "#91A188", "#D8B79F", "#F4EBE7"),
        ("storm_sea",          "Storm & Sea",        "#34495E", "#607080", "#8FB0B3", "#DCE2E4"),
        ("honey_cream",        "Honey & Cream",      "#C89B4A", "#E4C08C", "#7A6440", "#FBF5E5"),
        ("berry_bark",         "Berry & Bark",       "#6E2B3A", "#4A362C", "#B08F6B", "#EFE4D6"),
        ("coral_reef",         "Coral & Reef",       "#DE6E5A", "#4A9BA0", "#F0C97C", "#F7ECDF"),
        ("mist_stone",         "Mist & Stone",       "#6B7A82", "#A6B0B3", "#C6C0AF", "#ECEDEA"),
        ("lavender_dusk",      "Lavender & Dusk",    "#6B5C8C", "#A29AB8", "#E5D2A5", "#EFEAF2"),
        ("olive_ochre",        "Olive & Ochre",      "#6E7439", "#B08A3A", "#C8B884", "#EFEBDC"),
        ("snow_sky",           "Snow & Sky",         "#A0B4C4", "#C7D5E0", "#DDBB6E", "#F4F7FA"),
        ("terracotta_fig",     "Terracotta & Fig",   "#B85D3D", "#5B3D57", "#D9AC7A", "#F1DBC5"),
        ("moss_gold",          "Moss & Gold",        "#4C6B3B", "#C89B3A", "#7A5535", "#EBEBD7"),
        ("deep_ocean",         "Deep Ocean",         "#2C556E", "#5E86A0", "#7FB0B8", "#0F2A4A"),
        ("desert_bloom",       "Desert Bloom",       "#C67E4E", "#7A6B4E", "#D8A5A5", "#F2E3D0"),
    ]
    for i, (key, name, primary, secondary, accent, background) in enumerate(stories):
        palette = {
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "background": background,
        }
        op.execute(
            sa.text(
                "INSERT INTO colour_stories (id, key, name, palette, position, is_active) "
                "VALUES (:id, :key, :name, :palette, :position, true)"
            ).bindparams(
                id=f"clr_{key}",
                key=key,
                name=name,
                palette=json.dumps(palette),
                position=i,
            )
        )


def _seed_elements() -> None:
    entries = [
        ("rivers",            "Rivers"),
        ("bridges",           "Bridges"),
        ("birds",             "Birds"),
        ("animals",           "Animals"),
        ("mythical_creatures","Mythical Creatures"),
        ("lanterns",          "Lanterns"),
        ("cabins",            "Cabins"),
        ("gardens",           "Gardens"),
        ("stone_circles",     "Stone Circles"),
        ("lookouts",          "Lookouts"),
        ("lakes",             "Lakes"),
        ("waterfalls",        "Waterfalls"),
        ("market_squares",    "Market Squares"),
        ("hidden_paths",      "Hidden Paths"),
        ("wildflowers",       "Wildflowers"),
        ("ancient_trees",     "Ancient Trees"),
        ("boats",             "Boats"),
        ("harbours",          "Harbours"),
        ("caves",             "Caves"),
        ("shells",            "Shells"),
        ("fireflies",         "Fireflies"),
        ("herbs",             "Herbs"),
        ("orchards",          "Orchards"),
        ("moon_gates",        "Moon Gates"),
    ]
    for i, (key, name) in enumerate(entries):
        op.execute(
            sa.text(
                "INSERT INTO element_options (id, key, name, glyph_key, position, is_active) "
                "VALUES (:id, :key, :name, :glyph, :position, true)"
            ).bindparams(
                id=f"el_{key}",
                key=key,
                name=name,
                glyph=key,
                position=i,
            )
        )
