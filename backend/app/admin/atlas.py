"""
The Atlas — admin endpoints for the curated collection of Locations
(Atlas Volume I, Version 1.1, Chapters Nine + Ten).

Only Fresh Collective administrators reach these routes. Creators never
manage the Atlas — they choose a Location for their collective, but the
authoring surface for Locations (name, description, artwork, taxonomy,
recommendation metadata) lives here.

Endpoints under `/api/admin/atlas/*`:

  GET    /locations                              — list with collective counts
  GET    /locations/{key}                        — detail
  POST   /locations                              — create
  PATCH  /locations/{key}                        — update fields
  POST   /locations/{key}/hero-artwork           — upload hero image
  POST   /locations/{key}/thumbnail-artwork      — upload thumbnail image
  DELETE /locations/{key}/hero-artwork           — clear hero
  DELETE /locations/{key}/thumbnail-artwork      — clear thumbnail
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.storage import delete_file, save_image_with_thumbnail
from app.models.platform import Location, Space
from app.models.user import User


router = APIRouter(prefix="/api/admin/atlas", tags=["admin-atlas"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

LOCATION_TYPES: set[str] = {"ATLAS", "CORNERSTONE", "COMMUNITY"}
_LOCATION_TYPES_MSG = "Location type must be 'ATLAS', 'COMMUNITY', or 'CORNERSTONE'."


class LocationSummary(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    status: str
    location_type: str
    hero_artwork_url: str | None
    thumbnail_artwork_url: str | None
    biome: str | None
    archipelago: str | None
    collective_count: int
    position: int


class CollectiveInLocation(BaseModel):
    id: str
    slug: str
    name: str
    status: str


class LocationDetail(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    atlas_entry: str | None
    status: str
    location_type: str
    # Single master artwork — `hero_artwork_url` is the storage column; the
    # Admin UI treats it as "the artwork" and the same URL is served in every
    # display context. Future thumbnail-size generation would derive from
    # this same source without changing the field name.
    hero_artwork_url: str | None
    # Kept for backward-compatible payloads; the current UI does not surface
    # a separate thumbnail. Will be re-purposed if we add real resizing.
    thumbnail_artwork_url: str | None
    # Legacy classification fields — no longer edited via the Admin UI. Kept
    # in the response for data safety while the surface is being simplified.
    biome: str | None
    archipelago: str | None
    preferred_atmospheres: list[str]
    preferred_colour_stories: list[str]
    preferred_themes: list[str]
    position: int
    created_at: datetime
    updated_at: datetime
    collectives: list[CollectiveInLocation]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _collective_counts_by_location(db: Session) -> dict[str, int]:
    rows = (
        db.query(Space.location_id, func.count(Space.id))
        .filter(Space.location_id.isnot(None))
        .group_by(Space.location_id)
        .all()
    )
    return {loc_id: n for (loc_id, n) in rows if loc_id}


def _summary_from(loc: Location, count: int) -> LocationSummary:
    return LocationSummary(
        id=loc.id,
        key=loc.key,
        name=loc.name,
        description=loc.description,
        status=loc.status,
        location_type=loc.location_type,
        hero_artwork_url=loc.hero_artwork_url,
        thumbnail_artwork_url=loc.thumbnail_artwork_url,
        biome=loc.biome,
        archipelago=loc.archipelago,
        collective_count=count,
        position=loc.position,
    )


def _detail_from(loc: Location, db: Session) -> LocationDetail:
    collectives = (
        db.query(Space)
        .filter(Space.location_id == loc.id)
        .order_by(Space.name)
        .all()
    )
    return LocationDetail(
        id=loc.id,
        key=loc.key,
        name=loc.name,
        description=loc.description,
        atlas_entry=loc.atlas_entry,
        status=loc.status,
        location_type=loc.location_type,
        hero_artwork_url=loc.hero_artwork_url,
        thumbnail_artwork_url=loc.thumbnail_artwork_url,
        biome=loc.biome,
        archipelago=loc.archipelago,
        preferred_atmospheres=list(loc.preferred_atmospheres or []),
        preferred_colour_stories=list(loc.preferred_colour_stories or []),
        preferred_themes=list(loc.preferred_themes or []),
        position=loc.position,
        created_at=loc.created_at,
        updated_at=loc.updated_at,
        collectives=[
            CollectiveInLocation(id=s.id, slug=s.slug, name=s.name, status=str(s.status))
            for s in collectives
        ],
    )


def _get_by_key(key: str, db: Session) -> Location:
    loc = db.query(Location).filter(Location.key == key).first()
    if not loc:
        raise HTTPException(404, detail="Location not found.")
    return loc


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or "location"


def _unique_key(base: str, db: Session) -> str:
    slug = _slugify(base)
    existing = {k for (k,) in db.query(Location.key).all()}
    if slug not in existing:
        return slug
    n = 2
    while f"{slug}-{n}" in existing:
        n += 1
    return f"{slug}-{n}"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/locations", response_model=list[LocationSummary])
def list_locations(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> list[LocationSummary]:
    locations = db.query(Location).order_by(Location.position, Location.name).all()
    counts = _collective_counts_by_location(db)
    return [_summary_from(loc, counts.get(loc.id, 0)) for loc in locations]


@router.get("/locations/{key}", response_model=LocationDetail)
def get_location(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> LocationDetail:
    loc = _get_by_key(key, db)
    return _detail_from(loc, db)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class LocationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="active")
    location_type: str = Field(default="ATLAS")
    biome: str | None = Field(default=None, max_length=64)
    archipelago: str | None = Field(default=None, max_length=64)


@router.post("/locations", response_model=LocationDetail, status_code=201)
def create_location(
    body: LocationCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> LocationDetail:
    if body.status not in ("active", "hidden"):
        raise HTTPException(400, detail="Status must be 'active' or 'hidden'.")
    if body.location_type not in LOCATION_TYPES:
        raise HTTPException(400, detail=_LOCATION_TYPES_MSG)
    max_pos = db.query(func.coalesce(func.max(Location.position), 0)).scalar() or 0
    loc = Location(
        id=str(uuid4()),
        key=_unique_key(body.name, db),
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        status=body.status,
        location_type=body.location_type,
        biome=(body.biome or "").strip() or None,
        archipelago=(body.archipelago or "").strip() or None,
        preferred_atmospheres=[],
        preferred_colour_stories=[],
        preferred_themes=[],
        position=int(max_pos) + 1,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return _detail_from(loc, db)


# ---------------------------------------------------------------------------
# Update fields
# ---------------------------------------------------------------------------


class LocationUpdateRequest(BaseModel):
    """PATCH surface for a Location. Recommendation-metadata fields have been
    removed from the Admin UI; the columns remain in the DB but are no
    longer editable here. See Atlas v1.1 refinements."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    atlas_entry: str | None = Field(default=None, max_length=20000)
    status: str | None = None
    location_type: str | None = None
    position: int | None = None


