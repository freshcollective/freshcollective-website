"""Guides — the admin API.

Every endpoint is guarded by ``get_admin_user``. Guides are written by
the Platform Owner and nobody else; there is no creator-facing path
into this router and no reason for one.

Three design points worth stating where they are implemented.

**Saving never publishes.** ``PATCH`` carries no ``status`` field (see
``schemas.GuideUpdate``), so the only way a Guide goes live is the
explicit ``/publish`` endpoint. A draft cannot be published by a save
that went further than intended.

**Featuring is one action, not two.** Setting ``featured`` clears every
other featured row first, inside the same transaction, so the partial
unique index ``ux_guides_one_featured`` is never violated and the
admin is never told to go and unfeature something else first.

**The body is sanitised on the way in, always.** The editor constrains
what can be produced, but that is a UX constraint — any direct HTTP
call bypasses it. ``sanitize_guide_body`` is the boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.admin.guides.schemas import (
    GuideCreate,
    GuideDetail,
    GuideFeature,
    GuideListRow,
    GuideSettingsRead,
    GuideSettingsUpdate,
    GuideUpdate,
)
from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.core.storage import save_file
from app.models.guide import GUIDE_STATUSES, Guide, GuideSettings
from app.models.user import User
# Borrowed rather than copied: the platform should have one answer to
# "how long is this to read", not a Guides answer and a World Guide
# answer that drift apart. The function is pure and carries no World
# Guide semantics.
from app.models.world_guide import estimate_reading_time_minutes
from app.services.guide_body import has_unservable_image, sanitize_guide_body
from app.services.rich_text import rich_text_to_plain

router = APIRouter(prefix="/api/admin/guides", tags=["guides"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Naive UTC, matching every other ``DateTime(timezone=False)`` here."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load(db: Session, guide_id: str) -> Guide:
    guide = db.query(Guide).filter(Guide.id == guide_id).first()
    if guide is None:
        raise HTTPException(status_code=404, detail="Guide not found.")
    return guide


def _assert_slug_free(db: Session, slug: str, *, exclude_id: str | None = None) -> None:
    """409 rather than a 500 from the unique index.

    Checked here *and* constrained in the database: this gives the
    admin a sentence they can act on, and the index is what actually
    guarantees it under a concurrent save.
    """
    query = db.query(Guide).filter(Guide.slug == slug)
    if exclude_id is not None:
        query = query.filter(Guide.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"The slug '{slug}' is already used by another Guide.",
        )


def _reading_time(body: str | None) -> int:
    """Minutes, counted on the words a reader actually sees.

    The body is HTML, so the tags are stripped first — otherwise
    ``<strong>`` and ``</p>`` would be counted as words and a short
    Guide would claim to be a long one.
    """
    return estimate_reading_time_minutes(rich_text_to_plain(body))


def _detail(guide: Guide) -> GuideDetail:
    return GuideDetail(
        id=guide.id,
        slug=guide.slug,
        title=guide.title,
        standfirst=guide.standfirst,
        body=guide.body,
        category=guide.category,
        hero_image_url=guide.hero_image_url,
        hero_image_alt=guide.hero_image_alt,
        seo_title=guide.seo_title,
        seo_description=guide.seo_description,
        author_name=guide.author_name,
        featured=guide.featured,
        status=guide.status,
        published_at=guide.published_at,
        reading_time_minutes=guide.reading_time_minutes,
        cta_heading=guide.cta_heading,
        cta_text=guide.cta_text,
        cta_label=guide.cta_label,
        cta_href=guide.cta_href,
        created_at=guide.created_at,
        updated_at=guide.updated_at,
    )


def _blank_to_none(value: str | None) -> str | None:
    """An emptied text field means "no value", not an empty string."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _validate_http_url(value: str | None, *, field: str) -> str | None:
    """A navigable web URL, a site-relative path, or nothing.

    Site-relative is permitted because the most likely first CTA
    target is a page on this site. ``javascript:`` and ``data:`` are
    refused: this value becomes the ``href`` of a button rendered on
    a public page.
    """
    cleaned = _blank_to_none(value)
    if cleaned is None:
        return None
    if cleaned.startswith("/") and not cleaned.startswith("//"):
        return cleaned
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        parsed = None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} must be an http(s) URL or a path beginning with '/'."
            ),
        )
    return cleaned


# ---------------------------------------------------------------------------
# Settings — declared before /{guide_id} so the literal path wins
# ---------------------------------------------------------------------------


