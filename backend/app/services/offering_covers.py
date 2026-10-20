"""The curated default cover images an Offering may use.

Phase B6. Five approved images, named once here and referenced
everywhere — by the creator's picker, by the readiness check that
decides whether a cover is publishable, and by the installer that puts
the bytes in storage.

Referenced, never copied
------------------------

Choosing a default cover stores a **URL** on the Offering
(``/api/uploads/platform-artwork/offering-covers/<file>``). It does not
copy bytes into the creator's namespace. One object serves every
Offering that picks it, which is the approved behaviour and also why
these live under ``platform-artwork/`` — ``_bucket_for_key`` routes that
prefix to the **public** bucket and ``serve_public_upload`` serves it
without authentication, so a cover on a public Collective card needs no
session.

Two sizes, one decision
-----------------------

Each cover ships as a 1200px hero and a 600px thumbnail, mirroring
``THUMBNAIL_TARGET_WIDTH`` in ``core.storage``. A card showing a 1200px
image would move four times the bytes it needs, and the member detail
page showing a 600px one would look soft. WebP at quality 82/80 takes
the five source PNGs from 10.9 MB to 684 KB — a 94% reduction with no
visible change.

Why a manifest rather than a regex
----------------------------------

``offering_readiness.is_acceptable_cover`` used to accept any
hyphenated filename under the default prefix, and its own docstring
recorded the gap: *"the right tightening is a manifest constant listing
the real filenames"*. This is that constant. Membership of
:data:`DEFAULT_COVER_URLS` is now an exact-match test, so a creator can
store a default cover that exists and nothing else. That is a
**narrowing** of what the validator accepts, not a relaxation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Storage namespace. Public bucket, unauthenticated route — see above.
COVER_PREFIX = "platform-artwork/offering-covers"

#: Where the optimised files live in the repository. The installer reads
#: from here; nothing at runtime does.
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "offering-covers"


@dataclass(frozen=True)
class OfferingCover:
    """One curated cover.

    ``key`` is stable and is what a future migration or report would
    join on; ``label`` is what the creator reads. The two are separate
    so the wording can be improved without invalidating stored URLs.
    """

    key: str
    label: str
    #: One line telling a creator what this cover suits. Shown under the
    #: thumbnail in the picker.
    description: str
    #: Base filename, without extension. ``<file>.webp`` is the hero and
    #: ``<file>-thumb.webp`` the thumbnail.
    file: str

    @property
    def url(self) -> str:
        return f"/api/uploads/{COVER_PREFIX}/{self.file}.webp"

    @property
    def thumbnail_url(self) -> str:
        return f"/api/uploads/{COVER_PREFIX}/{self.file}-thumb.webp"

    @property
    def storage_key(self) -> str:
        return f"{COVER_PREFIX}/{self.file}.webp"

    @property
    def thumbnail_storage_key(self) -> str:
        return f"{COVER_PREFIX}/{self.file}-thumb.webp"

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
        }


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
        description="Several resources gathered into one download.",
        file="collections",
    ),
    OfferingCover(
        key="other-resources",
        label="Other resources",
        description="Anything else — images, references and mixed material.",
        file="other-resources",
    ),
)

COVERS_BY_KEY: dict[str, OfferingCover] = {c.key: c for c in DEFAULT_COVERS}

#: Every URL a creator may store as a default cover. Hero images only:
#: a thumbnail is a rendering detail the picker resolves, not a value
#: anybody stores, so allowing one here would let an Offering be
#: published with a 600px cover on its detail page.
DEFAULT_COVER_URLS: frozenset[str] = frozenset(c.url for c in DEFAULT_COVERS)


def manifest() -> list[dict]:
    """The picker's payload."""
    return [c.as_dict() for c in DEFAULT_COVERS]


def is_default_cover(url: str | None) -> bool:
    """Exact membership. See the module docstring."""
    return bool(url) and url in DEFAULT_COVER_URLS


def asset_paths() -> list[tuple[str, Path]]:
    """``(storage_key, local_path)`` for every file the installer ships."""
    out: list[tuple[str, Path]] = []
    for cover in DEFAULT_COVERS:
        out.append((cover.storage_key, ASSET_DIR / f"{cover.file}.webp"))
        out.append(
            (cover.thumbnail_storage_key, ASSET_DIR / f"{cover.file}-thumb.webp")
        )
    return out


def missing_assets() -> list[Path]:
    """Repository files the manifest names but that are not present."""
    return [p for _key, p in asset_paths() if not p.is_file()]


__all__ = [
    "COVER_PREFIX",
    "ASSET_DIR",
    "OfferingCover",
    "DEFAULT_COVERS",
    "COVERS_BY_KEY",
    "DEFAULT_COVER_URLS",
    "manifest",
    "is_default_cover",
    "asset_paths",
    "missing_assets",
]
