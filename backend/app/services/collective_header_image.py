"""Which image welcomes people into a Collective. One rule, one place.

A Collective has two visual identities and they are not rivals: the
creator's own brand — name, logo, banner, description — and the
Collective's home in the Fresh Collective world, its Atlas Location.
Phase 1 lets the creator say which of the two leads.

Why this exists as a module
---------------------------
It was decided independently in nine components. Every one of them read
Location artwork first and the uploaded banner last, each with its own
slightly different fallback chain — thumbnail-then-hero here,
hero-then-thumbnail there — so "which image does this Collective show"
had no single answer and a creator's banner appeared nowhere. One rule,
asked by every surface that shows the primary Collective image.

The rule
--------
    preference is 'banner' AND a banner exists  →  the banner
    otherwise                                   →  Location hero,
                                                   then Location
                                                   thumbnail, then the
                                                   banner, then nothing

The second line is the behaviour every surface had before this, kept
exactly: a Collective that has not chosen looks exactly as it looked.

The fallback is deliberately *safe in one direction only*. A creator who
chose their banner and whose banner has gone — a storage failure, a
file deleted out from under the row — sees their Location artwork
rather than a broken image. The stored preference is **not** changed by
that: the display falls back, the choice does not. When the image comes
back, so does their banner, without anybody having to re-select it.

What this does not touch
------------------------
World Artwork. ``island_artwork_*`` is not read here, and neither is
any Atlas editing path. Location artwork is *read* for display and
never written; it remains curated exclusively through Atlas Locations.

Surfaces that are about the Location rather than the Collective — the
island card on the About page, Discover Places, the Atlas admin — do
not call this. They show Location artwork because that is their
subject, which is the distinction Phase 1 is built on.
"""

from __future__ import annotations

from typing import Any

#: Stored values of ``Space.header_image_preference``.
PREFER_LOCATION = "location"
PREFER_BANNER = "banner"

PREFERENCES = (PREFER_LOCATION, PREFER_BANNER)

#: What a Collective that has never chosen gets, and what a row with an
#: unrecognised value is read as. Unknown reads as the default rather
#: than as the banner, so a bad value can never change how a
#: Collective looks.
DEFAULT_PREFERENCE = PREFER_LOCATION


def normalise_preference(value: str | None) -> str:
    """A stored value, read safely.

    Exact match only — no trimming or case folding. The column is
    written exclusively by our own code with one of two literals, so
    anything else is a value nobody intended, and the frontend mirror
    does a strict comparison too. Being forgiving here would mean
    ``"BANNER"`` changed a Collective's appearance on one side and not
    the other.
    """
    return value if value in PREFERENCES else DEFAULT_PREFERENCE


def _clean(value: Any) -> str | None:
    text = (value or "").strip() if isinstance(value, str) else None
    return text or None


def collective_header_image(
    *,
    preference: str | None,
    banner_url: str | None,
    location_hero_url: str | None = None,
    location_thumbnail_url: str | None = None,
) -> str | None:
    """The image a primary Collective surface should show, or ``None``.

    Pure, so the rule is testable without a Collective, and so the
    frontend's mirror in ``lib/collectiveHeaderImage.ts`` can be held
    against it.
    """
    banner = _clean(banner_url)
    hero = _clean(location_hero_url)
    thumbnail = _clean(location_thumbnail_url)

    if normalise_preference(preference) == PREFER_BANNER and banner:
        return banner
    # The chain every surface used before this existed.
    return hero or thumbnail or banner


def header_image_for_space(space: Any, location: Any = None) -> str | None:
    """:func:`collective_header_image` for a ``Space`` row.

    ``location`` is passed in rather than walked to, because the Space
    model has no relationship to its Atlas Location — the callers that
    have one already hydrated hand it over.
    """
    return collective_header_image(
        preference=getattr(space, "header_image_preference", None),
        banner_url=getattr(space, "cover_image_url", None),
        location_hero_url=getattr(location, "hero_artwork_url", None),
        location_thumbnail_url=getattr(location, "thumbnail_artwork_url", None),
    )


def preference_after_upload() -> str:
    """What uploading a banner means.

    A creator who has just chosen an image for their Collective wants
    to see it — asking them to upload and *then* select would be a
    second step for a decision they have already made. Switching back
    is one press away and keeps the file.
    """
    return PREFER_BANNER


def preference_after_removal() -> str:
    """What removing the banner means. There is nothing else to show."""
    return PREFER_LOCATION


__all__ = [
    "DEFAULT_PREFERENCE",
    "PREFERENCES",
    "PREFER_BANNER",
    "PREFER_LOCATION",
    "collective_header_image",
    "header_image_for_space",
    "normalise_preference",
    "preference_after_removal",
    "preference_after_upload",
]
