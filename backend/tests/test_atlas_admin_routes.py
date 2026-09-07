"""Route tests for the Atlas admin surface (``/api/admin/atlas/*``).

Focuses on the artwork upload/clear flow that was reworked to store
Atlas Location artwork under ``platform-artwork/atlas-locations/…`` so
it lives in the public bucket and is served without an auth-gated
cookie.

Tests call the endpoint functions directly (matching the pattern used
in ``test_physical_locations_routes.py``).
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile

# Sibling model imports SQLAlchemy needs to resolve when this file runs
# in isolation. Matches the pattern in test_physical_locations_routes.
import app.models.community_care  # noqa: F401
from app.admin.atlas import (
    clear_artwork,
    upload_artwork,
)
from app.models.platform import Location
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _location(**overrides) -> Location:
    defaults = dict(
        id=f"loc_{uuid.uuid4().hex[:12]}",
        key=f"loc-{uuid.uuid4().hex[:8]}",
        name="A Location",
        status="active",
        location_type="ATLAS",
        preferred_atmospheres=[],
        preferred_colour_stories=[],
        preferred_themes=[],
        position=0,
    )
    defaults.update(overrides)
    return Location(**defaults)


# A 2x2 solid PNG — Pillow can decode + resize this without needing
# a real hero-sized image. Matches the fixture used in test_r2_storage.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd4"
    "9a730000001649444154789c63fccfc0c0c0c0c0c4c0c0c0c0c000000d1d01"
    "036ac29be90000000049454e44ae426082"
)


def _png_upload(filename: str = "hero.png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_PNG_BYTES),
        filename=filename,
        headers={"content-type": "image/png"},  # type: ignore[arg-type]
    )


def _webp_bytes() -> bytes:
    """Tiny in-memory WebP so tests exercise the format the admin UI
    actually receives from the browser."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (128, 200, 190)).save(
        buf, format="WEBP", quality=85, method=6,
    )
    return buf.getvalue()


def _webp_upload(filename: str = "hero.webp") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_webp_bytes()),
        filename=filename,
        headers={"content-type": "image/webp"},  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Artwork upload — public namespace + WebP + safe replacement
# ---------------------------------------------------------------------------


class TestArtworkUpload:
    def test_png_upload_stores_hero_and_thumbnail_under_public_prefix(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        loc = _location(key="moon-lagoon", name="Moon Lagoon")
        db.add(loc)
        db.flush()

        result = asyncio.run(upload_artwork(
            key="moon-lagoon", file=_png_upload(), db=db, _=admin,
        ))
        # Both hero and thumbnail sit under the platform-artwork public
        # namespace so they are served without an auth-gated cookie.
        assert result.hero_artwork_url is not None
        assert result.hero_artwork_url.startswith(
            "/api/uploads/platform-artwork/atlas-locations/moon-lagoon/"
        )
        assert result.hero_artwork_url.endswith(".png")
        assert result.thumbnail_artwork_url is not None
        assert result.thumbnail_artwork_url.startswith(
            "/api/uploads/platform-artwork/atlas-locations/moon-lagoon/"
        )
        assert result.thumbnail_artwork_url.endswith(".png")
        # Hero and thumbnail are distinct objects.
        assert result.hero_artwork_url != result.thumbnail_artwork_url

    def test_webp_upload_stores_hero_and_thumbnail_under_public_prefix(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        loc = _location(key="webp-lagoon", name="WebP Lagoon")
        db.add(loc)
        db.flush()

        result = asyncio.run(upload_artwork(
            key="webp-lagoon", file=_webp_upload(), db=db, _=admin,
        ))
        assert result.hero_artwork_url is not None
        assert result.hero_artwork_url.startswith(
            "/api/uploads/platform-artwork/atlas-locations/webp-lagoon/"
        )
        assert result.hero_artwork_url.endswith(".webp")
        assert result.thumbnail_artwork_url is not None
        assert result.thumbnail_artwork_url.startswith(
            "/api/uploads/platform-artwork/atlas-locations/webp-lagoon/"
        )
        assert result.thumbnail_artwork_url.endswith(".webp")

    def test_upload_rejects_non_image(self, db, make_user):
        admin = make_user(role="admin")
        loc = _location(key="reject-me", name="Reject Me")
        db.add(loc)
        db.flush()

        bad = UploadFile(
            file=io.BytesIO(b"not an image"),
            filename="hero.txt",
            headers={"content-type": "text/plain"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                key="reject-me", file=bad, db=db, _=admin,
            ))
        assert ex.value.status_code == 400

    def test_missing_key_is_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                key="does-not-exist", file=_png_upload(), db=db, _=admin,
            ))
        assert ex.value.status_code == 404


# ---------------------------------------------------------------------------
# Safe replacement — the reason the endpoint was reworked
# ---------------------------------------------------------------------------


