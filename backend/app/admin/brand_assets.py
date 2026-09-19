"""World Management → Artwork → Fresh Collective Brand (admin API).

The brand section of the existing Artwork area, not a second asset
system: same ``platform_artwork`` table, same storage helper, same
public ``platform-artwork/`` prefix and therefore the same public R2
bucket and the same unauthenticated serve route. What is different is
the vocabulary — brand *roles* rather than artwork *slots* — because a
role carries things a slot does not: an approved bundled default, an
honest missing state, and per-role validation rules.

Endpoints
---------
  Admin (get_admin_user)
    GET    /api/admin/brand-assets            — every role, grouped
    POST   /api/admin/brand-assets/{role}     — replace the artwork
    DELETE /api/admin/brand-assets/{role}     — reset to approved default

  Public
    GET    /api/brand-assets                  — resolved map for renderers

Three decisions worth stating.

**No thumbnails.** World Artwork generates a 600px thumbnail for every
upload because those are photographs rendered into cards. A logo is
already small, is often transparent, and is the one image on the page
that must not be resampled by anything other than the browser at its
final size. Brand uploads store one file.

**No SVG.** The obvious format for a logo, and refused here. The
upload pipeline has no SVG sanitiser, and an SVG is a script-bearing
document served from our own origin. Adding one safely is its own
piece of work; until then, raster only, and the refusal says so rather
than reporting a generic "unsupported file".

**Reset is DELETE, not re-upload.** Approved defaults are files in the
repo, resolved in code. Resetting a role therefore deletes the
override and the default reappears — there is no copy of the default
in storage to restore, and so no way for the two to drift.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.brand import (
    BRAND_ASSET_ROLES,
    GROUP_LABELS,
    MAX_BRAND_ASSET_BYTES,
    ROLE_ORDER,
    BrandAssetResolution,
    UnknownBrandRoleError,
    get_role,
    resolve,
    resolve_all,
    storage_key_for,
    storage_subdir_for,
)
from app.brand.roles import EXTENSION_BY_CONTENT_TYPE
from app.core.database import get_db
from app.core.storage import delete_file, save_file
from app.models.platform import PlatformArtwork
from app.models.user import User


logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/api/admin/brand-assets", tags=["admin-brand-assets"],
)
public_router = APIRouter(prefix="/api/brand-assets", tags=["brand-assets"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class BrandAssetOut(BaseModel):
    """One role as World Management sees it.

    Deliberately absent: the storage key and the stored filename. An
    admin manages "the logo on a dark background", not
    ``platform-artwork/brand/logo_on_navy/9f2c…_final_v3_FINAL.png``.
    The key is an implementation detail and showing it invites people
    to treat it as an address.
    """

    role: str
    title: str
    group: str
    intended_use: str
    recommended: str
    accepted_formats: list[str]
    source: str                       # custom | default | missing
    image_url: str | None
    public_url: str | None
    missing_note: str | None
    updated_at: datetime | None
    updated_by: str | None
    can_reset: bool


class BrandAssetGroupOut(BaseModel):
    group: str
    label: str
    description: str
    assets: list[BrandAssetOut]


class PublicBrandAsset(BaseModel):
    role: str
    source: str
    image_url: str | None
    public_url: str | None


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------


_FORMAT_LABELS = {
    "image/png": "PNG",
    "image/webp": "WebP",
    "image/jpeg": "JPG",
}


def _display_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    return user.name or user.email


def _out(db: Session, res: BrandAssetResolution) -> BrandAssetOut:
    definition = get_role(res.role)
    return BrandAssetOut(
        role=res.role,
        title=definition.title,
        group=definition.group,
        intended_use=definition.intended_use,
        recommended=definition.recommended,
        accepted_formats=[
            _FORMAT_LABELS[c] for c in definition.content_types
        ],
        source=res.source,
        image_url=res.url,
        public_url=res.public_url,
        missing_note=definition.missing_note or None,
        updated_at=res.updated_at,
        updated_by=_display_name(db, res.updated_by_user_id),
        # Reset means "go back to the approved default". A role with no
        # default has nothing to go back to, so the control is absent
        # rather than present-and-disabled.
        can_reset=bool(definition.default_path),
    )


def _grouped(db: Session) -> list[BrandAssetGroupOut]:
    by_role = {r.role: r for r in resolve_all(db)}
    out: list[BrandAssetGroupOut] = []
    for group, meta in GROUP_LABELS.items():
        assets = [
            _out(db, by_role[role])
            for role in ROLE_ORDER
            if BRAND_ASSET_ROLES[role].group == group
        ]
        out.append(BrandAssetGroupOut(
            group=group, label=meta["label"],
            description=meta["description"], assets=assets,
        ))
    return out


def _role_or_404(role: str):
    try:
        return get_role(role)
    except UnknownBrandRoleError:
        # Roles are application-defined. An unrecognised one is not a
        # slot waiting to be created — it is a typo or a probe.
        raise HTTPException(404, detail="Unknown brand asset role.") from None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(definition, data: bytes, filename: str, content_type: str | None) -> str:
    """Check an upload against the role's rules. Returns the extension
    to store it under. Raises HTTPException(400) with a message written
    for the person who just dragged a file in."""
    lowered = (filename or "").lower()

    if lowered.endswith(".svg") or (content_type or "").startswith("image/svg"):
        raise HTTPException(400, detail=(
            "SVG uploads are not accepted. Fresh Collective's upload "
            "pipeline does not sanitise SVG, and an unsanitised SVG "
            "served from our own domain can carry script. Please supply "
            "a PNG or WebP export."
        ))

    if not data:
        raise HTTPException(400, detail="That file is empty.")

    if len(data) > MAX_BRAND_ASSET_BYTES:
        mb = MAX_BRAND_ASSET_BYTES / (1024 * 1024)
        raise HTTPException(400, detail=(
            f"That image is {len(data) / (1024 * 1024):.1f} MB. Brand "
            f"artwork must be under {mb:.0f} MB — a logo this large is "
            "usually a print export rather than a web asset."
        ))

    # Decode rather than trust the declared type: the browser's
    # content_type comes from the file extension and is trivially wrong.
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            actual = (img.format or "").upper()
            width, height = img.size
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, detail=(
            "That file could not be read as an image."
        )) from None

    detected = {"PNG": "image/png", "WEBP": "image/webp", "JPEG": "image/jpeg"}.get(actual)
    if detected is None or detected not in definition.content_types:
        allowed = ", ".join(_FORMAT_LABELS[c] for c in definition.content_types)
        raise HTTPException(400, detail=(
            f"{definition.title} accepts {allowed}. "
            + (
                "Transparency matters for this one, so a flat JPG will not do."
                if "image/jpeg" not in definition.content_types
                else "That file is not one of them."
            )
        ))

    if width < definition.min_width or height < definition.min_height:
        raise HTTPException(400, detail=(
            f"That image is {width} × {height}px. {definition.title} "
            f"needs at least {definition.min_width} × "
            f"{definition.min_height}px so it stays sharp where it is used."
        ))

    if definition.aspect is not None and not definition.aspect.accepts(width, height):
        raise HTTPException(400, detail=(
            f"That image is {width} × {height}px. {definition.title} must "
            f"be {definition.aspect.description} — anything else is "
            "cropped or letterboxed by whatever renders it, and we would "
            "rather you choose where it is trimmed than we guess."
        ))

    return EXTENSION_BY_CONTENT_TYPE[detected]


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@admin_router.get("", response_model=list[BrandAssetGroupOut])
def list_brand_assets(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> list[BrandAssetGroupOut]:
    """Every brand role, grouped, with its current source."""
    return _grouped(db)


@admin_router.post("/{role}", response_model=BrandAssetOut)
async def replace_brand_asset(
    role: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> BrandAssetOut:
    """Upload artwork for a role, replacing whatever is there."""
    definition = _role_or_404(role)

    data = await file.read()
    ext = _validate(definition, data, file.filename or "", file.content_type)

    row = (
        db.query(PlatformArtwork)
        .filter(PlatformArtwork.key == storage_key_for(role))
        .first()
    )
    previous_url = row.image_url if row else None

    stored_key, _resource, _size = save_file(
        data,
        f"{role}.{ext}",
        {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}[ext],
        storage_subdir_for(role),
    )
    image_url = f"/api/uploads/{stored_key}"

    if row is None:
        row = PlatformArtwork(key=storage_key_for(role))
        db.add(row)
    row.image_url = image_url
    row.thumbnail_url = None
    row.updated_by_user_id = admin.id
    db.commit()
    db.refresh(row)

    # Delete the superseded object only after the new one is committed.
    # The other order risks a failed write leaving the role with no
    # artwork at all, and a leaked object is cheaper than a blank logo.
    if previous_url and previous_url != image_url:
        try:
            delete_file(previous_url.removeprefix("/api/uploads/"))
        except Exception:  # noqa: BLE001
            logger.warning(
                "brand assets: could not delete superseded object for %s", role,
            )

    return _out(db, resolve(db, role))


@admin_router.delete("/{role}", response_model=BrandAssetOut)
def reset_brand_asset(
    role: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> BrandAssetOut:
    """Drop the override so the approved bundled default applies again.

    For a role with no default this clears the upload and returns the
    role to ``missing`` — still the correct outcome, and still honest.
    """
    _role_or_404(role)

    row = (
        db.query(PlatformArtwork)
        .filter(PlatformArtwork.key == storage_key_for(role))
        .first()
    )
    if row is not None:
        stored = row.image_url
        # Drop the row entirely rather than nulling its columns: the
        # absence of a row IS "no override", and leaving an empty row
        # behind would make ``updated_at`` claim the default changed
        # when the default is a file in the repo that did not.
        db.delete(row)
        db.commit()
        if stored:
            try:
                delete_file(stored.removeprefix("/api/uploads/"))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "brand assets: could not delete object on reset for %s", role,
                )

    return _out(db, resolve(db, role))


# ---------------------------------------------------------------------------
# Public read route
# ---------------------------------------------------------------------------


@public_router.get("", response_model=list[PublicBrandAsset])
def read_brand_assets(db: Session = Depends(get_db)) -> list[PublicBrandAsset]:
    """Resolved brand artwork for unauthenticated renderers.

    Returns every role including the missing ones, with nulls, so a
    consumer can tell "no artwork for this role" apart from "role I do
    not recognise" without a second request.
    """
    return [
        PublicBrandAsset(
            role=r.role, source=r.source,
            image_url=r.url, public_url=r.public_url,
        )
        for r in resolve_all(db)
    ]
