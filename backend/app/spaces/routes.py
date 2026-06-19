import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.models.access_pass import AccessPass, AccessPassStatus

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.creator.schemas import AboutBlockResponse, BlockMediaInfo, StepBlockResponse
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    Enrollment,
    EntitlementStatus,
    Event,
    EventBooking,
    Pathway,
    PathwayAboutBlock,
    PathwayEntitlement,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceAccessRequest,
    SpaceInvitation,
    SpaceMembership,
    SpaceMemberNotificationPrefs,
    SpaceRole,
    SpaceMembershipStatus,
    SpaceResource,
    StepComment,
    StepProgress,
    StepResource,
)
from app.models.user import User
from app.spaces.schemas import (
    AccessRequestOut,
    CompleteStepRequest,
    CompleteStepResponse,
    ContinueResponse,
    EventDetail,
    EventSummary,
    InviteLookupResponse,
    NotificationPrefsResponse,
    NotificationPrefsUpdate,
    PathwayProgress,
    PathwaySummary,
    PathwayWithSteps,
    PaymentOptionScheduleSummary,
    PaymentOptionSummary,
    PublicSpaceCard,
    SaveNotesRequest,
    SaveNotesResponse,
    SectionWithSteps,
    SpaceAccessStatus,
    SpaceResponse,
    SpaceSummary,
    CollectiveResourceResponse,
    AggregatedResourcesResponse,
    PathwayResourceGroup,
    PathwayResourceItem,
    StepCommentAuthor,
    StepCommentCreate,
    StepCommentItem,
    StepDetail,
    StepResourceResponse,
    StepSummary,
    BookingResponse,
    SeriesBookingResponse,
    AccessPassOut,
)

from app.services.notification_service import trigger_event_booking_creator  # noqa: E402

router = APIRouter(prefix="/api/spaces", tags=["spaces"])
me_router = APIRouter(prefix="/api/me", tags=["me"])
public_router = APIRouter(prefix="/api/public", tags=["public"])


# ---------------------------------------------------------------------------
# Public (unauthenticated) discovery endpoint
# ---------------------------------------------------------------------------

@public_router.get("/spaces", response_model=list[PublicSpaceCard])
def list_public_spaces(db: Session = Depends(get_db)) -> list[PublicSpaceCard]:
    """Return all public active spaces with aggregated counts — no auth required."""
    spaces = (
        db.query(Space)
        .filter(Space.status == "active", Space.is_public.is_(True))
        .order_by(Space.created_at)
        .all()
    )
    if not spaces:
        return []

    space_ids = [s.id for s in spaces]

    pathway_counts: dict[str, int] = dict(
        db.query(Pathway.space_id, func.count(Pathway.id))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status != "archived",
        )
        .group_by(Pathway.space_id)
        .all()
    )

    # Minimum price among active paid pathways per space.
    # - Legacy pathways (pricing_mode='legacy'): use pathway.price_cents.
    # - Payment-options pathways (pricing_mode='payment_options'): use minimum
    #   effective price from PUBLISHED options only (draft/archived excluded).
    #   effective_price_cents = COALESCE(override_total_cents, calculated_total_cents)
    _paid_access_types = ('one_time', 'subscription')
    min_pathway_prices: dict[str, int] = {}

    # Legacy pathway prices
    legacy_rows = (
        db.query(Pathway.space_id, func.min(Pathway.price_cents))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.access_type.in_(_paid_access_types),
            Pathway.pricing_mode == "legacy",
            Pathway.price_cents.isnot(None),
            Pathway.price_cents > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in legacy_rows:
        if min_cents is not None:
            min_pathway_prices[space_id] = int(min_cents)

    # Payment-options pathway prices — derived from published options only
    from sqlalchemy import case as sa_case
    effective_price_expr = func.coalesce(
        PaymentOption.override_total_cents,
        PaymentOption.calculated_total_cents,
    )
    options_rows = (
        db.query(Pathway.space_id, func.min(effective_price_expr))
        .join(PaymentOption, PaymentOption.pathway_id == Pathway.id)
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.pricing_mode == "payment_options",
            PaymentOption.status == "published",
            effective_price_expr.isnot(None),
            effective_price_expr > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in options_rows:
        if min_cents is not None:
            existing = min_pathway_prices.get(space_id)
            min_pathway_prices[space_id] = int(min_cents) if existing is None else min(existing, int(min_cents))

    member_counts: dict[str, int] = dict(
        db.query(Pathway.space_id, func.count(func.distinct(Enrollment.user_id)))
        .join(Enrollment, Enrollment.pathway_id == Pathway.id)
        .filter(Pathway.space_id.in_(space_ids))
        .group_by(Pathway.space_id)
        .all()
    )

    upcoming_event_space_ids: set[str] = {
        r[0] for r in db.query(Event.space_id)
        .filter(
            Event.space_id.in_(space_ids),
            Event.is_published.is_(True),
            Event.starts_at >= datetime.utcnow(),
        )
        .distinct()
        .all()
    }

    creator_ids = [s.creator_id for s in spaces if s.creator_id]
    creator_names: dict[str, str | None] = {}
    if creator_ids:
        rows = db.query(User.id, User.name).filter(User.id.in_(creator_ids)).all()
        creator_names = {r.id: r.name for r in rows}

    return [
        PublicSpaceCard(
            id=s.id,
            slug=s.slug,
            name=s.name,
            tagline=s.tagline,
            description=s.description,
            cover_image_url=s.cover_image_url,
            is_public=s.is_public,
            pathway_count=pathway_counts.get(s.id, 0),
            member_count=member_counts.get(s.id, 0),
            creator_name=creator_names.get(s.creator_id) if s.creator_id else None,
            has_upcoming_event=s.id in upcoming_event_space_ids,
            themes=s.themes or [],
            pricing_type=s.pricing_type or 'free',
            pricing_amount_cents=s.pricing_amount_cents,
            pricing_currency=s.pricing_currency or 'AUD',
            pricing_note=s.pricing_note,
            has_paid_internal_content=s.has_paid_internal_content or False,
            included_access_summary=s.included_access_summary,
            paid_content_summary=s.paid_content_summary,
            derived_has_paid_internal_content=s.id in min_pathway_prices,
            min_paid_pathway_price_cents=min_pathway_prices.get(s.id),
        )
        for s in spaces
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _get_pathway_or_404(space_id: str, pathway_slug: str, db: Session) -> Pathway:
    pathway = (
        db.query(Pathway)
        .filter(Pathway.space_id == space_id, Pathway.slug == pathway_slug)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pathway not found.")
    return pathway


def _get_step_or_404(pathway_id: str, step_slug: str, db: Session) -> PathwayStep:
    step = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway_id, PathwayStep.slug == step_slug)
        .first()
    )
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found.")
    return step


def _completed_step_ids(user_id: str, step_ids: list[str], db: Session) -> set[str]:
    """Return the subset of step_ids the user has completed (completed_at IS NOT NULL)."""
    records = (
        db.query(StepProgress.step_id)
        .filter(
            StepProgress.user_id == user_id,
            StepProgress.step_id.in_(step_ids),
            StepProgress.completed_at.isnot(None),
        )
        .all()
    )
    return {r.step_id for r in records}


def _ensure_enrollment(user_id: str, pathway_id: str, db: Session) -> None:
    """Create an active enrollment if one does not already exist."""
    exists = (
        db.query(Enrollment.id)
        .filter(Enrollment.user_id == user_id, Enrollment.pathway_id == pathway_id)
        .first()
    )
    if not exists:
        db.add(Enrollment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            pathway_id=pathway_id,
            status="active",
        ))
        db.flush()


def _compute_pathway_access(user: "User | None", pathway: Pathway, space: Space, db: Session) -> bool:
    """
    Return True if user has access to this pathway; False otherwise.
    Accepts None for unauthenticated visitors — they never have access to paid/included pathways.
    """
    if user is None:
        p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
        access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
        if p_status in ("draft", "archived", "coming_soon"):
            return False
        return access_type == "free"
    if user.role in ("creator", "admin"):
        return True
    space_role = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    if space_role:
        return True
    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
    if p_status in ("draft", "archived", "coming_soon"):
        return False
    if access_type == "free":
        return True
    if access_type == "included":
        mem = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        return mem is not None
    # one_time or subscription — requires active PathwayEntitlement that hasn't expired
    now = datetime.utcnow()
    ent = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        )
        .first()
    )
    return ent is not None


