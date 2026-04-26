"""
Service layer for the admin sales pipeline.
All business logic lives here; routes only handle HTTP concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sales import (
    BillingInterval,
    MemberSubscription,
    PipelineStage,
    SalesActivity,
    SalesLead,
    SalesOpportunity,
    SalesTask,
    SubscriptionPlan,
    SubscriptionPrice,
    SubscriptionStatus,
)
from app.sales.schemas import (
    ActivityCreate,
    LeadCreate,
    LeadUpdate,
    OpportunityCreate,
    OpportunityUpdate,
    PlanCreate,
    PriceCreate,
    StageUpdate,
    SubscriptionCreate,
    SubscriptionUpdate,
    TaskCreate,
    TaskUpdate,
    SalesSummaryResponse,
    LeadsbyStageItem,
    OpportunitiesByStageItem,
    UpcomingTask,
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_cents(cents: int, currency: str = "AUD") -> str:
    return f"{currency} ${cents / 100:.2f}"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def list_plans(db: Session) -> list[SubscriptionPlan]:
    return db.query(SubscriptionPlan).order_by(SubscriptionPlan.created_at.desc()).all()


def create_plan(db: Session, data: PlanCreate) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        id=_new_id(),
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_plan(db: Session, plan_id: str) -> SubscriptionPlan | None:
    return db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def list_prices(db: Session, plan_id: str | None = None) -> list[SubscriptionPrice]:
    q = db.query(SubscriptionPrice)
    if plan_id:
        q = q.filter(SubscriptionPrice.plan_id == plan_id)
    return q.order_by(SubscriptionPrice.effective_from.desc()).all()


def create_price(db: Session, data: PriceCreate, admin_user_id: str | None = None) -> SubscriptionPrice:
    now = _now()
    effective_from = data.effective_from or now

    # Deactivate any existing active prices for this plan+interval when new one starts
    existing = (
        db.query(SubscriptionPrice)
        .filter(
            SubscriptionPrice.plan_id == data.plan_id,
            SubscriptionPrice.billing_interval == data.billing_interval,
            SubscriptionPrice.is_active.is_(True),
            SubscriptionPrice.effective_to.is_(None),
        )
        .all()
    )
    for old_price in existing:
        old_price.is_active = False
        old_price.effective_to = effective_from

    price = SubscriptionPrice(
        id=_new_id(),
        plan_id=data.plan_id,
        currency=data.currency.upper(),
        amount_cents=data.amount_cents,
        billing_interval=data.billing_interval,
        effective_from=effective_from,
        effective_to=None,
        is_active=True,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price


def get_active_price(
    db: Session,
    plan_id: str,
    billing_interval: BillingInterval = BillingInterval.monthly,
) -> SubscriptionPrice | None:
    return (
        db.query(SubscriptionPrice)
        .filter(
            SubscriptionPrice.plan_id == plan_id,
            SubscriptionPrice.billing_interval == billing_interval,
            SubscriptionPrice.is_active.is_(True),
            SubscriptionPrice.effective_to.is_(None),
        )
        .first()
    )


def deactivate_price(db: Session, price_id: str) -> SubscriptionPrice | None:
    price = db.query(SubscriptionPrice).filter(SubscriptionPrice.id == price_id).first()
    if not price:
        return None
    price.is_active = False
    price.effective_to = _now()
    db.commit()
    db.refresh(price)
    return price


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def list_leads(
    db: Session,
    include_deleted: bool = False,
    status: str | None = None,
    stage: str | None = None,
) -> list[SalesLead]:
    q = db.query(SalesLead)
    if not include_deleted:
        q = q.filter(SalesLead.deleted_at.is_(None))
    if status:
        q = q.filter(SalesLead.status == status)
    if stage:
        q = q.filter(SalesLead.current_stage == stage)
    return q.order_by(SalesLead.created_at.desc()).all()


def create_lead(db: Session, data: LeadCreate) -> SalesLead:
    lead = SalesLead(
        id=_new_id(),
        first_name=data.first_name,
        last_name=data.last_name,
        email=str(data.email),
        phone=data.phone,
        source=data.source,
        status=data.status,
        current_stage=data.current_stage,
        interest_level=data.interest_level,
        notes_summary=data.notes_summary,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def get_lead(db: Session, lead_id: str) -> SalesLead | None:
    return (
        db.query(SalesLead)
        .filter(SalesLead.id == lead_id, SalesLead.deleted_at.is_(None))
        .first()
    )


def update_lead(db: Session, lead: SalesLead, data: LeadUpdate) -> SalesLead:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "email" and value is not None:
            value = str(value)
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


def soft_delete_lead(db: Session, lead: SalesLead) -> SalesLead:
    lead.deleted_at = _now()
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------

def list_opportunities(
    db: Session,
    lead_id: str | None = None,
    stage: str | None = None,
) -> list[SalesOpportunity]:
    q = db.query(SalesOpportunity)
    if lead_id:
        q = q.filter(SalesOpportunity.lead_id == lead_id)
    if stage:
        q = q.filter(SalesOpportunity.stage == stage)
    return q.order_by(SalesOpportunity.created_at.desc()).all()


def create_opportunity(db: Session, data: OpportunityCreate) -> SalesOpportunity:
    opp = SalesOpportunity(
        id=_new_id(),
        lead_id=data.lead_id,
        plan_id=data.plan_id,
        price_id=data.price_id,
        stage=data.stage,
        estimated_value_cents=data.estimated_value_cents,
        probability=data.probability,
        expected_close_date=data.expected_close_date,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def get_opportunity(db: Session, opportunity_id: str) -> SalesOpportunity | None:
    return db.query(SalesOpportunity).filter(SalesOpportunity.id == opportunity_id).first()


def update_opportunity(
    db: Session, opp: SalesOpportunity, data: OpportunityUpdate
) -> SalesOpportunity:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return opp


def move_opportunity_stage(
    db: Session, opp: SalesOpportunity, data: StageUpdate
) -> SalesOpportunity:
    now = _now()
    opp.stage = data.stage
    if data.stage == PipelineStage.won:
        opp.won_at = now
        opp.lost_at = None
        opp.lost_reason = None
    elif data.stage == PipelineStage.lost:
        opp.lost_at = now
        opp.lost_reason = data.lost_reason
        opp.won_at = None
    else:
        # Moving back to an open stage clears won/lost timestamps
        pass
    db.commit()
    db.refresh(opp)
    return opp


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

def list_activities(db: Session, lead_id: str) -> list[SalesActivity]:
    return (
        db.query(SalesActivity)
        .filter(SalesActivity.lead_id == lead_id)
        .order_by(SalesActivity.occurred_at.desc())
        .all()
    )


def create_activity(
    db: Session,
    lead_id: str,
    data: ActivityCreate,
    created_by_user_id: str | None = None,
) -> SalesActivity:
    activity = SalesActivity(
        id=_new_id(),
        lead_id=lead_id,
        opportunity_id=data.opportunity_id,
        activity_type=data.activity_type,
        title=data.title,
        body=data.body,
        occurred_at=data.occurred_at or _now(),
        created_by_user_id=created_by_user_id,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def list_tasks(
    db: Session,
    lead_id: str | None = None,
    completed: bool | None = None,
) -> list[SalesTask]:
    q = db.query(SalesTask)
    if lead_id:
        q = q.filter(SalesTask.lead_id == lead_id)
    if completed is False:
        q = q.filter(SalesTask.completed_at.is_(None))
    elif completed is True:
        q = q.filter(SalesTask.completed_at.isnot(None))
    return q.order_by(SalesTask.due_at.asc().nullslast()).all()


def create_task(
    db: Session,
    data: TaskCreate,
    created_by_user_id: str | None = None,
) -> SalesTask:
    task = SalesTask(
        id=_new_id(),
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
        title=data.title,
        description=data.description,
        due_at=data.due_at,
        assigned_to_user_id=data.assigned_to_user_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: str) -> SalesTask | None:
    return db.query(SalesTask).filter(SalesTask.id == task_id).first()


def update_task(db: Session, task: SalesTask, data: TaskUpdate) -> SalesTask:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task: SalesTask) -> SalesTask:
    task.completed_at = _now()
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Member subscriptions
# ---------------------------------------------------------------------------

def list_subscriptions(
    db: Session,
    user_id: str | None = None,
    status: str | None = None,
) -> list[MemberSubscription]:
    q = db.query(MemberSubscription)
    if user_id:
        q = q.filter(MemberSubscription.user_id == user_id)
    if status:
        q = q.filter(MemberSubscription.status == status)
    return q.order_by(MemberSubscription.started_at.desc()).all()


def create_subscription(db: Session, data: SubscriptionCreate) -> MemberSubscription:
    now = _now()
    sub = MemberSubscription(
        id=_new_id(),
        user_id=data.user_id,
        plan_id=data.plan_id,
        price_id=data.price_id,
        status=data.status,
        started_at=data.started_at or now,
        current_period_start=data.current_period_start,
        current_period_end=data.current_period_end,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_subscription(db: Session, subscription_id: str) -> MemberSubscription | None:
    return (
        db.query(MemberSubscription)
        .filter(MemberSubscription.id == subscription_id)
        .first()
    )


def update_subscription(
    db: Session, sub: MemberSubscription, data: SubscriptionUpdate
) -> MemberSubscription:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


# ---------------------------------------------------------------------------
# Summary / reporting
# ---------------------------------------------------------------------------

def get_summary(db: Session) -> SalesSummaryResponse:
    now = _now()

    # ── Leads ──────────────────────────────────────────────
    total_leads: int = (
        db.query(func.count(SalesLead.id))
        .filter(SalesLead.deleted_at.is_(None))
        .scalar()
        or 0
    )

    leads_by_stage_rows = (
        db.query(SalesLead.current_stage, func.count(SalesLead.id))
        .filter(SalesLead.deleted_at.is_(None))
        .group_by(SalesLead.current_stage)
        .all()
    )
    leads_by_stage = [
        LeadsbyStageItem(stage=row[0].value if hasattr(row[0], "value") else str(row[0]), count=row[1])
        for row in leads_by_stage_rows
    ]

    # ── Opportunities ───────────────────────────────────────
    open_opps: int = (
        db.query(func.count(SalesOpportunity.id))
        .filter(
            SalesOpportunity.stage.notin_([PipelineStage.won, PipelineStage.lost])
        )
        .scalar()
        or 0
    )
    won_opps: int = (
        db.query(func.count(SalesOpportunity.id))
        .filter(SalesOpportunity.stage == PipelineStage.won)
        .scalar()
        or 0
    )
    lost_opps: int = (
        db.query(func.count(SalesOpportunity.id))
        .filter(SalesOpportunity.stage == PipelineStage.lost)
        .scalar()
        or 0
    )

    opps_by_stage_rows = (
        db.query(SalesOpportunity.stage, func.count(SalesOpportunity.id))
        .group_by(SalesOpportunity.stage)
        .all()
    )
    opps_by_stage = [
        OpportunitiesByStageItem(
            stage=row[0].value if hasattr(row[0], "value") else str(row[0]),
            count=row[1],
        )
        for row in opps_by_stage_rows
    ]

    # Pipeline value = sum of estimated_value_cents for open opportunities
    pipeline_value_cents: int = (
        db.query(func.coalesce(func.sum(SalesOpportunity.estimated_value_cents), 0))
        .filter(
            SalesOpportunity.stage.notin_([PipelineStage.won, PipelineStage.lost]),
            SalesOpportunity.estimated_value_cents.isnot(None),
        )
        .scalar()
        or 0
    )

    # ── Subscriptions / MRR ────────────────────────────────
    # MRR = sum of amount_cents for all active monthly subscriptions
    active_sub_count: int = (
        db.query(func.count(MemberSubscription.id))
        .filter(MemberSubscription.status == SubscriptionStatus.active)
        .scalar()
        or 0
    )

    mrr_cents: int = (
        db.query(func.coalesce(func.sum(SubscriptionPrice.amount_cents), 0))
        .join(MemberSubscription, MemberSubscription.price_id == SubscriptionPrice.id)
        .filter(
            MemberSubscription.status == SubscriptionStatus.active,
            SubscriptionPrice.billing_interval == BillingInterval.monthly,
        )
        .scalar()
        or 0
    )

    # ── Tasks ───────────────────────────────────────────────
    open_tasks: int = (
        db.query(func.count(SalesTask.id))
        .filter(SalesTask.completed_at.is_(None))
        .scalar()
        or 0
    )
    overdue_tasks: int = (
        db.query(func.count(SalesTask.id))
        .filter(
            SalesTask.completed_at.is_(None),
            SalesTask.due_at < now,
        )
        .scalar()
        or 0
    )

    upcoming_task_rows = (
        db.query(SalesTask)
        .filter(
            SalesTask.completed_at.is_(None),
            SalesTask.due_at >= now,
        )
        .order_by(SalesTask.due_at.asc())
        .limit(10)
        .all()
    )
    upcoming_tasks = [UpcomingTask.model_validate(t) for t in upcoming_task_rows]

    # ── Determine display currency ──────────────────────────
    # Use the currency of the first active price; fallback to AUD
    sample_price = (
        db.query(SubscriptionPrice)
        .filter(SubscriptionPrice.is_active.is_(True))
        .first()
    )
    currency = sample_price.currency if sample_price else "AUD"

    return SalesSummaryResponse(
        total_leads=total_leads,
        leads_by_stage=leads_by_stage,
        open_opportunities=open_opps,
        won_opportunities=won_opps,
        lost_opportunities=lost_opps,
        opportunities_by_stage=opps_by_stage,
        pipeline_value_cents=pipeline_value_cents,
        pipeline_value_display=_format_cents(pipeline_value_cents, currency),
        active_subscriptions=active_sub_count,
        mrr_cents=mrr_cents,
        mrr_display=_format_cents(mrr_cents, currency),
        open_tasks=open_tasks,
        overdue_tasks=overdue_tasks,
        upcoming_tasks=upcoming_tasks,
    )
