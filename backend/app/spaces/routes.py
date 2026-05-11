from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.platform import Pathway, Space
from app.models.user import User
from app.spaces.schemas import PathwaySummary, SpaceResponse, SpaceSummary

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


@router.get("", response_model=list[SpaceSummary])
def list_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Space]:
    """Return all active spaces the current user has access to."""
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
    """Return a single space with its pathways."""
    space = (
        db.query(Space)
        .options(selectinload(Space.pathways))
        .filter(Space.slug == slug, Space.status == "active")
        .first()
    )
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


@router.get("/{slug}/pathways", response_model=list[PathwaySummary])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Pathway]:
    """Return all pathways in a space, ordered by position."""
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.position)
        .all()
    )
