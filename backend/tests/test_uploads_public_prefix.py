"""Uploads route — public-prefix carve-out.

The /api/uploads endpoint serves two kinds of files:

* platform-artwork/*  — rendered on public marketing pages, must be
                        reachable without a session cookie
* everything else     — private uploads; any signed-in user OK, but
                        signed-out callers must be rejected

These tests exercise the gating alone. File serving itself is a thin
FileResponse wrapper we don't need to re-verify.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.storage import UPLOAD_DIR
from app.main import app


@pytest.fixture
def platform_artwork_file() -> Path:
    """Write a tiny throwaway file under uploads/platform-artwork/ and
    yield its path so the route can find something real to serve."""
    subdir = UPLOAD_DIR / "platform-artwork"
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"test-{uuid.uuid4().hex}.txt"
    path.write_bytes(b"public artwork bytes")
    try:
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@pytest.fixture
def private_upload_file() -> Path:
    """Write a tiny throwaway file under uploads/misc/ — a path with no
    public carve-out — so we can verify auth is still enforced."""
    subdir = UPLOAD_DIR / "misc"
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"test-{uuid.uuid4().hex}.txt"
    path.write_bytes(b"private bytes")
    try:
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def test_platform_artwork_served_without_auth(platform_artwork_file: Path) -> None:
    """/api/uploads/platform-artwork/* returns 200 with no session cookie —
    it powers the public /for-creators and homepage marketing pages."""
    client = TestClient(app)
    rel = platform_artwork_file.relative_to(UPLOAD_DIR).as_posix()
    res = client.get(f"/api/uploads/{rel}")
    assert res.status_code == 200, res.text
    assert res.content == b"public artwork bytes"


def test_non_public_upload_requires_auth(private_upload_file: Path) -> None:
    """Any other prefix keeps the existing signed-in gate — an
    unauthenticated request must be rejected before the file is served."""
    client = TestClient(app)
    rel = private_upload_file.relative_to(UPLOAD_DIR).as_posix()
    res = client.get(f"/api/uploads/{rel}")
    assert res.status_code in (401, 403), res.text
