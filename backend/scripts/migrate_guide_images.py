"""Move Guide images off ``media/guides/`` onto ``guide-images/``.

Why this exists
---------------
The Guides admin originally saved images through
``save_media_file(space_slug="guides")``, producing keys shaped
``media/guides/{uuid}_{name}``. The uploads authoriser reads the
segment after ``media/`` as a Collective slug, found no Collective
called "guides", and answered 404 — to everyone, administrators in
the preview included. Guide images now live under ``guide-images/``
with their own public read route.

This script carries the already-uploaded ones across: it copies each
object to the new key and re-points the database rows that reference
it, in that order, so a run interrupted halfway leaves a row pointing
at a key that exists rather than one that does not.

Running it
----------
From the Render Shell for fc-api (or locally against a dev database)::

    python scripts/migrate_guide_images.py            # dry run
    python scripts/migrate_guide_images.py --apply

Dry run is the default and prints exactly what would change.

Idempotent: a second run finds no ``media/guides/`` references and
does nothing. Safe to run before the deploy that adds the new route,
after it, or twice.

The source objects are **not deleted**. One fewer irreversible step,
and the storage is a handful of images; clean them up by hand later
if it ever matters.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, or_  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.storage import copy_object  # noqa: E402
from app.models.guide import Guide  # noqa: E402

OLD_PREFIX = "/api/uploads/media/guides/"
NEW_PREFIX = "/api/uploads/guide-images/"


def _new_url(old_url: str) -> str:
    return NEW_PREFIX + old_url[len(OLD_PREFIX):]


def _key(url: str) -> str:
    """``/api/uploads/x/y.png`` → ``x/y.png``."""
    return url[len("/api/uploads/"):]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Perform the copy and the rewrite. Without it, dry run.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(Guide)
            .filter(
                or_(
                    Guide.hero_image_url.like(f"{OLD_PREFIX}%"),
                    func.strpos(Guide.body, OLD_PREFIX) > 0,
                ),
            )
            .all()
        )
        if not rows:
            print("Nothing to do — no Guide references media/guides/.")
            return 0

        print(f"{len(rows)} Guide(s) reference the old prefix:\n")
        copied: set[str] = set()

        for guide in rows:
            print(f"  {guide.slug}  ({guide.status})")

            # Collect every distinct old URL this row references, hero
            # first, then whatever the body embeds.
            urls: list[str] = []
            if guide.hero_image_url and guide.hero_image_url.startswith(OLD_PREFIX):
                urls.append(guide.hero_image_url)
            body = guide.body or ""
            start = 0
            while True:
                i = body.find(OLD_PREFIX, start)
                if i == -1:
                    break
                end = i
                while end < len(body) and body[end] not in '"\'< >':
                    end += 1
                urls.append(body[i:end])
                start = end

            for old_url in dict.fromkeys(urls):
                new_url = _new_url(old_url)
                print(f"    {old_url}\n      → {new_url}")
                if not args.apply or old_url in copied:
                    continue
                copy_object(_key(old_url), _key(new_url))
                copied.add(old_url)

            if args.apply:
                if guide.hero_image_url and guide.hero_image_url.startswith(OLD_PREFIX):
                    guide.hero_image_url = _new_url(guide.hero_image_url)
                if body:
                    guide.body = body.replace(OLD_PREFIX, NEW_PREFIX)

        if args.apply:
            db.commit()
            print(f"\nDone. {len(copied)} object(s) copied, {len(rows)} row(s) updated.")
            print("Source objects under media/guides/ were left in place.")
        else:
            print("\nDry run — nothing changed. Re-run with --apply.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
