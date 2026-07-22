"""One-time backfill: generate thumbnails for existing Location hero artwork.

Locations whose hero was uploaded before server-side thumbnail generation
existed have a populated `hero_artwork_url` but an empty
`thumbnail_artwork_url`. Consumers fall back to the hero, but the site
serves better card images if a real thumbnail is stored.

This script finds each such Location, reads the existing hero from disk,
runs it through the same Pillow-based thumbnail helper the upload path
uses, saves the thumbnail alongside the hero, and updates the row.

Safe to re-run: Locations that already have a thumbnail are skipped by
default. Pass --force to regenerate.

Usage:
  cd backend
  .venv/bin/python scripts/backfill_location_thumbnails.py --dry-run
  .venv/bin/python scripts/backfill_location_thumbnails.py
"""

from __future__ import annotations

import argparse
import io
import pathlib
import sys

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Importing the FastAPI app registers every SQLAlchemy model, so ORM
# relationships resolve correctly regardless of which model we touch here.
import app.main  # noqa: F401,E402

from PIL import Image, UnidentifiedImageError  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.storage import (  # noqa: E402
    UPLOAD_DIR,
    generate_thumbnail_bytes,
    save_file,
    delete_file,
)
from app.models.platform import Location  # noqa: E402


UPLOAD_URL_PREFIX = "/api/uploads/"

_EXT_TO_MIME: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
}


def resolve_hero_path(hero_url: str) -> pathlib.Path | None:
    """Convert a stored hero URL into an on-disk path inside UPLOAD_DIR.
    Returns None when the URL does not point at a file within uploads."""
    if not hero_url or not hero_url.startswith(UPLOAD_URL_PREFIX):
        return None
    rel = hero_url[len(UPLOAD_URL_PREFIX):]
    try:
        target = (UPLOAD_DIR / rel).resolve()
        root = UPLOAD_DIR.resolve()
        if not target.is_relative_to(root):
            return None
    except Exception:
        return None
    return target if target.is_file() else None


def hero_subdir_from_url(hero_url: str) -> str | None:
    """Extract the subdirectory the hero lives in, so the thumbnail can
    be written alongside it (e.g. `atlas-locations/{key}`)."""
    if not hero_url.startswith(UPLOAD_URL_PREFIX):
        return None
    rel = hero_url[len(UPLOAD_URL_PREFIX):]
    parts = rel.rsplit("/", 1)
    return parts[0] if len(parts) == 2 else None


def probe_image(data: bytes) -> None:
    """Raise UnidentifiedImageError / OSError if data isn't a readable image."""
    with Image.open(io.BytesIO(data)) as im:
        im.verify()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be done without writing files or updating rows.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate thumbnails even when thumbnail_artwork_url is already set.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY-RUN — no files written, no rows updated.")
    if args.force:
        print("FORCE — existing thumbnails will be regenerated.")
    print()

    db = SessionLocal()
    counts = {"CREATED": 0, "SKIPPED": 0, "MISSING": 0, "FAILED": 0}
    inspected = 0

    try:
        locations = (
            db.query(Location)
            .filter(Location.hero_artwork_url.isnot(None))
            .order_by(Location.key)
            .all()
        )

        for loc in locations:
            inspected += 1
            key = loc.key
            hero_url = loc.hero_artwork_url or ""

            if loc.thumbnail_artwork_url and not args.force:
                print(f"SKIPPED  {key}  (thumbnail already present)")
                counts["SKIPPED"] += 1
                continue

            hero_path = resolve_hero_path(hero_url)
            if hero_path is None:
                print(f"MISSING  {key}  (hero file not resolvable: {hero_url})")
                counts["MISSING"] += 1
                continue

            try:
                data = hero_path.read_bytes()
                probe_image(data)
            except (UnidentifiedImageError, OSError) as e:
                print(f"FAILED   {key}  (cannot read hero: {e})")
                counts["FAILED"] += 1
                continue

            subdir = hero_subdir_from_url(hero_url)
            if subdir is None:
                print(f"FAILED   {key}  (could not derive subdir from {hero_url})")
                counts["FAILED"] += 1
                continue

            ext = hero_path.suffix.lower()
            mime = _EXT_TO_MIME.get(ext)
            if mime is None:
                print(f"FAILED   {key}  (unsupported extension: {ext})")
                counts["FAILED"] += 1
                continue

            if args.dry_run:
                print(f"WOULD-CREATE {key}  (from {hero_path.name})")
                counts["CREATED"] += 1
                continue

            # Generate + persist the thumbnail. Do not touch the hero.
            try:
                thumb_bytes, thumb_name = generate_thumbnail_bytes(data, hero_path.name)
                thumb_rel, _rt, _sz = save_file(thumb_bytes, thumb_name, mime, subdir)
            except Exception as e:  # noqa: BLE001
                print(f"FAILED   {key}  (thumbnail generation: {e})")
                counts["FAILED"] += 1
                continue

            new_thumb_url = f"{UPLOAD_URL_PREFIX}{thumb_rel}"
            old_thumb_url = loc.thumbnail_artwork_url

            try:
                loc.thumbnail_artwork_url = new_thumb_url
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                # If DB commit failed, clean up the newly-written thumb so
                # we don't leave an orphan on disk.
                try:
                    delete_file(thumb_rel)
                except Exception:  # noqa: BLE001
                    pass
                print(f"FAILED   {key}  (db commit: {e})")
                counts["FAILED"] += 1
                continue

            # DB write succeeded — safe to delete the old thumbnail file
            # (only reachable with --force since default skips populated rows).
            if old_thumb_url and old_thumb_url.startswith(UPLOAD_URL_PREFIX):
                try:
                    delete_file(old_thumb_url[len(UPLOAD_URL_PREFIX):])
                except Exception:  # noqa: BLE001
                    pass

            print(f"CREATED  {key}  -> {new_thumb_url}")
            counts["CREATED"] += 1

    finally:
        db.close()

    print()
    print("Summary")
    print(f"  Locations inspected:        {inspected}")
    print(f"  Thumbnails created:         {counts['CREATED']}")
    print(f"  Skipped (already present):  {counts['SKIPPED']}")
    print(f"  Missing hero files:         {counts['MISSING']}")
    print(f"  Failed:                     {counts['FAILED']}")

    return 0 if counts["FAILED"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
