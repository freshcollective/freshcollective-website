import re
from datetime import datetime
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


# ---------------------------------------------------------------------------
# Space
# ---------------------------------------------------------------------------

class SpaceUpdateRequest(BaseModel):
    name: str | None = None
    tagline: str | None = None
    description: str | None = None
    is_public: bool | None = None
    status: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Name cannot be empty.")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("draft", "active", "archived"):
            raise ValueError("Invalid status.")
        return v


class SpaceDetail(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    is_public: bool
    status: str


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

class PathwayCreateRequest(BaseModel):
    title: str
    slug: str | None = None
    description: str | None = None
    status: str = "active"
    is_sequential: bool = True

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required.")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("draft", "active", "coming_soon", "archived"):
            raise ValueError("Invalid status.")
        return v


class PathwayUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    is_sequential: bool | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("draft", "active", "coming_soon", "archived"):
            raise ValueError("Invalid status.")
        return v


class PathwayResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    slug: str
    title: str
    description: str | None
    status: str
    is_sequential: bool
    position: int
    step_count: int = 0
    created_at: datetime


class ReorderRequest(BaseModel):
    ids: list[str]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

class StepCreateRequest(BaseModel):
    title: str
    slug: str | None = None
    content_type: str = "text"
    content_body: str | None = None
    content_url: str | None = None
    estimated_minutes: int | None = None
    is_required: bool = True

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required.")
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ("text", "video", "reflection", "exercise", "audio"):
            raise ValueError("Invalid content type.")
        return v


class StepUpdateRequest(BaseModel):
    title: str | None = None
    content_type: str | None = None
    content_body: str | None = None
    content_url: str | None = None
    estimated_minutes: int | None = None
    is_required: bool | None = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("text", "video", "reflection", "exercise", "audio"):
            raise ValueError("Invalid content type.")
        return v


class StepResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    slug: str
    title: str
    content_type: str
    content_body: str | None
    content_url: str | None
    estimated_minutes: int | None
    is_required: bool
    position: int


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class EventCreateRequest(BaseModel):
    title: str
    description: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    location_type: str = "zoom"
    location_url: str | None = None
    recording_url: str | None = None
    is_published: bool = False

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: str) -> str:
        if v not in ("zoom", "in_person", "async_recorded"):
            raise ValueError("Invalid location type.")
        return v


class EventUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location_type: str | None = None
    location_url: str | None = None
    recording_url: str | None = None
    is_published: bool | None = None

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("zoom", "in_person", "async_recorded"):
            raise ValueError("Invalid location type.")
        return v


class EventResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime | None
    location_type: str
    location_url: str | None
    recording_url: str | None
    is_published: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------

class PostCreateRequest(BaseModel):
    post_type: str = "announcement"
    title: str | None = None
    body: str
    is_pinned: bool = False

    @field_validator("post_type")
    @classmethod
    def validate_post_type(cls, v: str) -> str:
        if v not in ("prompt", "reflection", "discussion", "announcement"):
            raise ValueError("Invalid post type.")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Body is required.")
        return v


class PostUpdateRequest(BaseModel):
    post_type: str | None = None
    title: str | None = None
    body: str | None = None
    is_pinned: bool | None = None

    @field_validator("post_type")
    @classmethod
    def validate_post_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("prompt", "reflection", "discussion", "announcement"):
            raise ValueError("Invalid post type.")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Body cannot be empty.")
        return v


class PostManageResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    post_type: str
    title: str | None
    body: str
    is_pinned: bool
    is_visible: bool
    created_at: datetime
    author_name: str = ""
