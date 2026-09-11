"""Sweep stale RefundOperations that never received their webhook.

Runs a single reconciliation pass. Two categories:

* ``in_flight`` older than ``STALE_IN_FLIGHT_SECONDS`` — server likely
  crashed between inserting the row and persisting Stripe's outcome.
  Replayed via same idempotency-key (Phase A, <=24h) or metadata
  search (Phase B, >24h). Never generates a fresh Stripe idempotency
  key — always the one bound to the RefundOperation.id.

* ``accepted`` older than ``STALE_ACCEPTED_SECONDS`` — Stripe accepted
  the refund but the ``charge.refunded`` webhook was lost or delayed.
  Recovered via ``stripe.Refund.retrieve`` and force-sync of the
  ledger through the same handler the webhook would have used.
  Monotonic guards protect against a late webhook double-write.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/fc_refund_reconciler.py [--dry-run]

Exit code:
    0 on success (even when zero operations reconciled).
    1 on unexpected error.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
# Force full model registry load (see fip3_reconcile_grace.py for rationale).
import app.main  # noqa: F401
from app.core.database import SessionLocal
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationTerminalStatus,
)
from app.services import refund_reconciliation as _rec


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dry_run:
            now = datetime.utcnow()
            stale_in_flight_cutoff = (
                now - timedelta(seconds=_rec.STALE_IN_FLIGHT_SECONDS)
            )
            stale_accepted_cutoff = (
                now - timedelta(seconds=_rec.STALE_ACCEPTED_SECONDS)
            )
            in_flight = (
                db.query(RefundOperation)
                .filter(
                    RefundOperation.terminal_status
                    == RefundOperationTerminalStatus.in_flight.value,
                    RefundOperation.created_at < stale_in_flight_cutoff,
                )
                .all()
            )
            accepted = (
                db.query(RefundOperation)
                .filter(
                    RefundOperation.terminal_status
                    == RefundOperationTerminalStatus.accepted.value,
                    RefundOperation.updated_at < stale_accepted_cutoff,
                )
                .all()
            )
            print(
                f"[dry-run] {len(in_flight)} stale in_flight, "
                f"{len(accepted)} stale accepted at {now}"
            )
            for op in in_flight:
                print(
                    f"  in_flight op={op.id} txn={op.payment_transaction_id} "
                    f"age={(now - op.created_at).total_seconds():.0f}s"
                )
            for op in accepted:
                print(
                    f"  accepted op={op.id} txn={op.payment_transaction_id} "
                    f"stripe_refund={op.stripe_refund_id} "
                    f"age={(now - op.updated_at).total_seconds():.0f}s"
                )
            return 0

        summary = _rec.sweep_stale_operations(db)
        print(
            f"refund reconciler: "
            f"in_flight reconciled={summary['in_flight_reconciled']} "
            f"transient={summary['in_flight_transient']} | "
            f"accepted reconciled={summary['accepted_reconciled']} "
            f"transient={summary['accepted_transient']}"
        )
        return 0
    except Exception:
        logging.exception("refund reconcile failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
