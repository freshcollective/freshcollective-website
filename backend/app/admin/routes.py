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
    AdminCreatorCollectiveChip,
    AdminCreatorPlanCreate,
    AdminCreatorPlanEdit,
    AdminCreatorPlanRow,
    AdminCreatorRow,
    AdminCreatorSubscriptionRow,
    AdminInvitationRow,
    AdminPaymentSummary,
    AdminPlatformOverview,
    AdminRevenueByCreatorRow,
    AdminRevenueSummary,
    AdminCommerceOverview,
    AdminPeriodicPaymentSummary,
    AdminPeriodicRevenueSummary,
    AdminUserResponse,
    AdminUserRow,
    CollectiveRef,
    CommerceMovementEvent,
    CommerceWindow,
    CreatorBillingRow,
    ExtendPlanAccessRequest,
    GRANT_REASONS,
    GrantPathwayAccessRequest,
    GrantPathwayAccessResult,
    GrantPlanAccessRequest,
    GrantPlanAccessResult,
    GrowthSummary,
    LedgerRow,
    PLAN_GRANT_DURATIONS,
    PLAN_GRANT_REASONS,
    PeriodBoundsOut,
    PlanGrantHistoryRow,
    RevokePlanAccessRequest,
    PaymentTransactionOut,
    RoleUpdateRequest,
    SimplePaidPathwayRow,
    SimpleUserRow,
)
from app.auth.dependencies import get_admin_user
from app.services.notification_service import create_notification
from app.core.database import get_db
from app.creator.plan_config import (
    ALL_PLANS,
    ORGANISATION,
    PlanCapability,
    get_plan_capability,
)
from app.models.creator_billing import (
    CreatorPlan,
    CreatorPlanGrant,
    CreatorSubscription,
    CreatorSubscriptionStatus,
    PlanChangeEvent,
)
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

        # Source the allowance from `effective_collective_allowance` so
        # the display never disagrees with the guard. Platform owner
        # comes back as `None` (rendered as ∞ on the frontend).
        from app.creator.plan_guards import (
            effective_collective_allowance,
            is_platform_owner,
        )
        allowance = effective_collective_allowance(creator, db)
        owner_flag = is_platform_owner(creator)

        # The platform owner's effective access is inherent to the
        # account and does not depend on any historical
        # ``CreatorSubscription`` row. The row above (``plan``) may be
        # e.g. an old cancelled Community sub — echoing its name here
        # would mix historical state into the effective-access view.
        # Emit an explicit "Platform owner" label instead; the
        # historical row remains untouched in the DB and is still
        # surfaced in Access history.
        effective_plan_name = "Platform owner" if owner_flag else plan.name
        effective_plan_slug = "platform_owner" if owner_flag else plan.slug

        rows.append(CreatorBillingRow(
            user_id=creator.id,
            name=creator.name,
            email=creator.email,
            current_plan_name=effective_plan_name,
            current_plan_slug=effective_plan_slug,
            monthly_price_cents=plan.monthly_price_cents,
            currency=plan.currency,
            transaction_fee_basis_points=plan.transaction_fee_basis_points,
            collective_limit=allowance,
            subscription_status=sub_status,
            collectives_used=len(space_ids),
            pathways_used=pathways_used,
            joined_at=creator.created_at,
            is_platform_owner=owner_flag,
        ))

    return rows


# ---------------------------------------------------------------------------
# Grant plan access — non-financial admin action for creator subscriptions.
#
# The old PATCH `/creator-billing/{user_id}/plan` silently overwrote any
# existing subscription (paid or granted) with a new plan and reactivated
# it — the exact same "conflate manual with paid" bug the pathway-grant
# refactor fixed. It has been replaced by the trio below plus schema
# support for grant metadata + a grant history table.
#
# **Never** creates a PaymentTransaction. **Never** touches Stripe.
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = {
    CreatorSubscriptionStatus.active,
    CreatorSubscriptionStatus.trialing,
    CreatorSubscriptionStatus.past_due,
}

_PLAN_REASON_LABELS: dict[str, str] = {
    # Human-facing labels shown in creator notification copy. The
    # underlying enum values (`comp`, etc.) are stored unchanged; only
    # the label was renamed from "Complimentary access" to
    # "Complimentary plan" to read more naturally in the plan context.
    "comp":        "Complimentary plan",
    "beta":        "Beta or testing access",
    "migration":   "Migration",
    "correction":  "Subscription correction",
    "temporary":   "Temporary access",
    "replacement": "Replacement access",
    "internal":    "Internal use",
    "other":       "Other",
}


def _resolve_grant_ends_at(
    starts_at: datetime,
    ends_at: datetime | None,
    duration: str | None,
) -> datetime | None:
    """Return the ends_at implied by the caller's inputs.

    Rules:
      - If ``ends_at`` is provided, it wins.
      - Else if ``duration`` is provided, resolve it.
      - Else raise 422 — indefinite grants must be explicit via
        ``duration='indefinite'`` or an explicit null ``ends_at`` with
        a matching duration.
    """
    if ends_at is not None:
        return ends_at
    if duration is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Grant duration must be explicit. Pass either an ends_at "
                "date or a duration ('1_month', '3_months', '6_months', "
                "'12_months', or 'indefinite')."
            ),
        )
    if duration not in PLAN_GRANT_DURATIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid duration {duration!r}. Valid: "
                f"{list(PLAN_GRANT_DURATIONS)}."
            ),
        )
    if duration == "indefinite":
        return None
    months = {"1_month": 1, "3_months": 3, "6_months": 6, "12_months": 12}[duration]
    # Naive month arithmetic — good enough for a grant end date. Adds
    # `months` calendar months to `starts_at`, clamping the day if the
    # target month is shorter.
    year = starts_at.year + (starts_at.month - 1 + months) // 12
    month = (starts_at.month - 1 + months) % 12 + 1
    from calendar import monthrange
    day = min(starts_at.day, monthrange(year, month)[1])
    return starts_at.replace(year=year, month=month, day=day)


def _record_grant_event(
    db: Session,
    *,
    subscription: CreatorSubscription,
    action: str,
    reason: str | None,
    note: str | None,
    actor_user_id: str | None,
) -> None:
    """Append a row to the creator_plan_grants history table."""
    db.add(CreatorPlanGrant(
        id=str(uuid4()),
        subscription_id=subscription.id,
        action=action,
        creator_plan_id=subscription.creator_plan_id,
        starts_at=subscription.starts_at,
        ends_at=subscription.ends_at,
        reason=reason,
        note=note,
        actor_user_id=actor_user_id,
    ))


@router.post(
    "/creator-subscriptions/grant",
    response_model=GrantPlanAccessResult,
    status_code=201,
)
def grant_creator_plan_access(
    body: GrantPlanAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GrantPlanAccessResult:
    """Grant a creator access to a Fresh Collective plan without
    recording a payment. Creates a ``CreatorSubscription`` with
    ``source='manual_grant'`` and records a ``CreatorPlanGrant`` history
    event. Never creates a ``PaymentTransaction`` and never touches
    Stripe.
    """
    # --- Validate ---------------------------------------------------------
    if body.reason not in PLAN_GRANT_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reason {body.reason!r}. Valid: {list(PLAN_GRANT_REASONS)}.",
        )
    note = (body.note or "").strip() or None
    if body.reason == "other" and not note:
        raise HTTPException(
            status_code=422,
            detail="A note is required when reason is 'other'.",
        )

    creator = db.query(User).filter(User.id == body.creator_user_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found.")
    plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.slug == body.plan_slug, CreatorPlan.is_active.is_(True))
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{body.plan_slug}' not found.")

    starts_at = body.starts_at or datetime.utcnow()
    ends_at = _resolve_grant_ends_at(starts_at, body.ends_at, body.duration)

    # --- Conflict handling ------------------------------------------------
    existing_active = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == body.creator_user_id,
            CreatorSubscription.status.in_([s.value for s in _ACTIVE_STATUSES]),
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if existing_active:
        if existing_active.source == "stripe_paid":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Creator has an active paid Stripe subscription. "
                    "Refusing to overwrite silently — cancel the Stripe "
                    "subscription first or use a separate override workflow."
                ),
            )
        # existing manual grant — refuse and hint at the right action
        raise HTTPException(
            status_code=409,
            detail=(
                "Creator already has an active manually granted plan. "
                "Extend or revoke it explicitly rather than creating a "
                "second grant."
            ),
        )

    # --- Create / reactivate ---------------------------------------------
    existing_inactive = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.user_id == body.creator_user_id)
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    now = datetime.utcnow()
    if existing_inactive and existing_inactive.source == "manual_grant":
        # Reactivate the prior manual grant so limit-check queries still
        # find a single row per creator. Its history remains preserved in
        # `creator_plan_grants`.
        sub = existing_inactive
        sub.creator_plan_id = plan.id
        sub.status = CreatorSubscriptionStatus.active
        sub.starts_at = starts_at
        sub.ends_at = ends_at
        sub.source = "manual_grant"
        sub.grant_reason = body.reason
        sub.granted_by_user_id = admin.id
        sub.grant_note = note
        sub.revoked_at = None
        sub.revoked_by_user_id = None
        sub.revoked_reason = None
        sub.updated_at = now
        reactivated = True
    else:
        sub = CreatorSubscription(
            id=str(uuid4()),
            user_id=body.creator_user_id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=starts_at,
            ends_at=ends_at,
            source="manual_grant",
            grant_reason=body.reason,
            granted_by_user_id=admin.id,
            grant_note=note,
        )
        db.add(sub)
        reactivated = False

    db.flush()
    _record_grant_event(
        db, subscription=sub, action="granted",
        reason=body.reason, note=note, actor_user_id=admin.id,
    )
    db.commit()
    db.refresh(sub)

    # --- Notify creator ---------------------------------------------------
    try:
        reason_label = _PLAN_REASON_LABELS.get(body.reason, body.reason)
        if ends_at is not None:
            message = (
                f"Fresh Collective granted you access to the {plan.name} "
                f"plan until {ends_at.strftime('%d %b %Y')}. "
                f"Reason: {reason_label}."
            )
        else:
            message = (
                f"Fresh Collective granted you ongoing access to the "
                f"{plan.name} plan. Reason: {reason_label}."
            )
        create_notification(
            db=db,
            recipient_id=creator.id,
            notification_type="creator_plan_granted_by_platform",
            title=f"Plan access granted — {plan.name}",
            message=message,
            url=None,
        )
    except Exception:  # pragma: no cover
        import logging
        logging.getLogger(__name__).exception(
            "grant_creator_plan_access: creator notification failed"
        )

    return GrantPlanAccessResult(
        subscription_id=sub.id,
        source=sub.source,
        status=sub.status.value,
        reason=body.reason,
        note=note,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        granted_at=sub.updated_at if reactivated else sub.created_at,
        granted_by_user_id=admin.id,
        creator_name=creator.name,
        creator_email=creator.email,
        plan_slug=plan.slug,
        plan_name=plan.name,
        reactivated=reactivated,
    )


