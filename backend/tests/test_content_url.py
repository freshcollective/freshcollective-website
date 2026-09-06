"""SEC-016 — unit tests for the shared content-block URL validators.

Locks in the two shapes exposed by ``app.services.content_url``:

  * ``validate_nav_url``  — https, http, mailto, or ``/``-relative.
  * ``validate_media_url`` — https, http, or ``/``-relative (no mailto).

Both reject javascript:/data:/vbscript:/blob:/file:/ftp:/protocol-
relative variants and the common case/whitespace bypasses.

Route-level integration (create + patch across PathwayStepBlock,
PathwayAboutBlock, event about, series about) lives in
``test_content_block_url_validation.py``.
"""

from __future__ import annotations

import pytest

from app.services.content_url import (
    ContentUrlError,
    validate_media_url,
    validate_nav_url,
)


# Payloads that must be rejected by both validators. Covers scheme
# variants, case tricks, and whitespace bypasses.
_HOSTILE_COMMON = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "  javascript:alert(1)  ",
    "\tjavascript:alert(1)",
    "\njavascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "DATA:text/html,foo",
    "vbscript:msgbox(\"xss\")",
    "VBScript:msgbox(\"xss\")",
    "blob:https://evil/xxx",
    "file:///etc/passwd",
    "ftp://example.com",
    "tel:+15555555555",
    # Protocol-relative — resolves to https://evil.com in the browser
    # and would smuggle a cross-origin nav past a naive startswith('/').
    "//evil.com/x",
    "  //evil.com/x",
    # http-URL without a hostname.
    "http://",
    "https://",
]


class TestValidateNavUrl:
    @pytest.mark.parametrize("safe", [
        "https://example.com",
        "http://example.com/path?x=1",
        "https://EXAMPLE.com/Path",   # case in host/path is preserved
        "/spaces/foo",
        "/",
        "  https://example.com  ",    # whitespace stripped
        "mailto:hi@example.com",
        "MailTo:hi@example.com",       # scheme case-insensitive
    ])
    def test_safe_urls_accepted(self, safe: str) -> None:
        out = validate_nav_url(safe)
        assert out == safe.strip()

    @pytest.mark.parametrize("hostile", _HOSTILE_COMMON)
    def test_hostile_schemes_rejected(self, hostile: str) -> None:
        with pytest.raises(ContentUrlError):
            validate_nav_url(hostile)

    def test_empty_rejected(self) -> None:
        with pytest.raises(ContentUrlError):
            validate_nav_url("")
        with pytest.raises(ContentUrlError):
            validate_nav_url("   ")

    def test_mailto_requires_address(self) -> None:
        with pytest.raises(ContentUrlError):
            validate_nav_url("mailto:")
        with pytest.raises(ContentUrlError):
            validate_nav_url("mailto:   ")
        with pytest.raises(ContentUrlError):
            validate_nav_url("mailto:not-an-email")


class TestValidateMediaUrl:
    @pytest.mark.parametrize("safe", [
        "https://example.com/img.jpg",
        "http://example.com/img.png",
        "/uploads/a.png",
        "  https://example.com/x.jpg  ",
    ])
    def test_safe_urls_accepted(self, safe: str) -> None:
        out = validate_media_url(safe)
        assert out == safe.strip()

    @pytest.mark.parametrize("hostile", _HOSTILE_COMMON)
    def test_hostile_schemes_rejected(self, hostile: str) -> None:
        with pytest.raises(ContentUrlError):
            validate_media_url(hostile)

    @pytest.mark.parametrize("mailto", [
        "mailto:hi@example.com",
        "MailTo:hi@example.com",
        "  mailto:hi@example.com  ",
    ])
    def test_mailto_rejected_for_media(self, mailto: str) -> None:
        # This is the split from validate_nav_url — mailto is a nav
        # scheme, not a media source, so media-URL policy must reject it.
        with pytest.raises(ContentUrlError):
            validate_media_url(mailto)

    def test_empty_rejected(self) -> None:
        with pytest.raises(ContentUrlError):
            validate_media_url("")
        with pytest.raises(ContentUrlError):
            validate_media_url("   ")
