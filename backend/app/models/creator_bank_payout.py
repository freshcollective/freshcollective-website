"""Actual bank payouts, as Stripe reports them.

Why this exists
---------------
A Connect *transfer* moves a creator's share from Fresh Collective's balance
into the creator's Stripe balance. A *payout* is the separate, later step
where Stripe sends that balance to their bank. Fresh Collective could see the
first and had no record of the second, so the furthest it could honestly say
was "sent to Stripe" — true, but not what a creator wants to know.

Read from Stripe, never inferred
--------------------------------
Every row here comes from ``Payout.list`` on the connected account. Nothing
is derived from transfer records: a successful transfer says nothing about
whether the bank accepted the deposit, and treating one as the other is
exactly the claim this table exists to avoid making.

A projection, not a ledger
--------------------------
Stripe owns the truth. This is a cache so Creator Studio can render a list
without a Stripe round trip per page view, and it is keyed on Stripe's own
payout id so a re-read of the same payout updates the row rather than adding
one. Nothing in Fresh Collective's money path reads it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Stripe's payout statuses, as documented. Stored verbatim rather than
#: mapped to Fresh Collective's own vocabulary, so a status Stripe adds later
#: is recorded rather than silently coerced into the nearest known value.
#:
#: ``paid`` is the only one that means the money reached the bank.
PAYOUT_STATUSES: tuple[str, ...] = (
    "pending",
    "in_transit",
    "paid",
    "failed",
    "canceled",
)


class CreatorBankPayout(Base):
    """One payout from a creator's Stripe balance to their bank."""

    __tablename__ = "creator_bank_payouts"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    #: Who the payout belongs to. Every read is scoped by this: a creator
    #: must never be able to see another's payouts.
    creator_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    #: The connected account it was paid from, and the Stripe mode it belongs
    #: to. Test-mode and live-mode payouts must never appear in one list.
    stripe_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_mode: Mapped[str] = mapped_column(String(10), nullable=False)

    #: Stripe's payout id. The natural key: re-reading a payout updates this
    #: row instead of creating a second one, which is what makes the sync
    #: idempotent however many times it runs.
    provider_payout_id: Mapped[str] = mapped_column(String(255), nullable=False)

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Verbatim from Stripe. See :data:`PAYOUT_STATUSES`.
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    #: When Stripe expects the money to reach the bank — an estimate until
    #: the payout is ``paid``, and the figure a creator actually wants.
    arrival_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    #: When Stripe created the payout.
    initiated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    #: Stripe's machine-readable reason a payout failed, e.g.
    #: ``account_closed``. Kept for operators; the creator sees plain words.
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    #: When Fresh Collective last read this payout from Stripe. Lets the page
    #: say how current the list is rather than implying it is live.
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        # The idempotency guarantee, in the schema rather than in the sync
        # code: a second read of the same payout cannot become a second row.
        UniqueConstraint(
            "provider_payout_id", "stripe_mode",
            name="uq_creator_bank_payouts_provider_id_mode",
        ),
        CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_creator_bank_payouts_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_transit', 'paid', 'failed', 'canceled')",
            name="ck_creator_bank_payouts_status",
        ),
        CheckConstraint(
            "amount_cents >= 0", name="ck_creator_bank_payouts_amount_non_negative",
        ),
        # The only read pattern: this creator's payouts, newest first.
        Index(
            "ix_creator_bank_payouts_creator_mode_date",
            "creator_user_id", "stripe_mode", "arrival_date",
        ),
    )
