"""A member's recurring agreement to belong to one Collective.

Two records, two questions
--------------------------
``SpaceMembership`` answers *does this person belong?* — it is the one
record of membership, read by every access check on the platform, and it
is deliberately untouched by this model. ``CollectiveMembership`` answers
*what did they agree to pay, and is that payment current?*

The two meet in exactly one place: a verified first invoice calls
``membership_grant.ensure_membership_for_purchase``, which creates or
reactivates the membership row. Nothing else here grants access, and no
access check reads this table. That separation is what lets an invited,
comped or creator-owned membership carry on regardless of billing.

A returning member keeps one membership relationship and gains a second
agreement, which is why ``(user_id, space_id)`` is unique only across
*live* statuses.

Agreed terms are frozen
-----------------------
``interval``, ``amount_cents``, ``currency`` and the Stripe Price are
written once, at subscribe time, and never re-read from the Collective
afterwards. A creator who moves their Collective from A$29 to A$39 does
not re-price anybody who already subscribed — not by policy, but because
there is no code path that could. The fee context is frozen the same way
and for the same reason, matching ``PurchasePlan``.

Not this model's job
--------------------
Renewals, grace periods, cancellation and expiry are Stage 5A.2. The
columns they need exist here so that stage adds behaviour rather than a
migration, but nothing writes them yet.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CollectiveMembershipStatus(str, enum.Enum):
    """The agreement's state — not the member's.

    ``pending``
        Checkout opened; nothing paid. Grants nothing, and is the only
        state a member can hold without being a member.
    ``active``
        A verified payment is current.
    ``past_due``
        A renewal failed and Stripe is retrying. Stage 5A.2.
    ``cancel_scheduled``
        Cancelled by the member; the paid period is still running.
        Stage 5A.2.
    ``ended``
        The paid period finished, or grace expired. Stage 5A.2.
    ``cancelled``
        Stopped by an operator or by the member leaving — distinct from
        ``ended``, which is a period running out.
    ``failed``
        The first payment never succeeded and the attempt is closed.
    """

    pending = "pending"
    active = "active"
    past_due = "past_due"
    cancel_scheduled = "cancel_scheduled"
    ended = "ended"
    cancelled = "cancelled"
    failed = "failed"


#: Statuses that are, or could still become, billing. Mirrors the
#: partial unique index in migration 189 exactly — if these two ever
#: disagree the database wins, and a test asserts they do not.
LIVE_STATUSES: frozenset[str] = frozenset({
    CollectiveMembershipStatus.pending.value,
    CollectiveMembershipStatus.active.value,
    CollectiveMembershipStatus.past_due.value,
})


class CollectiveMembership(Base):
    __tablename__ = "collective_memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=CollectiveMembershipStatus.pending.value,
        server_default="pending",
    )

    # ── Agreed terms, frozen at subscribe ───────────────────────────
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    interval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    stripe_product_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── Stripe ──────────────────────────────────────────────────────
    stripe_customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    # ── Creator payment context, frozen at subscribe ────────────────
    creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    platform_fee_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    payout_model: Mapped[str | None] = mapped_column(String(20), nullable=True)
    connect_destination_account_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    creator_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # ── Lifecycle ───────────────────────────────────────────────────
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    cancelled_reason: Mapped[str | None] = mapped_column(String(250), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    #: Stage 5A.2 reads these. Nothing writes them yet.
    payment_problem_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    grace_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    last_failed_invoice_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )

    # ── Provenance ──────────────────────────────────────────────────
    stripe_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="test", server_default="test",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    @property
    def is_live(self) -> bool:
        """Is this agreement billing, or about to?"""
        return self.status in LIVE_STATUSES
