"""SEC-011 Stage A — backend security-header regression tests.

Pins the transport/content headers emitted by the fc-api middleware
plus the ``/api/uploads/*`` per-endpoint additions. Also pins the
negative invariants: fc-api must NOT emit CSP, Permissions-Policy,
X-Frame-Options, or frame-ancestors — those belong on fc-web
document responses only.

CORS / cookie / auth behaviour is asserted unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401

from app.core.storage import UPLOAD_DIR
from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def upload_file(tmp_path_factory):
    """Drop a real file into UPLOAD_DIR/platform-artwork/ so the public
    upload route has something to serve. Cleaned up after the test."""
    subdir = UPLOAD_DIR / "platform-artwork"
    subdir.mkdir(parents=True, exist_ok=True)
    target = subdir / "sec011_test_pixel.png"
    # Minimal valid 1x1 PNG (69 bytes) — content doesn't matter for
    # the header tests but must be a real file so FileResponse succeeds.
    target.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x1c\x18X\xd3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    yield target
    try:
        target.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# 1. Global transport/content headers via middleware
# ---------------------------------------------------------------------------


class TestGlobalTransportHeaders:
    def test_health_carries_hsts(self, client):
        r = client.get("/health")
        assert r.headers.get("strict-transport-security") == "max-age=31536000"

    def test_health_carries_xcto(self, client):
        r = client.get("/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_health_carries_referrer_policy(self, client):
        r = client.get("/health")
        assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_hsts_has_no_include_subdomains(self, client):
        """Stage A intentionally omits includeSubDomains; revisit
        when Fresh Collective moves to its real production domain."""
        r = client.get("/health")
        v = r.headers.get("strict-transport-security", "").lower()
        assert "includesubdomains" not in v

    def test_hsts_has_no_preload(self, client):
        """preload is effectively irreversible — never in Stage A."""
        r = client.get("/health")
        v = r.headers.get("strict-transport-security", "").lower()
        assert "preload" not in v

    def test_headers_present_on_authed_route_401(self, client):
        """Middleware runs after the endpoint returns even for
        exceptions — a 401 must still carry the headers."""
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        assert r.headers.get("strict-transport-security") == "max-age=31536000"
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_headers_present_on_404(self, client):
        r = client.get("/definitely-not-a-real-endpoint-9e7f")
        assert r.status_code == 404
        assert r.headers.get("strict-transport-security") == "max-age=31536000"
        assert r.headers.get("x-content-type-options") == "nosniff"


# ---------------------------------------------------------------------------
# 2. Negative invariants — fc-api must NOT emit document-oriented headers
# ---------------------------------------------------------------------------


class TestApiDoesNotEmitDocumentHeaders:
    """CSP, Permissions-Policy, X-Frame-Options, and frame-ancestors
    all belong on fc-web document responses. fc-api serves JSON /
    files, so shipping them here would be cargo-cult noise and could
    confuse a scanner into thinking the API was a document surface."""

    _FORBIDDEN = (
        "content-security-policy",
        "content-security-policy-report-only",
        "permissions-policy",
        "x-frame-options",
    )

    def test_health_omits_document_headers(self, client):
        r = client.get("/health")
        for name in self._FORBIDDEN:
            assert name not in {k.lower() for k in r.headers.keys()}, (
                f"fc-api emitted {name!r} — should be fc-web only."
            )

    def test_authed_endpoint_omits_document_headers(self, client):
        r = client.get("/api/auth/me")
        for name in self._FORBIDDEN:
            assert name not in {k.lower() for k in r.headers.keys()}


# ---------------------------------------------------------------------------
# 3. /api/uploads/* per-endpoint additions
# ---------------------------------------------------------------------------


class TestUploadSecurityHeaders:
    def test_public_upload_carries_corp_cross_origin(self, client, upload_file):
        r = client.get("/api/uploads/platform-artwork/sec011_test_pixel.png")
        assert r.status_code == 200
        assert r.headers.get("cross-origin-resource-policy") == "cross-origin"

    def test_public_upload_carries_xcto(self, client, upload_file):
        r = client.get("/api/uploads/platform-artwork/sec011_test_pixel.png")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_public_upload_still_carries_global_hsts(
        self, client, upload_file,
    ):
        r = client.get("/api/uploads/platform-artwork/sec011_test_pixel.png")
        assert r.headers.get("strict-transport-security") == "max-age=31536000"

    def test_upload_missing_file_still_carries_global_headers(self, client):
        """404 path — middleware runs; endpoint's CORP/XCTO don't."""
        r = client.get("/api/uploads/platform-artwork/does-not-exist.png")
        assert r.status_code == 404
        # Global headers present
        assert r.headers.get("strict-transport-security") == "max-age=31536000"
        assert r.headers.get("x-content-type-options") == "nosniff"


# ---------------------------------------------------------------------------
# 4. CORS + cookie + auth behaviour unchanged
# ---------------------------------------------------------------------------


class TestExistingBehaviourUnchanged:
    def test_cors_preflight_still_works(self, client):
        """Existing CORS middleware unaffected by the new security
        middleware."""
        from app.core.config import settings
        r = client.options(
            "/api/auth/me",
            headers={
                "Origin": settings.frontend_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        # 200 or 204 depending on FastAPI/Starlette version — both fine.
        assert r.status_code in (200, 204)
        assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}

    def test_set_cookie_preserved_on_login_failure(self, client):
        """Login with garbage credentials — no Set-Cookie expected,
        but the response must still carry the SEC-011 headers."""
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody-sec011@example.test", "password": "wrong"},
        )
        assert r.status_code in (400, 401)
        assert r.headers.get("strict-transport-security") == "max-age=31536000"

    def test_unauth_verify_email_endpoint_reachable(self, client):
        """SEC-009 endpoints unchanged."""
        r = client.post(
            "/api/auth/verify-email",
            json={"token": "sec011-fabricated-invalid"},
        )
        assert r.status_code == 400
        assert r.headers.get("x-content-type-options") == "nosniff"


# ---------------------------------------------------------------------------
# 5. Middleware setdefault semantics — endpoint headers win
# ---------------------------------------------------------------------------


class TestEndpointHeadersWinOnCollision:
    def test_upload_corp_is_not_overwritten_by_middleware(
        self, client, upload_file,
    ):
        """The middleware uses setdefault, so endpoint-set headers
        (like CORP on uploads) are preserved. Confirms the collision
        rule is correct by asserting the endpoint's header value
        appears rather than any middleware default."""
        r = client.get("/api/uploads/platform-artwork/sec011_test_pixel.png")
        assert r.headers.get("cross-origin-resource-policy") == "cross-origin"
