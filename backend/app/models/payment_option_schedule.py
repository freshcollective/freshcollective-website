from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentOptionSchedule(Base):
    """
    A payment schedule attached to a PaymentOption.

    schedule_type controls Stripe checkout mode:
      pay_in_full          → Stripe mode 'payment' (Phase A: fully implemented)
      recurring_installments → Stripe mode 'subscription' (Phase B: deferred)
      manual               → off-platform / custom arrangement

    For recurring_installments:
      installment_amount_cents × installment_count should ≈ total_amount_cents.
      stripe_interval / stripe_interval_count map to Stripe Price recurring params.
        weekly     → stripe_interval='week', stripe_interval_count=1
        fortnightly → stripe_interval='week', stripe_interval_count=2
    """

    __tablename__ = "payment_option_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_option_id: Mapped[str] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    schedule_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pay_in_full", server_default="pay_in_full"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    total_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upfront_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stripe_interval: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stripe_interval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )
    buyer_note: Mapped[str | None] = mapped_column(String, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=datetime.utcnow
    )
