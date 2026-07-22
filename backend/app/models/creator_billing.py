"""
SQLAlchemy models for creator plan tiers and subscriptions.

Tables:
  creator_plans         — plan definitions (Basic, Plus, future tiers)
  creator_subscriptions — one active subscription per creator user

Money: stored as integer cents (monthly_price_cents). Currency as VARCHAR(3), default AUD.
Fees:  stored as basis points (100 bp = 1%). E.g. 8% = 800 bp.
IDs:   string UUID4, consistent with the rest of the platform.

Stripe integration is intentionally deferred. stripe_subscription_id and
stripe_customer_id columns are present but always NULL until billing goes live.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CreatorSubscriptionStatus(str, enum.Enum):
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    cancelled = "cancelled"
    unpaid = "unpaid"


class CreatorPlan(Base):
    """A creator plan tier defining limits and fee structure."""

    __tablename__ = "creator_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    monthly_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )
    # Fresh Collective transaction fee on member payments, in basis points (800 = 8%)
    transaction_fee_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)

    collective_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    pathway_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_storage_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creator_admin_seat_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
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

    subscriptions: Mapped[list["CreatorSubscription"]] = relationship(
        "CreatorSubscription", back_populates="plan"
    )


class CreatorSubscription(Base):
    """
    Active creator subscription linking a user to their plan tier.
    One active/trialing row per creator at any time.

    Stripe fields (stripe_subscription_id, stripe_customer_id) are present
    but always NULL until Stripe billing is integrated.
    """

    __tablename__ = "creator_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    creator_plan_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("creator_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[CreatorSubscriptionStatus] = mapped_column(
        SAEnum(
            CreatorSubscriptionStatus,
            name="creator_subscription_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=CreatorSubscriptionStatus.active,
        server_default="active",
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
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

    # Source of the subscription — `stripe_paid` when it's backed by a real
    # Stripe subscription (once billing is live), `manual_grant` when it's
    # been granted from World Management. Never overwritten silently: the
    # admin grant/extend/revoke endpoints operate on `manual_grant` rows
    # only and refuse to touch `stripe_paid` ones. Enforced by a CHECK
    # constraint from migration 082.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual_grant",
    )

    # Grant audit — populated only when source='manual_grant'. Nullable so
    # a future stripe_paid row doesn't have to lie about reason/actor.
    grant_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    grant_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Revocation audit — set by the revoke endpoint when a manual grant is
    # explicitly ended. `status='cancelled'` alone does not preserve who
    # or why; these columns close that gap.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # TODO: Stripe billing — populate these when Stripe subscriptions go live
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    plan: Mapped[CreatorPlan] = relationship("CreatorPlan", back_populates="subscriptions")


class CreatorPlanGrant(Base):
    """Append-only history of manual creator-plan grant events.

    Recorded whenever an admin uses the Grant / Extend / Revoke actions
    on a creator's plan access. Preserves the reason, note, plan, and
    duration of previous grants even after a subscription is revoked or
    replaced, so the audit trail is not lossy.
    """

    __tablename__ = "creator_plan_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("creator_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # granted | extended | revoked
    creator_plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("creator_plans.id", ondelete="RESTRICT"), nullable=False,
    )
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )


class PlanChangeEvent(Base):
    """Append-only audit trail for admin edits to ``CreatorPlan`` rows.

    Written whenever the admin PATCH endpoint modifies a plan. The
    ``changes`` column stores a field-level diff shaped as
    ``{field: {before: <old>, after: <new>}}``. Enterprise / synthesised
    catalogue entries (Organisation) are not in ``creator_plans`` and
    cannot be edited, so they never produce an audit row.
    """

    __tablename__ = "plan_change_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("creator_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    changed_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    changes: Mapped[dict] = mapped_column(JSON, nullable=False)
