"""A Guide's body: safe to store, and safe to render.

A sibling of ``rich_text.py`` rather than a widening of it, and the
distinction matters. That module's allowlist is shared with every
Gathering and Gathering Series description a creator writes; adding
``img`` and ``blockquote`` there would hand inline images to every
creator-authored description on the platform as a side effect of
building a blog. Guides are written by platform admins only, so they
get a wider vocabulary and their own boundary.

Everything else is deliberately identical to ``rich_text.py``, because
the URL and ``rel`` rules should be decided once and learned once:
``http``/``https`` only, ``rel`` owned by nh3 rather than allowlisted
through, idempotent, and a value containing no markup returned byte
for byte so "tea & biscuits" is never rewritten to "tea &amp;
biscuits" on an untouched save.

The allowlist matches ``frontend/src/components/guides/GuideBody.tsx``
exactly, and a test asserts it. The asymmetry is what makes that worth
enforcing: a tag the sanitiser keeps and the renderer drops disappears
at display time, which reads to the author as lost work; a tag the
renderer handles and the sanitiser strips disappears at save time,
which is worse because the author watched it happen.

Images are constrained by origin, not only by scheme
---------------------------------------------------
An ``<img>`` pointing anywhere other than Fresh Collective's own media
hosts is already refused by the enforcing CSP's ``img-src``, so a
pasted external image would save cleanly and then render as a broken
box behind a console error nobody has open. Rather than leave that to
be discovered, :func:`sanitize_guide_body` drops the tag here and the
admin editor says so. The permitted shapes are the ones the platform
actually serves: a same-origin ``/api/uploads/…`` path — which is what
``save_media_file`` returns, and so what every uploaded Guide image
is — and the Cloudflare R2 hosts, for a body that names one directly.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import nh3

from app.core.config import settings

#: Exactly what ``GuideBody.tsx`` renders. Block tags, then inline.
#:
#: ``figure``/``figcaption`` are absent: the editor's image node emits
#: a bare ``<img>`` and the renderer supplies its own wrapper, so
#: allowing them would permit markup nothing produces and the renderer
#: would have to grow a branch for it.
ALLOWED_TAGS: frozenset[str] = frozenset({
    "p", "br",
    "h2", "h3",
    "ul", "ol", "li",
    "strong", "b", "em", "i",
    "a",
    "blockquote",
    "img",
})

#: ``rel`` is deliberately absent — nh3 owns it via ``link_rel``.
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "target"},
    "img": {"src", "alt"},
}

URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

LINK_REL = "noopener noreferrer"

#: Hosts whose images the CSP permits. Suffix-matched, mirroring
#: ``img-src https://*.r2.dev`` rather than reimplementing CSP's
#: matching rules in general.
#:
#: In practice almost every Guide image is the first case below, not
#: these: ``save_media_file`` returns a same-origin
#: ``/api/uploads/media/guides/…`` path and the redirect to R2 happens
#: server-side. These are here for a body that names an R2 URL
#: directly, which the public-bucket configuration can produce.
_R2_HOST_SUFFIXES: tuple[str, ...] = (".r2.cloudflarestorage.com", ".r2.dev")

#: Anything that looks like a tag — a letter after the ``<``, so
#: "3 < 5" and "<3 you all" are prose rather than markup.
_TAGLIKE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")

_IMG_TAG = re.compile(r"<img\b[^>]*>", flags=re.IGNORECASE)
_IMG_SRC = re.compile(r"""\bsrc\s*=\s*["']([^"']*)["']""", flags=re.IGNORECASE)


def _r2_public_host() -> str | None:
    """The configured R2 public base URL's host, if there is one.

    Read from settings rather than written down because the bucket's
    public URL changes when a custom media domain is connected, and a
    hardcoded host would start silently dropping images on the day
    that happens.
    """
    raw = (getattr(settings, "r2_public_base_url", None) or "").strip()
    if not raw:
        return None
    try:
        return urlparse(raw).hostname
    except ValueError:
        return None


def is_permitted_image_src(src: str) -> bool:
    """May the browser actually load this image?

    Answers the CSP's question, not a general safety question — an
    off-origin image is not dangerous, it simply will not appear, and
    an author is better served by being told at save time than by a
    blank space on a published page.
    """
    value = (src or "").strip()
    if not value:
        return False
    # A same-origin upload path. Not any relative URL: ``//evil.test/x``
    # is protocol-relative and would leave the origin entirely.
    if value.startswith("/") and not value.startswith("//"):
        return value.startswith("/api/uploads/")
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme not in URL_SCHEMES or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if any(host.endswith(suffix) for suffix in _R2_HOST_SUFFIXES):
        return True
    r2_host = _r2_public_host()
    return r2_host is not None and host == r2_host.lower()


def _drop_unservable_images(html: str) -> str:
    """Remove every ``<img>`` the CSP would refuse to load."""
    def replace(match: re.Match[str]) -> str:
        src_match = _IMG_SRC.search(match.group(0))
        src = src_match.group(1) if src_match else ""
        return match.group(0) if is_permitted_image_src(src) else ""

    return _IMG_TAG.sub(replace, html)


def sanitize_guide_body(value: str | None) -> str | None:
    """A Guide body safe to store and to render.

    Idempotent, so a round trip through the editor does not erode
    content. ``None`` and the empty string pass through unchanged.
    """
    if not value:
        return value
    if not _TAGLIKE.search(value):
        return value
    cleaned = nh3.clean(
        value,
        tags=set(ALLOWED_TAGS),
        attributes={k: set(v) for k, v in ALLOWED_ATTRIBUTES.items()},
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
    )
    # After nh3, not before: nh3 resolves entities and normalises
    # attribute quoting, so matching ``src`` on its output is matching
    # one shape rather than every shape an author could have typed.
    return _drop_unservable_images(cleaned)


def has_unservable_image(value: str | None) -> bool:
    """Did sanitising drop an image? Used to tell the author why."""
    if not value or not _TAGLIKE.search(value):
        return False
    for match in _IMG_TAG.finditer(value):
        src_match = _IMG_SRC.search(match.group(0))
        if not is_permitted_image_src(src_match.group(1) if src_match else ""):
            return True
    return False


__all__ = [
    "ALLOWED_ATTRIBUTES",
    "ALLOWED_TAGS",
    "LINK_REL",
    "URL_SCHEMES",
    "has_unservable_image",
    "is_permitted_image_src",
    "sanitize_guide_body",
]