def _check_pathway_access(
    user: User,
    pathway: Pathway,
    space: Space,
    db: Session,
) -> None:
    """
    Raise HTTP 403 if the user does not have access to this pathway.

    Access rules:
      - creator/admin role → always allowed
      - space creator/moderator membership → always allowed
      - draft/archived pathway → denied to all non-creators
      - coming_soon pathway → denied (About page is separate, not gated here)
      - free pathway (active) → allowed
      - included pathway (active) → allowed for space members
      - one_time/subscription pathway → requires active PathwayEntitlement row
    """
    # Platform admins and creator-role users always have access
    if user.role in ("creator", "admin"):
        return

    # Space creators and moderators always have access
    space_role = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    if space_role:
        return

    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")

    if p_status in ("draft", "archived"):
        raise HTTPException(status_code=403, detail="This pathway is not available.")
    if p_status == "coming_soon":
        raise HTTPException(status_code=403, detail="This pathway is coming soon.")

    if access_type == "free":
        return

    if access_type == "included":
        mem = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        if mem:
            return
        raise HTTPException(status_code=403, detail="This pathway is included with space membership.")

    # one_time / subscription — require an active entitlement that hasn't expired
    now = datetime.utcnow()
    entitlement = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        )
        .first()
    )
    if entitlement:
        return

    raise HTTPException(
        status_code=403,
        detail="Access to this pathway requires a purchase or manual grant.",
    )


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SpaceSummary])
def list_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Space]:
    return (
        db.query(Space)
        .filter(Space.status == "active")
        .order_by(Space.name)
        .all()
    )


@router.get("/{slug}", response_model=SpaceResponse)
def get_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SpaceResponse:
    space = (
        db.query(Space)
        .options(selectinload(Space.pathways))
        .filter(Space.slug == slug, Space.status == "active")
        .first()
    )
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    if not space.is_public and current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    learner_count = (
        db.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role == SpaceRole.learner,
        )
        .scalar()
    ) or 0
    resp = SpaceResponse.model_validate(space)
    return resp.model_copy(update={"learner_count": learner_count})


# ---------------------------------------------------------------------------
# Member access: join, request-access, my-access
# ---------------------------------------------------------------------------

@router.get("/{slug}/my-access", response_model=SpaceAccessStatus)
def get_my_access(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpaceAccessStatus:
    """Return the current user's access state for this Space."""
    space = _get_space_or_404(slug, db)

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.status == "active",
        )
        .first()
    )

    request = (
        db.query(SpaceAccessRequest)
        .filter(
            SpaceAccessRequest.space_id == space.id,
            SpaceAccessRequest.user_id == current_user.id,
            SpaceAccessRequest.status == "pending",
        )
        .first()
    )

    invite = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.email == current_user.email.lower(),
        )
        .first()
    )

    return SpaceAccessStatus(
        is_member=membership is not None,
        membership_role=(
            membership.role.value if membership and hasattr(membership.role, "value")
            else str(membership.role) if membership else None
        ),
        has_pending_request=request is not None,
        has_pending_invite=invite is not None,
    )


@router.post("/{slug}/join", status_code=201)
def join_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Join a public Space as a learner."""
    space = _get_space_or_404(slug, db)

    if not space.is_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This collective is private. Request access instead.")

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id)
        .first()
    )
    if existing:
        return {"joined": True, "already_member": True}

    db.add(SpaceMembership(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        space_id=space.id,
        role=SpaceRole.learner,
        status=SpaceMembershipStatus.active,
    ))
    db.commit()
    return {"joined": True, "already_member": False}


@router.post("/{slug}/request-access", status_code=201)
def request_access(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Submit an access request to a private Space."""
    space = _get_space_or_404(slug, db)

    if space.is_public:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This collective is public. Use the join endpoint instead.")

    existing_member = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id,
                SpaceMembership.status == "active")
        .first()
    )
    if existing_member:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You are already a member of this collective.")

    existing_request = (
        db.query(SpaceAccessRequest)
        .filter(SpaceAccessRequest.space_id == space.id, SpaceAccessRequest.user_id == current_user.id)
        .first()
    )
    if existing_request:
        if existing_request.status == "pending":
            return {"requested": True, "already_pending": True}
        # Allow re-requesting if previously declined
        existing_request.status = "pending"
        existing_request.updated_at = datetime.utcnow()
        db.commit()
        return {"requested": True, "already_pending": False}

    db.add(SpaceAccessRequest(
        id=str(uuid.uuid4()),
        space_id=space.id,
        user_id=current_user.id,
        status="pending",
    ))
    db.commit()
    return {"requested": True, "already_pending": False}


# ---------------------------------------------------------------------------
# Invite acceptance (token-based)
# ---------------------------------------------------------------------------

invites_router = APIRouter(prefix="/api/invites", tags=["invites"])


