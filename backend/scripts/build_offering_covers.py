"""Turn an approved source image into the two committed cover assets.

    python -m scripts.build_offering_covers --list
    python -m scripts.build_offering_covers workbook-guides collections
    python -m scripts.build_offering_covers --all

Why this exists
---------------

The five covers were converted by hand in B6 — PNG sources down to
1200px heroes and 600px thumbnails, WebP at quality 82/80 — and the
parameters survived only in a docstring. When two categories were
replaced, that had to be reconstructed by measuring the existing files.
This script records it as code so the next replacement is one command
and produces assets indistinguishable from their siblings.

What it does, and what it refuses to do
---------------------------------------

For each cover key it reads the source image from the approved folder,
writes ``<file>.webp`` at 1200px wide and ``<file>-thumb.webp`` at
600px, both into ``app/assets/offering-covers/`` under the exact
filenames ``services.offering_covers`` expects.

* **The source folder is never written to.** Opened read-only, and the
  script asserts the file's mtime and size are unchanged when it
  finishes.
* **Only keys in the manifest are accepted.** A typo names no file
  rather than creating one the manifest cannot see.
* **Aspect ratio is checked, not cropped.** The covers are 3:2 and the
  layouts reserve a 3:2 box. A source at a different ratio is refused
  with its measurements, because silently letterboxing or cropping
  somebody's approved artwork is worse than stopping.
* It will not run without Pillow, and it will not guess at a format:
  the output is WebP because the manifest's URLs say ``.webp``.

Dimensions and quality are the measured values from the B6 assets, so
re-running it over an unchanged source reproduces that source's current
asset byte-for-byte in dimensions and near-identically in size.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: The approved source folder. Read-only — see the module docstring.
#: Deliberately absolute and outside this repository: the originals are
#: the user's, and this checkout holds only the optimised derivatives.
SOURCE_DIR = Path("/home/lindsey/fc-production/Offering images")

#: Measured from the B6 assets, which are the reference.
HERO_WIDTH = 1200
THUMB_WIDTH = 600
HERO_QUALITY = 82
THUMB_QUALITY = 80

#: The covers are 3:2. Tolerance is generous enough for a source that is
#: 1536x1024 or 3000x2000 and tight enough to catch a 4:3 or a square.
TARGET_RATIO = 3 / 2
RATIO_TOLERANCE = 0.02


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "app" / "assets" / "offering-covers"


def _find_source(file_stem: str) -> Path:
    """The source image for this cover, whatever extension it carries.

    The user replaces artwork by dropping a new file in; two of the five
    arrived as WebP where the originals were PNG. So the extension is
    discovered rather than assumed, and an ambiguous pair is refused
    rather than resolved by alphabetical luck.
    """
    candidates = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.is_file() and p.stem == file_stem
        and p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg")
    )
    if not candidates:
        raise SystemExit(
            f"No source image for {file_stem!r} in {SOURCE_DIR}.\n"
            f"  looked for {file_stem}.(png|webp|jpg|jpeg)"
        )
    if len(candidates) > 1:
        raise SystemExit(
            f"Ambiguous source for {file_stem!r}: "
            + ", ".join(p.name for p in candidates)
            + "\n  Remove the one you do not want before running this."
        )
    return candidates[0]


def _build_one(cover, *, dry_run: bool) -> list[str]:
    from PIL import Image

    src = _find_source(cover.file)
    before = (src.stat().st_mtime_ns, src.stat().st_size)

    with Image.open(src) as im:
        width, height = im.size
        ratio = width / height
        if abs(ratio - TARGET_RATIO) > RATIO_TOLERANCE:
            raise SystemExit(
                f"{src.name} is {width}x{height} (ratio {ratio:.3f}).\n"
                f"  Offering covers are 3:2 ({TARGET_RATIO:.3f}); the member"
                f" page and the cards both reserve a 3:2 box.\n"
                f"  Refusing rather than cropping approved artwork."
            )
        if width < HERO_WIDTH:
            raise SystemExit(
                f"{src.name} is only {width}px wide; the hero is "
                f"{HERO_WIDTH}px. Upscaling would look worse than the"
                f" image it replaced."
            )
        # WebP has no alpha concerns for these, but a source saved with
        # one would otherwise encode a pointless alpha channel.
        source = im.convert("RGB") if im.mode not in ("RGB", "L") else im.copy()

    out: list[str] = []
    for width_px, quality, suffix in (
        (HERO_WIDTH, HERO_QUALITY, ""),
        (THUMB_WIDTH, THUMB_QUALITY, "-thumb"),
    ):
        height_px = round(source.height * (width_px / source.width))
        target = _asset_dir() / f"{cover.file}{suffix}.webp"
        if dry_run:
            out.append(
                f"    would write {target.name:<32} {width_px}x{height_px}"
                f"  q{quality}"
            )
            continue
        # LANCZOS, matching ``core.storage.generate_thumbnail_bytes``.
        resized = source.resize((width_px, height_px), Image.LANCZOS)
        resized.save(target, format="WEBP", quality=quality, method=6)
        out.append(
            f"    {target.name:<32} {width_px}x{height_px}"
            f"  q{quality}  {target.stat().st_size / 1024:.0f} KB"
        )

    after = (src.stat().st_mtime_ns, src.stat().st_size)
    if before != after:                              # pragma: no cover
        raise SystemExit(
            f"REFUSING TO CONTINUE: {src} changed while being read. "
            "The source folder must never be written to."
        )
    return out


def main(argv: list[str] | None = None) -> int:
    from app.services import offering_covers as covers

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "keys", nargs="*",
        help="cover keys to rebuild (see --list)",
    )
    parser.add_argument("--all", action="store_true", help="rebuild all five")
    parser.add_argument("--list", action="store_true", help="show the manifest")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be written, write nothing",
    )
    args = parser.parse_args(argv)

    by_key = {c.key: c for c in covers.DEFAULT_COVERS}

    if args.list:
        print(f"\nsource folder: {SOURCE_DIR}")
        print(f"asset folder:  {_asset_dir()}\n")
        print(f"  {'key':<20} {'file stem':<20} {'source present':<16} label")
        for c in covers.DEFAULT_COVERS:
            try:
                found = _find_source(c.file).name
            except SystemExit:
                found = "— missing —"
            print(f"  {c.key:<20} {c.file:<20} {found:<16} {c.label}")
        print()
        return 0

    keys = list(by_key) if args.all else args.keys
    if not keys:
        parser.error("name at least one cover key, or pass --all / --list")

    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise SystemExit(
            f"Unknown cover key(s): {', '.join(unknown)}\n"
            f"  known: {', '.join(by_key)}\n"
            "  A key not in the manifest would produce a file nothing reads."
        )

    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Source folder not found: {SOURCE_DIR}")

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}"
          f"rebuilding {len(keys)} cover(s) from {SOURCE_DIR}\n")
    for key in keys:
        cover = by_key[key]
        src = _find_source(cover.file)
        print(f"  {cover.label}  ({key})")
        print(f"    source: {src.name}  "
              f"{src.stat().st_size / 1024:.0f} KB")
        for line in _build_one(cover, dry_run=args.dry_run):
            print(line)
        print()
    if args.dry_run:
        print("Nothing written. Re-run without --dry-run.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
