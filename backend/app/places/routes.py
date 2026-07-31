"""
/api/places — the read + resolve surface for real-world Places.

Places are the geographic layer of the Discovery, Connection &
Belonging pillar (see
``docs/foundations/discovery-connection-belonging-v1.1.md``).

Endpoints:

  * ``GET  /api/places``             — list active Places (public read)
  * ``POST /api/places/lookup``      — autocomplete suggestions
                                        (Creator-only, proxied via the
                                        configured location provider)
  * ``POST /api/places/resolve``     — turn a picker selection into a
                                        stored Place row, deduplicating
                                        by provider_place_id

The whole surface is gated by ``settings.discovery_pillar_enabled``.
When the flag is off every endpoint returns 503 — matching the
convention set by Community Care — so a half-built surface can't be
discovered by accident.

Provider abstraction lives in
``app/services/location_providers/`` — see there for how to swap
away from Nominatim later.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.config import settings
from app.core.database import get_db
from app.models.place import Place, SpacePlace
from app.models.platform import Event, Space, SpaceStatus
from app.models.user import User
from app.spaces.schemas import PublicSpaceCard
from app.services.location_providers import (
    LocationSuggestion,
    get_location_provider,
)
from app.spaces.routes import hydrate_public_space_cards


router = APIRouter(prefix="/api/places", tags=["places"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlaceSummary(BaseModel):
    """Public shape for a Place.

    Includes curated artwork fields when set. Discover Places
    prefers ``hero_artwork_url`` over the deterministic atmosphere
    fallback; when it is ``None``, the client falls back to the
    per-slug gradient. The focal point governs cropped renderings
    (CSS ``object-position``) so meaningful subjects stay in-frame.

    Also carries a small "what's happening here" summary — the
    admin-authored blurb, an aggregate theme list from linked
    active Collectives, and counts — so a Discover Places card can
    render without a second round-trip. Nothing here reveals the
    identity of individual Collectives; that's the /discover-places
    detail page's job (not built yet).
    """

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    blurb: str | None
    themes: list[str]
    collective_count: int
    upcoming_gathering_count: int


class PlaceGathering(BaseModel):
    """Member-safe public projection of an upcoming Gathering on a
    Physical Location detail page. Never exposes venue address or
    private access instructions — those are enrolment-gated on the
    Gathering's own detail page."""

    id: str
    title: str
    space_slug: str
    space_name: str
    starts_at: datetime
    ends_at: datetime | None
    gathering_type: str
    attendance_format: str        # online | in_person | hybrid
    venue_name: str | None        # coarse locality only — never the address
    booking_access_type: str
    capacity: int | None
    ticket_price_cents: int | None
    ticket_currency: str | None
    thumbnail_url: str | None


class PlaceDetail(BaseModel):
    """Full public detail for a single Physical Location — powers the
    /discover-places/{slug} member page. Bundles the location's own
    payload, the list of Collectives that belong here (in the same
    ``PublicSpaceCard`` shape the Explore Collectives listing uses,
    so both pages render with the same card component), and the
    upcoming Gatherings that are eligible for members to see.

    Admin-only fields never leak: ``admin_note``, coordinates,
    ``provider_place_id`` and status are all absent."""

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    blurb: str | None
    themes: list[str]
    collective_count: int
    upcoming_gathering_count: int
    collectives: list[PublicSpaceCard]
    upcoming_gatherings: list[PlaceGathering]


class LookupRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)


class LookupResult(BaseModel):
    """One suggestion row the picker renders."""

    provider_place_id: str
    display: str
    name: str
    region: str
    country: str
    country_code: str
    latitude: float
    longitude: float

    @classmethod
    def from_suggestion(cls, s: LocationSuggestion) -> "LookupResult":
        return cls(
            provider_place_id=s.provider_place_id,
            display=s.display,
            name=s.name,
            region=s.region,
            country=s.country,
            country_code=s.country_code,
            latitude=s.latitude,
            longitude=s.longitude,
        )