@invites_router.get("/{token}", response_model=InviteLookupResponse)
def get_invite_by_token(
    token: str,
    db: Session = Depends(get_db),
) -> InviteLookupResponse:
    """Look up an invite by token — public endpoint (no auth required)."""
    invite = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.token == token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or already used.")

    space = db.query(Space).filter(Space.id == invite.space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    return InviteLookupResponse(
        id=invite.id,
        space_id=invite.space_id,
        space_name=space.name,
        space_slug=space.slug,
        email=invite.email,
        name=invite.name,
        role=invite.role.value if hasattr(invite.role, "value") else str(invite.role),
    )


@invites_router.post("/{token}/accept", status_code=201)
def accept_invite(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Accept a space invite by token. Caller must be logged in."""
    invite = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.token == token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or already used.")

    if current_user.email.lower() != invite.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invite was sent to a different email address. Please log in with that account.",
        )

    space = db.query(Space).filter(Space.id == invite.space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id)
        .first()
    )
    if not existing:
        role_value = invite.role.value if hasattr(invite.role, "value") else str(invite.role)
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            space_id=space.id,
            role=role_value,
            status=SpaceMembershipStatus.active,
        ))

    # Delete the invite — consumed
    db.delete(invite)
    db.commit()
    return {"accepted": True, "space_slug": space.slug}


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@router.get("/{slug}/pathways", response_model=list[PathwaySummary])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> list[PathwaySummary]:
    space = _get_space_or_404(slug, db)
    is_creator_or_admin = current_user is not None and current_user.role in ("creator", "admin")
    is_space_manager = False
    if current_user is not None:
        space_role = (
            db.query(SpaceMembership.role)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.role.in_(["creator", "moderator"]),
                SpaceMembership.status == "active",
            )
            .first()
        )
        is_space_manager = bool(space_role)

    query = db.query(Pathway).filter(Pathway.space_id == space.id)
    if not (is_creator_or_admin or is_space_manager):
        # Anonymous visitors and regular members only see published pathways (active + coming_soon)
        query = query.filter(Pathway.status.in_(["active", "coming_soon"]))

    pathways = query.order_by(Pathway.position).all()

    pathway_ids = [p.id for p in pathways]
    step_counts: dict[str, int] = {}
    if pathway_ids:
        step_counts = dict(
            db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
            .filter(PathwayStep.pathway_id.in_(pathway_ids))
            .group_by(PathwayStep.pathway_id)
            .all()
        )

    result = []
    for p in pathways:
        has_access = _compute_pathway_access(current_user, p, space, db)
        result.append(PathwaySummary(
            id=p.id,
            slug=p.slug,
            title=p.title,
            description=p.description,
            cover_image_url=p.cover_image_url,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            position=p.position,
            access_type=p.access_type.value if hasattr(p.access_type, "value") else str(p.access_type or "free"),
            pricing_mode=getattr(p, "pricing_mode", "legacy") or "legacy",
            price_cents=p.price_cents,
            currency=p.currency,
            billing_interval=p.billing_interval,
            user_has_access=has_access,
            step_count=step_counts.get(p.id, 0),
        ))
    return result


@router.get("/{slug}/pathways-progress", response_model=list[PathwayProgress])
def list_pathways_progress(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PathwayProgress]:
    """All pathways for a space, each annotated with this user's completion stats."""
    space = _get_space_or_404(slug, db)
    pathways = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.position)
        .all()
    )
    pathway_ids = [p.id for p in pathways]
    if not pathway_ids:
        return []

    step_counts: dict[str, int] = dict(
        db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
        .filter(PathwayStep.pathway_id.in_(pathway_ids))
        .group_by(PathwayStep.pathway_id)
        .all()
    )

    completed_counts: dict[str, int] = dict(
        db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
        .join(StepProgress, StepProgress.step_id == PathwayStep.id)
        .filter(
            PathwayStep.pathway_id.in_(pathway_ids),
            StepProgress.user_id == current_user.id,
            StepProgress.completed_at.isnot(None),
        )
        .group_by(PathwayStep.pathway_id)
        .all()
    )

    return [
        PathwayProgress(
            id=p.id,
            slug=p.slug,
            title=p.title,
            description=p.description,
            cover_image_url=p.cover_image_url,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            position=p.position,
            step_count=step_counts.get(p.id, 0),
            completed_count=completed_counts.get(p.id, 0),
            access_type=p.access_type.value if hasattr(p.access_type, "value") else str(p.access_type),
            price_cents=p.price_cents,
            currency=p.currency,
            billing_interval=p.billing_interval,
        )
        for p in pathways
    ]


@router.get("/{slug}/events", response_model=list[EventSummary])
def list_events(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[EventSummary]:
    """All upcoming published events for a space, with per-user booking state."""
    space = _get_space_or_404(slug, db)

    # Determine if caller is a member (affects event visibility and booking access)
    is_member = False
    if current_user:
        membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
        is_member = bool(membership)

    # Non-members (and anon users) only see public events; members see all published
    # Cancelled events are excluded from all member-facing list views
    if not space.is_public and not is_member and current_user is None:
        # Space is private and caller is unauthenticated — still show public events
        events_q = db.query(Event).filter(
            Event.space_id == space.id,
            Event.is_published.is_(True),
            Event.is_public.is_(True),
            Event.status == "active",
            Event.starts_at >= datetime.utcnow(),
        )
    elif is_member:
        events_q = db.query(Event).filter(
            Event.space_id == space.id,
            Event.is_published.is_(True),
            Event.status == "active",
            Event.starts_at >= datetime.utcnow(),
        )
    else:
        # Logged-in non-member: only public events
        events_q = db.query(Event).filter(
            Event.space_id == space.id,
            Event.is_published.is_(True),
            Event.is_public.is_(True),
            Event.status == "active",
            Event.starts_at >= datetime.utcnow(),
        )

    events = events_q.order_by(Event.starts_at).all()

    now = datetime.utcnow()

    # Bulk-fetch confirmed booking counts for all events in one query
    event_ids = [e.id for e in events]
    booked_counts: dict[str, int] = {}
    if event_ids:
        rows = (
            db.query(EventBooking.event_id, func.count(EventBooking.id))
            .filter(
                EventBooking.event_id.in_(event_ids),
                EventBooking.status == BookingStatus.confirmed,
            )
            .group_by(EventBooking.event_id)
            .all()
        )
        booked_counts = dict(rows)

    # Fetch current user's bookings if logged in
    user_bookings: dict[str, str] = {}  # event_id -> status
    if current_user:
        user_rows = (
            db.query(EventBooking.event_id, EventBooking.status)
            .filter(
                EventBooking.event_id.in_(event_ids),
                EventBooking.user_id == current_user.id,
            )
            .all()
        )
        user_bookings = {r.event_id: r.status.value for r in user_rows}

    # Bulk-check pathway entitlements for the current user
    # Collect unique required pathway IDs from pathway_required events
    required_pathway_ids = {
        e.booking_required_pathway_id
        for e in events
        if getattr(e, 'booking_access_type', 'all_members') == 'pathway_required'
        and e.booking_required_pathway_id
    }
    user_pathway_access: set[str] = set()
    if current_user and required_pathway_ids:
        ent_rows = (
            db.query(PathwayEntitlement.pathway_id)
            .filter(
                PathwayEntitlement.user_id == current_user.id,
                PathwayEntitlement.pathway_id.in_(required_pathway_ids),
                PathwayEntitlement.status == EntitlementStatus.active,
            )
            .all()
        )
        user_pathway_access = {r.pathway_id for r in ent_rows}
        # Creators/moderators always have pathway access
        if membership and getattr(membership, 'role', None) in (SpaceRole.creator, SpaceRole.moderator):
            user_pathway_access = required_pathway_ids

    # Bulk-fetch active AccessPass remaining credits per pathway for the current user
    # Used to populate pass_credits_remaining on each event (member-facing credit display)
    user_pass_credits: dict[str, int | None] = {}  # pathway_id → remaining credits (None = unlimited)
    if current_user and required_pathway_ids:
        pass_rows = (
            db.query(AccessPass)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.eligible_pathway_id.in_(required_pathway_ids),
                or_(
                    AccessPass.valid_until.is_(None),
                    AccessPass.valid_until > now,
                ),
            )
            .all()
        )
        for ap in pass_rows:
            if ap.eligible_pathway_id:
                user_pass_credits[ap.eligible_pathway_id] = ap.remaining_credits

    result = []
    for e in events:
        booked = booked_counts.get(e.id, 0)
        spots_remaining = (e.capacity - booked) if e.capacity is not None else None
        my_status = user_bookings.get(e.id)  # 'confirmed' | 'cancelled' | None
        booking_closed = bool(e.booking_closes_at and e.booking_closes_at <= now)
        is_full = e.capacity is not None and booked >= e.capacity
        event_access_type = getattr(e, 'booking_access_type', 'all_members') or 'all_members'
        required_pid = getattr(e, 'booking_required_pathway_id', None)
        has_pathway_access = (
            event_access_type == 'all_members'
            or required_pid is None
            or required_pid in user_pathway_access
        )
        # Credits remaining on the user's active AccessPass for this pathway (None = no pass or unlimited)
        pass_credits_remaining: int | None = (
            user_pass_credits.get(required_pid) if required_pid else None
        )
        # If user has an AccessPass with zero credits remaining, they cannot book
        credits_exhausted = (
            pass_credits_remaining is not None and pass_credits_remaining <= 0
        )
        can_book = (
            e.requires_booking
            and is_member
            and has_pathway_access
            and not credits_exhausted
            and my_status != "confirmed"
            and not booking_closed
            and not is_full
        )
        can_cancel = (
            e.requires_booking
            and is_member
            and my_status == "confirmed"
        )
        result.append(EventSummary(
            id=e.id,
            title=e.title,
            description=e.description,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            location_type=e.location_type.value if hasattr(e.location_type, "value") else str(e.location_type),
            requires_booking=e.requires_booking,
            capacity=e.capacity,
            booked_count=booked,
            spots_remaining=spots_remaining,
            booking_closes_at=e.booking_closes_at,
            booking_note=e.booking_note,
            my_booking_status=my_status,
            can_book=can_book,
            can_cancel_booking=can_cancel,
            recurrence_series_id=e.recurrence_series_id,
            recurrence_label=e.recurrence_label,
            recurrence_index=e.recurrence_index,
            recurrence_total=e.recurrence_total,
            is_public=e.is_public,
            thumbnail_url=e.thumbnail_url,
            status=e.status if e.status else "active",
            booking_access_type=event_access_type,
            booking_required_pathway_id=required_pid,
            user_has_pathway_access=has_pathway_access,
            pass_credits_remaining=pass_credits_remaining,
        ))
    return result


