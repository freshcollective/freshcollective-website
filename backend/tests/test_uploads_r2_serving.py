"""Persistent Media Storage Stage B — /api/uploads/* serving tests.

Locks in the redirect behaviour of ``app.uploads.routes`` under R2
mode while confirming the filesystem-mode branch still works. The
serving router owns three invariants:

  1. Public route (``/api/uploads/platform-artwork/*``) redirects to
     ``R2_PUBLIC_BASE_URL/<key>`` without an auth check.
  2. Private route (``/api/uploads/*``) requires auth first, then
     redirects to a short-lived pre-signed URL against the private
     bucket. Unauthenticated calls remain rejected before any R2
     interaction happens.
  3. Path traversal (``..``) is rejected in both modes with a 400.

Filesystem-mode tests live in ``test_uploads_public_prefix.py`` and
are exercised whenever ``settings.is_r2_enabled`` is False — no R2
credentials are set in the test env, so those tests run in that
branch by default. This file focuses on the R2 branch.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import storage as storage_module
from app.core.config import settings
from app.main import app


# ---------------------------------------------------------------------------
# Fixture — enable R2 mode + swap in a mock client
# ---------------------------------------------------------------------------


_PRESIGNED_URL = (
    "https://test-account.r2.cloudflarestorage.com/fc-media-test/"
    "avatars/some-key?X-Amz-Signature=fake&X-Amz-Expires=300"
)


@pytest.fixture
def r2_serving(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(settings, "r2_account_id", "test-account", raising=False)
    monkeypatch.setattr(settings, "r2_access_key_id", "test-access", raising=False)
    monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_private", "fc-media-test", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_public", "fc-media-public-test", raising=False)
    monkeypatch.setattr(
        settings, "r2_public_base_url", "https://pub-test.r2.dev", raising=False,
    )

    client = MagicMock(name="R2Client")
    client.generate_presigned_url.return_value = _PRESIGNED_URL

    storage_module.reset_r2_client_cache()
    monkeypatch.setattr(storage_module, "_r2_client", lambda: client)
    yield client


@pytest.fixture
def client() -> TestClient:
    # follow_redirects=False so we can inspect the 302 target.
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Public route — redirect to R2_PUBLIC_BASE_URL
# ---------------------------------------------------------------------------


class TestPublicRouteR2Mode:
    def test_public_route_redirects_to_public_r2(
        self, client: TestClient, r2_serving: MagicMock,
    ) -> None:
        r = client.get("/api/uploads/platform-artwork/hero/xyz.png")
        assert r.status_code == 302
        assert r.headers["location"] == (
            "https://pub-test.r2.dev/platform-artwork/hero/xyz.png"
        )

    def test_public_route_does_not_generate_presigned(
        self, client: TestClient, r2_serving: MagicMock,
    ) -> None:
        client.get("/api/uploads/platform-artwork/hero/xyz.png")
        # Public bucket has no signing — the R2 Public URL is the
        # final destination.
        r2_serving.generate_presigned_url.assert_not_called()

    def test_public_route_carries_corp_and_xcto(
        self, client: TestClient, r2_serving: MagicMock,
    ) -> None:
        r = client.get("/api/uploads/platform-artwork/hero/xyz.png")
        assert r.headers.get("cross-origin-resource-policy") == "cross-origin"
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_public_route_needs_no_auth(
        self, client: TestClient, r2_serving: MagicMock,
    ) -> None:
        # No session cookie set — must still succeed with the redirect.
        r = client.get("/api/uploads/platform-artwork/hero/xyz.png")
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Private route — auth gate + pre-signed redirect
# ---------------------------------------------------------------------------


class TestPrivateRouteR2Mode:
    def test_unauthenticated_call_is_rejected_before_r2(
        self, client: TestClient, r2_serving: MagicMock,
    ) -> None:
        r = client.get("/api/uploads/avatars/some-key.png")
        assert r.status_code in (401, 403)
        # No R2 interaction happened — auth gate ran first.
        r2_serving.generate_presigned_url.assert_not_called()

    def test_authenticated_call_redirects_to_presigned(
        self, client: TestClient, r2_serving: MagicMock,
        db, make_user,
    ) -> None:
        from app.auth.dependencies import get_current_user
        user = make_user()
        # Bypass the real session cookie by overriding the dependency
        # for the duration of this test — the endpoint under test is
        # the redirect logic, not the session lookup.
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            r = client.get("/api/uploads/avatars/some-key.png")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert r.status_code == 302
        assert r.headers["location"] == _PRESIGNED_URL
        r2_serving.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "fc-media-test", "Key": "avatars/some-key.png"},
            ExpiresIn=300,
        )

    def test_private_redirect_forbids_shared_caching(
        self, client: TestClient, r2_serving: MagicMock,
        db, make_user,
    ) -> None:
        from app.auth.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: make_user()
        try:
            r = client.get("/api/uploads/avatars/some-key.png")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        # Pre-signed URLs are caller-specific and time-bounded — any
        # shared cache stashing the 302 would hand the same URL back
        # to a different user later.
        cache_control = (r.headers.get("cache-control") or "").lower()
        assert "no-store" in cache_control


# ---------------------------------------------------------------------------
# Traversal protection (function-level — HTTP clients normalise `..`
# before it reaches the server, so we exercise the helper directly)
# ---------------------------------------------------------------------------


class TestTraversalGuard:
    def test_dotdot_at_start_rejected(self) -> None:
        from fastapi import HTTPException
        from app.uploads.routes import _reject_traversal

        with pytest.raises(HTTPException) as ex:
            _reject_traversal("../secret")
        assert ex.value.status_code == 400

    def test_dotdot_in_middle_rejected(self) -> None:
        from fastapi import HTTPException
        from app.uploads.routes import _reject_traversal

        with pytest.raises(HTTPException) as ex:
            _reject_traversal("avatars/../covers/secret.png")
        assert ex.value.status_code == 400

    def test_plain_key_accepted(self) -> None:
        from app.uploads.routes import _reject_traversal
        _reject_traversal("avatars/uuid_face.jpg")  # no raise
        _reject_traversal("media/some-space/community/x.png")

    def test_key_containing_dots_but_not_dotdot_accepted(self) -> None:
        # ``file.name.ext`` and hidden-file segments should not trip
        # the guard.
        from app.uploads.routes import _reject_traversal
        _reject_traversal("covers/my.file.name.png")
        _reject_traversal("covers/.hidden.png")
