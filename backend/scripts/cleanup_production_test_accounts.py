"""Audit — and only on request, remove — three disposable test accounts.

Scoped in code to exactly these three, and to nothing else:

  * jenson@hilliard.net.au      (Jenson Test)
  * hello@freshcollective.au    (Creator Test)
  * lindsey.wd@gmail.com        (Lindsey Test Account)

**tom@hilliard.net.au is protected** and cannot be a target: he is the
controlled example for the finite complimentary Creator lifecycle and
the later paid conversion, so his account, his Collective, his grant and
his Stripe references all stay. The script snapshots his rows before
doing anything and re-counts them afterwards, and rolls the whole thing
back if a single count moved.

Read-only by default. ``--apply`` is the only way to write.

What the audit is actually for
------------------------------
``users.id`` carries around a hundred foreign keys with three different
delete rules, and three of the cascades reach other people's data:
peer conversations (the thread and both sides' messages), creator↔member
threads, and Conversations the account authored (the post, plus every
real member's comments, reactions and votes on it). A plain
``DELETE FROM users`` would take all of that silently.

So the audit resolves every dependent row by reading the foreign-key map
out of ``information_schema`` at run time — not from a hand-written list
that would be wrong the moment a table is added — and refuses outright
if anything attached belongs to somebody outside the cleanup set.

Blockers are refusals, not warnings. If any one target is blocked,
nothing is deleted: these accounts exist as a set, and a half-cleaned
state is harder to reason about than either end.

Usage::

    cd backend
    # audit — writes nothing, and this is the default
    .venv/bin/python scripts/cleanup_production_test_accounts.py

    # with full email addresses for the people attached to things
    .venv/bin/python scripts/cleanup_production_test_accounts.py --show-emails

    # delete, only if the audit found no blockers
    .venv/bin/python scripts/cleanup_production_test_accounts.py --apply

Exit codes::

    0  ran successfully (audit clean, or apply completed)
    1  unexpected error — rolled back, nothing written
    2  blocked: something attached is not disposable. Nothing written.

Runtime config::

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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.test_account_cleanup import (
    PROTECTED_EMAILS,
    TARGET_EMAILS,
    apply_cleanup,
    audit,
    protected_snapshot,
    verify_protected_intact,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("cleanup_test_accounts")


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "<none>"
    local, _, domain = email.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 0)}@{domain}" if local else email


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit or remove the three disposable production test accounts.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete. Without it, this is an audit and writes nothing.",
    )
    parser.add_argument(
        "--show-emails", action="store_true",
        help="Show full addresses of attached third parties, not masked ones.",
    )
    args = parser.parse_args()
    show = (lambda e: e or "<none>") if args.show_emails else mask

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 68)
            log.info(
                "cleanup_test_accounts: %s",
                "APPLY" if args.apply else "AUDIT (read-only, nothing will be written)",
            )
            log.info("  targets:   %s", ", ".join(TARGET_EMAILS))
            log.info("  protected: %s", ", ".join(PROTECTED_EMAILS))
            log.info("=" * 68)

            before = protected_snapshot(db)
            for email, counts in before.items():
                if not counts.get("present"):
                    log.warning(
                        "  protected account %s was NOT FOUND in this database",
                        email,
                    )
                else:
                    log.info(
                        "  protected %s -> id=%s %s",
                        email, counts.get("user_id"),
                        " ".join(
                            f"{k}={v}" for k, v in counts.items()
                            if k not in {"present", "user_id"}
                        ),
                    )
            log.info("")

            plan = audit(db)

            for finding in plan.findings:
                log.info("-" * 68)
                if not finding.present:
                    log.info(
                        "%s — NOT PRESENT. Nothing to do (already removed, or "
                        "never existed in this database).", finding.email,
                    )
                    continue

                log.info(
                    "%s — id=%s name=%r role=%s",
                    finding.email, finding.user_id, finding.name, finding.role,
                )

                if finding.owned_spaces:
                    log.info("  Collectives owned:")
                    for sf in finding.owned_spaces:
                        log.info(
                            "    '%s' (%s) status=%s members=%d events=%d "
                            "pathways=%d posts=%d purchase_plans=%d payments=%d",
                            sf.name, sf.slug, sf.status, len(sf.member_emails),
                            sf.event_count, sf.pathway_count, sf.post_count,
                            sf.purchase_plan_count, sf.payment_transaction_count,
                        )
                        if sf.member_emails:
                            log.info(
                                "      members: %s",
                                ", ".join(show(e) for e in sorted(sf.member_emails)),
                            )
                        if sf.outside_member_emails:
                            log.warning(
                                "      OUTSIDE the cleanup set: %s",
                                ", ".join(
                                    show(e) for e in sorted(sf.outside_member_emails)
                                ),
                            )
                else:
                    log.info("  Collectives owned: none")

                restricting = finding.restricting()
                cascading = finding.cascading()
                nulling = finding.nulling()

                log.info(
                    "  dependent rows: %d table(s) cascade, %d restrict, %d set null",
                    len(cascading), len(restricting), len(nulling),
                )
                for dep in restricting:
                    log.info("    RESTRICT  %-52s %6d", dep.ref, dep.count)
                for dep in cascading:
                    log.info("    cascade   %-52s %6d", dep.ref, dep.count)
                for dep in nulling:
                    log.info("    set null  %-52s %6d", dep.ref, dep.count)

                if finding.blockers:
                    for b in finding.blockers:
                        log.error("  BLOCKED [%s] %s", b.kind, b.detail)
                else:
                    log.info("  no blockers — safe to delete")

            log.info("-" * 68)

            present = [f for f in plan.findings if f.present]
            log.info(
                "summary: %d of %d target(s) present, %d blocked",
                len(present), len(plan.findings), len(plan.blocked),
            )
            total_cascade = sum(
                d.count for f in present for d in f.cascading()
            )
            total_restrict = sum(
                d.count for f in present for d in f.restricting()
            )
            total_null = sum(d.count for f in present for d in f.nulling())
            log.info("  rows that would be DELETED by cascade   %6d", total_cascade)
            log.info("  rows that would be DELETED first        %6d", total_restrict)
            log.info("  rows that would be PRESERVED, nulled    %6d", total_null)
            log.info(
                "  Collectives that would be deleted       %6d",
                sum(len(f.owned_spaces) for f in present),
            )
            log.info("")
            log.info(
                "  Preserved by design: every row above marked 'set null' — "
                "Community Care records, payment transactions, discount "
                "codes, authored Gatherings and World Guide history all "
                "survive with the author reference cleared."
            )

            if plan.blocked:
                log.error("")
                log.error(
                    "BLOCKED — nothing was written. Something attached to "
                    "these accounts is not theirs to delete. Resolve the "
                    "blockers above, or exclude that account, and re-run."
                )
                db.rollback()
                return 2

            if not args.apply:
                log.info("")
                log.info(
                    "AUDIT ONLY — no changes written. Re-run with --apply to "
                    "delete the accounts listed above."
                )
                db.rollback()
                return 0

            if not present:
                log.info("")
                log.info("Nothing present to delete. Already clean.")
                db.rollback()
                return 0

            # --- apply ---------------------------------------------------
            result = apply_cleanup(db, plan)

            problems = verify_protected_intact(db, before)
            if problems:
                raise RuntimeError(
                    "protected account changed during cleanup: "
                    + "; ".join(problems)
                )

            # Re-resolve the targets: all three must now be gone.
            still_there = [
                f.email for f in plan.findings
                if f.present and db.execute(
                    text("SELECT 1 FROM users WHERE id = :uid"),
                    {"uid": f.user_id},
                ).first()
            ]
            if still_there:
                raise RuntimeError(
                    f"targets still present after delete: {still_there}"
                )

            db.commit()

            log.info("")
            log.info("APPLIED")
            log.info("  users deleted:")
            for u in result.users_deleted:
                log.info("    %s", u)
            log.info("  Collectives deleted:")
            for s in result.spaces_deleted or ["    (none)"]:
                log.info("    %s", s)
            log.info("  creator_subscriptions deleted   %6d",
                     result.subscriptions_deleted)
            log.info("  creator_media_assets deleted    %6d",
                     result.media_assets_deleted)
            for skip in result.skipped:
                log.info("  skipped: %s", skip)
            log.info("")
            log.info(
                "  %s verified unchanged: %s",
                ", ".join(PROTECTED_EMAILS),
                "all counts match the pre-run snapshot",
            )
            log.info(
                "  Stored media objects in R2 were not deleted — rows only. "
                "An orphaned blob is cheaper than a wrong deletion."
            )
            return 0

        except Exception:
            db.rollback()
            log.exception(
                "cleanup_test_accounts: FAILED — rolled back, nothing written"
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
