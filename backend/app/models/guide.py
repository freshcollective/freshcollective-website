"""SQLAlchemy models for Guides — free, public articles.

Shape mirrors migration 187. Deliberately separate from
``world_guide.py``: that is versioned governance with acceptance
records, and an article shares its admin *shape* and none of its data.
The only thing borrowed is :func:`estimate_reading_time_minutes`, and
that is borrowed rather than copied so the platform has one answer to
"how long is this to read" instead of two that drift.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enum-shaped string constants — kept in sync with migration 187's CHECKs.
# ---------------------------------------------------------------------------

#: Stored as stable slugs, displayed from one map in the frontend, so
#: renaming "Starting your Collective" is a copy change rather than a
#: data migration.
GUIDE_CATEGORIES: tuple[str, ...] = ("starting", "growing", "tools")

GUIDE_STATUSES: tuple[str, ...] = ("draft", "published")

#: The author the byline treats as the house voice. Any other name
#: renders as a plain "By {name}" — see ``frontend/src/lib/guides.ts``.
DEFAULT_AUTHOR_NAME = "Linds"


class Guide(Base):
    """One article.

    ``published_at`` is set the first time a Guide is published and
    kept thereafter, so unpublishing and republishing does not reset
    the date a reader was first shown. ``updated_at`` is the one the
    sitemap reports, because that is what actually changed.
    """

    __tablename__ = "guides"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    standfirst: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(48), nullable=False)

    hero_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    hero_image_alt: Mapped[str | None] = mapped_column(String(300), nullable=True)

    seo_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    author_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default=DEFAULT_AUTHOR_NAME,
    )
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    reading_time_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )

    cta_heading: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cta_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cta_href: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('starting', 'growing', 'tools')",
            name="ck_guides_category",
        ),
        CheckConstraint(
            "status IN ('draft', 'published')", name="ck_guides_status",
        ),
        CheckConstraint(
            "hero_image_url IS NULL "
            "OR (hero_image_alt IS NOT NULL AND length(trim(hero_image_alt)) > 0)",
            name="ck_guides_hero_alt_present",
        ),
        CheckConstraint(
            "(cta_heading IS NULL AND cta_text IS NULL "
            " AND cta_label IS NULL AND cta_href IS NULL) "
            "OR (cta_heading IS NOT NULL AND cta_text IS NOT NULL "
            "    AND cta_label IS NOT NULL AND cta_href IS NOT NULL)",
            name="ck_guides_cta_all_or_nothing",
        ),
        Index("ix_guides_slug", "slug", unique=True),
        Index("ix_guides_status_published_at", "status", "published_at"),
        # At most one featured Guide. Declared here as well as in the
        # migration so ``alembic check`` does not read it as drift.
        Index(
            "ux_guides_one_featured", "featured",
            unique=True, postgresql_where=sa_text("featured"),
        ),
    )


class GuideSettings(Base):
    """One row, ever — see the CHECK.

    Holds the Creator Starter Kit link and nothing else today. NULL
    means the Starter Kit band on ``/guides`` and the card in every
    Guide's sidebar do not render at all, which is the shipped state
    until the kit exists.
    """

    __tablename__ = "guide_settings"

    SINGLETON_ID = "singleton"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    starter_kit_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 'singleton'", name="ck_guide_settings_singleton"),
    )
