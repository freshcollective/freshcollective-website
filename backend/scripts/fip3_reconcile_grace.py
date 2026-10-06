"""FIP3 operator script — sweep expired-grace finite payment plans.

Runs a single reconciliation pass and prints the outcome. Safe to
run from cron, ad-hoc, or interactively. The in-process reconciler
in ``services/finite_plan_reconciler.py`` normally handles this
every 5 minutes; this script exists so operators / CI / a future
external cron can drive the sweep independently.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/fip3_reconcile_grace.py [--dry-run]

--dry-run
    Reports the plans that would suspend without touching them.
    Useful before shipping the schema change and again after any
    incident where you want to preview state.

Exit code:
    0 on success (even when zero plans suspended).
    1 on unexpected error (never on empty result).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Logging is configured first so that the line below is actually
# emitted. Without a handler installed, Python's last-resort handler
# drops anything below WARNING — and "SENTRY_DSN is not set" is an INFO
# line that matters most on the one deploy where it is true.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

# Error reporting starts here, before the app imports below, and that
# order is deliberate: the first thing that can go wrong in a cron is
# ``Settings`` refusing to construct, and that happens at import time.
# ``app.core.observability`` imports nothing from ``app``, so calling it
# first cannot affect import order or reintroduce a cycle.
#
# A missing ``SENTRY_DSN`` makes this a clean no-op, which is how every
# local and ad-hoc run behaves.
from app.core.observability import (  # noqa: E402
    flush_sentry,
    init_sentry,
)

init_sentry("fc-fip3-grace-reconciler")

# ruff: noqa: E402
# Force full model registry load so SQLAlchemy can resolve string-referenced
# relationships when this script runs standalone outside the FastAPI process.
# Without this, importing PurchasePlan alone leaves adjacent mappers
# (e.g. SpaceMembership → User) unresolved and the first db.query raises
# InvalidRequestError. Importing app.main is a side-effect import — it does
# NOT start uvicorn or the lifespan background loops (those only run when
# an ASGI server invokes the app), and does NOT mutate reconciliation logic.
import app.main  # noqa: F401
from app.core.database import SessionLocal
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.finite_plan_lifecycle import sweep_expired_grace_plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        if args.dry_run:
            due = (
                db.query(PurchasePlan)
                .filter(
                    PurchasePlan.status == PurchasePlanStatus.payment_problem,
                    PurchasePlan.grace_expires_at.is_not(None),
                    PurchasePlan.grace_expires_at <= now,
                )
                .all()
            )
            print(f"[dry-run] {len(due)} plan(s) with expired grace at {now}:")
            for p in due:
                print(
                    f"  plan={p.id} member={p.member_user_id} "
                    f"grace_expires_at={p.grace_expires_at} "
                    f"invoice={p.last_failed_invoice_id}"
                )
            return 0

        outcomes = sweep_expired_grace_plans(db, now=now)
        print(f"suspended {len(outcomes)} plan(s):")
        for o in outcomes:
            print(
                f"  plan={o.plan_id}  "
                f"entitlements suspended={len(o.suspended_entitlement_ids)} "
                f"preserved={len(o.preserved_entitlement_ids)}  "
                f"passes suspended={len(o.suspended_access_pass_ids)} "
                f"preserved={len(o.preserved_access_pass_ids)}"
            )
        return 0
    except Exception:
        logging.exception("reconcile failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    # The flush is in a ``finally`` so it runs on the failure path too,
    # which is the path whose event matters most. It is bounded and
    # swallows its own errors, so it cannot change the exit code — a
    # Sentry outage must never turn a good run into a failed cron.
    try:
        raise SystemExit(main())
    finally:
        flush_sentry()
