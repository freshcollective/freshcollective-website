"""Sweep expired-grace creator subscriptions.

Fresh Collective's own 7-day grace window after a failed monthly
invoice. Any ``creator_subscriptions`` row where
``status='past_due' AND grace_expires_at < now`` transitions to
``status='unpaid'`` — which blocks new paid checkout via the
existing ``NoActiveCreatorPlanError`` guard.

Idempotent under repeated runs. Existing member access, purchases,
and finite payment plans are unaffected.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/creator_subscription_grace_reconcile.py

Exit code:
    0 on success (even when zero rows moved).
    1 on unexpected error.

Runtime config (least-privilege, matches fc-refund-reconciler):

  * ``FC_SERVICE_ROLE=job``    — skips web-only Settings validators.
  * ``DATABASE_URL``           — same DB as fc-api.
  * ``APP_ENV=production``     — for the Stripe-key-mode guard, even
                                  though this script never touches
                                  Stripe.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
# Full registry load — matches fip3_reconcile_grace.py rationale.
import app.main  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.creator_subscription_lifecycle import (
    sweep_expired_creator_grace,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        try:
            n = sweep_expired_creator_grace(db)
            logger.info("creator_subscription_grace_reconcile: swept=%s", n)
            return 0
        except Exception:
            logger.exception("creator_subscription_grace_reconcile: failed")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
