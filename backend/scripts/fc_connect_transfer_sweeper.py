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
from datetime import datetime, timezone
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
import app.models.creator_bank_payout  # noqa: F401
import app.comms.models  # noqa: F401

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services import connect_transfer_sweeper as _sweeper
from app.services import creator_bank_payout_sync as payout_sync
from app.services import processing_fee_reconciliation as fee_recon
from app.services import stripe_connect_accounts as connect_accounts


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


def reconcile_processing_fees(db) -> str | None:
    """Fill in Stripe's processing fee on succeeded payments that lack one.

    Fresh Collective's own cost of sale, for rows the transfer path never
    prices — a sent row is out of the sweeper's reach, so without this the
    gap would never close. Writes no figure a creator can see; see
    ``services.processing_fee_reconciliation`` for what it will not touch.

    Swallows its own errors, like the reporters above. This runs after the
    money work, and a bookkeeping read that throws must not turn a sweep
    that transferred correctly into a failed cron. Keeping the handler here
    rather than in ``main`` also leaves ``main``'s only ``except`` the fatal
    one, which is what ``test_cron_observability`` requires of every script.

    Returns a Sentry event id when rows remain unpriced, otherwise ``None``.
    """
    try:
        report = fee_recon.reconcile_missing_fees(db)
    except Exception:
        logger.exception("processing fee reconciliation failed")
        return None

    if not report.unreadable:
        return None
    return capture_job_summary(
        "processing fees could not be read for some succeeded payments; "
        "Fresh Collective's cost of sale is incomplete",
        level="warning",
        rows_unpriced=len(report.unreadable),
        rows_resolved=report.resolved,
    )


def sync_bank_payouts(db) -> str | None:
    """Read each creator's actual bank payouts from Stripe.

    A Connect transfer and a bank payout are different events, and Fresh
    Collective only ever observed the first — so the furthest Creator Studio
    could honestly say was "sent to Stripe". This asks Stripe directly.

    Reuses this cron rather than adding a service: payouts are weekly, so a
    fifteen-minute lag is immaterial, and a new Render cron would mean a
    blueprint change. Every write is an upsert on Stripe's own payout id, so
    running it again — or alongside a future webhook writer — converges
    rather than duplicating.

    Swallows its own errors, like the reporters above. This runs after the
    money work and writes nothing a transfer depends on.

    Returns a Sentry event id when accounts could not be read.
    """
    try:
        report = payout_sync.sync_creator_bank_payouts(db)
    except Exception:
        logger.exception("bank payout sync failed")
        return None

    if not report.unreadable:
        return None
    # Account ids go to the Render log only, like the lists above.
    for account_id in report.unreadable:
        id_logger.warning("bank payout sync: could not read account=%s", account_id)
    return capture_job_summary(
        "bank payouts could not be read for some connected accounts",
        level="warning",
        accounts_unreadable=len(report.unreadable),
        accounts_seen=report.accounts,
        payouts_recorded=report.created + report.updated,
    )


#: Hour (UTC) whose first sweep carries the payout-schedule report.
#: UTC because Render runs crons in UTC, and a fixed hour is what makes
#: "once a day" mean the same thing every day.
DAILY_REPORT_HOUR_UTC = 2


def _is_daily_report_slot(now: datetime) -> bool:
    """True for the first sweep of the reporting hour.

    The sweeper ticks every fifteen minutes, so the opening quarter of
    one hour is one run a day.

    A sweep missed inside that window means no report that day. That is
    an acceptable trade for this particular check and not for the
    others: the straggler list is a *standing* condition that cannot
    change on its own, so a skipped day loses nothing that tomorrow
    will not say identically. Genuine failures never arrive here —
    ``set_weekly_payout_schedule`` logs those at ERROR the moment an
    account is created, which reaches Sentry independently of this
    script.
    """
    return now.hour == DAILY_REPORT_HOUR_UTC and now.minute < 15


