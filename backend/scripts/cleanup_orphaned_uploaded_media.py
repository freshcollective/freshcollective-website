"""Find — and only with --apply, delete — abandoned uploaded objects.

One upload flow writes an object before anything references it: the
Conversations composer uploads as soon as a member picks an image and
gets a URL back, and the post carrying that URL is saved later, or
never. Abandon the draft and the object stays in R2 for ever.

Read-only by default. ``--apply`` is the only way to delete.

Scope
-----
Exactly one upload class is eligible: ``media/{slug}/community/`` — the
only flow proven to publish a URL before any row exists. Every other
namespace is listed, classified and reported with the reason it is
excluded, so a later pass can argue from the audit instead of guessing.
See ``app/services/orphaned_media.py`` for the per-writer reasoning.

"Delete every unreferenced object" would be the wrong instrument:
a Media Library asset is unreferenced by any post from the moment it is
uploaded and is meant to be, since its ``creator_media_assets`` row owns
it and archiving that row keeps the object deliberately.

An object is an orphan only if all of these hold
------------------------------------------------
  1. its key is in an approved namespace
  2. its filename is the shape the uploader produces — 32 hex
     characters from ``uuid4()``, which is what makes a filename search
     a dependable reference test
  3. its ``{slug}`` resolves to a real Collective
  4. storage's own ``LastModified`` is older than the grace period
  5. no ``creator_media_assets`` row owns it
  6. nothing anywhere in the database mentions it

Point 6 is the broad scan: every text and JSON column in the schema, by
exact substring, for the filename *and* the bare key *and* the canonical
``/api/uploads/…`` URL. The filename alone is the strongest of the three
— it is a substring of all the others, of a percent-encoded URL, and of
any of them embedded in rich text or JSON — so the search is wider than
any single representation. ``strpos``, never ``LIKE``: these keys are
full of underscores, and ``LIKE`` reads ``_`` as "any character".

Both reference shapes are real. ``community_posts.image_url`` holds a
URL; ``step_resources.url`` holds a bare key. A URL-only scan would miss
the second.

Grace period
------------
72 hours by default, 24 hours minimum. Below that the sweep stops
protecting the upload-then-save window it exists for and starts racing
a member who is still typing. Anything lower needs
``--yes-i-accept-deleting-in-flight-uploads`` spelled out.

Apply mode
----------
Every predicate is re-evaluated immediately before each delete, against
the database as it is now — an audit can be hours old by the time
somebody types ``--apply``, and a member can publish in that window. A
candidate that has gained a reference is skipped and the run continues.
Storage errors are fatal: ``delete_file`` swallows them, so success is
established by re-reading the object.

This never touches the database. It removes storage objects that are
already unreferenced; it does not make anything orphaned.

Usage::

    cd backend
    # audit — the default, writes nothing
    python scripts/cleanup_orphaned_uploaded_media.py

    # audit with a longer grace period, and full keys listed
    python scripts/cleanup_orphaned_uploaded_media.py --older-than-hours 168

    # delete
    python scripts/cleanup_orphaned_uploaded_media.py --apply

Exit codes::

    0  ran successfully (including "no orphans")
    1  unexpected error
    2  refused — an unsafe grace period without the override

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
from app.services.orphaned_media import (
    DEFAULT_GRACE_HOURS,
    LISTING_PREFIXES,
    MINIMUM_GRACE_HOURS,
    NAMESPACES,
    UNSAFE_OVERRIDE_FLAG,
    audit,
    delete_orphans,
)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("orphaned_media")


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit (and with --apply, delete) abandoned uploads.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Delete the orphan candidates. Without it, this is an audit.",
    )
    parser.add_argument(
        "--older-than-hours", type=int, default=DEFAULT_GRACE_HOURS,
        help=f"Grace period in hours (default {DEFAULT_GRACE_HOURS}, "
             f"minimum {MINIMUM_GRACE_HOURS}).",
    )
    parser.add_argument(
        UNSAFE_OVERRIDE_FLAG, dest="unsafe", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--show-all", action="store_true",
        help="List every excluded object too, not just the candidates.",
    )
    args = parser.parse_args()

    grace = args.older_than_hours
    if grace < MINIMUM_GRACE_HOURS and not args.unsafe:
        log.error(
            "Refusing a %dh grace period. The minimum is %dh, because below "
            "that this stops protecting the upload-then-save window it "
            "exists for and starts racing a member who is still typing.\n"
            "If you genuinely mean it, pass %s.",
            grace, MINIMUM_GRACE_HOURS, UNSAFE_OVERRIDE_FLAG,
        )
        return 2
    if grace < MINIMUM_GRACE_HOURS:
        log.warning(
            "Running with a %dh grace period, below the %dh minimum, because "
            "the override was passed. In-flight uploads may be deleted.",
            grace, MINIMUM_GRACE_HOURS,
        )

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 78)
            log.info(
                "orphaned uploaded media: %s",
                "APPLY" if args.apply else "AUDIT (read-only, nothing deleted)",
            )
            log.info(
                "  storage mode     %s",
                "R2" if settings.is_r2_enabled else "filesystem",
            )
            log.info(
                "  prefixes scanned %s",
                ", ".join(repr(p) or "'' (private bucket root)"
                          for p in LISTING_PREFIXES),
            )
            log.info("  grace period     %dh", grace)
            log.info("=" * 78)
            log.info("")
            log.info("listing storage and scanning the schema…")

            report = audit(db, grace_hours=grace)

            log.info("")
            log.info("OBJECTS BY NAMESPACE")
            for name in sorted(report.by_namespace):
                ns = NAMESPACES[name]
                log.info(
                    "  %-20s %5d   %s",
                    name, report.by_namespace[name],
                    "ELIGIBLE" if ns.eligible else "excluded",
                )
                log.info("  %-20s         %s", "", ns.note)
            log.info("")
            log.info("  total objects scanned      %5d", report.total_scanned)
            log.info("  text/JSON columns scanned  %5d", report.columns_scanned)
            log.info("")
            log.info("ELIGIBLE NAMESPACE — WHY EACH OBJECT WAS KEPT OR NOT")
            log.info("  inside the grace period    %5d", len(report.too_young))
            log.info("  has a live reference       %5d", len(report.referenced))
            log.info("  owned by a media-asset row %5d", len(report.owned))
            log.info("  unclassified / odd name    %5d", len(report.unclassified))
            log.info("  ORPHAN CANDIDATES          %5d", len(report.orphans))
            log.info(
                "  reclaimable                %s",
                human(report.reclaimable_bytes),
            )

            if args.show_all:
                for label, group in (
                    ("inside the grace period", report.too_young),
                    ("referenced", report.referenced),
                    ("owned", report.owned),
                    ("unclassified", report.unclassified),
                ):
                    if not group:
                        continue
                    log.info("")
                    log.info("-- kept: %s", label)
                    for c in group:
                        log.info(
                            "   %-62s %8s %7.1fh  %s",
                            c.key, human(c.size), c.age_hours,
                            "; ".join(c.exclusions),
                        )

            if not report.orphans:
                log.info("")
                log.info(
                    "No orphan candidates. Either nothing has been abandoned "
                    "outside the grace period, or a previous run cleaned it "
                    "up. Nothing to do."
                )
                return 0

            # Group the candidates by namespace, as asked.
            grouped: dict[str, list] = {}
            for c in report.orphans:
                grouped.setdefault(c.namespace, []).append(c)

            log.info("")
            log.info("=" * 78)
            log.info("ORPHAN CANDIDATES")
            log.info("=" * 78)
            for namespace, items in sorted(grouped.items()):
                log.info("")
                log.info(
                    "  %s — %d object(s), %s",
                    namespace, len(items),
                    human(sum(c.size for c in items)),
                )
                log.info("  %s", NAMESPACES[namespace].note)
                for c in items:
                    log.info("")
                    log.info("    key            %s", c.key)
                    log.info("    Collective     %s (%s)", c.space_slug, c.space_id)
                    log.info("    size           %s", human(c.size))
                    log.info("    content type   %s", c.content_type or "—")
                    log.info(
                        "    age            %.1fh (modified %s)",
                        c.age_hours, c.last_modified,
                    )
                    log.info(
                        "    references     none found in %d text/JSON "
                        "column(s), searching filename, bare key and URL",
                        report.columns_scanned,
                    )

            if not args.apply:
                log.info("")
                log.info("=" * 78)
                log.info(
                    "AUDIT ONLY — nothing deleted. %d candidate(s), %s "
                    "reclaimable.",
                    len(report.orphans), human(report.reclaimable_bytes),
                )
                log.info(
                    "Re-run with --apply to delete them. Every check above is "
                    "re-run immediately before each delete, so anything that "
                    "has since gained a reference is skipped."
                )
                return 0

            log.info("")
            log.info("=" * 78)
            log.info("applying — re-checking each candidate before deleting it")
            outcome = delete_orphans(db, report.orphans, grace_hours=grace)

            log.info("")
            log.info("APPLIED")
            log.info("  deleted   %4d  (%s freed)",
                     len(outcome.deleted), human(outcome.freed_bytes))
            for c in outcome.deleted:
                log.info("    %s", c.key)
            log.info("  skipped   %4d", len(outcome.skipped))
            for key, reason in outcome.skipped:
                log.info("    %s — %s", key, reason)
            log.info("")
            log.info(
                "  A second run does nothing: the deleted objects are gone "
                "from the listing, and anything skipped was skipped because "
                "it is not an orphan."
            )
            return 0

        except Exception:
            log.exception(
                "orphaned_media: FAILED. Nothing in the database was touched "
                "— this job only ever deletes storage objects. Any deletion "
                "that completed is listed above."
            )
            return 1
        finally:
            db.rollback()


if __name__ == "__main__":
    raise SystemExit(main())