class LookupResponse(BaseModel):
    results: list[LookupResult]


class ResolveRequest(BaseModel):
    """The picker's canonical id is enough — the provider is
    re-queried server-side to get the authoritative payload. The
    client cannot spoof a Place's name or coordinates."""

    provider_place_id: str = Field(..., min_length=1, max_length=200)


class ResolveResponse(BaseModel):
    """The Place row that was found or created."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None
    latitude: float | None
    longitude: float | None
    timezone: str | None
    provider_place_id: str | None
    created: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_discovery_flag_on() -> None:
    """Refuse when the Discovery pillar is not yet enabled."""
    if not settings.discovery_pillar_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discovery is not yet enabled on this deployment.",
        )


def _slugify(name: str, country_code: str) -> str:
    """Derive a URL-safe slug from a Place name.

    Kept deterministic and readable — "Byron Bay, AU" → "byron-bay".
    Collisions are handled by ``_resolve_slug`` at insert time.
    """
    base = "".join(
        c.lower() if c.isalnum() else "-"
        for c in name.strip()
    )
    # Collapse runs of dashes, strip edges.
    while "--" in base:
        base = base.replace("--", "-")
    return base.strip("-") or country_code.lower()


def _resolve_slug(db: Session, base_slug: str) -> str:
    """Find a free slug. Appends ``-2``, ``-3``... on collision.

    Rare in practice — cities that share a name across countries
    would collide (e.g. Melbourne AU vs Melbourne US), and this
    ensures the second one gets ``melbourne-2`` rather than
    failing. Deduplication by provider_place_id happens above this;
    slug collision is only reached for genuinely different Places
    that share a name.
    """
    if not db.execute(select(Place).where(Place.slug == base_slug)).scalar_one_or_none():
        return base_slug
    n = 2
    while True:
        candidate = f"{base_slug}-{n}"
        if not db.execute(select(Place).where(Place.slug == candidate)).scalar_one_or_none():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PlaceSummary])
def list_places(db: Session = Depends(get_db)) -> list[PlaceSummary]:
    """List every active Place with a small activity summary.

    Draft, hidden, and archived Places never appear here — only
    ``active`` rows. No pagination — Places are editorial and rare;
    the list is expected to stay small enough for a single response
    for a long time. When that changes, extend the shape.
    """
    _ensure_discovery_flag_on()

    places = db.execute(
        select(Place)
        .where(Place.status == "active")
        .order_by(Place.name)
    ).scalars().all()

    if not places:
        return []

    place_ids = [p.id for p in places]

    # Active Collective count per Place — one aggregate query.
    count_rows = db.execute(
        select(SpacePlace.place_id, func.count(Space.id))
        .join(Space, Space.id == SpacePlace.space_id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
        )
        .group_by(SpacePlace.place_id)
    ).all()
    counts_by_place: dict[str, int] = {pid: int(c) for pid, c in count_rows}

    # Themes aggregated from linked active Collectives — dedup +
    # preserve first-appearance order for stability. Fetched in one
    # query so we don't do N+1.
    theme_rows = db.execute(
        select(SpacePlace.place_id, Space.themes)
        .join(Space, Space.id == SpacePlace.space_id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
        )
    ).all()
    themes_by_place: dict[str, list[str]] = {pid: [] for pid in place_ids}
    for place_id, themes in theme_rows:
        seen = set(themes_by_place[place_id])
        for t in themes or []:
            if t and t not in seen:
                themes_by_place[place_id].append(t)
                seen.add(t)

    # Upcoming published gatherings per Place — Events on linked
    # active Collectives with ``starts_at`` in the future.
    now = datetime.utcnow()
    gather_rows = db.execute(
        select(SpacePlace.place_id, func.count(Event.id))
        .join(Space, Space.id == SpacePlace.space_id)
        .join(Event, Event.space_id == Space.id)
        .where(
            SpacePlace.place_id.in_(place_ids),
            Space.status == SpaceStatus.active,
            Event.is_published.is_(True),
            Event.starts_at > now,
        )
        .group_by(SpacePlace.place_id)
    ).all()
    upcoming_by_place: dict[str, int] = {pid: int(c) for pid, c in gather_rows}

    return [
        PlaceSummary(
            id=p.id,
            slug=p.slug,
            name=p.name,
            country_code=p.country_code,
            region=p.region,
            hero_artwork_url=p.hero_artwork_url,
            artwork_alt_text=p.artwork_alt_text,
            artwork_focal_x=p.artwork_focal_x,
            artwork_focal_y=p.artwork_focal_y,
            blurb=p.blurb,
            themes=themes_by_place.get(p.id, []),
            collective_count=counts_by_place.get(p.id, 0),
            upcoming_gathering_count=upcoming_by_place.get(p.id, 0),
        )
        for p in places
    ]


@router.get("/{slug}", response_model=PlaceDetail)
def get_place(slug: str, db: Session = Depends(get_db)) -> PlaceDetail:
    """Public detail for a single active Physical Location.

    Draft, hidden, and archived Locations 404 here — the same rule
    the list surface uses. The payload bundles the Location's own
    public fields, the Collectives that belong here (rendered with
    the same ``PublicSpaceCard`` shape as Explore Collectives so
    the same card component can be reused visually), and the
    upcoming public / effectively-public Gatherings on those
    Collectives.
    """
    _ensure_discovery_flag_on()

    place = db.execute(
        select(Place).where(Place.slug == slug, Place.status == "active")
    ).scalar_one_or_none()
    if place is None:
        raise HTTPException(status_code=404, detail="Physical Location not found.")

    # Linked Collectives — same public filter as /api/public/spaces
    # (active + public + not auto-grant). ``hydrate_public_space_cards``
    # produces the identical shape the Explore listing uses.
    linked_spaces = db.execute(
        select(Space)
        .join(SpacePlace, SpacePlace.space_id == Space.id)
        .where(
            SpacePlace.place_id == place.id,
            Space.status == SpaceStatus.active,
            Space.is_public.is_(True),
            Space.auto_grant_role.is_(None),
        )
        .order_by(Space.created_at)
    ).scalars().all()
    collectives = hydrate_public_space_cards(list(linked_spaces), db)

    # Upcoming gatherings — published, future, and either explicitly
    # public or effectively public (``paid_separately`` tickets show
    # up on the paid Gathering surface for anyone). The same rule the
    # Space events endpoint applies for anonymous callers.
    gatherings: list[PlaceGathering] = []
    if linked_spaces:
        space_by_id = {s.id: s for s in linked_spaces}
        now = datetime.utcnow()
        event_rows = db.execute(
            select(Event)
            .where(
                Event.space_id.in_(list(space_by_id.keys())),
                Event.is_published.is_(True),
                Event.starts_at > now,
                Event.status == "active",
                (Event.is_public.is_(True)) | (Event.booking_access_type == "paid_separately"),
            )
            .order_by(Event.starts_at)
            .limit(20)
        ).scalars().all()
        gatherings = [
            PlaceGathering(
                id=e.id,
                title=e.title,
                space_slug=space_by_id[e.space_id].slug,
                space_name=space_by_id[e.space_id].name,
                starts_at=e.starts_at,
                ends_at=e.ends_at,
                gathering_type=e.gathering_type,
                attendance_format=e.attendance_format,
                # venue_name is the coarse locality (e.g. "Private
                # residence · South Croydon"); the full address stays
                # gated on the Gathering's own detail page.
                venue_name=e.venue_name,
                booking_access_type=e.booking_access_type,
                capacity=e.capacity,
                ticket_price_cents=e.ticket_price_cents,
                ticket_currency=e.ticket_currency,
                thumbnail_url=e.thumbnail_url,
            )
            for e in event_rows
        ]

    # Aggregate themes + counts identical to the list endpoint so the
    # detail card header can display the same numbers.
    seen: set[str] = set()
    theme_order: list[str] = []
    for s in linked_spaces:
        for t in s.themes or []:
            if t and t not in seen:
                seen.add(t)
                theme_order.append(t)
    upcoming_all_count = db.execute(
        select(func.count(Event.id)).where(
            Event.space_id.in_([s.id for s in linked_spaces]) if linked_spaces else False,
            Event.is_published.is_(True),
            Event.starts_at > datetime.utcnow(),
        )
    ).scalar_one() if linked_spaces else 0

    return PlaceDetail(
        id=place.id,
        slug=place.slug,
        name=place.name,
        country_code=place.country_code,
        region=place.region,
        hero_artwork_url=place.hero_artwork_url,
        artwork_alt_text=place.artwork_alt_text,
        artwork_focal_x=place.artwork_focal_x,
        artwork_focal_y=place.artwork_focal_y,
        blurb=place.blurb,
        themes=theme_order,
        collective_count=len(linked_spaces),
        upcoming_gathering_count=int(upcoming_all_count),
        collectives=collectives,
        upcoming_gatherings=gatherings,
    )


@router.post("/lookup", response_model=LookupResponse)
async def lookup_places(
    payload: LookupRequest,
    _user: User = Depends(get_creator_user),
) -> LookupResponse:
    """Autocomplete for the Place & Feel picker.

    Creator-only. The response never touches the database — it is a
    thin proxy to the configured provider. The client posts what the
    Creator picked back to ``/resolve`` when they select a row.
    """
    _ensure_discovery_flag_on()

    provider = get_location_provider()
    suggestions = await provider.search(payload.query, limit=6)
    return LookupResponse(
        results=[LookupResult.from_suggestion(s) for s in suggestions]
    )


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_place(
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_creator_user),
) -> ResolveResponse:
    """Turn a picker selection into a persisted Place row.

    Idempotent by ``provider_place_id``: if a Place with the same
    provider id already exists, return it. Otherwise, re-fetch the
    canonical suggestion from the provider (so the client cannot lie
    about name or coordinates) and create the Place **as a draft**.

    Draft status is deliberate: the provider result may be at any
    granularity (a suburb, a venue, an obscure hamlet), but
    Discover Places is a curated surface for **broad discovery
    areas** (see ``app.models.place``). Marking picker-created rows
    as ``draft`` means:

      * a Creator's Collective can still be linked to the Place
        immediately (SpacePlace is orthogonal to status);
      * Discover Places never surfaces the row until an admin
        reviews it and either promotes it to ``active`` (with the
        broad name they want members to see), merges it into an
        existing broader Place, or leaves it as draft.

    The public-facing name is therefore always an admin decision,
    never a raw provider payload.
    """
    _ensure_discovery_flag_on()

    existing = db.execute(
        select(Place).where(Place.provider_place_id == payload.provider_place_id)
    ).scalar_one_or_none()
    if existing is not None:
        return _to_response(existing, created=False)

    provider = get_location_provider()
    suggestion = await provider.fetch(payload.provider_place_id)
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That place could not be resolved. Please pick again.",
        )

    place = Place(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=_resolve_slug(db, _slugify(suggestion.name, suggestion.country_code)),
        name=suggestion.name,
        country_code=suggestion.country_code or "??",
        region=suggestion.region or None,
        latitude=suggestion.latitude,
        longitude=suggestion.longitude,
        timezone=suggestion.timezone,
        provider_place_id=suggestion.provider_place_id,
        status="draft",
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    return _to_response(place, created=True)


def _to_response(place: Place, *, created: bool) -> ResolveResponse:
    return ResolveResponse(
        id=place.id,
        slug=place.slug,
        name=place.name,
        country_code=place.country_code,
        region=place.region,
        latitude=place.latitude,
        longitude=place.longitude,
        timezone=place.timezone,
        provider_place_id=place.provider_place_id,
        created=created,
    )
