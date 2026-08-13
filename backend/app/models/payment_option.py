"""
PaymentOption model — flexible purchase options for pathways (and future gathering series/bundles).

Phase A: supports term passes (EMBODY) and simple one-time options.
Phase B: will add BookingAllowance enforcement.
Phase C: will add bundles/discounts.

Design notes:
  - pathway_id       = where this option is displayed (the pathway's About/checkout pages)
  - grants_pathway_id = which pathway entitlement is created after purchase
                       (null → defaults to pathway_id; future: can differ for bundles)
  - effective_price_cents = override_total_cents if set, else calculated_total_cents
  - calculated_total_cents is stored explicitly (not computed on read) so creators can
    confirm the calculation before choosing to override it
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.payment_option_grant import PaymentOptionGrant


class PaymentOptionType(str, enum.Enum):
    free = "free"
    one_time = "one_time"
    term_pass = "term_pass"
    subscription = "subscription"


class PaymentOptionStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class PaymentOption(Base):
    __tablename__ = "payment_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Scope
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Polymorphic attachment — every option attaches to *something* it
    # is displayed alongside and priced against. In V1 that is either
    # a Pathway or an EventSeries. No FK on ``attaches_to_id`` so
    # future kinds (individual gathering, bundle) slot in without a
    # migration — mirrors the pattern used by ``offer_pages.target_*``.
    # Backfilled from ``pathway_id`` for legacy rows in migration 105.
    attaches_to_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    attaches_to_id: Mapped[str] = mapped_column(String, nullable=False)
    # Which pathway entitlement is granted on purchase.
    # NULL → defaults to pathway_id at purchase time for pathway-attached
    # options; for series-attached options, NULL means "no pathway
    # entitlement granted — this option grants booking rights only".
    grants_pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )

    # Display
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_type: Mapped[PaymentOptionType] = mapped_column(
        SAEnum(PaymentOptionType, name="payment_option_type_enum", create_type=True),
        nullable=False,
        default=PaymentOptionType.one_time,
        server_default="one_time",
    )
    status: Mapped[PaymentOptionStatus] = mapped_column(
        SAEnum(PaymentOptionStatus, name="payment_option_status_enum", create_type=True),
        nullable=False,
        default=PaymentOptionStatus.draft,
        server_default="draft",
    )

    # Term dates (required for term_pass)
    term_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    term_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Session breakdown (for EMBODY-style tiered pricing)
    sessions_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_per_session_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Pricing
    # calculated_total_cents = total_sessions × price_per_session_cents (set by creator, not auto)
    calculated_total_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # override_total_cents — takes precedence over calculated when set
    override_total_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )

    # Notes
    buyer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Collective-level grants layer (introduced in migration 108) ────
    # A PaymentOption expresses WHAT the buyer receives via zero or
    # more PaymentOptionGrant rows. Legacy attachment (``attaches_to_*``
    # + ``grants_pathway_id`` + Series limit columns above) remain the
    # source of truth during B1; the grants side is populated in a
    # later backfill (B2). No behaviour reads from ``grants`` yet.
    grants: Mapped[list["PaymentOptionGrant"]] = relationship(
        "PaymentOptionGrant",
        back_populates="payment_option",
        cascade="all, delete-orphan",
        order_by="PaymentOptionGrant.position,PaymentOptionGrant.created_at",
        lazy="selectin",
    )

    @property
    def effective_price_cents(self) -> int | None:
        """override_total_cents takes precedence over calculated_total_cents."""
        if self.override_total_cents is not None:
            return self.override_total_cents
        return self.calculated_total_cents

    __table_args__ = (
        Index("ix_payment_options_space_id", "space_id"),
        Index("ix_payment_options_pathway_id", "pathway_id"),
        Index("ix_payment_options_attaches_to", "attaches_to_kind", "attaches_to_id"),
    )


# ---------------------------------------------------------------------------
# Runtime relationship-target registration.
#
# ``PaymentOption.grants`` refers to ``PaymentOptionGrant`` by string name.
# SQLAlchemy resolves the string when a mapper is first configured (i.e. at
# the first query against any mapped class), which requires
# ``PaymentOptionGrant`` to have been imported by *some* module first.
#
# The FastAPI runtime does not otherwise import ``payment_option_grant``
# (routes only use ``PaymentOption``), so without this line the mapper
# configuration fails with "name 'PaymentOptionGrant' is not defined" on
# the first real query — including the login endpoint's ``db.query(User)``.
# Placing the import at the bottom of this file, after the class body,
# guarantees that *any* module importing ``PaymentOption`` also registers
# ``PaymentOptionGrant``, without introducing a circular import
# (``payment_option_grant`` only touches ``PaymentOption`` under
# ``TYPE_CHECKING``).
from app.models import payment_option_grant  # noqa: E402,F401 — see docstring above
