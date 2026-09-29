"""Creator-managed discount codes, and the ledger of their redemptions.

A code belongs to one Collective. Uniqueness is ``(space_id, code)``, not
global — two Creators may both run FAMILY50, and neither can see or
redeem the other's. Codes are stored upper-cased, so matching is
case-insensitive and the stored value is the canonical one.

Money is minor units. A percentage is basis points (``5000`` = 50%)
rather than a float, because a float percentage multiplied into cents
invites drift that only shows up on an odd amount months later.

``redemption_count`` is a cache for display. ``DiscountRedemption`` is
the truth, and its two partial unique indexes are what make a webhook
redelivery a no-op rather than a second redemption.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiscountType(str, enum.Enum):
    percentage = "percentage"
    fixed_amount = "fixed_amount"


class DiscountScopeKind(str, enum.Enum):
    #: Every paid offer in the Collective.
    space = "space"
    #: One Payment Option, named by ``scope_id``.
    payment_option = "payment_option"


class DiscountCode(Base):
    __tablename__ = "discount_codes"
    __table_args__ = (
        UniqueConstraint("space_id", "code", name="uq_discount_codes_space_code"),
        CheckConstraint(
            "discount_type IN ('percentage', 'fixed_amount')",
            name="ck_discount_codes_type",
        ),
        CheckConstraint(
            "scope_kind IN ('space', 'payment_option')",
            name="ck_discount_codes_scope_kind",
        ),
        CheckConstraint(
            "(discount_type = 'percentage'"
            "  AND percent_bps IS NOT NULL AND percent_bps BETWEEN 1 AND 10000"
            "  AND amount_cents IS NULL)"
            " OR (discount_type = 'fixed_amount'"
            "  AND amount_cents IS NOT NULL AND amount_cents > 0"
            "  AND currency IS NOT NULL AND percent_bps IS NULL)",
            name="ck_discount_codes_value_shape",
        ),
        CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_discount_codes_max_redemptions",
        ),
        CheckConstraint(
            "redemption_count >= 0", name="ck_discount_codes_redemption_count",
        ),
        CheckConstraint(
            "(scope_kind = 'space' AND scope_id IS NULL)"
            " OR (scope_kind = 'payment_option' AND scope_id IS NOT NULL)",
            name="ck_discount_codes_scope_shape",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: Canonical upper-cased form. Use ``normalise_code`` on every read.
    code: Mapped[str] = mapped_column(String(40), nullable=False)

    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Basis points. 5000 = 50%. NULL for fixed-amount codes.
    percent_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Minor units. NULL for percentage codes.
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Required for fixed-amount; a fixed discount is meaningless without one.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redemption_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    scope_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DiscountScopeKind.space.value,
        server_default="space",
    )
    scope_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="CASCADE"),
        nullable=True,
    )

    created_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )


class DiscountRedemption(Base):
    """One genuinely successful purchase that consumed a code.

    Written at fulfilment, never at validation — typing a code into
    checkout is not a redemption. Exactly one of
    ``payment_transaction_id`` / ``purchase_plan_id`` is set, and the
    partial unique index on whichever it is makes a replayed webhook
    collide instead of double-counting.
    """

    __tablename__ = "discount_redemptions"
    __table_args__ = (
        CheckConstraint(
            "original_amount_cents >= 0 AND discount_amount_cents >= 0"
            " AND final_amount_cents >= 0"
            " AND final_amount_cents = original_amount_cents - discount_amount_cents",
            name="ck_discount_redemptions_amounts",
        ),
        CheckConstraint(
            "(payment_transaction_id IS NOT NULL AND purchase_plan_id IS NULL)"
            " OR (payment_transaction_id IS NULL AND purchase_plan_id IS NOT NULL)",
            name="ck_discount_redemptions_one_purchase",
        ),
        Index(
            "uq_discount_redemptions_code_txn",
            "discount_code_id", "payment_transaction_id",
            unique=True,
            postgresql_where=sa_text("payment_transaction_id IS NOT NULL"),
        ),
        Index(
            "uq_discount_redemptions_code_plan",
            "discount_code_id", "purchase_plan_id",
            unique=True,
            postgresql_where=sa_text("purchase_plan_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    discount_code_id: Mapped[str] = mapped_column(
        String, ForeignKey("discount_codes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    payment_transaction_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    purchase_plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("purchase_plans.id", ondelete="SET NULL"),
        nullable=True,
    )

    original_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    final_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )


class ReservationStatus(str, enum.Enum):
    """Only ``held`` consumes a slot.

    The two terminal states differ in what FC knows. ``converted`` means
    the purchase completed and a redemption row exists. ``released``
    means FC has positive knowledge the checkout can never complete — a
    Stripe expiry webhook, a Session verified expired, or a reservation
    that never reached Stripe at all. A reservation FC merely *suspects*
    is dead stays ``held``, because guessing frees a slot that a paid
    member is still entitled to.
    """

    held = "held"
    converted = "converted"
    released = "released"


class DiscountReservation(Base):
    """A slot held while one member is away at Stripe.

    Created before the Stripe Session, committed immediately so a crash
    between the two leaves evidence rather than a silently free slot. Its
    pricing is frozen at creation: conversion charges what the member was
    quoted, not what the code says by the time their webhook lands.

    Identity is the purchase attempt — code, member, Payment Option and
    schedule — so a retry of the same purchase reuses its own reservation
    instead of being told the code is fully used, while the same member
    using one Collective-wide code on a different offer correctly takes a
    second slot.
    """

    __tablename__ = "discount_reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    discount_code_id: Mapped[str] = mapped_column(
        String, ForeignKey("discount_codes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    #: All four identity columns are NOT NULL. A nullable one would let a
    #: row slip past the partial unique index that makes retry safe.
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    payment_option_id: Mapped[str] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="CASCADE"), nullable=False,
    )
    payment_option_schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("payment_option_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="held")

    original_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    final_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    discount_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Persisted BEFORE the Stripe call, so a recovery replay re-sends
    #: identical parameters — including the original absolute expiry.
    #: Recomputing ``now + 60 minutes`` on a retry would send different
    #: parameters under the same idempotency key.
    session_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    session_create_params_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    session_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    intended_payment_transaction_id: Mapped[str | None] = mapped_column(
        String, nullable=True,
    )
    provider_checkout_session_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    provider_checkout_session_url: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    payment_transaction_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )

    verification_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa_text("0"),
    )
    last_verification_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    last_verification_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    release_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