@router.post(
    "/creator-subscriptions/{subscription_id}/extend",
    response_model=GrantPlanAccessResult,
)
def extend_creator_plan_grant(
    subscription_id: str,
    body: ExtendPlanAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GrantPlanAccessResult:
    """Extend a manually granted creator subscription. Refuses when the
    row is a paid Stripe subscription — those have their own lifecycle.
    Records a ``CreatorPlanGrant`` history event.
    """
    sub = db.query(CreatorSubscription).filter(CreatorSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    if sub.source != "manual_grant":
        raise HTTPException(
            status_code=409,
            detail="Can only extend a manually granted subscription.",
        )
    if sub.status != CreatorSubscriptionStatus.active:
        raise HTTPException(
            status_code=409,
            detail="Can only extend an active grant. Revoked or expired grants must be re-granted.",
        )

    new_ends_at = _resolve_grant_ends_at(sub.starts_at, body.ends_at, body.duration)
    sub.ends_at = new_ends_at
    sub.updated_at = datetime.utcnow()
    _record_grant_event(
        db, subscription=sub, action="extended",
        reason=None, note=(body.note or "").strip() or None,
        actor_user_id=admin.id,
    )
    db.commit()
    db.refresh(sub)

    plan = db.query(CreatorPlan).filter(CreatorPlan.id == sub.creator_plan_id).first()
    creator = db.query(User).filter(User.id == sub.user_id).first()
    return GrantPlanAccessResult(
        subscription_id=sub.id,
        source=sub.source,
        status=sub.status.value,
        reason=sub.grant_reason or "",
        note=sub.grant_note,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        granted_at=sub.updated_at,
        granted_by_user_id=sub.granted_by_user_id or admin.id,
        creator_name=creator.name if creator else None,
        creator_email=creator.email if creator else "",
        plan_slug=plan.slug if plan else "",
        plan_name=plan.name if plan else "",
        reactivated=False,
    )


@router.post(
    "/creator-subscriptions/{subscription_id}/revoke",
    response_model=GrantPlanAccessResult,
)
def revoke_creator_plan_grant(
    subscription_id: str,
    body: RevokePlanAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GrantPlanAccessResult:
    """Revoke a manually granted subscription. Refuses on paid rows —
    Stripe subscriptions must be cancelled through their own workflow.
    """
    sub = db.query(CreatorSubscription).filter(CreatorSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    if sub.source != "manual_grant":
        raise HTTPException(
            status_code=409,
            detail="Can only revoke a manually granted subscription.",
        )
    if sub.status != CreatorSubscriptionStatus.active:
        raise HTTPException(
            status_code=409,
            detail="Grant is not active.",
        )

    now = datetime.utcnow()
    sub.status = CreatorSubscriptionStatus.cancelled
    sub.revoked_at = now
    sub.revoked_by_user_id = admin.id
    sub.revoked_reason = (body.reason or "").strip() or None
    sub.updated_at = now
    _record_grant_event(
        db, subscription=sub, action="revoked",
        reason=body.reason, note=(body.note or "").strip() or None,
        actor_user_id=admin.id,
    )
    db.commit()
    db.refresh(sub)

    plan = db.query(CreatorPlan).filter(CreatorPlan.id == sub.creator_plan_id).first()
    creator = db.query(User).filter(User.id == sub.user_id).first()
    return GrantPlanAccessResult(
        subscription_id=sub.id,
        source=sub.source,
        status=sub.status.value,
        reason=sub.grant_reason or "",
        note=sub.grant_note,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        granted_at=sub.updated_at,
        granted_by_user_id=sub.granted_by_user_id or admin.id,
        creator_name=creator.name if creator else None,
        creator_email=creator.email if creator else "",
        plan_slug=plan.slug if plan else "",
        plan_name=plan.name if plan else "",
        reactivated=False,
    )


@router.get(
    "/creator-subscriptions/{subscription_id}/history",
    response_model=list[PlanGrantHistoryRow],
)
def list_creator_plan_grant_history(
    subscription_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[PlanGrantHistoryRow]:
    """Return the append-only grant history for a subscription — the
    audit trail of granted/extended/revoked events, oldest first."""
    events = (
        db.query(CreatorPlanGrant)
        .filter(CreatorPlanGrant.subscription_id == subscription_id)
        .order_by(CreatorPlanGrant.created_at.asc())
        .all()
    )
    if not events:
        return []
    plan_ids = {e.creator_plan_id for e in events}
    actor_ids = {e.actor_user_id for e in events if e.actor_user_id}
    plan_map: dict[str, tuple[str, str]] = {
        row[0]: (row[1], row[2])
        for row in db.query(CreatorPlan.id, CreatorPlan.slug, CreatorPlan.name)
        .filter(CreatorPlan.id.in_(plan_ids)).all()
    } if plan_ids else {}
    actor_map = {
        u.id: u.name
        for u in db.query(User).filter(User.id.in_(actor_ids)).all()
    } if actor_ids else {}

    out: list[PlanGrantHistoryRow] = []
    for e in events:
        slug, name = plan_map.get(e.creator_plan_id, ("—", "—"))
        out.append(PlanGrantHistoryRow(
            id=e.id,
            action=e.action,
            plan_slug=slug,
            plan_name=name,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            reason=e.reason,
            note=e.note,
            actor_user_id=e.actor_user_id,
            actor_name=actor_map.get(e.actor_user_id) if e.actor_user_id else None,
            created_at=e.created_at,
        ))
    return out


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


def _compute_payment_summary(
    db: Session,
    *,
    starts_at: "datetime | None" = None,
    ends_at: "datetime | None" = None,
    creator_user_id: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    stripe_mode: str | None = None,
) -> AdminPaymentSummary:
    """Compute an :class:`AdminPaymentSummary` over an optional half-open
    ``[starts_at, ends_at)`` UTC window.

    All filters are additive and independent — the caller passes only
    what they want to constrain. Called by both the flat and periodic
    endpoints; the periodic endpoint calls it twice (current + previous)
    without re-implementing the aggregation.
    """
    def _base_q(statuses: set | None = None):
        q = db.query(PaymentTransaction).filter(
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES])
        )
        if statuses:
            q = q.filter(PaymentTransaction.status.in_([s.value for s in statuses]))
        if starts_at is not None:
            q = q.filter(PaymentTransaction.created_at >= starts_at)
        if ends_at is not None:
            q = q.filter(PaymentTransaction.created_at < ends_at)
        if creator_user_id:
            q = q.filter(PaymentTransaction.creator_user_id == creator_user_id)
        if space_id:
            q = q.filter(PaymentTransaction.space_id == space_id)
        if pathway_id:
            q = q.filter(PaymentTransaction.pathway_id == pathway_id)
        if stripe_mode:
            q = q.filter(PaymentTransaction.stripe_mode == stripe_mode)
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


@router.get("/payments/summary", response_model=AdminPaymentSummary)
def get_admin_payment_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    creator_user_id: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    stripe_mode: str | None = None,
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

    parsed_from: "datetime | None" = None
    parsed_to: "datetime | None" = None
    if date_from:
        try:
            parsed_from = datetime.combine(date.fromisoformat(date_from), datetime.min.time())
        except ValueError:
            parsed_from = None
    if date_to:
        try:
            # Preserve the legacy inclusive-endpoint behaviour of the flat
            # endpoint: `date_to=2026-06-30` includes rows on 30 June. The
            # new periodic endpoint uses strict half-open windows; the flat
            # endpoint here keeps its historical semantics unchanged.
            parsed_to = datetime.combine(date.fromisoformat(date_to), datetime.max.time())
        except ValueError:
            parsed_to = None

    return _compute_payment_summary(
        db,
        starts_at=parsed_from,
        ends_at=parsed_to,
        creator_user_id=creator_user_id,
        space_id=space_id,
        pathway_id=pathway_id,
        stripe_mode=stripe_mode,
    )


@router.get("/payments/summary/periodic", response_model=AdminPeriodicPaymentSummary)
def get_admin_payment_summary_periodic(
    period: str = "this_month",
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminPeriodicPaymentSummary:
    """Payment summary bracketed by a named reporting period, with the
    comparable previous-period totals returned in the same response.

    Valid ``period`` values: ``this_month`` (default, month-to-date),
    ``last_month`` (full prior month), ``this_fy`` (Australian FY-to-date,
    Jul → Jun), ``all_time`` (no window, no comparison).

    ``stripe_mode`` is an orthogonal filter — pass ``test`` or ``live``
    to restrict both windows to that mode. Period and mode never mix.
    """
    from app.core.periods import PeriodKey, VALID_PERIODS, resolve_period

    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Valid: {list(VALID_PERIODS)}.",
        )
    current_bounds, previous_bounds = resolve_period(period)  # type: ignore[arg-type]

    current = _compute_payment_summary(
        db,
        starts_at=current_bounds.starts_at,
        ends_at=current_bounds.ends_at,
        stripe_mode=stripe_mode,
    )
    previous = None
    previous_bounds_out: PeriodBoundsOut | None = None
    if previous_bounds is not None:
        previous = _compute_payment_summary(
            db,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
            stripe_mode=stripe_mode,
        )
        previous_bounds_out = PeriodBoundsOut(
            label=previous_bounds.label,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
        )

    return AdminPeriodicPaymentSummary(
        period=period,
        stripe_mode=stripe_mode,
        current_bounds=PeriodBoundsOut(
            label=current_bounds.label,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        ),
        current=current,
        previous_bounds=previous_bounds_out,
        previous=previous,
    )


@router.get("/payments", response_model=list[PaymentTransactionOut])
def list_payments(
    status: str | None = None,
    transaction_type: str | None = None,
    creator_user_id: str | None = None,
    space_id: str | None = None,
    pathway_id: str | None = None,
    stripe_mode: str | None = None,
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
    if stripe_mode:
        q = q.filter(PaymentTransaction.stripe_mode == stripe_mode)
    rows = q.order_by(PaymentTransaction.created_at.desc()).all()
    return [PaymentTransactionOut.model_validate(r) for r in rows]


@router.get("/payments/ledger", response_model=list[LedgerRow])
def get_payments_ledger(
    period: str = "this_month",
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[LedgerRow]:
    """Denormalised transaction ledger for the Transactions page.

    Half-open period window (via ``resolve_period``), same grammar as the
    Commerce overview. Buyer / creator / collective / pathway names are
    bulk-looked-up and inlined so the UI never sees opaque foreign keys.
    Stripe provider IDs are deliberately not returned — this is the
    ledger view, not a debugging surface.

    ``stripe_mode`` auto-defaults to the platform's configured mode so a
    caretaker never accidentally sees mixed test + live rows. Ordered by
    ``created_at`` desc.
    """
    from app.core.config import settings
    from app.core.periods import VALID_PERIODS, resolve_period
    from app.models.platform import Pathway, Space
    from app.models.user import User as UserModel

    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Valid: {list(VALID_PERIODS)}.",
        )

    effective_mode = stripe_mode or settings.stripe_mode
    current_bounds, _ = resolve_period(period)  # type: ignore[arg-type]

    q = db.query(PaymentTransaction)
    if current_bounds.starts_at is not None:
        q = q.filter(PaymentTransaction.created_at >= current_bounds.starts_at)
    if current_bounds.ends_at is not None:
        q = q.filter(PaymentTransaction.created_at < current_bounds.ends_at)
    if effective_mode:
        q = q.filter(PaymentTransaction.stripe_mode == effective_mode)
    txns = q.order_by(PaymentTransaction.created_at.desc()).all()

    if not txns:
        return []

    # Bulk-fetch names once, then denormalise per row.
    user_ids = {t.payer_user_id for t in txns if t.payer_user_id} | {
        t.creator_user_id for t in txns if t.creator_user_id
    }
    space_ids = {t.space_id for t in txns if t.space_id}
    pathway_ids = {t.pathway_id for t in txns if t.pathway_id}

    users = (
        {u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()}
        if user_ids else {}
    )
    space_names = (
        dict(db.query(Space.id, Space.name).filter(Space.id.in_(space_ids)).all())
        if space_ids else {}
    )
    pathway_titles = (
        dict(db.query(Pathway.id, Pathway.title).filter(Pathway.id.in_(pathway_ids)).all())
        if pathway_ids else {}
    )

    def _enum_value(v):
        return v.value if hasattr(v, "value") else str(v)

    result: list[LedgerRow] = []
    for t in txns:
        payer = users.get(t.payer_user_id) if t.payer_user_id else None
        creator = users.get(t.creator_user_id) if t.creator_user_id else None
        result.append(LedgerRow(
            id=t.id,
            created_at=t.created_at,
            transaction_type=_enum_value(t.transaction_type),
            status=_enum_value(t.status),
            payout_status=_enum_value(t.payout_status),
            provider=_enum_value(t.payment_provider),
            stripe_mode=t.stripe_mode,
            payer_name=(payer.name if payer else None),
            payer_email=(payer.email if payer else None),
            creator_id=t.creator_user_id,
            creator_name=(creator.name if creator else None),
            creator_email=(creator.email if creator else None),
            space_name=space_names.get(t.space_id) if t.space_id else None,
            pathway_title=pathway_titles.get(t.pathway_id) if t.pathway_id else None,
            currency=t.currency,
            gross_amount_cents=t.gross_amount_cents,
            platform_fee_cents=t.platform_fee_cents,
            net_creator_amount_cents=t.net_creator_amount_cents,
        ))
    return result


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

        # Platform-owned spaces (creator_id IS NULL) always use 0 bps
        if space.platform_owned:
            bps = 0
        else:
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
# Grant access — non-financial admin action (replaces the old
# "Manual purchase" flow, per the Option C recommendation).
#
# The old flow simultaneously created a `PathwayEntitlement` AND a
# `PaymentTransaction` with `provider=manual, status=succeeded` — the
# transaction was indistinguishable from a real Stripe purchase to every
# downstream summary. That fabricated FC revenue, creator earnings, and
# pending payout obligations that no cash backed.
#
# This flow creates or reactivates a `PathwayEntitlement` **only**, with
# a structured reason recorded on the entitlement row. No
# `PaymentTransaction` is ever produced. Gross volume, FC revenue,
# creator earnings, and pending creator payouts are untouched.
#
# The raw `POST /api/admin/payments/manual` scaffolding endpoint — which
# could also fabricate transactions — is removed in the same change.
#
# Deferred:
#   `POST /api/admin/payments/offline` — Record offline payment. Will be
#   added when real off-Stripe cash flows exist and Stripe Connect is
#   live. See `docs/deferred-record-offline-payment.md`.
# ---------------------------------------------------------------------------

@router.post("/entitlements/grant", response_model=GrantPathwayAccessResult, status_code=201)
def grant_pathway_access(
    body: GrantPathwayAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GrantPathwayAccessResult:
    """Grant a member access to a pathway from World Management.

    Creates or reactivates a ``PathwayEntitlement`` with
    ``source=EntitlementSource.admin`` and records the structured
    ``grant_reason`` and ``note`` for audit. Does **not** create a
    ``PaymentTransaction`` — this is a non-financial action.

    ``reason`` must be one of ``comp | beta | migration | correction |
    replacement | other``. When ``reason == 'other'`` a note is required.

    Returns 409 when the member already has an active entitlement, so
    the caretaker can be told the current state instead of silently
    overwriting it. Reactivates a prior *revoked/expired* entitlement
    rather than creating a duplicate row — the entitlement's audit
    fields (``granted_by_user_id``, ``grant_reason``, ``notes``) are
    updated to reflect the current grant event.

    The creator of the pathway is notified in-app that Fresh Collective
    granted access. Platform-owned pathways (``space.creator_id IS NULL``)
    have no creator to notify and skip notification.
    """
    # ------------------------------------------------------------------ Validate
    if body.reason not in GRANT_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reason {body.reason!r}. Valid: {list(GRANT_REASONS)}.",
        )
    note = (body.note or "").strip() or None
    if body.reason == "other" and not note:
        raise HTTPException(
            status_code=422,
            detail="A note is required when reason is 'other'.",
        )

    # ------------------------------------------------------------------ Look up
    member = db.query(User).filter(User.id == body.member_user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    pathway = db.query(Pathway).filter(Pathway.id == body.pathway_id).first()
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")

    space = db.query(Space).filter(Space.id == pathway.space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")

    # ------------------------------------------------------------------ Guard
    existing_active = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == body.member_user_id,
            PathwayEntitlement.pathway_id == body.pathway_id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=409,
            detail="Member already has active access to this pathway.",
        )

    # ------------------------------------------------------------------ Create / reactivate
    existing_inactive = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == body.member_user_id,
            PathwayEntitlement.pathway_id == body.pathway_id,
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .first()
    )

    now = datetime.utcnow()
    reactivated = False
    if existing_inactive:
        reactivated = True
        ent = existing_inactive
        ent.status = EntitlementStatus.active
        ent.source = EntitlementSource.admin
        ent.granted_by_user_id = admin.id
        ent.grant_reason = body.reason
        ent.revoked_by_user_id = None
        ent.revoked_at = None
        ent.ends_at = None
        ent.notes = note
        ent.updated_at = now
    else:
        ent = PathwayEntitlement(
            id=str(uuid4()),
            user_id=body.member_user_id,
            space_id=space.id,
            pathway_id=body.pathway_id,
            source=EntitlementSource.admin,
            status=EntitlementStatus.active,
            starts_at=now,
            granted_by_user_id=admin.id,
            grant_reason=body.reason,
            notes=note,
        )
        db.add(ent)

    db.commit()
    db.refresh(ent)

    # ------------------------------------------------------------------ Notify creator
    # Platform-owned pathways (no creator_id) skip notification —
    # there's no creator to inform.
    if space.creator_id and space.creator_id != admin.id:
        try:
            member_label = member.name or member.email
            reason_label = _GRANT_REASON_LABELS.get(body.reason, body.reason)
            create_notification(
                db=db,
                recipient_id=space.creator_id,
                notification_type="pathway_access_granted_by_platform",
                title=f"Access granted to {pathway.title}",
                message=(
                    f"Fresh Collective granted access to {pathway.title} "
                    f"for {member_label}. Reason: {reason_label}."
                ),
                url=None,
            )
        except Exception:  # pragma: no cover
            # Notification failure must not roll back the grant.
            import logging
            logging.getLogger(__name__).exception(
                "grant_pathway_access: creator notification failed"
            )

    return GrantPathwayAccessResult(
        entitlement_id=ent.id,
        entitlement_source=ent.source.value,
        reactivated=reactivated,
        reason=ent.grant_reason or body.reason,
        note=ent.notes,
        granted_at=ent.updated_at if reactivated else ent.created_at,
        granted_by_user_id=admin.id,
        member_name=member.name,
        member_email=member.email,
        pathway_title=pathway.title,
        space_name=space.name,
        space_slug=space.slug,
    )


# Human-facing labels used inside the creator notification message so a
# creator reads "Complimentary access" rather than "comp".
_GRANT_REASON_LABELS: dict[str, str] = {
    "comp":        "Complimentary access",
    "beta":        "Beta or testing access",
    "migration":   "Migration",
    "correction":  "Purchase correction",
    "replacement": "Replacement access",
    "other":       "Other",
}


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

    # ── Stage 2 Mother World fields ─────────────────────────────────────
    from datetime import datetime, timedelta
    from app.admin.schemas import MotherWorldHealth, MotherWorldMoment
    from app.core.config import settings as _s

    now_utc = datetime.utcnow()
    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now_utc - timedelta(days=7)

    upcoming_gatherings = (
        db.query(func.count(Event.id))
        .filter(
            Event.is_published.is_(True),
            Event.status == "active",
            Event.starts_at > now_utc,
        )
        .scalar() or 0
    )
    total_gross_cents_today = int(
        db.query(func.sum(PaymentTransaction.gross_amount_cents))
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.updated_at >= start_of_day,
        )
        .scalar() or 0
    )
    total_gross_cents_7d = int(
        db.query(func.sum(PaymentTransaction.gross_amount_cents))
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            PaymentTransaction.updated_at >= seven_days_ago,
        )
        .scalar() or 0
    )
    failed_transactions_7d = (
        db.query(func.count(PaymentTransaction.id))
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.failed,
            PaymentTransaction.updated_at >= seven_days_ago,
        )
        .scalar() or 0
    )

    recent_moments = _collect_recent_moments(db, limit=5)

    world_health = MotherWorldHealth(
        platform_ok=True,  # if we're serving this response, the platform is up
        stripe_ok=bool(_s.stripe_enabled),
        webhook_configured=bool(_s.stripe_webhook_secret),
        standalone_gathering_sales_enabled=bool(_s.standalone_gathering_sales_enabled),
        stripe_mode=_s.stripe_mode,
        last_backup_at=None,  # no scheduled backup automation yet — reported honestly
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
        upcoming_gatherings=upcoming_gatherings,
        total_gross_cents_today=total_gross_cents_today,
        total_gross_cents_7d=total_gross_cents_7d,
        failed_transactions_7d=failed_transactions_7d,
        recent_moments=recent_moments,
        world_health=world_health,
    )


def _collect_recent_moments(db: Session, *, limit: int = 5) -> list:
    """
    Assemble a small chronological feed of "moments" for Mother World.

    Draws from a handful of cross-table sources and formats each as a
    natural-language sentence about a person or community. Intentionally
    bounded so the feed stays skimmable — no infinite scroll.

    Sources:
      - Recently published Collectives
      - Recently succeeded member purchases
      - Recently signed-up users
      - Recently published Gatherings

    Returns the newest `limit` events across all sources.
    """
    from datetime import datetime
    from app.admin.schemas import MotherWorldMoment
    from app.models.user import User as UserModel

    per_source = max(limit, 3)
    moments: list[MotherWorldMoment] = []

    # 1. Recently published Collectives
    recent_spaces = (
        db.query(Space).filter(Space.status == "active")
        .order_by(Space.created_at.desc())
        .limit(per_source)
        .all()
    )
    creator_ids = {s.creator_id for s in recent_spaces if s.creator_id}
    creators_by_id = {}
    if creator_ids:
        creators_by_id = {
            u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(creator_ids)).all()
        }
    for s in recent_spaces:
        moments.append(MotherWorldMoment(
            kind="collective",
            # Warmer phrasing (Stage 3): the Collective is the subject of
            # its own arrival, not the creator. Reads as a moment in the
            # world rather than a database write. Matches the style in
            # the spec ("Coral Cay opened its doors.").
            message=f"{s.name} opened its doors.",
            when=s.created_at,
            href="/admin/collectives",
        ))

    # 2. Recently succeeded member purchases
    recent_txns = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
        )
        .order_by(PaymentTransaction.updated_at.desc())
        .limit(per_source)
        .all()
    )
    payer_ids = {t.payer_user_id for t in recent_txns if t.payer_user_id}
    space_ids = {t.space_id for t in recent_txns if t.space_id}
    payers_by_id = {}
    spaces_by_id = {}
    if payer_ids:
        payers_by_id = {
            u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(payer_ids)).all()
        }
    if space_ids:
        spaces_by_id = {
            s.id: s for s in db.query(Space).filter(Space.id.in_(space_ids)).all()
        }
    for t in recent_txns:
        payer = payers_by_id.get(t.payer_user_id) if t.payer_user_id else None
        first_name = (payer.name.split()[0] if payer and payer.name else "A member")
        space = spaces_by_id.get(t.space_id) if t.space_id else None
        space_name = space.name if space else "a Collective"
        moments.append(MotherWorldMoment(
            kind="transaction",
            message=f"{first_name} became part of {space_name}.",
            when=t.updated_at,
            href="/admin/payments",
        ))

    # 3. Recently signed-up users
    recent_users = (
        db.query(UserModel)
        .order_by(UserModel.created_at.desc())
        .limit(per_source)
        .all()
    )
    for u in recent_users:
        first_name = (u.name.split()[0] if u.name else "Someone")
        moments.append(MotherWorldMoment(
            kind="signup",
            message=f"{first_name} arrived in Fresh Collective.",
            when=u.created_at,
            href="/admin/users",
        ))

    # 4. Recently published Gatherings
    recent_events = (
        db.query(Event)
        .filter(Event.is_published.is_(True))
        .order_by(Event.created_at.desc())
        .limit(per_source)
        .all()
    )
    for e in recent_events:
        space = db.query(Space).filter(Space.id == e.space_id).first()
        space_name = space.name if space else "a Collective"
        moments.append(MotherWorldMoment(
            kind="gathering",
            message=f"{space_name} shared a new gathering.",
            when=e.created_at,
            href="/admin/collectives",
        ))

    moments.sort(key=lambda m: m.when, reverse=True)
    return moments[:limit]


