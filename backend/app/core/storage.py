"""File storage — Cloudflare R2 in production, local disk in dev/test.

Mode selection is per-call and gated on ``settings.is_r2_enabled``.
When any R2 env var is unset the module writes to ``backend/uploads/``
under UPLOAD_DIR — the pre-Stage-B behaviour — so tests and local dev
do not require R2 credentials.

Public / private split
----------------------
The R2 side is two buckets, chosen to mirror the split already enforced
by ``app/uploads/routes.py``:

  * ``r2_bucket_public``  — keys under ``platform-artwork/*``. Fronted
    by an R2 public URL (temporarily the R2.dev subdomain; later
    ``media.freshcollective.com``). Served with a plain 302 redirect
    from ``/api/uploads/platform-artwork/*``.
  * ``r2_bucket_private`` — every other key (avatars, covers, logos,
    pathway covers, media library, community images, gathering
    artwork, step resources, atlas/place artwork, world guide).
    Served via short-lived pre-signed URLs from the auth-gated
    ``/api/uploads/*`` route after the user's session is verified.

The bucket for a given key is decided by ``_bucket_for_key`` — the
sole authoritative mapping. Callers do not choose a bucket; they
choose a subdir and the routing follows.

Key structure is unchanged from the local-disk layout:
``{subdir}/{uuid}_{sanitised_filename}``. That means DB values stored
as ``/api/uploads/{key}`` continue to work verbatim — the serving
router translates them to R2 at read time. Storage backend swap
requires zero DB migration.

Deletions call the R2 DeleteObject on the correct bucket (S3 API is
idempotent: a missing key is not an error). Filesystem fallback keeps
the pre-existing ``resolve() + is_relative_to`` traversal guard.
"""

from __future__ import annotations

import io
import pathlib
import re
from functools import lru_cache
from typing import TYPE_CHECKING
from uuid import uuid4

from app.core.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client


# Absolute path to the on-disk uploads root, used in filesystem mode
# and by scripts/tests that monkeypatch this attribute. Kept exported
# unchanged from pre-Stage-B so ``backfill_location_thumbnails.py``,
# ``tests/test_uploads_public_prefix.py``, ``tests/test_security_headers.py``,
# ``tests/test_world_guide.py`` and ``tests/test_physical_locations_routes.py``
# continue to work without modification.
UPLOAD_DIR = pathlib.Path(__file__).parent.parent.parent / "uploads"

# Target width for auto-generated thumbnails of curated artwork
# (Locations, Platform Artwork). Chosen to look sharp at typical card
# sizes on 2x displays without bloating page weight. Height derives
# from the source aspect ratio; smaller sources are left untouched.
THUMBNAIL_TARGET_WIDTH = 600

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB

ALLOWED_EXTENSIONS = {
    ".pdf", ".mp4", ".mov", ".mp3", ".wav", ".m4a",
    ".docx", ".png", ".jpg", ".jpeg", ".webp",
}

MIME_TO_RESOURCE_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
    "audio/aac": "audio",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "file",
    "image/png": "file",
    "image/jpeg": "file",
}


# ---------------------------------------------------------------------------
# R2 client — lazy, cached
# ---------------------------------------------------------------------------

# ``lru_cache`` gives us one boto3 client for the process. boto3 clients
# are threadsafe and cheap to reuse; recreating per request would add
# TLS setup overhead on every upload. Tests that toggle R2 mode call
# ``reset_r2_client_cache()`` to force reconstruction against the
# monkeypatched settings.
@lru_cache(maxsize=1)
def _r2_client() -> "S3Client":
    """Build the S3-compatible client for R2. Callers MUST gate on
    ``settings.is_r2_enabled`` first; this function assumes every
    credential is set."""
    import boto3  # local import — avoids paying import cost in FS mode

    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # R2 ignores region but boto3 requires *something*. "auto" is the
        # Cloudflare-documented value.
        region_name="auto",
    )


def reset_r2_client_cache() -> None:
    """Force the next ``_r2_client()`` call to rebuild against current
    settings. Used only by tests that toggle R2 mode on/off."""
    _r2_client.cache_clear()


def _bucket_for_key(key: str) -> str:
    """Route a storage key to the correct R2 bucket.

    Mirrors the /api/uploads router split: public bucket owns
    ``platform-artwork/*`` keys, private bucket owns everything else.
    Atlas + physical-location artwork is intentionally private today —
    served through the auth-gated route — so it maps to the private
    bucket even though it is curated content.
    """
    if key.startswith("platform-artwork/"):
        assert settings.r2_bucket_public is not None
        return settings.r2_bucket_public
    assert settings.r2_bucket_private is not None
    return settings.r2_bucket_private


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w.\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:120] or "file"


