"""HTML sanitiser for community post bodies (SEC-001).

Establishes the invariant that ``CommunityPost.body`` in the database
is always safe to render — including when the frontend uses
``dangerouslySetInnerHTML``. The sink at
``frontend/src/app/spaces/[slug]/community/[postId]/page.tsx`` and the
mirror in Creator Studio both render whatever is stored, so this
module is the *sole* authoritative security boundary. The client-side
``sanitizeHtml`` in ``CommunityManager.tsx`` is a UX helper that runs
before submission; it is not a security control (trivially bypassed
by any direct HTTP call to the API).

Allowlist matches what the creator composer actually produces:

    <b> <strong> <i> <em> <u> <a> <br> <p> <div> <span>

with ``<a>`` limited to ``http``/``https`` URLs. ``nh3`` (Ammonia)
always sets ``rel="noopener noreferrer"`` on links, so ``rel`` is
managed by the sanitiser rather than allowlisted through — hence
``rel`` is deliberately absent from ``ALLOWED_ATTRIBUTES['a']``.
"""

from __future__ import annotations

import nh3

# Tags the creator composer emits and the render surfaces can display.
_ALLOWED_TAGS: frozenset[str] = frozenset(
    {"b", "strong", "i", "em", "u", "a", "br", "p", "div", "span"}
)

# ``rel`` is intentionally omitted — nh3 owns it via ``link_rel`` below.
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "target"}}

# Only real navigable web URLs. Blocks ``javascript:``, ``data:``,
# ``vbscript:``, and any other scheme by default.
_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# nh3 will append this ``rel`` to every ``<a>`` it emits.
_LINK_REL: str = "noopener noreferrer"


def sanitize_post_body(html: str) -> str:
    """Return a sanitised copy of a community post body.

    Idempotent — sanitising an already-sanitised string is a no-op.
    Preserves plain text and the allowed rich-text subset unchanged;
    strips every other tag, attribute, and URL scheme.
    """
    if not html:
        return html
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        link_rel=_LINK_REL,
    )
