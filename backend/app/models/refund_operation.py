"""SQLAlchemy model for RefundOperation — the durable audit + state
machine for creator/admin-initiated Stripe refunds.

One PaymentTransaction can host N RefundOperation rows (partial
refunds landing at different times). The ledger truth (cumulative
refunded amount, status, per-side reversal columns) lives on
PaymentTransaction and is maintained by the ``charge.refunded``
webhook handler. RefundOperation records the operational request:
who / when / why / how much / Stripe Refund id / outcome.

State machine
-------------
See ``services.refund_reconciliation`` for the transition helpers.

::

    in_flight ──→ accepted             (Stripe .create returned Refund;
                                        API path conditional UPDATE)
              ├──→ webhook_confirmed    (metadata-first correlator when
                                        webhook arrives before API persist)
              ├──→ refused              (Stripe 4xx: over-refund, etc.)
              └──→ failed               (Stripe 5xx unrecoverable, OR
                                        reconciliation confirmed no
                                        Stripe refund exists)
    accepted  ──→ webhook_confirmed    (webhook correlated by
                                        metadata.refund_operation_id OR
                                        by stripe_refund_id;
                                        OR retrieve-based reconciliation
                                        confirmed status='succeeded')
              └──→ failed               (retrieve reconciliation found
                                        status='failed' / 'canceled')

Active states blocking a new refund on the same PaymentTransaction:
``in_flight`` (with a staleness window), ``accepted``.

Terminal states: ``webhook_confirmed``, ``refused``, ``failed``.

Idempotency key
---------------
The refund orchestration derives Stripe's idempotency-key from
``id`` as ``f"refop:{id}:v1"``. Stripe caches by key for 24 hours;
reconciliation replays within that window are safe by construction.
Beyond 24h, ``Refund.list`` + ``metadata.refund_operation_id``
search is the fallback.

Never write two RefundOperation rows for the same intent — that
would generate two different idempotency keys and could produce
two real refunds. The in-flight check enforces this.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefundOperationTerminalStatus(str, enum.Enum):
    in_flight = "in_flight"
    accepted = "accepted"
    webhook_confirmed = "webhook_confirmed"
    refused = "refused"
    failed = "failed"


# Active states that block a fresh refund on the same PaymentTransaction.
# Used by the in-flight check in the refund endpoint.
ACTIVE_REFUND_STATUSES = frozenset({
    RefundOperationTerminalStatus.in_flight.value,
    RefundOperationTerminalStatus.accepted.value,
})


class RefundOperationReason(str, enum.Enum):
    """Restricted reason enum for the initiator's motivation.
    Kept small so downstream reporting stays useful; free-text
    detail belongs in ``note``.
    """
    member_request = "member_request"
    duplicate = "duplicate"
    fraudulent = "fraudulent"
    goodwill = "goodwill"
    error_correction = "error_correction"
    other = "other"


class StripeIdentifierKind(str, enum.Enum):
    """Which Stripe identifier was used to submit the refund.

    Preferred: ``charge`` when the PaymentTransaction carries
    ``provider_charge_id``. Fallback: ``payment_intent`` when only
    ``provider_payment_intent_id`` is known (pay-in-full rows
    before the opportunistic charge-id backfill in the refund
    handler has run).
    """
    charge = "charge"
    payment_intent = "payment_intent"


class RefundOperation(Base):
    __tablename__ = "refund_operations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # refop_<uuid>
    payment_transaction_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("payment_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Amount the caller asked to refund, in cents. Immutable per row.
    requested_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # The expected ``charge.amount_refunded`` value AFTER this refund
    # completes. Computed at insert-time under row lock as
    # ``PaymentTransaction.refunded_amount_cents + requested_amount_cents``.
    # Not authoritative — the webhook's actual cumulative value wins —
    # but used by the correlator + operator UI to detect drift.
    expected_cumulative_refunded_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )

    # Stripe identifier used at the point of the API call. Persisted
    # so reconciliation can replay ``stripe.Refund.create`` with the
    # SAME parameters + SAME idempotency-key.
    stripe_identifier_kind: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    stripe_identifier_value: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )

    # Populated when Stripe returns a Refund object — either directly
    # from the API call, or from a webhook whose Refund carries our
    # metadata.refund_operation_id.
    stripe_refund_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )

    # String rather than SAEnum so future values (e.g. a distinct
    # 'orphaned' state) can be added by writing a value without a
    # DB enum migration.
    terminal_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=RefundOperationTerminalStatus.in_flight.value,
        server_default=RefundOperationTerminalStatus.in_flight.value,
    )
    api_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated when a platform-owner overrides a refund on a
    # ``payout_status ∈ {paid, held}`` transaction — flags
    # operational follow-up. Values:
    #   post_payout_manual_recovery_required
    #   post_hold_manual_review_required
    payout_advisory: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Non-null when a state transition was driven by reconciliation
    # (either lazy from the refund endpoint or the background cron)
    # rather than the happy webhook path.
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    confirming_webhook_event_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("webhook_events.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_refund_operations_stripe_refund_id", "stripe_refund_id"),
        Index(
            "ix_refund_operations_active_check",
            "payment_transaction_id", "terminal_status",
        ),
    )
