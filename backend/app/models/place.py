"""
Real-world Places for Discovery, Connection & Belonging.

A Place is a geographic entity a person or Collective can be
associated with — a city, or (rarely) a region when the honest
answer really is broader than one city. Places are editorial, curated
by hand as the platform expands into new cities; the seed script is
idempotent and only adds Places where actual Fresh Collective activity
exists.

Places are deliberately separate from ``app.models.platform.Location``
(the Atlas mythic-worldview layer used for Collective aesthetics).
Both concepts survive; nothing about the Atlas changes here.

See ``docs/foundations/discovery-connection-belonging-v1.1.md``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Place(Base):
    """A curated real-world Place (city, sometimes region)."""

    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Kebab-case, unique. Used in URLs (/discover-places/<slug>).
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    # Human-readable name — "Byron Bay", "Melbourne".
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # ISO 3166-1 alpha-2 (e.g. "AU"). Editorial choice, not derived
    # from geocoding — the operator names what the Place is.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    # Optional wider containing region for disambiguation ("Northern
    # Rivers", "Greater Melbourne"). Prefer cities over regions; only
    # populate when the wider frame is genuinely meaningful.
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Editorial description — a few paragraphs about what Fresh
    # Collective looks like here. Nullable while the copy is drafted.
    blurb: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Only two statuses: 'active' (visible) and 'hidden' (not surfaced
    # anywhere but preserved for links/history). No 'deleted' — Places
    # are curated and rare; removing one is an editorial decision, not
    # a lifecycle event.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'hidden')",
            name="places_status_check",
        ),
    )


class SpacePlace(Base):
    """Join row — a Collective is associated with a Place.

    A Collective may be associated with more than one Place (a
    creator who splits their time between two cities, a Local Circle
    that gathers in both). The join is unordered; no primary/secondary
    distinction is stored until a concrete use case appears for one.
    """

    __tablename__ = "space_places"

    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    place_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("places.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
