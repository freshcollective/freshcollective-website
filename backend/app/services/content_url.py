"""SEC-016 — shared URL validation for content-block sinks.

Two policies, chosen to match the actual browser sink shape:

  * ``validate_nav_url``  — https, http, mailto, or ``/``-relative.
    For any block whose ``embed_url`` reaches a clickable
    ``<a href>`` navigation sink. That includes the ``link`` block,
    the ``video_embed`` fallback anchor (rendered when the URL is
    not a recognised embed provider), and — via
    ``button_validator.validate_button_url`` — the ``button`` block.

  * ``validate_media_url`` — https, http, or ``/``-relative. For
    any block whose ``embed_url`` reaches a media sink
    (``<img src>`` today; ``<audio>``/``<video>`` in future).
    ``mailto:`` is not a media source and is deliberately excluded
    even though nav-shaped sinks accept it.

Both policies explicitly reject javascript:, data:, vbscript:,
blob:, file:, ftp:, protocol-relative URLs (``//host``), and the
common case/whitespace variants that can bypass a naive prefix
check.

Actual embed iframes (``embed`` block type) keep going through
``services.embed_validator.extract_and_validate_embed_url`` — that
policy is stricter (provider allowlist + iframe-src extraction)
and this module deliberately does not replace it.

Rationale for the split: buttons and inline links have a legitimate
use for ``mailto:``; media (image/audio/video) sources do not, and
allowing it there would only widen the exploit surface without
enabling any real Fresh Collective feature.
"""

from __future__ import annotations

from urllib.parse import urlparse


class ContentUrlError(ValueError):
    """Raised when a content-block URL fails validation."""


def _validate_core(raw: str, *, allow_mailto: bool) -> str:
    s = (raw or "").strip()
    if not s:
        raise ContentUrlError("URL is required.")

    # Internal app paths. Reject protocol-relative URLs (``//host``)
    # which resolve to https://host in a browser and would smuggle an
    # external navigation past a naive ``startswith('/')`` check.
    if s.startswith("/"):
        if s.startswith("//"):
            raise ContentUrlError("Protocol-relative URLs are not allowed.")
        return s

    lower = s.lower()

    # Mailto — only when the sink is a navigation link.
    if lower.startswith("mailto:"):
        if not allow_mailto:
            raise ContentUrlError(
                "mailto: URLs are not valid for media/image sources."
            )
        addr = s[len("mailto:"):].strip()
        if not addr or "@" not in addr:
            raise ContentUrlError(
                "mailto: link must include an email address."
            )
        return s

    # http(s) only — everything else (javascript:, data:, vbscript:,
    # blob:, file:, ftp:, tel:, …) falls through to this rejection.
    if not (lower.startswith("http://") or lower.startswith("https://")):
        allowed = (
            "https://, http://, mailto:, or / for internal links"
            if allow_mailto
            else "https://, http://, or / for internal links"
        )
        raise ContentUrlError(f"URL must start with {allowed}.")

    try:
        parsed = urlparse(s)
    except ValueError as e:
        raise ContentUrlError(f"Invalid URL: {e}") from e

    if not parsed.hostname:
        raise ContentUrlError("URL is missing a hostname.")

    return s


def validate_nav_url(raw: str) -> str:
    """SEC-016 — navigation-link URL. Accepts https, http, mailto,
    or ``/``-relative. Everything else (javascript:, data:, blob:,
    file:, ftp:, vbscript:, protocol-relative, case/whitespace
    variants) is rejected."""
    return _validate_core(raw, allow_mailto=True)


def validate_media_url(raw: str) -> str:
    """SEC-016 — media-source URL. Accepts https, http, or
    ``/``-relative. ``mailto:`` and every other scheme are rejected."""
    return _validate_core(raw, allow_mailto=False)