def _settings_row(db: Session) -> GuideSettings:
    """The one settings row, created if migration 187's seed is gone."""
    row = (
        db.query(GuideSettings)
        .filter(GuideSettings.id == GuideSettings.SINGLETON_ID)
        .first()
    )
    if row is None:
        row = GuideSettings(id=GuideSettings.SINGLETON_ID, starter_kit_url=None)
        db.add(row)
        db.flush()
    return row


@router.get("/settings", response_model=GuideSettingsRead)
def get_settings(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideSettingsRead:
    row = _settings_row(db)
    return GuideSettingsRead(
        starter_kit_url=row.starter_kit_url, updated_at=row.updated_at,
    )


@router.put("/settings", response_model=GuideSettingsRead)
def update_settings(
    body: GuideSettingsUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideSettingsRead:
    """Set or clear the Creator Starter Kit link.

    Clearing it is a first-class action, not an edge case: it is how
    the Starter Kit band on ``/guides`` and the card in every Guide's
    sidebar are taken back down.
    """
    row = _settings_row(db)
    row.starter_kit_url = _validate_http_url(
        body.starter_kit_url, field="starter_kit_url",
    )
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return GuideSettingsRead(
        starter_kit_url=row.starter_kit_url, updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Images — also before /{guide_id}
# ---------------------------------------------------------------------------


#: Matches ``storage.ALLOWED_EXTENSIONS``, which ``save_file``
#: enforces. GIF is absent because that shared list does not carry it,
#: and widening a list every other upload path depends on is not this
#: endpoint's business — WebP covers animation and compresses better.
#:
#: SVG is absent on purpose and would stay absent even if the shared
#: list grew one: an SVG is a document that can carry script, and
#: these render on public marketing pages rather than behind a login.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

#: Guide images get their own storage prefix and their own public read
#: route (``serve_guide_image``). They used to go through
#: ``save_media_file(space_slug="guides")``, which produced
#: ``media/guides/…`` — a key the uploads authoriser reads as
#: "the Asset Library of a Collective slugged *guides*". There is no
#: such Collective, so every Guide image 404'd for everyone including
#: administrators; and had anyone ever registered that slug, Guide
#: artwork would have quietly fallen under their Collective's
#: membership rules.
GUIDE_IMAGE_PREFIX = "guide-images"


@router.post("/images", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user),
) -> dict:
    """Accept a hero or inline image and return a URL to reference.

    Writes to the ``guide-images/`` prefix, which ``save_file`` routes
    to Cloudflare R2 whenever the ``R2_*`` variables are set and to
    the local upload directory otherwise, returning a same-origin
    ``/api/uploads/…`` URL either way.

    Admin-only, like every other write here. The matching *read* is
    deliberately public — see ``serve_guide_image``.
    """
    filename = file.filename or "image"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{ext or '(none)'}' is not permitted. "
                "Use PNG, JPG or WebP."
            ),
        )
    mime = file.content_type or ""
    if not mime.startswith("image/"):
        raise HTTPException(
            status_code=400, detail="Only image uploads are permitted here.",
        )
    data = await file.read()
    try:
        rel_path, _resource_type, size = save_file(
            data=data,
            original_name=filename,
            mime_type=mime,
            subdir=GUIDE_IMAGE_PREFIX,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"url": f"/api/uploads/{rel_path}", "size": size, "media_type": "image"}


# ---------------------------------------------------------------------------
# List and create
# ---------------------------------------------------------------------------


@router.get("", response_model=list[GuideListRow])
def list_guides(
    status: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[GuideListRow]:
    """Every Guide, drafts included. Newest work first.

    Ordered by ``updated_at`` rather than ``published_at`` because
    this is a work list: the Guide you were last editing belongs at
    the top whether or not it has ever been published.
    """
    if status is not None and status not in GUIDE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {list(GUIDE_STATUSES)}",
        )
    query = db.query(Guide)
    if status is not None:
        query = query.filter(Guide.status == status)
    rows = query.order_by(Guide.updated_at.desc()).all()
    return [
        GuideListRow(
            id=g.id,
            slug=g.slug,
            title=g.title,
            category=g.category,
            status=g.status,
            featured=g.featured,
            published_at=g.published_at,
            updated_at=g.updated_at,
            reading_time_minutes=g.reading_time_minutes,
        )
        for g in rows
    ]


