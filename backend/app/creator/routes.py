"""
/api/creator/* — routes for creator/admin users to manage their Spaces.

Permission model:
- All endpoints require role in ('creator', 'admin') via get_creator_user.
- Space-specific endpoints additionally verify the caller owns the space
  OR has a creator/moderator membership in that space.
"""

import json
import pathlib
import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.core.storage import delete_file, save_file, save_media_file
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
    EventCreateRequest,
    EventResponse,
    EventUpdateRequest,
    InvitationCreateRequest,
    InvitationResponse,
    BlockMediaInfo,
    MediaAssetResponse,
    MediaAssetUpdateRequest,
    PathwayCreateRequest,
    PathwayResponse,
    PathwayUpdateRequest,
    PostCreateRequest,
    PostManageResponse,
    PostUpdateRequest,
    ReorderRequest,
    SectionCreateRequest,
    SectionResponse,
    SectionUpdateRequest,
    SpaceCreateRequest,
    SpaceDetail,
    SpaceUpdateRequest,
    StepBlockCreateRequest,
    StepBlockReorderRequest,
    StepBlockResponse,
    StepBlockUpdateRequest,
    StepCreateRequest,
    StepResourceCreateRequest,
    StepResourceResponse,
    StepResourceUpdateRequest,
    StepResponse,
    StepUpdateRequest,
    slugify,
)
from app.models.platform import (
    CommunityPost,
    CreatorMediaAsset,
    Event,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceInvitation,
    SpaceMembership,
    StepResource,
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


def _get_step(pathway: Pathway, step_slug: str, db: Session) -> PathwayStep:
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id,
        PathwayStep.slug == step_slug,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    return step


def _get_resource(step: PathwayStep, resource_id: str, db: Session) -> StepResource:
    resource = db.query(StepResource).filter(
        StepResource.id == resource_id,
        StepResource.step_id == step.id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


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


@router.post("/spaces", response_model=SpaceDetail, status_code=201)
def create_space(
    body: SpaceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    existing_slugs = [slug for (slug,) in db.query(Space.slug).all()]
    slug = _unique_slug(slugify(body.name), existing_slugs)
    space = Space(
        id=str(uuid4()),
        slug=slug,
        name=body.name.strip(),
        tagline=body.tagline.strip() if body.tagline else None,
        description=body.description.strip() if body.description else None,
        creator_id=current_user.id,
        is_public=False,
        status="draft",
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


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
    if body.is_public is not None:
        space.is_public = body.is_public
    if body.status is not None:
        space.status = body.status
    db.commit()
    db.refresh(space)
    return space


@router.post("/spaces/{slug}/cover", response_model=SpaceDetail)
async def upload_cover_image(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    space = _get_managed_space(slug, current_user, db)
    filename = file.filename or "cover.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are allowed.")
    data = await file.read()
    if space.cover_image_url:
        old_rel = space.cover_image_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "covers")
    space.cover_image_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(space)
    return space


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/invitations", response_model=list[InvitationResponse])
def list_invitations(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[InvitationResponse]:
    space = _get_managed_space(slug, current_user, db)
    invitations = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.space_id == space.id)
        .order_by(SpaceInvitation.created_at.desc())
        .all()
    )
    return [InvitationResponse.model_validate(inv) for inv in invitations]


@router.post("/spaces/{slug}/invitations", response_model=InvitationResponse, status_code=201)
def create_invitation(
    slug: str,
    body: InvitationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> InvitationResponse:
    space = _get_managed_space(slug, current_user, db)

    # Reject if email already belongs to an active member of this space
    existing_member = (
        db.query(SpaceMembership)
        .join(User, User.id == SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
            func.lower(User.email) == body.email,  # body.email already lowercased
        )
        .first()
    )
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person is already a member of this collective.",
        )

    # Reject duplicate pending invitation
    existing_invite = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.email == body.email,
        )
        .first()
    )
    if existing_invite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person has already been invited to this collective.",
        )

    # TODO: Send invitation email when email service is connected.
    invitation = SpaceInvitation(
        id=str(uuid4()),
        space_id=space.id,
        email=body.email,
        name=body.name,
        role=body.role,
        note=body.note,
        invited_by_id=current_user.id,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return InvitationResponse.model_validate(invitation)


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
            "practice_body": p.practice_body,
            "cover_image_url": p.cover_image_url,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "access_type": p.access_type,
            "price_cents": p.price_cents,
            "currency": p.currency,
            "billing_interval": p.billing_interval,
            "is_sequential": p.is_sequential,
            "position": p.position,
            "step_count": step_count,
            "updated_at": p.updated_at,
            "created_at": p.created_at,
        })
    return result


