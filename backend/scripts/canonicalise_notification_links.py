"""ONE-TIME: move in-app notification links off the old frontend host.

Before the custom domain, member-facing links were built from
``FRONTEND_ORIGIN`` — fc-web's Render host. Emails carrying that host
are history and stay as they are. In-app notifications are not history:
the row *is* the link, and tapping one today takes a member to a
hostname that is not the product.

    https://fc-web-q950.onrender.com/reset-password?token=X
    →  https://freshcollective.au/reset-password?token=X

Only the origin changes. Path, query and fragment are preserved byte for
byte — a notification URL can carry a token, and the token was never
the problem.

Read-only by default. ``--apply`` is the only way to write.

What it refuses to touch
------------------------
  * any other ``onrender.com`` subdomain — reported, not rewritten
  * every external host, Stripe included
  * relative paths, which are how most in-app links are stored and
    which have no origin to correct
  * notification ``title`` and ``message``. If the old host appears in
    one of those it is reported, because that is content rather than
    navigation and a person should decide.

Nothing else on the row is written — not ``is_read``, not timestamps,
not the body. Each update is additionally guarded on the exact URL it
was audited with, so a row that changed in between is skipped rather
than overwritten.

Usage::

    cd backend
    # audit — the default, writes nothing
    python scripts/canonicalise_notification_links.py

    # with full recipient addresses rather than masked ones
    python scripts/canonicalise_notification_links.py --show-emails

    # rewrite
    python scripts/canonicalise_notification_links.py --apply

Exit codes::

    0  ran successfully (including "nothing to do")
    1  unexpected error — the transaction was rolled back
    2  blocked: something needs review. Nothing written.

Not scheduled. Absent from render.yaml, and a second run does nothing.
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
from app.services.notification_link_canonicalisation import (
    OLD_ORIGIN,
    apply as apply_rewrites,
    audit,
    destination_is_usable,
    remaining,
)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("notification_links")


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "<none>"
    local, _, domain = email.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 0)}@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time canonicalisation of in-app notification links.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Rewrite the links. Without it, this is an audit.",
    )
    parser.add_argument(
        "--show-emails", action="store_true",
        help="Show full recipient addresses instead of masked ones.",
    )
    args = parser.parse_args()
    show = (lambda e: e or "<none>") if args.show_emails else mask

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 78)
            log.info(
                "in-app notification links: %s",
                "APPLY" if args.apply else "AUDIT (read-only, nothing written)",
            )
            log.info("  rewriting origin   %s", OLD_ORIGIN)
            log.info("              to     %s", settings.resolved_public_app_url)
            log.info("  path, query and fragment are preserved exactly")
            log.info("=" * 78)

            unusable = destination_is_usable()
            if unusable and args.apply:
                log.error("")
                log.error("REFUSING TO APPLY — %s", unusable)
                db.rollback()
                return 2
            if unusable:
                log.warning("")
                log.warning("NOTE — %s", unusable)
                log.warning("The audit below is still accurate; --apply "
                            "would be refused.")

            findings, mentions = audit(db)

            if not findings and not mentions:
                log.info("")
                log.info(
                    "No in-app notification links on the old host. Either "
                    "this has already run, or there were none. Nothing to do."
                )
                db.rollback()
                return 0

            safe = [f for f in findings if f.safe]
            needs_review = [f for f in findings if not f.safe]

            log.info("")
            log.info("AFFECTED NOTIFICATIONS")
            for finding in findings:
                log.info("-" * 78)
                log.info("  id             %s", finding.notification_id)
                log.info("  type           %s", finding.notification_type)
                log.info("  recipient      %s", show(finding.email))
                log.info("  created_at     %s", finding.created_at)
                log.info("  read           %s", finding.is_read)
                log.info("  from           %s", finding.old_url)
                log.info("  to             %s", finding.new_url)
                for warning in finding.warnings:
                    log.error("  REVIEW         %s", warning)

            if mentions:
                log.info("-" * 78)
                log.info("")
                log.info(
                    "THE OLD HOST ALSO APPEARS IN NOTIFICATION TEXT — not "
                    "rewritten, because that is content rather than navigation:"
                )
                for mention in mentions:
                    log.info(
                        "  %s  %s: %s",
                        mention.notification_id, mention.column, mention.excerpt,
                    )

            log.info("-" * 78)
            log.info("")
            log.info("  rewritable         %4d", len(safe))
            log.info("  needing review     %4d", len(needs_review))
            log.info("  mentions in text   %4d", len(mentions))

            if needs_review:
                log.error("")
                log.error(
                    "BLOCKED — nothing written. %d row(s) matched "
                    "'onrender.com' but not the one origin this tool "
                    "rewrites. Look at them before continuing; a host nobody "
                    "expected is worth understanding rather than guessing at.",
                    len(needs_review),
                )
                db.rollback()
                return 2

            if not args.apply:
                log.info("")
                log.info(
                    "AUDIT ONLY — nothing written. Re-run with --apply to "
                    "rewrite the %d link(s) above.", len(safe),
                )
                db.rollback()
                return 0

            updated = apply_rewrites(db, safe)

            # Re-audited inside the transaction: a non-zero count rolls
            # the whole thing back rather than reporting a partial pass.
            left = remaining(db)
            if left:
                raise RuntimeError(
                    f"{left} notification(s) still link to the old host "
                    f"after the rewrite — rolling back"
                )

            db.commit()

            log.info("")
            log.info("APPLIED")
            log.info("  links rewritten    %4d", len(updated))
            for finding in updated:
                log.info("    %s", finding.notification_id)
            skipped = len(safe) - len(updated)
            if skipped:
                log.info(
                    "  skipped            %4d  (changed since the audit)",
                    skipped,
                )
            log.info("")
            log.info(
                "  Re-audit reports %d notification(s) on the old host.", left,
            )
            log.info(
                "  Nothing else was written: no email history, no intent, no "
                "event payload, and nothing on these rows but the url."
            )
            return 0

        except Exception:
            db.rollback()
            log.exception(
                "notification_links: FAILED — rolled back. No notification "
                "link was changed."
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
