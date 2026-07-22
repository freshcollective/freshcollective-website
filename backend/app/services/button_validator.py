"""
URL validation for `button` content blocks.

Rules:
  • https://, http://, mailto: are accepted as-is (after the host/local-part
    is non-empty).
  • Bare paths starting with "/" are accepted (internal app links).
  • Everything else is rejected — particularly javascript:, data:, vbscript:,
    blob:, file:, ftp:, and protocol-relative URLs.

The button block uses existing columns:
    label     — button text
    embed_url — destination URL (validated by this module)
    caption   — one of:
                  * a legacy style name (primary | secondary | outline | subtle)
                  * a JSON envelope combining the writer's chosen Filled /
                    Outline / Text style with a palette-linked role or an
                    explicit hex override:
                        {"style":"filled","colour":"palette:primary"}
                        {"style":"outline","colour":"custom:#3A6B7A"}
    content   — open-in-new-tab marker ("new_tab" | "same_tab" | None)
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse


VALID_BUTTON_STYLES: frozenset[str] = frozenset(
    {"primary", "secondary", "outline", "subtle"}
)

# Modern styles kept in the JSON envelope. Independent of the legacy
# style names so writers can choose Filled/Outline/Text without
# implicitly picking a colour.
VALID_BUTTON_NEW_STYLES: frozenset[str] = frozenset(
    {"filled", "outline", "text"}
)

# Colour roles that resolve against the collective's active palette.
# Must mirror ``PALETTE_ROLES`` in ``frontend/src/lib/collectivePalette.ts``.
VALID_PALETTE_ROLES: frozenset[str] = frozenset(
    {"primary", "secondary", "accent", "background"}
)

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$")

VALID_NEW_TAB_VALUES: frozenset[str] = frozenset({"new_tab", "same_tab"})


class ButtonValidationError(ValueError):
    """Raised when a button block's URL/style fails validation."""


def validate_button_url(raw: str) -> str:
    """
    Validate a button destination URL. Returns the trimmed URL on success.
    Raises ButtonValidationError otherwise.
    """
    s = (raw or "").strip()
    if not s:
        raise ButtonValidationError("Button URL is required.")

    # Internal app paths
    if s.startswith("/"):
        # Reject protocol-relative URLs like "//evil.com" — these resolve to
        # https://evil.com in a browser.
        if s.startswith("//"):
            raise ButtonValidationError("Protocol-relative URLs are not allowed.")
        return s

    # Mailto links
    if s.lower().startswith("mailto:"):
        addr = s[len("mailto:"):].strip()
        if not addr or "@" not in addr:
            raise ButtonValidationError("mailto: link must include an email address.")
        return s

    # http(s) URLs
    lower = s.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        raise ButtonValidationError(
            "URL must start with https://, http://, mailto:, or / for internal links."
        )

    try:
        parsed = urlparse(s)
    except ValueError as e:
        raise ButtonValidationError(f"Invalid URL: {e}") from e

    if not parsed.hostname:
        raise ButtonValidationError("URL is missing a hostname.")

    return s


def validate_button_text(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s:
        raise ButtonValidationError("Button text is required.")
    if len(s) > 80:
        raise ButtonValidationError("Button text must be 80 characters or fewer.")
    return s


def _validate_button_colour_token(colour: str) -> str:
    """Colour tokens must be either ``palette:<role>`` or ``custom:#hex``.
    Legacy fixed keys are rejected here (they never appear in the JSON
    envelope). Whitespace is stripped; the resolved token is returned.
    """
    s = colour.strip()
    if s.startswith("palette:"):
        role = s.split(":", 1)[1].strip().lower()
        if role not in VALID_PALETTE_ROLES:
            raise ButtonValidationError(
                f"Button palette role must be one of: {', '.join(sorted(VALID_PALETTE_ROLES))}."
            )
        return f"palette:{role}"
    if s.startswith("custom:"):
        hex_val = s.split(":", 1)[1].strip()
        if not _HEX_RE.match(hex_val):
            raise ButtonValidationError(
                "Custom button colour must be a hex value like #3A6B7A."
            )
        return f"custom:{hex_val}"
    raise ButtonValidationError(
        "Button colour must be a palette role (palette:primary) or a custom hex (custom:#3A6B7A)."
    )


def normalise_button_style(raw: str | None) -> str:
    """
    Accept and normalise a button block's ``caption`` value.

    Three shapes are permitted:

      1. Legacy style name (``primary`` | ``secondary`` | ``outline`` |
         ``subtle``) — kept for backward compatibility with pre-palette
         buttons. Returned as-is (lowercased, trimmed).
      2. Modern JSON envelope ``{"style": "...", "colour": "..."}`` —
         re-serialised with only the whitelisted fields so we never
         persist a caption we can't render.
      3. Empty / null — falls back to ``primary`` for safety.
    """
    if raw is None:
        return "primary"
    s = raw.strip()
    if not s:
        return "primary"
    # Modern JSON envelope: parse, validate, re-serialise.
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, ValueError) as e:
            raise ButtonValidationError(
                "Button caption JSON is malformed."
            ) from e
        if not isinstance(data, dict):
            raise ButtonValidationError("Button caption JSON must be an object.")
        style = str(data.get("style", "")).strip().lower()
        colour = str(data.get("colour", "")).strip()
        if style not in VALID_BUTTON_NEW_STYLES:
            raise ButtonValidationError(
                f"Button style must be one of: {', '.join(sorted(VALID_BUTTON_NEW_STYLES))}."
            )
        colour_norm = _validate_button_colour_token(colour)
        # Re-serialise in a canonical key order so equality checks in
        # tests are deterministic and we never persist stray fields.
        return json.dumps({"style": style, "colour": colour_norm}, separators=(",", ":"))
    # Legacy style name.
    legacy = s.lower()
    if legacy not in VALID_BUTTON_STYLES:
        raise ButtonValidationError(
            f"Button style must be one of: {', '.join(sorted(VALID_BUTTON_STYLES))}, "
            f"or a JSON envelope {{\"style\":..., \"colour\":...}}."
        )
    return legacy


def normalise_new_tab(raw: str | None) -> str | None:
    """
    Returns "new_tab", "same_tab", or None (defer to UI default).
    Empty / unknown values normalise to None.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if s in VALID_NEW_TAB_VALUES:
        return s
    return None