@router.post("", response_model=GuideDetail, status_code=201)
def create_guide(
    body: GuideCreate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    """A new Guide, always as a draft.

    Created with the minimum — title, slug, category — so the editor
    has somewhere to save into rather than holding a whole article in
    browser state before anything exists.
    """
    _assert_slug_free(db, body.slug)
    guide = Guide(
        id=str(uuid4()),
        slug=body.slug,
        title=body.title.strip(),
        standfirst="",
        body="",
        category=body.category,
        status="draft",
        reading_time_minutes=1,
    )
    db.add(guide)
    db.commit()
    db.refresh(guide)
    return _detail(guide)


# ---------------------------------------------------------------------------
# One Guide
# ---------------------------------------------------------------------------


@router.get("/{guide_id}", response_model=GuideDetail)
def get_guide(
    guide_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    return _detail(_load(db, guide_id))


@router.patch("/{guide_id}", response_model=GuideDetail)
def update_guide(
    guide_id: str,
    body: GuideUpdate,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    """Save. Never publishes — there is no ``status`` to send."""
    guide = _load(db, guide_id)
    fields = body.model_dump(exclude_unset=True)

    if "slug" in fields and fields["slug"] != guide.slug:
        _assert_slug_free(db, fields["slug"], exclude_id=guide.id)
        guide.slug = fields["slug"]

    for name in ("title", "standfirst", "author_name", "category"):
        if name in fields and fields[name] is not None:
            setattr(guide, name, fields[name].strip() if isinstance(
                fields[name], str) else fields[name])

    if "body" in fields:
        raw = fields["body"] or ""
        if has_unservable_image(raw):
            raise HTTPException(
                status_code=400,
                detail=(
                    "An image in the body points somewhere this site cannot "
                    "load from. Upload the image here instead of linking to "
                    "it elsewhere."
                ),
            )
        guide.body = sanitize_guide_body(raw) or ""
        guide.reading_time_minutes = _reading_time(guide.body)

    for name in ("hero_image_url", "hero_image_alt", "seo_title",
                 "seo_description", "cta_heading", "cta_text", "cta_label"):
        if name in fields:
            setattr(guide, name, _blank_to_none(fields[name]))

    if "cta_href" in fields:
        guide.cta_href = _validate_http_url(fields["cta_href"], field="cta_href")

    # The database enforces both of these too; raising here means the
    # admin reads a sentence instead of an IntegrityError.
    if guide.hero_image_url and not (guide.hero_image_alt or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A hero image needs alt text describing it.",
        )
    cta_parts = [guide.cta_heading, guide.cta_text, guide.cta_label, guide.cta_href]
    if any(cta_parts) and not all(cta_parts):
        raise HTTPException(
            status_code=400,
            detail=(
                "A call to action needs all four of heading, text, button "
                "label and link — or none of them."
            ),
        )

    guide.updated_at = _now()
    db.commit()
    db.refresh(guide)
    return _detail(guide)


@router.delete("/{guide_id}", status_code=204)
def delete_guide(
    guide_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> None:
    """Hard delete. The admin UI confirms first."""
    guide = _load(db, guide_id)
    db.delete(guide)
    db.commit()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post("/{guide_id}/publish", response_model=GuideDetail)
def publish_guide(
    guide_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    """Make a Guide public.

    ``published_at`` is set once and kept. Unpublishing and
    republishing does not move the date a reader was first shown this
    article, which is the date the structured data reports.
    """
    guide = _load(db, guide_id)
    if not guide.standfirst.strip() or not guide.body.strip():
        raise HTTPException(
            status_code=400,
            detail="A Guide needs a standfirst and a body before it is published.",
        )
    guide.status = "published"
    if guide.published_at is None:
        guide.published_at = _now()
    guide.updated_at = _now()
    db.commit()
    db.refresh(guide)
    return _detail(guide)


@router.post("/{guide_id}/unpublish", response_model=GuideDetail)
def unpublish_guide(
    guide_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    """Back to draft. The public pages 404 it immediately."""
    guide = _load(db, guide_id)
    guide.status = "draft"
    guide.updated_at = _now()
    db.commit()
    db.refresh(guide)
    return _detail(guide)


@router.post("/{guide_id}/feature", response_model=GuideDetail)
def feature_guide(
    guide_id: str,
    body: GuideFeature,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> GuideDetail:
    """Feature this Guide, or unfeature it.

    Featuring clears every other featured row first, in the same
    transaction and flushed before this row is set — the partial
    unique index would otherwise reject the write, and "unfeature the
    other one first" is not a thing anyone should have to do by hand.
    """
    guide = _load(db, guide_id)
    if body.featured:
        others = (
            db.query(Guide)
            .filter(Guide.featured.is_(True), Guide.id != guide.id)
            .all()
        )
        for other in others:
            other.featured = False
            other.updated_at = _now()
        db.flush()
    guide.featured = body.featured
    guide.updated_at = _now()
    db.commit()
    db.refresh(guide)
    return _detail(guide)