@router.get("/spaces/{slug}/pathways/{pathway_slug}", response_model=PathwayResponse)
def get_pathway(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        "id": pathway.id,
        "slug": pathway.slug,
        "title": pathway.title,
        "description": pathway.description,
        "practice_body": pathway.practice_body,
        "cover_image_url": pathway.cover_image_url,
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "access_type": pathway.access_type,
        "price_cents": pathway.price_cents,
        "currency": pathway.currency,
        "billing_interval": pathway.billing_interval,
        "is_sequential": pathway.is_sequential,
        "position": pathway.position,
        "step_count": step_count,
        "updated_at": pathway.updated_at,
        "created_at": pathway.created_at,
    }


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
        practice_body=body.practice_body,
        status=body.status,
        is_sequential=body.is_sequential,
        position=position,
        access_type=body.access_type,
        price_cents=body.price_cents,
        currency=body.currency,
        billing_interval=body.billing_interval,
    )
    db.add(pathway)
    db.commit()
    db.refresh(pathway)
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "price_cents", "currency",
                                             "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "step_count": 0,
    }


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

    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if field == "title" and val is not None:
            pathway.title = val.strip()
        elif field in ("description", "practice_body"):
            setattr(pathway, field, (val.strip() or None) if val else None)
        elif field == "status" and val is not None:
            pathway.status = val
        elif field == "is_sequential" and val is not None:
            pathway.is_sequential = val
        elif field == "access_type" and val is not None:
            pathway.access_type = val
        elif field in ("price_cents", "billing_interval"):
            setattr(pathway, field, val)
        elif field == "currency" and val is not None:
            pathway.currency = val

    db.commit()
    db.refresh(pathway)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "price_cents", "currency",
                                             "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "step_count": step_count,
    }


