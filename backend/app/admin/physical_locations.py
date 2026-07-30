"""
Physical Locations — admin CRUD for the real-world Places that
back Discover Places.

Physical Locations answer *"what communities are in my area?"*.
They are **broad discovery areas** — cities members will naturally
recognise and search for (Melbourne, Hobart, Auckland) or named
regions that gather under one banner (Blue Mountains, Sunshine
Coast, Mornington Peninsula). Sub-city localities — suburbs,
neighbourhoods, individual venue suburbs — never become Physical
Locations. Specific locality lives on the Collective as
descriptive copy; precise venue lives on the Gathering
(``venue_name`` / ``venue_address``).

They are deliberately separate from Collective identity, Atlas
Islands, and Collective visual identity. A Collective may
belong to a Physical Location, but must never inherit its
artwork or visual identity.

Only Fresh Collective administrators reach these routes. Creators
never create or edit Physical Locations from Creator Studio — they
choose from approved active locations at Collective setup, and
that surface lives elsewhere. Picker-driven creations from the
Creator side (see ``app.places.routes.resolve_place``) land as
``draft`` — never visible on Discover Places until an admin
promotes them, so nothing suburb-level ever slips onto the
public catalogue automatically.

Endpoints under `/api/admin/physical-locations/*`:

  GET    /                          — list with Collective counts,
                                       search, status filter,
                                       country filter, sort
  GET    /{slug}                    — detail (with Collectives)
  POST   /                          — create
  PATCH  /{slug}                    — update fields
  POST   /{slug}/artwork            — upload hero artwork
  DELETE /{slug}/artwork            — clear artwork
  DELETE /{slug}                    — delete the Location (blocked
                                       if any Collectives are still
                                       linked)

The migration is 093; the model is
``app.models.place.Place``.
See docs/foundations/discovery-connection-belonging-location-model.md.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.storage import delete_file, save_file
from app.models.place import Place, SpacePlace
from app.models.platform import Space
from app.models.user import User


router = APIRouter(prefix="/api/admin/physical-locations", tags=["admin-physical-locations"])


ALLOWED_STATUSES: set[str] = {"draft", "active", "hidden", "archived"}
_STATUS_MSG = "Status must be one of: draft, active, hidden, archived."

_ALLOWED_ART_EXT = ("jpg", "jpeg", "png", "webp")


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class PhysicalLocationSummary(BaseModel):
    """Row shape for the admin list."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    region: str | None
    country_code: str
    status: str
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    collective_count: int
    updated_at: datetime


class CollectiveInLocation(BaseModel):
    """A Collective attached to this Physical Location. Read-only
    from this admin surface — a Collective's own identity is
    edited in Creator Studio, never here."""

    id: str
    slug: str
    name: str
    status: str


class PhysicalLocationDetail(BaseModel):
    """Full detail shape for the admin edit page."""

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    region: str | None
    country_code: str
    blurb: str | None
    admin_note: str | None
    status: str
    hero_artwork_url: str | None
    artwork_alt_text: str | None
    artwork_focal_x: float
    artwork_focal_y: float
    latitude: float | None
    longitude: float | None
    timezone: str | None
    provider_place_id: str | None
    collectives: list[CollectiveInLocation]
    collective_count: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collective_counts_by_place(db: Session) -> dict[str, int]:
    """One query — active Collectives per place_id."""
    rows = (
        db.query(SpacePlace.place_id, func.count(Space.id))
        .join(Space, Space.id == SpacePlace.space_id)
        .filter(Space.status == "active")
        .group_by(SpacePlace.place_id)
        .all()
    )
    return {place_id: int(count) for place_id, count in rows}


def _linked_collectives(place_id: str, db: Session) -> list[CollectiveInLocation]:
    rows = (
        db.query(Space)
        .join(SpacePlace, SpacePlace.space_id == Space.id)
        .filter(SpacePlace.place_id == place_id)
        .order_by(Space.name)
        .all()
    )
    return [
        CollectiveInLocation(
            id=s.id, slug=s.slug, name=s.name,
            status=(s.status.value if hasattr(s.status, 'value') else str(s.status)),
        )
        for s in rows
    ]


def _detail_from(place: Place, db: Session) -> PhysicalLocationDetail:
    collectives = _linked_collectives(place.id, db)
    return PhysicalLocationDetail(
        id=place.id,
        slug=place.slug,
        name=place.name,
        region=place.region,
        country_code=place.country_code,
        blurb=place.blurb,
        admin_note=place.admin_note,
        status=place.status,
        hero_artwork_url=place.hero_artwork_url,
        artwork_alt_text=place.artwork_alt_text,
        artwork_focal_x=place.artwork_focal_x,
        artwork_focal_y=place.artwork_focal_y,
        latitude=place.latitude,
        longitude=place.longitude,
        timezone=place.timezone,
        provider_place_id=place.provider_place_id,
        collectives=collectives,
        collective_count=len([c for c in collectives if c.status == "active"]),
        created_at=place.created_at,
        updated_at=place.updated_at,
    )


