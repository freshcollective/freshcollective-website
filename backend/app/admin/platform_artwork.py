"""Platform Artwork — admin endpoints for shared interface artwork.

A small, named collection of images owned by the platform itself
(dashboard tiles, etc.) — distinct from Atlas Location artwork.
Only Fresh Collective administrators reach the mutation routes.
The public read route returns the current image map so unauthenticated
pages (dashboard tiles) can render the uploaded artwork.

Endpoints:
  Admin (protected)
    GET    /api/admin/platform-artwork              — list all entries
    POST   /api/admin/platform-artwork/{key}        — upload hero + generate thumbnail
    DELETE /api/admin/platform-artwork/{key}        — remove hero + thumbnail

  Public
    GET    /api/platform-artwork                    — read-only map for tiles
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.storage import delete_file, save_image_with_thumbnail
from app.models.platform import PlatformArtwork
from app.models.user import User


# The stable, canonical set of platform artwork keys. New entries are
# added here rather than as free-form strings so callers can rely on
# the vocabulary being explicit and reviewable.
PLATFORM_ARTWORK_KEYS: dict[str, dict[str, str]] = {
    "explore_collectives": {
        "title": "Explore Collectives",
        "description": (
            "The shared artwork used for the Explore Collectives tile on the "
            "member dashboard."
        ),
    },
    "creator_studio": {
        "title": "Creator Studio",
        "description": (
            "The shared artwork used for the Creator Studio tile on the "
            "member dashboard."
        ),
    },
    "mother_world_hero": {
        "title": "Mother World Hero",
        "description": (
            "The panoramic image shown at the top of Mother World."
        ),
    },
}


admin_router = APIRouter(prefix="/api/admin/platform-artwork", tags=["admin-platform-artwork"])
public_router = APIRouter(prefix="/api/platform-artwork", tags=["platform-artwork"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class PlatformArtworkItem(BaseModel):
    key: str
    title: str
    description: str
    image_url: str | None
    thumbnail_url: str | None
    updated_at: datetime | None


def _known_or_404(key: str) -> dict[str, str]:
    meta = PLATFORM_ARTWORK_KEYS.get(key)
    if not meta:
        raise HTTPException(404, detail="Unknown platform artwork key.")
    return meta


def _row(db: Session, key: str) -> PlatformArtwork | None:
    return db.query(PlatformArtwork).filter(PlatformArtwork.key == key).first()


def _item(key: str, row: PlatformArtwork | None) -> PlatformArtworkItem:
    meta = PLATFORM_ARTWORK_KEYS[key]
    return PlatformArtworkItem(
        key=key,
        title=meta["title"],
        description=meta["description"],
        image_url=row.image_url if row else None,
        thumbnail_url=row.thumbnail_url if row else None,
        updated_at=row.updated_at if row else None,
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@admin_router.get("", response_model=list[PlatformArtworkItem])
def list_platform_artwork(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> list[PlatformArtworkItem]:
    rows = {r.key: r for r in db.query(PlatformArtwork).all()}
    return [_item(k, rows.get(k)) for k in PLATFORM_ARTWORK_KEYS]


_ALLOWED_EXT = ("jpg", "jpeg", "png", "webp")


@admin_router.post("/{key}", response_model=PlatformArtworkItem)
async def upload_platform_artwork(
    key: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PlatformArtworkItem:
    _known_or_404(key)
    filename = file.filename or "artwork.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, detail="Only JPG, PNG, and WebP images are allowed.")

    row = _row(db, key)
    if row:
        for url in (row.image_url, row.thumbnail_url):
            if url:
                try:
                    delete_file(url.removeprefix("/api/uploads/"))
                except Exception:  # noqa: BLE001
                    pass

    data = await file.read()
    try:
        hero_rel, thumb_rel = save_image_with_thumbnail(
            data, filename, file.content_type or "image/jpeg", f"platform-artwork/{key}",
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e

    hero_url = f"/api/uploads/{hero_rel}"
    thumb_url = f"/api/uploads/{thumb_rel}"

    if row is None:
        row = PlatformArtwork(key=key, image_url=hero_url, thumbnail_url=thumb_url)
        db.add(row)
    else:
        row.image_url = hero_url
        row.thumbnail_url = thumb_url

    db.commit()
    db.refresh(row)
    return _item(key, row)


@admin_router.delete("/{key}", response_model=PlatformArtworkItem)
def clear_platform_artwork(
    key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PlatformArtworkItem:
    _known_or_404(key)
    row = _row(db, key)
    if row:
        for url in (row.image_url, row.thumbnail_url):
            if url:
                try:
                    delete_file(url.removeprefix("/api/uploads/"))
                except Exception:  # noqa: BLE001
                    pass
        row.image_url = None
        row.thumbnail_url = None
        db.commit()
        db.refresh(row)
    return _item(key, row)


# ---------------------------------------------------------------------------
# Public read route — unauthenticated so dashboard tiles can render
# ---------------------------------------------------------------------------


class PublicPlatformArtwork(BaseModel):
    key: str
    image_url: str | None
    thumbnail_url: str | None


@public_router.get("", response_model=list[PublicPlatformArtwork])
def read_platform_artwork(
    db: Session = Depends(get_db),
) -> list[PublicPlatformArtwork]:
    """Read-only map of platform artwork for public consumers (dashboard
    tiles). Returns every known key; missing rows come back with null URLs."""
    rows = {r.key: r for r in db.query(PlatformArtwork).all()}
    return [
        PublicPlatformArtwork(
            key=k,
            image_url=rows[k].image_url if k in rows else None,
            thumbnail_url=rows[k].thumbnail_url if k in rows else None,
        )
        for k in PLATFORM_ARTWORK_KEYS
    ]
