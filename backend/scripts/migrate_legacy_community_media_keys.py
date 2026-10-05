"""ONE-TIME: move legacy Conversation images onto their canonical key.

``save_media_file`` used to sanitise the whole ``space_slug`` string, so
Collective Conversations — the only caller that passed a path — had its
separator flattened::

    expected:  media/{slug}/community/{file}
    written:   media/{slug}_community/{file}

The writer is fixed and new uploads are nested. This moves what was
written before, so the compatibility branch in
``uploads/authorization._authorise_media`` can eventually be deleted —
and with it the edge where a Collective genuinely named
``{target}_community`` could resolve ahead of the legacy interpretation.

Read-only by default. ``--apply`` is the only way to write.

Order of operations, and why
----------------------------
copy → verify → repoint the database → delete. Never any other order.

Storage and the database cannot be committed together, so the failure
mode is chosen rather than accidental: if the database update fails
after the copy, a duplicate object is left behind and costs pennies.
Deleting first — or deleting before the reference moves — would risk the
only readable copy of a member's image. ``--keep-source`` makes that
asymmetry explicit for a first cautious run.

Re-runnable. A reference already canonical is reported and skipped. A
destination that already holds an identical object is treated as a
completed copy, not a collision, so a run that stopped halfway finishes
cleanly.

Usage::

    cd backend
    # audit — writes nothing, and this is the default
    .venv/bin/python scripts/migrate_legacy_community_media_keys.py

    # with full email addresses rather than masked ones
    .venv/bin/python scripts/migrate_legacy_community_media_keys.py --show-emails

    # migrate, leaving the old objects in place for now
    .venv/bin/python scripts/migrate_legacy_community_media_keys.py --apply --keep-source

    # migrate and remove the old objects
    .venv/bin/python scripts/migrate_legacy_community_media_keys.py --apply

Exit codes::

    0  ran successfully (including "nothing to migrate")
    1  unexpected error — the database transaction was rolled back
    2  blocked: at least one candidate is not safe. Nothing written.

Not scheduled. Absent from render.yaml, and a second run does nothing.

Runtime config::

  * ``FC_SERVICE_ROLE=job``  — skips web-only Settings validators.
  * ``DATABASE_URL``         — same database as fc-api.
  * R2 credentials           — same as fc-api, or filesystem mode in dev.
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
from app.services.legacy_community_media import (
    REFERENCE_COLUMNS,
    audit,
    migrate,
)

logging.basicConfig(
    level=logging.INFO, format="%(message)s", stream=sys.stdout,
)
log = logging.getLogger("legacy_media")


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "<none>"
    local, _, domain = email.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 0)}@{domain}"


def size_of(info) -> str:
    return f"{info.size}B" if info is not None else "—"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time migration of legacy Conversation media keys.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually copy, repoint and delete. Without it, this is an audit.",
    )
    parser.add_argument(
        "--keep-source", action="store_true",
        help=(
            "Migrate but leave the legacy objects in storage. A safe first "
            "run: the references move, nothing is removed, and a later run "
            "with --apply cleans up."
        ),
    )
    parser.add_argument(
        "--show-emails", action="store_true",
        help="Show full author addresses instead of masked ones.",
    )
    args = parser.parse_args()
    show = (lambda e: e or "<none>") if args.show_emails else mask

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 74)
            log.info(
                "legacy Conversation media keys: %s",
                "APPLY" if args.apply else "AUDIT (read-only, nothing written)",
            )
            log.info(
                "  storage mode: %s",
                "R2" if settings.is_r2_enabled else "filesystem",
            )
            log.info(
                "  columns searched: %s",
                ", ".join(f"{t}.{c}" for t, c in REFERENCE_COLUMNS),
            )
            log.info("=" * 74)

            candidates = audit(db)

            if not candidates:
                log.info("")
                log.info(
                    "No legacy references found. Either this has already run, "
                    "or no Conversation image was ever written under the "
                    "flattened key. Nothing to do."
                )
                db.rollback()
                return 0

            objects = {c.source_key for c in candidates}
            log.info("")
            log.info(
                "candidate references: %d   unique storage objects: %d",
                len(candidates), len(objects),
            )
            log.info("")

            for c in candidates:
                log.info("-" * 74)
                log.info("  %s.%s  id=%s", c.table, c.column, c.row_id)
                log.info("    url            %s", c.url)
                log.info("    source key     %s", c.source_key)
                log.info("    destination    %s", c.dest_key or "<unresolved>")
                log.info(
                    "    Collective     %s",
                    f"'{c.space_name}' ({c.space_slug}) id={c.space_id}"
                    if c.space_id else f"<unresolved from '{c.derived_slug}'>",
                )
                log.info("    author         %s", show(c.author_email))
                log.info("    created_at     %s", c.created_at)
                log.info(
                    "    source exists  %s  %s",
                    c.source_exists, size_of(c.source_info),
                )
                log.info(
                    "    dest exists    %s  %s%s",
                    c.dest_exists, size_of(c.dest_info),
                    "  (identical — copy already done)" if c.already_copied else "",
                )
                log.info("    other refs     %d", c.other_references)
                if c.blockers:
                    for b in c.blockers:
                        log.error("    BLOCKED  %s", b)
                else:
                    log.info("    safe to migrate")

            log.info("-" * 74)
            safe = [c for c in candidates if c.safe]
            blocked = [c for c in candidates if not c.safe]
            log.info("")
            log.info("  safe to migrate      %4d reference(s)", len(safe))
            log.info("  blocked              %4d reference(s)", len(blocked))
            log.info(
                "  objects to copy      %4d",
                len({c.source_key for c in safe if not c.already_copied}),
            )
            log.info(
                "  objects to delete    %4d",
                0 if args.keep_source
                else len({c.source_key for c in safe}),
            )

            if blocked:
                log.error("")
                log.error(
                    "BLOCKED — nothing written. Every candidate must be safe "
                    "before this runs: a partial migration of a shared object "
                    "is harder to reason about than none."
                )
                db.rollback()
                return 2

            if not args.apply:
                log.info("")
                log.info(
                    "AUDIT ONLY — no changes written. Re-run with --apply to "
                    "migrate the references above%s.",
                    " (add --keep-source to leave the old objects in place)",
                )
                db.rollback()
                return 0

            log.info("")
            log.info(
                "applying: copy -> verify -> repoint -> %s",
                "keep source" if args.keep_source else "delete source",
            )
            result = migrate(db, safe, delete_source=not args.keep_source)

            # The references must all be canonical now. Checked inside
            # the transaction, so a mismatch rolls the database back —
            # the copies stay, which is the harmless half.
            remaining = audit(db)
            if remaining:
                raise RuntimeError(
                    f"{len(remaining)} legacy reference(s) still present "
                    f"after the update — rolling back"
                )

            db.commit()

            log.info("")
            log.info("APPLIED")
            log.info("  objects copied        %4d", len(result.copied))
            for line in result.copied:
                log.info("    %s", line)
            log.info("  references updated   %4d", result.references_updated)
            log.info("  objects deleted      %4d", len(result.deleted))
            for key in result.deleted:
                log.info("    %s", key)
            for line in result.skipped:
                log.info("  skipped: %s", line)
            log.info("")
            if args.keep_source:
                log.info(
                    "  Legacy objects were left in place. Re-run with --apply "
                    "(without --keep-source) to remove them once you have "
                    "confirmed the images still render."
                )
            log.info(
                "  Next: re-run this audit. It must report zero references "
                "before the compatibility resolver in "
                "``uploads/authorization._authorise_media`` is removed — that "
                "removal belongs in a separate change, so there is a rollback "
                "window."
            )
            return 0

        except Exception:
            db.rollback()
            log.exception(
                "legacy_media: FAILED — database rolled back. Any object "
                "already copied is still in place and harmless; nothing was "
                "deleted unless the log above says so."
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