@router.post("/{slug}/events/{event_id}/book", response_model=BookingResponse)
def book_event(
    slug: str,
    event_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    """Book a spot at a gathering. Members only. Enforces capacity and cutoff time."""
    space = _get_space_or_404(slug, db)

    # Must be an active member
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member to book.")

    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id, Event.is_published.is_(True))
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")
    if not event.requires_booking:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering does not require booking.")
    if getattr(event, 'status', 'active') == 'cancelled':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering has been cancelled.")

    # Check pathway access restriction (existing logic — unchanged)
    event_access_type = getattr(event, 'booking_access_type', 'all_members') or 'all_members'
    required_pid = getattr(event, 'booking_required_pathway_id', None)
    is_privileged = getattr(membership, 'role', None) in (SpaceRole.creator, SpaceRole.moderator)

    if event_access_type == 'pathway_required' and required_pid:
        entitlement = (
            db.query(PathwayEntitlement)
            .filter(
                PathwayEntitlement.user_id == current_user.id,
                PathwayEntitlement.pathway_id == required_pid,
                PathwayEntitlement.status == EntitlementStatus.active,
            )
            .first()
        )
        if not entitlement and not is_privileged:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must have access to the required pathway to book this session.",
            )

    now = datetime.utcnow()

    # --- AccessPass credit check (Phase B) ---
    # Layered on top of the existing pathway access check.
    # If the user has an AccessPass for this pathway: hard-enforce total credits and weekly cap.
    # If no AccessPass exists (legacy/manual PathwayEntitlement): allow without credit tracking.
    # Creators and moderators bypass all credit checks.
    access_pass_to_charge: AccessPass | None = None

    if not is_privileged and event_access_type == 'pathway_required' and required_pid:
        candidate_pass = (
            db.query(AccessPass)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.eligible_pathway_id == required_pid,
                AccessPass.status == AccessPassStatus.active,
                or_(
                    AccessPass.valid_until.is_(None),
                    AccessPass.valid_until > now,
                ),
            )
            .order_by(AccessPass.created_at.desc())
            .first()
        )

        if candidate_pass is not None:
            # Hard enforce: total credits exhausted
            if (
                candidate_pass.total_credits is not None
                and candidate_pass.used_credits >= candidate_pass.total_credits
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You have no remaining sessions on your current pass.",
                )

            # Hard enforce: weekly cap
            # Uses the EVENT's starts_at week, not the booking creation time.
            # This allows a member to book sessions in multiple future weeks on
            # the same day, while still preventing two sessions in the same event week.
            if candidate_pass.credits_per_week is not None:
                # Determine the Monday of the week the target event falls in
                event_weekday = event.starts_at.weekday()  # 0=Mon … 6=Sun
                event_week_start = (event.starts_at - timedelta(days=event_weekday)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                event_week_end = event_week_start + timedelta(days=7)
                weekly_used = (
                    db.query(func.count(EventBooking.id))
                    .join(Event, EventBooking.event_id == Event.id)
                    .filter(
                        EventBooking.access_pass_id == candidate_pass.id,
                        EventBooking.status == BookingStatus.confirmed,
                        Event.starts_at >= event_week_start,
                        Event.starts_at < event_week_end,
                    )
                    .scalar()
                ) or 0
                if weekly_used >= candidate_pass.credits_per_week:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"You have reached your weekly limit of "
                            f"{candidate_pass.credits_per_week} session(s)."
                        ),
                    )

            access_pass_to_charge = candidate_pass
        # else: no AccessPass found → legacy/manual path, booking proceeds without credit tracking

    if event.starts_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering has already started.")
    if event.booking_closes_at and event.booking_closes_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking has closed for this gathering.")

    # Check capacity
    if event.capacity is not None:
        confirmed = (
            db.query(func.count(EventBooking.id))
            .filter(EventBooking.event_id == event.id, EventBooking.status == BookingStatus.confirmed)
            .scalar()
        )
        if confirmed >= event.capacity:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering is fully booked.")

    # Reactivate cancelled booking or create new
    existing = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == event.id, EventBooking.user_id == current_user.id)
        .first()
    )
    if existing:
        if existing.status == BookingStatus.confirmed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already booked.")
        existing.status = BookingStatus.confirmed
        existing.booked_at = now
        existing.cancelled_at = None
        existing.access_pass_id = access_pass_to_charge.id if access_pass_to_charge else None
        existing.credits_used = 1 if access_pass_to_charge else 0
        if access_pass_to_charge:
            access_pass_to_charge.used_credits += 1
        db.commit()
        db.refresh(existing)
        background_tasks.add_task(trigger_event_booking_creator, event.id, current_user.id)
        return BookingResponse(status="confirmed", booking_id=existing.id)

    booking = EventBooking(
        id=str(uuid.uuid4()),
        event_id=event.id,
        user_id=current_user.id,
        status=BookingStatus.confirmed,
        booked_at=now,
        access_pass_id=access_pass_to_charge.id if access_pass_to_charge else None,
        credits_used=1 if access_pass_to_charge else 0,
    )
    db.add(booking)
    if access_pass_to_charge:
        access_pass_to_charge.used_credits += 1
    db.commit()
    db.refresh(booking)
    background_tasks.add_task(trigger_event_booking_creator, event.id, current_user.id)
    return BookingResponse(status="confirmed", booking_id=booking.id)