def _summary_from(place: Place, active_count: int) -> PhysicalLocationSummary:
    return PhysicalLocationSummary(
        id=place.id,
        slug=place.slug,
        name=place.name,
        region=place.region,
        country_code=place.country_code,
        status=place.status,
        hero_artwork_url=place.hero_artwork_url,
        artwork_alt_text=place.artwork_alt_text,
        artwork_focal_x=place.artwork_focal_x,
        artwork_focal_y=place.artwork_focal_y,
        collective_count=active_count,
        updated_at=place.updated_at,
    )


def _get_by_slug(slug: str, db: Session) -> Place:
    place = db.execute(select(Place).where(Place.slug == slug)).scalar_one_or_none()
    if place is None:
        raise HTTPException(status_code=404, detail="Physical Location not found.")
    return place


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "place"


def _unique_slug(base_slug: str, db: Session, exclude_id: str | None = None) -> str:
    q = select(Place).where(Place.slug == base_slug)
    if exclude_id is not None:
        q = q.where(Place.id != exclude_id)
    if not db.execute(q).scalar_one_or_none():
        return base_slug
    n = 2
    while True:
        candidate = f"{base_slug}-{n}"
        q = select(Place).where(Place.slug == candidate)
        if exclude_id is not None:
            q = q.where(Place.id != exclude_id)
        if not db.execute(q).scalar_one_or_none():
            return candidate
        n += 1


def _delete_existing_artwork(url: str | None) -> None:
    if not url:
        return
    try:
        delete_file(url.removeprefix("/api/uploads/"))
    except Exception:  # noqa: BLE001
        # Best-effort cleanup. A missing file must not block the
        # DB update.
        pass


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

_SORT_CHOICES = {"alphabetical", "recently-updated", "most-collectives"}


