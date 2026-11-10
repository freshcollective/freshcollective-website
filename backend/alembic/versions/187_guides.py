"""Guides — free public articles, with one settings row beside them.

Two tables, both new. Nothing existing is touched, so this is additive
and reversible in the ordinary way.

``guides``
    One row per article. Separate from ``world_guide_documents`` on
    purpose: that table is versioned governance with acceptance
    records, and an article needs none of it. The two share an admin
    *shape* and no data.

    ``featured`` carries a partial unique index rather than an
    application rule. "At most one featured Guide" is the kind of
    invariant that survives exactly as long as every code path
    remembers it, and the index means a second featured row is a
    database error rather than a quietly wrong home page. Postgres
    treats a partial index on ``(featured) WHERE featured`` as "at
    most one row where featured is true", which is the property
    wanted; ``false`` rows are not in the index at all.

``guide_settings``
    One row, ever. ``CHECK (id = 'singleton')`` is what makes that
    true — without it this is simply a table that will grow a second
    row one day and leave two answers to a question with one answer.

    It holds ``starter_kit_url`` and nothing else today. NULL is the
    shipped state and means the Creator Starter Kit band on /guides
    and the card in every Guide's sidebar render *not at all* — no
    placeholder, no disabled button. The row is seeded here with a
    NULL URL so the admin screen has something to read and update
    rather than having to create-or-update on first save.

Revision ID: 187
Revises: 186
"""

from alembic import op
import sqlalchemy as sa

revision = "187"
down_revision = "186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guides",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("standfirst", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("hero_image_url", sa.Text(), nullable=True),
        sa.Column("hero_image_alt", sa.String(length=300), nullable=True),
        sa.Column("seo_title", sa.String(length=120), nullable=True),
        sa.Column("seo_description", sa.String(length=300), nullable=True),
        sa.Column(
            "author_name", sa.String(length=120),
            nullable=False, server_default="Linds",
        ),
        sa.Column(
            "featured", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "status", sa.String(length=16),
            nullable=False, server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "reading_time_minutes", sa.Integer(),
            nullable=False, server_default="1",
        ),
        # The call to action, if the author sets one. All four together
        # or none: a heading with no link is a dead end, and a link with
        # no label has nothing to click.
        sa.Column("cta_heading", sa.String(length=160), nullable=True),
        sa.Column("cta_text", sa.String(length=300), nullable=True),
        sa.Column("cta_label", sa.String(length=80), nullable=True),
        sa.Column("cta_href", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "category IN ('starting', 'growing', 'tools')",
            name="ck_guides_category",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name="ck_guides_status",
        ),
        # Alt text is not optional once there is an image to describe.
        # Enforced here as well as in the editor because the editor is
        # a UX constraint and this is the one that survives a direct
        # HTTP call.
        sa.CheckConstraint(
            "hero_image_url IS NULL "
            "OR (hero_image_alt IS NOT NULL AND length(trim(hero_image_alt)) > 0)",
            name="ck_guides_hero_alt_present",
        ),
        sa.CheckConstraint(
            "(cta_heading IS NULL AND cta_text IS NULL "
            " AND cta_label IS NULL AND cta_href IS NULL) "
            "OR (cta_heading IS NOT NULL AND cta_text IS NOT NULL "
            "    AND cta_label IS NOT NULL AND cta_href IS NOT NULL)",
            name="ck_guides_cta_all_or_nothing",
        ),
    )

    op.create_index("ix_guides_slug", "guides", ["slug"], unique=True)
    # The public list's only ordering.
    op.create_index(
        "ix_guides_status_published_at", "guides", ["status", "published_at"],
    )
    # At most one featured Guide, enforced where it cannot be forgotten.
    op.create_index(
        "ux_guides_one_featured", "guides", ["featured"],
        unique=True, postgresql_where=sa.text("featured"),
    )

    op.create_table(
        "guide_settings",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("starter_kit_url", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 'singleton'", name="ck_guide_settings_singleton"),
    )
    # Seeded empty, so reading the setting never has to cope with "no
    # row yet" and saving is an update rather than an upsert.
    op.execute(
        "INSERT INTO guide_settings (id, starter_kit_url) "
        "VALUES ('singleton', NULL)"
    )


def downgrade() -> None:
    op.drop_table("guide_settings")
    op.drop_index("ux_guides_one_featured", table_name="guides")
    op.drop_index("ix_guides_status_published_at", table_name="guides")
    op.drop_index("ix_guides_slug", table_name="guides")
    op.drop_table("guides")
