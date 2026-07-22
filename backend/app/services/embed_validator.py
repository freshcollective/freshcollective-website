"""
Embed URL extraction and allowlist validation for pathway step/about blocks
of type `embed`.

Creators paste either a bare URL or an <iframe ...> snippet from a trusted
third-party (Calendly, Typeform, Google Forms, etc.). We extract the iframe
`src` if present, validate the hostname against a fixed allowlist, then store
the URL only. Raw HTML is never persisted — eliminating the XSS surface.

The frontend renders embeds inside a standard sandboxed <iframe>. Provider
metadata (display height/aspect ratio) is resolved at render time from the
same allowlist, mirrored in `frontend/src/lib/embedAllowlist.ts`.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


# Hostnames (or hostname suffixes) we permit for embed src URLs.
# Match is exact OR endswith ".<suffix>" — never substring, to prevent
# attacker-controlled hosts like "calendly.com.evil.tld".
EMBED_ALLOWED_HOSTS: tuple[str, ...] = (
    "youtube.com", "www.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com",
    "youtu.be",
    "vimeo.com", "player.vimeo.com",
    "wistia.com", "fast.wistia.com", "fast.wistia.net",
    "loom.com", "www.loom.com",
    "forms.gle",
    "docs.google.com",
    "typeform.com", "form.typeform.com",
    "calendly.com",
    "spotify.com", "open.spotify.com",
    "soundcloud.com", "w.soundcloud.com",
)


_IFRAME_SRC_RE = re.compile(
    r"""<iframe\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


class EmbedValidationError(ValueError):
    """Raised when an embed URL cannot be extracted or fails allowlist check."""


def extract_embed_src(raw: str) -> str:
    """
    Given either a URL or an <iframe> HTML snippet, return the embed URL.
    Trims whitespace. Does not validate the host — see validate_embed_host.
    """
    s = (raw or "").strip()
    if not s:
        raise EmbedValidationError("Embed URL is required.")

    # If it looks like iframe HTML, extract src
    if "<iframe" in s.lower():
        m = _IFRAME_SRC_RE.search(s)
        if not m:
            raise EmbedValidationError(
                "Could not find src attribute in the iframe code. "
                "Paste the full <iframe ... src=\"...\"> tag from the embed code."
            )
        s = m.group(1).strip()

    # Reject anything that isn't an absolute http(s) URL
    if not (s.startswith("http://") or s.startswith("https://")):
        raise EmbedValidationError(
            "Embed src must be an https:// URL."
        )

    return s


def validate_embed_host(url: str) -> str:
    """
    Validate that the URL's hostname is on the allowlist. Returns the URL
    unchanged. Raises EmbedValidationError on rejection.
    """
    try:
        parsed = urlparse(url)
    except ValueError as e:  # malformed
        raise EmbedValidationError(f"Invalid URL: {e}") from e

    host = (parsed.hostname or "").lower()
    if not host:
        raise EmbedValidationError("Embed URL is missing a hostname.")

    # Require https for safety (http allowed only for localhost during dev — but
    # creators don't paste localhost embeds, so reject across the board).
    if parsed.scheme != "https":
        raise EmbedValidationError("Embed URL must use https://.")

    if host not in EMBED_ALLOWED_HOSTS:
        # Also allow exact-suffix match like "subdomain.youtube.com"
        if not any(host.endswith("." + h) for h in EMBED_ALLOWED_HOSTS):
            raise EmbedValidationError(
                f"Embed host '{host}' is not on the allowlist. "
                f"Supported providers: YouTube, Vimeo, Wistia, Loom, Google Forms, "
                f"Typeform, Calendly, Spotify, SoundCloud."
            )

    return url


def extract_and_validate_embed_url(raw: str) -> str:
    """
    One-shot helper used by the API routes: extract the src (if iframe),
    then validate the host. Returns the canonical URL to store.
    """
    return validate_embed_host(extract_embed_src(raw))
