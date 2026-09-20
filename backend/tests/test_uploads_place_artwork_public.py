"""Place hero artwork is publicly readable — without leaving the private bucket.

Discover Places is an unauthenticated surface, and a Place's hero
artwork is curated, member-facing imagery. Before the route this file
covers existed, those objects were unreachable by *everyone*:
``place-artwork`` is not in ``authorize_upload``'s dispatch table, and
that table is default-deny, so an anonymous visitor got 401 and a
signed-in administrator got 403. The artwork rendered nowhere at all.

The fix deliberately did NOT move the objects. They stay in the
private bucket — moving them would mean a data migration and would
invalidate every ``hero_artwork_url`` already stored — so the public
route reads a private object by issuing the same short-lived
pre-signed redirect the auth-gated route uses.

What must stay true, and is asserted below: reads are open, writes are
not, every other private namespace is untouched, and traversal is
still refused.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import storage as storage_module
from app.core.config import settings
from app.core.storage import UPLOAD_DIR
from app.main import app


PLACE_BYTES = b"melbourne hero artwork bytes"


@pytest.fixture
def place_artwork_file() -> Path:
    subdir = UPLOAD_DIR / "place-artwork" / "melbourne"
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"test-{uuid.uuid4().hex}.png"
    path.write_bytes(PLACE_BYTES)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture
def private_upload_file() -> Path:
    """A namespace with no carve-out, to prove the fix was narrow."""
    subdir = UPLOAD_DIR / "avatars"
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"test-{uuid.uuid4().hex}.png"
    path.write_bytes(b"private bytes")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _rel(path: Path) -> str:
    return path.relative_to(UPLOAD_DIR).as_posix()


# ===========================================================================
# Reads are open
# ===========================================================================


class TestAnonymousReads:
    def test_place_artwork_is_served_without_a_session(self, place_artwork_file):
        """The whole point: Discover Places renders for signed-out
        visitors, so its artwork cannot require a cookie."""
        res = TestClient(app).get(f"/api/uploads/{_rel(place_artwork_file)}")
        assert res.status_code == 200, res.text
        assert res.content == PLACE_BYTES

    def test_an_authenticated_caller_gets_it_too(self, place_artwork_file, db, make_user):
        """Opening a namespace publicly must not accidentally close it
        to signed-in users — which is what the dispatch table's
        default-deny did to administrators before this route."""
        from app.auth.dependencies import get_current_user
        from app.core.database import get_db

        app.dependency_overrides[get_current_user] = lambda: make_user()
        app.dependency_overrides[get_db] = lambda: db
        try:
            res = TestClient(app).get(f"/api/uploads/{_rel(place_artwork_file)}")
            assert res.status_code == 200, res.text
            assert res.content == PLACE_BYTES
        finally:
            app.dependency_overrides.clear()

    def test_a_missing_object_is_a_plain_404(self, place_artwork_file):
        """Not a 500, and not a 401 that would imply the namespace is
        private after all."""
        res = TestClient(app).get("/api/uploads/place-artwork/melbourne/nope.png")
        assert res.status_code == 404, res.text

    def test_the_response_is_embeddable_cross_origin(self, place_artwork_file):
        """fc-web renders these from a different origin than fc-api."""
        res = TestClient(app).get(f"/api/uploads/{_rel(place_artwork_file)}")
        assert res.headers.get("cross-origin-resource-policy") == "cross-origin"
        assert res.headers.get("x-content-type-options") == "nosniff"


# ===========================================================================
# The carve-out is narrow
# ===========================================================================


class TestEverythingElseStaysPrivate:
    def test_other_namespaces_still_require_a_session(self, private_upload_file):
        res = TestClient(app).get(f"/api/uploads/{_rel(private_upload_file)}")
        assert res.status_code in (401, 403), res.text

    def test_an_unknown_namespace_is_still_default_denied(self, db, make_user):
        """Signed in, so this is the dispatch table answering, not the
        session gate."""
        from app.auth.dependencies import get_current_user
        from app.core.database import get_db

        app.dependency_overrides[get_current_user] = lambda: make_user()
        app.dependency_overrides[get_db] = lambda: db
        try:
            res = TestClient(app).get("/api/uploads/not-a-namespace/x.png")
            assert res.status_code == 403, res.text
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.parametrize("path", [
        "place-artwork/../avatars/secret.png",
        "place-artwork/melbourne/../../avatars/secret.png",
    ])
    def test_traversal_never_reaches_a_private_file(self, path):
        """Two guards, and the outer one fires first. The client and
        Starlette normalise ``..`` out of the path before routing, so
        these resolve to ``avatars/…`` and hit the auth-gated route —
        401 rather than the 400 the traversal check would give. Either
        answer is a refusal; what matters is that no private object is
        ever handed back, so that is what this asserts."""
        res = TestClient(app).get(f"/api/uploads/{path}")
        assert res.status_code in (400, 401, 403, 404), res.text
        assert res.status_code not in (200, 302)
        assert b"private bytes" not in res.content

    def test_the_traversal_guard_itself_still_rejects(self):
        """Covered directly, because path normalisation means a
        traversal-shaped URL no longer reaches it through the client.
        A caller that does reach the route with a ``..`` segment — a
        server-side call, a future client that does not normalise —
        must still be refused."""
        from fastapi import HTTPException
        from app.uploads.routes import _reject_traversal

        with pytest.raises(HTTPException) as exc:
            _reject_traversal("place-artwork/../avatars/secret.png")
        assert exc.value.status_code == 400
        # And a legitimate key passes untouched.
        _reject_traversal("place-artwork/melbourne/abc_melbourne.png")

    def test_writes_are_still_admin_only(self):
        """Only reading was opened up. Upload and delete live on the
        admin router behind ``get_admin_user``."""
        client = TestClient(app)
        assert client.post(
            "/api/admin/physical-locations/melbourne/artwork",
            files={"file": ("x.png", b"x", "image/png")},
        ).status_code in (401, 403)
        assert client.delete(
            "/api/admin/physical-locations/melbourne/artwork",
        ).status_code in (401, 403)


# ===========================================================================
# R2 mode — public read, private bucket
# ===========================================================================


_PRESIGNED = (
    "https://test-account.r2.cloudflarestorage.com/fc-media-test/"
    "place-artwork/melbourne/x.png?X-Amz-Signature=fake"
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
    mock = MagicMock(name="R2Client")
    mock.generate_presigned_url.return_value = _PRESIGNED
    storage_module.reset_r2_client_cache()
    monkeypatch.setattr(storage_module, "_r2_client", lambda: mock)
    yield mock


class TestR2Mode:
    def test_anonymous_read_redirects_to_a_presigned_private_url(self, r2_serving):
        client = TestClient(app, follow_redirects=False)
        res = client.get("/api/uploads/place-artwork/melbourne/x.png")

        assert res.status_code == 302, res.text
        assert res.headers["location"] == _PRESIGNED
        # The private bucket, not the public one — the objects did not move.
        r2_serving.generate_presigned_url.assert_called_once()
        _args, kwargs = r2_serving.generate_presigned_url.call_args
        assert kwargs["Params"]["Bucket"] == settings.r2_bucket_private
        assert kwargs["Params"]["Key"] == "place-artwork/melbourne/x.png"

    def test_the_redirect_is_never_shared_cached(self, r2_serving):
        """A pre-signed URL is time-bounded; a shared cache holding the
        302 would hand a stale one to later visitors."""
        client = TestClient(app, follow_redirects=False)
        res = client.get("/api/uploads/place-artwork/melbourne/x.png")
        assert "no-store" in res.headers.get("cache-control", "")

    def test_platform_artwork_still_uses_the_public_origin(self, r2_serving):
        """The sibling namespace is unchanged: public bucket, no
        signing. Proves this change did not generalise."""
        client = TestClient(app, follow_redirects=False)
        res = client.get("/api/uploads/platform-artwork/hero/x.png")
        assert res.status_code == 302
        assert res.headers["location"].startswith("https://pub-test.r2.dev/")
        r2_serving.generate_presigned_url.assert_not_called()