@router.post("/{slug}/events/{event_id}/cancel-booking", response_model=BookingResponse)
def cancel_booking(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    """Cancel the current user's booking for a gathering."""
    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")

    booking = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event.id,
            EventBooking.user_id == current_user.id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active booking found.")

    now = datetime.utcnow()
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = now

    # Credit restoration: restore if cancelling more than 24h before gathering start
    if booking.access_pass_id and booking.credits_used > 0:
        access_pass = db.query(AccessPass).filter(AccessPass.id == booking.access_pass_id).first()
        if access_pass:
            hours_until = (event.starts_at - now).total_seconds() / 3600
            if hours_until > 24:
                access_pass.used_credits = max(0, access_pass.used_credits - booking.credits_used)

    db.commit()
    return BookingResponse(status="cancelled", booking_id=booking.id)


@router.get("/{slug}/my-passes", response_model=list[AccessPassOut])
def get_my_passes(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """Return the current user's active AccessPasses for this space."""
    space = _get_space_or_404(slug, db)
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member.")

    now = datetime.utcnow()
    passes = (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == current_user.id,
            AccessPass.space_id == space.id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .order_by(AccessPass.created_at.desc())
        .all()
    )

    from app.models.payment_option import PaymentOption as _PO
    results = []
    for ap in passes:
        opt_name = None
        if ap.payment_option_id:
            opt = db.query(_PO).filter(_PO.id == ap.payment_option_id).first()
            if opt:
                opt_name = opt.name
        results.append(AccessPassOut(
            id=ap.id,
            pass_type=ap.pass_type.value if hasattr(ap.pass_type, "value") else str(ap.pass_type),
            status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
            valid_from=ap.valid_from,
            valid_until=ap.valid_until,
            total_credits=ap.total_credits,
            used_credits=ap.used_credits,
            remaining_credits=ap.remaining_credits,
            credits_per_week=ap.credits_per_week,
            eligible_pathway_id=ap.eligible_pathway_id,
            option_name=opt_name,
            pathway_title=None,
            created_at=ap.created_at,
        ))
    return results


@router.get("/{slug}/events/{event_id}", response_model=EventDetail)
def get_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    """Return a single published event by ID within a space, with booking state."""
    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(
            Event.id == event_id,
            Event.space_id == space.id,
            Event.is_published.is_(True),
        )
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    # Non-members can only see public events
    is_member = False
    if current_user:
        is_member = bool(
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
    if not is_member and not event.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    now = datetime.utcnow()
    is_past = bool(event.ends_at and event.ends_at < now) or (not event.ends_at and event.starts_at < now)

    booked_count = 0
    my_booking_status = None
    if event.requires_booking:
        booked_count = (
            db.query(func.count(EventBooking.id))
            .filter(EventBooking.event_id == event.id, EventBooking.status == BookingStatus.confirmed)
            .scalar()
        ) or 0
        if current_user:
            my_row = (
                db.query(EventBooking)
                .filter(EventBooking.event_id == event.id, EventBooking.user_id == current_user.id)
                .first()
            )
            if my_row:
                my_booking_status = my_row.status.value if hasattr(my_row.status, "value") else my_row.status

    spots_remaining = None
    if event.capacity is not None:
        spots_remaining = max(0, event.capacity - booked_count)

    event_status = getattr(event, 'status', 'active') or 'active'
    is_cancelled = event_status == 'cancelled'

    # Pathway access restriction
    event_access_type = getattr(event, 'booking_access_type', 'all_members') or 'all_members'
    required_pid = getattr(event, 'booking_required_pathway_id', None)
    user_has_pathway_access = True
    if event_access_type == 'pathway_required' and required_pid and current_user:
        # Creators/moderators always have access
        if is_member and (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        ):
            user_has_pathway_access = True
        else:
            ent = (
                db.query(PathwayEntitlement)
                .filter(
                    PathwayEntitlement.user_id == current_user.id,
                    PathwayEntitlement.pathway_id == required_pid,
                    PathwayEntitlement.status == EntitlementStatus.active,
                )
                .first()
            )
            user_has_pathway_access = bool(ent)

    booking_open = (
        event.requires_booking
        and not is_past
        and not is_cancelled
        and is_member
        and user_has_pathway_access
        and (event.booking_closes_at is None or event.booking_closes_at > now)
    )
    can_book = booking_open and my_booking_status != "confirmed" and (spots_remaining is None or spots_remaining > 0)
    can_cancel_booking = bool(not is_past and not is_cancelled and my_booking_status == "confirmed")

    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "location_type": event.location_type.value if hasattr(event.location_type, "value") else str(event.location_type),
        "location_url": event.location_url if is_member else None,
        "recording_url": event.recording_url if is_member else None,
        "requires_booking": event.requires_booking,
        "capacity": event.capacity,
        "booked_count": booked_count,
        "spots_remaining": spots_remaining,
        "booking_closes_at": event.booking_closes_at,
        "booking_note": event.booking_note,
        "my_booking_status": my_booking_status,
        "can_book": can_book,
        "can_cancel_booking": can_cancel_booking,
        "recurrence_series_id": event.recurrence_series_id,
        "recurrence_label": event.recurrence_label,
        "recurrence_index": event.recurrence_index,
        "recurrence_total": event.recurrence_total,
        "is_public": event.is_public,
        "thumbnail_url": event.thumbnail_url,
        "status": event_status,
        "booking_access_type": event_access_type,
        "booking_required_pathway_id": required_pid,
        "user_has_pathway_access": user_has_pathway_access,
    }


@router.post("/{slug}/events/series/{series_id}/book", response_model=SeriesBookingResponse)
def book_series(
    slug: str,
    series_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeriesBookingResponse:
    """Book all future bookable sessions in a recurrence series. Skips full/closed/already-booked."""
    space = _get_space_or_404(slug, db)
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member to book.")

    now = datetime.utcnow()
    events = (
        db.query(Event)
        .filter(
            Event.space_id == space.id,
            Event.recurrence_series_id == series_id,
            Event.is_published.is_(True),
            Event.requires_booking.is_(True),
            Event.status == "active",
            Event.starts_at > now,
        )
        .order_by(Event.starts_at)
        .all()
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No upcoming bookable sessions in this series.")

    event_ids = [e.id for e in events]
    confirmed_counts: dict[str, int] = dict(
        db.query(EventBooking.event_id, func.count(EventBooking.id))
        .filter(EventBooking.event_id.in_(event_ids), EventBooking.status == BookingStatus.confirmed)
        .group_by(EventBooking.event_id)
        .all()
    )
    existing_bookings: dict[str, "EventBooking"] = {
        b.event_id: b
        for b in db.query(EventBooking).filter(
            EventBooking.event_id.in_(event_ids),
            EventBooking.user_id == current_user.id,
        ).all()
    }

    booked = 0
    already_booked = 0
    skipped_full = 0
    skipped_closed = 0

    for e in events:
        existing = existing_bookings.get(e.id)
        if existing and existing.status == BookingStatus.confirmed:
            already_booked += 1
            continue
        if e.booking_closes_at and e.booking_closes_at <= now:
            skipped_closed += 1
            continue
        confirmed = confirmed_counts.get(e.id, 0)
        if e.capacity is not None and confirmed >= e.capacity:
            skipped_full += 1
            continue

        if existing:
            existing.status = BookingStatus.confirmed
            existing.booked_at = now
            existing.cancelled_at = None
        else:
            db.add(EventBooking(
                id=str(uuid.uuid4()),
                event_id=e.id,
                user_id=current_user.id,
                status=BookingStatus.confirmed,
                booked_at=now,
            ))
        booked += 1

    db.commit()
    return SeriesBookingResponse(
        booked=booked,
        already_booked=already_booked,
        skipped_full=skipped_full,
        skipped_closed=skipped_closed,
        total_in_series=len(events),
    )


@router.get("/{slug}/events/{event_id}/calendar.ics")
def download_ics(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Download an iCalendar (.ics) file for a gathering. Available for public events or members."""
    from fastapi.responses import Response

    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id, Event.is_published.is_(True))
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    is_member = False
    if current_user:
        is_member = bool(
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
    if not is_member and not event.is_public:
        raise HTTPException(status_code=404, detail="Event not found.")
    if getattr(event, 'status', 'active') == 'cancelled':
        raise HTTPException(status_code=410, detail="This event has been cancelled.")

    def fmt_ics_dt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    starts = fmt_ics_dt(event.starts_at)
    if event.ends_at:
        ends = fmt_ics_dt(event.ends_at)
    else:
        from datetime import timedelta
        ends = fmt_ics_dt(event.starts_at + timedelta(hours=1))

    location = event.location_url or ""
    description = (event.description or "").replace("\n", "\\n")
    event_url = f"https://fresh.community/spaces/{slug}/events/{event.id}"
    uid = f"{event.id}@fresh.community"

    ics = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Fresh Collective//Gatherings//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{starts}",
        f"DTEND:{ends}",
        f"SUMMARY:{event.title}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        f"URL:{event_url}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])

    safe_title = "".join(c for c in event.title if c.isalnum() or c in " -_").strip().replace(" ", "-")
    filename = f"{safe_title or 'gathering'}.ics"
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Space Resources (member-facing — members only, published resources only)
# ---------------------------------------------------------------------------

@router.get("/{slug}/resources", response_model=AggregatedResourcesResponse)
def list_space_resources(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    space = _get_space_or_404(slug, db)
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if not membership and current_user.role not in ("admin", "creator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Members only.")

    # -- General standalone resources (scope=general, published) --------------
    standalone_orm = (
        db.query(SpaceResource)
        .filter(
            SpaceResource.space_id == space.id,
            SpaceResource.status == "published",
            SpaceResource.scope == "general",
        )
        .order_by(SpaceResource.sort_order, SpaceResource.created_at)
        .all()
    )
    standalone = [CollectiveResourceResponse.model_validate(r) for r in standalone_orm]

    # -- Pathway resource groups (accessible active pathways) -----------------
    pathways = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id, Pathway.status == "active")
        .order_by(Pathway.position)
        .all()
    )

    # Pre-fetch pathway-scoped SpaceResources grouped by pathway_id
    pathway_ids = [p.id for p in pathways]
    scoped_resources_orm = (
        db.query(SpaceResource)
        .filter(
            SpaceResource.space_id == space.id,
            SpaceResource.scope == "pathway",
            SpaceResource.status == "published",
            SpaceResource.pathway_id.in_(pathway_ids),
        )
        .order_by(SpaceResource.sort_order, SpaceResource.created_at)
        .all()
    ) if pathway_ids else []
    scoped_by_pathway: dict[str, list[SpaceResource]] = {}
    for sr in scoped_resources_orm:
        if sr.pathway_id:
            scoped_by_pathway.setdefault(sr.pathway_id, []).append(sr)

    pathway_groups: list[PathwayResourceGroup] = []
    for pathway in pathways:
        if not _compute_pathway_access(current_user, pathway, space, db):
            continue

        access_type = (
            pathway.access_type.value
            if hasattr(pathway.access_type, "value")
            else str(pathway.access_type or "free")
        )
        access_label = (
            "Free" if access_type == "free"
            else "Included" if access_type == "included"
            else "Purchased"
        )

        items: list[PathwayResourceItem] = []

        # 1. Pathway-scoped SpaceResource records
        for r in scoped_by_pathway.get(pathway.id, []):
            items.append(PathwayResourceItem(
                id=r.id,
                title=r.title,
                description=r.description,
                resource_type=r.resource_type,
                url=r.url,
                file_name=r.file_name,
                file_size=r.file_size,
                is_downloadable=bool(r.file_name),
                source="pathway_resource",
            ))

        # 2. StepResource records and content_url from pathway steps
        steps = (
            db.query(PathwayStep)
            .filter(PathwayStep.pathway_id == pathway.id)
            .order_by(PathwayStep.position)
            .all()
        )
        step_ids = [s.id for s in steps]
        step_map = {s.id: s for s in steps}

        if step_ids:
            step_resources = (
                db.query(StepResource)
                .filter(StepResource.step_id.in_(step_ids))
                .order_by(StepResource.position)
                .all()
            )
            for sr in step_resources:
                if sr.step_id not in step_map:
                    continue
                items.append(PathwayResourceItem(
                    id=sr.id,
                    title=sr.title,
                    description=sr.description,
                    resource_type=sr.resource_type,
                    url=sr.url,
                    file_name=sr.file_name,
                    file_size=sr.file_size,
                    mime_type=sr.mime_type,
                    is_downloadable=sr.is_downloadable,
                    step_id=sr.step_id,
                    step_title=step_map[sr.step_id].title,
                    source="pathway_step",
                ))

            # Include content_url for video/audio steps as a resource item.
            # content_url is the step's primary media (not supplementary),
            # but it IS a link/file members should be able to access from
            # the Resources page.
            for step in steps:
                if step.content_url:
                    ct = (
                        step.content_type.value
                        if hasattr(step.content_type, "value")
                        else str(step.content_type or "text")
                    )
                    if ct in ("video", "audio"):
                        items.append(PathwayResourceItem(
                            id=f"step_content_{step.id}",
                            title=step.title,
                            description=None,
                            resource_type=ct,
                            url=step.content_url,
                            is_downloadable=False,
                            step_id=step.id,
                            step_title=step.title,
                            source="pathway_step_content",
                        ))

        if items:
            pathway_groups.append(PathwayResourceGroup(
                pathway_id=pathway.id,
                pathway_title=pathway.title,
                pathway_slug=pathway.slug,
                access_label=access_label,
                resources=items,
            ))

    return AggregatedResourcesResponse(
        standalone_resources=standalone,
        pathway_resource_groups=pathway_groups,
    )


@router.get("/{slug}/pathways/{pathway_slug}", response_model=PathwaySummary)
def get_pathway(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Pathway:
    space = _get_space_or_404(slug, db)
    return _get_pathway_or_404(space.id, pathway_slug, db)


@router.get("/{slug}/pathways/{pathway_slug}/overview", response_model=PathwayWithSteps)
def get_pathway_overview(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> PathwayWithSteps:
    """Pathway detail with ordered steps and this user's completion state."""
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db) if current_user else set()

    step_summaries = [
        StepSummary(
            id=s.id,
            slug=s.slug,
            title=s.title,
            content_type=s.content_type.value if hasattr(s.content_type, "value") else str(s.content_type),
            estimated_minutes=s.estimated_minutes,
            is_required=s.is_required,
            position=s.position,
            is_completed=s.id in completed,
        )
        for s in steps
    ]

    # Build section groupings (only if pathway has sections defined)
    db_sections = (
        db.query(PathwaySection)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position)
        .all()
    )
    summary_by_id = {s.id: s for s in step_summaries}
    sections = []
    for sec in db_sections:
        sec_steps = (
            db.query(PathwayStep)
            .filter(PathwayStep.section_id == sec.id)
            .order_by(PathwayStep.section_position.nulls_last(), PathwayStep.position)
            .all()
        )
        sections.append(SectionWithSteps(
            id=sec.id,
            title=sec.title,
            position=sec.position,
            steps=[summary_by_id[s.id] for s in sec_steps if s.id in summary_by_id],
        ))

    user_has_access = _compute_pathway_access(current_user, pathway, space, db)

    published_options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.pathway_id == pathway.id,
            PaymentOption.status == "published",
        )
        .order_by(PaymentOption.position)
        .all()
    )

    # Fetch published schedules for each option in one query
    opt_ids = [o.id for o in published_options]
    schedules_by_opt: dict[str, list[PaymentOptionSchedule]] = {oid: [] for oid in opt_ids}
    if opt_ids:
        pub_schedules = (
            db.query(PaymentOptionSchedule)
            .filter(
                PaymentOptionSchedule.payment_option_id.in_(opt_ids),
                PaymentOptionSchedule.status == "published",
            )
            .order_by(PaymentOptionSchedule.position)
            .all()
        )
        for s in pub_schedules:
            schedules_by_opt[s.payment_option_id].append(s)

    option_summaries = [
        PaymentOptionSummary(
            id=opt.id,
            name=opt.name,
            description=opt.description,
            payment_type=opt.payment_type.value if hasattr(opt.payment_type, "value") else str(opt.payment_type),
            status=opt.status.value if hasattr(opt.status, "value") else str(opt.status),
            term_start_date=opt.term_start_date,
            term_end_date=opt.term_end_date,
            sessions_per_week=opt.sessions_per_week,
            total_sessions=opt.total_sessions,
            price_per_session_cents=opt.price_per_session_cents,
            calculated_total_cents=opt.calculated_total_cents,
            override_total_cents=opt.override_total_cents,
            effective_price_cents=opt.effective_price_cents,
            currency=opt.currency,
            buyer_note=opt.buyer_note,
            position=opt.position,
            schedules=[
                PaymentOptionScheduleSummary(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    schedule_type=s.schedule_type,
                    status=s.status,
                    total_amount_cents=s.total_amount_cents,
                    installment_amount_cents=s.installment_amount_cents,
                    installment_count=s.installment_count,
                    interval=s.interval,
                    currency=s.currency,
                    buyer_note=s.buyer_note,
                    position=s.position,
                )
                for s in schedules_by_opt.get(opt.id, [])
            ],
        )
        for opt in published_options
    ]

    return PathwayWithSteps(
        id=pathway.id,
        slug=pathway.slug,
        title=pathway.title,
        description=pathway.description,
        cover_image_url=pathway.cover_image_url,
        status=pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        step_count=len(steps),
        completed_count=len(completed),
        steps=step_summaries,
        sections=sections,
        access_type=pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type),
        pricing_mode=getattr(pathway, "pricing_mode", "legacy") or "legacy",
        price_cents=pathway.price_cents,
        currency=pathway.currency,
        billing_interval=pathway.billing_interval,
        user_has_access=user_has_access,
        payment_options=option_summaries,
    )


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@router.get("/{slug}/pathways/{pathway_slug}/steps", response_model=list[StepSummary])
def list_steps(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepSummary]:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db)

    return [
        StepSummary(
            id=s.id,
            slug=s.slug,
            title=s.title,
            content_type=s.content_type.value if hasattr(s.content_type, "value") else str(s.content_type),
            estimated_minutes=s.estimated_minutes,
            is_required=s.is_required,
            position=s.position,
            is_completed=s.id in completed,
        )
        for s in steps
    ]


