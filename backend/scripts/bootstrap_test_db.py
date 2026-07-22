"""
Bootstrap the fc_test database from fc_prod's *schema only*.

Why this exists: alembic migration 001 assumes the `users` table already
exists (early in the project's life the schema was created via
`Base.metadata.create_all()` and alembic was started at "add role to
users"). Consequently a raw `alembic upgrade head` cannot bring an
empty DB to `head` on its own.

This script uses `pg_dump --schema-only` on fc_prod — a read-only
operation that briefly acquires shared locks but never writes — to copy
the full schema plus the alembic_version row into fc_test. After this
runs, `alembic upgrade head` against fc_test is a normal forward walk
from whatever revision fc_prod is at.

Guards:
  - Refuses to run if the target DB is not fc_test (or another *_test DB).
  - Refuses to touch anything but localhost.
  - Never writes to fc_prod. `pg_dump --schema-only` is read-only.

Usage:
  cd backend
  .venv/bin/python3 scripts/bootstrap_test_db.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _load_env() -> str:
    if not ENV_FILE.exists():
        raise RuntimeError(".env not found — cannot resolve DATABASE_URL")
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DATABASE_URL not set in .env")


def _split_url(url: str) -> tuple[str, str, str, str, str]:
    # postgresql://user:pass@host:port/db  → components
    assert url.startswith("postgresql://"), f"unexpected URL scheme: {url}"
    body = url[len("postgresql://"):]
    userpass, _, hostportdb = body.partition("@")
    user, _, pw = userpass.partition(":")
    hostport, _, db = hostportdb.partition("/")
    host, _, port = hostport.partition(":")
    return user, pw, host, port or "5432", db


def main() -> int:
    prod_url = _load_env()
    user, pw, host, port, prod_db = _split_url(prod_url)

    if host not in ("localhost", "127.0.0.1", "::1"):
        print(f"ERROR: refuse to run against non-local host {host!r}", file=sys.stderr)
        return 1

    test_db = os.environ.get("TEST_DB_NAME", "fc_test")
    if not test_db.endswith("_test"):
        print(f"ERROR: target DB {test_db!r} must end with '_test'", file=sys.stderr)
        return 1
    if test_db == prod_db:
        print("ERROR: target and source DBs must not be equal", file=sys.stderr)
        return 1

    env = {**os.environ, "PGPASSWORD": pw}

    # 1. Verify test DB exists and is empty (or nearly so).
    print(f"→ Verifying target DB '{test_db}' exists and is safe to load…")
    check = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", test_db,
         "-tAc", "SELECT COUNT(*) FROM information_schema.tables "
                 "WHERE table_schema='public'"],
        env=env, capture_output=True, text=True, check=True,
    )
    existing = int(check.stdout.strip() or "0")
    if existing > 0:
        print(f"  '{test_db}' already has {existing} tables in public schema.")
        answer = input("  Wipe them and re-load from prod schema? [yes/NO]: ").strip().lower()
        if answer != "yes":
            print("  Aborted.")
            return 1
        print(f"→ Dropping and recreating public schema on {test_db}…")
        subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", test_db,
             "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
            env=env, check=True,
        )

    # 2. Dump prod schema (read-only) and pipe into test.
    print(f"→ pg_dump --schema-only '{prod_db}' → psql '{test_db}' …")
    dump = subprocess.Popen(
        ["pg_dump", "-h", host, "-p", port, "-U", user, "--schema-only",
         "--no-owner", "--no-privileges", prod_db],
        env=env, stdout=subprocess.PIPE,
    )
    load = subprocess.Popen(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", test_db,
         "--set", "ON_ERROR_STOP=on", "-q"],
        env=env, stdin=dump.stdout,
    )
    dump.stdout.close()  # allow dump to receive SIGPIPE if load exits
    load.wait()
    dump.wait()
    if dump.returncode != 0 or load.returncode != 0:
        print(f"ERROR: pg_dump exit={dump.returncode}, psql exit={load.returncode}",
              file=sys.stderr)
        return 2

    # 3. `pg_dump --schema-only` creates the alembic_version *table* but
    #    not the row that records the current revision. Copy that single
    #    row across so the test DB knows where to resume from.
    prod_ver = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", prod_db,
         "-tAc", "SELECT version_num FROM alembic_version"],
        env=env, capture_output=True, text=True, check=True,
    )
    prod_rev = prod_ver.stdout.strip()
    if not prod_rev:
        print("WARNING: fc_prod has no alembic_version row — nothing to stamp.")
    else:
        subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", test_db,
             "-c", f"DELETE FROM alembic_version; "
                   f"INSERT INTO alembic_version(version_num) VALUES ('{prod_rev}');"],
            env=env, check=True, capture_output=True,
        )
        print(f"→ Stamped {test_db} at alembic version {prod_rev} (matches {prod_db}).")

    print(f"\n✓ {test_db} now mirrors {prod_db}'s schema. Run alembic upgrade "
          f"head next to apply any newer migrations (e.g. 080).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