def report_payout_schedule_stragglers(
    db, *, now: datetime | None = None,
) -> str | None:
    """Which connected accounts Stripe is not paying out weekly.

    Reported once a day, not once a sweep. The condition is static —
    nothing in the system moves an account onto weekly, so the same
    list was being re-sent every fifteen minutes (FC-API-5: ~390
    identical events in four days). Daily keeps the signal and drops
    96 events a day to one.

    Setting the schedule at account creation can fail quietly — Stripe may
    refuse the write, and the function deliberately does not raise so that a
    creator is never left without a usable account over a payout cadence.
    This is the other half of that trade: the condition is surfaced on every
    pass instead of being discovered in a Stripe invoice.

    Costs no Stripe calls. ``payout_interval`` is projected onto the account
    row by every sync, so this reads Stripe's own answer out of the database.

    Reported, never enforced, and never acted on automatically: changing a
    live payout schedule is an operator decision. Returns a Sentry event id
    when there is something to report. Swallows its own errors.
    """
    # Checked before the query, not after: on the other ninety-five
    # sweeps of the day there is nothing to decide, so there is no
    # reason to ask the database.
    if not _is_daily_report_slot(now or datetime.now(timezone.utc)):
        return None

    try:
        stragglers = connect_accounts.accounts_not_on_weekly_payouts(db)
    except Exception:
        logger.warning(
            "payout schedule check: could not list accounts", exc_info=True,
        )
        return None

    if not stragglers:
        logger.info("payout schedule check: every connected account is weekly")
        return None

    # Ids go to the Render log only, like the needs-attention list above.
    for creator_id, account_id, interval in stragglers:
        id_logger.warning(
            "payout schedule check: creator=%s account=%s interval=%r "
            "(expected weekly)", creator_id, account_id, interval,
        )
    # Counts, not values. ``capture_job_summary`` accepts ints only and
    # replaces anything else with DROPPED_NOT_A_COUNT, logging as it goes —
    # so the list of interval names this used to pass never reached Sentry
    # and produced a warning on every run. The aggregate is what tells
    # somebody to go and look; the per-account detail is already in the
    # Render log above, which is where acting on it belongs.
    daily = sum(1 for _, _, i in stragglers if i == "daily")
    unknown = sum(1 for _, _, i in stragglers if i is None)
    return capture_job_summary(
        "connected accounts are not on weekly payouts",
        level="warning",
        accounts=len(stragglers),
        on_daily=daily,
        interval_unknown=unknown,
        other_interval=len(stragglers) - daily - unknown,
    )


def _field(entry: object, name: str) -> object | None:
    """One field off a Stripe object or a plain mapping, never raising."""
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def report_balance_headroom(db) -> str | None:
    """Can Fresh Collective's balance still cover what it owes creators?

    This became worth watching when FC started absorbing Stripe's
    processing fee. A charge adds ``gross - stripe_fee`` to FC's balance
    while the transfer sends ``gross - platform_fee``, so every sale where
    the commission is smaller than Stripe's fee is funded from FC's own
    money — always for a 0% creator, and for small sales on the lower
    commission tiers. FC's balance is also swept to its bank weekly.

    Reported, never enforced. A thin balance must not stop a transfer
    being attempted: ``source_transaction`` means Stripe accepts the
    request while the charge is still settling, and ``balance_insufficient``
    is already classified retryable, so the sweeper recovers on its own
    once funds land. Gating here would turn a cash-flow wobble into unpaid
    creators.

    Returns a Sentry event id when the balance cannot cover what is owed,
    otherwise ``None``. Swallows its own errors — a Stripe read that fails
    must not fail the cron.
    """
    try:
        owed = db.execute(
            text(
                "SELECT currency, count(*), "
                "       coalesce(sum(net_creator_amount_cents), 0) "
                "FROM payment_transactions "
                "WHERE payout_model = 'connect' "
                "  AND connect_transfer_status = 'pending' "
                "GROUP BY currency"
            )
        ).fetchall()
    except Exception:
        logger.warning("balance headroom: could not total what is owed", exc_info=True)
        return None

    if not owed:
        logger.info("balance headroom: nothing owed")
        return None

    try:
        import stripe

        from app.core.config import settings

        stripe.api_key = settings.stripe_secret_key
        balance = stripe.Balance.retrieve()
        # ``balance.available`` entries are ``StripeObject``s, which support
        # attribute access but not ``.get()``; a plain dict is the other way
        # round. Read both shapes rather than assume, because getting this
        # wrong would silently disable the monitor — the whole function
        # swallows its own errors — rather than announce itself.
        available: dict[str, int] = {}
        for entry in balance.available:
            ccy = _field(entry, "currency")
            amount = _field(entry, "amount")
            if ccy is None or amount is None:
                continue
            available[str(ccy).upper()] = int(amount)
    except Exception:
        logger.warning("balance headroom: could not read the Stripe balance", exc_info=True)
        return None

    short: dict[str, int] = {}
    for currency, rows, owed_cents in owed:
        ccy = str(currency).upper()
        have = available.get(ccy, 0)
        logger.info(
            "balance headroom: %s owed=%s across %s row(s), available=%s",
            ccy, owed_cents, rows, have,
        )
        if owed_cents > have:
            short[ccy] = int(owed_cents) - have

    if not short:
        return None
    return capture_job_summary(
        "connect transfers owed exceed Fresh Collective's available balance",
        level="error",
        **{f"short_{ccy.lower()}_cents": cents for ccy, cents in short.items()},
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
        report_balance_headroom(db)

        # Both of these come after the money work and report only. Each
        # swallows its own errors, so neither can fail a sweep that
        # transferred correctly — and neither adds a handler to ``main``.
        reconcile_processing_fees(db)
        report_payout_schedule_stragglers(db)
        sync_bank_payouts(db)

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