@router.get("/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepDetail)
def get_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StepDetail:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    return StepDetail(
        id=step.id,
        slug=step.slug,
        title=step.title,
        content_type=step.content_type.value if hasattr(step.content_type, "value") else str(step.content_type),
        content_body=step.content_body,
        content_url=step.content_url,
        estimated_minutes=step.estimated_minutes,
        is_required=step.is_required,
        position=step.position,
        is_completed=progress is not None and progress.completed_at is not None,
        reflection_text=progress.reflection_text if progress else None,
    )


@router.post(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/complete",
    response_model=CompleteStepResponse,
)
def complete_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: CompleteStepRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompleteStepResponse:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    _ensure_enrollment(current_user.id, pathway.id, db)

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    if progress:
        progress.completed_at = datetime.utcnow()
        if body.reflection_text is not None:
            progress.reflection_text = body.reflection_text
    else:
        db.add(StepProgress(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            step_id=step.id,
            completed_at=datetime.utcnow(),
            reflection_text=body.reflection_text,
        ))

    db.commit()
    return CompleteStepResponse(is_completed=True)


@router.patch(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/notes",
    response_model=SaveNotesResponse,
)
def save_notes(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: SaveNotesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SaveNotesResponse:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    if progress:
        progress.reflection_text = body.reflection_text
    else:
        # Create a draft progress record (completed_at stays NULL)
        db.add(StepProgress(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            step_id=step.id,
            completed_at=None,
            reflection_text=body.reflection_text,
        ))

    db.commit()
    return SaveNotesResponse(saved=True)


@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=list[StepResourceResponse],
)
def list_step_resources(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepResource]:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)
    return (
        db.query(StepResource)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position)
        .all()
    )


