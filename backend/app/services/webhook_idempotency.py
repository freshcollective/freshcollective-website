"""Durable provider-webhook idempotency helper.

Wraps a webhook handler so the same provider event id is processed
exactly once under normal operation, and is *retryable* under
abnormal operation (crashed worker, interrupted deploy).

The five failure modes it protects against:

1. Stripe re-delivers the same event id after a transient failure.
2. Two workers receive the same event at the same time.
3. A handler raises — Stripe should see non-2xx and retry.
4. The worker dies **before** the handler runs.
5. The worker dies **after** the handler committed domain writes
   but **before** the outcome marker was recorded.

Cases (4) and (5) are the reason for the lease design. Without
timing information, a ``pending`` row from a dead worker would look
identical to a genuinely in-flight worker, and every future
delivery would skip forever.

Lease design
------------
Every row carries ``processing_started_at``, set to ``NOW()`` on
each transition into ``pending``. A later delivery reading a
``pending`` row checks its age:

* Fresh (``NOW() - processing_started_at < LEASE_SECONDS``)
  → another worker is genuinely processing; return ``in_flight``.
* Stale (older than the lease) → reclaim atomically via
  conditional UPDATE, re-run the handler.

The reclaim UPDATE is guarded by the same age predicate, so if two
workers race to reclaim the same stale row, exactly one wins (the
losing UPDATE returns zero rows and the loser treats the row as
in-flight).

Handler idempotency contract
----------------------------
Because case (5) permits the handler to run again after already
having committed domain writes, **every handler must be
idempotent**. Concretely: check for the existence of the domain
object it would create (usually by the provider's natural key —
``provider_invoice_id``, ``provider_payment_intent_id``, etc.),
or use ``INSERT ... ON CONFLICT DO NOTHING`` semantics. Do not
assume "the helper prevents duplicate execution" — it prevents
double-execution under normal timing, not after a crash.

Transaction boundaries
----------------------
1. **Row insert / reclaim — own transaction.** We commit the
   ``pending`` marker *before* running the handler so a concurrent
   duplicate observes it.
2. **Handler runs.** May commit whatever it wants; the helper does
   not wrap it in an outer transaction. If the handler is invoked
   via a reclaim, the row already has ``attempt_count`` incremented
   and a fresh ``processing_started_at``.
3. **Outcome marker — own transaction.** On success, ``UPDATE ...
   SET outcome = 'succeeded'``. On failure, ``UPDATE ... SET
   outcome = 'failed', error_message = ...`` and re-raise so
   Stripe retries.
4. **Skip path** (handler raises ``SkipWebhookEvent``) marks
   ``skipped`` — used for event types this deployment doesn't act
   on.

Concurrency
-----------
The unique constraint on ``(provider, provider_event_id)`` is the
safety net. ``INSERT ... ON CONFLICT DO NOTHING`` on first delivery,
guarded reclaim UPDATE on subsequent deliveries.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent, WebhookEventOutcome


logger = logging.getLogger(__name__)


# Default lease window — 5 minutes. Chosen so a genuinely slow
# Stripe handler (e.g. one making several downstream calls) has room
# to finish, while a crashed worker's row is recoverable on the
# next Stripe redelivery. Callers can override for tests.
DEFAULT_LEASE_SECONDS = 300


ProcessResult = Literal["processed", "skipped", "in_flight"]


@dataclass(frozen=True)
class ProcessOutcome:
    """Return value of :func:`process_webhook_event`.

    ``result``
        * ``processed`` — the handler ran to completion just now
          (either first delivery, or a reclaim after failure /
          stale lease).
        * ``skipped`` — a prior delivery already reached
          ``succeeded`` / ``skipped``. Nothing was invoked.
        * ``in_flight`` — another worker holds a fresh lease on
          this event. This delivery skipped; the concurrent one
          will complete or fail.

    ``event_row_id``
        The row's PK — handy for logging / correlating.
    """

    result: ProcessResult
    event_row_id: str


def process_webhook_event(
    db: Session,
    *,
    provider: str,
    provider_event_id: str,
    event_type: str,
    handler: Callable[[], None],
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> ProcessOutcome:
    """Run ``handler`` at most once for ``(provider, provider_event_id)``.

    ``handler`` is a zero-argument callable. It should perform its
    domain writes on the same ``db`` Session. It may commit or not
    — the helper commits the outcome marker independently.

    ``lease_seconds`` bounds how long a ``pending`` row is treated
    as in-flight before it becomes reclaimable by a later delivery.
    Tests may pass ``0`` to force immediate staleness.

    Callers wishing to record "we saw this event type but do not
    handle it" should have the handler raise :class:`SkipWebhookEvent`
    — the helper will mark the row ``skipped``.
    """
    provider_event_id = provider_event_id.strip()
    if not provider_event_id:
        raise ValueError("provider_event_id is required")

    row_id, action = _acquire_lease(
        db,
        provider=provider,
        provider_event_id=provider_event_id,
        event_type=event_type,
        lease_seconds=lease_seconds,
    )

    if action == "skipped":
        return ProcessOutcome(result="skipped", event_row_id=row_id)
    if action == "in_flight":
        return ProcessOutcome(result="in_flight", event_row_id=row_id)

    # We hold the lease — run the handler.
    try:
        handler()
    except SkipWebhookEvent as exc:
        db.execute(
            text(
                "UPDATE webhook_events "
                "SET outcome = 'skipped', processed_at = :now "
                "WHERE id = :id"
            ),
            {"id": row_id, "now": datetime.utcnow()},
        )
        db.commit()
        logger.info(
            "webhook_event skipped (%s:%s type=%s): %s",
            provider, provider_event_id, event_type, exc,
        )
        return ProcessOutcome(result="skipped", event_row_id=row_id)
    except Exception as exc:
        # Reset the row to ``failed`` in a fresh transaction so the
        # marker survives the handler's rollback.
        db.rollback()
        db.execute(
            text(
                "UPDATE webhook_events "
                "SET outcome = 'failed', "
                "    error_message = :err "
                "WHERE id = :id"
            ),
            {"id": row_id, "err": str(exc)[:2000]},
        )
        db.commit()
        logger.error(
            "webhook_event handler raised (%s:%s type=%s): %s",
            provider, provider_event_id, event_type, exc,
        )
        raise

    db.execute(
        text(
            "UPDATE webhook_events "
            "SET outcome = 'succeeded', processed_at = :now "
            "WHERE id = :id"
        ),
        {"id": row_id, "now": datetime.utcnow()},
    )
    db.commit()
    return ProcessOutcome(result="processed", event_row_id=row_id)


# ---------------------------------------------------------------------------
# Lease acquisition — internal
# ---------------------------------------------------------------------------


_AcquireAction = Literal["hold_lease", "skipped", "in_flight"]


def _acquire_lease(
    db: Session,
    *,
    provider: str,
    provider_event_id: str,
    event_type: str,
    lease_seconds: int,
) -> tuple[str, _AcquireAction]:
    """Insert-or-reclaim the row for this event. Returns (row_id, action).

    ``action``:
      * ``hold_lease`` — the caller now owns the lease and should
        invoke the handler.
      * ``skipped``    — the row is already ``succeeded`` / ``skipped``;
        nothing to do.
      * ``in_flight``  — another worker holds a fresh lease.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=lease_seconds)

    # Try the first-delivery fast path.
    new_row_id = f"whe_{uuid.uuid4().hex[:24]}"
    inserted = db.execute(
        text("""
            INSERT INTO webhook_events (
                id, provider, provider_event_id, event_type,
                outcome, received_at, processing_started_at, attempt_count
            ) VALUES (
                :id, :provider, :provider_event_id, :event_type,
                'pending', :now, :now, 1
            )
            ON CONFLICT (provider, provider_event_id) DO NOTHING
            RETURNING id
        """),
        {
            "id": new_row_id,
            "provider": provider,
            "provider_event_id": provider_event_id,
            "event_type": event_type,
            "now": now,
        },
    ).first()

    if inserted is not None:
        db.commit()
        return new_row_id, "hold_lease"

    # Row exists — inspect state.
    existing = db.execute(
        text(
            "SELECT id, outcome, processing_started_at "
            "FROM webhook_events "
            "WHERE provider = :provider "
            "AND provider_event_id = :provider_event_id"
        ),
        {"provider": provider, "provider_event_id": provider_event_id},
    ).first()
    if existing is None:
        raise RuntimeError(
            f"webhook_events row missing after INSERT conflict: "
            f"{provider}:{provider_event_id}"
        )
    row_id, outcome, processing_started_at = existing[0], existing[1], existing[2]

    if outcome in ("succeeded", "skipped"):
        return row_id, "skipped"

    if outcome == "failed":
        # Straight reclaim — failed rows have no lease concept.
        db.execute(
            text(
                "UPDATE webhook_events "
                "SET outcome = 'pending', "
                "    processing_started_at = :now, "
                "    attempt_count = attempt_count + 1, "
                "    error_message = NULL "
                "WHERE id = :id AND outcome = 'failed'"
            ),
            {"id": row_id, "now": now},
        )
        db.commit()
        return row_id, "hold_lease"

    # outcome == 'pending' — check lease age.
    fresh = (
        processing_started_at is not None
        and processing_started_at > stale_cutoff
    )
    if fresh:
        return row_id, "in_flight"

    # Stale — try to reclaim atomically. The WHERE clause repeats
    # the staleness predicate so a concurrent worker that reclaimed
    # first (freshening the timestamp) causes our UPDATE to touch
    # zero rows. If we get zero rows, treat as in_flight — the
    # winner will proceed.
    reclaimed = db.execute(
        text(
            "UPDATE webhook_events "
            "SET outcome = 'pending', "
            "    processing_started_at = :now, "
            "    attempt_count = attempt_count + 1, "
            "    error_message = NULL "
            "WHERE id = :id "
            "AND outcome = 'pending' "
            "AND (processing_started_at IS NULL "
            "     OR processing_started_at < :cutoff) "
            "RETURNING id"
        ),
        {"id": row_id, "now": now, "cutoff": stale_cutoff},
    ).first()
    db.commit()

    if reclaimed is not None:
        logger.warning(
            "webhook_event reclaimed stale pending (%s:%s type=%s row=%s)",
            provider, provider_event_id, event_type, row_id,
        )
        return row_id, "hold_lease"

    # Someone else reclaimed first — treat as in-flight.
    return row_id, "in_flight"


class SkipWebhookEvent(Exception):
    """Raised by a handler to mark the event ``skipped`` without failing.

    Use when the handler received an event type it does not intend
    to act on (e.g. an event category surfaced by Stripe that this
    deployment ignores). Prefer ``skipped`` over ``succeeded`` for
    "we saw it but did nothing" — it keeps the operational count
    of "actually did work" honest.
    """
