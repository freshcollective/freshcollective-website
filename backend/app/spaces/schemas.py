from datetime import datetime
from pydantic import BaseModel


class PathwaySummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    title: str
    description: str | None
    cover_image_url: str | None = None
    status: str
    position: int


class SpaceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    is_public: bool
    status: str
    pathways: list[PathwaySummary] = []


class SpaceSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    status: str


class StepSummary(BaseModel):
    """Step within a pathway list — includes current user's completion state."""

    id: str
    slug: str
    title: str
    content_type: str
    estimated_minutes: int | None
    is_required: bool
    position: int
    is_completed: bool


class StepDetail(BaseModel):
    """Full step for the step reading page."""

    id: str
    slug: str
    title: str
    content_type: str
    content_body: str | None
    content_url: str | None
    estimated_minutes: int | None
    is_required: bool
    position: int
    is_completed: bool
    reflection_text: str | None


class PathwayWithSteps(BaseModel):
    """Pathway overview with ordered steps and progress summary."""

    id: str
    slug: str
    title: str
    description: str | None
    status: str
    step_count: int
    completed_count: int
    steps: list[StepSummary]


class CompleteStepRequest(BaseModel):
    reflection_text: str | None = None


class CompleteStepResponse(BaseModel):
    is_completed: bool


class SaveNotesRequest(BaseModel):
    reflection_text: str


class SaveNotesResponse(BaseModel):
    saved: bool


class PathwayProgress(BaseModel):
    """Pathway summary enriched with the current user's completion stats."""

    id: str
    slug: str
    title: str
    description: str | None
    cover_image_url: str | None = None
    status: str
    position: int
    step_count: int
    completed_count: int


class EventSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime | None
    location_type: str


class EventDetail(EventSummary):
    """Full event including join/recording URLs, shown on the detail page."""

    location_url: str | None
    recording_url: str | None


class ContinueResponse(BaseModel):
    space_slug: str
    pathway_slug: str
    pathway_title: str
    step_slug: str
    step_title: str
    all_complete: bool
