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
    AdminAccessRequestRow,
    AdminAccessResponse,
    AdminCollectiveRow,
    AdminCreatorPlanRow,
    AdminCreatorRow,
    AdminCreatorSubscriptionRow,
    AdminInvitationRow,
    AdminPaymentSummary,
    AdminPlanChangeRequest,
    AdminPlatformOverview,
    AdminRevenueByCreatorRow,
    AdminRevenueSummary,
    AdminUserResponse,
    AdminUserRow,
    CreatorBillingRow,
    ManualPaymentCreateRequest,
    ManualPathwayPurchaseRequest,
    ManualPathwayPurchaseResult,
    PaymentTransactionOut,
    RoleUpdateRequest,
    SimplePaidPathwayRow,
    SimpleUserRow,
)
from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.creator_billing import CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentProvider,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Event,
    Pathway,
    PathwayEntitlement,
    Space,
    SpaceAccessRequest,
    SpaceInvitation,
    SpaceMembership,
    SpaceResource,
)
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

# Revenue-relevant transaction types — excludes creator subscription payments
_MEMBER_TXN_TYPES = {
    PaymentTransactionType.member_pathway_purchase,
    PaymentTransactionType.member_collective_purchase,
    PaymentTransactionType.member_pathway_subscription,
    PaymentTransactionType.member_collective_subscription,
}
_REVENUE_STATUSES = {PaymentTransactionStatus.succeeded}
_REFUNDED_STATUSES = {
    PaymentTransactionStatus.refunded,
    PaymentTransactionStatus.partially_refunded,
}


