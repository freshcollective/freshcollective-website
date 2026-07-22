"""
Local file storage for V1/dev.

Files are stored under backend/uploads/{subdir}/{uuid_filename}.
Served via GET /api/uploads/{subdir}/{uuid_filename} (auth required).

Production upgrade path: replace save_file / delete_file with presigned S3 PUT/DELETE,
store the S3 key in the url column, and serve via presigned GET URLs instead of
/api/uploads. The rest of the codebase does not need to change.
"""

import io
import pathlib
import re
from uuid import uuid4

# Absolute path to the uploads root, resolved relative to this file.
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


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w.\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:120] or "file"


def save_file(
    data: bytes,
    original_name: str,
    mime_type: str,
    subdir: str,
) -> tuple[str, str, int]:
    """
    Persist upload bytes to disk.

    Returns:
        rel_path      — relative path from UPLOAD_DIR, used as the URL path segment
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

    dest_dir = UPLOAD_DIR / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / stored_name).write_bytes(data)

    rel_path = f"{subdir}/{stored_name}"
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
    Save a media-library file to disk under uploads/media/{space_slug}/.

    Returns:
        storage_path    — relative path within UPLOAD_DIR (e.g. "media/my-space/abc_file.pdf")
        file_url        — URL path for serving  (e.g. "/api/uploads/media/my-space/abc_file.pdf")
        media_type      — "image" | "video" | "audio" | "document" | "other"
        stored_filename — just the filename portion
        size            — byte count

    TODO: protect private member resources behind authenticated access checks before production.
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
    dest_dir = UPLOAD_DIR / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / stored_filename).write_bytes(data)

    storage_path = f"{subdir}/{stored_filename}"
    file_url = f"/api/uploads/{storage_path}"
    return storage_path, file_url, media_type, stored_filename, size


def delete_file(rel_path: str) -> None:
    """Remove a stored file. Silently ignores missing files or path traversal attempts."""
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

    The hero preserves the original bytes. The thumbnail is downscaled to
    `target_width` while preserving aspect ratio; images narrower than the
    target width are not upscaled — the thumbnail simply mirrors the hero
    at its native size.

    Returns:
        hero_rel_path      — relative path used to construct the URL
        thumbnail_rel_path — sibling path for the generated thumbnail
    """
    hero_rel, _resource, _size = save_file(data, original_name, mime_type, subdir)
    thumb_bytes, thumb_name = generate_thumbnail_bytes(data, original_name, target_width)
    thumb_rel, _r2, _s2 = save_file(thumb_bytes, thumb_name, mime_type, subdir)
    return hero_rel, thumb_rel
