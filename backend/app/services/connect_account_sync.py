"""Re-read a creator's Stripe account and persist the projection.

Extracted so the creator endpoints and the v2 webhook intake share one
implementation. Two callers writing the same row from the same two Stripe
objects should not be two pieces of code, and the projection service
staying the only interpreter of Stripe state depends on there being a
single path into it.

The invariant every caller relies on: **both Stripe objects are fetched
before anything is written.** A failure halfway through therefore mutates
nothing, so there is no partial state to roll back and no way for the row
to end up describing a mixture of two moments. That is also why a
retryable failure can safely leave a good projection in place — see
:func:`record_sync_failure`.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.creator_stripe_account import CreatorStripeAccount, SyncSource
from app.services import connect_account_state as projection
from app.services import stripe_connect_accounts as connect

logger = logging.getLogger(__name__)


def sync_from_stripe(
    db: Session,
    row: CreatorStripeAccount,
    *,
    source: SyncSource,
    v2: dict | None = None,
) -> CreatorStripeAccount:
    """Fetch, project, persist, and stamp the sync diagnostics.

    ``v2`` may be supplied when the caller already holds a fresh account
    object — the account-create response is one — so a just-returned
    object is not immediately re-read.

    Raises whatever :mod:`stripe_connect_accounts` raises. Callers
    distinguish retryable from terminal on those types; nothing is written
    when it raises.
    """
    if not row.stripe_account_id:
        raise ValueError("cannot sync a row with no stripe_account_id")

    account = v2 if v2 is not None else connect.retrieve_account(row.stripe_account_id)
    legacy = connect.retrieve_legacy_account(row.stripe_account_id)

    projection.project(
        stripe_account_id=row.stripe_account_id, v2=account, v1=legacy,
    ).apply_to(row)

    row.last_synced_at = datetime.utcnow()
    row.last_sync_source = source.value
    row.last_error_message = None
    db.commit()
    return row


def record_sync_failure(
    db: Session, row: CreatorStripeAccount, message: str,
) -> None:
    """Record why a sync failed, and change nothing else.

    Deliberately leaves every projected field alone. An unanswered
    question is not evidence: a creator who was ``ready`` a minute ago must
    not be demoted because Stripe timed out, and ``resource_missing`` is
    also what a mode mismatch looks like rather than proof an account is
    gone.
    """
    row.last_error_message = message[:1000]
    db.commit()