@router.get("/platform/collectives", response_model=list[AdminCollectiveRow])
def list_all_collectives(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCollectiveRow]:
    """Live collectives across the platform, with counts + activity + health.

    Only spaces with `status == active` are returned — the same rule that
    makes a collective a live community in the member-facing platform.
    Drafts belong in the creator's own studio (they are unfinished work);
    archived collectives are a historical view that World Management does
    not currently expose. Both remain untouched in the database.

    All aggregates are batched so the response stays O(1) queries
    regardless of collective count.
    """
    from datetime import timedelta
    from app.models.platform import CommunityPost, Location
    from app.models.user import User as UserModel

    spaces = (
        db.query(Space)
        .filter(Space.status == "active")
        .order_by(Space.created_at.desc())
        .all()
    )

    # ---- Batch counts (existing) ----------------------------------------
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

    # ---- Activity signals -----------------------------------------------
    # last_activity_at = MAX across the four community-facing signals:
    # published posts, published pathways, published gatherings, active joins.
    # Draft / admin / billing changes intentionally excluded.
    last_post = dict(
        db.query(CommunityPost.space_id, func.max(CommunityPost.created_at))
        .filter(CommunityPost.publication_status == "published")
        .group_by(CommunityPost.space_id)
        .all()
    )
    last_pathway = dict(
        db.query(Pathway.space_id, func.max(Pathway.created_at))
        .group_by(Pathway.space_id)
        .all()
    )
    last_event = dict(
        db.query(Event.space_id, func.max(Event.created_at))
        .filter(Event.is_published.is_(True))
        .group_by(Event.space_id)
        .all()
    )
    last_join = dict(
        db.query(SpaceMembership.space_id, func.max(SpaceMembership.joined_at))
        .filter(
            SpaceMembership.role == "learner",
            SpaceMembership.status == "active",
        )
        .group_by(SpaceMembership.space_id)
        .all()
    )

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    new_members_7d = dict(
        db.query(SpaceMembership.space_id, func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.role == "learner",
            SpaceMembership.status == "active",
            SpaceMembership.joined_at >= week_ago,
        )
        .group_by(SpaceMembership.space_id)
        .all()
    )
    next_gathering = dict(
        db.query(Event.space_id, func.min(Event.starts_at))
        .filter(
            Event.is_published.is_(True),
            Event.status == "active",
            Event.starts_at > now,
        )
        .group_by(Event.space_id)
        .all()
    )

    # ---- Location + creator lookups -------------------------------------
    location_ids = {s.location_id for s in spaces if s.location_id}
    locations_by_id: dict[str, Location] = (
        {l.id: l for l in db.query(Location).filter(Location.id.in_(location_ids)).all()}
        if location_ids else {}
    )

    creator_ids = {s.creator_id for s in spaces if s.creator_id}
    creator_map: dict[str, UserModel] = (
        {u.id: u for u in db.query(UserModel).filter(UserModel.id.in_(creator_ids)).all()}
        if creator_ids else {}
    )

    # ---- Assemble rows --------------------------------------------------
    rows: list[AdminCollectiveRow] = []
    for s in spaces:
        creator = creator_map.get(s.creator_id) if s.creator_id else None
        location = locations_by_id.get(s.location_id) if s.location_id else None
        status_val = s.status.value if hasattr(s.status, "value") else str(s.status)

        last_activity_at = _max_optional(
            last_post.get(s.id),
            last_pathway.get(s.id),
            last_event.get(s.id),
            last_join.get(s.id),
        )
        n_new_7d = int(new_members_7d.get(s.id, 0))
        next_g_at = next_gathering.get(s.id)
        member_count = int(mem_counts.get(s.id, 0))

        health = _derive_collective_health(
            status=status_val,
            member_count=member_count,
            created_at=s.created_at,
            last_activity_at=last_activity_at,
            now=now,
        )
        phrase = _derive_activity_phrase(
            status=status_val,
            created_at=s.created_at,
            last_activity_at=last_activity_at,
            member_count=member_count,
            new_members_7d=n_new_7d,
            next_gathering_at=next_g_at,
            now=now,
        )

        rows.append(AdminCollectiveRow(
            id=s.id,
            name=s.name,
            slug=s.slug,
            status=status_val,
            is_public=s.is_public,
            has_paid_internal_content=getattr(s, "has_paid_internal_content", False),
            creator_id=s.creator_id,
            creator_name=creator.name if creator else None,
            creator_email=creator.email if creator else None,
            member_count=member_count,
            pathway_count=pathway_counts.get(s.id, 0),
            gathering_count=gathering_counts.get(s.id, 0),
            resource_count=resource_counts.get(s.id, 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
            cover_image_url=s.cover_image_url,
            location_id=s.location_id,
            location_name=location.name if location else None,
            location_hero_artwork_url=location.hero_artwork_url if location else None,
            last_activity_at=last_activity_at,
            next_gathering_at=next_g_at,
            new_members_7d=n_new_7d,
            health=health,
            activity_phrase=phrase,
        ))
    return rows


# ---------------------------------------------------------------------------
# Collective health + activity phrasing
#
# Centralised here so /admin/collectives, Mother World and any future caller
# render the same, single truthful signal per collective. Rules follow the
# product spec agreed for the Gallery/List redesign:
#
#   Healthy         — activity within 21 days
#   Quiet           — 22–59 days inactive (routine)
#   Needs attention — 60+ days inactive, or long-running draft, or Active
#                     with zero members after a grace window
#
# Archived collectives are intentionally never surfaced as "needs attention" —
# an archive is a deliberate act, not a health issue.
# ---------------------------------------------------------------------------


def _max_optional(*dts: datetime | None) -> datetime | None:
    values = [d for d in dts if d is not None]
    return max(values) if values else None


def _min_optional(*dts: datetime | None) -> datetime | None:
    values = [d for d in dts if d is not None]
    return min(values) if values else None


def _derive_collective_health(
    *,
    status: str,
    member_count: int,
    created_at: datetime,
    last_activity_at: datetime | None,
    now: datetime,
) -> str:
    age_days = (now - created_at).days
    if status == "archived":
        return "quiet"
    if status == "draft":
        return "needs_attention" if age_days >= 30 else "quiet"
    # active
    if member_count == 0 and age_days >= 7:
        return "needs_attention"
    reference = last_activity_at or created_at
    inactive_days = (now - reference).days
    if inactive_days >= 60:
        return "needs_attention"
    if inactive_days >= 22:
        return "quiet"
    return "healthy"


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _derive_activity_phrase(
    *,
    status: str,
    created_at: datetime,
    last_activity_at: datetime | None,
    member_count: int,
    new_members_7d: int,
    next_gathering_at: datetime | None,
    now: datetime,
) -> str:
    if status == "draft":
        age_days = (now - created_at).days
        if age_days >= 30:
            return f"In draft for {_weeks(age_days)}"
        return "In draft"
    if status == "archived":
        return "Archived"

    # Active — try meaningful upcoming/recent events first, then fall back
    # to recency wording. Only ever return one phrase.
    if next_gathering_at is not None:
        delta_days = (next_gathering_at.date() - now.date()).days
        if 0 <= delta_days <= 7:
            if delta_days == 0:
                return "Gathering today"
            if delta_days == 1:
                return "Gathering tomorrow"
            return f"Gathering in {delta_days} days"

    if new_members_7d >= 3:
        return f"{new_members_7d} new members this week"

    if member_count == 0:
        age_days = (now - created_at).days
        if age_days < 7:
            return "New this week"
        return "Waiting for its first member"

    if last_activity_at is None:
        # No community-facing signal yet, so fall back to how long the
        # collective itself has existed.
        age_days = (now - created_at).days
        if age_days <= 1:
            return "New today"
        if age_days < 7:
            return "New this week"
        if age_days < 22:
            return "Quiet so far"
        if age_days < 60:
            return f"Quiet for {_weeks(age_days)}"
        return f"Sleeping since {_month_year(created_at, now)}"

    days = (now - last_activity_at).days
    if days <= 1:
        return "Active today"
    if days < 7:
        return "Active this week"
    if days < 22:
        return "Quiet this week"
    if days < 60:
        return f"Quiet for {_weeks(days)}"
    return f"Sleeping since {_month_year(last_activity_at, now)}"


def _weeks(days: int) -> str:
    weeks = max(1, days // 7)
    return "1 week" if weeks == 1 else f"{weeks} weeks"


def _month_year(dt: datetime, now: datetime) -> str:
    name = _MONTHS[dt.month - 1]
    return name if dt.year == now.year else f"{name} {dt.year}"


# ---------------------------------------------------------------------------
# Creator health + activity phrasing
#
# Health aggregates from the creator's Collectives so /admin/creators and
# /admin/collectives never disagree about who's healthy. States match the
# Creators-page product spec:
#
#   flourishing   — active builder, growth or upcoming gatherings recently
#   new           — arrived in the last 30 days (a state to celebrate)
#   quiet         — active but nothing new in the last 30 days
#   needs_support — a collective flagged needs_attention, or long dormant,
#                   or has been here 30+ days without opening a collective
# ---------------------------------------------------------------------------


def _derive_creator_health(
    *,
    created_at: datetime,
    has_collectives: bool,
    any_collective_needs_attention: bool,
    last_activity_at: datetime | None,
    new_members_30d: int,
    next_gathering_at: datetime | None,
    now: datetime,
) -> str:
    age_days = (now - created_at).days
    if any_collective_needs_attention:
        return "needs_support"
    if not has_collectives:
        # Grace window for a brand-new creator; after 30 days without
        # opening a collective the caretaker probably wants a nudge.
        return "needs_support" if age_days >= 30 else "new"
    if last_activity_at is None:
        # Has collectives but no community-facing activity yet.
        return "new" if age_days < 30 else "quiet"
    days_inactive = (now - last_activity_at).days
    if days_inactive >= 60:
        return "needs_support"
    if age_days < 30:
        return "new"
    recently_upcoming = (
        next_gathering_at is not None
        and (next_gathering_at - now).days <= 30
    )
    if new_members_30d > 0 or recently_upcoming or days_inactive < 30:
        return "flourishing"
    return "quiet"


def _derive_creator_activity_phrase(
    *,
    created_at: datetime,
    has_collectives: bool,
    last_activity_at: datetime | None,
    latest_post: datetime | None,
    latest_pathway: datetime | None,
    latest_event: datetime | None,
    new_members_30d: int,
    next_gathering_at: datetime | None,
    now: datetime,
) -> str:
    age_days = (now - created_at).days

    if not has_collectives:
        if age_days < 7:
            return "Just arrived"
        if age_days < 30:
            return "Still finding their feet"
        return "Yet to open a collective"

    # Priority: upcoming gathering (immediate), then bursts of new members,
    # then latest publication with the specific kind named, then generic
    # recency. Always exactly one truthful phrase.
    if next_gathering_at is not None:
        delta_days = (next_gathering_at.date() - now.date()).days
        if 0 <= delta_days <= 7:
            if delta_days == 0:
                return "Hosting a gathering today"
            if delta_days == 1:
                return "Hosting a gathering tomorrow"
            return f"Hosting a gathering in {delta_days} days"

    if new_members_30d >= 3:
        return f"Welcomed {new_members_30d} members this month"

    # A specific publication phrase reads warmer than "Active this week"
    # when we know what was published. Only used if it happened recently.
    publication_candidates: list[tuple[datetime, str]] = []
    if latest_pathway is not None:
        publication_candidates.append((latest_pathway, "pathway"))
    if latest_event is not None:
        publication_candidates.append((latest_event, "gathering"))
    if latest_post is not None:
        publication_candidates.append((latest_post, "post"))
    if publication_candidates:
        publication_candidates.sort(key=lambda p: p[0], reverse=True)
        when, kind = publication_candidates[0]
        days = (now - when).days
        if days <= 7:
            weekday = when.strftime("%A")
            if kind == "pathway":
                return f"Published a new pathway on {weekday}"
            if kind == "gathering":
                return f"Shared a new gathering on {weekday}"
            return f"Posted on {weekday}"

    if last_activity_at is None:
        if age_days < 30:
            return f"Building since {_month_year(created_at, now)}"
        return "Quiet across their collectives"

    days = (now - last_activity_at).days
    if days <= 1:
        return "Active today"
    if days < 7:
        return "Active this week"
    if days < 22:
        return "Steady across their collectives"
    if days < 60:
        return "Quiet across their collectives"
    return f"Sleeping since {_month_year(last_activity_at, now)}"


@router.get("/platform/creators", response_model=list[AdminCreatorRow])
def list_platform_creators(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCreatorRow]:
    """All creator and admin users with plan, activity and derived health
    for the redesigned /admin/creators Gallery/List.

    Health is aggregated from the same activity signals that drive
    /admin/collectives — the two pages must never disagree about who's
    healthy. All aggregates are batched so the response stays O(1)
    queries regardless of creator count.
    """
    from datetime import timedelta
    from app.models.platform import CommunityPost, CreatorProfile, Location
    from app.models.user import User as UserModel

    creators = (
        db.query(UserModel)
        .filter(UserModel.role.in_(["creator", "admin"]))
        .order_by(UserModel.created_at)
        .all()
    )
    if not creators:
        return []

    creator_ids = [c.id for c in creators]

    # ---- Plans + subscriptions ------------------------------------------
    plans_by_id = {p.id: p for p in db.query(CreatorPlan).all()}
    subs = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id.in_(creator_ids),
            CreatorSubscription.status.in_(["active", "trialing"]),
        )
        .all()
    )
    sub_map: dict[str, CreatorSubscription] = {s.user_id: s for s in subs}
    fallback_plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .first()
    )

    # ---- Avatars --------------------------------------------------------
    profile_avatars = dict(
        db.query(CreatorProfile.user_id, CreatorProfile.avatar_url)
        .filter(CreatorProfile.user_id.in_(creator_ids))
        .all()
    )

    # ---- Active spaces owned by these creators --------------------------
    # World Management shows the *live* world — draft/archived spaces are
    # legitimate parts of a creator's inventory but they don't shape the
    # public census. Health and activity aggregate only over active spaces
    # so the caretaker sees the same truth on both /admin/creators and
    # /admin/collectives.
    active_spaces = (
        db.query(Space)
        .filter(
            Space.creator_id.in_(creator_ids),
            Space.status == "active",
        )
        .all()
    )
    spaces_by_creator: dict[str, list[Space]] = {}
    for s in active_spaces:
        if s.creator_id:
            spaces_by_creator.setdefault(s.creator_id, []).append(s)
    active_space_ids = [s.id for s in active_spaces]

    # Non-archived (active + draft) total for the plan-usage count on the
    # row — this mirrors what Creator Plans uses for capacity accounting.
    inventory_counts = dict(
        db.query(Space.creator_id, func.count(Space.id))
        .filter(
            Space.creator_id.in_(creator_ids),
            Space.status.notin_(["archived"]),
        )
        .group_by(Space.creator_id)
        .all()
    )

    # ---- Locations for space chips --------------------------------------
    location_ids = {s.location_id for s in active_spaces if s.location_id}
    locations_by_id: dict[str, Location] = (
        {l.id: l for l in db.query(Location).filter(Location.id.in_(location_ids)).all()}
        if location_ids else {}
    )

    # ---- Per-space aggregates (only over active spaces) -----------------
    # Batched so the whole endpoint stays O(1) queries. Draft/admin/billing
    # signals are deliberately excluded — same rule as the collectives feed.
    now = datetime.utcnow()
    month_ago = now - timedelta(days=30)

    mem_counts: dict[str, int] = {}
    last_post: dict[str, datetime] = {}
    last_pathway: dict[str, datetime] = {}
    last_event: dict[str, datetime] = {}
    last_join: dict[str, datetime] = {}
    new_members_30d_by_space: dict[str, int] = {}
    next_gathering_by_space: dict[str, datetime] = {}

    if active_space_ids:
        mem_counts = dict(
            db.query(SpaceMembership.space_id, func.count(SpaceMembership.id))
            .filter(
                SpaceMembership.space_id.in_(active_space_ids),
                SpaceMembership.role == "learner",
                SpaceMembership.status == "active",
            )
            .group_by(SpaceMembership.space_id)
            .all()
        )
        last_post = dict(
            db.query(CommunityPost.space_id, func.max(CommunityPost.created_at))
            .filter(
                CommunityPost.space_id.in_(active_space_ids),
                CommunityPost.publication_status == "published",
            )
            .group_by(CommunityPost.space_id)
            .all()
        )
        last_pathway = dict(
            db.query(Pathway.space_id, func.max(Pathway.created_at))
            .filter(Pathway.space_id.in_(active_space_ids))
            .group_by(Pathway.space_id)
            .all()
        )
        last_event = dict(
            db.query(Event.space_id, func.max(Event.created_at))
            .filter(
                Event.space_id.in_(active_space_ids),
                Event.is_published.is_(True),
            )
            .group_by(Event.space_id)
            .all()
        )
        last_join = dict(
            db.query(SpaceMembership.space_id, func.max(SpaceMembership.joined_at))
            .filter(
                SpaceMembership.space_id.in_(active_space_ids),
                SpaceMembership.role == "learner",
                SpaceMembership.status == "active",
            )
            .group_by(SpaceMembership.space_id)
            .all()
        )
        new_members_30d_by_space = dict(
            db.query(SpaceMembership.space_id, func.count(SpaceMembership.id))
            .filter(
                SpaceMembership.space_id.in_(active_space_ids),
                SpaceMembership.role == "learner",
                SpaceMembership.status == "active",
                SpaceMembership.joined_at >= month_ago,
            )
            .group_by(SpaceMembership.space_id)
            .all()
        )
        next_gathering_by_space = dict(
            db.query(Event.space_id, func.min(Event.starts_at))
            .filter(
                Event.space_id.in_(active_space_ids),
                Event.is_published.is_(True),
                Event.status == "active",
                Event.starts_at > now,
            )
            .group_by(Event.space_id)
            .all()
        )

    # ---- Assemble rows --------------------------------------------------
    rows: list[AdminCreatorRow] = []
    for creator in creators:
        sub = sub_map.get(creator.id)
        plan = (plans_by_id.get(sub.creator_plan_id) if sub else None) or fallback_plan
        plan_name = plan.name if plan else "—"
        sub_status = "none"
        if sub:
            sub_status = sub.status.value if hasattr(sub.status, "value") else str(sub.status)

        their_spaces = spaces_by_creator.get(creator.id, [])
        # spaces_by_creator only holds active spaces, so its length is the
        # published count. Draft = non-archived total minus published, no
        # extra query needed.
        published_count = len(their_spaces)
        inventory_total = int(inventory_counts.get(creator.id, 0))
        draft_count = max(0, inventory_total - published_count)
        chips = [
            AdminCreatorCollectiveChip(
                id=s.id,
                slug=s.slug,
                name=s.name,
                location_name=(locations_by_id[s.location_id].name if s.location_id and s.location_id in locations_by_id else None),
                location_hero_artwork_url=(locations_by_id[s.location_id].hero_artwork_url if s.location_id and s.location_id in locations_by_id else None),
            )
            for s in sorted(their_spaces, key=lambda x: x.created_at, reverse=True)
        ]

        members_reached = sum(mem_counts.get(s.id, 0) for s in their_spaces)
        new_members_30d = sum(new_members_30d_by_space.get(s.id, 0) for s in their_spaces)
        next_gathering_at = _min_optional(*(next_gathering_by_space.get(s.id) for s in their_spaces))
        latest_post = _max_optional(*(last_post.get(s.id) for s in their_spaces))
        latest_pathway = _max_optional(*(last_pathway.get(s.id) for s in their_spaces))
        latest_event = _max_optional(*(last_event.get(s.id) for s in their_spaces))
        latest_join = _max_optional(*(last_join.get(s.id) for s in their_spaces))
        last_activity_at = _max_optional(latest_post, latest_pathway, latest_event, latest_join)

        # Health mirrors what the caretaker sees on /admin/collectives:
        # a creator whose active collectives all sit inside the healthy
        # window is flourishing; a creator with a needs_attention collective
        # inherits that concern.
        any_collective_needs_attention = any(
            _derive_collective_health(
                status="active",
                member_count=mem_counts.get(s.id, 0),
                created_at=s.created_at,
                last_activity_at=_max_optional(
                    last_post.get(s.id), last_pathway.get(s.id), last_event.get(s.id), last_join.get(s.id),
                ),
                now=now,
            ) == "needs_attention"
            for s in their_spaces
        )
        health = _derive_creator_health(
            created_at=creator.created_at,
            has_collectives=bool(their_spaces),
            any_collective_needs_attention=any_collective_needs_attention,
            last_activity_at=last_activity_at,
            new_members_30d=new_members_30d,
            next_gathering_at=next_gathering_at,
            now=now,
        )
        phrase = _derive_creator_activity_phrase(
            created_at=creator.created_at,
            has_collectives=bool(their_spaces),
            last_activity_at=last_activity_at,
            latest_post=latest_post,
            latest_pathway=latest_pathway,
            latest_event=latest_event,
            new_members_30d=new_members_30d,
            next_gathering_at=next_gathering_at,
            now=now,
        )

        rows.append(AdminCreatorRow(
            id=creator.id,
            name=creator.name,
            email=creator.email,
            role=creator.role,
            created_at=creator.created_at,
            collective_count=inventory_total,
            published_collective_count=published_count,
            draft_collective_count=draft_count,
            plan_name=plan_name,
            subscription_status=sub_status,
            avatar_url=profile_avatars.get(creator.id),
            collectives=chips,
            total_members_reached=members_reached,
            last_activity_at=last_activity_at,
            next_gathering_at=next_gathering_at,
            new_members_30d=new_members_30d,
            health=health,
            activity_phrase=phrase,
        ))
    return rows


