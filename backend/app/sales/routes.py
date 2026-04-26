"""
Admin sales pipeline routes — all require authenticated admin role.

Prefix: /api/admin/sales
Tags:   admin-sales

Security:
  Every route uses Depends(get_admin_user) which:
  - Returns 401 if no valid session cookie
  - Returns 403 if the authenticated user is not role='admin'
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.user import User
from app.sales import service
from app.sales.schemas import (
    ActivityCreate,
    ActivityResponse,
    LeadCreate,
    LeadResponse,
    LeadUpdate,
    OpportunityCreate,
    OpportunityResponse,
    OpportunityUpdate,
    PlanCreate,
    PlanResponse,
    PriceCreate,
    PriceResponse,
    SalesSummaryResponse,
    StageUpdate,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)

router = APIRouter(prefix="/api/admin/sales", tags=["admin-sales"])


# ─────────────────────────────────────────────────────────────────────────────
# Plans
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanResponse])
def list_plans(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[PlanResponse]:
    """List all subscription plans. Admin only."""
    plans = service.list_plans(db)
    return [PlanResponse.model_validate(p) for p in plans]


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> PlanResponse:
    """Create a subscription plan. Admin only."""
    plan = service.create_plan(db, payload)
    return PlanResponse.model_validate(plan)


# ─────────────────────────────────────────────────────────────────────────────
# Prices
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/prices", response_model=list[PriceResponse])
def list_prices(
    plan_id: str | None = Query(default=None, description="Filter by plan ID"),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[PriceResponse]:
    """List subscription prices. Optionally filter by plan_id. Admin only."""
    prices = service.list_prices(db, plan_id=plan_id)
    return [PriceResponse.model_validate(p) for p in prices]


@router.post("/prices", response_model=PriceResponse, status_code=status.HTTP_201_CREATED)
def create_price(
    payload: PriceCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> PriceResponse:
    """
    Create a new price for a plan.

    Creating a new active price for the same plan+billing_interval will
    automatically deactivate the previous active price and set its effective_to.
    Admin only.
    """
    # Validate plan exists
    plan = service.get_plan(db, payload.plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{payload.plan_id}' not found.",
        )
    price = service.create_price(db, payload)
    return PriceResponse.model_validate(price)


@router.patch(
    "/prices/{price_id}/deactivate",
    response_model=PriceResponse,
)
def deactivate_price(
    price_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> PriceResponse:
    """Deactivate a price. Admin only."""
    price = service.deactivate_price(db, price_id)
    if not price:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price not found.")
    return PriceResponse.model_validate(price)


# ─────────────────────────────────────────────────────────────────────────────
# Leads
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads", response_model=list[LeadResponse])
def list_leads(
    status: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[LeadResponse]:
    """List sales leads. Optionally filter by status or stage. Admin only."""
    leads = service.list_leads(db, include_deleted=include_deleted, status=status, stage=stage)
    return [LeadResponse.model_validate(l) for l in leads]


@router.post("/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Create a new sales lead. Admin only."""
    lead = service.create_lead(db, payload)
    return LeadResponse.model_validate(lead)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(
    lead_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Get a single lead. Admin only."""
    lead = service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    return LeadResponse.model_validate(lead)


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Update a lead. Admin only."""
    lead = service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    lead = service.update_lead(db, lead, payload)
    return LeadResponse.model_validate(lead)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    lead_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a lead. The record is retained with deleted_at set. Admin only."""
    lead = service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    service.soft_delete_lead(db, lead)


# ─────────────────────────────────────────────────────────────────────────────
# Opportunities
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/opportunities", response_model=list[OpportunityResponse])
def list_opportunities(
    lead_id: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[OpportunityResponse]:
    """List opportunities. Optionally filter by lead or stage. Admin only."""
    opps = service.list_opportunities(db, lead_id=lead_id, stage=stage)
    return [OpportunityResponse.model_validate(o) for o in opps]


@router.post(
    "/opportunities",
    response_model=OpportunityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_opportunity(
    payload: OpportunityCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> OpportunityResponse:
    """Create a new opportunity. Admin only."""
    lead = service.get_lead(db, payload.lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found."
        )
    opp = service.create_opportunity(db, payload)
    return OpportunityResponse.model_validate(opp)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
def get_opportunity(
    opportunity_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> OpportunityResponse:
    """Get a single opportunity. Admin only."""
    opp = service.get_opportunity(db, opportunity_id)
    if not opp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found."
        )
    return OpportunityResponse.model_validate(opp)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
def update_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> OpportunityResponse:
    """Update an opportunity. Admin only."""
    opp = service.get_opportunity(db, opportunity_id)
    if not opp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found."
        )
    opp = service.update_opportunity(db, opp, payload)
    return OpportunityResponse.model_validate(opp)


@router.patch(
    "/opportunities/{opportunity_id}/stage",
    response_model=OpportunityResponse,
)
def move_opportunity_stage(
    opportunity_id: str,
    payload: StageUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> OpportunityResponse:
    """
    Move an opportunity to a new pipeline stage.
    Moving to 'won' sets won_at; moving to 'lost' sets lost_at and optionally lost_reason.
    Admin only.
    """
    opp = service.get_opportunity(db, opportunity_id)
    if not opp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found."
        )
    opp = service.move_opportunity_stage(db, opp, payload)
    return OpportunityResponse.model_validate(opp)


# ─────────────────────────────────────────────────────────────────────────────
# Activities
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/leads/{lead_id}/activities",
    response_model=list[ActivityResponse],
)
def list_activities(
    lead_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[ActivityResponse]:
    """List all activities for a lead. Admin only."""
    lead = service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    activities = service.list_activities(db, lead_id)
    return [ActivityResponse.model_validate(a) for a in activities]


@router.post(
    "/leads/{lead_id}/activities",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_activity(
    lead_id: str,
    payload: ActivityCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ActivityResponse:
    """Log an activity for a lead. Admin only."""
    lead = service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    activity = service.create_activity(db, lead_id, payload, created_by_user_id=admin.id)
    return ActivityResponse.model_validate(activity)


# ─────────────────────────────────────────────────────────────────────────────
# Tasks
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    lead_id: str | None = Query(default=None),
    completed: bool | None = Query(default=None),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[TaskResponse]:
    """List follow-up tasks. Filter by lead or completion status. Admin only."""
    tasks = service.list_tasks(db, lead_id=lead_id, completed=completed)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Create a follow-up task. Admin only."""
    lead = service.get_lead(db, payload.lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    task = service.create_task(db, payload, created_by_user_id=admin.id)
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Update a task. Admin only."""
    task = service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    task = service.update_task(db, task, payload)
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Mark a task as complete. Admin only."""
    task = service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task is already completed.",
        )
    task = service.complete_task(db, task)
    return TaskResponse.model_validate(task)


# ─────────────────────────────────────────────────────────────────────────────
# Member subscriptions
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/subscriptions", response_model=list[SubscriptionResponse])
def list_subscriptions(
    user_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[SubscriptionResponse]:
    """List member subscriptions. Admin only."""
    subs = service.list_subscriptions(db, user_id=user_id, status=status)
    return [SubscriptionResponse.model_validate(s) for s in subs]


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    payload: SubscriptionCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Create a member subscription record. Admin only."""
    # Validate plan and price exist
    plan = service.get_plan(db, payload.plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{payload.plan_id}' not found.",
        )
    sub = service.create_subscription(db, payload)
    return SubscriptionResponse.model_validate(sub)


@router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
def update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Update a subscription record (status, billing periods, etc.). Admin only."""
    sub = service.get_subscription(db, subscription_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found."
        )
    sub = service.update_subscription(db, sub, payload)
    return SubscriptionResponse.model_validate(sub)


# ─────────────────────────────────────────────────────────────────────────────
# Summary / reporting
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=SalesSummaryResponse)
def get_summary(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SalesSummaryResponse:
    """
    Admin sales dashboard summary.

    Returns:
      - total leads, leads by stage
      - open/won/lost opportunities, opportunities by stage
      - pipeline estimated value (open opportunities)
      - active subscription count
      - current MRR (sum of monthly subscription prices)
      - open and overdue tasks, upcoming task list
    Admin only.
    """
    return service.get_summary(db)
