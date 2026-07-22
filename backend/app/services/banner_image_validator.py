"""
Light validation for the optional banner_image_url field used by pathway
sections and pathway steps.

Accepted shapes:
  • Absolute https:// URL (external image hosts, CDN)
  • Relative path beginning with "/" (Media Library returns paths like
    "/api/uploads/<file>.jpg")
  • None — to clear the banner

Rejected:
  • javascript:, data:, vbscript:, file:, ftp: schemes
  • http:// (non-secure)
  • Protocol-relative URLs ("//evil.com")
  • Anything else
"""

from __future__ import annotations


class BannerImageValidationError(ValueError):
    pass


def validate_banner_image_url(raw: str | None) -> str | None:
    """
    Normalise/validate a banner URL. Returns the trimmed URL, or None if
    the value was None / empty (which clears the banner). Raises
    BannerImageValidationError on rejection.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None  # treat empty string as "clear"

    if s.startswith("//"):
        raise BannerImageValidationError("Protocol-relative URLs are not allowed.")
    if s.startswith("/"):
        return s  # internal upload path

    lower = s.lower()
    if lower.startswith("https://"):
        return s

    raise BannerImageValidationError(
        "Banner image URL must be an https:// URL or a Media Library path."
    )