@router.get("/platform/users", response_model=list[AdminUserRow])
def list_platform_users(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminUserRow]:
    """All users with their derived role badges and the actual collectives
    they belong to / have created. Admin only.

    Roles are derived rather than stored, so a person can carry more than
    one at once (e.g. Owner + Creator). Sourced from:

      - **owner**   — email matches ``settings.platform_owner_email``
      - **admin**   — ``role == "admin"`` in the DB *and not* the owner
                      (reserved for future platform staff)
      - **creator** — owns at least one non-archived Space
      - **member**  — has at least one active learner membership

    Everyone gets at least one badge; a user with none of the above still
    reads as a **member**.
    """
    from app.core.config import settings
    from app.models.user import User as UserModel

    users = db.query(UserModel).order_by(UserModel.created_at.desc()).all()

    # Batch-fetch the actual collectives (name + slug), not counts, so the
    # Members page can list them. One row per (user, space) — grouped in
    # Python to avoid a second round-trip.
    joined_rows = (
        db.query(
            SpaceMembership.user_id,
            Space.id,
            Space.name,
            Space.slug,
        )
        .join(Space, SpaceMembership.space_id == Space.id)
        .filter(
            SpaceMembership.role == "learner",
            SpaceMembership.status == "active",
            Space.status != "archived",
        )
        .order_by(SpaceMembership.user_id, Space.name)
        .all()
    )
    joined_map: dict[str, list[CollectiveRef]] = {}
    for user_id, space_id, name, slug in joined_rows:
        joined_map.setdefault(user_id, []).append(
            CollectiveRef(id=space_id, name=name, slug=slug)
        )

    owned_rows = (
        db.query(Space.creator_id, Space.id, Space.name, Space.slug)
        .filter(Space.creator_id.isnot(None), Space.status != "archived")
        .order_by(Space.creator_id, Space.name)
        .all()
    )
    owned_map: dict[str, list[CollectiveRef]] = {}
    for creator_id, space_id, name, slug in owned_rows:
        owned_map.setdefault(creator_id, []).append(
            CollectiveRef(id=space_id, name=name, slug=slug)
        )

    owner_email = (settings.platform_owner_email or "").strip().lower()

    rows: list[AdminUserRow] = []
    for u in users:
        joined = joined_map.get(u.id, [])
        owned = owned_map.get(u.id, [])
        is_owner = bool(owner_email) and (u.email or "").strip().lower() == owner_email
        rows.append(
            AdminUserRow(
                id=u.id,
                name=u.name,
                email=u.email,
                roles=_derive_role_badges(
                    db_role=u.role,
                    is_owner=is_owner,
                    has_owned=bool(owned),
                    has_joined=bool(joined),
                ),
                created_at=u.created_at,
                joined_collectives=joined,
                owned_collectives=owned,
            )
        )
    return rows


