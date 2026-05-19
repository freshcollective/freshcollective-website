"""
/api/admin/* — routes accessible to authenticated users with role='admin' only.

Normal users receive 403 Forbidden.

Add admin-facing features here:
  - GET    /api/admin/users        — list all users
  - PATCH  /api/admin/users/{id}/role — change a user's role
  etc.
"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin import service
from app.admin.schemas import (
    AdminPlanChangeRequest,
    AdminUserResponse,
    CreatorBillingRow,
    ManualPaymentCreateRequest,
    PaymentTransactionOut,
    RoleUpdateRequest,
)
from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.creator_billing import CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus
from app.models.payment import PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType, PaymentProvider
from app.models.platform import Pathway, Space, SpaceMembership
from app.models.user import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminUserResponse]:
    """List all users. Admin only."""
    users = service.list_users(db)
    return [AdminUserResponse.model_validate(u) for u in users]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    payload: RoleUpdateRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminUserResponse:
    """Change a user's role. Admin only."""
    if payload.role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be 'user' or 'admin'.",
        )
    user = service.set_user_role(db, user_id, payload.role)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return AdminUserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Creator Billing (admin)
# ---------------------------------------------------------------------------

def _creator_managed_space_ids(user_id: str, db: Session) -> set[str]:
    """Return non-archived space IDs managed by this user (same logic as billing endpoint).
    Draft collectives count toward creator plan limits because they still occupy creator capacity."""
    owned = {
        r[0] for r in db.query(Space.id).filter(
            Space.creator_id == user_id,
            Space.status.notin_(["archived"]),
        ).all()
    }
    membered = {
        r[0] for r in db.query(SpaceMembership.space_id)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
            Space.status.notin_(["archived"]),
        ).all()
    }
    return owned | membered


@router.get("/creator-billing", response_model=list[CreatorBillingRow])
def list_creator_billing(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[CreatorBillingRow]:
    """List all creator and admin users with their current plan and usage. Admin only."""
    creators = (
        db.query(User)
        .filter(User.role.in_(["creator", "admin"]))
        .order_by(User.created_at)
        .all()
    )

    # All active plans keyed by id
    plans_by_id = {p.id: p for p in db.query(CreatorPlan).all()}

    # Active subscriptions keyed by user_id
    subs = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.status.in_(["active", "trialing"]))
        .all()
    )
    sub_map: dict[str, CreatorSubscription] = {s.user_id: s for s in subs}

    # Default to cheapest plan when no subscription exists
    fallback_plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )

    rows: list[CreatorBillingRow] = []
    for creator in creators:
        sub = sub_map.get(creator.id)
        plan = (plans_by_id.get(sub.creator_plan_id) if sub else None) or fallback_plan
        if not plan:
            continue

        sub_status = "none"
        if sub:
            sub_status = sub.status.value if hasattr(sub.status, "value") else str(sub.status)

        space_ids = _creator_managed_space_ids(creator.id, db)
        pathways_used = (
            db.query(func.count(Pathway.id))
            .filter(Pathway.space_id.in_(space_ids))
            .scalar() or 0
        ) if space_ids else 0

        rows.append(CreatorBillingRow(
            user_id=creator.id,
            name=creator.name,
            email=creator.email,
            current_plan_name=plan.name,
            current_plan_slug=plan.slug,
            monthly_price_cents=plan.monthly_price_cents,
            currency=plan.currency,
            transaction_fee_basis_points=plan.transaction_fee_basis_points,
            collective_limit=plan.collective_limit,
            subscription_status=sub_status,
            collectives_used=len(space_ids),
            pathways_used=pathways_used,
            joined_at=creator.created_at,
        ))

    return rows


