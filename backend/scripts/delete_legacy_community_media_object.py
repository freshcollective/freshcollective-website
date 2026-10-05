"""ONE-TIME: delete the one legacy Conversation object left in storage.

The migration moved ``media/{slug}_community/{file}`` to
``media/{slug}/community/{file}`` and repointed the database. Run with
``--keep-source``, it left the old object behind on purpose, so the
images could be confirmed to render before anything became
irreversible. They render. This removes it.

Why this does not discover anything
-----------------------------------
The database is already canonical, so *nothing* references the old key
— that is the goal of the migration, not a signal to search on. A
discovery-based delete would have no input here, and a "delete every
flattened media key" sweep would be a far broader instrument than the
one object in front of us. So the key pair is explicit, and the script
proves the object is safe to lose instead of inferring it.

What is checked before the delete
---------------------------------
  * the legacy object exists (or is already gone — then there is
    nothing to do, and that is a success)
  * the canonical object exists
  * their sizes match
  * their content hashes match, where the backend gives comparable ones
  * **zero** database references point at the legacy URL
  * **at least one** points at the canonical URL
  * an ordinary active member of that Collective can read the canonical
    key through the real authoriser, and a non-member cannot

The reference scan is deliberately wider than the migration's two
columns: it searches every text column in the schema whose name could
hold a media URL, by substring, so a URL embedded in rich text counts
too. A migration cares where images are written; a delete cares whether
anything at all still points at the bytes.

Read-only by default. ``--apply`` is the only way to delete, it removes
only the exact legacy key, and it verifies afterwards that the legacy
object is gone and the canonical object is still there. Re-running after
a successful delete reports "already gone" and exits 0.

Usage::

    cd backend
    # audit — the default, writes nothing
    python scripts/delete_legacy_community_media_object.py

    # delete the legacy object
    python scripts/delete_legacy_community_media_object.py --apply

Exit codes::

    0  safe, or already done
    1  unexpected error
    2  blocked — something did not check out. Nothing deleted.

Not scheduled. Absent from render.yaml.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("FC_SERVICE_ROLE", "job")

# ruff: noqa: E402
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.legacy_community_media import check_orphan, delete_orphan

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("legacy_orphan")

#: The object the migration left behind, and its replacement. Named
#: explicitly rather than discovered — see the module docstring.
DEFAULT_SOURCE_KEY = (
    "media/embody_community/daf81721d32644f3a8ee26166c6b91f4_IMG_3359.jpeg"
)
DEFAULT_DEST_KEY = (
    "media/embody/community/daf81721d32644f3a8ee26166c6b91f4_IMG_3359.jpeg"
)


def describe(info) -> str:
    if info is None:
        return "absent"
    tag = f" etag={info.etag}" if info.etag else ""
    return f"{info.size}B{tag}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete one legacy Conversation object, after proving it "
                    "is safe to lose.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Delete the legacy object. Without it, this is an audit.",
    )
    parser.add_argument(
        "--source-key", default=DEFAULT_SOURCE_KEY,
        help="Legacy key to delete. Defaults to the known one.",
    )
    parser.add_argument(
        "--dest-key", default=DEFAULT_DEST_KEY,
        help="Canonical key it was migrated to. Defaults to the known one.",
    )
    args = parser.parse_args()

    engine = create_engine(
        settings.database_url, future=True, pool_pre_ping=True,
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 74)
            log.info(
                "legacy Conversation object cleanup: %s",
                "APPLY" if args.apply else "AUDIT (read-only, nothing deleted)",
            )
            log.info(
                "  storage mode: %s",
                "R2" if settings.is_r2_enabled else "filesystem",
            )
            log.info("=" * 74)

            c = check_orphan(db, args.source_key, args.dest_key)

            log.info("")
            log.info("  legacy object      %s", c.source_key)
            log.info("                     %s", describe(c.source_info))
            log.info("  canonical object   %s", c.dest_key)
            log.info("                     %s", describe(c.dest_info))
            log.info("")
            log.info(
                "  columns scanned    %d (every text column that could hold "
                "a media URL)", c.columns_scanned,
            )
            log.info(
                "  legacy references  %d%s", len(c.legacy_references),
                "  " + ", ".join(c.legacy_references[:5])
                if c.legacy_references else "   (required: 0)",
            )
            log.info(
                "  canonical refs     %d%s", len(c.canonical_references),
                "  " + ", ".join(c.canonical_references[:5])
                if c.canonical_references else "   (required: at least 1)",
            )
            log.info("")
            log.info("  member can read    %s", c.member_allowed or "not checked")
            log.info("  non-member denied  %s", c.non_member_denied or "not checked")

            for note in c.notes:
                log.info("  note: %s", note)
            for blocker in c.blockers:
                log.error("  BLOCKED  %s", blocker)

            log.info("")
            if c.blockers:
                log.error(
                    "BLOCKED — nothing deleted. The legacy object stays where "
                    "it is, which is the harmless outcome."
                )
                return 2

            if c.already_deleted:
                log.info(
                    "ALREADY DONE — the legacy object is gone and the "
                    "canonical one is in place and referenced. Nothing to do."
                )
                return 0

            if not args.apply:
                log.info(
                    "SAFE TO DELETE — audit only, nothing written. Re-run with "
                    "--apply to remove the legacy object."
                )
                return 0

            log.info("deleting %s", c.source_key)
            removed = delete_orphan(c)
            log.info("")
            log.info("DELETED" if removed else "NOTHING TO DELETE")
            log.info("  legacy object gone        %s", c.source_key)
            log.info("  canonical object intact   %s", c.dest_key)
            log.info("")
            log.info(
                "  Next: the legacy authorisation fallback is already removed "
                "in code, so there is nothing left to unwind. A re-run of "
                "scripts/migrate_legacy_community_media_keys.py should keep "
                "reporting zero references."
            )
            return 0

        except Exception:
            log.exception(
                "legacy_orphan: FAILED. If the delete had already gone "
                "through, the log above says so; the canonical object is "
                "never touched by this script."
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