@router.post("/spaces/{slug}/pathways/{pathway_slug}/cover", response_model=PathwayResponse)
async def upload_pathway_cover(
    slug: str,
    pathway_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    filename = file.filename or "cover.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are allowed.")
    data = await file.read()
    if pathway.cover_image_url:
        old_rel = pathway.cover_image_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "pathway-covers")
    pathway.cover_image_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(pathway)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "price_cents", "currency",
                                             "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "step_count": step_count,
    }


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
# Sections
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways/{pathway_slug}/sections", response_model=list[SectionResponse])
def list_sections(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwaySection]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwaySection)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position)
        .all()
    )


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections", response_model=SectionResponse, status_code=201)
def create_section(
    slug: str,
    pathway_slug: str,
    body: SectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwaySection:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    max_pos = (
        db.query(PathwaySection.position)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0
    section = PathwaySection(
        id=str(uuid4()),
        pathway_id=pathway.id,
        title=body.title,
        position=position,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.patch("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}", response_model=SectionResponse)
def update_section(
    slug: str,
    pathway_slug: str,
    section_id: str,
    body: SectionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwaySection:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    if body.title is not None:
        section.title = body.title
    db.commit()
    db.refresh(section)
    return section


@router.delete("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}", status_code=204)
def delete_section(
    slug: str,
    pathway_slug: str,
    section_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    # Unlink steps from this section before deleting
    db.query(PathwayStep).filter(PathwayStep.section_id == section_id).update({"section_id": None})
    db.delete(section)
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections/reorder", status_code=204)
def reorder_sections(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwaySection).filter(
            PathwaySection.id == sid, PathwaySection.pathway_id == pathway.id
        ).update({"position": i})
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

    section_position: int | None = None
    if body.section_id:
        max_sec_pos = (
            db.query(PathwayStep.section_position)
            .filter(PathwayStep.section_id == body.section_id, PathwayStep.section_position.isnot(None))
            .order_by(PathwayStep.section_position.desc())
            .first()
        )
        section_position = (max_sec_pos[0] + 1) if max_sec_pos else 0

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
        section_id=body.section_id,
        section_position=section_position,
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

    # Use model_fields_set so null values in JSON explicitly clear the field
    update = body.model_dump(exclude_unset=True)
    if "title" in update and update["title"] is not None:
        step.title = update["title"].strip()
    if "content_type" in update and update["content_type"] is not None:
        step.content_type = update["content_type"]
    if "content_body" in update:
        step.content_body = update["content_body"] or None
    if "content_url" in update:
        step.content_url = update["content_url"] or None
    if "estimated_minutes" in update:
        step.estimated_minutes = update["estimated_minutes"]
    if "is_required" in update and update["is_required"] is not None:
        step.is_required = update["is_required"]
    if "section_id" in update:
        new_section_id = update["section_id"]
        if new_section_id != step.section_id:
            step.section_id = new_section_id
            if new_section_id:
                # Place at end of the new section
                max_sec_pos = (
                    db.query(PathwayStep.section_position)
                    .filter(
                        PathwayStep.section_id == new_section_id,
                        PathwayStep.id != step.id,
                        PathwayStep.section_position.isnot(None),
                    )
                    .order_by(PathwayStep.section_position.desc())
                    .first()
                )
                step.section_position = (max_sec_pos[0] + 1) if max_sec_pos else 0
            else:
                step.section_position = None

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
    """Reorder all steps in a flat (no-sections) pathway by global position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid, PathwayStep.pathway_id == pathway.id
        ).update({"position": i})
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps/unsectioned/reorder", status_code=204)
def reorder_unsectioned_steps(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Reorder unsectioned steps by global position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid,
            PathwayStep.pathway_id == pathway.id,
            PathwayStep.section_id.is_(None),
        ).update({"position": i})
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}/steps/reorder", status_code=204)
def reorder_section_steps(
    slug: str,
    pathway_slug: str,
    section_id: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Reorder steps within a section by section_position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid,
            PathwayStep.section_id == section_id,
        ).update({"section_position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Step Resources
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=list[StepResourceResponse],
)
def list_step_resources(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[StepResource]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    return (
        db.query(StepResource)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position)
        .all()
    )


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=StepResourceResponse,
    status_code=201,
)
def create_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepResourceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    max_pos = (
        db.query(StepResource.position)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    resource = StepResource(
        id=str(uuid4()),
        step_id=step.id,
        title=body.title,
        description=body.description,
        resource_type=body.resource_type,
        url=body.url,
        file_name=None,
        file_size=None,
        mime_type=None,
        position=position,
        is_downloadable=False,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/upload",
    response_model=StepResourceResponse,
    status_code=201,
)
def upload_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    try:
        data = file.file.read()
        rel_path, resource_type, size = save_file(
            data=data,
            original_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            subdir=f"steps/{step.id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    max_pos = (
        db.query(StepResource.position)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    resource = StepResource(
        id=str(uuid4()),
        step_id=step.id,
        title=title.strip(),
        description=description.strip() if description else None,
        resource_type=resource_type,
        url=rel_path,
        file_name=file.filename,
        file_size=size,
        mime_type=file.content_type,
        position=position,
        is_downloadable=True,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/{resource_id}",
    response_model=StepResourceResponse,
)
def update_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    resource_id: str,
    body: StepResourceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    resource = _get_resource(step, resource_id, db)

    update = body.model_dump(exclude_unset=True)
    if "title" in update and update["title"] is not None:
        resource.title = update["title"].strip()
    if "description" in update:
        resource.description = (update["description"] or "").strip() or None
    if "url" in update and update["url"] is not None and resource.file_name is None:
        # Only allow URL edits on link-type resources (not uploaded files)
        resource.url = update["url"].strip() or None

    db.commit()
    db.refresh(resource)
    return resource


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/{resource_id}",
    status_code=204,
)
def delete_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    resource = _get_resource(step, resource_id, db)

    # Clean up uploaded file if present
    if resource.url and resource.file_name:
        delete_file(resource.url)

    db.delete(resource)
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


@router.patch("/spaces/{slug}/community/{post_id}", response_model=PostManageResponse)
def update_post(
    slug: str,
    post_id: str,
    body: PostUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if body.post_type is not None:
        post.post_type = body.post_type
    if body.title is not None:
        post.title = body.title or None
    if body.body is not None:
        post.body = body.body
    if body.is_pinned is not None:
        post.is_pinned = body.is_pinned
    db.commit()
    db.refresh(post)
    from app.models.user import User as UserModel
    author = db.get(UserModel, post.author_id)
    return {
        "id": post.id,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        "title": post.title,
        "body": post.body,
        "is_pinned": post.is_pinned,
        "is_visible": post.is_visible,
        "created_at": post.created_at,
        "author_name": author.name or author.email.split("@")[0] if author else "",
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


@router.patch("/spaces/{slug}/community/{post_id}/hide", status_code=204)
def hide_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Soft-hide: removes from learner feed but keeps manageable in Creator Studio."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_visible = False
    db.commit()


@router.patch("/spaces/{slug}/community/{post_id}/unhide", status_code=204)
def unhide_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Restore a hidden post to the learner feed."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_visible = True
    db.commit()


@router.delete("/spaces/{slug}/community/{post_id}", status_code=204)
def delete_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Hard delete. Use hide/unhide for reversible moderation."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    db.delete(post)
    db.commit()


# ---------------------------------------------------------------------------
# Media Library
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/media", response_model=list[MediaAssetResponse])
def list_media(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[CreatorMediaAsset]:
    """Return active media assets for the given space, newest first."""
    space = _get_managed_space(slug, current_user, db)
    return (
        db.query(CreatorMediaAsset)
        .filter(
            CreatorMediaAsset.space_id == space.id,
            CreatorMediaAsset.status == "active",
        )
        .order_by(CreatorMediaAsset.created_at.desc())
        .all()
    )


@router.post("/spaces/{slug}/media", response_model=MediaAssetResponse, status_code=201)
async def upload_media(
    slug: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
    """
    Upload a file to the media library for the given space.

    Files are organised under uploads/media/{space_slug}/.
    // TODO: Move video storage/streaming to Mux, Cloudflare Stream, S3, or similar before production-scale use.
    // TODO: protect private member resources behind authenticated access checks before production.
    """
    space = _get_managed_space(slug, current_user, db)
    data = await file.read()
    original_name = file.filename or "upload"
    mime = file.content_type or "application/octet-stream"

    try:
        storage_path, file_url, media_type, stored_filename, size = save_media_file(
            data, original_name, mime, space.slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ext = pathlib.Path(original_name).suffix.lower()
    used_title = title.strip() if title.strip() else pathlib.Path(original_name).stem

    asset = CreatorMediaAsset(
        id=str(uuid4()),
        space_id=space.id,
        uploaded_by_user_id=current_user.id,
        title=used_title,
        description=description.strip() if description.strip() else None,
        original_filename=original_name,
        stored_filename=stored_filename,
        storage_path=storage_path,
        file_url=file_url,
        mime_type=mime,
        media_type=media_type,
        file_size_bytes=size,
        extension=ext,
        status="active",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/spaces/{slug}/media/{media_id}", response_model=MediaAssetResponse)
def update_media(
    slug: str,
    media_id: str,
    body: MediaAssetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
    """Update title or description of a media asset."""
    space = _get_managed_space(slug, current_user, db)
    asset = db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.id == media_id,
        CreatorMediaAsset.space_id == space.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    if body.title is not None:
        asset.title = body.title
    if body.description is not None:
        asset.description = body.description or None
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/spaces/{slug}/media/{media_id}/archive", response_model=MediaAssetResponse)
def archive_media(
    slug: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
    """Soft-archive a media asset. Hides from the active library."""
    space = _get_managed_space(slug, current_user, db)
    asset = db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.id == media_id,
        CreatorMediaAsset.space_id == space.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    asset.status = "archived"
    db.commit()
    db.refresh(asset)
    return asset


# ---------------------------------------------------------------------------
# Step Blocks
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=list[StepBlockResponse],
)
def list_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    return (
        db.query(PathwayStepBlock)
        .options(selectinload(PathwayStepBlock.media_asset))
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )


def _parse_inline_bold(raw: str) -> list[dict]:
    nodes: list[dict] = []
    parts = re.split(r"\*\*(.+?)\*\*", raw)
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 0:
            nodes.append({"type": "text", "text": part})
        else:
            nodes.append({"type": "text", "marks": [{"type": "bold"}], "text": part})
    return nodes or [{"type": "text", "text": ""}]


def _content_body_to_tiptap(content_body: str) -> str:
    chunks = [c.strip() for c in re.split(r"\n\n+", content_body.strip()) if c.strip()]
    nodes: list[dict] = []
    for chunk in chunks:
        if chunk == "---":
            nodes.append({"type": "horizontalRule"})
            continue
        lines = chunk.split("\n")
        if all(ln.startswith("- ") for ln in lines):
            nodes.append({"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": _parse_inline_bold(ln[2:])}
                ]}
                for ln in lines
            ]})
            continue
        if len(lines) == 1 and re.match(r"^\*\*[^*]+\*\*$", chunk):
            nodes.append({"type": "heading", "attrs": {"level": 3},
                          "content": [{"type": "text", "text": chunk[2:-2]}]})
            continue
        para_text = " ".join(ln.strip() for ln in lines if ln.strip())
        nodes.append({"type": "paragraph", "content": _parse_inline_bold(para_text)})
    if not nodes:
        nodes = [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]
    return json.dumps({"type": "doc", "content": nodes}, ensure_ascii=False)


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/convert-legacy",
    response_model=list[StepBlockResponse],
    status_code=201,
)
def convert_legacy_content(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    """Convert a step's legacy content_body into an editable text block.

    Only acts when content_body is non-empty and the step has no existing blocks.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    existing = (
        db.query(PathwayStepBlock)
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )
    if existing:
        return existing  # Already has blocks — nothing to do

    if not step.content_body or not step.content_body.strip():
        return []  # No legacy content to convert

    tiptap_json = _content_body_to_tiptap(step.content_body)
    block = PathwayStepBlock(
        id=str(uuid4()),
        step_id=step.id,
        block_type="text",  # type: ignore[arg-type]
        position=0,
        content=tiptap_json,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return [block]


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=StepBlockResponse,
    status_code=201,
)
def create_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStepBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    # Validate media_asset_id belongs to this space
    if body.media_asset_id:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    # Determine position
    if body.position is not None:
        position = body.position
    else:
        max_pos = (
            db.query(func.max(PathwayStepBlock.position))
            .filter(PathwayStepBlock.step_id == step.id)
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayStepBlock(
        id=str(uuid4()),
        step_id=step.id,
        block_type=body.block_type,
        position=position,
        content=body.content,
        label=body.label,
        caption=body.caption,
        embed_url=body.embed_url,
        media_asset_id=body.media_asset_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
    return block


# IMPORTANT: Register /blocks/reorder BEFORE /blocks/{block_id} to avoid route conflict
@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/reorder",
    response_model=list[StepBlockResponse],
)
def reorder_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayStepBlock)
        .filter(PathwayStepBlock.step_id == step.id)
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()

    return (
        db.query(PathwayStepBlock)
        .options(selectinload(PathwayStepBlock.media_asset))
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/{block_id}",
    response_model=StepBlockResponse,
)
def update_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    body: StepBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStepBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    block = db.query(PathwayStepBlock).filter(
        PathwayStepBlock.id == block_id,
        PathwayStepBlock.step_id == step.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found.")

    if body.media_asset_id is not None:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
    return block


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/{block_id}",
    status_code=204,
)
def delete_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    block = db.query(PathwayStepBlock).filter(
        PathwayStepBlock.id == block_id,
        PathwayStepBlock.step_id == step.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found.")

    db.delete(block)
    db.commit()


# ---------------------------------------------------------------------------
# Pathway About Blocks — CRUD for the pathway-level about/sales page
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_about_blocks(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwayAboutBlock)
        .options(selectinload(PathwayAboutBlock.media_asset))
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=AboutBlockResponse,
    status_code=201,
)
def create_about_block(
    slug: str,
    pathway_slug: str,
    body: AboutBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    if body.media_asset_id:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.position is not None:
        position = body.position
    else:
        max_pos = (
            db.query(func.max(PathwayAboutBlock.position))
            .filter(PathwayAboutBlock.pathway_id == pathway.id)
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayAboutBlock(
        id=str(uuid4()),
        pathway_id=pathway.id,
        block_type=body.block_type,
        position=position,
        content=body.content,
        label=body.label,
        caption=body.caption,
        embed_url=body.embed_url,
        media_asset_id=body.media_asset_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
    return block


# IMPORTANT: /about-blocks/reorder must be registered BEFORE /about-blocks/{block_id}
@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/reorder",
    response_model=list[AboutBlockResponse],
)
def reorder_about_blocks(
    slug: str,
    pathway_slug: str,
    body: AboutBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayAboutBlock)
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()

    return (
        db.query(PathwayAboutBlock)
        .options(selectinload(PathwayAboutBlock.media_asset))
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/{block_id}",
    response_model=AboutBlockResponse,
)
def update_about_block(
    slug: str,
    pathway_slug: str,
    block_id: str,
    body: AboutBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    block = db.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.id == block_id,
        PathwayAboutBlock.pathway_id == pathway.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    if body.media_asset_id is not None:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
    return block


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/{block_id}",
    status_code=204,
)
def delete_about_block(
    slug: str,
    pathway_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    block = db.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.id == block_id,
        PathwayAboutBlock.pathway_id == pathway.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    db.delete(block)
    db.commit()
