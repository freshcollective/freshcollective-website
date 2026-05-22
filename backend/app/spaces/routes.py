import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.creator.schemas import AboutBlockResponse, BlockMediaInfo, StepBlockResponse
from app.models.platform import (
    Enrollment,
    EntitlementStatus,
    Event,
    Pathway,
    PathwayAboutBlock,
    PathwayEntitlement,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceMembership,
    SpaceMemberNotificationPrefs,
    StepComment,
    StepProgress,
    StepResource,
)
from app.models.user import User
from app.spaces.schemas import (
    CompleteStepRequest,
    CompleteStepResponse,
    ContinueResponse,
    EventDetail,
    EventSummary,
    NotificationPrefsResponse,
    NotificationPrefsUpdate,
    PathwayProgress,
    PathwaySummary,
    PathwayWithSteps,
    PublicSpaceCard,
    SaveNotesRequest,
    SaveNotesResponse,
    SectionWithSteps,
    SpaceResponse,
    SpaceSummary,
    StepCommentAuthor,
    StepCommentCreate,
    StepCommentItem,
    StepDetail,
    StepResourceResponse,
    StepSummary,
)

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
        .filter(Pathway.space_id.in_(space_ids))
        .group_by(Pathway.space_id)
        .all()
    )

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


def _compute_pathway_access(user: User, pathway: Pathway, space: Space, db: Session) -> bool:
    """
    Return True if user has access to this pathway; False otherwise.
    Same rules as _check_pathway_access but returns a bool instead of raising.
    Used by the checkout page to determine which state to show.
    """
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
    # one_time or subscription — requires active PathwayEntitlement
    ent = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
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

    # one_time / subscription — require an active entitlement
    entitlement = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
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
    current_user: User = Depends(get_current_user),
) -> Space:
    space = (
        db.query(Space)
        .options(selectinload(Space.pathways))
        .filter(Space.slug == slug, Space.status == "active")
        .first()
    )
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@router.get("/{slug}/pathways", response_model=list[PathwaySummary])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PathwaySummary]:
    space = _get_space_or_404(slug, db)
    is_creator_or_admin = current_user.role in ("creator", "admin")
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
        # Regular members only see published pathways (active + coming_soon)
        query = query.filter(Pathway.status.in_(["active", "coming_soon"]))

    pathways = query.order_by(Pathway.position).all()

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
            price_cents=p.price_cents,
            currency=p.currency,
            billing_interval=p.billing_interval,
            user_has_access=has_access,
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
    current_user: User = Depends(get_current_user),
) -> list[Event]:
    """All upcoming published events for a space, sorted chronologically."""
    space = _get_space_or_404(slug, db)
    return (
        db.query(Event)
        .filter(
            Event.space_id == space.id,
            Event.is_published.is_(True),
            Event.starts_at >= datetime.utcnow(),
        )
        .order_by(Event.starts_at)
        .all()
    )


@router.get("/{slug}/events/{event_id}", response_model=EventDetail)
def get_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    """Return a single published event by ID within a space."""
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
    return event


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
    current_user: User = Depends(get_current_user),
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
    completed = _completed_step_ids(current_user.id, step_ids, db)

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
        price_cents=pathway.price_cents,
        currency=pathway.currency,
        billing_interval=pathway.billing_interval,
        user_has_access=user_has_access,
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
    current_user: User = Depends(get_current_user),
) -> list[PathwayAboutBlock]:
    """Return about-page blocks for a pathway.

    Accessible to any authenticated user — locked pathways can still show
    their About page as a preview/sales page before purchase.
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