@router.get("/payments/summary", response_model=AdminPaymentSummary)
def get_admin_payment_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    creator_user_id: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminPaymentSummary:
    """
    Platform-wide payment summary for admin earnings dashboard.
    Revenue totals are based on succeeded member-purchase transactions only.
    Creator subscription payments are excluded from revenue totals.
    Admin only.
    """
    from datetime import date

    def _base_q(statuses: set | None = None):
        q = db.query(PaymentTransaction).filter(
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES])
        )
        if statuses:
            q = q.filter(PaymentTransaction.status.in_([s.value for s in statuses]))
        if date_from:
            try:
                q = q.filter(PaymentTransaction.created_at >= date.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                q = q.filter(PaymentTransaction.created_at <= date.fromisoformat(date_to))
            except ValueError:
                pass
        if creator_user_id:
            q = q.filter(PaymentTransaction.creator_user_id == creator_user_id)
        if space_id:
            q = q.filter(PaymentTransaction.space_id == space_id)
        if pathway_id:
            q = q.filter(PaymentTransaction.pathway_id == pathway_id)
        return q

    succeeded = _base_q({PaymentTransactionStatus.succeeded}).all()
    total_gross = sum(r.gross_amount_cents for r in succeeded)
    total_fee = sum(r.platform_fee_cents for r in succeeded)
    total_net = sum(r.net_creator_amount_cents or 0 for r in succeeded)
    total_processing = sum(r.processing_fee_cents or 0 for r in succeeded)
    pending_payout = sum(
        r.net_creator_amount_cents or 0
        for r in succeeded
        if r.payout_status == PayoutStatus.pending
    )

    all_rows = _base_q().all()
    return AdminPaymentSummary(
        total_gross_amount_cents=total_gross,
        total_platform_fee_cents=total_fee,
        total_creator_net_amount_cents=total_net,
        total_processing_fee_cents=total_processing,
        pending_payout_cents=pending_payout,
        succeeded_count=len(succeeded),
        refunded_count=sum(1 for r in all_rows if r.status in (
            PaymentTransactionStatus.refunded, PaymentTransactionStatus.partially_refunded
        )),
        disputed_count=sum(1 for r in all_rows if r.status == PaymentTransactionStatus.disputed),
        pending_count=sum(1 for r in all_rows if r.status == PaymentTransactionStatus.pending),
        failed_count=sum(1 for r in all_rows if r.status == PaymentTransactionStatus.failed),
    )


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


# ---------------------------------------------------------------------------
# Simple list helpers (for admin form dropdowns)
# ---------------------------------------------------------------------------

@router.get("/users/simple", response_model=list[SimpleUserRow])
def list_users_simple(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[SimpleUserRow]:
    """All users as id/name/email rows for dropdown population. Admin only."""
    users = db.query(User).order_by(User.name).all()
    return [SimpleUserRow.model_validate(u) for u in users]


@router.get("/pathways/paid-simple", response_model=list[SimplePaidPathwayRow])
def list_paid_pathways_simple(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[SimplePaidPathwayRow]:
    """All paid pathways (one_time / subscription) with creator fee bps. Admin only."""
    pathways = (
        db.query(Pathway)
        .join(Space, Space.id == Pathway.space_id)
        .filter(Pathway.access_type.in_(["one_time", "subscription"]))
        .order_by(Space.name, Pathway.title)
        .all()
    )

    # Cheapest active plan as a fee fallback
    fallback_plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    fallback_bps = fallback_plan.transaction_fee_basis_points if fallback_plan else 800

    # Cache creator fee bps per creator_user_id
    fee_cache: dict[str, int] = {}

    rows: list[SimplePaidPathwayRow] = []
    for pw in pathways:
        space = pw.space
        creator_id: str | None = space.creator_id

        if creator_id is None:
            # Find creator via membership
            mem = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.space_id == space.id,
                    SpaceMembership.role == "creator",
                    SpaceMembership.status == "active",
                )
                .first()
            )
            creator_id = mem.user_id if mem else None

        if creator_id and creator_id not in fee_cache:
            sub = (
                db.query(CreatorSubscription)
                .filter(
                    CreatorSubscription.user_id == creator_id,
                    CreatorSubscription.status.in_([
                        CreatorSubscriptionStatus.active,
                        CreatorSubscriptionStatus.trialing,
                    ]),
                )
                .order_by(CreatorSubscription.created_at.desc())
                .first()
            )
            if sub:
                plan = db.query(CreatorPlan).filter(CreatorPlan.id == sub.creator_plan_id).first()
                fee_cache[creator_id] = plan.transaction_fee_basis_points if plan else fallback_bps
            else:
                fee_cache[creator_id] = fallback_bps

        bps = fee_cache.get(creator_id or "", fallback_bps)

        rows.append(SimplePaidPathwayRow(
            id=pw.id,
            title=pw.title,
            space_id=space.id,
            space_name=space.name,
            space_slug=space.slug,
            access_type=pw.access_type,
            price_cents=pw.price_cents or 0,
            currency=pw.currency or "AUD",
            billing_interval=pw.billing_interval,
            creator_fee_basis_points=bps,
        ))

    return rows


# ---------------------------------------------------------------------------
# Manual purchase simulation
# ---------------------------------------------------------------------------

@router.post("/payments/manual-pathway-purchase", response_model=ManualPathwayPurchaseResult, status_code=201)
def manual_pathway_purchase(
    body: ManualPathwayPurchaseRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ManualPathwayPurchaseResult:
    """
    Admin-only: simulate a completed pathway purchase for a member.

    Creates a PaymentTransaction (status=succeeded, provider=manual) and a
    PathwayEntitlement (source=admin).  If the member already has an active
    entitlement, returns 409.  If a revoked/inactive entitlement exists it is
    reactivated rather than duplicated.
    """
    payer = db.query(User).filter(User.id == body.payer_user_id).first()
    if not payer:
        raise HTTPException(status_code=404, detail="Payer user not found.")

    pathway = db.query(Pathway).filter(Pathway.id == body.pathway_id).first()
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")

    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")

    # Resolve creator
    creator_id: str | None = space.creator_id
    if creator_id is None:
        mem = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.role == "creator",
                SpaceMembership.status == "active",
            )
            .first()
        )
        creator_id = mem.user_id if mem else None

    # Creator's current fee bps
    fallback_plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )
    fallback_bps = fallback_plan.transaction_fee_basis_points if fallback_plan else 800

    fee_bps = fallback_bps
    if creator_id:
        sub = (
            db.query(CreatorSubscription)
            .filter(
                CreatorSubscription.user_id == creator_id,
                CreatorSubscription.status.in_([
                    CreatorSubscriptionStatus.active,
                    CreatorSubscriptionStatus.trialing,
                ]),
            )
            .order_by(CreatorSubscription.created_at.desc())
            .first()
        )
        if sub:
            plan = db.query(CreatorPlan).filter(CreatorPlan.id == sub.creator_plan_id).first()
            if plan:
                fee_bps = plan.transaction_fee_basis_points

    # Guard: active entitlement already exists
    existing_active = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == body.payer_user_id,
            PathwayEntitlement.pathway_id == body.pathway_id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=409,
            detail="Member already has an active entitlement for this pathway.",
        )

    # Fee/net calculations (basis points)
    gross = pathway.price_cents or 0
    currency = pathway.currency or "AUD"
    platform_fee = round(gross * fee_bps / 10000)
    net_creator = gross - platform_fee
    net_platform = platform_fee

    # Create or reactivate entitlement
    existing_inactive = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == body.payer_user_id,
            PathwayEntitlement.pathway_id == body.pathway_id,
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .first()
    )

    now = datetime.utcnow()
    if existing_inactive:
        ent = existing_inactive
        ent.status = EntitlementStatus.active
        ent.source = EntitlementSource.admin
        ent.granted_by_user_id = admin.id
        ent.revoked_by_user_id = None
        ent.revoked_at = None
        ent.ends_at = None
        ent.notes = body.notes
        ent.updated_at = now
    else:
        ent = PathwayEntitlement(
            id=str(uuid4()),
            user_id=body.payer_user_id,
            space_id=space.id,
            pathway_id=body.pathway_id,
            source=EntitlementSource.admin,
            status=EntitlementStatus.active,
            starts_at=now,
            granted_by_user_id=admin.id,
            notes=body.notes,
        )
        db.add(ent)

    db.flush()  # populate ent.id before referencing in txn

    txn = PaymentTransaction(
        id=str(uuid4()),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.manual,
        payer_user_id=body.payer_user_id,
        creator_user_id=creator_id,
        space_id=space.id,
        pathway_id=body.pathway_id,
        entitlement_id=ent.id,
        currency=currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=net_platform,
        notes=body.notes,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    db.refresh(ent)

    return ManualPathwayPurchaseResult(
        transaction_id=txn.id,
        entitlement_id=ent.id,
        entitlement_source=ent.source.value,
        payer_name=payer.name,
        payer_email=payer.email,
        pathway_title=pathway.title,
        space_name=space.name,
        space_slug=space.slug,
        currency=currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=net_platform,
    )


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


# ---------------------------------------------------------------------------
# Platform admin — owner/admin panel endpoints
# ---------------------------------------------------------------------------

@router.get("/platform/overview", response_model=AdminPlatformOverview)
def get_platform_overview(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminPlatformOverview:
    """Platform-wide stats for the admin overview page. Admin only."""
    from app.models.user import User as UserModel

    total_collectives   = db.query(func.count(Space.id)).scalar() or 0
    active_collectives  = db.query(func.count(Space.id)).filter(Space.status == "active").scalar() or 0
    draft_collectives   = db.query(func.count(Space.id)).filter(Space.status == "draft").scalar() or 0
    archived_collectives = db.query(func.count(Space.id)).filter(Space.status == "archived").scalar() or 0

    total_users   = db.query(func.count(UserModel.id)).scalar() or 0
    admin_users   = db.query(func.count(UserModel.id)).filter(UserModel.role == "admin").scalar() or 0
    creator_users = db.query(func.count(UserModel.id)).filter(UserModel.role == "creator").scalar() or 0
    member_users  = total_users - admin_users - creator_users

    pending_access_requests = (
        db.query(func.count(SpaceAccessRequest.id))
        .filter(SpaceAccessRequest.status == "pending")
        .scalar() or 0
    )
    pending_invitations = db.query(func.count(SpaceInvitation.id)).scalar() or 0

    succeeded_transactions = (
        db.query(func.count(PaymentTransaction.id))
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
        )
        .scalar() or 0
    )
    total_gross_cents = int(
        db.query(func.sum(PaymentTransaction.gross_amount_cents))
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
        )
        .scalar() or 0
    )

    return AdminPlatformOverview(
        total_collectives=total_collectives,
        active_collectives=active_collectives,
        draft_collectives=draft_collectives,
        archived_collectives=archived_collectives,
        total_users=total_users,
        admin_users=admin_users,
        creator_users=creator_users,
        member_users=member_users,
        pending_access_requests=pending_access_requests,
        pending_invitations=pending_invitations,
        total_gross_cents=total_gross_cents,
        succeeded_transactions=succeeded_transactions,
    )