def _derive_role_badges(
    *, db_role: str, is_owner: bool, has_owned: bool, has_joined: bool
) -> list[str]:
    """Ordered most-privileged → least. Everyone gets at least 'member'."""
    badges: list[str] = []
    if is_owner:
        badges.append("owner")
    elif db_role == "admin":
        badges.append("admin")
    if has_owned:
        badges.append("creator")
    if has_joined:
        badges.append("member")
    if not badges:
        badges.append("member")
    return badges


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

_ADMIN_PLAN_ORDER = {p.slug: i for i, p in enumerate(ALL_PLANS)}


def _admin_plan_row(
    plan: CreatorPlan | None,
    capability: PlanCapability | None,
    active_subscriptions: int,
) -> AdminCreatorPlanRow:
    """Merge a DB `CreatorPlan` row with its capability record from
    `plan_config`. Either side may be None:

      - `plan=None, capability=Organisation`: synthesises Organisation as a
        catalogue entry without a DB row (Organisation is not a
        subscribable plan).
      - `plan=<row>, capability=None`: legacy DB row we don't recognise —
        pass through DB values and fall back to sensible capability
        defaults.
    """
    if plan is not None:
        row_id = plan.id
        name = plan.name
        slug = plan.slug
        description = plan.description
        monthly_price_cents = plan.monthly_price_cents
        currency = plan.currency
        transaction_fee_basis_points = plan.transaction_fee_basis_points
        collective_limit = plan.collective_limit
        is_active = plan.is_active
        created_at = plan.created_at
    elif capability is not None:
        row_id = f"synthetic-{capability.slug}"
        name = capability.display_name
        slug = capability.slug
        description = capability.positioning
        monthly_price_cents = capability.monthly_price_cents
        currency = capability.currency
        transaction_fee_basis_points = capability.transaction_fee_basis_points
        collective_limit = capability.active_collective_limit
        # Synthetic entries are considered available if the capability record
        # is marked as such — Organisation is `is_purchasable=False` but still
        # "available" in the catalogue as an enterprise offering.
        is_active = True
        created_at = None
    else:
        raise ValueError("Both plan and capability were None.")

    # Community shows no transaction fee (no paid offers) even though the
    # DB stores 0 bp. Represent that as null in the API so the frontend
    # can hide the metric rather than showing "0%".
    if capability is not None and not capability.paid_offers_enabled:
        transaction_fee_basis_points = None

    plan_type = "enterprise" if capability is not None and not capability.is_purchasable else "subscription"

    return AdminCreatorPlanRow(
        id=row_id,
        name=name,
        slug=slug,
        description=description,
        monthly_price_cents=monthly_price_cents,
        currency=currency,
        transaction_fee_basis_points=transaction_fee_basis_points,
        collective_limit=collective_limit,
        is_active=is_active,
        active_subscriptions=active_subscriptions,
        created_at=created_at,
        plan_type=plan_type,
        paid_offers_enabled=capability.paid_offers_enabled if capability else True,
        commercial_use=capability.commercial_use if capability else True,
        is_purchasable=capability.is_purchasable if capability else True,
        # Sourced from PlanCapability — same value the enforcement path
        # reads — so the catalogue display and the limit-check code can
        # never drift on member allowance.
        member_allowance_per_collective=(
            capability.member_allowance_per_collective if capability else None
        ),
    )


