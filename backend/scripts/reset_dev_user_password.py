"""
Dev-only script — resets (or creates) a local user's password.

Usage:
  cd backend
  .venv/bin/python3 scripts/reset_dev_user_password.py

Never run against production. Never prints password hashes.
"""

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
    print("ERROR: DATABASE_URL not found in .env or environment.")
    sys.exit(1)

SAFE_HOSTS = ("localhost", "127.0.0.1", "::1")
is_local = any(h in db_url for h in SAFE_HOSTS)
if not is_local:
    print("ERROR: DATABASE_URL does not point to localhost. Refusing to run.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_EMAIL = "lindsey@hilliard.net.au"
TARGET_ROLE  = "admin"
TARGET_NAME  = "Lindsey Hilliard"

# Import dev password from arg or prompt
if len(sys.argv) > 1:
    new_password = sys.argv[1]
else:
    import getpass
    new_password = getpass.getpass(f"New password for {TARGET_EMAIL}: ")

if len(new_password) < 8:
    print("ERROR: Password must be at least 8 characters.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Hash the password using the real project helper
# ---------------------------------------------------------------------------
# Add backend root to path so we can import app.core.security
sys.path.insert(0, str(ROOT))

from app.core.security import hash_password  # noqa: E402

new_hash = hash_password(new_password)

# ---------------------------------------------------------------------------
# Connect and upsert
# ---------------------------------------------------------------------------
import psycopg2  # noqa: E402
import uuid      # noqa: E402

conn = psycopg2.connect(db_url)
cur  = conn.cursor()

cur.execute("SELECT id, name, role FROM users WHERE email = %s", (TARGET_EMAIL,))
row = cur.fetchone()

if row:
    user_id, name, role = row
    cur.execute(
        "UPDATE users SET password_hash = %s WHERE email = %s",
        (new_hash, TARGET_EMAIL),
    )
    conn.commit()
    print(f"✓ Password reset for existing user: {TARGET_EMAIL} (role={role})")
else:
    user_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (user_id, TARGET_EMAIL, TARGET_NAME, new_hash, TARGET_ROLE),
    )
    conn.commit()
    print(f"✓ Created new user: {TARGET_EMAIL} (role={TARGET_ROLE})")

cur.close()
conn.close()
print("Done. Login with the password you just set.")
