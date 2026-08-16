"""FIP3 — grants log used for source-aware suspension.

The pre-FIP3 model collapses to one ``PathwayEntitlement`` row per
``(user_id, pathway_id)``: a manual grant followed by a plan-driven
grant reactivates the same row, overwriting ``source`` and
opportunistically setting ``purchase_plan_id``. When the plan is
later suspended we cannot tell from the entitlement row alone
whether the user still has independent access via a manual/admin
grant, a different plan, or a pay-in-full purchase.

Every fulfilment writes one row here per (user, target, source) so
plan-suspension can ask a simple question:

    is any *other* active grant record present for this
    (user, target) that isn't linked to this plan?

If yes → leave the entitlement/pass active.
If no  → suspend it (plan owned it exclusively).

The log is additive and does not compete with ``PathwayEntitlement``
or ``AccessPass`` as the source of truth for "does the user have
access". Reader code continues to consult those tables. This log
supports lifecycle operations only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# String constants — used across the fulfilment write-path and the FIP3
# suspension/reinstatement services. Kept as strings (not an Enum) to
# match how ``grant_kind`` and ``source_type`` are stored — CHECK-free
# in the schema so we can add new source types without a migration.
# ---------------------------------------------------------------------------

GRANT_KIND_PATHWAY = "pathway"
GRANT_KIND_SERIES = "series"

SOURCE_PLAN_PAYMENT = "plan_payment"      # FIP2/3 per-invoice grant
SOURCE_PAY_IN_FULL = "pay_in_full"         # single-Checkout purchase
SOURCE_ADMIN_GRANT = "admin_grant"         # creator/admin grant flow
SOURCE_FREE = "free"                        # free/included content
SOURCE_MANUAL = "manual"                    # ad-hoc / migration
SOURCE_SUBSCRIPTION = "subscription"       # future Creator subscription


class AccessGrantRecord(Base):
    """One row per grant event.

    Never mutates ``granted_at`` on re-delivery — a duplicate
    fulfilment attempt should skip via the natural key check in
    the write helper (``services.access_grant_records.record_grant``),
    NOT extend an existing record.
    """

    __tablename__ = "access_grant_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    grant_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_pathway_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_series_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("event_series.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_purchase_plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("purchase_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_payment_transaction_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(target_pathway_id IS NOT NULL) <> (target_series_id IS NOT NULL)",
            name="ck_agr_exactly_one_target",
        ),
    )
