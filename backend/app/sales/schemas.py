"""
Pydantic request/response schemas for the admin sales pipeline.

All money fields:
  - raw integer cents in API (amount_cents: int)
  - formatted display string added alongside for convenience (amount_display: str)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator

from app.models.sales import (
    ActivityType,
    BillingInterval,
    InterestLevel,
    LeadStatus,
    PipelineStage,
    SubscriptionStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_cents(amount_cents: int, currency: str = "AUD") -> str:
    """Return a human-readable money string, e.g. 'AUD $39.00'."""
    dollars = amount_cents / 100
    return f"{currency} ${dollars:.2f}"


# ---------------------------------------------------------------------------
# Subscription plans
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: bool = True


class PlanResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Subscription prices
# ---------------------------------------------------------------------------

class PriceCreate(BaseModel):
    plan_id: str
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    amount_cents: int = Field(..., gt=0, description="Price in integer cents, e.g. 3900 for $39.00")
    billing_interval: BillingInterval = BillingInterval.monthly
    effective_from: Optional[datetime] = None  # defaults to now in service

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()


class PriceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    plan_id: str
    currency: str
    amount_cents: int
    billing_interval: BillingInterval
    effective_from: datetime
    effective_to: Optional[datetime]
    is_active: bool
    created_at: datetime

    @computed_field
    @property
    def amount_display(self) -> str:
        return _format_cents(self.amount_cents, self.currency)


# ---------------------------------------------------------------------------
# Sales leads
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    source: Optional[str] = Field(None, max_length=100)
    status: LeadStatus = LeadStatus.prospect
    current_stage: PipelineStage = PipelineStage.new_lead
    interest_level: Optional[InterestLevel] = None
    notes_summary: Optional[str] = None


class LeadUpdate(BaseModel):
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    source: Optional[str] = Field(None, max_length=100)
    status: Optional[LeadStatus] = None
    current_stage: Optional[PipelineStage] = None
    interest_level: Optional[InterestLevel] = None
    notes_summary: Optional[str] = None
    converted_user_id: Optional[str] = None


class LeadResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    first_name: Optional[str]
    last_name: Optional[str]
    email: str
    phone: Optional[str]
    source: Optional[str]
    status: LeadStatus
    current_stage: PipelineStage
    interest_level: Optional[InterestLevel]
    notes_summary: Optional[str]
    converted_user_id: Optional[str]
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Sales opportunities
# ---------------------------------------------------------------------------

class OpportunityCreate(BaseModel):
    lead_id: str
    plan_id: Optional[str] = None
    price_id: Optional[str] = None
    stage: PipelineStage = PipelineStage.new_lead
    estimated_value_cents: Optional[int] = Field(None, gt=0)
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[datetime] = None


class OpportunityUpdate(BaseModel):
    plan_id: Optional[str] = None
    price_id: Optional[str] = None
    stage: Optional[PipelineStage] = None
    estimated_value_cents: Optional[int] = Field(None, gt=0)
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[datetime] = None
    lost_reason: Optional[str] = Field(None, max_length=500)


class StageUpdate(BaseModel):
    stage: PipelineStage
    lost_reason: Optional[str] = Field(None, max_length=500)


class OpportunityResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    lead_id: str
    plan_id: Optional[str]
    price_id: Optional[str]
    stage: PipelineStage
    estimated_value_cents: Optional[int]
    probability: Optional[int]
    expected_close_date: Optional[datetime]
    won_at: Optional[datetime]
    lost_at: Optional[datetime]
    lost_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Sales activities
# ---------------------------------------------------------------------------

class ActivityCreate(BaseModel):
    opportunity_id: Optional[str] = None
    activity_type: ActivityType = ActivityType.note
    title: str = Field(..., min_length=1, max_length=300)
    body: Optional[str] = None
    occurred_at: Optional[datetime] = None  # defaults to now in service


class ActivityResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    lead_id: str
    opportunity_id: Optional[str]
    activity_type: ActivityType
    title: str
    body: Optional[str]
    occurred_at: datetime
    created_by_user_id: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Sales tasks
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    lead_id: str
    opportunity_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    assigned_to_user_id: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    assigned_to_user_id: Optional[str] = None


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    lead_id: str
    opportunity_id: Optional[str]
    title: str
    description: Optional[str]
    due_at: Optional[datetime]
    completed_at: Optional[datetime]
    assigned_to_user_id: Optional[str]
    created_by_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Member subscriptions
# ---------------------------------------------------------------------------

class SubscriptionCreate(BaseModel):
    user_id: str
    plan_id: str
    price_id: str
    status: SubscriptionStatus = SubscriptionStatus.active
    started_at: Optional[datetime] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None


class SubscriptionUpdate(BaseModel):
    status: Optional[SubscriptionStatus] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = Field(None, max_length=500)
    payment_provider: Optional[str] = Field(None, max_length=50)
    payment_provider_subscription_id: Optional[str] = Field(None, max_length=200)


class SubscriptionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    plan_id: str
    price_id: str
    status: SubscriptionStatus
    started_at: datetime
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    payment_provider: Optional[str]
    payment_provider_subscription_id: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Summary / reporting
# ---------------------------------------------------------------------------

class LeadsbyStageItem(BaseModel):
    stage: str
    count: int


class OpportunitiesByStageItem(BaseModel):
    stage: str
    count: int


class UpcomingTask(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    lead_id: str
    due_at: Optional[datetime]


class SalesSummaryResponse(BaseModel):
    # Leads
    total_leads: int
    leads_by_stage: list[LeadsbyStageItem]

    # Opportunities
    open_opportunities: int
    won_opportunities: int
    lost_opportunities: int
    opportunities_by_stage: list[OpportunitiesByStageItem]

    # Pipeline value (estimated, open opportunities only)
    pipeline_value_cents: int
    pipeline_value_display: str

    # Subscriptions
    active_subscriptions: int
    mrr_cents: int
    mrr_display: str

    # Tasks
    open_tasks: int
    overdue_tasks: int
    upcoming_tasks: list[UpcomingTask]