@router.get("/creator-plans", response_model=list[AdminCreatorPlanRow])
def list_creator_plans(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminCreatorPlanRow]:
    """The canonical Plan Catalogue.

    Returns Community / Creator / Pro (as DB rows) plus Organisation (as a
    synthetic catalogue entry — Organisation is not a subscribable plan and
    lives in `plan_config` only). Ordered Community → Creator → Pro →
    Organisation regardless of monthly price.

    Any additional DB plans that aren't in the canonical lineup are
    appended after Organisation so nothing is silently hidden from admins."""
    plans = db.query(CreatorPlan).all()

    sub_counts: dict[str, int] = dict(
        db.query(CreatorSubscription.creator_plan_id, func.count(CreatorSubscription.id))
        .filter(CreatorSubscription.status.in_([
            CreatorSubscriptionStatus.active,
            CreatorSubscriptionStatus.trialing,
        ]))
        .group_by(CreatorSubscription.creator_plan_id)
        .all()
    )

    rows: list[AdminCreatorPlanRow] = [
        _admin_plan_row(plan, get_plan_capability(plan.slug), sub_counts.get(plan.id, 0))
        for plan in plans
    ]
    # Append Organisation as a synthetic entry. Organisation is an
    # enterprise pathway, not a subscribable plan, so active_subscriptions
    # is always 0.
    rows.append(_admin_plan_row(None, ORGANISATION, 0))

    rows.sort(key=lambda r: _ADMIN_PLAN_ORDER.get(r.slug, 999))
    return rows