@router.get(
    "/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_pathway_about_blocks(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> list[PathwayAboutBlock]:
    """Return about-page blocks for a pathway.

    Public — locked and anonymous visitors can view the About page as a preview/sales page.
    """
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    return (
        db.query(PathwayAboutBlock)
        .options(selectinload(PathwayAboutBlock.media_asset))
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=list[StepBlockResponse],
)
def list_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PathwayStepBlock]:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)
    return (
        db.query(PathwayStepBlock)
        .options(selectinload(PathwayStepBlock.media_asset))
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )


# ---------------------------------------------------------------------------
# Me — continue journey
# ---------------------------------------------------------------------------

@me_router.get("/continue", response_model=ContinueResponse | None)
def get_continue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContinueResponse | None:
    """Return the user's most relevant next step, defaulting to REAL Journey."""
    # Always anchor to REAL Journey as the primary pathway
    pathway = (
        db.query(Pathway)
        .join(Space)
        .filter(Space.slug == "the-natural-leader-hub", Pathway.slug == "real-journey")
        .first()
    )
    if not pathway:
        return None

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )
    if not steps:
        return None

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db)
    all_complete = len(completed) >= len(steps)

    next_step = next((s for s in steps if s.id not in completed), steps[-1])

    return ContinueResponse(
        space_slug="the-natural-leader-hub",
        pathway_slug=pathway.slug,
        pathway_title=pathway.title,
        step_slug=next_step.slug,
        step_title=next_step.title,
        all_complete=all_complete,
    )


