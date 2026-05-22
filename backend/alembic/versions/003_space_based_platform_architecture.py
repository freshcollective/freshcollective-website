"""Add Space-based platform architecture.

Revision ID: 003
Revises: 002
Create Date: 2026-05-11

Changes:
  1. Extend users.role CHECK constraint to include 'creator'
  2. Create platform enum types
  3. Create platform tables:
       spaces, space_memberships, creator_profiles,
       pathways, pathway_steps, enrollments, step_progress,
       events, community_posts, post_comments
  4. Seed V1 data (idempotent ON CONFLICT DO NOTHING):
       - Fresh Collective Space
       - REAL Journey, Growth, Transformation, Essence Pathways

This migration is purely additive — no existing tables or data are touched
beyond the role CHECK constraint update.

Implementation note: all DDL is written as raw SQL via op.execute() to bypass
SQLAlchemy's type registry. When env.py imports the platform models, SQLAlchemy
registers the SAEnum types with create_type=True. If op.create_table() is used
with those enum columns, SQLAlchemy re-resolves the type from its registry and
tries to CREATE TYPE even when create_type=False is passed — causing a
DuplicateObject error after our explicit CREATE TYPE runs. Raw SQL avoids this
entirely and is more explicit and stable across SQLAlchemy versions.
"""

from alembic import op

# ---------------------------------------------------------------------------
# Fixed seed IDs — stable across environments
# ---------------------------------------------------------------------------
FC_SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"
PATHWAY_REAL_JOURNEY_ID = "b0bd060b-1c83-41ef-8055-1870b258b75a"
PATHWAY_GROWTH_ID = "e99be637-12d2-4e8a-b4b3-89028d6a8ace"
PATHWAY_TRANSFORMATION_ID = "e835d32d-78c7-4a49-a16b-535aa56b8b41"
PATHWAY_ESSENCE_ID = "c81e4617-c625-484c-adcc-23c195ab7059"