class TestArtworkReplacementSafety:
    def _seed_existing_pair(self, tmp_path, key):
        """Write a plausible existing hero + thumbnail pair on disk
        (under the new public path) and return their URLs."""
        subdir = tmp_path / "platform-artwork" / "atlas-locations" / key
        subdir.mkdir(parents=True)
        hero = subdir / "OLD_hero.png"
        thumb = subdir / "OLD_thumb_hero.png"
        hero.write_bytes(_PNG_BYTES)
        thumb.write_bytes(_PNG_BYTES)
        base = f"/api/uploads/platform-artwork/atlas-locations/{key}"
        return hero, thumb, f"{base}/OLD_hero.png", f"{base}/OLD_thumb_hero.png"

    def test_successful_replacement_deletes_old_hero_and_thumbnail(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        hero_file, thumb_file, hero_url, thumb_url = self._seed_existing_pair(
            tmp_path, "replace-me",
        )
        admin = make_user(role="admin")
        loc = _location(
            key="replace-me", name="Replace Me",
            hero_artwork_url=hero_url,
            thumbnail_artwork_url=thumb_url,
        )
        db.add(loc)
        db.flush()

        result = asyncio.run(upload_artwork(
            key="replace-me", file=_png_upload(), db=db, _=admin,
        ))
        # New URLs different from the old ones.
        assert result.hero_artwork_url != hero_url
        assert result.thumbnail_artwork_url != thumb_url
        # Old files cleaned up on disk.
        assert not hero_file.exists()
        assert not thumb_file.exists()

    def test_failed_replacement_preserves_existing_hero_and_thumbnail(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        hero_file, thumb_file, hero_url, thumb_url = self._seed_existing_pair(
            tmp_path, "safe-fail",
        )
        admin = make_user(role="admin")
        loc = _location(
            key="safe-fail", name="Safe Fail",
            hero_artwork_url=hero_url,
            thumbnail_artwork_url=thumb_url,
        )
        db.add(loc)
        db.flush()

        # A non-image body will trip the extension guard before any
        # storage write happens — the previous artwork MUST survive.
        bad = UploadFile(
            file=io.BytesIO(b"not an image"),
            filename="hero.txt",
            headers={"content-type": "text/plain"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                key="safe-fail", file=bad, db=db, _=admin,
            ))
        assert ex.value.status_code == 400
        assert hero_file.exists(), "old hero was destroyed by failed upload"
        assert thumb_file.exists(), "old thumbnail was destroyed by failed upload"
        db.refresh(loc)
        assert loc.hero_artwork_url == hero_url
        assert loc.thumbnail_artwork_url == thumb_url

    def test_thumbnail_generation_failure_leaves_no_orphan_hero(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        """If thumbnail generation raises after the hero is written to
        storage, the just-written hero must be cleaned up so we do not
        leak an orphan object."""
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        loc = _location(key="orphan-guard", name="Orphan Guard")
        db.add(loc)
        db.flush()

        # Corrupt the source so Pillow decode fails cleanly inside
        # save_image_with_thumbnail's thumbnail-generation step —
        # which our fix moved BEFORE the hero write, so nothing lands
        # in storage at all.
        broken_png_upload = UploadFile(
            file=io.BytesIO(b"\x89PNGnot-a-real-png"),
            filename="broken.png",
            headers={"content-type": "image/png"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException):
            asyncio.run(upload_artwork(
                key="orphan-guard", file=broken_png_upload, db=db, _=admin,
            ))
        # DB unchanged.
        db.refresh(loc)
        assert loc.hero_artwork_url is None
        assert loc.thumbnail_artwork_url is None
        # And no orphan files under the target subdir.
        target = tmp_path / "platform-artwork" / "atlas-locations" / "orphan-guard"
        if target.exists():
            assert list(target.iterdir()) == [], (
                "no files should have been written for a failed upload"
            )


# ---------------------------------------------------------------------------
# Clear — must work for both legacy (private-path) and new (public-path) URLs
# ---------------------------------------------------------------------------


class TestArtworkClear:
    def test_clear_removes_legacy_private_path_urls(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        """A Location that still carries the legacy
        ``atlas-locations/{key}/…`` (private-namespace) URL must be
        cleanable so we can tidy up production's one pre-fix upload."""
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        subdir = tmp_path / "atlas-locations" / "legacy-clear"
        subdir.mkdir(parents=True)
        hero_file = subdir / "LEGACY_hero.png"
        thumb_file = subdir / "LEGACY_thumb_hero.png"
        hero_file.write_bytes(_PNG_BYTES)
        thumb_file.write_bytes(_PNG_BYTES)

        admin = make_user(role="admin")
        loc = _location(
            key="legacy-clear", name="Legacy Clear",
            hero_artwork_url="/api/uploads/atlas-locations/legacy-clear/LEGACY_hero.png",
            thumbnail_artwork_url="/api/uploads/atlas-locations/legacy-clear/LEGACY_thumb_hero.png",
        )
        db.add(loc)
        db.flush()

        result = clear_artwork(key="legacy-clear", db=db, _=admin)
        assert result.hero_artwork_url is None
        assert result.thumbnail_artwork_url is None
        assert not hero_file.exists()
        assert not thumb_file.exists()

    def test_clear_removes_new_public_path_urls(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        subdir = tmp_path / "platform-artwork" / "atlas-locations" / "public-clear"
        subdir.mkdir(parents=True)
        hero_file = subdir / "NEW_hero.png"
        thumb_file = subdir / "NEW_thumb_hero.png"
        hero_file.write_bytes(_PNG_BYTES)
        thumb_file.write_bytes(_PNG_BYTES)

        admin = make_user(role="admin")
        loc = _location(
            key="public-clear", name="Public Clear",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/public-clear/NEW_hero.png"
            ),
            thumbnail_artwork_url=(
                "/api/uploads/platform-artwork/atlas-locations/public-clear/NEW_thumb_hero.png"
            ),
        )
        db.add(loc)
        db.flush()

        result = clear_artwork(key="public-clear", db=db, _=admin)
        assert result.hero_artwork_url is None
        assert result.thumbnail_artwork_url is None
        assert not hero_file.exists()
        assert not thumb_file.exists()
