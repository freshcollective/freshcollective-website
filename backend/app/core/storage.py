"""
Local file storage for V1/dev.

Files are stored under backend/uploads/{subdir}/{uuid_filename}.
Served via GET /api/uploads/{subdir}/{uuid_filename} (auth required).

Production upgrade path: replace save_file / delete_file with presigned S3 PUT/DELETE,
store the S3 key in the url column, and serve via presigned GET URLs instead of
/api/uploads. The rest of the codebase does not need to change.
"""

import pathlib
import re
from uuid import uuid4

# Absolute path to the uploads root, resolved relative to this file.
UPLOAD_DIR = pathlib.Path(__file__).parent.parent.parent / "uploads"

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB

ALLOWED_EXTENSIONS = {
    ".pdf", ".mp4", ".mov", ".mp3", ".wav", ".m4a",
    ".docx", ".png", ".jpg", ".jpeg",
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


def delete_file(rel_path: str) -> None:
    """Remove a stored file. Silently ignores missing files or path traversal attempts."""
    try:
        target = (UPLOAD_DIR / rel_path).resolve()
        root = UPLOAD_DIR.resolve()
        if target.is_relative_to(root) and target.is_file():
            target.unlink()
    except Exception:
        pass