NOW = "2026-05-11 00:00:00"

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Extend users.role CHECK constraint ─────────────────────────────
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('user', 'creator', 'admin'))"
    )

    # ── 2. Create enum types (IF NOT EXISTS via DO block) ─────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE space_status_enum AS ENUM ('draft', 'active', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE space_role_enum AS ENUM ('learner', 'moderator', 'creator');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE space_membership_status_enum AS ENUM ('active', 'paused', 'removed');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE pathway_status_enum AS ENUM ('draft', 'active', 'coming_soon', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE step_content_type_enum AS ENUM ('text', 'video', 'reflection', 'exercise', 'audio');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE enrollment_status_enum AS ENUM ('active', 'paused', 'completed');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE event_location_type_enum AS ENUM ('zoom', 'in_person', 'async_recorded');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;

        DO $$ BEGIN
            CREATE TYPE post_type_enum AS ENUM ('prompt', 'reflection', 'discussion', 'announcement');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── 3. Create tables (raw SQL — bypasses SQLAlchemy type registry) ────

    op.execute("""
        CREATE TABLE IF NOT EXISTS spaces (
            id              TEXT PRIMARY KEY,
            slug            VARCHAR(100) NOT NULL,
            name            VARCHAR(200) NOT NULL,
            tagline         VARCHAR(300),
            description     TEXT,
            cover_image_url VARCHAR(500),
            creator_id      TEXT REFERENCES users(id) ON DELETE RESTRICT,
            is_public       BOOLEAN NOT NULL DEFAULT true,
            status          space_status_enum NOT NULL DEFAULT 'active',
            created_at      TIMESTAMP NOT NULL DEFAULT now(),
            updated_at      TIMESTAMP NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_spaces_slug       ON spaces(slug);
        CREATE        INDEX IF NOT EXISTS ix_spaces_creator_id ON spaces(creator_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS space_memberships (
            id        TEXT PRIMARY KEY,
            user_id   TEXT NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
            space_id  TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            role      space_role_enum             NOT NULL DEFAULT 'learner',
            status    space_membership_status_enum NOT NULL DEFAULT 'active',
            joined_at TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT space_memberships_user_space_unique UNIQUE (user_id, space_id)
        );
        CREATE INDEX IF NOT EXISTS ix_space_memberships_user_id   ON space_memberships(user_id);
        CREATE INDEX IF NOT EXISTS ix_space_memberships_space_id  ON space_memberships(space_id);
        CREATE INDEX IF NOT EXISTS ix_space_memberships_space_user ON space_memberships(space_id, user_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS creator_profiles (
            user_id      TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            display_name VARCHAR(200),
            bio          TEXT,
            avatar_url   VARCHAR(500),
            website_url  VARCHAR(500),
            is_public    BOOLEAN NOT NULL DEFAULT true,
            created_at   TIMESTAMP NOT NULL DEFAULT now(),
            updated_at   TIMESTAMP NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pathways (
            id              TEXT PRIMARY KEY,
            space_id        TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            slug            VARCHAR(100) NOT NULL,
            title           VARCHAR(200) NOT NULL,
            description     TEXT,
            cover_image_url VARCHAR(500),
            is_sequential   BOOLEAN NOT NULL DEFAULT true,
            status          pathway_status_enum NOT NULL DEFAULT 'active',
            position        INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP NOT NULL DEFAULT now(),
            updated_at      TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT pathways_space_slug_unique UNIQUE (space_id, slug)
        );
        CREATE INDEX IF NOT EXISTS ix_pathways_space_id       ON pathways(space_id);
        CREATE INDEX IF NOT EXISTS ix_pathways_space_position ON pathways(space_id, position);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pathway_steps (
            id                TEXT PRIMARY KEY,
            pathway_id        TEXT NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            slug              VARCHAR(100) NOT NULL,
            title             VARCHAR(300) NOT NULL,
            content_type      step_content_type_enum NOT NULL DEFAULT 'text',
            content_body      TEXT,
            content_url       VARCHAR(500),
            estimated_minutes INTEGER,
            is_required       BOOLEAN NOT NULL DEFAULT true,
            position          INTEGER NOT NULL DEFAULT 0,
            created_at        TIMESTAMP NOT NULL DEFAULT now(),
            updated_at        TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT pathway_steps_pathway_slug_unique UNIQUE (pathway_id, slug)
        );
        CREATE INDEX IF NOT EXISTS ix_pathway_steps_pathway_id       ON pathway_steps(pathway_id);
        CREATE INDEX IF NOT EXISTS ix_pathway_steps_pathway_position ON pathway_steps(pathway_id, position);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS enrollments (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
            pathway_id   TEXT NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            status       enrollment_status_enum NOT NULL DEFAULT 'active',
            enrolled_at  TIMESTAMP NOT NULL DEFAULT now(),
            completed_at TIMESTAMP,
            CONSTRAINT enrollments_user_pathway_unique UNIQUE (user_id, pathway_id)
        );
        CREATE INDEX IF NOT EXISTS ix_enrollments_user_id      ON enrollments(user_id);
        CREATE INDEX IF NOT EXISTS ix_enrollments_pathway_id   ON enrollments(pathway_id);
        CREATE INDEX IF NOT EXISTS ix_enrollments_user_pathway ON enrollments(user_id, pathway_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS step_progress (
            id               TEXT PRIMARY KEY,
            user_id          TEXT NOT NULL REFERENCES users(id)         ON DELETE CASCADE,
            step_id          TEXT NOT NULL REFERENCES pathway_steps(id) ON DELETE CASCADE,
            completed_at     TIMESTAMP NOT NULL DEFAULT now(),
            reflection_text  TEXT,
            CONSTRAINT step_progress_user_step_unique UNIQUE (user_id, step_id)
        );
        CREATE INDEX IF NOT EXISTS ix_step_progress_user_id   ON step_progress(user_id);
        CREATE INDEX IF NOT EXISTS ix_step_progress_step_id   ON step_progress(step_id);
        CREATE INDEX IF NOT EXISTS ix_step_progress_user_step ON step_progress(user_id, step_id);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id            TEXT PRIMARY KEY,
            space_id      TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            created_by_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            title         VARCHAR(300) NOT NULL,
            description   TEXT,
            starts_at     TIMESTAMP NOT NULL,
            ends_at       TIMESTAMP,
            location_type event_location_type_enum NOT NULL DEFAULT 'zoom',
            location_url  VARCHAR(500),
            recording_url VARCHAR(500),
            is_published  BOOLEAN NOT NULL DEFAULT false,
            created_at    TIMESTAMP NOT NULL DEFAULT now(),
            updated_at    TIMESTAMP NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_events_space_id       ON events(space_id);
        CREATE INDEX IF NOT EXISTS ix_events_created_by_id  ON events(created_by_id);
        CREATE INDEX IF NOT EXISTS ix_events_space_starts_at ON events(space_id, starts_at);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS community_posts (
            id         TEXT PRIMARY KEY,
            space_id   TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            author_id  TEXT NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
            post_type  post_type_enum NOT NULL DEFAULT 'discussion',
            title      VARCHAR(300),
            body       TEXT NOT NULL,
            is_pinned  BOOLEAN NOT NULL DEFAULT false,
            is_visible BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_community_posts_space_id      ON community_posts(space_id);
        CREATE INDEX IF NOT EXISTS ix_community_posts_author_id     ON community_posts(author_id);
        CREATE INDEX IF NOT EXISTS ix_community_posts_space_created ON community_posts(space_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_community_posts_space_pinned  ON community_posts(space_id, is_pinned);
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS post_comments (
            id         TEXT PRIMARY KEY,
            post_id    TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            author_id  TEXT NOT NULL REFERENCES users(id)           ON DELETE CASCADE,
            body       TEXT NOT NULL,
            is_visible BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_post_comments_post_id      ON post_comments(post_id);
        CREATE INDEX IF NOT EXISTS ix_post_comments_author_id    ON post_comments(author_id);
        CREATE INDEX IF NOT EXISTS ix_post_comments_post_created ON post_comments(post_id, created_at);
    """)

    # ── 4. Seed: Fresh Collective Space + Pathways (idempotent) ──────────
    op.execute(f"""
        INSERT INTO spaces (id, slug, name, tagline, description, is_public, status, created_at, updated_at)
        VALUES (
            '{FC_SPACE_ID}',
            'the-natural-leader-hub',
            'The Natural Leader Hub',
            'An experiential learning space for women ready to grow.',
            'The Natural Leader Hub is the flagship space on the platform. Start with the REAL Journey — the foundational pathway — then explore Growth and beyond.',
            true,
            'active',
            '{NOW}',
            '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    for pathway_id, slug, title, description, status, position in [
        (
            PATHWAY_REAL_JOURNEY_ID,
            "real-journey",
            "REAL Journey",
            "The foundational pathway. Four phases — Recognise, Explore, Align, Lead — to help you reconnect, understand yourself, and move forward with intention.",
            "active",
            1,
        ),
        (
            PATHWAY_GROWTH_ID,
            "growth",
            "Growth",
            "Deepen your self-awareness, build self-trust, and step into your uniqueness.",
            "active",
            2,
        ),
        (
            PATHWAY_TRANSFORMATION_ID,
            "transformation",
            "Transformation",
            "Embodiment, Vision, and Purpose. Coming soon.",
            "coming_soon",
            3,
        ),
        (
            PATHWAY_ESSENCE_ID,
            "essence",
            "Essence",
            "Harmony, Creativity, and Manifestation. Coming soon.",
            "coming_soon",
            4,
        ),
    ]:
        op.execute(f"""
            INSERT INTO pathways (id, space_id, slug, title, description, is_sequential, status, position, created_at, updated_at)
            VALUES (
                '{pathway_id}',
                '{FC_SPACE_ID}',
                '{slug}',
                '{title}',
                '{description}',
                true,
                '{status}',
                {position},
                '{NOW}',
                '{NOW}'
            )
            ON CONFLICT (id) DO NOTHING;
        """)


def downgrade() -> None:
    # Remove seed data
    op.execute(f"DELETE FROM pathways WHERE space_id = '{FC_SPACE_ID}'")
    op.execute(f"DELETE FROM spaces WHERE id = '{FC_SPACE_ID}'")

    # Drop tables in reverse dependency order
    for table in [
        "post_comments",
        "community_posts",
        "events",
        "step_progress",
        "enrollments",
        "pathway_steps",
        "pathways",
        "creator_profiles",
        "space_memberships",
        "spaces",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop enum types
    for enum_name in [
        "post_type_enum",
        "event_location_type_enum",
        "enrollment_status_enum",
        "step_content_type_enum",
        "pathway_status_enum",
        "space_membership_status_enum",
        "space_role_enum",
        "space_status_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    # Restore original role constraint
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('user', 'admin'))"
    )
