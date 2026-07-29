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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.config import settings
from app.core.database import get_db
from app.models.place import Place
from app.models.user import User
from app.services.location_providers import (
    LocationSuggestion,
    get_location_provider,
)


router = APIRouter(prefix="/api/places", tags=["places"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlaceSummary(BaseModel):
    """Public shape for a Place. Intentionally minimal — extend when a
    real UI need appears, not before."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    country_code: str
    region: str | None


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
    """List every active Place. Hidden Places are excluded.

    No pagination — Places are editorial and rare; the list is
    expected to stay small enough for a single response for a long
    time. When that changes, extend the shape.
    """
    _ensure_discovery_flag_on()

    rows = db.execute(
        select(Place)
        .where(Place.status == "active")
        .order_by(Place.name)
    ).scalars().all()
    return [PlaceSummary.model_validate(r) for r in rows]


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
    about name or coordinates) and create the Place.
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
