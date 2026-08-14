"""SQLAlchemy model for durable webhook-event idempotency.

Stripe may deliver the same webhook event more than once — the
signed retry cadence is documented at
https://stripe.com/docs/webhooks#retries. Fresh Collective must
process each event exactly once, even under concurrent worker
delivery and even across process restarts.

Design
------
One row per provider event id. The unique constraint on
``(provider, provider_event_id)`` is the idempotency boundary. The
``outcome`` column records what happened; the helper in
``services/webhook_idempotency.py`` uses ``pending → succeeded /
failed`` transitions to distinguish an in-flight attempt from a
completed one.

Not just for finite instalments
-------------------------------
FIP1 introduces this because the recurring-plan lifecycle needs it,
but the table is provider-agnostic. Existing webhook handlers
(``checkout.session.completed`` / ``checkout.session.expired`` /
``payment_intent.payment_failed``) may adopt the helper in a future
housekeeping pass — FIP1 deliberately does not refactor them, per
the "don't touch pay-in-full" constraint.

Persistence semantics
---------------------
The helper commits the ``pending`` row *before* running the
handler, so a concurrent duplicate delivery observes it and skips
cleanly. If the handler raises, the row is updated to ``failed``
(same transaction) so a Stripe retry re-attempts processing rather
than being permanently marked done.

**Stale-pending recovery.** A worker can crash after committing the
``pending`` marker but before recording the final outcome — either
before running the handler, mid-handler, or after the handler
committed its domain writes. To prevent an event becoming
permanently stranded in ``pending``, the row carries a
``processing_started_at`` timestamp. A later delivery inspects the
age of the pending row: fresh (within the lease window) means
"another worker is genuinely processing this now, skip"; stale
means "the previous worker died, reclaim the lease and re-run".

**Handler idempotency contract.** Because the lease design permits
re-running the handler after a crash — including a crash where the
handler had already committed domain writes — every FIP2+ handler
MUST be idempotent. Concretely: check for the existence of the
domain object it would create (e.g. by ``provider_invoice_id``
uniqueness) before writing, or use ``INSERT ... ON CONFLICT DO
NOTHING`` semantics. See ``services/webhook_idempotency.py`` for
the exact transaction boundaries + reclaim logic.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebhookEventOutcome(str, enum.Enum):
    """The processing state of a received webhook event.

    ``pending``
        The idempotency row has been inserted; the caller's
        handler is running (or has crashed mid-run). A duplicate
        delivery seeing this state skips — the in-flight worker
        will finish, or the failed handler will be retried by
        Stripe's own delivery retry, which will see the same
        pending row.

    ``succeeded``
        Handler ran to completion. Duplicate deliveries skip.

    ``skipped``
        Event was of a type this deployment does not handle
        (e.g. an event category we've not yet wired). Not an
        error; recorded so operational tooling can see what was
        seen but not acted on.

    ``failed``
        Handler raised. The row is retained with the error
        message so the next Stripe retry (or a manual replay)
        can attempt again. On the next attempt the helper
        transitions ``failed → pending`` before invoking the
        handler.
    """

    pending = "pending"
    succeeded = "succeeded"
    skipped = "skipped"
    failed = "failed"


class WebhookEvent(Base):
    """One row per provider event id we have observed.

    Uniqueness of ``(provider, provider_event_id)`` is the
    idempotency guarantee. Handlers must never dedupe on their own
    ad-hoc state — always go through
    ``services/webhook_idempotency.process_webhook_event()``.
    """

    __tablename__ = "webhook_events"

    # Our own id so we can reference this row from log tables etc.
    id: Mapped[str] = mapped_column(String, primary_key=True)

    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="stripe", server_default="stripe",
    )
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    outcome: Mapped[WebhookEventOutcome] = mapped_column(
        SAEnum(
            WebhookEventOutcome,
            name="webhook_event_outcome_enum",
            create_type=True,
        ),
        nullable=False,
        default=WebhookEventOutcome.pending,
        server_default="pending",
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    # Set to ``NOW()`` every time the row enters the ``pending`` state
    # (initial insert + reclaim after failure + reclaim after stale
    # lease). Used by :func:`process_webhook_event` to distinguish
    # "in-flight" from "abandoned by dead worker" — a pending row
    # older than the lease timeout is reclaimable by any delivery.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    # Number of times this event has entered processing. Incremented
    # by the idempotency helper on each ``pending`` transition so the
    # error tail is visible when triaging retries.
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id",
            name="uq_webhook_events_provider_event_id",
        ),
        Index("ix_webhook_events_event_type", "event_type"),
        Index("ix_webhook_events_outcome", "outcome"),
        Index("ix_webhook_events_received_at", "received_at"),
    )
