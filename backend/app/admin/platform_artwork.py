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
    "discover_places": {
        "title": "Discover Places",
        "description": (
            "The shared artwork used for the Discover Places tile on the "
            "member dashboard."
        ),
    },
    "ways_to_connect": {
        "title": "Ways to Connect",
        "description": (
            "The shared artwork used for the Ways to Connect tile on the "
            "member dashboard."
        ),
    },
    "new_to_fresh_collective": {
        "title": "New to Fresh Collective",
        "description": (
            "The tile shown in \u2018Elsewhere in the world\u2019 on Your "
            "World for members who haven\u2019t yet completed the "
            "orientation. A gentle door into /onboarding \u2014 a first "
            "horizon, warm and unhurried."
        ),
    },
    # ─── Auth Pages ─────────────────────────────────────────────────
    # Shared full-bleed background artwork behind /login and /signup.
    # Falls back to the bundled ``/world/login-hero.png`` when no image
    # is uploaded, so a fresh install still has a proper background.
    "auth_background": {
        "title": "Login & Signup Background",
        "description": (
            "The full-bleed world artwork behind the /login and /signup "
            "pages. A calm, spacious view of the Fresh Collective world "
            "\u2014 read through a deep navy overlay, so mid-tone or "
            "richly-lit images sit best."
        ),
    },
    # ─── Public Homepage ────────────────────────────────────────────
    # Artwork consumed by the public homepage at /. Each card falls
    # back to a deterministic atmospheric gradient (placeAtmosphere.ts)
    # when no image is uploaded, so a fresh install still looks intentional.
    "homepage_explore_collectives": {
        "title": "Homepage — Explore Collectives",
        "description": (
            "The hero image on the Explore Collectives discovery card on "
            "the public homepage."
        ),
    },
    "homepage_discover_places": {
        "title": "Homepage — Discover Places",
        "description": (
            "The hero image on the Discover Places discovery card on "
            "the public homepage."
        ),
    },
    "homepage_ways_to_connect": {
        "title": "Homepage — Ways to Connect",
        "description": (
            "The hero image on the Ways to Connect discovery card on "
            "the public homepage."
        ),
    },
    "homepage_creator_studio": {
        "title": "Homepage — Creator Studio",
        "description": (
            "The large editorial image anchoring the For Creators section "
            "on the public homepage."
        ),
    },
    "homepage_closing_invitation": {
        "title": "Homepage — Closing Invitation",
        "description": (
            "Optional supporting image behind the closing invitation at "
            "the end of the homepage. Leave empty to render without an image."
        ),
    },
    # Life inside a Collective — atmospheric artwork behind each
    # feature's floating UI. Also intended as the hero image on the
    # dedicated Pathways / Gatherings / Conversations / Library pages
    # when those are built, so the assets are reusable.
    "homepage_pathways": {
        "title": "Homepage — Pathways",
        "description": (
            "Atmospheric image behind the Pathways feature on the public "
            "homepage. Also used as the hero image on the dedicated "
            "Pathways page when built."
        ),
    },
    "homepage_gatherings": {
        "title": "Homepage — Gatherings",
        "description": (
            "Atmospheric image behind the Gatherings feature on the public "
            "homepage. Also used as the hero image on the dedicated "
            "Gatherings page when built."
        ),
    },
    "homepage_conversations": {
        "title": "Homepage — Conversations",
        "description": (
            "Atmospheric image behind the Conversations feature on the "
            "public homepage. Also used as the hero image on the dedicated "
            "Conversations page when built."
        ),
    },
    "homepage_resources": {
        "title": "Homepage — Resources",
        "description": (
            "Atmospheric image behind the Resources feature on the public "
            "homepage. Also used as the hero image on the dedicated "
            "Resources page when built."
        ),
    },
    # For Creators page — one image per creator account, presented as
    # editorial rows on /for-creators. Falls back to atmospheric gradients
    # when no image is uploaded so the page still reads considered.
    "for_creators_community": {
        "title": "For Creators — Community Collective",
        "description": (
            "Editorial image for the Community Collective account row on "
            "the public For Creators page. Local, welcoming, small-group "
            "energy — a shared table, a neighbourhood gathering."
        ),
    },
    "for_creators_creator": {
        "title": "For Creators — Creator",
        "description": (
            "Editorial image for the Creator account row on the public "
            "For Creators page. A single creator at work — a studio, a "
            "practitioner's space, considered craft."
        ),
    },
    "for_creators_pro": {
        "title": "For Creators — Creator Portfolio",
        "description": (
            "Editorial image for the Creator Portfolio account row on the "
            "public For Creators page. Several places thriving under one "
            "hand — a small village, a scene with multiple centres."
        ),
    },
    "for_creators_organisation": {
        "title": "For Creators — Ecosystem",
        "description": (
            "Editorial image for the Ecosystem account row on the public "
            "For Creators page. A wider connected landscape — an ecosystem "
            "view, a horizon of interlinked places."
        ),
    },
    "for_creators_world_builders": {
        "title": "For Creators — World Builders",
        "description": (
            "Editorial image for the World Builders Collective section on "
            "the public For Creators page. Creators learning together — "
            "a shared workspace, a considered space of practice."
        ),
    },
    # ─── Onboarding — Member ────────────────────────────────────────
    # Hero artwork shown at the top of each Member onboarding step
    # (/onboarding). Each step falls back to a small SVG scene when no
    # image is uploaded, so a fresh install still reads intentional.
    "member_onboarding_welcome": {
        "title": "Member Onboarding — Welcome",
        "description": (
            "Hero image for step 1 of the Member orientation. The first "
            "moment of arrival — a horizon, an opening in the world."
        ),
    },
    "member_onboarding_interests": {
        "title": "Member Onboarding — What draws you here",
        "description": (
            "Hero image for step 2 of the Member orientation. A compass, "
            "an archipelago, or the sense of choosing a direction."
        ),
    },
    "member_onboarding_how_it_works": {
        "title": "Member Onboarding — How this place works",
        "description": (
            "Hero image for step 3 of the Member orientation. Reads as "
            "a living environment with several rooms — pathways, "
            "gatherings, conversations, resources — held together."
        ),
    },
    "member_onboarding_arrival": {
        "title": "Member Onboarding — Arrival",
        "description": (
            "Hero image for the final step of the Member orientation. "
            "A threshold, an invitation into Your World."
        ),
    },
    # ─── Onboarding — Creator ───────────────────────────────────────
    # Creator welcome (/creator-onboarding) and the ritual steps in
    # Build Your Collective. Island + Colour Palette are omitted on
    # purpose — those steps already have strong native artwork.
    "creator_onboarding_welcome": {
        "title": "Creator Onboarding — Welcome",
        "description": (
            "Hero image for /creator-onboarding, shown once after Creator "
            "plan activation. A calm arrival at a new vantage point."
        ),
    },
    "creator_ritual_atmosphere": {
        "title": "Build Your Collective — Atmosphere",
        "description": (
            "Hero image for the Atmosphere step of Build Your Collective. "
            "Evokes feeling and mood — light, weather, air."
        ),
    },
    "creator_ritual_identity": {
        "title": "Build Your Collective — Identity",
        "description": (
            "Hero image for the Identity Statement step of Build Your "
            "Collective. A single, clear mark — the heart of the space."
        ),
    },
    "creator_ritual_welcome_message": {
        "title": "Build Your Collective — Welcome Message",
        "description": (
            "Hero image for the Welcome Message step of Build Your "
            "Collective. A door opening, a room warmed for arrival."
        ),
    },
    "creator_ritual_practical": {
        "title": "Build Your Collective — Practical Details",
        "description": (
            "Hero image for the Practical Details step of Build Your "
            "Collective. Grounded, considered, plain."
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
