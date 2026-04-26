"""
SQLAlchemy models for the Fresh Collective admin sales pipeline.

Tables:
  subscription_plans      — membership product records
  subscription_prices     — versioned pricing (supports price changes over time)
  sales_leads             — prospects / people in the pipeline
  sales_opportunities     — individual deals tracked per lead
  sales_activities        — logged notes, calls, emails, conversations
  sales_tasks             — follow-up tasks for admin
  member_subscriptions    — internal subscription records per user

Money: stored as integer cents (amount_cents). Currency as VARCHAR(3), default AUD.
IDs:   string UUID4, consistent with the existing users table.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BillingInterval(str, enum.Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    annual = "annual"


class LeadStatus(str, enum.Enum):
    prospect = "prospect"
    free_user = "free_user"
    trialing = "trialing"
    active = "active"
    paused = "paused"
    cancelled = "cancelled"
    past_due = "past_due"
    lost = "lost"


class PipelineStage(str, enum.Enum):
    new_lead = "new_lead"
    contacted = "contacted"
    qualified = "qualified"
    invited = "invited"
    trial_or_free_user = "trial_or_free_user"
    sales_conversation = "sales_conversation"
    checkout_sent = "checkout_sent"
    won = "won"
    lost = "lost"
    nurture = "nurture"


class InterestLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    very_high = "very_high"


class ActivityType(str, enum.Enum):
    note = "note"
    call = "call"
    email = "email"
    message = "message"
    meeting = "meeting"
    follow_up = "follow_up"
    other = "other"


class SubscriptionStatus(str, enum.Enum):
    trialing = "trialing"
    active = "active"
    paused = "paused"
    cancelled = "cancelled"
    past_due = "past_due"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    prices: Mapped[list["SubscriptionPrice"]] = relationship(
        "SubscriptionPrice", back_populates="plan"
    )
    opportunities: Mapped[list["SalesOpportunity"]] = relationship(
        "SalesOpportunity", back_populates="plan"
    )
    subscriptions: Mapped[list["MemberSubscription"]] = relationship(
        "MemberSubscription", back_populates="plan"
    )


class SubscriptionPrice(Base):
    """
    Versioned pricing. When the price changes:
      1. Set is_active=false / effective_to on the old row.
      2. Insert a new row with the new amount and effective_from.
    This preserves the price each member originally joined at via the FK in
    member_subscriptions.price_id.
    """

    __tablename__ = "subscription_prices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )
    # Stored as integer cents — never floats
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    billing_interval: Mapped[BillingInterval] = mapped_column(
        SAEnum(BillingInterval, name="billing_interval_enum", create_type=True),
        nullable=False,
        default=BillingInterval.monthly,
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    # NULL means this price is still current
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    plan: Mapped[SubscriptionPlan] = relationship("SubscriptionPlan", back_populates="prices")
    opportunities: Mapped[list["SalesOpportunity"]] = relationship(
        "SalesOpportunity", back_populates="price"
    )
    subscriptions: Mapped[list["MemberSubscription"]] = relationship(
        "MemberSubscription", back_populates="price"
    )

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="subscription_prices_amount_positive"),
    )


class SalesLead(Base):
    """
    A prospect or lead moving through the sales pipeline.
    Soft-deleted via deleted_at; never hard-deleted.
    """

    __tablename__ = "sales_leads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="lead_status_enum", create_type=True),
        nullable=False,
        default=LeadStatus.prospect,
        server_default="prospect",
    )
    current_stage: Mapped[PipelineStage] = mapped_column(
        SAEnum(PipelineStage, name="pipeline_stage_enum", create_type=True),
        nullable=False,
        default=PipelineStage.new_lead,
        server_default="new_lead",
    )
    interest_level: Mapped[InterestLevel | None] = mapped_column(
        SAEnum(InterestLevel, name="interest_level_enum", create_type=True),
        nullable=True,
    )
    notes_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to users table — set when a lead converts to a paid member
    converted_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Soft delete — do not hard-delete leads
    deleted_at: Mapped[datetime | None] = mapped_column(
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

    opportunities: Mapped[list["SalesOpportunity"]] = relationship(
        "SalesOpportunity", back_populates="lead"
    )
    activities: Mapped[list["SalesActivity"]] = relationship(
        "SalesActivity", back_populates="lead"
    )
    tasks: Mapped[list["SalesTask"]] = relationship(
        "SalesTask", back_populates="lead"
    )


class SalesOpportunity(Base):
    """
    A specific deal/opportunity attached to a lead.
    Tracks the lifecycle from pipeline stage through won/lost.
    """

    __tablename__ = "sales_opportunities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sales_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("subscription_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    price_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("subscription_prices.id", ondelete="SET NULL"),
        nullable=True,
    )
    stage: Mapped[PipelineStage] = mapped_column(
        SAEnum(PipelineStage, name="pipeline_stage_enum", create_type=False),
        nullable=False,
        default=PipelineStage.new_lead,
        server_default="new_lead",
    )
    # Estimated deal value in cents (e.g. annual value or first month)
    estimated_value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0–100
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_close_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    won_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    lost_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    lost_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lead: Mapped[SalesLead] = relationship("SalesLead", back_populates="opportunities")
    plan: Mapped[SubscriptionPlan | None] = relationship(
        "SubscriptionPlan", back_populates="opportunities"
    )
    price: Mapped[SubscriptionPrice | None] = relationship(
        "SubscriptionPrice", back_populates="opportunities"
    )
    activities: Mapped[list["SalesActivity"]] = relationship(
        "SalesActivity", back_populates="opportunity"
    )
    tasks: Mapped[list["SalesTask"]] = relationship(
        "SalesTask", back_populates="opportunity"
    )

    __table_args__ = (
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 100)",
            name="sales_opportunities_probability_range",
        ),
    )


class SalesActivity(Base):
    """
    Immutable audit log of interactions: notes, calls, emails, meetings.
    Activities are never deleted.
    """

    __tablename__ = "sales_activities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sales_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("sales_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    activity_type: Mapped[ActivityType] = mapped_column(
        SAEnum(ActivityType, name="activity_type_enum", create_type=True),
        nullable=False,
        default=ActivityType.note,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    lead: Mapped[SalesLead] = relationship("SalesLead", back_populates="activities")
    opportunity: Mapped[SalesOpportunity | None] = relationship(
        "SalesOpportunity", back_populates="activities"
    )


class SalesTask(Base):
    """
    Follow-up tasks for admin — reminders to call, email, follow up.
    """

    __tablename__ = "sales_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sales_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("sales_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    assigned_to_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    lead: Mapped[SalesLead] = relationship("SalesLead", back_populates="tasks")
    opportunity: Mapped[SalesOpportunity | None] = relationship(
        "SalesOpportunity", back_populates="tasks"
    )


class MemberSubscription(Base):
    """
    Internal subscription record for each paying member.
    price_id is immutable after creation — preserves the price the member
    joined at even if the default price changes later.
    Future: add payment_provider and payment_provider_subscription_id when
    integrating Stripe or another payment processor.
    """

    __tablename__ = "member_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Locked to the price at time of subscription — never changes
    price_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("subscription_prices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, name="subscription_status_enum", create_type=True),
        nullable=False,
        default=SubscriptionStatus.active,
        server_default="active",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Placeholder for future payment provider integration
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
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

    plan: Mapped[SubscriptionPlan] = relationship(
        "SubscriptionPlan", back_populates="subscriptions"
    )
    price: Mapped[SubscriptionPrice] = relationship(
        "SubscriptionPrice", back_populates="subscriptions"
    )