@router.get("/platform/collectives", response_model=list[AdminCollectiveRow])
def list_all_collectives(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCollectiveRow]:
    """All spaces with member/pathway/event/resource counts. Admin only."""
    spaces = db.query(Space).order_by(Space.created_at.desc()).all()

    # Batch counts to avoid N+1
    from sqlalchemy import case, distinct

    # member counts (learner role, active status)
    mem_counts = dict(
        db.query(SpaceMembership.space_id, func.count(SpaceMembership.id))
        .filter(SpaceMembership.role == "learner", SpaceMembership.status == "active")
        .group_by(SpaceMembership.space_id)
        .all()
    )
    pathway_counts = dict(
        db.query(Pathway.space_id, func.count(Pathway.id))
        .group_by(Pathway.space_id)
        .all()
    )
    gathering_counts = dict(
        db.query(Event.space_id, func.count(Event.id))
        .filter(Event.is_published.is_(True))
        .group_by(Event.space_id)
        .all()
    )
    resource_counts = dict(
        db.query(SpaceResource.space_id, func.count(SpaceResource.id))
        .filter(SpaceResource.status == "published")
        .group_by(SpaceResource.space_id)
        .all()
    )

    # Creator lookup
    creator_ids = {s.creator_id for s in spaces if s.creator_id}
    from app.models.user import User as UserModel
    creator_map = {
        u.id: u
        for u in db.query(UserModel).filter(UserModel.id.in_(creator_ids)).all()
    } if creator_ids else {}

    rows: list[AdminCollectiveRow] = []
    for s in spaces:
        creator = creator_map.get(s.creator_id) if s.creator_id else None
        status_val = s.status.value if hasattr(s.status, "value") else str(s.status)
        rows.append(AdminCollectiveRow(
            id=s.id,
            name=s.name,
            slug=s.slug,
            status=status_val,
            is_public=s.is_public,
            has_paid_internal_content=getattr(s, "has_paid_internal_content", False),
            creator_name=creator.name if creator else None,
            creator_email=creator.email if creator else None,
            member_count=mem_counts.get(s.id, 0),
            pathway_count=pathway_counts.get(s.id, 0),
            gathering_count=gathering_counts.get(s.id, 0),
            resource_count=resource_counts.get(s.id, 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        ))
    return rows


@router.get("/platform/creators", response_model=list[AdminCreatorRow])
def list_platform_creators(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCreatorRow]:
    """All creator and admin users with plan/usage summary. Admin only."""
    from app.models.user import User as UserModel

    creators = (
        db.query(UserModel)
        .filter(UserModel.role.in_(["creator", "admin"]))
        .order_by(UserModel.created_at)
        .all()
    )

    plans_by_id = {p.id: p for p in db.query(CreatorPlan).all()}
    subs = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.status.in_(["active", "trialing"]))
        .all()
    )
    sub_map: dict[str, CreatorSubscription] = {s.user_id: s for s in subs}

    fallback_plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )

    rows: list[AdminCreatorRow] = []
    for creator in creators:
        sub = sub_map.get(creator.id)
        plan = (plans_by_id.get(sub.creator_plan_id) if sub else None) or fallback_plan
        plan_name = plan.name if plan else "—"
        sub_status = "none"
        if sub:
            sub_status = sub.status.value if hasattr(sub.status, "value") else str(sub.status)

        collective_count = len(_creator_managed_space_ids(creator.id, db))
        rows.append(AdminCreatorRow(
            id=creator.id,
            name=creator.name,
            email=creator.email,
            role=creator.role,
            created_at=creator.created_at,
            collective_count=collective_count,
            plan_name=plan_name,
            subscription_status=sub_status,
        ))
    return rows