@router.patch("/locations/{key}", response_model=LocationDetail)
def update_location(
    key: str,
    body: LocationUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> LocationDetail:
    loc = _get_by_key(key, db)
    if body.name is not None:
        loc.name = body.name.strip()
    if body.description is not None:
        loc.description = body.description.strip() or None
    if body.atlas_entry is not None:
        loc.atlas_entry = body.atlas_entry.strip() or None
    if body.status is not None:
        if body.status not in ("active", "hidden"):
            raise HTTPException(400, detail="Status must be 'active' or 'hidden'.")
        loc.status = body.status
    if body.location_type is not None:
        if body.location_type not in LOCATION_TYPES:
            raise HTTPException(400, detail=_LOCATION_TYPES_MSG)
        loc.location_type = body.location_type
    if body.position is not None:
        loc.position = int(body.position)
    db.commit()
    db.refresh(loc)
    return _detail_from(loc, db)


# ---------------------------------------------------------------------------
# Artwork upload / clear
# ---------------------------------------------------------------------------

_ALLOWED_EXT = ("jpg", "jpeg", "png", "webp")


def _delete_existing(url: str | None) -> None:
    if not url:
        return
    try:
        delete_file(url.removeprefix("/api/uploads/"))
    except Exception:  # noqa: BLE001
        pass


async def _upload_image_with_thumbnail(
    file: UploadFile,
    subdir: str,
    existing_hero: str | None,
    existing_thumbnail: str | None,
) -> tuple[str, str]:
    filename = file.filename or "artwork.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, detail="Only JPG, PNG, and WebP images are allowed.")
    data = await file.read()
    _delete_existing(existing_hero)
    _delete_existing(existing_thumbnail)
    try:
        hero_rel, thumb_rel = save_image_with_thumbnail(
            data, filename, file.content_type or "image/jpeg", subdir,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    return f"/api/uploads/{hero_rel}", f"/api/uploads/{thumb_rel}"


@router.post("/locations/{key}/artwork", response_model=LocationDetail)
async def upload_artwork(
    key: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> LocationDetail:
    """Upload the master artwork for a Location.

    The hero is stored at its original resolution; a proportional
    thumbnail (~600px wide) is generated server-side and stored
    alongside it. Consumers use the thumbnail for grids and cards,
    and the hero for large previews.
    """
    loc = _get_by_key(key, db)
    hero_url, thumb_url = await _upload_image_with_thumbnail(
        file,
        f"atlas-locations/{loc.key}",
        loc.hero_artwork_url,
        loc.thumbnail_artwork_url,
    )
    loc.hero_artwork_url = hero_url
    loc.thumbnail_artwork_url = thumb_url
    db.commit()
    db.refresh(loc)
    return _detail_from(loc, db)


@router.delete("/locations/{key}/artwork", response_model=LocationDetail)
def clear_artwork(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> LocationDetail:
    loc = _get_by_key(key, db)
    for url_attr in ("hero_artwork_url", "thumbnail_artwork_url"):
        _delete_existing(getattr(loc, url_attr))
        setattr(loc, url_attr, None)
    db.commit()
    db.refresh(loc)
    return _detail_from(loc, db)
