"""The five shared Offering cover categories, and how one resolves to an image.

A creator choosing "Audio & meditations" is choosing a **category**. The
image that category currently shows is managed by an administrator in
World Settings → World Artwork, alongside the dashboard tiles, the
homepage scenes and the member cards — one artwork manager, one storage
bucket, one set of permissions.

What changed, and why
---------------------

B6 shipped these as five pairs of files committed to the repository and
installed into R2 by a script of their own (now deleted), with the
Offering storing the chosen image's **URL**. That is now retired in
favour of World Artwork, because the two systems were doing the same job
and only one of them was the platform's established one.

The consequence worth naming: World Artwork stores an upload under a
generated filename, so **replacing a shared default changes its URL**.
An Offering holding that URL would be left pointing at a deleted object.
So an Offering stores ``default_cover_key`` — the category — and the URL
is resolved at read time. Replace the artwork and every Offering using
that category follows, with nothing to backfill.

Three layers, in precedence order
---------------------------------

1. **The creator's own cover.** ``offerings.cover_image_url``, uploaded
   to the private ``offering-covers/`` namespace and gated by
   ``uploads.authorization._authorise_offering_cover``. Wins when set.
2. **The shared category artwork.** ``offerings.default_cover_key`` →
   ``platform_artwork`` → a public ``platform-artwork/`` URL.
3. **Nothing.** ``None``, which every surface renders as a deliberate
   gradient rather than a broken image.

Layer 3 is a real state, not an error: an administrator may not have
uploaded a category's artwork yet, and a creator must not be blocked
on that. See ``resolve_cover_url``.

The committed assets
--------------------

``app/assets/offering-covers/`` still holds the ten optimised WebP
files. They are **source artwork** now rather than a delivery mechanism
— an administrator uploads the hero through World Artwork, which
generates its own thumbnail. ``scripts/build_offering_covers.py``
prepares a correctly sized hero from an approved original;
``asset_paths`` and ``missing_assets`` exist for it and for the tests
that check the files are present.

Only the five heroes are needed for upload. The five ``-thumb`` files
are kept because they are approved artwork and cost 160 KB, not because
anything reads them: ``storage.save_image_with_thumbnail`` derives a
600px thumbnail from whatever is uploaded, which is the same width the
committed thumbnails use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.offering import Offering

#: Where the optimised source files live in the repository. Read by
#: ``scripts/build_offering_covers.py`` and by the tests that assert the
#: approved artwork is present. Nothing at runtime reads these.
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "offering-covers"

#: Prefix of every World Artwork key belonging to an Offering category.
#: Chosen so the five slots sort together in the manager and are
#: recognisable in the ``platform_artwork`` table at a glance.
ARTWORK_KEY_PREFIX = "offering_cover_"


@dataclass(frozen=True)
class OfferingCover:
    """One shared cover category.

    ``key`` is stable and is what ``offerings.default_cover_key`` stores;
    ``label`` is what a creator reads. The two are separate so the
    wording can be improved without invalidating stored rows — which is
    now load-bearing rather than hypothetical, because the key is a
    foreign reference rather than a display string.
    """

    key: str
    label: str
    #: One line telling a creator what this category suits. Shown under
    #: the thumbnail in the picker.
    description: str
    #: Basename of the committed source artwork, without extension.
    #: ``<file>.webp`` is the hero an administrator uploads.
    file: str

    @property
    def artwork_key(self) -> str:
        """The World Artwork slot that supplies this category's image.

        Derived rather than stored: a second field could disagree with
        the key, and this guarantees the manager's slot and the
        Offering's stored category can never drift apart.
        """
        return f"{ARTWORK_KEY_PREFIX}{self.key.replace('-', '_')}"


#: The approved five, in picker order. Labels describe what a creator is
#: *selling*, not what the photograph contains — a creator looking for
#: somewhere to put a meditation recording should find "Audio &
#: meditations", not "headphones on a window seat".
DEFAULT_COVERS: tuple[OfferingCover, ...] = (
    OfferingCover(
        key="workbook-guides",
        label="Workbooks & guides",
        description="Printable workbooks, guides and written practices.",
        file="workbook-guides",
    ),
    OfferingCover(
        key="audio",
        label="Audio & meditations",
        description="Recorded practices, meditations and audio courses.",
        file="audio",
    ),
    OfferingCover(
        key="spreadsheet",
        label="Spreadsheets & trackers",
        description="Planners, trackers and templates people fill in.",
        file="spreadsheet",
    ),
    OfferingCover(
        key="collections",
        label="Collections & bundles",
        description="Several resources gathered into one Offering.",
        file="collections",
    ),
    OfferingCover(
        key="other-resources",
        label="Other digital resources",
        description="Anything else a member downloads and keeps.",
        file="other-resources",
    ),
)

#: Keyed lookups. ``COVERS_BY_KEY`` is the validation gate for
#: ``offerings.default_cover_key``; ``COVERS_BY_ARTWORK_KEY`` is the
#: reverse, for mapping a World Artwork slot back to its category.
COVERS_BY_KEY: dict[str, OfferingCover] = {c.key: c for c in DEFAULT_COVERS}
COVERS_BY_ARTWORK_KEY: dict[str, OfferingCover] = {
    c.artwork_key: c for c in DEFAULT_COVERS
}

#: Every category key, for validation and for tests.
DEFAULT_COVER_KEYS: tuple[str, ...] = tuple(c.key for c in DEFAULT_COVERS)

#: Every World Artwork key the five categories occupy. Registered in
#: ``admin.platform_artwork`` from this tuple, so the manager and this
#: module cannot list different slots.
ARTWORK_KEYS: tuple[str, ...] = tuple(c.artwork_key for c in DEFAULT_COVERS)


def is_valid_key(key: str | None) -> bool:
    """Whether this is one of the five categories."""
    return key is not None and key in COVERS_BY_KEY


# ---------------------------------------------------------------------------
# Resolution — the only place the three layers are combined
# ---------------------------------------------------------------------------


def artwork_urls(db: "Session") -> dict[str, str | None]:
    """Current image URL for each category, keyed by **category** key.

    One query for all five. A category with no uploaded artwork maps to
    ``None`` rather than being absent, so callers iterate the five
    categories and never have to distinguish "missing row" from "no
    image".
    """
    from app.models.platform import PlatformArtwork

    rows = {
        r.key: r.image_url
        for r in db.query(PlatformArtwork)
        .filter(PlatformArtwork.key.in_(ARTWORK_KEYS))
        .all()
    }
    return {c.key: rows.get(c.artwork_key) for c in DEFAULT_COVERS}


def artwork_thumbnail_urls(db: "Session") -> dict[str, str | None]:
    """Thumbnail URL for each category, for the picker's grid.

    Falls back to the hero when no thumbnail exists — World Artwork
    always generates one, but a row written before it did, or one whose
    thumbnail write failed, should still show a picture.
    """
    from app.models.platform import PlatformArtwork

    rows = {
        r.key: (r.thumbnail_url or r.image_url)
        for r in db.query(PlatformArtwork)
        .filter(PlatformArtwork.key.in_(ARTWORK_KEYS))
        .all()
    }
    return {c.key: rows.get(c.artwork_key) for c in DEFAULT_COVERS}


def resolve_cover_url(
    db: "Session",
    offering: "Offering",
    *,
    shared: dict[str, str | None] | None = None,
) -> str | None:
    """The image URL this Offering should display, or ``None``.

    Precedence, and the reason for each step:

    1. ``cover_image_url`` — the creator's own upload wins. Stated
       requirement, and the reason the two columns are separate.
    2. ``default_cover_key`` — the shared category's current artwork.
       May itself be ``None`` when an administrator has not uploaded
       that category yet, which is a legitimate state.
    3. ``None`` — every surface renders a deliberate gradient. Never a
       broken image, and never a guess at a different category's
       artwork, which would show a member the wrong picture.

    An **unknown** key resolves to ``None`` rather than raising. The
    column carries no CHECK (see migration 163), so a hand-written or
    restored-from-older-dump row could hold anything; a missing image is
    a better answer than a 500 on a member's page.

    ``shared`` lets a caller listing many Offerings pass the result of
    :func:`artwork_urls` once instead of querying per row. Passing it is
    an optimisation, never a different answer.
    """
    if offering.cover_image_url:
        return offering.cover_image_url
    key = offering.default_cover_key
    if not key:
        return None
    lookup = shared if shared is not None else artwork_urls(db)
    return lookup.get(key)


# ---------------------------------------------------------------------------
# The committed source assets — for the build script and its tests
# ---------------------------------------------------------------------------


def asset_paths() -> tuple[tuple[str, Path], ...]:
    """``(filename, path)`` for all ten committed files.

    The first element is the plain filename rather than a storage key:
    these are source artwork now, with no destination of their own.
    World Artwork decides where an uploaded image lands.
    """
    out: list[tuple[str, Path]] = []
    for c in DEFAULT_COVERS:
        out.append((f"{c.file}.webp", ASSET_DIR / f"{c.file}.webp"))
        out.append((f"{c.file}-thumb.webp", ASSET_DIR / f"{c.file}-thumb.webp"))
    return tuple(out)


def hero_asset_paths() -> tuple[tuple[OfferingCover, Path], ...]:
    """Just the five heroes — what an administrator actually uploads."""
    return tuple(
        (c, ASSET_DIR / f"{c.file}.webp") for c in DEFAULT_COVERS
    )


def missing_assets() -> list[Path]:
    """Committed files named by the manifest that are not on disk."""
    return [p for _name, p in asset_paths() if not p.is_file()]


__all__ = [
    "ARTWORK_KEYS",
    "ARTWORK_KEY_PREFIX",
    "ASSET_DIR",
    "COVERS_BY_ARTWORK_KEY",
    "COVERS_BY_KEY",
    "DEFAULT_COVERS",
    "DEFAULT_COVER_KEYS",
    "OfferingCover",
    "artwork_thumbnail_urls",
    "artwork_urls",
    "asset_paths",
    "hero_asset_paths",
    "is_valid_key",
    "missing_assets",
    "resolve_cover_url",
]
