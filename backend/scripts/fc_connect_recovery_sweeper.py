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
    capture_job_summary,
    flush_sentry,
    init_sentry,
)

init_sentry("fc-connect-recovery-sweeper")

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


logger = logging.getLogger("fc_connect_recovery_sweeper")

#: Render-only — see the transfer sweeper, and
#: ``RENDER_ONLY_LOGGER_SUFFIX`` in ``app/core/observability.py``.
id_logger = logging.getLogger("fc_connect_recovery_sweeper.ids")


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


def report_partial_failures(report) -> str | None:
    """One Sentry event for money a creator owes FC that could not be
    taken back. Returns the event id, or ``None`` when there is nothing
    to report.

    ``warning`` rather than ``error``, and that is a judgement about
    the mechanism rather than about the amount: nothing is ever written
    off here, so a row past the attention threshold is still in the
    queue and still backing off towards its next attempt. What it needs
    is a person choosing to intervene, which is what reporting it is
    for.

    ``outstanding_cents`` is an aggregate across the pass — no row, no
    creator, no Stripe object.
    """
    if not report.needs_attention:
        return None
    return capture_job_summary(
        "connect recovery sweep still owed after repeated attempts",
        level="warning",
        needs_attention=len(report.needs_attention),
        outstanding_cents=report.outstanding_cents,
        attempted=report.attempted,
        still_retryable=report.still_retryable,
        recovery_required=report.recovery_required,
        cooling_off=report.cooling_off,
    )


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

        # Ids in the Render log, counts in Sentry — see the transfer
        # sweeper for why this is the Render-only logger at WARNING.
        if report.needs_attention:
            id_logger.warning(
                "still owed after repeated attempts: %s",
                ", ".join(report.needs_attention),
            )

        report_partial_failures(report)
        return 0
    except Exception:
        logger.exception("connect recovery sweep failed")
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
