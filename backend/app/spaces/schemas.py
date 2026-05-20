from datetime import datetime
from pydantic import BaseModel, computed_field, field_validator


class StepResourceResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    resource_type: str
    title: str
    description: str | None
    url: str | None
    file_name: str | None
    file_size: int | None
    mime_type: str | None
    position: int
    is_downloadable: bool
    created_at: datetime


class PathwaySummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    title: str
    description: str | None
    cover_image_url: str | None = None
    status: str
    position: int
    access_type: str = 'free'
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    user_has_access: bool = False


class SpaceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    is_public: bool
    status: str
    timezone: str = 'Australia/Melbourne'
    cover_image_url: str | None = None
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


class SectionWithSteps(BaseModel):
    """A pathway section/module with its nested steps."""

    id: str
    title: str
    position: int
    steps: list[StepSummary]


class PathwayWithSteps(BaseModel):
    """Pathway overview with ordered steps and progress summary."""

    id: str
    slug: str
    title: str
    description: str | None
    cover_image_url: str | None = None
    status: str
    step_count: int
    completed_count: int
    steps: list[StepSummary]
    sections: list[SectionWithSteps] = []
    access_type: str = 'free'
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    user_has_access: bool = False


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
    access_type: str = 'free'
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None


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


class PublicSpaceCard(BaseModel):
    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    cover_image_url: str | None
    is_public: bool
    pathway_count: int
    member_count: int
    creator_name: str | None
    has_upcoming_event: bool
    themes: list[str] = []


# ---------------------------------------------------------------------------
# Step Comments (Questions & discussion)
# ---------------------------------------------------------------------------

class StepCommentAuthor(BaseModel):
    id: str
    name: str | None
    email: str

    @computed_field
    @property
    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]


class StepCommentItem(BaseModel):
    id: str
    body: str
    author: StepCommentAuthor
    created_at: datetime


class StepCommentCreate(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment body cannot be empty.")
        if len(v) > 2000:
            raise ValueError("Comment body exceeds 2000 characters.")
        return v


# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

class NotificationPrefsResponse(BaseModel):
    space_id: str
    space_slug: str
    space_name: str
    # Email
    weekly_digest_email: bool
    daily_digest_email: bool
    admin_broadcast_email: bool
    gathering_reminder_email: bool
    new_post_email: bool
    comment_reply_email: bool
    pathway_comment_email: bool
    new_pathway_email: bool
    # Push (TODO: wire up delivery when push system is implemented)
    push_enabled: bool
    push_gathering_reminders: bool
    push_replies: bool
    push_announcements: bool


class NotificationPrefsUpdate(BaseModel):
    weekly_digest_email: bool | None = None
    daily_digest_email: bool | None = None
    admin_broadcast_email: bool | None = None
    gathering_reminder_email: bool | None = None
    new_post_email: bool | None = None
    comment_reply_email: bool | None = None
    pathway_comment_email: bool | None = None
    new_pathway_email: bool | None = None
    push_enabled: bool | None = None
    push_gathering_reminders: bool | None = None
    push_replies: bool | None = None
    push_announcements: bool | None = None
