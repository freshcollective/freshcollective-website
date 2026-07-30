"""
Real-world Places for Discovery, Connection & Belonging.

A Place is a **broad discovery area** — the answer to "what
communities are in my area?". Cities ("Melbourne", "Hobart",
"Auckland") and named regions where a whole area gathers under one
banner ("Blue Mountains", "Sunshine Coast", "Mornington
Peninsula") are the shape of a Place.

**Sub-city localities are never Places.** Suburbs, neighbourhoods,
precincts, individual venue suburbs (Fitzroy, Richmond, Croydon
South) belong on the Collective or Gathering that inhabits them,
not here — the Discover Places surface exists so a member can find
communities nearby, and a per-suburb card would fragment discovery
without adding meaning. Specific locality lives with the
Collective (as descriptive copy) and precise venue lives with the
Gathering (``venue_name``/``venue_address``).

Places are editorial, curated by administrators as the platform
expands into new discovery areas. The picker-driven resolve flow
seeds new rows as ``draft`` so nothing suburb-level ever surfaces
publicly without an admin's say-so.

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
    Float,
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
    # Distinct from admin_note: blurb may be surfaced publicly on
    # Discover Places; admin_note never is.
    blurb: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Internal free-text note authored by administrators. Never
    # surfaced publicly. Distinct from ``blurb`` (which is
    # member-facing editorial copy) — this is the equivalent of
    # a Post-it stuck to the record.
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Curated hero artwork uploaded through the World Management
    # Physical Locations admin surface. When present, takes
    # precedence over the deterministic atmospheric fallback used
    # on Discover Places. This artwork MUST NOT be used on
    # Collective cards, Collective About pages, Atlas Islands,
    # Creator Studio identity, or member profile visuals — it is
    # the geographic Place's identity, not a Collective's.
    hero_artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Accessible alt text for the uploaded artwork. Nullable
    # because artwork can be uploaded before alt text is set;
    # the admin UI encourages authoring it alongside upload.
    artwork_alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Normalised focal point for the artwork (0.0–1.0). Used as
    # CSS ``object-position`` so cropped renderings keep the
    # meaningful centre of the image visible. Defaults to
    # 0.5,0.5 (dead centre) — the safe fallback.
    artwork_focal_x: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    artwork_focal_y: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    # Coordinates — filled from the location autocomplete picker at
    # Place creation time. Nullable because early Places (Phase 0
    # seed style) may have been created without a provider payload.
    # Not surfaced on Discover Places directly; kept for future
    # "near you" surfaces and for deterministic map rendering if
    # that ever ships.
    latitude:  Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # IANA timezone identifier (e.g. "Australia/Melbourne"). Derived
    # from the picker at Place creation. Collectives inherit this as
    # a default when their own timezone is unset.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Deduplication key. The location provider's canonical id for
    # this place (e.g. an OpenStreetMap ``osm_type:osm_id`` pair, a
    # Google Place ID, a Mapbox feature id). Two Creators picking
    # the same city hit the same id and link to the same Place.
    # Nullable to accommodate Places seeded manually before a
    # picker payload existed. See
    # ``docs/foundations/discovery-connection-belonging-location-model.md``.
    provider_place_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, unique=True, index=True
    )
    # Lifecycle vocabulary used by the World Management admin
    # surface:
    #   draft    — being composed; never appears publicly.
    #   active   — visible on Discover Places.
    #   hidden   — preserved for links / history; not surfaced.
    #   archived — retired; still queryable in admin.
    # See migration 093.
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
            "status IN ('draft', 'active', 'hidden', 'archived')",
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
