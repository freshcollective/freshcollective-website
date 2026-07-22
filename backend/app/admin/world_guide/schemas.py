"""Pydantic schemas for the World Guide admin + public surfaces."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.world_guide import (
    DOCUMENT_AUDIENCES,
    DOCUMENT_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


class VersionSummary(BaseModel):
    id: str
    version_number: str
    status: str
    effective_date: date | None
    published_at: datetime | None
    published_by_name: str | None
    last_edited_by_name: str | None
    updated_at: datetime


class VersionDetail(BaseModel):
    id: str
    document_id: str
    version_number: str
    status: str
    effective_date: date | None
    why_this_exists: str | None
    what_this_covers: str | None
    main_content: str | None
    whats_changed: str | None
    published_at: datetime | None
    published_by_name: str | None
    last_edited_by_name: str | None
    created_at: datetime
    updated_at: datetime


class DocumentListRow(BaseModel):
    """Row shape for the admin list page."""
    id: str
    slug: str
    title: str
    category: str
    audience: str
    status: str                # 'draft' | 'published' | 'archived'
    current_version_number: str | None
    effective_date: date | None
    updated_at: datetime
    last_updated_by_name: str | None


class DocumentSummary(BaseModel):
    """Compact shape for the dashboard's recently-updated card."""
    id: str
    slug: str
    title: str
    category: str
    status: str
    current_version_number: str | None
    updated_at: datetime


class DocumentDetail(BaseModel):
    """Full admin editor payload — the document plus every version."""
    id: str
    slug: str
    title: str
    category: str
    audience: str
    summary: str | None
    reading_time_minutes: int | None
    author_name: str | None
    author_user_id: str | None
    archived_at: datetime | None
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[VersionSummary]
    current_draft: VersionDetail | None
    current_published: VersionDetail | None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class WorldGuideOverview(BaseModel):
    """Dashboard top-of-page counts + a small list of recent changes."""
    published_count: int
    draft_count: int
    archived_count: int
    last_published: DocumentSummary | None
    recently_updated: list[DocumentSummary]


# ---------------------------------------------------------------------------
# Write requests
# ---------------------------------------------------------------------------


class CreateDocumentRequest(BaseModel):
    """Create a new document plus its first draft version."""
    title: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1, max_length=128)
    category: str
    audience: str
    summary: str | None = None
    effective_date: date | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in DOCUMENT_CATEGORIES:
            raise ValueError(f"category must be one of {list(DOCUMENT_CATEGORIES)}")
        return v

    @field_validator("audience")
    @classmethod
    def _valid_audience(cls, v: str) -> str:
        if v not in DOCUMENT_AUDIENCES:
            raise ValueError(f"audience must be one of {list(DOCUMENT_AUDIENCES)}")
        return v

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean:
            raise ValueError("slug is required")
        for ch in clean:
            if not (ch.isalnum() or ch in "-_"):
                raise ValueError(
                    "slug may only contain lowercase letters, digits, - and _"
                )
        return clean


class UpdateDocumentRequest(BaseModel):
    """Update document-level metadata. Every field is optional; missing
    fields are left unchanged. Slug + category may still be edited
    while the document is a draft; once anything is published, they
    remain editable but callers should tread carefully as URLs may
    depend on the slug."""
    title: str | None = None
    slug: str | None = Field(default=None, max_length=128)
    category: str | None = None
    audience: str | None = None
    summary: str | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in DOCUMENT_CATEGORIES:
            raise ValueError(f"category must be one of {list(DOCUMENT_CATEGORIES)}")
        return v

    @field_validator("audience")
    @classmethod
    def _valid_audience(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in DOCUMENT_AUDIENCES:
            raise ValueError(f"audience must be one of {list(DOCUMENT_AUDIENCES)}")
        return v

    @field_validator("slug")
    @classmethod
    def _valid_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        clean = v.strip().lower()
        if not clean:
            raise ValueError("slug cannot be empty")
        for ch in clean:
            if not (ch.isalnum() or ch in "-_"):
                raise ValueError(
                    "slug may only contain lowercase letters, digits, - and _"
                )
        return clean


class UpdateVersionRequest(BaseModel):
    """Edit a draft version's content. Missing fields are left
    unchanged. Refused (409) if the version is published — a
    published version is frozen, so callers create a new draft
    version instead."""
    effective_date: date | None = None
    why_this_exists: str | None = None
    what_this_covers: str | None = None
    main_content: str | None = None
    whats_changed: str | None = None


class NewDraftFromCurrentRequest(BaseModel):
    """Create a new draft version by branching from the current
    published version. Optional carry-forward controls let the caller
    decide which sections to prefill."""
    carry_over_content: bool = True


# ---------------------------------------------------------------------------
# Public read models
# ---------------------------------------------------------------------------


class PublicDocumentCard(BaseModel):
    """Card shape for the public World Guide landing page."""
    slug: str
    title: str
    category: str
    audience: str
    summary: str | None
    reading_time_minutes: int | None
    version_number: str
    effective_date: date | None


class PublicRelatedDocument(BaseModel):
    slug: str
    title: str
    category: str


class PublicDocumentDetail(BaseModel):
    """Payload for the individual document page on the public site."""
    slug: str
    title: str
    category: str
    audience: str
    summary: str | None
    reading_time_minutes: int | None
    version_number: str
    effective_date: date | None
    published_at: datetime | None
    updated_at: datetime
    why_this_exists: str | None
    what_this_covers: str | None
    main_content: str | None
    whats_changed: str | None
    related: list[PublicRelatedDocument]