@router.get("/platform/users", response_model=list[AdminUserRow])
def list_platform_users(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminUserRow]:
    """All users with collective membership and ownership counts. Admin only."""
    from app.models.user import User as UserModel

    users = db.query(UserModel).order_by(UserModel.created_at.desc()).all()

    # Batch counts
    joined_counts = dict(
        db.query(SpaceMembership.user_id, func.count(SpaceMembership.id))
        .filter(SpaceMembership.role == "learner", SpaceMembership.status == "active")
        .group_by(SpaceMembership.user_id)
        .all()
    )
    owned_counts = dict(
        db.query(Space.creator_id, func.count(Space.id))
        .filter(Space.creator_id.isnot(None), Space.status != "archived")
        .group_by(Space.creator_id)
        .all()
    )

    return [
        AdminUserRow(
            id=u.id,
            name=u.name,
            email=u.email,
            role=u.role,
            created_at=u.created_at,
            joined_collectives=joined_counts.get(u.id, 0),
            owned_collectives=owned_counts.get(u.id, 0),
        )
        for u in users
    ]


@router.get("/platform/access", response_model=AdminAccessResponse)
def list_access_and_invites(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminAccessResponse:
    """Platform-wide access requests and pending invitations. Admin only."""
    from app.models.user import User as UserModel

    access_reqs = (
        db.query(SpaceAccessRequest)
        .order_by(SpaceAccessRequest.created_at.desc())
        .all()
    )
    invitations = (
        db.query(SpaceInvitation)
        .order_by(SpaceInvitation.created_at.desc())
        .all()
    )

    space_ids = {r.space_id for r in access_reqs} | {i.space_id for i in invitations}
    spaces = {s.id: s for s in db.query(Space).filter(Space.id.in_(space_ids)).all()} if space_ids else {}

    user_ids = (
        {r.user_id for r in access_reqs}
        | {i.invited_by_id for i in invitations}
    )
    users: dict[str, UserModel] = {
        u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()
    } if user_ids else {}

    req_rows: list[AdminAccessRequestRow] = []
    for r in access_reqs:
        space = spaces.get(r.space_id)
        requester = users.get(r.user_id)
        req_rows.append(AdminAccessRequestRow(
            id=r.id,
            space_id=r.space_id,
            space_name=space.name if space else r.space_id,
            space_slug=space.slug if space else r.space_id,
            user_id=r.user_id,
            user_name=requester.name if requester else None,
            user_email=requester.email if requester else r.user_id,
            status=r.status,
            message=r.message,
            created_at=r.created_at,
        ))

    inv_rows: list[AdminInvitationRow] = []
    for i in invitations:
        space = spaces.get(i.space_id)
        inviter = users.get(i.invited_by_id)
        role_val = i.role.value if hasattr(i.role, "value") else str(i.role)
        inv_rows.append(AdminInvitationRow(
            id=i.id,
            space_id=i.space_id,
            space_name=space.name if space else i.space_id,
            space_slug=space.slug if space else i.space_id,
            email=i.email,
            name=i.name,
            role=role_val,
            invited_by_name=inviter.name if inviter else None,
            invited_by_email=inviter.email if inviter else None,
            created_at=i.created_at,
        ))

    return AdminAccessResponse(access_requests=req_rows, invitations=inv_rows)


# ---------------------------------------------------------------------------
# Creator plans & subscriptions (Money section)
# ---------------------------------------------------------------------------

@router.get("/creator-plans", response_model=list[AdminCreatorPlanRow])
def list_creator_plans(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCreatorPlanRow]:
    """All creator billing plans with active subscriber counts. Admin only."""
    plans = db.query(CreatorPlan).order_by(CreatorPlan.monthly_price_cents).all()

    sub_counts: dict[str, int] = dict(
        db.query(CreatorSubscription.creator_plan_id, func.count(CreatorSubscription.id))
        .filter(CreatorSubscription.status.in_([
            CreatorSubscriptionStatus.active,
            CreatorSubscriptionStatus.trialing,
        ]))
        .group_by(CreatorSubscription.creator_plan_id)
        .all()
    )

    rows: list[AdminCreatorPlanRow] = []
    for plan in plans:
        rows.append(AdminCreatorPlanRow(
            id=plan.id,
            name=plan.name,
            slug=plan.slug,
            description=plan.description,
            monthly_price_cents=plan.monthly_price_cents,
            currency=plan.currency,
            transaction_fee_basis_points=plan.transaction_fee_basis_points,
            collective_limit=plan.collective_limit,
            is_active=plan.is_active,
            active_subscriptions=sub_counts.get(plan.id, 0),
            created_at=plan.created_at,
        ))
    return rows


@router.get("/creator-subscriptions", response_model=list[AdminCreatorSubscriptionRow])
def list_creator_subscriptions_admin(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCreatorSubscriptionRow]:
    """All creator billing subscriptions with user and plan details. Admin only."""
    from app.models.user import User as UserModel

    subs = db.query(CreatorSubscription).order_by(CreatorSubscription.created_at.desc()).all()
    if not subs:
        return []

    user_ids = {s.user_id for s in subs}
    plan_ids = {s.creator_plan_id for s in subs}

    user_map: dict[str, UserModel] = {
        u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()
    }
    plan_map: dict[str, CreatorPlan] = {
        p.id: p for p in db.query(CreatorPlan).filter(CreatorPlan.id.in_(plan_ids)).all()
    }

    rows: list[AdminCreatorSubscriptionRow] = []
    for sub in subs:
        user = user_map.get(sub.user_id)
        plan = plan_map.get(sub.creator_plan_id)
        status_val = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
        rows.append(AdminCreatorSubscriptionRow(
            id=sub.id,
            user_id=sub.user_id,
            user_name=user.name if user else None,
            user_email=user.email if user else sub.user_id,
            plan_id=sub.creator_plan_id,
            plan_name=plan.name if plan else "—",
            plan_slug=plan.slug if plan else "—",
            monthly_price_cents=plan.monthly_price_cents if plan else 0,
            currency=plan.currency if plan else "AUD",
            transaction_fee_basis_points=plan.transaction_fee_basis_points if plan else 0,
            status=status_val,
            starts_at=sub.starts_at,
            ends_at=sub.ends_at,
            stripe_subscription_id=getattr(sub, "stripe_subscription_id", None),
            stripe_customer_id=getattr(sub, "stripe_customer_id", None),
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        ))
    return rows


# ---------------------------------------------------------------------------
# Revenue dashboard
# ---------------------------------------------------------------------------

@router.get("/revenue/summary", response_model=AdminRevenueSummary)
def get_revenue_summary(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminRevenueSummary:
    """Platform revenue summary for admin revenue dashboard. Admin only."""
    succeeded = PaymentTransactionStatus.succeeded

    # Creator subscription fees paid to FC (gross = FC revenue)
    sub_revenue = int(
        db.query(func.sum(PaymentTransaction.gross_amount_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type == PaymentTransactionType.creator_subscription_payment,
        )
        .scalar() or 0
    )

    # Platform fees retained from member purchases
    platform_fee_revenue = int(
        db.query(func.sum(PaymentTransaction.platform_fee_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
        )
        .scalar() or 0
    )

    # Gross member sales (total of what members paid for creator content)
    gross_sales = int(
        db.query(func.sum(PaymentTransaction.gross_amount_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
        )
        .scalar() or 0
    )

    # Creator net from member sales
    creator_net = int(
        db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.net_creator_amount_cents.isnot(None),
        )
        .scalar() or 0
    )

    # Paid out
    paid_out = int(
        db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.payout_status == PayoutStatus.paid,
            PaymentTransaction.net_creator_amount_cents.isnot(None),
        )
        .scalar() or 0
    )

    # Pending payout (member sales only — creator subs go to FC directly)
    pending_payout = int(
        db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.payout_status == PayoutStatus.pending,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.net_creator_amount_cents.isnot(None),
        )
        .scalar() or 0
    )

    succeeded_count = int(
        db.query(func.count(PaymentTransaction.id))
        .filter(PaymentTransaction.status == succeeded)
        .scalar() or 0
    )
    refunded_count = int(
        db.query(func.count(PaymentTransaction.id))
        .filter(PaymentTransaction.status.in_([
            PaymentTransactionStatus.refunded,
            PaymentTransactionStatus.partially_refunded,
        ]))
        .scalar() or 0
    )
    failed_count = int(
        db.query(func.count(PaymentTransaction.id))
        .filter(PaymentTransaction.status == PaymentTransactionStatus.failed)
        .scalar() or 0
    )

    return AdminRevenueSummary(
        total_fc_revenue_cents=sub_revenue + platform_fee_revenue,
        subscription_revenue_cents=sub_revenue,
        platform_fee_revenue_cents=platform_fee_revenue,
        total_gross_sales_cents=gross_sales,
        total_creator_net_cents=creator_net,
        paid_out_cents=paid_out,
        pending_payout_cents=pending_payout,
        succeeded_transactions=succeeded_count,
        refunded_transactions=refunded_count,
        failed_transactions=failed_count,
    )


@router.get("/revenue/by-creator", response_model=list[AdminRevenueByCreatorRow])
def get_revenue_by_creator(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminRevenueByCreatorRow]:
    """Per-creator revenue breakdown. Admin only."""
    from app.models.user import User as UserModel

    succeeded = PaymentTransactionStatus.succeeded

    # Member sales by creator_user_id (gross, FC fee, creator net)
    member_sales = (
        db.query(
            PaymentTransaction.creator_user_id,
            func.sum(PaymentTransaction.gross_amount_cents).label("gross"),
            func.sum(PaymentTransaction.platform_fee_cents).label("fc_fees"),
            func.sum(PaymentTransaction.net_creator_amount_cents).label("creator_net"),
        )
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.creator_user_id.isnot(None),
        )
        .group_by(PaymentTransaction.creator_user_id)
        .all()
    )

    # Creator subscription payments by payer_user_id (the creator paid FC)
    sub_payments = (
        db.query(
            PaymentTransaction.payer_user_id,
            func.sum(PaymentTransaction.gross_amount_cents).label("sub_revenue"),
        )
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.transaction_type == PaymentTransactionType.creator_subscription_payment,
            PaymentTransaction.payer_user_id.isnot(None),
        )
        .group_by(PaymentTransaction.payer_user_id)
        .all()
    )

    # Paid-out amounts by creator
    paid_rows = (
        db.query(
            PaymentTransaction.creator_user_id,
            func.sum(PaymentTransaction.net_creator_amount_cents).label("paid"),
        )
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.payout_status == PayoutStatus.paid,
            PaymentTransaction.creator_user_id.isnot(None),
            PaymentTransaction.net_creator_amount_cents.isnot(None),
        )
        .group_by(PaymentTransaction.creator_user_id)
        .all()
    )

    # Pending payout by creator
    pending_rows = (
        db.query(
            PaymentTransaction.creator_user_id,
            func.sum(PaymentTransaction.net_creator_amount_cents).label("pending"),
        )
        .filter(
            PaymentTransaction.status == succeeded,
            PaymentTransaction.payout_status == PayoutStatus.pending,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.creator_user_id.isnot(None),
            PaymentTransaction.net_creator_amount_cents.isnot(None),
        )
        .group_by(PaymentTransaction.creator_user_id)
        .all()
    )

    sales_map = {r.creator_user_id: r for r in member_sales}
    sub_map: dict[str, int] = {r.payer_user_id: int(r.sub_revenue) for r in sub_payments}
    paid_map: dict[str, int] = {r.creator_user_id: int(r.paid) for r in paid_rows}
    pending_map: dict[str, int] = {r.creator_user_id: int(r.pending) for r in pending_rows}

    all_creator_ids = set(sales_map.keys()) | set(sub_map.keys())
    if not all_creator_ids:
        return []

    user_map: dict[str, UserModel] = {
        u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(all_creator_ids)).all()
    }
    space_counts: dict[str, int] = dict(
        db.query(Space.creator_id, func.count(Space.id))
        .filter(Space.creator_id.in_(all_creator_ids), Space.status != "archived")
        .group_by(Space.creator_id)
        .all()
    )

    rows: list[AdminRevenueByCreatorRow] = []
    for creator_id in all_creator_ids:
        user = user_map.get(creator_id)
        sales = sales_map.get(creator_id)
        gross_sales = int(sales.gross) if sales and sales.gross else 0
        fc_fees = int(sales.fc_fees) if sales and sales.fc_fees else 0
        creator_net = int(sales.creator_net) if sales and sales.creator_net else 0
        sub_rev = sub_map.get(creator_id, 0)

        rows.append(AdminRevenueByCreatorRow(
            creator_user_id=creator_id,
            creator_name=user.name if user else None,
            creator_email=user.email if user else creator_id,
            collective_count=space_counts.get(creator_id, 0),
            gross_sales_cents=gross_sales,
            platform_fees_cents=fc_fees,
            creator_net_cents=creator_net,
            subscription_revenue_cents=sub_rev,
            total_fc_revenue_cents=fc_fees + sub_rev,
            paid_out_cents=paid_map.get(creator_id, 0),
            pending_payout_cents=pending_map.get(creator_id, 0),
        ))

    rows.sort(key=lambda r: r.total_fc_revenue_cents, reverse=True)
    return rows
