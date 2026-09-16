"""Creator subscription lifecycle sweeps — grace expiry today, room
for future creator-side reconciliation tasks.

Called from ``scripts/creator_subscription_grace_reconcile.py``
(Render cron). Idempotent under repeated runs.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.creator_billing import (
    CreatorSubscription,
    CreatorSubscriptionStatus,
)


logger = logging.getLogger(__name__)


def sweep_expired_creator_grace(db: Session) -> int:
    """Transition every ``past_due`` sub whose ``grace_expires_at`` is
    in the past to ``unpaid``. Return the count moved.

    Effect on downstream fee resolution: ``_resolve_fee_bps_for_creator``
    filters on ``status IN ('active','trialing')``, so an ``unpaid``
    row causes ``NoActiveCreatorPlanError`` on paid checkout — new
    paid sales are blocked. Existing members retain access.
    """
    now = datetime.utcnow()
    victims = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.status == CreatorSubscriptionStatus.past_due,
            CreatorSubscription.grace_expires_at.is_not(None),
            CreatorSubscription.grace_expires_at < now,
        )
        .all()
    )
    if not victims:
        return 0
    for sub in victims:
        sub.status = CreatorSubscriptionStatus.unpaid
        logger.info(
            "creator_subscription_grace: sub=%s user=%s grace_expired at=%s "
            "→ status=unpaid",
            sub.stripe_subscription_id, sub.user_id, sub.grace_expires_at,
        )
    db.commit()
    return len(victims)