@router.post("/creator-plans", response_model=AdminCreatorPlanRow, status_code=201)
def create_creator_plan(
    body: AdminCreatorPlanCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminCreatorPlanRow:
    """Create a new creator billing plan. Slug must be unique. Admin only."""
    existing = db.query(CreatorPlan).filter(CreatorPlan.slug == body.slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A plan with slug '{body.slug}' already exists.")

    if body.monthly_price_cents < 0:
        raise HTTPException(status_code=422, detail="monthly_price_cents must be >= 0.")
    if body.transaction_fee_basis_points < 0 or body.transaction_fee_basis_points > 10000:
        raise HTTPException(status_code=422, detail="transaction_fee_basis_points must be 0–10000.")
    if body.collective_limit < 1:
        raise HTTPException(status_code=422, detail="collective_limit must be >= 1.")

    plan = CreatorPlan(
        id=str(uuid4()),
        name=body.name,
        slug=body.slug,
        description=body.description,
        monthly_price_cents=body.monthly_price_cents,
        currency=body.currency.upper(),
        transaction_fee_basis_points=body.transaction_fee_basis_points,
        collective_limit=body.collective_limit,
        is_active=body.is_active,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    return _admin_plan_row(plan, get_plan_capability(plan.slug), 0)


@router.patch("/creator-plans/{plan_id}", response_model=AdminCreatorPlanRow)
def edit_creator_plan(
    plan_id: str,
    body: AdminCreatorPlanEdit,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminCreatorPlanRow:
    """Edit a DB-backed ``CreatorPlan``. Admin only.

    Refuses when the target id belongs to a synthetic catalogue entry
    (Organisation, whose id starts with ``synthetic-``). Slug is never
    editable — it is a stable system identifier that other rows
    reference by string. Only supplied fields are updated; validation
    mirrors the create endpoint.

    Every edit that changes at least one field writes an append-only
    ``PlanChangeEvent`` capturing the before/after values, the actor
    (``changed_by_user_id``), and the timestamp.
    """
    from app.models.creator_billing import PlanChangeEvent

    if plan_id.startswith("synthetic-"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Synthetic catalogue entries (e.g. Organisation) are not "
                "backed by a database row and cannot be edited here."
            ),
        )

    plan = db.query(CreatorPlan).filter(CreatorPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")

    # --- Validate supplied fields (mirrors create endpoint) --------------
    if body.monthly_price_cents is not None and body.monthly_price_cents < 0:
        raise HTTPException(status_code=422, detail="monthly_price_cents must be >= 0.")
    if body.transaction_fee_basis_points is not None and not (
        0 <= body.transaction_fee_basis_points <= 10000
    ):
        raise HTTPException(status_code=422, detail="transaction_fee_basis_points must be 0–10000.")
    if body.collective_limit is not None and body.collective_limit < 1:
        raise HTTPException(status_code=422, detail="collective_limit must be >= 1.")
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=422, detail="name must not be empty.")

    # --- Compute diff ----------------------------------------------------
    updates: dict[str, tuple] = {}   # {field: (before, after)}
    def _consider(field: str, before, after) -> None:
        if after is not None and after != before:
            updates[field] = (before, after)

    _consider("name",                          plan.name,                          body.name.strip() if body.name is not None else None)
    _consider("description",                   plan.description,                   body.description)
    _consider("monthly_price_cents",           plan.monthly_price_cents,           body.monthly_price_cents)
    _consider("transaction_fee_basis_points",  plan.transaction_fee_basis_points,  body.transaction_fee_basis_points)
    _consider("collective_limit",              plan.collective_limit,              body.collective_limit)
    _consider("is_active",                     plan.is_active,                     body.is_active)

    if not updates:
        # No-op edit — return the current state, no audit row.
        active_count = (
            db.query(func.count(CreatorSubscription.id))
            .filter(
                CreatorSubscription.creator_plan_id == plan.id,
                CreatorSubscription.status.in_([
                    CreatorSubscriptionStatus.active,
                    CreatorSubscriptionStatus.trialing,
                ]),
            ).scalar() or 0
        )
        return _admin_plan_row(plan, get_plan_capability(plan.slug), int(active_count))

    # --- Apply -----------------------------------------------------------
    for field, (_before, after) in updates.items():
        setattr(plan, field, after)
    plan.updated_at = datetime.utcnow()

    db.add(PlanChangeEvent(
        id=str(uuid4()),
        plan_id=plan.id,
        changed_by_user_id=admin.id,
        changes={field: {"before": before, "after": after} for field, (before, after) in updates.items()},
    ))

    db.commit()
    db.refresh(plan)

    active_count = (
        db.query(func.count(CreatorSubscription.id))
        .filter(
            CreatorSubscription.creator_plan_id == plan.id,
            CreatorSubscription.status.in_([
                CreatorSubscriptionStatus.active,
                CreatorSubscriptionStatus.trialing,
            ]),
        ).scalar() or 0
    )
    return _admin_plan_row(plan, get_plan_capability(plan.slug), int(active_count))


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
            source=sub.source,
            grant_reason=sub.grant_reason,
            granted_by_user_id=sub.granted_by_user_id,
            grant_note=sub.grant_note,
            revoked_at=sub.revoked_at,
            stripe_subscription_id=getattr(sub, "stripe_subscription_id", None),
            stripe_customer_id=getattr(sub, "stripe_customer_id", None),
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        ))
    return rows


# ---------------------------------------------------------------------------
# Revenue dashboard
# ---------------------------------------------------------------------------

def _compute_revenue_summary(
    db: Session,
    *,
    starts_at: "datetime | None" = None,
    ends_at: "datetime | None" = None,
    stripe_mode: str | None = None,
) -> AdminRevenueSummary:
    """Compute an :class:`AdminRevenueSummary` over an optional half-open
    ``[starts_at, ends_at)`` UTC window, optionally further constrained
    by ``stripe_mode``. Called by both the flat and periodic endpoints.
    """
    succeeded = PaymentTransactionStatus.succeeded

    def _mode_filter(q):
        if stripe_mode:
            q = q.filter(PaymentTransaction.stripe_mode == stripe_mode)
        if starts_at is not None:
            q = q.filter(PaymentTransaction.created_at >= starts_at)
        if ends_at is not None:
            q = q.filter(PaymentTransaction.created_at < ends_at)
        return q

    # Creator subscription fees paid to FC (gross = FC revenue)
    sub_revenue = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.gross_amount_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.transaction_type == PaymentTransactionType.creator_subscription_payment,
            )
        ).scalar() or 0
    )

    # Platform fees retained from member purchases
    platform_fee_revenue = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.platform_fee_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            )
        ).scalar() or 0
    )

    # Gross member sales (total of what members paid for creator content)
    gross_sales = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.gross_amount_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
            )
        ).scalar() or 0
    )

    # Creator net from member sales
    creator_net = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
                PaymentTransaction.net_creator_amount_cents.isnot(None),
            )
        ).scalar() or 0
    )

    # Paid out
    paid_out = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.payout_status == PayoutStatus.paid,
                PaymentTransaction.net_creator_amount_cents.isnot(None),
            )
        ).scalar() or 0
    )

    # Pending payout (member sales only — creator subs go to FC directly)
    pending_payout = int(
        _mode_filter(
            db.query(func.sum(PaymentTransaction.net_creator_amount_cents))
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.payout_status == PayoutStatus.pending,
                PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TXN_TYPES]),
                PaymentTransaction.net_creator_amount_cents.isnot(None),
            )
        ).scalar() or 0
    )

    succeeded_count = int(
        _mode_filter(
            db.query(func.count(PaymentTransaction.id))
            .filter(PaymentTransaction.status == succeeded)
        ).scalar() or 0
    )
    refunded_count = int(
        _mode_filter(
            db.query(func.count(PaymentTransaction.id))
            .filter(PaymentTransaction.status.in_([
                PaymentTransactionStatus.refunded,
                PaymentTransactionStatus.partially_refunded,
            ]))
        ).scalar() or 0
    )
    failed_count = int(
        _mode_filter(
            db.query(func.count(PaymentTransaction.id))
            .filter(PaymentTransaction.status == PaymentTransactionStatus.failed)
        ).scalar() or 0
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


@router.get("/revenue/summary", response_model=AdminRevenueSummary)
def get_revenue_summary(
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminRevenueSummary:
    """
    Platform revenue summary for admin revenue dashboard. Admin only.

    Pass ?stripe_mode=live to see only real revenue (default after go-live).
    Pass ?stripe_mode=test to see only sandbox/test figures.
    Omit to see all transactions regardless of mode.
    """
    return _compute_revenue_summary(db, stripe_mode=stripe_mode)


@router.get("/revenue/summary/periodic", response_model=AdminPeriodicRevenueSummary)
def get_revenue_summary_periodic(
    period: str = "this_month",
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminPeriodicRevenueSummary:
    """Revenue summary bracketed by a named reporting period, with the
    comparable previous-period totals returned in the same response.

    Same period grammar as ``/payments/summary/periodic``: ``this_month``
    (MTD), ``last_month`` (full prior month), ``this_fy`` (AU FY-to-date),
    ``all_time`` (no window, no comparison). ``stripe_mode`` remains
    orthogonal — it further constrains both windows but is never mixed
    into the period key.
    """
    from app.core.periods import VALID_PERIODS, resolve_period

    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Valid: {list(VALID_PERIODS)}.",
        )
    current_bounds, previous_bounds = resolve_period(period)  # type: ignore[arg-type]

    current = _compute_revenue_summary(
        db,
        starts_at=current_bounds.starts_at,
        ends_at=current_bounds.ends_at,
        stripe_mode=stripe_mode,
    )
    previous = None
    previous_bounds_out: PeriodBoundsOut | None = None
    if previous_bounds is not None:
        previous = _compute_revenue_summary(
            db,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
            stripe_mode=stripe_mode,
        )
        previous_bounds_out = PeriodBoundsOut(
            label=previous_bounds.label,
            starts_at=previous_bounds.starts_at,
            ends_at=previous_bounds.ends_at,
        )

    return AdminPeriodicRevenueSummary(
        period=period,
        stripe_mode=stripe_mode,
        current_bounds=PeriodBoundsOut(
            label=current_bounds.label,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        ),
        current=current,
        previous_bounds=previous_bounds_out,
        previous=previous,
    )


# ---------------------------------------------------------------------------
# Commerce overview — Stage 2
#
# One-request page shape. Composes:
#   - revenue summary (current + previous windows)
#   - growth counters (current + previous windows)
#   - recent movement (period-agnostic — latest events regardless of the
#     selected window, filtered by stripe_mode)
# ---------------------------------------------------------------------------


def _compute_growth_summary(
    db: Session,
    *,
    starts_at: "datetime | None" = None,
    ends_at: "datetime | None" = None,
) -> GrowthSummary:
    """Count new creators / members / collectives in the given window.

    "New" is defined by ``created_at`` in ``[starts_at, ends_at)``.
    Archived collectives are excluded so a caretaker doesn't see growth
    they later un-shipped. Users are counted by DB role — a user with
    role ``admin`` is counted as a creator (it's the platform-owner
    convention; the future non-owner "admin" role will still show as a
    creator here since they run the platform, not a collective).
    """
    from app.models.platform import Space
    from app.models.user import User as UserModel

    def _window(q, col):
        if starts_at is not None:
            q = q.filter(col >= starts_at)
        if ends_at is not None:
            q = q.filter(col < ends_at)
        return q

    new_creators = int(
        _window(
            db.query(func.count(UserModel.id)).filter(UserModel.role.in_(("creator", "admin"))),
            UserModel.created_at,
        ).scalar() or 0
    )
    new_members = int(
        _window(
            db.query(func.count(UserModel.id)).filter(UserModel.role == "user"),
            UserModel.created_at,
        ).scalar() or 0
    )
    new_collectives = int(
        _window(
            db.query(func.count(Space.id)).filter(Space.status != "archived"),
            Space.created_at,
        ).scalar() or 0
    )

    return GrowthSummary(
        new_creators=new_creators,
        new_members=new_members,
        new_collectives=new_collectives,
    )


def _movement_label_and_kind(
    txn: PaymentTransaction,
    user_names: dict[str, str | None],
    space_names: dict[str, str],
    pathway_titles: dict[str, str],
) -> tuple[str, str]:
    """Return ``(label, kind)`` — the humane one-line event summary the
    Commerce "Recent movement" list renders.

    ``kind`` drives the icon / hue in the UI. Fallback is ``other`` and
    the raw type name, so an unfamiliar transaction still displays
    honestly rather than crashing.
    """
    def _name(user_id: str | None) -> str:
        return (user_names.get(user_id) if user_id else None) or "Someone"

    payer = _name(txn.payer_user_id)
    creator = _name(txn.creator_user_id)
    space = space_names.get(txn.space_id) if txn.space_id else None
    pathway = pathway_titles.get(txn.pathway_id) if txn.pathway_id else None

    ttype = txn.transaction_type.value if hasattr(txn.transaction_type, "value") else str(txn.transaction_type)
    status = txn.status.value if hasattr(txn.status, "value") else str(txn.status)

    # Refunds take precedence over type — a refunded purchase reads as
    # a refund event, not the underlying purchase.
    if status in ("refunded", "partially_refunded") or ttype == "refund":
        target = space or pathway or "a purchase"
        return (f"Refund issued — {target}", "refund")

    if ttype == "creator_subscription_payment":
        return (f"Creator subscription — {creator}", "subscription")
    if ttype == "member_collective_purchase":
        return (f"{payer} joined {space or 'a collective'}", "purchase")
    if ttype == "member_collective_subscription":
        return (f"{payer} subscribed to {space or 'a collective'}", "subscription")
    if ttype == "member_pathway_purchase":
        return (f"{payer} enrolled in {pathway or 'a pathway'}", "purchase")
    if ttype == "member_pathway_subscription":
        return (f"{payer} subscribed to {pathway or 'a pathway'}", "subscription")
    if ttype == "gathering_ticket_purchase":
        return (f"Gathering ticket — {payer}", "ticket")
    if ttype == "adjustment":
        return ("Adjustment", "adjustment")

    return (ttype.replace("_", " ").capitalize(), "other")


def _compute_recent_movements(
    db: Session,
    *,
    stripe_mode: str | None = None,
    limit: int = 10,
) -> list[CommerceMovementEvent]:
    """Fetch the ``limit`` most recent payment events, filtered by
    ``stripe_mode``. Names are bulk-looked-up so the response is
    render-ready without further round-trips.
    """
    from app.models.platform import Pathway, Space
    from app.models.user import User as UserModel

    q = db.query(PaymentTransaction).order_by(PaymentTransaction.created_at.desc())
    if stripe_mode:
        q = q.filter(PaymentTransaction.stripe_mode == stripe_mode)
    txns = q.limit(limit).all()
    if not txns:
        return []

    user_ids = {t.payer_user_id for t in txns if t.payer_user_id} | {
        t.creator_user_id for t in txns if t.creator_user_id
    }
    space_ids = {t.space_id for t in txns if t.space_id}
    pathway_ids = {t.pathway_id for t in txns if t.pathway_id}

    user_names: dict[str, str | None] = (
        dict(db.query(UserModel.id, UserModel.name).filter(UserModel.id.in_(user_ids)).all())
        if user_ids else {}
    )
    space_names: dict[str, str] = (
        dict(db.query(Space.id, Space.name).filter(Space.id.in_(space_ids)).all())
        if space_ids else {}
    )
    pathway_titles: dict[str, str] = (
        dict(db.query(Pathway.id, Pathway.title).filter(Pathway.id.in_(pathway_ids)).all())
        if pathway_ids else {}
    )

    events: list[CommerceMovementEvent] = []
    for t in txns:
        label, kind = _movement_label_and_kind(t, user_names, space_names, pathway_titles)
        status_val = t.status.value if hasattr(t.status, "value") else str(t.status)
        events.append(CommerceMovementEvent(
            id=t.id,
            label=label,
            kind=kind,
            amount_cents=t.gross_amount_cents,
            currency=t.currency,
            status=status_val,
            occurred_at=t.created_at,
            stripe_mode=t.stripe_mode,
        ))
    return events


@router.get("/commerce/overview", response_model=AdminCommerceOverview)
def get_commerce_overview(
    period: str = "this_month",
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminCommerceOverview:
    """One-shot payload for the Commerce overview page.

    Returns:
        * revenue + growth for the current window
        * revenue + growth for the previous comparable window (unless
          ``period=all_time``, which returns ``previous=None``)
        * the 10 most recent payment events (period-agnostic —
          "what's happening lately", filtered by ``stripe_mode``)
        * ``test_mode_active`` — whether the platform is currently in
          Stripe test mode, so the UI can render a soft "viewing test
          data" banner without a second call

    ``stripe_mode`` defaults to whatever the platform is configured for
    (``settings.stripe_mode``), so a caretaker can't accidentally see
    mixed test + live totals. Callers may override for debugging.
    """
    from app.core.config import settings
    from app.core.periods import VALID_PERIODS, resolve_period

    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period {period!r}. Valid: {list(VALID_PERIODS)}.",
        )

    effective_mode = stripe_mode or settings.stripe_mode
    current_bounds, previous_bounds = resolve_period(period)  # type: ignore[arg-type]

    current_revenue = _compute_revenue_summary(
        db,
        starts_at=current_bounds.starts_at,
        ends_at=current_bounds.ends_at,
        stripe_mode=effective_mode,
    )
    current_growth = _compute_growth_summary(
        db,
        starts_at=current_bounds.starts_at,
        ends_at=current_bounds.ends_at,
    )
    current_window = CommerceWindow(
        bounds=PeriodBoundsOut(
            label=current_bounds.label,
            starts_at=current_bounds.starts_at,
            ends_at=current_bounds.ends_at,
        ),
        revenue=current_revenue,
        growth=current_growth,
    )

    previous_window: CommerceWindow | None = None
    if previous_bounds is not None:
        previous_window = CommerceWindow(
            bounds=PeriodBoundsOut(
                label=previous_bounds.label,
                starts_at=previous_bounds.starts_at,
                ends_at=previous_bounds.ends_at,
            ),
            revenue=_compute_revenue_summary(
                db,
                starts_at=previous_bounds.starts_at,
                ends_at=previous_bounds.ends_at,
                stripe_mode=effective_mode,
            ),
            growth=_compute_growth_summary(
                db,
                starts_at=previous_bounds.starts_at,
                ends_at=previous_bounds.ends_at,
            ),
        )

    recent = _compute_recent_movements(db, stripe_mode=effective_mode, limit=10)

    return AdminCommerceOverview(
        period=period,
        stripe_mode=effective_mode,
        test_mode_active=(settings.stripe_mode == "test"),
        current=current_window,
        previous=previous_window,
        recent_movements=recent,
    )


@router.get("/revenue/by-creator", response_model=list[AdminRevenueByCreatorRow])
def get_revenue_by_creator(
    stripe_mode: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminRevenueByCreatorRow]:
    """Per-creator revenue breakdown. Admin only. Pass ?stripe_mode=live for real revenue only."""
    from app.models.user import User as UserModel

    succeeded = PaymentTransactionStatus.succeeded

    def _mf(q):
        """Apply stripe_mode filter when requested."""
        if stripe_mode:
            q = q.filter(PaymentTransaction.stripe_mode == stripe_mode)
        return q

    # Member sales by creator_user_id (gross, FC fee, creator net)
    member_sales = (
        _mf(
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
        )
        .group_by(PaymentTransaction.creator_user_id)
        .all()
    )

    # Creator subscription payments by payer_user_id (the creator paid FC)
    sub_payments = (
        _mf(
            db.query(
                PaymentTransaction.payer_user_id,
                func.sum(PaymentTransaction.gross_amount_cents).label("sub_revenue"),
            )
            .filter(
                PaymentTransaction.status == succeeded,
                PaymentTransaction.transaction_type == PaymentTransactionType.creator_subscription_payment,
                PaymentTransaction.payer_user_id.isnot(None),
            )
        )
        .group_by(PaymentTransaction.payer_user_id)
        .all()
    )

    # Paid-out amounts by creator
    paid_rows = (
        _mf(
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
        )
        .group_by(PaymentTransaction.creator_user_id)
        .all()
    )

    # Pending payout by creator
    pending_rows = (
        _mf(
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
