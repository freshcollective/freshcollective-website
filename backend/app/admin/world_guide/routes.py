"""
/api/admin/world-guide/* — governance CMS for Fresh Collective.

Every endpoint is guarded by ``get_admin_user`` — the World Guide is a
platform-owner surface, not a creator-side one.

Model shape (see ``app.models.world_guide``):

  - ``WorldGuideDocument`` holds the metadata a document keeps across
    every version (title, slug, category, audience, summary) plus a
    nullable ``current_version_id`` pointing at the currently-live
    published version.

  - ``WorldGuideVersion`` holds the content. A version's ``status`` is
    one of ``draft`` / ``published`` / ``archived``. Only draft
    versions are editable. Publishing a draft is a one-way state
    transition; to change a published document, callers create a new
    draft version.

  - ``WorldGuideAcceptance`` exists at the schema layer but is not
    exposed by any endpoint yet — the member acceptance workflow will
    land later without a further migration.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.world_guide.schemas import (
    CreateDocumentRequest,
    DocumentDetail,
    DocumentListRow,
    DocumentSummary,
    NewDraftFromCurrentRequest,
    UpdateDocumentRequest,
    UpdateVersionRequest,
    VersionDetail,
    VersionSummary,
    WorldGuideOverview,
)
from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.storage import save_media_file
from app.models.user import User
from app.models.world_guide import (
    WorldGuideDocument,
    WorldGuideVersion,
    estimate_reading_time_minutes,
    next_version_number,
)


router = APIRouter(prefix="/api/admin/world-guide", tags=["world-guide"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _name_map(db: Session, user_ids: set[str]) -> dict[str, str | None]:
    if not user_ids:
        return {}
    rows = db.query(User.id, User.name).filter(User.id.in_(user_ids)).all()
    return {uid: name for uid, name in rows}


def _load_document(db: Session, doc_id: str) -> WorldGuideDocument:
    doc = db.query(WorldGuideDocument).filter(WorldGuideDocument.id == doc_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


def _load_version(db: Session, version_id: str) -> WorldGuideVersion:
    v = db.query(WorldGuideVersion).filter(WorldGuideVersion.id == version_id).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return v


def _latest_by_kind(
    db: Session, document_id: str, status_value: str
) -> WorldGuideVersion | None:
    return (
        db.query(WorldGuideVersion)
        .filter(
            WorldGuideVersion.document_id == document_id,
            WorldGuideVersion.status == status_value,
        )
        .order_by(WorldGuideVersion.created_at.desc())
        .first()
    )


def _open_draft(db: Session, document_id: str) -> WorldGuideVersion | None:
    """Return the currently-mutable draft (there is at most one)."""
    return _latest_by_kind(db, document_id, "draft")


def _document_status(doc: WorldGuideDocument, versions: list[WorldGuideVersion]) -> str:
    """Roll a document into a single status for the admin list.

    Archived beats everything (the document itself is archived);
    otherwise published > draft.
    """
    if doc.archived_at is not None:
        return "archived"
    if any(v.status == "published" for v in versions):
        return "published"
    return "draft"


def _version_summary(v: WorldGuideVersion, names: dict[str, str | None]) -> VersionSummary:
    return VersionSummary(
        id=v.id,
        version_number=v.version_number,
        status=v.status,
        effective_date=v.effective_date,
        published_at=v.published_at,
        published_by_name=names.get(v.published_by_user_id) if v.published_by_user_id else None,
        last_edited_by_name=names.get(v.last_edited_by_user_id) if v.last_edited_by_user_id else None,
        updated_at=v.updated_at,
    )


def _version_detail(v: WorldGuideVersion, names: dict[str, str | None]) -> VersionDetail:
    return VersionDetail(
        id=v.id,
        document_id=v.document_id,
        version_number=v.version_number,
        status=v.status,
        effective_date=v.effective_date,
        why_this_exists=v.why_this_exists,
        what_this_covers=v.what_this_covers,
        main_content=v.main_content,
        whats_changed=v.whats_changed,
        published_at=v.published_at,
        published_by_name=names.get(v.published_by_user_id) if v.published_by_user_id else None,
        last_edited_by_name=names.get(v.last_edited_by_user_id) if v.last_edited_by_user_id else None,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _current_published(doc: WorldGuideDocument, db: Session) -> WorldGuideVersion | None:
    if not doc.current_version_id:
        return None
    return db.query(WorldGuideVersion).filter(
        WorldGuideVersion.id == doc.current_version_id
    ).first()


# ---------------------------------------------------------------------------
# GET /overview
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=WorldGuideOverview)
def get_overview(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> WorldGuideOverview:
    published_count = int(
        db.query(func.count(WorldGuideDocument.id))
        .filter(
            WorldGuideDocument.current_version_id.isnot(None),
            WorldGuideDocument.archived_at.is_(None),
        )
        .scalar()
        or 0
    )
    draft_count = int(
        db.query(func.count(WorldGuideDocument.id))
        .filter(
            WorldGuideDocument.current_version_id.is_(None),
            WorldGuideDocument.archived_at.is_(None),
        )
        .scalar()
        or 0
    )
    archived_count = int(
        db.query(func.count(WorldGuideDocument.id))
        .filter(WorldGuideDocument.archived_at.isnot(None))
        .scalar()
        or 0
    )

    # Last published — pick the document whose current version was
    # most recently published_at.
    last_published_doc: WorldGuideDocument | None = None
    last_pub_row = (
        db.query(WorldGuideDocument, WorldGuideVersion)
        .join(
            WorldGuideVersion,
            WorldGuideVersion.id == WorldGuideDocument.current_version_id,
        )
        .filter(WorldGuideDocument.archived_at.is_(None))
        .order_by(WorldGuideVersion.published_at.desc())
        .first()
    )
    if last_pub_row is not None:
        last_published_doc = last_pub_row[0]

    # Recently updated: any document (draft or published) sorted by
    # its own updated_at.
    recent = (
        db.query(WorldGuideDocument)
        .filter(WorldGuideDocument.archived_at.is_(None))
        .order_by(WorldGuideDocument.updated_at.desc())
        .limit(6)
        .all()
    )

    versions_by_doc: dict[str, WorldGuideVersion | None] = {}
    for d in recent:
        versions_by_doc[d.id] = _current_published(d, db) or _latest_by_kind(db, d.id, "draft")

    def _summary(d: WorldGuideDocument) -> DocumentSummary:
        cv = versions_by_doc.get(d.id)
        return DocumentSummary(
            id=d.id,
            slug=d.slug,
            title=d.title,
            category=d.category,
            status="published" if d.current_version_id else "draft",
            current_version_number=cv.version_number if cv is not None else None,
            updated_at=d.updated_at,
        )

    last_published = None
    if last_published_doc is not None:
        last_published = _summary(last_published_doc)

    return WorldGuideOverview(
        published_count=published_count,
        draft_count=draft_count,
        archived_count=archived_count,
        last_published=last_published,
        recently_updated=[_summary(d) for d in recent],
    )


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentListRow])
def list_documents(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[DocumentListRow]:
    docs = db.query(WorldGuideDocument).order_by(
        WorldGuideDocument.updated_at.desc()
    ).all()
    if not docs:
        return []
    doc_ids = [d.id for d in docs]
    versions = (
        db.query(WorldGuideVersion)
        .filter(WorldGuideVersion.document_id.in_(doc_ids))
        .all()
    )
    versions_by_doc: dict[str, list[WorldGuideVersion]] = {d.id: [] for d in docs}
    for v in versions:
        versions_by_doc[v.document_id].append(v)

    editor_ids: set[str] = set()
    for v in versions:
        if v.last_edited_by_user_id:
            editor_ids.add(v.last_edited_by_user_id)
    names = _name_map(db, editor_ids)

    rows: list[DocumentListRow] = []
    for d in docs:
        vs = versions_by_doc.get(d.id, [])
        current = next((v for v in vs if v.id == d.current_version_id), None)
        if current is None:
            # Fall back to the most recent version (usually a draft).
            current = max(vs, key=lambda x: x.updated_at) if vs else None
        rows.append(DocumentListRow(
            id=d.id,
            slug=d.slug,
            title=d.title,
            category=d.category,
            audience=d.audience,
            status=_document_status(d, vs),
            current_version_number=current.version_number if current is not None else None,
            effective_date=current.effective_date if current is not None else None,
            updated_at=d.updated_at,
            last_updated_by_name=(
                names.get(current.last_edited_by_user_id)
                if current is not None and current.last_edited_by_user_id else None
            ),
        ))
    return rows


# ---------------------------------------------------------------------------
# POST /documents  —  create document + initial draft version
# ---------------------------------------------------------------------------


@router.post("/documents", response_model=DocumentDetail, status_code=201)
def create_document(
    body: CreateDocumentRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    # Slug uniqueness — the DB has a UNIQUE constraint; check first
    # so the failure is a clean 409 rather than a raw IntegrityError.
    conflict = db.query(WorldGuideDocument.id).filter(
        WorldGuideDocument.slug == body.slug
    ).first()
    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A document with slug {body.slug!r} already exists.",
        )

    doc = WorldGuideDocument(
        id=str(uuid4()),
        slug=body.slug,
        title=body.title.strip(),
        category=body.category,
        audience=body.audience,
        summary=(body.summary or "").strip() or None,
        author_user_id=admin.id,
    )
    db.add(doc)
    db.flush()

    draft = WorldGuideVersion(
        id=str(uuid4()),
        document_id=doc.id,
        version_number=next_version_number(None),
        status="draft",
        effective_date=body.effective_date,
        last_edited_by_user_id=admin.id,
    )
    db.add(draft)
    db.flush()

    db.commit()
    db.refresh(doc)
    return get_document(doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# GET /documents/{id}
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    doc = _load_document(db, document_id)
    versions = (
        db.query(WorldGuideVersion)
        .filter(WorldGuideVersion.document_id == doc.id)
        .order_by(WorldGuideVersion.created_at.desc())
        .all()
    )
    editor_ids: set[str] = set()
    for v in versions:
        if v.published_by_user_id:
            editor_ids.add(v.published_by_user_id)
        if v.last_edited_by_user_id:
            editor_ids.add(v.last_edited_by_user_id)
    if doc.author_user_id:
        editor_ids.add(doc.author_user_id)
    names = _name_map(db, editor_ids)

    published = _current_published(doc, db)
    draft = _open_draft(db, doc.id)

    return DocumentDetail(
        id=doc.id,
        slug=doc.slug,
        title=doc.title,
        category=doc.category,
        audience=doc.audience,
        summary=doc.summary,
        reading_time_minutes=doc.reading_time_minutes,
        author_name=names.get(doc.author_user_id) if doc.author_user_id else None,
        author_user_id=doc.author_user_id,
        archived_at=doc.archived_at,
        current_version_id=doc.current_version_id,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        versions=[_version_summary(v, names) for v in versions],
        current_draft=_version_detail(draft, names) if draft is not None else None,
        current_published=_version_detail(published, names) if published is not None else None,
    )


# ---------------------------------------------------------------------------
# PATCH /documents/{id}
# ---------------------------------------------------------------------------


@router.patch("/documents/{document_id}", response_model=DocumentDetail)
def update_document(
    document_id: str,
    body: UpdateDocumentRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    doc = _load_document(db, document_id)
    if doc.archived_at is not None:
        raise HTTPException(status_code=409, detail="Document is archived.")
    if body.slug is not None and body.slug != doc.slug:
        conflict = db.query(WorldGuideDocument.id).filter(
            WorldGuideDocument.slug == body.slug,
            WorldGuideDocument.id != doc.id,
        ).first()
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A document with slug {body.slug!r} already exists.",
            )
        doc.slug = body.slug
    if body.title is not None:
        doc.title = body.title.strip()
    if body.category is not None:
        doc.category = body.category
    if body.audience is not None:
        doc.audience = body.audience
    if body.summary is not None:
        doc.summary = body.summary.strip() or None
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return get_document(doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /documents/{id}/archive
# ---------------------------------------------------------------------------


@router.post("/documents/{document_id}/archive", response_model=DocumentDetail)
def archive_document(
    document_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    doc = _load_document(db, document_id)
    if doc.archived_at is None:
        doc.archived_at = datetime.utcnow()
        doc.updated_at = datetime.utcnow()
        db.commit()
    return get_document(doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /documents/{id}/duplicate
# ---------------------------------------------------------------------------


@router.post("/documents/{document_id}/duplicate", response_model=DocumentDetail, status_code=201)
def duplicate_document(
    document_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    src = _load_document(db, document_id)
    # Pick a fresh slug so the copy doesn't collide.
    base_slug = f"{src.slug}-copy"
    candidate = base_slug
    n = 1
    while db.query(WorldGuideDocument.id).filter(
        WorldGuideDocument.slug == candidate
    ).first() is not None:
        n += 1
        candidate = f"{base_slug}-{n}"

    # Prefer the published content if present; else the current draft.
    src_version = _current_published(src, db) or _open_draft(db, src.id)

    new_doc = WorldGuideDocument(
        id=str(uuid4()),
        slug=candidate,
        title=f"{src.title} (copy)",
        category=src.category,
        audience=src.audience,
        summary=src.summary,
        author_user_id=admin.id,
    )
    db.add(new_doc)
    db.flush()

    new_draft = WorldGuideVersion(
        id=str(uuid4()),
        document_id=new_doc.id,
        version_number=next_version_number(None),
        status="draft",
        effective_date=src_version.effective_date if src_version else None,
        why_this_exists=src_version.why_this_exists if src_version else None,
        what_this_covers=src_version.what_this_covers if src_version else None,
        main_content=src_version.main_content if src_version else None,
        whats_changed=None,
        last_edited_by_user_id=admin.id,
    )
    db.add(new_draft)
    db.flush()

    _recalculate_reading_time(db, new_doc)
    db.commit()
    return get_document(new_doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /documents/{id}/versions  —  new draft
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentDetail,
    status_code=201,
)
def create_new_draft(
    document_id: str,
    body: NewDraftFromCurrentRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Create a new draft version.

    Refuses if there is already an open draft — a document has at most
    one editable draft at a time. Callers wanting to reset the draft
    should just edit the existing draft in place.
    """
    doc = _load_document(db, document_id)
    if doc.archived_at is not None:
        raise HTTPException(status_code=409, detail="Document is archived.")
    existing_draft = _open_draft(db, doc.id)
    if existing_draft is not None:
        raise HTTPException(
            status_code=409,
            detail="An open draft already exists for this document.",
        )

    published = _current_published(doc, db)
    prev_version = published.version_number if published else None
    kind = "draft"
    version_number = next_version_number(prev_version, kind=kind)

    new_draft = WorldGuideVersion(
        id=str(uuid4()),
        document_id=doc.id,
        version_number=version_number,
        status="draft",
        effective_date=published.effective_date if (published and body.carry_over_content) else None,
        why_this_exists=(published.why_this_exists if published and body.carry_over_content else None),
        what_this_covers=(published.what_this_covers if published and body.carry_over_content else None),
        main_content=(published.main_content if published and body.carry_over_content else None),
        whats_changed=None,
        last_edited_by_user_id=admin.id,
    )
    db.add(new_draft)
    db.flush()

    db.commit()
    return get_document(doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# PATCH /versions/{id}  —  edit draft content
# ---------------------------------------------------------------------------


@router.patch("/versions/{version_id}", response_model=VersionDetail)
def update_version(
    version_id: str,
    body: UpdateVersionRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VersionDetail:
    version = _load_version(db, version_id)
    if version.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft versions can be edited. Create a new draft to change published content.",
        )
    doc = _load_document(db, version.document_id)

    changed = False
    if body.effective_date is not None:
        version.effective_date = body.effective_date
        changed = True
    for field in ("why_this_exists", "what_this_covers", "main_content", "whats_changed"):
        val = getattr(body, field)
        if val is not None:
            setattr(version, field, val.strip() or None)
            changed = True

    if changed:
        version.last_edited_by_user_id = admin.id
        version.updated_at = datetime.utcnow()
        doc.updated_at = version.updated_at
        _recalculate_reading_time(db, doc)
    db.commit()
    db.refresh(version)
    names = _name_map(
        db, {version.last_edited_by_user_id, version.published_by_user_id}  # type: ignore[arg-type]
    )
    return _version_detail(version, names)


def _recalculate_reading_time(db: Session, doc: WorldGuideDocument) -> None:
    """Refresh the document's reading time based on the currently
    published version if there is one, else the most recent draft."""
    v = _current_published(doc, db) or _open_draft(db, doc.id)
    if v is None:
        doc.reading_time_minutes = None
        return
    doc.reading_time_minutes = estimate_reading_time_minutes(
        v.why_this_exists, v.what_this_covers, v.main_content, v.whats_changed,
    )


# ---------------------------------------------------------------------------
# POST /versions/{id}/publish  —  freeze a draft, make it live
# ---------------------------------------------------------------------------


@router.post("/versions/{version_id}/publish", response_model=DocumentDetail)
def publish_version(
    version_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    version = _load_version(db, version_id)
    if version.status == "published":
        raise HTTPException(status_code=409, detail="This version is already published.")
    if version.status == "archived":
        raise HTTPException(status_code=409, detail="Archived versions cannot be published.")

    doc = _load_document(db, version.document_id)
    if doc.archived_at is not None:
        raise HTTPException(status_code=409, detail="Document is archived.")

    # First publish → 1.0. Subsequent → previous_major.previous_minor+1.
    current_published = _current_published(doc, db)
    if current_published is None:
        new_version_number = "1.0"
    else:
        new_version_number = next_version_number(
            current_published.version_number, kind="publish_next"
        )
    # If the draft's version number is still 0.x we overwrite it on
    # publish; otherwise keep the assigned number.
    if version.version_number.startswith("0."):
        version.version_number = new_version_number
    else:
        # Guarantee uniqueness against the target family too.
        exists = db.query(WorldGuideVersion.id).filter(
            WorldGuideVersion.document_id == doc.id,
            WorldGuideVersion.version_number == version.version_number,
            WorldGuideVersion.id != version.id,
        ).first()
        if exists is not None:
            version.version_number = new_version_number

    now = datetime.utcnow()
    version.status = "published"
    version.published_at = now
    version.published_by_user_id = admin.id
    version.updated_at = now

    # Mark the previously-current published version as archived — kept
    # forever, but not "the" live version any more.
    if current_published is not None and current_published.id != version.id:
        current_published.status = "archived"
        current_published.updated_at = now

    doc.current_version_id = version.id
    doc.updated_at = now
    _recalculate_reading_time(db, doc)

    db.commit()
    return get_document(doc.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /images  —  image upload used by the editor's toolbar
# ---------------------------------------------------------------------------


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@router.post("/images", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user),
) -> dict:
    """Accept an image upload from the World Guide editor and return
    a URL the caller can drop into a Markdown reference.

    Storage: the platform-owned media store under ``uploads/media/
    world-guide/``. Refuses non-image mime types and non-image
    extensions; the shared ``save_media_file`` enforces size limits.
    """
    filename = file.filename or "image"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext or '(none)'}' is not permitted for images.",
        )
    mime = file.content_type or ""
    if not mime.startswith("image/") and mime != "image/svg+xml":
        raise HTTPException(
            status_code=400,
            detail="Only image uploads are permitted here.",
        )
    data = await file.read()
    try:
        _, file_url, media_type, _stored, size = save_media_file(
            data=data,
            original_name=filename,
            mime_type=mime,
            space_slug="world-guide",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if media_type != "image":
        raise HTTPException(
            status_code=400,
            detail="Uploaded file was not recognised as an image.",
        )
    return {"url": file_url, "size": size, "media_type": media_type}
