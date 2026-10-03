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
    "neutrinoplatform.com",
)


# Provider display names, in the order a creator meets them in the
# helper text. Kept beside the host tuple because the rejection message
# used to be a hand-written string literal and nothing stopped it
# drifting from what was actually allowed.
EMBED_PROVIDER_NAMES: tuple[str, ...] = (
    "YouTube",
    "Vimeo",
    "Wistia",
    "Loom",
    "Google Forms",
    "Typeform",
    "Calendly",
    "Spotify",
    "SoundCloud",
    "Neutrino Human Design",
)


# Hosts whose embeds live at one known path, keyed by the allowlist
# entry that matched. A host absent from this map is unrestricted, as
# every provider was before Neutrino.
#
# Neutrino serves other things from the same domain — the marketing
# site, the app, ``loader.js`` — and only ``/widget-v2/iframe`` is the
# embeddable widget. Pinning the path means a creator cannot
# accidentally (or deliberately) frame the rest of the platform through
# a block that exists to show a chart.
#
# Matched **exactly**, not as a prefix. There is no evidence Neutrino
# serves anything beneath the widget path, and an unused permission is
# one an attacker gets for free: a prefix rule would admit every future
# ``/widget-v2/iframe/<anything>`` route sight unseen. If Neutrino does
# add a sub-route, this is one tuple entry.
#
# The query string is deliberately untouched: the widget carries
# ``type``, ``key`` and ``hideBrand`` and is useless without them.
EMBED_ALLOWED_PATHS: dict[str, tuple[str, ...]] = {
    "neutrinoplatform.com": ("/widget-v2/iframe",),
}


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


def _matched_allowed_host(host: str) -> str | None:
    """The allowlist entry ``host`` satisfies, or ``None``.

    Exact match first, then an exact-suffix match like
    ``subdomain.youtube.com``. Never a substring, so
    ``calendly.com.evil.tld`` matches nothing. Returning the entry
    rather than a bool lets the caller look up per-host policy.
    """
    if host in EMBED_ALLOWED_HOSTS:
        return host
    for allowed in EMBED_ALLOWED_HOSTS:
        if host.endswith("." + allowed):
            return allowed
    return None


def _path_is_allowed(path: str, allowed: tuple[str, ...]) -> bool:
    """``path`` is exactly one of ``allowed``.

    Not a prefix test. ``/widget-v2/iframe`` permits itself and nothing
    else — neither ``/widget-v2/iframexyz`` (which a bare
    ``startswith`` would admit) nor ``/widget-v2/iframe/v3`` (which a
    segment-prefix test would).

    One tolerance: a single trailing slash is the same resource, and
    rejecting a URL that works in the browser would be a confusing
    refusal rather than a safer one. It cannot reach a different path.
    """
    candidate = path or "/"
    if candidate != "/" and candidate.endswith("/"):
        candidate = candidate.rstrip("/")
    return candidate in allowed


def validate_embed_host(url: str) -> str:
    """
    Validate that the URL's hostname is on the allowlist, and that its
    path is permitted for hosts that restrict one. Returns the URL
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

    matched = _matched_allowed_host(host)
    if matched is None:
        raise EmbedValidationError(
            f"Embed host '{host}' is not on the allowlist. "
            f"Supported providers: {', '.join(EMBED_PROVIDER_NAMES)}."
        )

    allowed_paths = EMBED_ALLOWED_PATHS.get(matched)
    if allowed_paths is not None and not _path_is_allowed(parsed.path, allowed_paths):
        shown = parsed.path or "/"
        raise EmbedValidationError(
            f"Embed path '{shown}' is not supported for {matched}. "
            f"Expected exactly: {', '.join(allowed_paths)}."
        )

    return url


def extract_and_validate_embed_url(raw: str) -> str:
    """
    One-shot helper used by the API routes: extract the src (if iframe),
    then validate the host. Returns the canonical URL to store.
    """
    return validate_embed_host(extract_embed_src(raw))