@router.patch("/creator-billing/{user_id}/plan", response_model=CreatorBillingRow)
def change_creator_plan(
    user_id: str,
    body: AdminPlanChangeRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CreatorBillingRow:
    """Manually change a creator's plan. Admin only. Does not touch Stripe."""
    target = db.query(User).filter(User.id == user_id, User.role.in_(["creator", "admin"])).first()
    if not target:
        raise HTTPException(status_code=404, detail="Creator not found.")

    plan = db.query(CreatorPlan).filter(CreatorPlan.slug == body.creator_plan_slug, CreatorPlan.is_active.is_(True)).first()
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{body.creator_plan_slug}' not found.")

    sub = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.user_id == user_id)
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )

    if sub:
        # TODO: Add plan change audit log table when billing history is needed
        sub.creator_plan_id = plan.id
        sub.status = CreatorSubscriptionStatus.active
        sub.updated_at = datetime.utcnow()
        # Preserve any existing Stripe fields — do not overwrite with None
    else:
        sub = CreatorSubscription(
            id=str(uuid4()),
            user_id=user_id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(),
        )
        db.add(sub)

    db.commit()
    db.refresh(sub)

    space_ids = _creator_managed_space_ids(user_id, db)
    pathways_used = (
        db.query(func.count(Pathway.id)).filter(Pathway.space_id.in_(space_ids)).scalar() or 0
    ) if space_ids else 0

    return CreatorBillingRow(
        user_id=target.id,
        name=target.name,
        email=target.email,
        current_plan_name=plan.name,
        current_plan_slug=plan.slug,
        monthly_price_cents=plan.monthly_price_cents,
        currency=plan.currency,
        transaction_fee_basis_points=plan.transaction_fee_basis_points,
        collective_limit=plan.collective_limit,
        subscription_status="active",
        collectives_used=len(space_ids),
        pathways_used=pathways_used,
        joined_at=target.created_at,
    )


@router.get("/stats")
async def get_stats(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Basic platform stats. Admin only."""
    from app.models.user import User as UserModel

    total = db.query(UserModel).count()
    admins = db.query(UserModel).filter(UserModel.role == "admin").count()
    return {"total_users": total, "admin_count": admins, "member_count": total - admins}


# ---------------------------------------------------------------------------
# Payment Transactions
# ---------------------------------------------------------------------------

@router.get("/payments", response_model=list[PaymentTransactionOut])
def list_payments(
    status: str | None = None,
    transaction_type: str | None = None,
    creator_user_id: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[PaymentTransactionOut]:
    """List all payment transactions with optional filters. Admin only."""
    q = db.query(PaymentTransaction)
    if status:
        q = q.filter(PaymentTransaction.status == status)
    if transaction_type:
        q = q.filter(PaymentTransaction.transaction_type == transaction_type)
    if creator_user_id:
        q = q.filter(PaymentTransaction.creator_user_id == creator_user_id)
    if space_id:
        q = q.filter(PaymentTransaction.space_id == space_id)
    if pathway_id:
        q = q.filter(PaymentTransaction.pathway_id == pathway_id)
    rows = q.order_by(PaymentTransaction.created_at.desc()).all()
    return [PaymentTransactionOut.model_validate(r) for r in rows]


@router.post("/payments/manual", response_model=PaymentTransactionOut, status_code=201)
def create_manual_payment(
    body: ManualPaymentCreateRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> PaymentTransactionOut:
    """
    Create a manual placeholder transaction for admin record-keeping.
    Does not grant access automatically — entitlement linkage must be done
    explicitly via the entitlement endpoints when needed.
    """
    # Validate enums before accepting
    valid_types = {e.value for e in PaymentTransactionType}
    valid_statuses = {e.value for e in PaymentTransactionStatus}
    valid_providers = {e.value for e in PaymentProvider}

    if body.transaction_type not in valid_types:
        raise HTTPException(status_code=422, detail=f"Invalid transaction_type '{body.transaction_type}'.")
    if body.status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status '{body.status}'.")
    if body.payment_provider not in valid_providers:
        raise HTTPException(status_code=422, detail=f"Invalid payment_provider '{body.payment_provider}'.")

    txn = PaymentTransaction(
        id=str(uuid4()),
        transaction_type=body.transaction_type,
        status=body.status,
        payment_provider=body.payment_provider,
        payer_user_id=body.payer_user_id,
        creator_user_id=body.creator_user_id,
        space_id=body.space_id,
        pathway_id=body.pathway_id,
        entitlement_id=body.entitlement_id,
        creator_plan_id=body.creator_plan_id,
        creator_subscription_id=body.creator_subscription_id,
        currency=body.currency,
        gross_amount_cents=body.gross_amount_cents,
        platform_fee_basis_points=body.platform_fee_basis_points,
        platform_fee_cents=body.platform_fee_cents,
        net_creator_amount_cents=body.net_creator_amount_cents,
        net_platform_amount_cents=body.net_platform_amount_cents,
        notes=body.notes,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return PaymentTransactionOut.model_validate(txn)
