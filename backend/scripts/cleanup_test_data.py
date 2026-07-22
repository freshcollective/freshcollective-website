"""
Production readiness cleanup — remove test/sandbox data before go-live.

Usage:
  # Dry run (default — shows what would be deleted, nothing is committed):
  python scripts/cleanup_test_data.py

  # Execute (actually deletes — prompts for confirmation first):
  python scripts/cleanup_test_data.py --execute

What this deletes:
  - Test users (identified by email pattern — see TEST_EMAIL_PATTERNS)
  - Their space memberships
  - Their pathway entitlements
  - Their access passes
  - Their event bookings
  - Their notifications
  - Payment transactions belonging to those users
  - Stale pending payment transactions (status=pending, older than 24 h)

What this NEVER deletes:
  - Users matching PROTECTED_EMAILS
  - Spaces, pathways, payment options, content, events
  - Entitlements or transactions for protected/real users
  - The Alembic migration history

Run the dry-run first and review the output before executing.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Bootstrap path so we can import app modules from the backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings

# ---------------------------------------------------------------------------
# Configuration — edit these lists before running
# ---------------------------------------------------------------------------

# Email substrings / patterns that identify test accounts (case-insensitive).
# A user is considered a test account if their email contains ANY of these strings.
TEST_EMAIL_PATTERNS = [
    "test",
    "example.com",
    ".test",
    "testbuyer",
    "testmember",
]

# These users are always protected — never deleted regardless of email pattern.
PROTECTED_EMAILS = {
    "lindsey@hilliard.net.au",
    "lindsey.wd@gmail.com",  # Lindsey's personal Gmail — keep even if contains no "test" marker
}

# Stale pending transactions older than this many hours are cancelled/deleted.
STALE_PENDING_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_test_email(email: str) -> bool:
    low = email.lower()
    if low in {e.lower() for e in PROTECTED_EMAILS}:
        return False
    return any(pat in low for pat in TEST_EMAIL_PATTERNS)


def confirm(prompt: str) -> bool:
    ans = input(f"\n{prompt} [yes/no]: ").strip().lower()
    return ans == "yes"


def run_cleanup(execute: bool) -> None:
    engine = create_engine(settings.database_url)
    mode_label = "EXECUTE" if execute else "DRY RUN"
    print(f"\n{'=' * 60}")
    print(f"  Fresh Collective — Test Data Cleanup  [{mode_label}]")
    print(f"{'=' * 60}\n")

    if execute:
        print("WARNING: This will permanently delete data from the production database.")
        print("Make sure you have a recent database backup before proceeding.\n")
        if not confirm("Are you absolutely sure you want to delete test data?"):
            print("Aborted.")
            return

    with Session(engine) as db:
        # ---------------------------------------------------------------
        # 1. Identify test users
        # ---------------------------------------------------------------
        users = db.execute(text("SELECT id, email, name, role FROM users ORDER BY email")).fetchall()

        test_users = [u for u in users if is_test_email(u.email)]
        kept_users = [u for u in users if not is_test_email(u.email)]

        print("USERS TO DELETE:")
        if test_users:
            for u in test_users:
                print(f"  [{u.role:6}] {u.email}  (id={u.id}, name={u.name})")
        else:
            print("  (none)")

        print("\nUSERS TO KEEP:")
        for u in kept_users:
            print(f"  [{u.role:6}] {u.email}  (id={u.id})")

        test_user_ids = [u.id for u in test_users]

        if not test_user_ids:
            print("\nNo test users found. Checking for stale pending transactions only.")

        # ---------------------------------------------------------------
        # 2. Gather dependent records for test users
        # ---------------------------------------------------------------
        def count_for_users(table: str, user_col: str) -> int:
            if not test_user_ids:
                return 0
            placeholders = ", ".join(f":u{i}" for i in range(len(test_user_ids)))
            params = {f"u{i}": uid for i, uid in enumerate(test_user_ids)}
            row = db.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {user_col} IN ({placeholders})"),
                params,
            ).fetchone()
            return row[0] if row else 0

        def fetch_ids_for_users(table: str, user_col: str) -> list[str]:
            if not test_user_ids:
                return []
            placeholders = ", ".join(f":u{i}" for i in range(len(test_user_ids)))
            params = {f"u{i}": uid for i, uid in enumerate(test_user_ids)}
            rows = db.execute(
                text(f"SELECT id FROM {table} WHERE {user_col} IN ({placeholders})"),
                params,
            ).fetchall()
            return [r[0] for r in rows]

        txn_ids = fetch_ids_for_users("payment_transactions", "payer_user_id")
        ent_ids = fetch_ids_for_users("pathway_entitlements", "user_id")
        pass_ids = fetch_ids_for_users("access_passes", "user_id")
        booking_ids = fetch_ids_for_users("event_bookings", "user_id")
        notif_ids = fetch_ids_for_users("notifications", "user_id")
        membership_ids = fetch_ids_for_users("space_memberships", "user_id")

        print(f"\nRECORDS THAT WILL BE DELETED (for test users):")
        print(f"  payment_transactions   : {len(txn_ids)}")
        print(f"  pathway_entitlements   : {len(ent_ids)}")
        print(f"  access_passes          : {len(pass_ids)}")
        print(f"  event_bookings         : {len(booking_ids)}")
        print(f"  notifications          : {len(notif_ids)}")
        print(f"  space_memberships      : {len(membership_ids)}")

        # ---------------------------------------------------------------
        # 3. Identify stale pending transactions (from test users or all)
        # ---------------------------------------------------------------
        stale_cutoff = datetime.utcnow() - timedelta(hours=STALE_PENDING_HOURS)
        stale_rows = db.execute(
            text("""
                SELECT id, payer_user_id, gross_amount_cents, provider_checkout_session_id, created_at
                FROM payment_transactions
                WHERE status = 'pending'
                  AND created_at < :cutoff
            """),
            {"cutoff": stale_cutoff},
        ).fetchall()

        # Exclude any stale pending txns that belong to protected/real users
        protected_ids_set = {u.id for u in kept_users}
        stale_to_cancel = [r for r in stale_rows if r.payer_user_id not in protected_ids_set]
        stale_for_real_users = [r for r in stale_rows if r.payer_user_id in protected_ids_set]

        if stale_to_cancel:
            print(f"\nSTALE PENDING TRANSACTIONS TO CANCEL (>{STALE_PENDING_HOURS}h, test users only):")
            for r in stale_to_cancel:
                print(f"  id={r.id}  session={r.provider_checkout_session_id or 'N/A'}  created={r.created_at}")
        else:
            print(f"\nNo stale pending transactions for test users found.")

        if stale_for_real_users:
            print(f"\nSTALE PENDING TRANSACTIONS FOR REAL USERS (skipped — review manually):")
            for r in stale_for_real_users:
                print(f"  id={r.id}  payer={r.payer_user_id}  created={r.created_at}")

        # ---------------------------------------------------------------
        # 4. Summary
        # ---------------------------------------------------------------
        total_deletions = (
            len(test_user_ids)
            + len(txn_ids)
            + len(ent_ids)
            + len(pass_ids)
            + len(booking_ids)
            + len(notif_ids)
            + len(membership_ids)
        )
        total_cancellations = len(stale_to_cancel)

        print(f"\n{'─' * 60}")
        print(f"  TOTAL rows to delete    : {total_deletions}")
        print(f"  TOTAL txns to cancel    : {total_cancellations}")
        print(f"{'─' * 60}")

        if not execute:
            print("\nDRY RUN complete — no changes made.")
            print("Re-run with --execute to apply deletions.")
            return

        # ---------------------------------------------------------------
        # 5. Execute deletions (in dependency order)
        # ---------------------------------------------------------------
        now = datetime.utcnow()

        def delete_by_ids(table: str, ids: list[str], label: str) -> None:
            if not ids:
                return
            for i, chunk in enumerate(_chunks(ids, 100)):
                placeholders = ", ".join(f":id{j}" for j in range(len(chunk)))
                params = {f"id{j}": v for j, v in enumerate(chunk)}
                db.execute(text(f"DELETE FROM {table} WHERE id IN ({placeholders})"), params)
            print(f"  deleted {len(ids)} rows from {table}  [{label}]")

        def _chunks(lst: list, n: int):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]

        print("\nDeleting records...")

        # Cancel stale pending transactions before anything else
        for r in stale_to_cancel:
            db.execute(
                text("""
                    UPDATE payment_transactions
                    SET status = 'cancelled', payout_status = 'not_applicable', updated_at = :now
                    WHERE id = :id
                """),
                {"id": r.id, "now": now},
            )
        if stale_to_cancel:
            print(f"  cancelled {len(stale_to_cancel)} stale pending transactions")

        # Nullify entitlement_id FK on payment_transactions before deleting entitlements
        if ent_ids:
            placeholders = ", ".join(f":e{i}" for i in range(len(ent_ids)))
            params = {f"e{i}": v for i, v in enumerate(ent_ids)}
            db.execute(
                text(f"UPDATE payment_transactions SET entitlement_id = NULL WHERE entitlement_id IN ({placeholders})"),
                params,
            )

        # Delete in dependency order
        delete_by_ids("notifications", notif_ids, "test users")
        delete_by_ids("event_bookings", booking_ids, "test users")
        delete_by_ids("access_passes", pass_ids, "test users")
        delete_by_ids("pathway_entitlements", ent_ids, "test users")
        delete_by_ids("payment_transactions", txn_ids, "test users")
        delete_by_ids("space_memberships", membership_ids, "test users")
        delete_by_ids("users", test_user_ids, "test users")

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"  Cleanup complete. {total_deletions} rows deleted, {total_cancellations} transactions cancelled.")
        print(f"{'=' * 60}\n")

        # ---------------------------------------------------------------
        # 6. Verification summary
        # ---------------------------------------------------------------
        remaining_users = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
        remaining_txns = db.execute(text("SELECT COUNT(*) FROM payment_transactions")).scalar()
        remaining_ents = db.execute(text("SELECT COUNT(*) FROM pathway_entitlements")).scalar()
        remaining_passes = db.execute(text("SELECT COUNT(*) FROM access_passes")).scalar()

        print("POST-CLEANUP COUNTS:")
        print(f"  users                  : {remaining_users}")
        print(f"  payment_transactions   : {remaining_txns}")
        print(f"  pathway_entitlements   : {remaining_ents}")
        print(f"  access_passes          : {remaining_passes}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove test data before go-live.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete records (default is dry-run — shows plan only).",
    )
    args = parser.parse_args()
    run_cleanup(execute=args.execute)