# ---------------------------------------------------------------------------
# Step Comments — Questions & discussion
# ---------------------------------------------------------------------------

@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/comments",
    response_model=list[StepCommentItem],
)
def list_step_comments(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepCommentItem]:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    comments = (
        db.query(StepComment)
        .filter(StepComment.step_id == step.id, StepComment.is_visible.is_(True))
        .order_by(StepComment.created_at.asc())
        .all()
    )

    # Batch-load authors
    from app.models.user import User as UserModel
    author_ids = list({c.author_id for c in comments})
    authors = {
        u.id: u
        for u in db.query(UserModel).filter(UserModel.id.in_(author_ids)).all()
    }

    return [
        StepCommentItem(
            id=c.id,
            body=c.body,
            author=StepCommentAuthor(
                id=c.author_id,
                name=authors[c.author_id].name if c.author_id in authors else None,
                email=authors[c.author_id].email if c.author_id in authors else "",
            ),
            created_at=c.created_at,
        )
        for c in comments
    ]


@router.post(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/comments",
    response_model=StepCommentItem,
    status_code=201,
)
def create_step_comment(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StepCommentItem:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    comment = StepComment(
        id=str(uuid.uuid4()),
        step_id=step.id,
        author_id=current_user.id,
        body=body.body,
        is_visible=True,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return StepCommentItem(
        id=comment.id,
        body=comment.body,
        author=StepCommentAuthor(
            id=current_user.id,
            name=current_user.name,
            email=current_user.email,
        ),
        created_at=comment.created_at,
    )

# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

_NOTIF_DEFAULTS = dict(
    weekly_digest_email=True,
    daily_digest_email=False,
    admin_broadcast_email=True,
    gathering_reminder_email=True,
    new_post_email=False,
    comment_reply_email=True,
    pathway_comment_email=True,
    new_pathway_email=True,
    push_enabled=False,
    push_gathering_reminders=False,
    push_replies=False,
    push_announcements=False,
)


def _prefs_response(space: Space, prefs: "SpaceMemberNotificationPrefs | None") -> NotificationPrefsResponse:
    if prefs is None:
        return NotificationPrefsResponse(
            space_id=space.id,
            space_slug=space.slug,
            space_name=space.name,
            **_NOTIF_DEFAULTS,  # type: ignore[arg-type]
        )
    return NotificationPrefsResponse(
        space_id=space.id,
        space_slug=space.slug,
        space_name=space.name,
        weekly_digest_email=prefs.weekly_digest_email,
        daily_digest_email=prefs.daily_digest_email,
        admin_broadcast_email=prefs.admin_broadcast_email,
        gathering_reminder_email=prefs.gathering_reminder_email,
        new_post_email=prefs.new_post_email,
        comment_reply_email=prefs.comment_reply_email,
        pathway_comment_email=prefs.pathway_comment_email,
        new_pathway_email=prefs.new_pathway_email,
        push_enabled=prefs.push_enabled,
        push_gathering_reminders=prefs.push_gathering_reminders,
        push_replies=prefs.push_replies,
        push_announcements=prefs.push_announcements,
    )


def _require_membership(space_id: str, user_id: str, db: Session) -> None:
    m = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space_id,
        SpaceMembership.user_id == user_id,
        SpaceMembership.status == "active",
    ).first()
    if not m:
        raise HTTPException(status_code=403, detail="You are not a member of this collective.")


@router.get("/{slug}/notification-settings", response_model=NotificationPrefsResponse)
def get_notification_settings(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPrefsResponse:
    space = _get_space_or_404(slug, db)
    _require_membership(space.id, current_user.id, db)
    prefs = db.query(SpaceMemberNotificationPrefs).filter(
        SpaceMemberNotificationPrefs.user_id == current_user.id,
        SpaceMemberNotificationPrefs.space_id == space.id,
    ).first()
    return _prefs_response(space, prefs)


@router.patch("/{slug}/notification-settings", response_model=NotificationPrefsResponse)
def update_notification_settings(
    slug: str,
    payload: NotificationPrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPrefsResponse:
    space = _get_space_or_404(slug, db)
    _require_membership(space.id, current_user.id, db)

    prefs = db.query(SpaceMemberNotificationPrefs).filter(
        SpaceMemberNotificationPrefs.user_id == current_user.id,
        SpaceMemberNotificationPrefs.space_id == space.id,
    ).first()

    if prefs is None:
        import uuid as _uuid
        prefs = SpaceMemberNotificationPrefs(
            id=str(_uuid.uuid4()),
            user_id=current_user.id,
            space_id=space.id,
            **_NOTIF_DEFAULTS,
        )
        db.add(prefs)
        db.flush()

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(prefs, field, value)

    db.commit()
    db.refresh(prefs)
    return _prefs_response(space, prefs)