def _fs_write(subdir: str, stored_name: str, data: bytes) -> None:
    """Filesystem-mode write. Used only when R2 is not enabled — e.g.
    local dev and every backend test that doesn't opt into R2 mode."""
    dest_dir = UPLOAD_DIR / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / stored_name).write_bytes(data)


def _r2_put(key: str, data: bytes, content_type: str | None) -> None:
    """R2-mode write. Bucket is derived from the key; content type is
    passed through so the browser sees the right MIME on subsequent
    presigned/public GETs."""
    _r2_client().put_object(
        Bucket=_bucket_for_key(key),
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )


# ---------------------------------------------------------------------------
# Public API — kept identical to pre-Stage-B so callers do not change
# ---------------------------------------------------------------------------


def save_file(
    data: bytes,
    original_name: str,
    mime_type: str,
    subdir: str,
) -> tuple[str, str, int]:
    """
    Persist upload bytes.

    Returns:
        rel_path      — relative path from UPLOAD_DIR / bucket root,
                        used as the URL path segment
        resource_type — inferred type string (video | audio | pdf | file)
        size          — byte count
    """
    ext = pathlib.Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type '{ext}' is not permitted. "
            "Allowed: pdf, mp4, mov, mp3, wav, m4a, docx, png, jpg"
        )

    size = len(data)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("File exceeds the 200 MB size limit.")

    safe_base = _sanitize_filename(pathlib.Path(original_name).stem)
    stored_name = f"{uuid4().hex}_{safe_base}{ext}"
    rel_path = f"{subdir}/{stored_name}"

    if settings.is_r2_enabled:
        _r2_put(rel_path, data, mime_type)
    else:
        _fs_write(subdir, stored_name, data)

    resource_type = MIME_TO_RESOURCE_TYPE.get(mime_type, "file")
    return rel_path, resource_type, size


# ---------------------------------------------------------------------------
# Media Library — extended upload support
# ---------------------------------------------------------------------------

# (media_type, max_bytes)
MEDIA_EXTENSION_MAP: dict[str, tuple[str, int]] = {
    # Images — 10 MB
    ".jpg":  ("image",    10 * 1024 * 1024),
    ".jpeg": ("image",    10 * 1024 * 1024),
    ".png":  ("image",    10 * 1024 * 1024),
    ".webp": ("image",    10 * 1024 * 1024),
    # Documents — 25 MB
    ".pdf":  ("document", 25 * 1024 * 1024),
    ".doc":  ("document", 25 * 1024 * 1024),
    ".docx": ("document", 25 * 1024 * 1024),
    ".xls":  ("document", 25 * 1024 * 1024),
    ".xlsx": ("document", 25 * 1024 * 1024),
    ".ppt":  ("document", 25 * 1024 * 1024),
    ".pptx": ("document", 25 * 1024 * 1024),
    # Audio — 50 MB
    ".mp3":  ("audio",    50 * 1024 * 1024),
    ".wav":  ("audio",    50 * 1024 * 1024),
    ".m4a":  ("audio",    50 * 1024 * 1024),
    # Video — 250 MB for dev/testing only
    # TODO: Move video storage/streaming to Mux, Cloudflare Stream, S3, or similar before production-scale use.
    ".mp4":  ("video",   250 * 1024 * 1024),
    ".mov":  ("video",   250 * 1024 * 1024),
    ".webm": ("video",   250 * 1024 * 1024),
}


