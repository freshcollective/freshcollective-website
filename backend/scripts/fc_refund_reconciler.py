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

init_sentry("fc-refund-reconciler")

# ruff: noqa: E402
# Force full SQLAlchemy model registry load WITHOUT importing app.main.
# app.main pulls in every FastAPI router → every service → every model
# but also every unrelated web-app dependency (uploads/R2, comms
# webhooks, auth, etc.) which forces the reconciler to satisfy web-only
# runtime config (R2 credentials, JWT_SECRET). We only need the models
# so SQLAlchemy can resolve string-referenced relationships when
# RefundOperation and its FKs are queried.
#
# List mirrors backend/alembic/env.py so any model added to the alembic
# registry is also loaded here.
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
import app.comms.models  # noqa: F401

from app.core.database import SessionLocal
from app.models.refund_operation import (
    RefundOperation,
    RefundOperationTerminalStatus,
)
from app.services import refund_reconciliation as _rec


def report_partial_failures(summary: dict) -> str | None:
    """One Sentry event for a pass that left a refund's outcome
    unknown. Returns the event id, or ``None`` when every operation
    resolved.

    A transient count means Stripe could not be reached, the row was
    left exactly where it was, and the run exited 0. One run of that is
    ordinary and self-heals in fifteen minutes; the same count every
    run is a member waiting on money. Sentry groups these into one
    issue, so the *pattern* is what shows — which is the thing a
    per-run log line cannot tell you.

    ``warning``, not ``error``: the next run is the normal fix. The
    genuinely wrong states inside the sweep — an ``accepted`` operation
    with no Stripe refund id, a refund id Stripe does not recognise —
    already log at ERROR inside ``app.services.refund_reconciliation``
    and become their own issues from there. One signal per condition.
    """
    unresolved = (
        summary["in_flight_transient"] + summary["accepted_transient"]
    )
    if not unresolved:
        return None
    return capture_job_summary(
        "refund reconciler left operations unresolved",
        level="warning",
        in_flight_transient=summary["in_flight_transient"],
        accepted_transient=summary["accepted_transient"],
        in_flight_reconciled=summary["in_flight_reconciled"],
        accepted_reconciled=summary["accepted_reconciled"],
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

        report_partial_failures(summary)
        return 0
    except Exception:
        logging.exception("refund reconcile failed")
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