@router.get("", response_model=list[PhysicalLocationSummary])
def list_locations(
    q: str | None = Query(default=None, description="Search by name / region."),
    status: str | None = Query(default=None, description="Filter by status."),
    country: str | None = Query(default=None, description="Filter by ISO country code (uppercase)."),
    sort: str = Query(default="alphabetical", description="alphabetical | recently-updated | most-collectives"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> list[PhysicalLocationSummary]:
    if sort not in _SORT_CHOICES:
        raise HTTPException(400, detail=f"sort must be one of: {sorted(_SORT_CHOICES)}")
    if status is not None and status not in ALLOWED_STATUSES:
        raise HTTPException(400, detail=_STATUS_MSG)

    stmt = select(Place)
    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Place.name).like(pattern),
                func.lower(func.coalesce(Place.region, "")).like(pattern),
            )
        )
    if status is not None:
        stmt = stmt.where(Place.status == status)
    if country is not None:
        stmt = stmt.where(Place.country_code == country.upper())

    if sort == "alphabetical":
        stmt = stmt.order_by(Place.name)
    elif sort == "recently-updated":
        stmt = stmt.order_by(Place.updated_at.desc())
    # `most-collectives` is applied after we compute counts.

    places = db.execute(stmt).scalars().all()
    counts = _collective_counts_by_place(db)

    summaries = [_summary_from(p, counts.get(p.id, 0)) for p in places]
    if sort == "most-collectives":
        summaries.sort(key=lambda s: (-s.collective_count, s.name))
    return summaries


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@router.get("/{slug}", response_model=PhysicalLocationDetail)
def get_location(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PhysicalLocationDetail:
    return _detail_from(_get_by_slug(slug, db), db)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class PhysicalLocationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    country_code: str = Field(..., min_length=2, max_length=2)
    status: str = Field(default="draft")
    admin_note: str | None = Field(default=None, max_length=4000)

    @field_validator("country_code")
    @classmethod
    def _upper_country(cls, v: str) -> str:
        return v.upper()

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ALLOWED_STATUSES:
            raise ValueError(_STATUS_MSG)
        return v


@router.post("", response_model=PhysicalLocationDetail, status_code=201)
def create_location(
    body: PhysicalLocationCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PhysicalLocationDetail:
    slug = body.slug.strip() if body.slug else _slugify(body.name)
    slug = _unique_slug(slug, db)
    place = Place(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=slug,
        name=body.name.strip(),
        region=(body.region or "").strip() or None,
        country_code=body.country_code,
        status=body.status,
        admin_note=(body.admin_note or "").strip() or None,
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    return _detail_from(place, db)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class PhysicalLocationUpdateRequest(BaseModel):
    """PATCH surface — every field is optional. Only supplied fields
    change. Slug changes are allowed but validated for uniqueness."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    status: str | None = None
    blurb: str | None = Field(default=None, max_length=4000)
    admin_note: str | None = Field(default=None, max_length=4000)
    artwork_alt_text: str | None = Field(default=None, max_length=500)
    artwork_focal_x: float | None = Field(default=None, ge=0.0, le=1.0)
    artwork_focal_y: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("country_code")
    @classmethod
    def _upper_country(cls, v: str | None) -> str | None:
        return v.upper() if v is not None else v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(_STATUS_MSG)
        return v


@router.patch("/{slug}", response_model=PhysicalLocationDetail)
def update_location(
    slug: str,
    body: PhysicalLocationUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PhysicalLocationDetail:
    place = _get_by_slug(slug, db)
    if body.name is not None:
        place.name = body.name.strip()
    if body.slug is not None and body.slug != place.slug:
        place.slug = _unique_slug(body.slug.strip(), db, exclude_id=place.id)
    if body.region is not None:
        place.region = body.region.strip() or None
    if body.country_code is not None:
        place.country_code = body.country_code
    if body.status is not None:
        place.status = body.status
    if body.blurb is not None:
        place.blurb = body.blurb.strip() or None
    if body.admin_note is not None:
        place.admin_note = body.admin_note.strip() or None
    if body.artwork_alt_text is not None:
        place.artwork_alt_text = body.artwork_alt_text.strip() or None
    if body.artwork_focal_x is not None:
        place.artwork_focal_x = body.artwork_focal_x
    if body.artwork_focal_y is not None:
        place.artwork_focal_y = body.artwork_focal_y
    db.commit()
    db.refresh(place)
    return _detail_from(place, db)


# ---------------------------------------------------------------------------
# Artwork upload / clear
# ---------------------------------------------------------------------------

@router.post("/{slug}/artwork", response_model=PhysicalLocationDetail)
async def upload_artwork(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PhysicalLocationDetail:
    """Upload the hero artwork for a Physical Location.

    Overwrites any prior artwork (old file cleaned up on
    best-effort basis). Focal point stays at whatever the admin
    last set — a fresh upload does NOT reset it, since editors
    often reupload an updated crop of the same scene.
    """
    place = _get_by_slug(slug, db)
    filename = file.filename or "artwork.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_ART_EXT:
        raise HTTPException(400, detail="Only JPG, PNG, and WebP images are allowed.")
    data = await file.read()

    _delete_existing_artwork(place.hero_artwork_url)
    try:
        rel_path, _resource_type, _size = save_file(
            data,
            filename,
            file.content_type or "image/jpeg",
            f"place-artwork/{place.slug}",
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e

    place.hero_artwork_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(place)
    return _detail_from(place, db)


@router.delete("/{slug}/artwork", response_model=PhysicalLocationDetail)
def clear_artwork(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PhysicalLocationDetail:
    place = _get_by_slug(slug, db)
    _delete_existing_artwork(place.hero_artwork_url)
    place.hero_artwork_url = None
    place.artwork_alt_text = None
    place.artwork_focal_x = 0.5
    place.artwork_focal_y = 0.5
    db.commit()
    db.refresh(place)
    return _detail_from(place, db)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{slug}", status_code=204)
def delete_location(
    slug: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> None:
    """Delete a Physical Location.

    Physical Locations are curated discovery records, not historical
    entities — an unused Location should simply not exist. If the
    Location has any linked Collectives (of any status), deletion is
    blocked with a 409 so the admin can move or remove those links
    first. This is defence-in-depth on top of the SpacePlace CASCADE:
    the CASCADE would silently drop a Collective's Physical Location
    if we ever bypassed this guard, so we don't.

    User.home_place_id is intentionally NOT a block: it is a personal
    preference and the FK is defined ``ON DELETE SET NULL`` — members
    keep their account and simply lose the personal association.
    """
    place = _get_by_slug(slug, db)
    linked_count = db.execute(
        select(func.count()).select_from(SpacePlace).where(
            SpacePlace.place_id == place.id
        )
    ).scalar_one()
    if linked_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{linked_count} Collective(s) are still linked to this "
                "Physical Location. Move or remove those links, then delete."
            ),
        )
    _delete_existing_artwork(place.hero_artwork_url)
    db.delete(place)
    db.commit()
    return None
