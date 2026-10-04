"""ONE-TIME: reset Ways to Connect participation so every member chooses.

Ways to Connect launched with ``users.ways_to_connect_enabled`` defaulting
to ``true`` (migration 138), then became opt-in (migration 150). Migration
150 only changed the default for accounts created afterwards — deliberately,
because resetting live participation is a product decision about real
people and does not belong in a file that runs automatically on deploy.

This script is that decision, made explicit and reviewable. It sets every
``true`` to ``false`` exactly once, so that participation from here on is
something each member actually chose rather than something they inherited.

Why a ``true`` cannot be read as consent
----------------------------------------
Established by ``scripts/ways_to_connect_participation_audit.py`` and
confirmed against production on 2026-10-05 (11 accounts, all ``true``,
none ``false``):

  * The column is NOT NULL with no tri-state — migration 138 rejected a
    "hasn't decided" state outright, so nobody was ever asked.
  * ``users.updated_at`` is ``onupdate`` on the whole row, so it moves for
    a name change, a bio edit, a suspension or an email verification. It
    cannot isolate a choice about this field.
  * There is no audit table, no settings-change event and no consent row
    for this field anywhere in the schema.

A ``false``, by contrast, *is* trustworthy: nothing writes ``false``
except the member's own PATCH of ``/api/auth/me``. So rows already
``false`` are deliberate opt-outs and are never touched here — the
``WHERE`` clause excludes them, which also makes a second run a no-op.

What this does NOT touch
------------------------
Only ``users.ways_to_connect_enabled``. Participation opt-out is not
blocking and is not a deletion: existing connections and conversations
stay exactly as they are. Nothing reads or writes ``member_hellos``,
``peer_threads``, ``peer_messages``, ``member_blocks``, Community Care
reports, or any other account or profile field. Asserted by test, not
just by reading the SQL.

Members keep the Ways to Connect and Messages navigation and the Your
World doorway afterwards, and ``/ways-to-connect`` shows them the opt-in
state with a "Turn on Ways to Connect" button. Nobody loses the route
back in.

**This is not a scheduled job.** It is run once, by hand, and then it is
history. It is deliberately absent from ``render.yaml`` and from Render
cron, and it would do nothing on a second run anyway.

Usage::

    cd backend
    # inspect — writes nothing, and this is the default
    .venv/bin/python scripts/ways_to_connect_reset_participation_once.py

    # same, with full email addresses rather than masked ones
    .venv/bin/python scripts/ways_to_connect_reset_participation_once.py --show-emails

    # actually reset the rows listed above
    .venv/bin/python scripts/ways_to_connect_reset_participation_once.py --apply

Emails are masked by default. The dry run exists to be pasted into a
conversation for review, and a list of member addresses is not something
to put in a shell transcript by accident. At this scale the masked form
plus the role is enough to recognise an account; ``--show-emails`` is
there when it genuinely is not.

Exit codes::

    0  ran successfully (including "nothing to do")
    1  unexpected error — the transaction was rolled back

Runtime config (least-privilege, matches the reconcilers)::

  * ``FC_SERVICE_ROLE=job``  — skips web-only Settings validators.
  * ``DATABASE_URL``         — same database as fc-api.
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
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.user import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ways_to_connect_reset")

#: The tables a participation change must leave completely alone. Used by
#: the tests to assert the blast radius rather than infer it.
UNTOUCHED_TABLES = (
    "member_hellos",
    "peer_threads",
    "peer_messages",
    "member_blocks",
)


def mask_email(email: str | None) -> str:
    """``ada@example.com`` -> ``a**@example.com``. Enough to recognise an
    account without putting the address in a shell transcript."""
    if not email or "@" not in email:
        return "<none>"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"{local}@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time reset of Ways to Connect participation to opt-in.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the change. Without it, this is a dry run.",
    )
    parser.add_argument(
        "--show-emails",
        action="store_true",
        help="Print full email addresses instead of masked ones.",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            def count(*where) -> int:
                return db.scalar(
                    select(func.count()).select_from(User).where(*where)
                ) or 0

            total = db.scalar(select(func.count()).select_from(User)) or 0
            before_true = count(User.ways_to_connect_enabled.is_(True))
            before_false = count(User.ways_to_connect_enabled.is_(False))

            mode = "APPLY" if args.apply else "DRY RUN (nothing will be written)"
            logger.info("ways_to_connect_reset: %s", mode)
            logger.info("  total accounts                  %6d", total)
            logger.info("  ways_to_connect_enabled = true  %6d", before_true)
            logger.info("  ways_to_connect_enabled = false %6d", before_false)
            logger.info("")

            # The rows the UPDATE will match, read before writing so the
            # dry run and the apply report the same set.
            targets = db.scalars(
                select(User)
                .where(User.ways_to_connect_enabled.is_(True))
                .order_by(User.role, User.created_at)
            ).all()

            if not targets:
                logger.info(
                    "ways_to_connect_reset: nothing to do — no account is "
                    "opted in by inheritance. A previous run has already "
                    "done this, or every member has chosen for themselves."
                )
                db.rollback()
                return 0

            logger.info(
                "ways_to_connect_reset: %d account(s) would move true -> false"
                if not args.apply else
                "ways_to_connect_reset: %d account(s) moving true -> false",
                len(targets),
            )
            for user in targets:
                logger.info(
                    "  %-11s role=%-7s id=%s  %s",
                    "would reset" if not args.apply else "reset",
                    user.role,
                    user.id,
                    user.email if args.show_emails else mask_email(user.email),
                )
            logger.info("")

            if not args.apply:
                logger.info(
                    "ways_to_connect_reset: DRY RUN — no changes written. "
                    "Re-run with --apply to perform the reset."
                )
                # Nothing was written, but the SELECTs opened a
                # transaction worth closing cleanly.
                db.rollback()
                return 0

            # One statement, scoped by the same predicate that produced
            # the list above. Rows already ``false`` are excluded, which
            # preserves every deliberate opt-out and makes a second run
            # match nothing.
            result = db.execute(
                User.__table__.update()
                .where(User.ways_to_connect_enabled.is_(True))
                .values(ways_to_connect_enabled=False)
            )
            changed = result.rowcount

            after_true = count(User.ways_to_connect_enabled.is_(True))
            after_false = count(User.ways_to_connect_enabled.is_(False))

            # Read back inside the transaction, so a disagreement rolls
            # the whole thing back rather than leaving it half done.
            if after_true != 0:
                raise RuntimeError(
                    f"expected 0 accounts opted in after the reset, found "
                    f"{after_true} — rolling back"
                )
            if changed != len(targets):
                raise RuntimeError(
                    f"expected to change {len(targets)} row(s), changed "
                    f"{changed} — rolling back"
                )
            if after_false != before_false + changed:
                raise RuntimeError(
                    f"opt-out total does not add up: {before_false} + "
                    f"{changed} != {after_false} — rolling back"
                )

            db.commit()

            logger.info("ways_to_connect_reset: APPLIED")
            logger.info("  rows changed                    %6d", changed)
            logger.info("  ways_to_connect_enabled = true  %6d (was %d)",
                        after_true, before_true)
            logger.info("  ways_to_connect_enabled = false %6d (was %d)",
                        after_false, before_false)
            logger.info("")
            logger.info(
                "  Untouched by design: %s, and every other account and "
                "profile field. Existing connections and conversations are "
                "unaffected.", ", ".join(UNTOUCHED_TABLES),
            )
            logger.info(
                "  Members keep the navigation and the Your World doorway, "
                "and /ways-to-connect now offers them the opt-in state."
            )
            return 0

        except Exception:
            db.rollback()
            logger.exception(
                "ways_to_connect_reset: FAILED — rolled back, nothing written"
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
