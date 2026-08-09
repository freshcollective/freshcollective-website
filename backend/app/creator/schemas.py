import re
from datetime import date, datetime
from pydantic import BaseModel, field_validator

ALLOWED_THEMES: set[str] = {
    "Inner Work", "Wellbeing", "Creativity", "Leadership", "Reflection",
    "Movement", "Business", "Spirituality", "Relationships", "Parenting",
}


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

class PlaceRef(BaseModel):
    """A compact view of a Geographic Location on the response side.

    Included in SpaceDetail so the Creator UI can render the current
    Primary Location without a second round trip. Not editable
    directly — Creators change the link via connection_style +
    primary_place_id on the update request.
    """

    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    region: str | None = None
    country_code: str


class SpaceCreateRequest(BaseModel):
    name: str
    tagline: str | None = None
    description: str | None = None
    about_content: str | None = None
    is_public: bool = False
    themes: list[str] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty.")
        if len(v) > 200:
            raise ValueError("Name must be 200 characters or fewer.")
        return v

    @field_validator("themes")
    @classmethod
    def validate_themes(cls, v: list[str]) -> list[str]:
        invalid = [t for t in v if t not in ALLOWED_THEMES]
        if invalid:
            raise ValueError(f"Invalid themes: {invalid}")
        return v


ALLOWED_PRICING_TYPES: set[str] = {
    "free", "paid_one_time", "paid_monthly", "paid_annual", "invite_only", "coming_soon",
}


class SpaceUpdateRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    tagline: str | None = None
    description: str | None = None
    about_content: str | None = None
    is_public: bool | None = None
    status: str | None = None
    timezone: str | None = None
    themes: list[str] | None = None
    # Public pricing display
    pricing_type: str | None = None
    pricing_amount_cents: int | None = None
    pricing_currency: str | None = None
    pricing_note: str | None = None
    has_paid_internal_content: bool | None = None
    included_access_summary: str | None = None
    paid_content_summary: str | None = None
    guidance_start_title: str | None = None
    guidance_start_body: str | None = None
    guidance_focus_title: str | None = None
    guidance_focus_body: str | None = None
    guidance_links_title: str | None = None
    guidance_links_body: str | None = None
    # Place & Feel — Discovery pillar. See
    # docs/foundations/discovery-connection-belonging-location-model.md.
    # connection_style is one of 'online' | 'in_person' | 'both';
    # primary_place_id is the Place row a Geographic Location resolves
    # to (created via /api/places/resolve). Passing primary_place_id=""
    # clears the current Place link. When connection_style is 'online',
    # the backend clears the link regardless of what primary_place_id
    # was sent.
    connection_style: str | None = None
    primary_place_id: str | None = None

    @field_validator("connection_style")
    @classmethod
    def validate_connection_style(cls, v: str | None) -> str | None:
        if v is not None and v not in ("online", "in_person", "both"):
            raise ValueError("connection_style must be one of: online, in_person, both.")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Name cannot be empty.")
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip().lower()
            if not v:
                raise ValueError("Slug cannot be empty.")
            if len(v) > 80:
                raise ValueError("Slug must be 80 characters or fewer.")
            if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', v):
                raise ValueError(
                    "Slug must contain only lowercase letters, numbers, and hyphens, "
                    "and cannot start or end with a hyphen."
                )
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("draft", "active", "archived"):
            raise ValueError("Invalid status.")
        return v

    @field_validator("pricing_type")
    @classmethod
    def validate_pricing_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_PRICING_TYPES:
            raise ValueError(f"Invalid pricing_type. Must be one of: {sorted(ALLOWED_PRICING_TYPES)}")
        return v

    @field_validator("themes")
    @classmethod
    def validate_themes(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            invalid = [t for t in v if t not in ALLOWED_THEMES]
            if invalid:
                raise ValueError(f"Invalid themes: {invalid}")
        return v


class SpaceDetail(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    slug: str
    name: str
    tagline: str | None
    description: str | None
    about_content: str | None = None
    is_public: bool
    status: str
    timezone: str = 'Australia/Melbourne'
    cover_image_url: str | None = None
    logo_url: str | None = None
    themes: list[str] = []
    pricing_type: str = 'free'
    pricing_amount_cents: int | None = None
    pricing_currency: str = 'AUD'
    pricing_note: str | None = None
    has_paid_internal_content: bool = False
    included_access_summary: str | None = None
    paid_content_summary: str | None = None
    derived_has_paid_internal_content: bool = False
    guidance_start_title: str | None = None
    guidance_start_body: str | None = None
    guidance_focus_title: str | None = None
    guidance_focus_body: str | None = None
    guidance_links_title: str | None = None
    guidance_links_body: str | None = None
    # Atlas v1.2 identity fields — Location provides artwork, Colour Palette
    # drives the collective's visual interface, atmosphere + identity + welcome
    # personalise the experience. Legacy collectives (created before v1.2)
    # may have NULLs in the underlying columns; the pre-validator below
    # coerces those NULLs into safe defaults so response shape stays stable.
    location: dict | None = None
    location_id: str | None = None
    colour_palette: dict | None = None
    colour_palette_key: str | None = None
    atmosphere_keys: list[str] = []
    identity_statement: str | None = None
    welcome_message: str | None = None
    # When set, this space auto-grants membership to every user whose
    # ``users.role`` matches this value (see Space.auto_grant_role in
    # models/platform.py). Read-only in the API — never editable via
    # Creator Studio. Frontend uses this to render the locked
    # "access managed automatically" Settings panel.
    auto_grant_role: str | None = None
    # Place & Feel — Discovery pillar. connection_style is set by the
    # Creator through Place & Feel; primary_place is the resolved
    # Geographic Location (null when connection_style is 'online').
    connection_style: str = 'online'
    primary_place: "PlaceRef | None" = None

    @field_validator("atmosphere_keys", mode="before")
    @classmethod
    def _coerce_atmosphere_keys(cls, v: object) -> list[str]:
        # Legacy rows may store None where the migration expected a list.
        if v is None:
            return []
        return v  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Space Resources (collective-level)
# ---------------------------------------------------------------------------

ALLOWED_RESOURCE_TYPES: set[str] = {
    "link", "file", "replay", "guide", "template", "audio", "video", "other",
}


ALLOWED_RESOURCE_STATUSES: set[str] = {"draft", "published", "archived"}


class ResourceCreateRequest(BaseModel):
    title: str
    description: str | None = None
    resource_type: str = "link"
    url: str | None = None
    status: str = "draft"
    sort_order: int = 0
    # Unified Library folder — optional. Null → "All items".
    folder_id: str | None = None
    # v2 multi-pathway. Empty/missing list = General. Legacy `scope` and
    # `pathway_id` fields are still accepted from old clients but ignored
    # whenever `pathway_ids` is provided; route writes both old + new for
    # back-compat (see creator/routes.py).
    pathway_ids: list[str] | None = None
    # Legacy (kept for back-compat with older API consumers)
    scope: str = "general"
    pathway_id: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required.")
        if len(v) > 300:
            raise ValueError("Title must be 300 characters or fewer.")
        return v

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        if v not in ALLOWED_RESOURCE_TYPES:
            raise ValueError(f"Invalid resource_type. Must be one of: {sorted(ALLOWED_RESOURCE_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ALLOWED_RESOURCE_STATUSES:
            raise ValueError(f"Status must be one of: {sorted(ALLOWED_RESOURCE_STATUSES)}.")
        return v


class ResourceUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    resource_type: str | None = None
    url: str | None = None
    status: str | None = None
    sort_order: int | None = None
    # Unified Library folder. Explicit ``null`` moves to "All items";
    # omitting the field leaves the folder unchanged. Handler uses
    # ``model_fields_set`` to distinguish.
    folder_id: str | None = None
    pathway_ids: list[str] | None = None
    # Legacy (kept for back-compat)
    scope: str | None = None
    pathway_id: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty.")
        return v

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_RESOURCE_TYPES:
            raise ValueError(f"Invalid resource_type. Must be one of: {sorted(ALLOWED_RESOURCE_TYPES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_RESOURCE_STATUSES:
            raise ValueError(f"Status must be one of: {sorted(ALLOWED_RESOURCE_STATUSES)}.")
        return v


class ResourcePathwayInfo(BaseModel):
    """Minimal pathway info for resource badges in Creator Studio."""
    model_config = {"from_attributes": True}
    id: str
    slug: str
    title: str


class ResourceResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    title: str
    description: str | None
    resource_type: str
    url: str | None
    file_name: str | None
    file_size: int | None
    status: str
    sort_order: int
    # Unified Library folder — nullable ("All items").
    folder_id: str | None = None
    # v2: list of pathways this resource belongs to. Empty list = General.
    pathways: list[ResourcePathwayInfo] = []
    # Count of references from step + about blocks. Computed server-side
    # in a single grouped query (see creator/routes.py).
    usage_count: int = 0
    # Legacy back-compat fields (still populated, but new UI uses `pathways`)
    scope: str = "general"
    pathway_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ResourceUsageReference(BaseModel):
    """One place where a resource is referenced."""
    kind: str  # "step_block" | "about_block"
    pathway_id: str | None = None
    pathway_title: str | None = None
    pathway_slug: str | None = None
    step_id: str | None = None
    step_title: str | None = None
    step_slug: str | None = None
    href: str | None = None  # creator-studio link to the location


class ResourceUsageResponse(BaseModel):
    resource_id: str
    references: list[ResourceUsageReference]


# ---------------------------------------------------------------------------
# Library — one creator surface over the two asset stores
# ---------------------------------------------------------------------------


class LibraryFolderResponse(BaseModel):
    """One folder in the unified Library."""

    model_config = {"from_attributes": True}
    id: str
    name: str
    position: int
    item_count: int = 0


class LibraryFolderCreateRequest(BaseModel):
    name: str
    position: int | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Folder name is required.")
        if len(v) > 200:
            raise ValueError("Folder name must be 200 characters or fewer.")
        return v


class LibraryFolderUpdateRequest(BaseModel):
    name: str | None = None
    position: int | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Folder name cannot be empty.")
        if len(v) > 200:
            raise ValueError("Folder name must be 200 characters or fewer.")
        return v


class LibraryFileInfo(BaseModel):
    """Shape for a ``kind='file'`` Library item — the file portion.

    Files live in ``creator_media_assets``; legacy file rows in
    ``space_resources`` (uploaded via the pre-Library Resources page)
    are also surfaced here with derived fields so the creator sees
    every historical file alongside new uploads.
    """

    url: str
    mime_type: str | None = None
    size_bytes: int | None = None
    original_filename: str | None = None
    media_type: str  # image | video | audio | document | other
    extension: str | None = None


class LibraryLinkInfo(BaseModel):
    """Shape for a ``kind='link'`` Library item — the link portion."""

    url: str
    resource_type: str  # 'link' for new items; legacy values preserved


class LibraryItem(BaseModel):
    """One entry in the unified Library list.

    ``kind`` discriminates the two backing tables; the creator never
    sees this — it drives which of ``file`` / ``link`` is populated.
    """

    kind: str  # 'file' | 'link'
    id: str
    title: str
    description: str | None = None
    folder_id: str | None = None
    used_in_count: int = 0
    file: LibraryFileInfo | None = None
    link: LibraryLinkInfo | None = None
    created_at: datetime
    updated_at: datetime


class LibraryListResponse(BaseModel):
    items: list[LibraryItem]
    total: int
    limit: int
    offset: int
    # Always returned so the sidebar can render without a second
    # round trip. Cheap — one query per Collective.
    folders: list[LibraryFolderResponse] = []


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

class PathwayCreateRequest(BaseModel):
    title: str
    slug: str | None = None
    description: str | None = None
    practice_body: str | None = None
    status: str = "draft"
    is_sequential: bool = True
    access_type: str = "free"
    price_cents: int | None = None
    # Free / included pathways don't carry a currency; the frontend
    # explicitly sends null for these, and the `pathways.currency`
    # column is nullable in the DB.
    currency: str | None = "AUD"
    billing_interval: str | None = None
    # When True (default), a 🛤 pathway-typed Conversation Channel is
    # created alongside the Pathway. Members are auto-joined by their
    # active Enrollment through the permissions layer.
    create_channel: bool = True

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

    @field_validator("access_type")
    @classmethod
    def validate_access_type(cls, v: str) -> str:
        if v not in ("free", "included", "one_time", "subscription"):
            raise ValueError("Invalid access type.")
        return v


class PathwayUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    practice_body: str | None = None
    status: str | None = None
    is_sequential: bool | None = None
    access_type: str | None = None
    pricing_mode: str | None = None
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    cover_image_url: str | None = None
    pathway_type: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("draft", "active", "coming_soon", "archived"):
            raise ValueError("Invalid status.")
        return v

    @field_validator("access_type")
    @classmethod
    def validate_access_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("free", "included", "one_time", "subscription", "included_with_offer"):
            raise ValueError("Invalid access type.")
        return v

    @field_validator("pricing_mode")
    @classmethod
    def validate_pricing_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in ("legacy", "payment_options"):
            raise ValueError("pricing_mode must be 'legacy' or 'payment_options'.")
        return v

    @field_validator("pathway_type")
    @classmethod
    def validate_pathway_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("guided_experience", "knowledge_guide"):
            raise ValueError(
                "pathway_type must be 'guided_experience' or 'knowledge_guide'."
            )
        return v


class PathwayResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    slug: str
    title: str
    description: str | None
    practice_body: str | None = None
    cover_image_url: str | None = None
    status: str
    access_type: str = "free"
    pricing_mode: str = "legacy"
    price_cents: int | None = None
    currency: str = "AUD"
    billing_interval: str | None = None
    is_sequential: bool
    pathway_type: str = "guided_experience"
    position: int
    step_count: int = 0
    updated_at: datetime | None = None
    created_at: datetime


class ReorderRequest(BaseModel):
    ids: list[str]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

class SectionCreateRequest(BaseModel):
    title: str
    banner_image_url: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required.")
        if len(v) > 200:
            raise ValueError("Title must be 200 characters or fewer.")
        return v


class SectionUpdateRequest(BaseModel):
    title: str | None = None
    banner_image_url: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty.")
        return v


class SectionResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    pathway_id: str
    title: str
    position: int
    banner_image_url: str | None = None
    created_at: datetime


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
    section_id: str | None = None
    reflection_enabled: bool = True
    discussion_enabled: bool = True
    banner_image_url: str | None = None

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


_VALID_RELEASE_TYPES = {
    "immediate", "days_after_enrollment", "fixed_date", "after_previous", "manual",
}
_VALID_PREVIOUS_STATES = {"completed", "started"}


class StepUpdateRequest(BaseModel):
    title: str | None = None
    content_type: str | None = None
    content_body: str | None = None
    content_url: str | None = None
    estimated_minutes: int | None = None
    is_required: bool | None = None
    section_id: str | None = None
    reflection_enabled: bool | None = None
    discussion_enabled: bool | None = None
    banner_image_url: str | None = None
    # Drip scheduling — see app.services.pathway_release for the rules.
    release_type: str | None = None
    release_offset_days: int | None = None
    release_at: datetime | None = None
    release_timezone: str | None = None
    release_previous_state: str | None = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("text", "video", "reflection", "exercise", "audio"):
            raise ValueError("Invalid content type.")
        return v

    @field_validator("release_type")
    @classmethod
    def validate_release_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_RELEASE_TYPES:
            raise ValueError("Invalid release type.")
        return v

    @field_validator("release_previous_state")
    @classmethod
    def validate_release_previous_state(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_PREVIOUS_STATES:
            raise ValueError("Invalid release_previous_state.")
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
    section_position: int | None = None
    section_id: str | None = None
    reflection_enabled: bool = True
    discussion_enabled: bool = True
    banner_image_url: str | None = None
    # Drip scheduling — echoed so the editor form can populate itself.
    release_type: str = "immediate"
    release_offset_days: int | None = None
    release_at: datetime | None = None
    release_timezone: str | None = None
    release_previous_state: str = "completed"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class RecurrenceRequest(BaseModel):
    """Describes a weekly recurrence pattern for bulk event creation."""
    pattern: str = "weekly"  # only "weekly" supported for now
    days_of_week: list[int]  # 0=Mon, 1=Tue, ..., 6=Sun
    series_label: str | None = None
    end_after_n: int | None = None       # stop after N total occurrences
    repeat_until: datetime | None = None  # stop on/before this date

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        if v not in ("weekly",):
            raise ValueError("Only 'weekly' recurrence is supported.")
        return v

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, v: list[int]) -> list[int]:
        for d in v:
            if d < 0 or d > 6:
                raise ValueError("days_of_week values must be 0 (Mon) to 6 (Sun).")
        if not v:
            raise ValueError("At least one day of the week is required.")
        return sorted(set(v))


class BulkEventCreateResponse(BaseModel):
    created_count: int
    series_id: str


class EventCreateRequest(BaseModel):
    title: str
    description: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    # Legacy `location_type` is preserved for the older UI + iCal
    # generator. New surfaces should send `attendance_format` +
    # `venue_*` / `location_url` instead.
    location_type: str = "zoom"
    location_url: str | None = None
    recording_url: str | None = None
    is_published: bool = False
    is_public: bool = False
    requires_booking: bool = False
    capacity: int | None = None
    booking_closes_at: datetime | None = None
    booking_note: str | None = None
    thumbnail_url: str | None = None
    recurrence: RecurrenceRequest | None = None
    # Gatherings 2.0 vocabulary — see services/gathering_types.py.
    gathering_type: str = "other"
    attendance_format: str = "online"
    venue_name: str | None = None
    venue_address: str | None = None
    access_instructions: str | None = None
    booking_access_type: str = "included_with_collective"
    booking_required_pathway_id: str | None = None
    # Standalone paid Gatherings (booking_access_type='paid_separately').
    # Draft-safe (nullable) — validation that publish requires both is
    # applied server-side, not by field-level required.
    ticket_price_cents: int | None = None
    ticket_currency: str | None = None
    # When True (default), a 📅 gathering-typed Conversation Channel is
    # created alongside the Event. Confirmed attendees are auto-joined
    # by their EventBooking through the permissions layer. For bulk
    # (recurring) creation this flag is ignored — the series shares
    # a single channel via the series-level flag if we add one later.
    create_channel: bool = True

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: str) -> str:
        if v not in ("zoom", "in_person", "async_recorded"):
            raise ValueError("Invalid location type.")
        return v

    @field_validator("gathering_type")
    @classmethod
    def _validate_gathering_type(cls, v: str) -> str:
        from app.services.gathering_types import GATHERING_TYPE_VALUES
        if v not in GATHERING_TYPE_VALUES:
            raise ValueError("Invalid gathering type.")
        return v

    @field_validator("attendance_format")
    @classmethod
    def _validate_attendance_format(cls, v: str) -> str:
        from app.services.gathering_types import ATTENDANCE_FORMAT_VALUES
        if v not in ATTENDANCE_FORMAT_VALUES:
            raise ValueError("Invalid attendance format.")
        return v

    @field_validator("booking_access_type")
    @classmethod
    def _validate_access_type(cls, v: str) -> str:
        from app.services.gathering_types import normalise_access_type, ACCESS_TYPE_VALUES
        normalised = normalise_access_type(v)
        if normalised not in ACCESS_TYPE_VALUES:
            raise ValueError("Invalid access type.")
        return normalised


class EventUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location_type: str | None = None
    location_url: str | None = None
    recording_url: str | None = None
    is_published: bool | None = None
    is_public: bool | None = None
    requires_booking: bool | None = None
    capacity: int | None = None
    booking_closes_at: datetime | None = None
    booking_note: str | None = None
    thumbnail_url: str | None = None
    gathering_type: str | None = None
    attendance_format: str | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    access_instructions: str | None = None
    booking_access_type: str | None = None
    booking_required_pathway_id: str | None = None
    # Standalone paid Gatherings — nullable on update; edit-lock and
    # publish validation are enforced in the route handler.
    ticket_price_cents: int | None = None
    ticket_currency: str | None = None

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("zoom", "in_person", "async_recorded"):
            raise ValueError("Invalid location type.")
        return v

    @field_validator("gathering_type")
    @classmethod
    def _validate_gathering_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.services.gathering_types import GATHERING_TYPE_VALUES
        if v not in GATHERING_TYPE_VALUES:
            raise ValueError("Invalid gathering type.")
        return v

    @field_validator("attendance_format")
    @classmethod
    def _validate_attendance_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.services.gathering_types import ATTENDANCE_FORMAT_VALUES
        if v not in ATTENDANCE_FORMAT_VALUES:
            raise ValueError("Invalid attendance format.")
        return v

    @field_validator("booking_access_type")
    @classmethod
    def _validate_access_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.services.gathering_types import normalise_access_type, ACCESS_TYPE_VALUES
        normalised = normalise_access_type(v)
        if normalised not in ACCESS_TYPE_VALUES:
            raise ValueError("Invalid access type.")
        return normalised


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
    is_public: bool = False
    requires_booking: bool = False
    capacity: int | None = None
    booking_closes_at: datetime | None = None
    booking_note: str | None = None
    booked_count: int = 0
    attended_count: int = 0
    no_show_count: int = 0
    thumbnail_url: str | None = None
    status: str = "active"
    recurrence_series_id: str | None = None
    recurrence_label: str | None = None
    recurrence_index: int | None = None
    recurrence_total: int | None = None
    gathering_type: str = "other"
    attendance_format: str = "online"
    venue_name: str | None = None
    venue_address: str | None = None
    access_instructions: str | None = None
    booking_access_type: str = "included_with_collective"
    booking_required_pathway_id: str | None = None
    # Standalone paid Gatherings — always present on the wire (null for
    # non-paid access types) so the creator UI doesn't need to branch.
    ticket_price_cents: int | None = None
    ticket_currency: str | None = None
    # Ticket-sales aggregate, computed by `services/ticket_summary.py`.
    # Null for non-paid Gatherings to keep the payload small.
    ticket_sales: "TicketSalesSummaryOut | None" = None
    created_at: datetime


class TicketSalesSummaryOut(BaseModel):
    """Creator-facing aggregate for a standalone paid Gathering.

    Mirror of `services.ticket_summary.TicketSalesSummary`. Never contains
    Stripe internal identifiers or per-attendee data.
    """
    status: str
    paid_ticket_count: int = 0
    complimentary_count: int = 0
    confirmed_booking_count: int = 0
    active_hold_count: int = 0
    remaining_capacity: int | None = None
    gross_ticket_revenue_cents: int = 0
    revenue_currency: str | None = None
    has_completed_ticket_sales: bool = False
    has_active_payment_holds: bool = False
    sales_enabled: bool = False
    stripe_mode: str = "test"


class BookedMemberItem(BaseModel):
    booking_id: str
    user_id: str
    name: str | None
    email: str
    booked_at: datetime
    status: str
    source: str | None = None
    note: str | None = None
    attendance_status: str | None = None
    attendance_marked_at: datetime | None = None
    credits_used: int = 0
    access_pass_id: str | None = None
    # Stage 3 additions — creator-facing, DB-authoritative labelling for
    # standalone paid Gatherings. Non-paid Gatherings still get an
    # access_source label ("Included" / "Creator added" / etc.) but
    # amount_paid_cents/currency/purchased_at stay null.
    access_source: str = "Complimentary"
    amount_paid_cents: int | None = None
    currency: str | None = None
    purchased_at: datetime | None = None


class ManualBookingRequest(BaseModel):
    user_id: str
    note: str | None = None
    use_pass: bool = False          # if True: find active pass, enforce caps, deduct credit
    access_pass_id: str | None = None  # optional: use specific pass; auto-detected if omitted


class MemberActivePassOut(BaseModel):
    pass_id: str
    option_name: str | None
    pathway_title: str | None
    total_credits: int | None
    used_credits: int
    remaining_credits: int | None
    credits_per_week: int | None
    valid_from: str | None = None  # ISO date string
    valid_until: str | None = None  # ISO date string
    status: str


class RecurringBookingRequest(BaseModel):
    event_ids: list[str]
    use_pass: bool = True
    access_pass_id: str | None = None
    note: str | None = None


class RecurringBookingItem(BaseModel):
    event_id: str
    event_title: str
    starts_at: str
    booking_id: str | None = None
    status: str  # "booked" | "skipped"
    reason: str | None = None


class PassSummary(BaseModel):
    pass_id: str
    option_name: str | None
    total_credits: int | None
    used_credits: int
    remaining_credits: int | None
    credits_per_week: int | None


class RecurringBookingResponse(BaseModel):
    booked: list[RecurringBookingItem]
    skipped: list[RecurringBookingItem]
    pass_summary: PassSummary | None = None


class AttendanceUpdateRequest(BaseModel):
    status: str  # 'attended' | 'no_show' | 'pending'


class CreatorMemberItem(BaseModel):
    id: str
    display_name: str
    email: str
    space_role: str
    joined_at: datetime
    is_creator: bool = False


class MemberBookingItem(BaseModel):
    booking_id: str
    event_id: str
    event_title: str
    event_starts_at: datetime
    event_location_type: str
    booking_status: str
    attendance_status: str | None = None
    booked_at: datetime


class AddMemberRequest(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None          # legacy / fallback
    role: str = "learner"
    note: str | None = None
    payment_option_id: str | None = None
    payment_status: str = "unpaid"


class AddMemberResponse(BaseModel):
    result: str  # 'added_as_member' | 'pending_invite_created' | 'already_member' | 'invite_already_pending'
    message: str


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------

class PostCreateRequest(BaseModel):
    post_type: str = "announcement"
    title: str | None = None
    body: str
    is_pinned: bool = False
    image_url: str | None = None

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


_VALID_POST_TYPES = {
    "reflection", "question", "poll", "announcement", "celebration", "share",
    # Legacy — round-trip cleanly.
    "prompt", "discussion",
}


class PostUpdateRequest(BaseModel):
    post_type: str | None = None
    title: str | None = None
    body: str | None = None
    is_pinned: bool | None = None
    image_url: str | None = None
    # Community Phase 2 — reschedule support. `scheduled_for=None` on an
    # already-scheduled post transitions it back to immediate publication;
    # a datetime in the future keeps / updates the schedule.
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None

    @field_validator("post_type")
    @classmethod
    def validate_post_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_POST_TYPES:
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
    image_url: str | None = None
    is_pinned: bool
    is_visible: bool
    created_at: datetime
    author_name: str = ""
    # Community Phase 2 — scheduling state, so the creator UI can render
    # scheduled cards without a second lookup.
    publication_status: str = "published"
    scheduled_for: datetime | None = None
    scheduling_timezone: str | None = None
    published_at: datetime | None = None
    # Channels — surfaced so the Queue timeline can label rows by
    # destination Channel and flag archived-destination rows.
    channel_id: str | None = None
    channel_slug: str | None = None
    channel_name: str | None = None
    channel_archived: bool = False


# ---------------------------------------------------------------------------
# Step Resources
# ---------------------------------------------------------------------------

class StepResourceCreateRequest(BaseModel):
    title: str
    description: str | None = None
    resource_type: str = "link"
    url: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required.")
        return v

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        if v not in ("video", "audio", "link"):
            raise ValueError("Invalid resource type. For links use: video, audio, or link.")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required.")
        return v


class StepResourceUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("URL cannot be empty.")
        return v


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


# ---------------------------------------------------------------------------
# Space Invitations
# ---------------------------------------------------------------------------

class InvitationCreateRequest(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None          # legacy / fallback
    role: str = "learner"
    note: str | None = None
    payment_option_id: str | None = None
    payment_status: str = "unpaid"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("learner", "moderator", "creator"):
            raise ValueError("Invalid role. Must be learner, moderator, or creator.")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip() or None
        return v


class InvitationResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    space_id: str
    email: str
    name: str | None
    role: str
    note: str | None
    invited_by_id: str
    token: str
    payment_option_id: str | None = None
    payment_option_name: str | None = None
    payment_status: str = "unpaid"
    sent_at: datetime | None = None
    created_at: datetime


class AccessRequestOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    user_display_name: str
    user_email: str
    status: str                # pending | approved | declined
    message: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Media Library
# ---------------------------------------------------------------------------

class MediaAssetResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    space_id: str
    uploaded_by_user_id: str
    title: str
    description: str | None
    alt_text: str | None = None
    tags: str | None = None
    original_filename: str
    stored_filename: str
    storage_path: str
    file_url: str
    mime_type: str
    media_type: str
    file_size_bytes: int
    extension: str
    status: str
    # Unified Library folder — nullable ("All items").
    folder_id: str | None = None
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime


class MediaAssetUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    alt_text: str | None = None
    tags: str | None = None
    # Unified Library folder. Explicit ``null`` moves the asset to
    # "All items"; omitting the field leaves the folder unchanged.
    # The handler uses ``model_fields_set`` to distinguish "not sent"
    # from "sent as null".
    folder_id: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty.")
            if len(v) > 300:
                raise ValueError("Title must be 300 characters or fewer.")
        return v


class MediaUsageReference(BaseModel):
    """One place where a media asset is referenced."""
    kind: str  # "step_block_image" | "step_block_audio" | "step_block_file" | "about_block_image" | "about_block_audio" | "about_block_file" | "pathway_cover" | "step_banner"
    pathway_id: str | None = None
    pathway_title: str | None = None
    pathway_slug: str | None = None
    step_id: str | None = None
    step_title: str | None = None
    step_slug: str | None = None
    label: str | None = None  # human-readable description of the location


class MediaUsageResponse(BaseModel):
    media_id: str
    references: list[MediaUsageReference]


# ---------------------------------------------------------------------------
# Step Blocks
# ---------------------------------------------------------------------------

VALID_BLOCK_TYPES = (
    "heading", "text", "image", "video_embed", "audio",
    "file_download", "link", "reflection_prompt", "exercise", "callout", "divider",
    "embed", "button", "resource", "columns",
)

# Soft container palette keys. NULL = no container. Must mirror the
# frontend palette in `frontend/src/lib/calloutPalette.ts`.
VALID_CONTAINER_STYLES = (
    "teal", "gold", "blue", "rose", "sage", "grey", "lilac", "orange",
)


def _validate_container_style(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if v not in VALID_CONTAINER_STYLES:
        raise ValueError(
            f"Invalid container style. Must be one of: {', '.join(VALID_CONTAINER_STYLES)}"
        )
    return v


class BlockMediaInfo(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    title: str
    file_url: str
    media_type: str
    mime_type: str
    original_filename: str


class BlockResourceInfo(BaseModel):
    """Live snapshot of the linked SpaceResource served inside a block response.

    The block itself only stores resource_id; this snapshot is read at request
    time so any edit to the underlying Resource (title, description, status,
    url) immediately flows through to every block that references it.
    """
    model_config = {"from_attributes": True}
    id: str
    title: str
    description: str | None
    resource_type: str
    url: str | None
    file_name: str | None
    status: str
    scope: str


class StepBlockResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    step_id: str
    block_type: str
    position: int
    content: str | None
    label: str | None
    caption: str | None
    embed_url: str | None
    media_asset_id: str | None
    media_asset: BlockMediaInfo | None = None
    resource_id: str | None = None
    resource: BlockResourceInfo | None = None
    container_style: str | None = None
    created_at: datetime
    updated_at: datetime


class StepBlockCreateRequest(BaseModel):
    block_type: str
    position: int | None = None
    content: str | None = None
    label: str | None = None
    caption: str | None = None
    embed_url: str | None = None
    media_asset_id: str | None = None
    resource_id: str | None = None
    container_style: str | None = None

    @field_validator("block_type")
    @classmethod
    def validate_block_type(cls, v: str) -> str:
        if v not in VALID_BLOCK_TYPES:
            raise ValueError(f"Invalid block type. Must be one of: {', '.join(VALID_BLOCK_TYPES)}")
        return v

    @field_validator("container_style")
    @classmethod
    def validate_container_style(cls, v: str | None) -> str | None:
        return _validate_container_style(v)


class StepBlockUpdateRequest(BaseModel):
    content: str | None = None
    label: str | None = None
    caption: str | None = None
    embed_url: str | None = None
    media_asset_id: str | None = None
    resource_id: str | None = None
    container_style: str | None = None

    @field_validator("container_style")
    @classmethod
    def validate_container_style(cls, v: str | None) -> str | None:
        return _validate_container_style(v)


class StepBlockReorderRequest(BaseModel):
    ids: list[str]


# ---------------------------------------------------------------------------
# Pathway About Blocks
# ---------------------------------------------------------------------------

class AboutBlockResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    pathway_id: str
    block_type: str
    position: int
    content: str | None
    label: str | None
    caption: str | None
    embed_url: str | None
    media_asset_id: str | None
    media_asset: BlockMediaInfo | None = None
    resource_id: str | None = None
    resource: BlockResourceInfo | None = None
    container_style: str | None = None
    created_at: datetime
    updated_at: datetime


class AboutBlockCreateRequest(BaseModel):
    block_type: str
    position: int | None = None
    content: str | None = None
    label: str | None = None
    caption: str | None = None
    embed_url: str | None = None
    media_asset_id: str | None = None
    resource_id: str | None = None
    container_style: str | None = None

    @field_validator("block_type")
    @classmethod
    def validate_block_type(cls, v: str) -> str:
        if v not in VALID_BLOCK_TYPES:
            raise ValueError(f"Invalid block type. Must be one of: {', '.join(VALID_BLOCK_TYPES)}")
        return v

    @field_validator("container_style")
    @classmethod
    def validate_container_style(cls, v: str | None) -> str | None:
        return _validate_container_style(v)


class AboutBlockUpdateRequest(BaseModel):
    content: str | None = None
    label: str | None = None
    caption: str | None = None
    embed_url: str | None = None
    media_asset_id: str | None = None
    resource_id: str | None = None
    container_style: str | None = None

    @field_validator("container_style")
    @classmethod
    def validate_container_style(cls, v: str | None) -> str | None:
        return _validate_container_style(v)


class AboutBlockReorderRequest(BaseModel):
    ids: list[str]


# ---------------------------------------------------------------------------
# Member pathway access (Creator Studio People detail panel)
# ---------------------------------------------------------------------------

class MemberPathwayAccessItem(BaseModel):
    """Access state + progress for one pathway, viewed from the creator's perspective."""
    id: str
    slug: str
    title: str
    pathway_status: str          # draft | active | coming_soon | archived
    access_type: str             # free | included | one_time | subscription
    price_cents: int | None
    currency: str
    billing_interval: str | None
    # Derived access fields
    access_state: str            # accessible | locked | coming_soon | draft | archived
    access_label: str            # Free | Included | Purchased | Subscribed | Locked | Coming soon | Draft
    access_source: str | None    # free | included | one_time | subscription | None
    # Progress
    total_steps: int
    completed_steps: int
    progress_pct: int
    last_activity_at: datetime | None
    enrollment_status: str | None  # active | paused | completed | None


# ---------------------------------------------------------------------------
# Creator Billing
# ---------------------------------------------------------------------------

class CreatorPlanOut(BaseModel):
    # Note: `model_config` intentionally omitted — this model is populated
    # explicitly by `_creator_plan_out` in routes.py so the capability
    # fields (which come from app.creator.plan_config, not the DB row)
    # can be merged into the response.

    # DB-backed identity + pricing
    id: str
    name: str
    slug: str
    description: str | None
    monthly_price_cents: int | None  # None for Organisation ("Talk to us")
    currency: str

    # DB-backed numeric limits (legacy fields; capability fields below
    # supersede them where they diverge)
    transaction_fee_basis_points: int | None
    collective_limit: int | None
    pathway_limit: int | None
    media_storage_limit_mb: int | None
    creator_admin_seat_limit: int | None

    # ----- capability record (from app.creator.plan_config) -----
    tagline: str = ""
    positioning: str = ""

    active_collective_limit: int | None = None
    member_allowance_per_collective: int | None = None
    pooled_member_allowance: int | None = None
    caretaker_limit_per_collective: int | None = None
    storage_allowance_mb: int | None = None

    location_scope: str = "atlas_full"
    analytics_level: str = "basic"

    paid_offers_enabled: bool = False
    pathways_enabled: bool = False
    gatherings_enabled: bool = False
    resources_enabled: bool = False
    automations_enabled: bool = False
    commercial_use: bool = False
    approval_required: bool = False
    is_self_service: bool = True
    is_purchasable: bool = True

    card_headline: str = ""
    card_features: list[str] = []


class CreatorSubscriptionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    # Stripe fields intentionally not exposed here
    stripe_connected: bool = False  # always False until Stripe is live


class CreatorUsage(BaseModel):
    collectives_used: int
    pathways_used: int
    # media_storage_used_mb not yet calculated (requires file-size tracking per asset)
    media_storage_used_mb: int | None


class CreatorPaymentSetup(BaseModel):
    creator_billing_connected: bool   # True when creator's Stripe subscription billing is active
    member_payments_connected: bool   # True when FC platform Stripe is configured for member checkout
    stripe_connect_connected: bool    # True when creator's own Stripe Connect account is set up (Phase 2+)
    stripe_test_mode: bool            # True when platform is using Stripe test keys


class CreatorBillingResponse(BaseModel):
    # Platform Owners (role='admin') are a separate account type: they do not
    # belong to any creator subscription plan and receive `current_plan`,
    # `subscription`, and `available_plans` = None / []. Every other creator
    # always has a plan and subscription. Usage counts and payment setup are
    # populated for both account types.
    current_plan: CreatorPlanOut | None = None
    subscription: CreatorSubscriptionOut | None = None
    usage: CreatorUsage
    available_plans: list[CreatorPlanOut] = []
    payment_setup: CreatorPaymentSetup
    is_platform_owner: bool = False


# ---------------------------------------------------------------------------
# Pathway Entitlements (Creator Studio People panel)
# ---------------------------------------------------------------------------

class EntitlementOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    pathway_id: str
    pathway_slug: str
    pathway_title: str
    pathway_status: str
    access_type: str
    source: str               # free | included | manual_grant | one_time_purchase | subscription | admin
    status: str               # active | revoked | expired | cancelled | pending
    starts_at: datetime
    ends_at: datetime | None
    granted_by_name: str | None
    revoked_by_name: str | None
    revoked_at: datetime | None
    notes: str | None
    # Progress (computed)
    total_steps: int
    completed_steps: int
    progress_pct: int
    last_activity_at: datetime | None


class GrantEntitlementRequest(BaseModel):
    pathway_id: str
    notes: str | None = None


class RevokeEntitlementRequest(BaseModel):
    pathway_id: str
    notes: str | None = None


class GrantPassRequest(BaseModel):
    user_id: str
    payment_option_id: str                         # required — auto-populates credits/dates/pathway
    pass_type: str = "term_pass"
    total_credits: int | None = None
    credits_per_week: int | None = None
    valid_from: date | None = None                # defaults to today
    valid_until: date | None = None
    eligible_pathway_id: str | None = None
    source: str = "manual"                         # "manual" | "bank_transfer" | "cash" | "complimentary" | "test"
    notes: str | None = None
    also_grant_pathway_access: bool = True         # create PathwayEntitlement if eligible_pathway_id is set
    record_payment: bool = False
    payment_amount_cents: int | None = None        # only used if record_payment=True


class GrantPassResponse(BaseModel):
    pass_id: str
    entitlement_id: str | None = None
    transaction_id: str | None = None
    message: str


# ---------------------------------------------------------------------------
# Payment Transactions (creator-visible)
# ---------------------------------------------------------------------------

class CreatorPaymentSummary(BaseModel):
    """Earnings summary for the current creator's transactions."""
    # Totals from succeeded member purchases (excludes creator subscription payments)
    total_gross_amount_cents: int
    total_platform_fee_cents: int
    total_creator_net_amount_cents: int

    # Payout estimate — sum of net_creator for succeeded transactions with payout_status=pending
    # TODO: subtract once Stripe Connect transfers are processed (payout_status → paid)
    pending_payout_cents: int

    # Transaction counts by status
    succeeded_count: int
    refunded_count: int
    disputed_count: int
    pending_count: int


class CreatorPaymentTransactionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    transaction_type: str
    status: str

    payer_user_id: str | None
    space_id: str | None
    pathway_id: str | None
    payment_option_id: str | None = None
    payment_option_schedule_id: str | None = None

    currency: str
    gross_amount_cents: int
    platform_fee_basis_points: int
    platform_fee_cents: int
    net_creator_amount_cents: int | None

    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Payment Options
# ---------------------------------------------------------------------------

_VALID_OPTION_TYPES = ("free", "one_time", "term_pass", "subscription")
_VALID_OPTION_STATUSES = ("draft", "published", "archived")


class PaymentOptionCreateRequest(BaseModel):
    name: str
    description: str | None = None
    payment_type: str = "one_time"
    status: str = "draft"
    term_start_date: date | None = None
    term_end_date: date | None = None
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    price_per_session_cents: int | None = None
    calculated_total_cents: int | None = None
    override_total_cents: int | None = None
    currency: str = "AUD"
    buyer_note: str | None = None
    internal_note: str | None = None
    grants_pathway_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required.")
        return v

    @field_validator("payment_type")
    @classmethod
    def validate_payment_type(cls, v: str) -> str:
        if v not in _VALID_OPTION_TYPES:
            raise ValueError(f"payment_type must be one of: {_VALID_OPTION_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_OPTION_STATUSES:
            raise ValueError(f"status must be one of: {_VALID_OPTION_STATUSES}")
        return v


class PaymentOptionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    payment_type: str | None = None
    status: str | None = None
    term_start_date: date | None = None
    term_end_date: date | None = None
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    price_per_session_cents: int | None = None
    calculated_total_cents: int | None = None
    override_total_cents: int | None = None
    currency: str | None = None
    buyer_note: str | None = None
    internal_note: str | None = None
    grants_pathway_id: str | None = None

    @field_validator("payment_type")
    @classmethod
    def validate_payment_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_OPTION_TYPES:
            raise ValueError(f"payment_type must be one of: {_VALID_OPTION_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_OPTION_STATUSES:
            raise ValueError(f"status must be one of: {_VALID_OPTION_STATUSES}")
        return v


class PaymentOptionResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    space_id: str
    pathway_id: str | None
    grants_pathway_id: str | None
    name: str
    description: str | None
    payment_type: str
    status: str
    term_start_date: date | None
    term_end_date: date | None
    sessions_per_week: int | None
    total_sessions: int | None
    price_per_session_cents: int | None
    calculated_total_cents: int | None
    override_total_cents: int | None
    effective_price_cents: int | None
    currency: str
    buyer_note: str | None
    internal_note: str | None
    position: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Payment option schedules
# ---------------------------------------------------------------------------

_VALID_SCHEDULE_TYPES = ("pay_in_full", "recurring_installments", "manual")
_VALID_SCHEDULE_STATUSES = ("draft", "published", "archived")


class PaymentOptionScheduleCreateRequest(BaseModel):
    name: str
    description: str | None = None
    schedule_type: str = "pay_in_full"
    status: str = "draft"
    total_amount_cents: int | None = None
    upfront_amount_cents: int | None = None
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None
    stripe_interval: str | None = None
    stripe_interval_count: int | None = None
    currency: str = "AUD"
    buyer_note: str | None = None
    internal_note: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name is required")
        return v.strip()

    @field_validator("schedule_type")
    @classmethod
    def validate_schedule_type(cls, v: str) -> str:
        if v not in _VALID_SCHEDULE_TYPES:
            raise ValueError(f"schedule_type must be one of: {_VALID_SCHEDULE_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_SCHEDULE_STATUSES:
            raise ValueError(f"status must be one of: {_VALID_SCHEDULE_STATUSES}")
        return v


class PaymentOptionScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule_type: str | None = None
    status: str | None = None
    total_amount_cents: int | None = None
    upfront_amount_cents: int | None = None
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None
    stripe_interval: str | None = None
    stripe_interval_count: int | None = None
    currency: str | None = None
    buyer_note: str | None = None
    internal_note: str | None = None

    @field_validator("schedule_type")
    @classmethod
    def validate_schedule_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_SCHEDULE_TYPES:
            raise ValueError(f"schedule_type must be one of: {_VALID_SCHEDULE_TYPES}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_SCHEDULE_STATUSES:
            raise ValueError(f"status must be one of: {_VALID_SCHEDULE_STATUSES}")
        return v


class PaymentOptionScheduleResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    payment_option_id: str
    name: str
    description: str | None
    schedule_type: str
    status: str
    total_amount_cents: int | None
    upfront_amount_cents: int | None
    installment_amount_cents: int | None
    installment_count: int | None
    interval: str | None
    stripe_interval: str | None
    stripe_interval_count: int | None
    currency: str
    buyer_note: str | None
    internal_note: str | None
    position: int
    created_at: datetime
    updated_at: datetime


class GenerateSchedulesRequest(BaseModel):
    """
    Request body for the 'generate standard schedules' convenience endpoint.

    Generates draft pay_in_full, weekly, and fortnightly schedules based
    on the payment option's effective_price_cents. Caller supplies installment
    counts (defaults to 10 weekly / 5 fortnightly if not provided).
    """
    weekly_installment_count: int = 10
    fortnightly_installment_count: int = 5


# ---------------------------------------------------------------------------
# Access Passes (Phase B)
# ---------------------------------------------------------------------------

class AccessPassAdminOut(BaseModel):
    """Creator-facing AccessPass summary, includes member info and booking stats."""

    id: str
    pass_type: str
    status: str
    valid_from: datetime
    valid_until: datetime | None = None
    total_credits: int | None = None
    used_credits: int
    remaining_credits: int | None = None
    credits_per_week: int | None = None
    eligible_pathway_id: str | None = None
    option_name: str | None = None
    pathway_title: str | None = None
    created_at: datetime
    # Member info
    member_name: str | None = None
    member_email: str | None = None
    # Booking stats
    total_bookings: int = 0
    recent_bookings: int = 0  # last 30 days
