"""
Dev-only script — resets an existing local user's password, or creates a
brand-new local test user.

This script CAN silently overwrite an existing account's password. Prior
misuse (a headless verification run that reset a real user's password
without warning) is the reason for the guard rails below.

USAGE — reset an existing account:

    .venv/bin/python3 scripts/reset_dev_user_password.py \\
        --email user@example.com --confirm

USAGE — reset an admin account (extra safety flag required):

    .venv/bin/python3 scripts/reset_dev_user_password.py \\
        --email admin@example.com --confirm --allow-admin

USAGE — create a new user if the email does not exist:

    .venv/bin/python3 scripts/reset_dev_user_password.py \\
        --email newuser@example.com --confirm --create-if-missing \\
        [--name "Display Name"] [--role learner|creator|admin]

The password is prompted for interactively via getpass — it is NEVER
accepted on the command line and is NEVER echoed or logged.

Additional guards:
  - DATABASE_URL must point to localhost / 127.0.0.1 / ::1
  - --confirm is mandatory (there is no "just run it" shortcut)
  - The default TARGET_EMAIL has been removed; --email is required
  - Existing admin accounts require --allow-admin in addition to --confirm
  - New users default to role='learner' — creator/admin roles must be opted into
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Guard: refuse to run if DATABASE_URL looks like a production host
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

db_url = ""
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            db_url = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

if not db_url:
    db_url = os.environ.get("DATABASE_URL", "")

if not db_url:
    print("ERROR: DATABASE_URL not found in .env or environment.", file=sys.stderr)
    sys.exit(1)

SAFE_HOSTS = ("localhost", "127.0.0.1", "::1")
if not any(h in db_url for h in SAFE_HOSTS):
    print(
        "ERROR: DATABASE_URL does not point to localhost. Refusing to run.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reset_dev_user_password.py",
        description=(
            "Reset (or create) a local dev user's password. Requires --email "
            "and --confirm. Existing admins additionally require --allow-admin. "
            "Passwords are prompted interactively; never accepted on the CLI."
        ),
    )
    p.add_argument(
        "--email",
        required=True,
        help="Exact email of the target account (case-sensitive as stored).",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required. Confirms you understand this will replace the existing "
            "password hash irreversibly."
        ),
    )
    p.add_argument(
        "--allow-admin",
        action="store_true",
        help="Required when the target account has role='admin'.",
    )
    p.add_argument(
        "--create-if-missing",
        action="store_true",
        help="Create a new user when --email does not exist. Off by default.",
    )
    p.add_argument(
        "--name",
        default=None,
        help="Display name when creating a new user. Ignored for existing users.",
    )
    p.add_argument(
        "--role",
        choices=("learner", "creator", "admin"),
        default="learner",
        help="Role when creating a new user. Defaults to 'learner'.",
    )
    return p


args = build_parser().parse_args()

target_email: str = args.email.strip()
if not target_email or "@" not in target_email:
    print("ERROR: --email must be a valid email address.", file=sys.stderr)
    sys.exit(2)

if not args.confirm:
    print(
        "ERROR: --confirm is required. This script will replace an existing "
        "password hash irreversibly; re-run with --confirm to proceed.",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Look up the target account BEFORE prompting for a password. This lets us
# refuse admin resets, and describe exactly what will happen, before the
# operator even types the new password.
# ---------------------------------------------------------------------------
import psycopg2  # noqa: E402

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute(
    "SELECT id, name, role FROM users WHERE email = %s",
    (target_email,),
)
row = cur.fetchone()

if row is None and not args.create_if_missing:
    print(
        f"ERROR: no user found with email '{target_email}'.\n"
        f"Re-run with --create-if-missing to create a new user with this email.",
        file=sys.stderr,
    )
    cur.close()
    conn.close()
    sys.exit(3)

if row is not None:
    _user_id, existing_name, existing_role = row
    print(f"\nTarget account exists:")
    print(f"  email : {target_email}")
    print(f"  name  : {existing_name}")
    print(f"  role  : {existing_role}")
    print(
        "\nWARNING: proceeding will REPLACE the current password hash on this\n"
        "account. Any existing password will stop working. There is no undo.\n"
    )
    if existing_role == "admin" and not args.allow_admin:
        print(
            "ERROR: this account has role='admin'. Re-run with --allow-admin "
            "in addition to --confirm to reset an admin account.",
            file=sys.stderr,
        )
        cur.close()
        conn.close()
        sys.exit(4)
else:
    print(f"\nNo existing user with email '{target_email}'.")
    print(f"Will CREATE a new user:")
    print(f"  email : {target_email}")
    print(f"  name  : {args.name or target_email.split('@')[0]}")
    print(f"  role  : {args.role}")
    if args.role == "admin" and not args.allow_admin:
        print(
            "ERROR: creating an admin account requires --allow-admin.",
            file=sys.stderr,
        )
        cur.close()
        conn.close()
        sys.exit(4)


# ---------------------------------------------------------------------------
# Prompt for the new password interactively (never via CLI arg).
# ---------------------------------------------------------------------------
new_password = getpass.getpass("New password (input hidden): ")
if len(new_password) < 8:
    print("ERROR: password must be at least 8 characters.", file=sys.stderr)
    cur.close()
    conn.close()
    sys.exit(2)

confirm_password = getpass.getpass("Confirm new password: ")
if new_password != confirm_password:
    print("ERROR: passwords did not match.", file=sys.stderr)
    cur.close()
    conn.close()
    sys.exit(2)


# ---------------------------------------------------------------------------
# Hash + apply
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT))
from app.core.security import hash_password  # noqa: E402

new_hash = hash_password(new_password)
# Overwrite the plaintext local so it never lingers in memory longer than
# strictly necessary. Not a full defence, but a good habit.
new_password = ""
confirm_password = ""

if row is not None:
    cur.execute(
        "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE email = %s",
        (new_hash, target_email),
    )
    conn.commit()
    print(f"\n✓ Password reset for existing user: {target_email}")
else:
    import uuid  # local import — only needed on the create path
    new_id = str(uuid.uuid4())
    display_name = args.name or target_email.split("@")[0]
    cur.execute(
        """
        INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (new_id, target_email, display_name, new_hash, args.role),
    )
    conn.commit()
    print(
        f"\n✓ Created new user: {target_email} (role={args.role})\n"
        f"  id: {new_id}"
    )

cur.close()
conn.close()
print("Done. The new password is now active.")
