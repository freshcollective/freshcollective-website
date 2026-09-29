"""Retry the creator recoveries that are still outstanding.

The counterpart to ``fc_connect_transfer_sweeper.py``: that one sends money FC
owes a creator, this one gets money back that a creator owes FC after a refund
or a dispute, where the transfer reversal did not complete at the time.

Picks up rows where ``payout_model = 'connect'``, a transfer was actually sent,
``connect_recovery_state = 'required'`` and ``connect_unrecovered_amount_cents``
is still above zero. All of the arithmetic stays in the reversal service — the
cumulative target is recomputed under a row lock from stored refund and dispute
state, and only the remaining delta is reversed.

Attempts back off exponentially, because the usual reason a reversal fails is
that the creator's balance cannot cover it and that does not change minute to
minute. Nothing is ever written off: a row past the attention threshold is
reported and stays in the queue.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/fc_connect_recovery_sweeper.py [--dry-run] [--limit N]

Exit code:
    0 on success, including a pass that recovered nothing.
    1 on unexpected error.
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
# Load the model registry without importing app.main — the web app pulls in
# uploads/R2, comms and auth config this job has no use for. List mirrors
# backend/alembic/env.py.
from app.db.base import Base  # noqa: F401
import app.models.user  # noqa: F401
import app.models.sales  # noqa: F401
import app.models.platform  # noqa: F401
import app.models.creator_billing  # noqa: F401
import app.models.payment  # noqa: F401
import app.models.payment_option  # noqa: F401
import app.models.payment_option_schedule  # noqa: F401
import app.models.payment_option_grant  # noqa: F401
import app.models.access_pass  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.activity  # noqa: F401
import app.models.place  # noqa: F401
import app.models.purchase_intent  # noqa: F401
import app.models.purchase_plan  # noqa: F401
import app.models.webhook_event  # noqa: F401
import app.models.community_care  # noqa: F401
import app.models.access_grant_record  # noqa: F401
import app.models.refund_operation  # noqa: F401
import app.models.creator_payout_batch  # noqa: F401
import app.models.creator_stripe_account  # noqa: F401
import app.comms.models  # noqa: F401

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services import connect_recovery_sweeper as _sweeper


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)

logger = logging.getLogger("fc_connect_recovery_sweeper")


def _report_only(db, limit: int) -> int:
    rows = db.execute(
        text(
            """
            SELECT id, currency, transfer_amount_cents,
                   reversed_transfer_amount_cents,
                   connect_unrecovered_amount_cents,
                   reversal_attempt_count, reversal_attempted_at,
                   connect_dispute_opened_at, reversal_last_error
            FROM payment_transactions
            WHERE payout_model = 'connect'
              AND provider_transfer_id IS NOT NULL
              AND connect_recovery_state = 'required'
              AND connect_unrecovered_amount_cents > 0
              AND connect_transfer_status <> 'reversed'
            ORDER BY reversal_attempted_at ASC NULLS FIRST, created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()
    if not rows:
        logger.info("dry run: nothing outstanding")
        return 0

    now = datetime.utcnow()
    total = 0
    logger.info("dry run: %s row(s) still owed back", len(rows))
    for (
        txn_id, currency, transferred, already, outstanding,
        attempts, last_attempt, disputed_at, last_error,
    ) in rows:
        total += outstanding or 0
        if last_attempt is None:
            due = "due now (never attempted)"
        else:
            ready_at = last_attempt + _sweeper.cooldown_for(attempts or 0)
            due = "due now" if now >= ready_at else f"due {ready_at.isoformat()}"
        logger.info(
            "  %s  %s  outstanding=%s (transferred=%s reversed=%s)  attempts=%s  "
            "%s%s%s",
            txn_id, currency, outstanding, transferred, already, attempts, due,
            "  DISPUTED" if disputed_at else "",
            f"  last_error={last_error!r}" if last_error else "",
        )
    logger.info("dry run: %s total outstanding", total)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what is outstanding and when each row is next due; change nothing",
    )
    parser.add_argument(
        "--limit", type=int, default=_sweeper.DEFAULT_BATCH_SIZE,
        help=f"rows per pass (default {_sweeper.DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dry_run:
            return _report_only(db, args.limit)

        report = _sweeper.sweep_pending_recoveries(db, limit=args.limit)
        logger.info("sweep complete: %s", report.as_log_fields())
        if report.needs_attention:
            # Still owed, not abandoned.
            logger.error(
                "still owed after repeated attempts: %s",
                ", ".join(report.needs_attention),
            )
        return 0
    except Exception:
        logger.exception("connect recovery sweep failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
