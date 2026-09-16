"""Idempotency helper for the Stripe webhook.

Callers pass ``event.id`` + a stable payload hash; we insert into
``stripe_webhook_events`` with ON CONFLICT DO NOTHING and return
``True`` when we won the race (i.e. this event has not been
processed yet). A subsequent call marks the row processed.

Not used by the older finite-plan handlers — those retain their
row-level SELECT FOR UPDATE idempotency. New creator-billing
handlers use this table exclusively.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


def hash_payload(event_object: dict) -> str:
    """Stable SHA-256 of the event's ``data.object`` payload. Used to
    detect replay-with-mutation — an event.id re-delivery whose body
    differs from the one we already processed is treated as suspect."""
    canonical = json.dumps(event_object, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def claim_event(
    db: Session, *, event_id: str, event_type: str, payload_sha256: str,
) -> bool:
    """Claim ``event_id`` for processing.

    Returns True if this call wins the race (first delivery), False if
    the event was already claimed (duplicate). Raises ValueError when
    a duplicate arrives with a different payload hash — that shouldn't
    happen for a legitimate Stripe redelivery and warrants an alert.
    """
    result = db.execute(
        text(
            """
            INSERT INTO stripe_webhook_events (id, event_type, payload_sha256)
            VALUES (:id, :event_type, :payload_sha256)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": event_id,
            "event_type": event_type,
            "payload_sha256": payload_sha256,
        },
    )
    if result.rowcount == 1:
        db.commit()
        return True
    # Row already existed — check the payload hash matches.
    row = db.execute(
        text(
            "SELECT payload_sha256 FROM stripe_webhook_events WHERE id = :id"
        ),
        {"id": event_id},
    ).first()
    if row is None:
        # Should be unreachable — the INSERT reported a conflict.
        return False
    stored_hash = row[0]
    if stored_hash != payload_sha256:
        raise ValueError(
            f"Stripe event {event_id!r} redelivered with a different payload "
            f"hash ({payload_sha256!r} vs stored {stored_hash!r}). Refusing "
            "to reprocess."
        )
    logger.info(
        "stripe_webhook_dedup: event %s (%s) already processed; skipping.",
        event_id, event_type,
    )
    return False


def mark_processed(db: Session, event_id: str) -> None:
    """Stamp ``processed_at`` after a handler completes without raising."""
    db.execute(
        text(
            "UPDATE stripe_webhook_events SET processed_at = :now WHERE id = :id"
        ),
        {"id": event_id, "now": datetime.utcnow()},
    )
    db.commit()
