"""
Authenticated file serving for locally-stored uploads.

GET /api/uploads/{file_path:path}

Any logged-in user (learner, creator, admin) can fetch files.
Path traversal is blocked by checking that the resolved path remains
inside UPLOAD_DIR.

Production note: replace this with presigned S3 GET URLs — no code
changes outside this file are needed.
"""

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.core.storage import UPLOAD_DIR
from app.models.user import User

uploads_router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@uploads_router.get("/{file_path:path}")
def serve_upload(
    file_path: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    target = (UPLOAD_DIR / file_path).resolve()
    root = UPLOAD_DIR.resolve()

    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=media_type or "application/octet-stream")
