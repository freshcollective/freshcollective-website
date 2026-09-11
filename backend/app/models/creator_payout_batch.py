"""SQLAlchemy models for manual creator payout bookkeeping.

Two models:

* :class:`CreatorPayoutBatch` — one row per admin-recorded manual
  payout. Scoped by ``(creator_user_id, currency)`` — cross-Collective
  since a creator's future Stripe Connect account is per-User and a
  real-world bank transfer is per-recipient. ``total_amount_cents``
  and ``transaction_count`` are IMMUTABLE snapshots at creation.

* :class:`CreatorPayoutBatchItem` — immutable join row per
  ``(batch, transaction)``. NEVER deleted or reassigned. When a batch
  is corrected via cancellation, PaymentTransaction rows may revert
  to ``payout_status='pending'`` and clear their convenience
  ``payout_batch_id`` pointer, but the BatchItem row stays as the
  historical evidence of what was originally recorded as paid.

Cancellation is a correction of Fresh Collective's INTERNAL record.
It does NOT reverse a bank transfer. UI must warn admins explicitly.
Historical rows remain visible in the audit trail.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CreatorPayoutBatchStatus(str, enum.Enum):
    paid = "paid"
    cancelled = "cancelled"


class CreatorPayoutBatch(Base):
    __tablename__ = "creator_payout_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # cpb_<uuid>
    creator_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # IMMUTABLE snapshot fields — populated at creation, never mutated.
    # A later refund landing on one of the linked transactions does NOT
    # change these values. Historical fact.
    total_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)

    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[CreatorPayoutBatchStatus] = mapped_column(
        SAEnum(
            CreatorPayoutBatchStatus,
            name="creator_payout_batch_status_enum",
            create_type=False,
        ),
        nullable=False,
        default=CreatorPayoutBatchStatus.paid,
        server_default="paid",
    )

    created_by_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    # Admin-recorded date/time of the actual bank/SEPA transfer.
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )

    # Cancellation audit — never mutates the immutable fields above.
    # ``cancellation_reason`` is required when transitioning to
    # ``cancelled`` (enforced at the endpoint layer).
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancelled_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_creator_payout_batches_creator_currency_status",
            "creator_user_id", "currency", "status",
        ),
    )


class CreatorPayoutBatchItem(Base):
    """Immutable per-(batch, transaction) audit row.

    Never deleted, never reassigned. When a batch is cancelled with
    ``revert_transactions=True``, the linked PaymentTransactions may
    revert to ``payout_status='pending'`` and clear their
    ``payout_batch_id`` convenience pointer, but this BatchItem row
    remains as historical evidence of what the original batch
    contained. If the same transaction is later paid in another
    batch, a NEW BatchItem row is created — historical membership of
    each batch is queryable forever.
    """
    __tablename__ = "creator_payout_batch_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # cpbi_<uuid>
    payout_batch_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("creator_payout_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_transaction_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("payment_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The amount recorded as paid for this transaction in this batch.
    # SUM over a batch equals the batch's total_amount_cents.
    creator_amount_cents_at_payout: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    # State snapshot of refund reversal at the moment of payout —
    # lets us cleanly attribute later refund growth as post-payout
    # (which flows into RefundOperation.payout_advisory).
    refunded_creator_amount_cents_at_payout: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "payout_batch_id", "payment_transaction_id",
            name="uq_payout_batch_item_batch_txn",
        ),
        Index(
            "ix_creator_payout_batch_items_batch", "payout_batch_id",
        ),
        Index(
            "ix_creator_payout_batch_items_txn", "payment_transaction_id",
        ),
    )
