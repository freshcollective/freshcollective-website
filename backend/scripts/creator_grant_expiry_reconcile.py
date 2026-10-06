"""Expire finite complimentary Creator grants whose end date has passed.

Returns the creator to the Community plan by cancelling the grant row;
``plan_guards.resolve_creator_plan`` then resolves Community via its
cheapest-active-plan fallback. Nothing is deleted, no Stripe
subscription is created, and nobody is charged. See
``app/services/creator_grant_expiry.py`` for the full semantics,
including the three conditions under which a due grant is deliberately
left alone.

**Dry run is the default.** This script reports what it would do and
writes nothing unless ``--apply`` is passed. That is deliberate: it
changes entitlements, so it must be reviewable before it is armed, and
deploying it must not be able to mutate anything by accident.

Usage:

    cd backend
    # inspect — writes nothing
    .venv/bin/python scripts/creator_grant_expiry_reconcile.py
    # actually expire the rows listed above
    .venv/bin/python scripts/creator_grant_expiry_reconcile.py --apply

Exit codes:
    0  ran successfully (including "nothing due")
    1  unexpected error
    2  refused to run — Community is not the cheapest active plan, so a
       downgrade would not resolve to Community

Runtime config (least-privilege, matches the other reconcilers):

  * ``FC_SERVICE_ROLE=job``    — skips web-only Settings validators.
  * ``DATABASE_URL``           — same DB as fc-api.
  * ``APP_ENV=production``     — for the Stripe-key-mode guard, even
                                  though this script never touches
                                  Stripe.
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
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
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

init_sentry("fc-creator-grant-expiry")

# ruff: noqa: E402
# Full registry load — matches creator_subscription_grace_reconcile.py.
import app.main  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.creator_grant_expiry import (
    reconcile_expired_grants,
    survey_manual_grants,
)


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually expire the grants. Without it, this is a dry run.",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        try:
            # Dry run doubles as the pre-arming report: every manual
            # grant with its lifecycle classification, including the
            # excluded ones and why. Skipped when applying, where the
            # per-row log lines below are the record.
            if not args.apply:
                survey = survey_manual_grants(db)
                logger.info(
                    "creator_grant_expiry_reconcile: surveying %s manual grant(s)",
                    len(survey),
                )
                for row in survey:
                    logger.info(
                        "  [%s] user=%s <%s> plan=%s status=%s reason=%s "
                        "starts=%s ends=%s paid_sub=%s sub=%s",
                        row.lifecycle, row.user_id, row.user_email,
                        row.plan_slug, row.status, row.grant_reason,
                        row.starts_at, row.ends_at,
                        row.has_paid_subscription, row.subscription_id,
                    )
                counts: dict[str, int] = {}
                for row in survey:
                    counts[row.lifecycle] = counts.get(row.lifecycle, 0) + 1
                logger.info(
                    "creator_grant_expiry_reconcile: by lifecycle — %s",
                    ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none",
                )

            report = reconcile_expired_grants(db, apply=args.apply)

            if report.halted_reason:
                logger.error(
                    "creator_grant_expiry_reconcile: HALTED — %s",
                    report.halted_reason,
                )
                db.rollback()
                return 2

            mode = "APPLIED" if report.applied else "DRY RUN (no changes written)"
            logger.info(
                "creator_grant_expiry_reconcile: %s — due=%s skipped=%s",
                mode, report.expired_count, report.skipped_count,
            )
            for row in report.expired:
                logger.info(
                    "  %s subscription=%s user=%s plan=%s reason=%s ends_at=%s",
                    "expired" if report.applied else "would expire",
                    row.subscription_id, row.user_id, row.plan_slug,
                    row.grant_reason, row.ends_at,
                )
            for skipped in report.skipped:
                logger.warning(
                    "  left alone subscription=%s user=%s plan=%s — %s",
                    skipped.grant.subscription_id, skipped.grant.user_id,
                    skipped.grant.plan_slug, skipped.reason,
                )

            if report.applied:
                db.commit()
            else:
                # Belt and braces: the service writes nothing in dry-run
                # mode, but the SELECT ... FOR UPDATE opened a
                # transaction worth closing cleanly.
                db.rollback()
            return 0
        except Exception:
            db.rollback()
            logger.exception("creator_grant_expiry_reconcile: failed")
            return 1


if __name__ == "__main__":
    # The flush is in a ``finally`` so it runs on the failure path too,
    # which is the path whose event matters most. It is bounded and
    # swallows its own errors, so it cannot change the exit code — a
    # Sentry outage must never turn a good run into a failed cron.
    try:
        raise SystemExit(main())
    finally:
        flush_sentry()
