"""
/api/creator/* — routes for creator/admin users to manage their Spaces.

Permission model:
- All endpoints require role in ('creator', 'admin') via get_creator_user.
- Space-specific endpoints additionally verify the caller owns the space
  OR has a creator/moderator membership in that space.
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.creator.schemas import (
    EventCreateRequest,
    EventResponse,
    EventUpdateRequest,
    PathwayCreateRequest,
    PathwayResponse,
    PathwayUpdateRequest,
    PostCreateRequest,
    PostManageResponse,
    ReorderRequest,
    SpaceDetail,
    SpaceUpdateRequest,
    StepCreateRequest,
    StepResponse,
    StepUpdateRequest,
    slugify,
)
from app.models.platform import (
    CommunityPost,
    Event,
    Pathway,
    PathwayStep,
    Space,
    SpaceMembership,
)
from app.models.user import User
from app.spaces.schemas import SpaceSummary

router = APIRouter(prefix="/api/creator", tags=["creator"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _get_managed_space(slug: str, user: User, db: Session) -> Space:
    """Return the Space if the user owns it or is a creator/moderator."""
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    if user.role == "admin":
        return space  # admins can manage anything

    is_owner = space.creator_id == user.id
    if not is_owner:
        mem = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == user.id,
                SpaceMembership.role.in_(["creator", "moderator"]),
                SpaceMembership.status == "active",
            )
            .first()
        )
        if not mem:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage this Space.",
            )
    return space


def _get_pathway(space: Space, pathway_slug: str, db: Session) -> Pathway:
    pathway = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id, Pathway.slug == pathway_slug)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")
    return pathway


def _unique_slug(base: str, existing: list[str]) -> str:
    slug = base
    counter = 2
    while slug in existing:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _pathway_slug(space: Space, title: str, exclude_id: str | None, db: Session) -> str:
    existing = [
        p.slug for p in db.query(Pathway.slug)
        .filter(Pathway.space_id == space.id, Pathway.id != exclude_id)
        .all()
    ]
    return _unique_slug(slugify(title), existing)


def _step_slug(pathway: Pathway, title: str, exclude_id: str | None, db: Session) -> str:
    existing = [
        s.slug for s in db.query(PathwayStep.slug)
        .filter(PathwayStep.pathway_id == pathway.id, PathwayStep.id != exclude_id)
        .all()
    ]
    return _unique_slug(slugify(title), existing)


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@router.get("/spaces", response_model=list[SpaceSummary])
def list_my_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[Space]:
    if current_user.role == "admin":
        return db.query(Space).order_by(Space.name).all()
    owned = db.query(Space).filter(Space.creator_id == current_user.id).all()
    membered = (
        db.query(Space)
        .join(SpaceMembership, SpaceMembership.space_id == Space.id)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .all()
    )
    seen = {s.id for s in owned}
    return owned + [s for s in membered if s.id not in seen]


@router.get("/spaces/{slug}", response_model=SpaceDetail)
def get_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    return _get_managed_space(slug, current_user, db)


@router.patch("/spaces/{slug}", response_model=SpaceDetail)
def update_space(
    slug: str,
    body: SpaceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    space = _get_managed_space(slug, current_user, db)
    if body.name is not None:
        space.name = body.name.strip()
    if body.tagline is not None:
        space.tagline = body.tagline.strip() or None
    if body.description is not None:
        space.description = body.description.strip() or None
    db.commit()
    db.refresh(space)
    return space


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways", response_model=list[PathwayResponse])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    pathways = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.position)
        .all()
    )
    result = []
    for p in pathways:
        step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == p.id).count()
        result.append({
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "is_sequential": p.is_sequential,
            "position": p.position,
            "step_count": step_count,
            "created_at": p.created_at,
        })
    return result


@router.post("/spaces/{slug}/pathways", response_model=PathwayResponse, status_code=201)
def create_pathway(
    slug: str,
    body: PathwayCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)

    pslug = body.slug or _pathway_slug(space, body.title, None, db)
    existing = db.query(Pathway).filter(Pathway.space_id == space.id, Pathway.slug == pslug).first()
    if existing:
        pslug = _pathway_slug(space, body.title, None, db)

    max_pos = db.query(Pathway.position).filter(Pathway.space_id == space.id).order_by(Pathway.position.desc()).first()
    position = (max_pos[0] + 1) if max_pos else 0

    pathway = Pathway(
        id=str(uuid4()),
        space_id=space.id,
        slug=pslug,
        title=body.title.strip(),
        description=body.description,
        status=body.status,
        is_sequential=body.is_sequential,
        position=position,
    )
    db.add(pathway)
    db.commit()
    db.refresh(pathway)
    return {**{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "is_sequential", "position", "created_at"]},
            "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
            "step_count": 0}


@router.patch("/spaces/{slug}/pathways/{pathway_slug}", response_model=PathwayResponse)
def update_pathway(
    slug: str,
    pathway_slug: str,
    body: PathwayUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    if body.title is not None:
        pathway.title = body.title.strip()
    if body.description is not None:
        pathway.description = body.description.strip() or None
    if body.status is not None:
        pathway.status = body.status
    if body.is_sequential is not None:
        pathway.is_sequential = body.is_sequential

    db.commit()
    db.refresh(pathway)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {**{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "is_sequential", "position", "created_at"]},
            "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
            "step_count": step_count}


@router.post("/spaces/{slug}/pathways/reorder", status_code=204)
def reorder_pathways(
    slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    for i, pid in enumerate(body.ids):
        db.query(Pathway).filter(Pathway.id == pid, Pathway.space_id == space.id).update({"position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways/{pathway_slug}/steps", response_model=list[StepResponse])
def list_steps(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStep]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )


@router.get("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepResponse)
def get_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id,
        PathwayStep.slug == step_slug,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    return step


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps", response_model=StepResponse, status_code=201)
def create_step(
    slug: str,
    pathway_slug: str,
    body: StepCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    sslug = body.slug or _step_slug(pathway, body.title, None, db)
    max_pos = db.query(PathwayStep.position).filter(PathwayStep.pathway_id == pathway.id).order_by(PathwayStep.position.desc()).first()
    position = (max_pos[0] + 1) if max_pos else 0

    step = PathwayStep(
        id=str(uuid4()),
        pathway_id=pathway.id,
        slug=sslug,
        title=body.title.strip(),
        content_type=body.content_type,
        content_body=body.content_body,
        content_url=body.content_url,
        estimated_minutes=body.estimated_minutes,
        is_required=body.is_required,
        position=position,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.patch("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepResponse)
def update_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id, PathwayStep.slug == step_slug
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")

    if body.title is not None:
        step.title = body.title.strip()
    if body.content_type is not None:
        step.content_type = body.content_type
    if body.content_body is not None:
        step.content_body = body.content_body
    if body.content_url is not None:
        step.content_url = body.content_url or None
    if body.estimated_minutes is not None:
        step.estimated_minutes = body.estimated_minutes
    if body.is_required is not None:
        step.is_required = body.is_required

    db.commit()
    db.refresh(step)
    return step


@router.delete("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", status_code=204)
def delete_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id, PathwayStep.slug == step_slug
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    db.delete(step)
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps/reorder", status_code=204)
def reorder_steps(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid, PathwayStep.pathway_id == pathway.id
        ).update({"position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/events", response_model=list[EventResponse])
def list_events(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[Event]:
    space = _get_managed_space(slug, current_user, db)
    return (
        db.query(Event)
        .filter(Event.space_id == space.id)
        .order_by(Event.starts_at.desc())
        .all()
    )


@router.get("/spaces/{slug}/events/{event_id}", response_model=EventResponse)
def get_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Event:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


@router.post("/spaces/{slug}/events", response_model=EventResponse, status_code=201)
def create_event(
    slug: str,
    body: EventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Event:
    space = _get_managed_space(slug, current_user, db)
    event = Event(
        id=str(uuid4()),
        space_id=space.id,
        created_by_id=current_user.id,
        title=body.title.strip(),
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        location_type=body.location_type,
        location_url=body.location_url,
        recording_url=body.recording_url,
        is_published=body.is_published,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/spaces/{slug}/events/{event_id}", response_model=EventResponse)
def update_event(
    slug: str,
    event_id: str,
    body: EventUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Event:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    for field in ("title", "description", "starts_at", "ends_at", "location_type", "location_url", "recording_url", "is_published"):
        val = getattr(body, field)
        if val is not None:
            setattr(event, field, val)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/spaces/{slug}/events/{event_id}", status_code=204)
def delete_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    db.delete(event)
    db.commit()


# ---------------------------------------------------------------------------
# Community management
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/community", response_model=list[PostManageResponse])
def list_posts(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    from app.models.user import User as UserModel
    rows = (
        db.query(CommunityPost, UserModel)
        .join(UserModel, UserModel.id == CommunityPost.author_id)
        .filter(CommunityPost.space_id == space.id)
        .order_by(CommunityPost.created_at.desc())
        .all()
    )
    return [
        {
            "id": post.id,
            "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
            "title": post.title,
            "body": post.body,
            "is_pinned": post.is_pinned,
            "is_visible": post.is_visible,
            "created_at": post.created_at,
            "author_name": author.name or author.email.split("@")[0],
        }
        for post, author in rows
    ]


@router.post("/spaces/{slug}/community", response_model=PostManageResponse, status_code=201)
def create_post(
    slug: str,
    body: PostCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    post = CommunityPost(
        id=str(uuid4()),
        space_id=space.id,
        author_id=current_user.id,
        post_type=body.post_type,
        title=body.title,
        body=body.body,
        is_pinned=body.is_pinned,
        is_visible=True,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {
        "id": post.id,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        "title": post.title,
        "body": post.body,
        "is_pinned": post.is_pinned,
        "is_visible": post.is_visible,
        "created_at": post.created_at,
        "author_name": current_user.name or current_user.email.split("@")[0],
    }


@router.patch("/spaces/{slug}/community/{post_id}/pin", status_code=204)
def toggle_pin(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_pinned = not post.is_pinned
    db.commit()


@router.delete("/spaces/{slug}/community/{post_id}", status_code=204)
def hide_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_visible = False
    db.commit()