def save_media_file(
    data: bytes,
    original_name: str,
    mime_type: str,
    space_slug: str,
) -> tuple[str, str, str, str, int]:
    """
    Save a media-library file. Key layout: ``media/{safe_slug}/…``.

    Returns:
        storage_path    — relative path (e.g. "media/my-space/abc_file.pdf")
        file_url        — URL path for serving  (e.g. "/api/uploads/media/my-space/abc_file.pdf")
        media_type      — "image" | "video" | "audio" | "document" | "other"
        stored_filename — just the filename portion
        size            — byte count
    """
    ext = pathlib.Path(original_name).suffix.lower()
    if ext not in MEDIA_EXTENSION_MAP:
        allowed = ", ".join(sorted(MEDIA_EXTENSION_MAP.keys()))
        raise ValueError(
            f"File type '{ext}' is not permitted. Allowed: {allowed}"
        )

    media_type, max_bytes = MEDIA_EXTENSION_MAP[ext]
    size = len(data)
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ValueError(f"File exceeds the {mb} MB limit for {media_type} files.")

    safe_base = _sanitize_filename(pathlib.Path(original_name).stem)
    stored_filename = f"{uuid4().hex}_{safe_base}{ext}"

    safe_slug = re.sub(r"[^\w\-]", "_", space_slug)[:50]
    subdir = f"media/{safe_slug}"
    storage_path = f"{subdir}/{stored_filename}"

    if settings.is_r2_enabled:
        _r2_put(storage_path, data, mime_type)
    else:
        _fs_write(subdir, stored_filename, data)

    file_url = f"/api/uploads/{storage_path}"
    return storage_path, file_url, media_type, stored_filename, size


def delete_file(rel_path: str) -> None:
    """Remove a stored file. Silently ignores missing files (R2 side)
    and path-traversal attempts (filesystem side)."""
    if not rel_path:
        return

    if settings.is_r2_enabled:
        try:
            _r2_client().delete_object(
                Bucket=_bucket_for_key(rel_path),
                Key=rel_path,
            )
        except Exception:
            # Deletion is best-effort — mirrors the filesystem branch's
            # swallow-and-continue posture. Callers do not rely on
            # deletion success (parent-row commit is authoritative).
            pass
        return

    try:
        target = (UPLOAD_DIR / rel_path).resolve()
        root = UPLOAD_DIR.resolve()
        if target.is_relative_to(root) and target.is_file():
            target.unlink()
    except Exception:
        pass


class StorageDeleteError(RuntimeError):
    """Raised by ``delete_keys`` when the R2 bulk delete surfaces a
    hard error the caller needs to know about (network failure,
    permission denied). Missing keys are NOT errors — S3
    ``DeleteObjects`` is idempotent by design.

    Used by orchestrated multi-step deletes (e.g. Collective delete
    in ``creator/routes.py``) that want to abort before making
    irreversible DB changes if the storage backend is unavailable."""


def delete_keys(keys: list[str]) -> None:
    """Delete an explicit list of storage keys.

    Different contract from ``delete_file``:

      * ``delete_file(key)`` is best-effort — swallows all errors.
        Used for single-object cleanup where the parent row commit
        is authoritative and R2 orphans are acceptable.

      * ``delete_keys(keys)`` RAISES ``StorageDeleteError`` on hard
        R2 errors so a caller doing a multi-step orchestration
        (e.g. delete R2 media → delete DB rows) can abort BEFORE
        the irreversible DB step. Missing keys remain non-errors
        (S3 ``DeleteObjects`` is idempotent).

    Bucket routing: each key routes to public or private based on
    the ``platform-artwork/`` prefix, matching ``save_file``.

    In filesystem mode, unlinks each and ignores missing files;
    never raises.
    """
    if not keys:
        return

    if not settings.is_r2_enabled:
        for key in keys:
            _fs_delete_one(key)
        return

    # Group by bucket so each ``delete_objects`` call targets exactly
    # one bucket (S3 API constraint).
    by_bucket: dict[str, list[str]] = {}
    for key in keys:
        if not key:
            continue
        by_bucket.setdefault(_bucket_for_key(key), []).append(key)

    client = _r2_client()
    hard_errors: list[str] = []
    for bucket, bucket_keys in by_bucket.items():
        # S3 caps bulk delete at 1000 keys per call. Chunk for safety.
        for i in range(0, len(bucket_keys), 1000):
            chunk = bucket_keys[i : i + 1000]
            resp = client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
            )
            # ``Quiet`` suppresses per-object success entries; only
            # errors appear in the response. Any key-level error
            # here is hard (auth, throttling); missing keys do not
            # produce entries.
            for err in resp.get("Errors", []) or []:
                hard_errors.append(
                    f"{err.get('Key')}: {err.get('Code')} {err.get('Message')}"
                )

    if hard_errors:
        raise StorageDeleteError(
            "R2 bulk delete reported errors: " + "; ".join(hard_errors[:5])
            + (f" (and {len(hard_errors) - 5} more)" if len(hard_errors) > 5 else "")
        )


