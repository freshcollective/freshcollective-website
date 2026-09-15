#!/usr/bin/env python
"""Read-only production audit for the Creator Plans workstream.

Two facts we need before implementing the missing-plan guard and the
one-active-plan unique index:

  A. Every row in ``creator_plans`` — name, slug, monthly_price_cents,
     transaction_fee_basis_points, is_active. Confirms which of the
     seeded plans currently exist in prod, whether any admin-time
     additions or edits have happened, and whether any 0% plan we can
     reuse for Lindsey's Founding Creator is already present.

  B. Any creator with more than one active/trialing
     CreatorSubscription row. Blocks the partial UNIQUE index in the
     forthcoming migration if any exist — Lindsey needs to resolve
     each duplicate by hand before we lock the invariant in.

Safety (mirrors ``scripts/audit_local_vs_prod.py``):

  * SELECT-only. No INSERT / UPDATE / DELETE / DDL anywhere in this
    file. If a future change needs to write, add it elsewhere.
  * Refuses to run if PROD_DATABASE_URL is missing or points at the
    same host+db as DATABASE_URL (so an accidental invocation with
    only ``.env`` populated hits nothing dangerous).
  * Prints only the sanitised host+db of the connection it's using,
    never the credentials.

Usage:
    cd backend
    PROD_DATABASE_URL="postgresql://..." .venv/bin/python \\
        scripts/audit_creator_plans_prod.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:
    pass

import app.main  # noqa: F401,E402 — prime SQLAlchemy registry

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402


def _sanitised_url(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.username or '?'}@{host}{port}{p.path}"


def _same_db(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname, pa.port, pa.path) == (pb.hostname, pb.port, pb.path)


def main() -> int:
    prod_url = os.environ.get("PROD_DATABASE_URL")
    if not prod_url:
        print("ERROR: PROD_DATABASE_URL not set.", file=sys.stderr)
        return 2

    local_url = os.environ.get("DATABASE_URL", "")
    if local_url and _same_db(prod_url, local_url):
        print(
            "ERROR: PROD_DATABASE_URL resolves to the same host+db as "
            "DATABASE_URL — refusing to run.",
            file=sys.stderr,
        )
        return 2

    print(f"Connecting (read-only) to: {_sanitised_url(prod_url)}")

    engine = create_engine(prod_url, future=True, pool_pre_ping=True)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session: Session = Session_()

    try:
        # --------------------------------------------------------------
        # A. Current CreatorPlans
        # --------------------------------------------------------------
        print("\n=== CreatorPlans (production) ===")
        rows = session.execute(text(
            """
            SELECT id, slug, name, monthly_price_cents,
                   transaction_fee_basis_points, currency, is_active,
                   created_at
            FROM creator_plans
            ORDER BY monthly_price_cents, slug
            """
        )).all()
        if not rows:
            print("  (none)")
        else:
            for r in rows:
                fee_pct = r.transaction_fee_basis_points / 100.0
                price_dollars = r.monthly_price_cents / 100.0
                active = "active" if r.is_active else "inactive"
                print(
                    f"  {r.slug:20s} | {r.name:24s} | "
                    f"${price_dollars:>7.2f} {r.currency} / mo | "
                    f"{fee_pct:>5.2f}% fee | {active}"
                )

        # --------------------------------------------------------------
        # B. Duplicate active/trialing subscriptions per creator
        # --------------------------------------------------------------
        print("\n=== Duplicate active/trialing CreatorSubscriptions ===")
        dups = session.execute(text(
            """
            SELECT user_id, COUNT(*) AS n_active
            FROM creator_subscriptions
            WHERE status IN ('active', 'trialing')
            GROUP BY user_id
            HAVING COUNT(*) > 1
            ORDER BY n_active DESC, user_id
            """
        )).all()
        if not dups:
            print("  (none — partial UNIQUE index will apply cleanly)")
        else:
            print(
                f"  BLOCKING: {len(dups)} creator(s) currently hold "
                f"multiple active/trialing subscriptions. Resolve by "
                f"hand before the migration is run."
            )
            for d in dups:
                print(f"    user_id={d.user_id}  active_rows={d.n_active}")

        # --------------------------------------------------------------
        # C. Total active/trialing subscriptions (context)
        # --------------------------------------------------------------
        total_subs = session.execute(text(
            """
            SELECT COUNT(*) FROM creator_subscriptions
            WHERE status IN ('active', 'trialing')
            """
        )).scalar_one()
        total_creators = session.execute(text(
            "SELECT COUNT(*) FROM users WHERE role = 'creator'"
        )).scalar_one()
        print(f"\n  Total active/trialing subs: {total_subs}")
        print(f"  Total users with role='creator': {total_creators}")

        # --------------------------------------------------------------
        # D. Distribution of status values (context)
        # --------------------------------------------------------------
        print("\n=== CreatorSubscription status distribution ===")
        by_status = Counter()
        for row in session.execute(text(
            "SELECT status FROM creator_subscriptions"
        )).all():
            by_status[row.status] += 1
        for status, n in sorted(by_status.items()):
            print(f"  {status:12s} {n}")

    finally:
        session.close()
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
