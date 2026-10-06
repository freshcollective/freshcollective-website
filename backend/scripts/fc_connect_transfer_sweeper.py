"""Send the Connect transfers that are owed and still unsent.

One bounded pass. Picks up rows where ``payout_model = 'connect'`` and
``connect_transfer_status = 'pending'`` — a creator share whose payment has
succeeded and whose transfer has not landed yet.

The common reason a transfer is waiting is not an outage: a transfer tied to
a charge that has not settled is refused for insufficient balance, and the
identical call succeeds shortly after. Those rows stay ``pending`` and are
retried here rather than being written off.

Never touched: ``awaiting_payment`` rows (a transfer applies but is not due —
an abandoned Checkout Session lives there forever), ``manual`` rows (paid by
batch), and rows that already carry a ``provider_transfer_id``.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/fc_connect_transfer_sweeper.py [--dry-run] [--limit N]

Exit code:
    0 on success, including a pass that sent nothing.
    1 on unexpected error.
"""

from __future__ import annotations

import argparse
import logging
import sys
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

init_sentry("fc-connect-transfer-sweeper")

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
from app.services import connect_transfer_sweeper as _sweeper


logger = logging.getLogger("fc_connect_transfer_sweeper")

#: Render-only: the ``.ids`` suffix keeps these lines out of error
#: reporting entirely, breadcrumbs included. See
#: ``RENDER_ONLY_LOGGER_SUFFIX`` in ``app/core/observability.py``.
id_logger = logging.getLogger("fc_connect_transfer_sweeper.ids")


def _report_only(db, limit: int) -> int:
    rows = db.execute(
        text(
            """
            SELECT id, currency, net_creator_amount_cents, processing_fee_cents,
                   transfer_attempt_count, transfer_last_error
            FROM payment_transactions
            WHERE payout_model = 'connect'
              AND connect_transfer_status = 'pending'
              AND provider_transfer_id IS NULL
            ORDER BY created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).all()
    if not rows:
        logger.info("dry run: no transfers owed")
        return 0
    logger.info("dry run: %s transfer(s) owed", len(rows))
    for txn_id, currency, net_creator, fee, attempts, last_error in rows:
        amount = None if (net_creator is None or fee is None) else net_creator - fee
        logger.info(
            "  %s  %s  net_creator=%s fee=%s -> transfer=%s  attempts=%s%s",
            txn_id, currency, net_creator, fee,
            amount if amount is not None else "UNKNOWN (fee missing)",
            attempts,
            f"  last_error={last_error!r}" if last_error else "",
        )
    return 0


def report_partial_failures(report) -> str | None:
    """One Sentry event for a pass that finished and still left money
    unsent. Returns the event id, or ``None`` when there is nothing to
    report — which is the overwhelming majority of runs.

    This exists because the sweep can do exactly what it was built to
    do and a creator can still be unpaid at the end of it. The process
    exits 0, Render sees a healthy cron, and the only trace is a log
    line nobody is reading.

    ``failed`` is the serious half: terminal by classification, so that
    money will not move again on its own. ``needs_attention`` is still
    being retried — a slower problem, and a quieter level.
    """
    if not (report.failed or report.needs_attention):
        return None
    return capture_job_summary(
        "connect transfer sweep left transfers unsent",
        level="error" if report.failed else "warning",
        failed=report.failed,
        needs_attention=len(report.needs_attention),
        still_pending=report.still_pending,
        fee_unavailable=report.fee_unavailable,
        held_by_dispute=report.held_by_dispute,
        considered=report.considered,
        sent=report.sent,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what is owed and what would be sent; move no money",
    )
    parser.add_argument(
        "--limit", type=int, default=_sweeper.DEFAULT_BATCH_SIZE,
        help=f"transactions per pass (default {_sweeper.DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dry_run:
            return _report_only(db, args.limit)

        report = _sweeper.sweep_pending_transfers(db, limit=args.limit)
        logger.info("sweep complete: %s", report.as_log_fields())

        # The ids stay here, in the Render log, because acting on them
        # means opening those transactions. The Render-only logger is
        # what keeps them out of the summary's breadcrumb trail, and
        # WARNING is what keeps this from becoming a second issue for
        # the one condition.
        if report.needs_attention:
            id_logger.warning(
                "still owed after repeated attempts: %s",
                ", ".join(report.needs_attention),
            )

        report_partial_failures(report)
        return 0
    except Exception:
        logger.exception("connect transfer sweep failed")
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
