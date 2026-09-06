"""
Serving for stored uploads. Two flavours:

GET /api/uploads/platform-artwork/{file_path:path}
    Publicly readable. Platform artwork is rendered on unauthenticated
    marketing pages (e.g. /for-creators, homepage hero), so its files
    cannot be gated on a session. In R2 mode this returns a 302 to the
    public R2 origin (``R2_PUBLIC_BASE_URL``). In filesystem mode it
    serves the local file directly.

GET /api/uploads/{file_path:path}
    All other uploads (avatars, cover images, resources, atlas artwork,
    community images, etc.) require a signed-in user of any role. In
    R2 mode this returns a 302 to a short-lived pre-signed R2 GET URL
    (5 minutes) for the private bucket. In filesystem mode it serves
    the local file directly.

Path traversal is blocked in filesystem mode by ``resolve()`` +
``is_relative_to(UPLOAD_DIR)``. In R2 mode any ``..`` segment in the
requested path is rejected outright — R2 keys are opaque strings, but
refusing traversal-shaped requests keeps the write and read layers
consistent and defends against future misuse.

The DB values are the same in both modes: ``/api/uploads/{key}``.
Storage backend swap requires zero DB migration.
"""

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.auth.dependencies import get_current_user
from app.core import storage as storage_module
from app.core.config import settings
from app.core.storage import UPLOAD_DIR
from app.models.user import User

uploads_router = APIRouter(prefix="/api/uploads", tags=["uploads"])


# Pre-signed URL lifetime for private-bucket redirects. Short by design
# — long enough for a page load to complete, short enough that a leaked
# URL (Slack paste, screenshot with URL bar, browser history export)
# stops working before it can be exploited.
_PRESIGNED_URL_EXPIRY_SECONDS = 300


def _reject_traversal(file_path: str) -> None:
    """Refuse ``..`` in the requested key. R2 keys are literal, so a
    ``..`` segment is not a filesystem traversal — but it still smells
    wrong and lets us surface bugs early instead of silently 404ing
    against R2."""
    for part in file_path.split("/"):
        if part == "..":
            raise HTTPException(status_code=400, detail="Invalid path.")


def _serve_from_filesystem(file_path: str) -> FileResponse:
    """Filesystem-mode serving — the pre-Stage-B behaviour, preserved
    for local dev and tests that write to UPLOAD_DIR."""
    target = (UPLOAD_DIR / file_path).resolve()
    root = UPLOAD_DIR.resolve()

    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    media_type, _ = mimetypes.guess_type(str(target))
    # ``Cross-Origin-Resource-Policy: cross-origin`` lets fc-web embed
    # these bytes as ``<img src>`` from a different origin.
    # ``X-Content-Type-Options: nosniff`` refuses browser MIME
    # sniffing — ``media_type`` is authoritative.
    return FileResponse(
        str(target),
        media_type=media_type or "application/octet-stream",
        headers={
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _redirect_to_public_r2(key: str) -> RedirectResponse:
    """Public-bucket redirect. ``R2_PUBLIC_BASE_URL`` is the origin
    (R2.dev subdomain initially, custom domain later); the key is
    URL-encoded per component so path segments with reserved chars
    still resolve correctly."""
    assert settings.r2_public_base_url is not None
    base = settings.r2_public_base_url.rstrip("/")
    # ``quote`` with ``safe='/'`` preserves the path structure while
    # escaping anything else; keys are UUID-prefixed so this rarely
    # matters, but it is the safe encoding either way.
    encoded = quote(key, safe="/")
    return RedirectResponse(
        url=f"{base}/{encoded}",
        status_code=302,
        headers={
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _redirect_to_presigned_r2(key: str) -> RedirectResponse:
    """Private-bucket redirect via a short-lived pre-signed URL. Called
    only after the auth-gated route has verified the user's session."""
    assert settings.r2_bucket_private is not None
    # Attribute lookup at call time (via the module reference) so tests
    # that monkeypatch ``storage_module._r2_client`` are observed here.
    url = storage_module._r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_private, "Key": key},
        ExpiresIn=_PRESIGNED_URL_EXPIRY_SECONDS,
    )
    return RedirectResponse(
        url=url,
        status_code=302,
        headers={
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
            # A pre-signed URL is caller-specific and time-bounded; any
            # shared cache that stored the 302 would hand the same URL
            # to other users well past its usefulness. Force no-store
            # so intermediaries do not stash it.
            "Cache-Control": "private, max-age=0, no-store",
        },
    )


# Public route — declared first so FastAPI's specificity ordering picks
# it before the catch-all below.
@uploads_router.get("/platform-artwork/{file_path:path}")
def serve_public_upload(file_path: str):
    _reject_traversal(file_path)
    key = f"platform-artwork/{file_path}"
    if settings.is_r2_enabled:
        return _redirect_to_public_r2(key)
    return _serve_from_filesystem(key)


@uploads_router.get("/{file_path:path}")
def serve_upload(
    file_path: str,
    current_user: User = Depends(get_current_user),
):
    _reject_traversal(file_path)
    if settings.is_r2_enabled:
        return _redirect_to_presigned_r2(file_path)
    return _serve_from_filesystem(file_path)
