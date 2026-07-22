"""
/api/world-guide/* — public governance documents.

Every endpoint is open to anonymous visitors: the World Guide is a
public surface. Only documents that are not archived and have a live
current published version are visible; a document with only draft
versions does not exist at the public URL until it is first published.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin.world_guide.schemas import (
    PublicDocumentCard,
    PublicDocumentDetail,
    PublicRelatedDocument,
)
from app.core.database import get_db
from app.models.world_guide import (
    WorldGuideDocument,
    WorldGuideVersion,
)


router = APIRouter(prefix="/api/world-guide", tags=["world-guide"])


def _published_query(db: Session):
    """Base query — documents with a live published version and not
    archived. Joined against the current version so the caller can
    read version-level fields (number, effective_date) without a
    second lookup."""
    return (
        db.query(WorldGuideDocument, WorldGuideVersion)
        .join(
            WorldGuideVersion,
            WorldGuideVersion.id == WorldGuideDocument.current_version_id,
        )
        .filter(WorldGuideDocument.archived_at.is_(None))
    )


@router.get("", response_model=list[PublicDocumentCard])
def list_public_documents(
    db: Session = Depends(get_db),
) -> list[PublicDocumentCard]:
    rows = _published_query(db).order_by(WorldGuideDocument.title.asc()).all()
    return [
        PublicDocumentCard(
            slug=doc.slug,
            title=doc.title,
            category=doc.category,
            audience=doc.audience,
            summary=doc.summary,
            reading_time_minutes=doc.reading_time_minutes,
            version_number=v.version_number,
            effective_date=v.effective_date,
        )
        for doc, v in rows
    ]


@router.get("/{slug}", response_model=PublicDocumentDetail)
def get_public_document(
    slug: str,
    db: Session = Depends(get_db),
) -> PublicDocumentDetail:
    row = _published_query(db).filter(WorldGuideDocument.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc, v = row

    # Related — every other published document in the same category,
    # up to a small cap. Simple + explicit; a curated relationships
    # table can replace this later without a schema migration.
    related_rows = (
        _published_query(db)
        .filter(
            WorldGuideDocument.category == doc.category,
            WorldGuideDocument.id != doc.id,
        )
        .order_by(WorldGuideDocument.title.asc())
        .limit(4)
        .all()
    )
    related = [
        PublicRelatedDocument(
            slug=other_doc.slug,
            title=other_doc.title,
            category=other_doc.category,
        )
        for other_doc, _ in related_rows
    ]

    return PublicDocumentDetail(
        slug=doc.slug,
        title=doc.title,
        category=doc.category,
        audience=doc.audience,
        summary=doc.summary,
        reading_time_minutes=doc.reading_time_minutes,
        version_number=v.version_number,
        effective_date=v.effective_date,
        published_at=v.published_at,
        updated_at=doc.updated_at,
        why_this_exists=v.why_this_exists,
        what_this_covers=v.what_this_covers,
        main_content=v.main_content,
        whats_changed=v.whats_changed,
        related=related,
    )
