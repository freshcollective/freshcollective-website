"""
File serving for locally-stored uploads.

GET /api/uploads/platform-artwork/{file_path:path}
    Publicly readable. Platform artwork is rendered on unauthenticated
    marketing pages (e.g. /for-creators, homepage hero), so its files
    cannot be gated on a session.

GET /api/uploads/{file_path:path}
    All other uploads (avatars, cover images, resources, etc.) require
    a signed-in user of any role.

Path traversal is blocked by checking that the resolved path remains
inside UPLOAD_DIR.

Production note: replace this with presigned S3 GET URLs — no code
changes outside this file are needed. Public files would live in a
CDN-fronted bucket; private files behind signed URLs.
"""

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.core.storage import UPLOAD_DIR
from app.models.user import User

uploads_router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _serve(file_path: str) -> FileResponse:
    target = (UPLOAD_DIR / file_path).resolve()
    root = UPLOAD_DIR.resolve()

    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    media_type, _ = mimetypes.guess_type(str(target))
    # SEC-011 Stage A — ``Cross-Origin-Resource-Policy: cross-origin``
    # lets fc-web embed these bytes as ``<img src>`` from a different
    # origin. Without it, a future ``Cross-Origin-Embedder-Policy``
    # tightening on fc-web would silently block every media load.
    # ``X-Content-Type-Options: nosniff`` refuses browser MIME
    # sniffing — the media_type guessed above is authoritative.
    # (The transport HSTS + Referrer-Policy headers are added
    # uniformly by the FastAPI middleware in ``app.main``.)
    return FileResponse(
        str(target),
        media_type=media_type or "application/octet-stream",
        headers={
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Public route — declared first so FastAPI's specificity ordering picks
# it before the catch-all below.
@uploads_router.get("/platform-artwork/{file_path:path}")
def serve_public_upload(file_path: str) -> FileResponse:
    return _serve(f"platform-artwork/{file_path}")


@uploads_router.get("/{file_path:path}")
def serve_upload(
    file_path: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    return _serve(file_path)
