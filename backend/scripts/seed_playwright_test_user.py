"""
Dev-only script — seeds the dedicated Playwright test account.

The Playwright test user is a fixed, clearly non-production account used
by automated browser verification. It exists so that headless testing
never touches — and never needs to touch — a real user record.

Identity:
  email     : playwright-test@fresh-collective.test
  role      : learner   (minimum permissions by default)
  password  : chosen interactively by the operator; hash stored via the
              real project helper. Never accepted on the CLI.

Usage:
  cd backend
  .venv/bin/python3 scripts/seed_playwright_test_user.py

Environment variables (advanced, opt-in only):
  PLAYWRIGHT_TEST_EMAIL   override the fixed email (must end in .test)
  PLAYWRIGHT_TEST_ROLE    'learner' | 'creator' — never 'admin'

This script:
  - refuses to run against a non-localhost DATABASE_URL
  - refuses any email that doesn't clearly look like a test account
    (must contain '.test' or 'example.com' or 'playwright')
  - refuses role='admin' outright
  - prompts for the password interactively (never via CLI)
  - is idempotent: re-running with the same email updates the password
    on the same test row (no duplicates, no cascading records)
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Local DB guard (same pattern as reset_dev_user_password.py)
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
# Identity — fixed unless overridden by env vars (which are validated).
# ---------------------------------------------------------------------------
DEFAULT_EMAIL = "playwright-test@fresh-collective.test"
DEFAULT_NAME  = "Playwright Test User"

email = os.environ.get("PLAYWRIGHT_TEST_EMAIL", DEFAULT_EMAIL).strip().lower()
role  = os.environ.get("PLAYWRIGHT_TEST_ROLE", "learner").strip().lower()

TEST_MARKERS = (".test", "example.com", "playwright")
if not any(m in email for m in TEST_MARKERS):
    print(
        f"ERROR: '{email}' does not look like a test address. Test emails must "
        f"contain one of: {', '.join(TEST_MARKERS)}.",
        file=sys.stderr,
    )
    sys.exit(2)

if role == "admin":
    print(
        "ERROR: role='admin' is not permitted for the Playwright test user. "
        "Use role='learner' (default) or role='creator' if creator flows must "
        "be tested.",
        file=sys.stderr,
    )
    sys.exit(2)

if role not in ("learner", "creator"):
    print(f"ERROR: invalid role '{role}'. Must be 'learner' or 'creator'.", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Prompt for password interactively.
# ---------------------------------------------------------------------------
print("\nSeeding Playwright test account:")
print(f"  email : {email}")
print(f"  role  : {role}")
print()
password = getpass.getpass("Set test-user password (input hidden): ")
if len(password) < 8:
    print("ERROR: password must be at least 8 characters.", file=sys.stderr)
    sys.exit(2)
confirm = getpass.getpass("Confirm password: ")
if password != confirm:
    print("ERROR: passwords did not match.", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Hash + upsert
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT))
from app.core.security import hash_password  # noqa: E402

password_hash = hash_password(password)
password = ""
confirm = ""

import psycopg2  # noqa: E402
import uuid      # noqa: E402

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("SELECT id, role FROM users WHERE email = %s", (email,))
row = cur.fetchone()

if row is not None:
    _user_id, existing_role = row
    if existing_role != role:
        print(
            f"NOTE: existing test user role is '{existing_role}', keeping it as-is. "
            f"To change roles, update the record manually.",
        )
    cur.execute(
        "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE email = %s",
        (password_hash, email),
    )
    conn.commit()
    print(f"\n✓ Playwright test account password updated: {email}")
else:
    new_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (new_id, email, DEFAULT_NAME, password_hash, role),
    )
    conn.commit()
    print(f"\n✓ Playwright test account created: {email} (role={role})")

cur.close()
conn.close()
print("Done. Automated tests may now log in with this account.")