def _fs_delete_one(rel_path: str) -> None:
    """Filesystem-mode single-file delete for ``delete_keys``. Same
    traversal guard as ``delete_file``; missing files silently
    tolerated."""
    try:
        target = (UPLOAD_DIR / rel_path).resolve()
        root = UPLOAD_DIR.resolve()
        if target.is_relative_to(root) and target.is_file():
            target.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Curated artwork — hero + auto-generated thumbnail
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Map source extension → (Pillow save format, output extension).
_THUMBNAIL_FORMAT: dict[str, tuple[str, str]] = {
    ".jpg":  ("JPEG", ".jpg"),
    ".jpeg": ("JPEG", ".jpg"),
    ".png":  ("PNG",  ".png"),
    ".webp": ("WEBP", ".webp"),
}


def generate_thumbnail_bytes(
    data: bytes,
    original_name: str,
    target_width: int = THUMBNAIL_TARGET_WIDTH,
) -> tuple[bytes, str]:
    """Resize a source image and return the thumbnail bytes plus a
    suggested filename.

    Preserves aspect ratio. Images narrower than `target_width` are not
    upscaled — the "thumbnail" mirrors the source at its native size.

    Returns:
        thumb_bytes  — encoded thumbnail image
        thumb_name   — filename with a `thumb_` prefix and the source's stem,
                       suitable to pass to `save_file`.
    """
    # Local import so the storage module doesn't hard-require Pillow at
    # import time — helpful for lightweight test environments that don't
    # touch image uploads.
    from PIL import Image  # type: ignore[import-not-found]

    ext = pathlib.Path(original_name).suffix.lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise ValueError("Only JPG, PNG, and WebP images are allowed.")

    save_format, out_ext = _THUMBNAIL_FORMAT[ext]
    with Image.open(io.BytesIO(data)) as im:
        # Preserve transparency for PNG/WebP; JPEG needs an opaque base.
        if save_format == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        width, height = im.size
        if width > target_width:
            new_height = max(1, round(height * (target_width / width)))
            thumb = im.resize((target_width, new_height), Image.LANCZOS)
        else:
            thumb = im.copy()

        buf = io.BytesIO()
        save_kwargs: dict[str, object] = {"format": save_format}
        if save_format == "JPEG":
            save_kwargs["quality"] = 85
            save_kwargs["optimize"] = True
        elif save_format == "WEBP":
            save_kwargs["quality"] = 85
            save_kwargs["method"] = 6
        elif save_format == "PNG":
            save_kwargs["optimize"] = True
        thumb.save(buf, **save_kwargs)

    stem = pathlib.Path(original_name).stem
    return buf.getvalue(), f"thumb_{stem}{out_ext}"


def save_image_with_thumbnail(
    data: bytes,
    original_name: str,
    mime_type: str,
    subdir: str,
    target_width: int = THUMBNAIL_TARGET_WIDTH,
) -> tuple[str, str]:
    """Persist a curated image and generate a proportional thumbnail.

    The hero preserves the original bytes. The thumbnail is downscaled
    to ``target_width`` while preserving aspect ratio; images narrower
    than the target width are not upscaled — the thumbnail simply
    mirrors the hero at its native size.

    Both files travel through ``save_file``, so both land in the same
    bucket (public if ``subdir`` begins with ``platform-artwork/``,
    private otherwise). This matches the existing behaviour where the
    thumbnail is served through the same URL prefix as the hero.

    Atomic-ish semantics: the thumbnail bytes are generated (Pillow
    validation) BEFORE any storage writes, so an invalid source raises
    without leaving orphan objects. If the hero write succeeds but the
    thumbnail write fails, the just-written hero is deleted to avoid
    leaking storage.
    """
    # Generate the thumbnail first — Pillow's decode/encode is where
    # the vast majority of "bad image" failures happen, and validating
    # here means an invalid source raises before any R2 write.
    # Normalise Pillow's error types (UnidentifiedImageError, OSError
    # on truncated streams) into ValueError so upstream endpoints that
    # catch ValueError can return a clean 400.
    try:
        thumb_bytes, thumb_name = generate_thumbnail_bytes(data, original_name, target_width)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not decode image: {e}") from e

    hero_rel, _resource, _size = save_file(data, original_name, mime_type, subdir)
    try:
        thumb_rel, _r2, _s2 = save_file(thumb_bytes, thumb_name, mime_type, subdir)
    except Exception:
        # Compensate the successful hero write so we don't leak.
        try:
            delete_file(hero_rel)
        except Exception:  # noqa: BLE001
            pass
        raise
    return hero_rel, thumb_rel
