from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccessPassType(str, enum.Enum):
    pathway_access = "pathway_access"
    term_pass = "term_pass"
    class_pass = "class_pass"
    event_ticket = "event_ticket"
    retreat_booking = "retreat_booking"
    membership = "membership"
    bundle = "bundle"


class AccessPassStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    used = "used"
    expired = "expired"
    cancelled = "cancelled"
    suspended = "suspended"


class AccessPassSource(str, enum.Enum):
    one_time_purchase = "one_time_purchase"
    subscription = "subscription"
    admin_grant = "admin_grant"
    manual = "manual"
    free = "free"


class AccessPass(Base):
    """Records what a member owns after a successful purchase.

    Serves as the source of truth for booking/session/ticket allowances.
    PathwayEntitlement remains the source of truth for pathway content access.
    """

    __tablename__ = "access_passes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source of this pass
    payment_transaction_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_option_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="SET NULL"), nullable=True
    )
    payment_option_schedule_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_option_schedules.id", ondelete="SET NULL"), nullable=True
    )

    # Classification
    pass_type: Mapped[AccessPassType] = mapped_column(
        SAEnum(AccessPassType, name="accesspasstype", create_type=True),
        nullable=False,
    )

    # Lifecycle
    status: Mapped[AccessPassStatus] = mapped_column(
        SAEnum(AccessPassStatus, name="accesspassstatus", create_type=True),
        nullable=False,
        default=AccessPassStatus.active,
        server_default="active",
    )

    # Validity window
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # Booking credits (null = not credit-based, e.g. pathway_access with no sessions)
    total_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    credits_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Gathering eligibility: gatherings whose booking_required_pathway_id matches this
    eligible_pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Series eligibility: gatherings whose ``series_id`` matches this
    # are bookable using this pass. Introduced in migration 105 so
    # series-attached PaymentOptions can grant scoped booking rights
    # without piggy-backing on a Pathway as a gating token.
    eligible_series_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("event_series.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Pathway content link (when purchase also grants pathway content)
    grants_pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )
    pathway_entitlement_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathway_entitlements.id", ondelete="SET NULL"), nullable=True
    )

    # Audit
    source: Mapped[AccessPassSource] = mapped_column(
        SAEnum(AccessPassSource, name="accesspasssource", create_type=True),
        nullable=False,
        default=AccessPassSource.one_time_purchase,
        server_default="one_time_purchase",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_access_passes_user_status", "user_id", "status"),
    )

    @property
    def remaining_credits(self) -> int | None:
        if self.total_credits is None:
            return None
        return max(0, self.total_credits - self.used_credits)


class AccessPassEvent(Base):
    """Join table: which specific events an access pass grants entry to.

    Used for event_ticket and retreat_booking pass types (Phase C+).
    Created now but not populated in Phase B.
    """

    __tablename__ = "access_pass_events"

    access_pass_id: Mapped[str] = mapped_column(
        String, ForeignKey("access_passes.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(
        String, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
