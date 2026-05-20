"""
SQLAlchemy model for the payment transaction ledger.

This table is the internal source of truth for all payment activity:
  - Creator billing: creator → Fresh Collective (subscription payments)
  - Member payments: member → creator (pathway/collective purchases)

Stripe integration is intentionally deferred. All provider_* columns are
present but always NULL until Stripe is integrated.
"""

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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentTransactionType(str, enum.Enum):
    creator_subscription_payment = "creator_subscription_payment"
    member_pathway_purchase = "member_pathway_purchase"
    member_collective_purchase = "member_collective_purchase"
    member_pathway_subscription = "member_pathway_subscription"
    member_collective_subscription = "member_collective_subscription"
    refund = "refund"
    adjustment = "adjustment"


class PaymentTransactionStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"
    disputed = "disputed"
    cancelled = "cancelled"


class PaymentProvider(str, enum.Enum):
    manual = "manual"
    stripe = "stripe"


class PayoutStatus(str, enum.Enum):
    not_applicable = "not_applicable"  # creator subscription payments, failed/cancelled
    pending = "pending"                # succeeded member purchase, not yet paid out
    paid = "paid"                      # TODO: set when Stripe Connect transfer confirmed
    held = "held"                      # TODO: set when payout is on hold (dispute, etc.)
    cancelled = "cancelled"            # TODO: set if payout is cancelled


class PaymentTransaction(Base):
    """
    Ledger row for a single payment event.

    Calculation rules:
      Member payments:
        platform_fee_cents        = gross_amount_cents * platform_fee_basis_points / 10000
        net_creator_amount_cents  = gross_amount_cents - platform_fee_cents
        net_platform_amount_cents = platform_fee_cents
        processing_fee_cents      = NULL (Stripe not connected)

      Creator billing:
        platform_fee_basis_points = 0
        platform_fee_cents        = 0
        net_platform_amount_cents = gross_amount_cents
        net_creator_amount_cents  = NULL
    """

    __tablename__ = "payment_transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    transaction_type: Mapped[PaymentTransactionType] = mapped_column(
        SAEnum(
            PaymentTransactionType,
            name="payment_transaction_type_enum",
            create_type=True,
        ),
        nullable=False,
    )
    status: Mapped[PaymentTransactionStatus] = mapped_column(
        SAEnum(
            PaymentTransactionStatus,
            name="payment_transaction_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=PaymentTransactionStatus.pending,
        server_default="pending",
    )
    payment_provider: Mapped[PaymentProvider] = mapped_column(
        SAEnum(
            PaymentProvider,
            name="payment_provider_enum",
            create_type=True,
        ),
        nullable=False,
        default=PaymentProvider.manual,
        server_default="manual",
    )

    # Parties
    payer_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Resource references (all nullable — not all transactions have all of these)
    space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entitlement_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathway_entitlements.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_subscription_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Money (all stored as integer cents)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )
    gross_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    platform_fee_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_fee_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True
        # TODO: Stripe webhook — populate from Stripe charge.balance_transaction when live
    )
    net_creator_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_platform_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # TODO: Stripe webhook — populate these from webhook events when Stripe is integrated
    provider_checkout_session_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_payment_intent_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_charge_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Payout tracking — populated by admin when transfer is processed
    # TODO: wire to Stripe Connect payouts once connected
    payout_status: Mapped[PayoutStatus] = mapped_column(
        SAEnum(PayoutStatus, name="payout_status_enum", create_type=False),
        nullable=False,
        default=PayoutStatus.pending,
        server_default="pending",
    )
    payout_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    payout_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_payment_transactions_status", "status"),
        Index("ix_payment_transactions_transaction_type", "transaction_type"),
        Index("ix_payment_transactions_created_at", "created_at"),
    )
