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

# ruff: noqa: E402
from app.core.database import SessionLocal
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.finite_plan_lifecycle import sweep_expired_grace_plans


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)


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
    sys.exit(main())
