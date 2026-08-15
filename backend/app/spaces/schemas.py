from datetime import date, datetime
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
    pricing_mode: str = 'legacy'
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    # 'guided_experience' | 'knowledge_guide'. Default keeps every
    # legacy pathway rendering exactly as it did before.
    pathway_type: str = 'guided_experience'
    user_has_access: bool = False
    step_count: int = 0
    unlock_offer_names: list[str] = []


class SpaceResponse(BaseModel):
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
    # Optional "hosted by" mark. Rendered subtly beside the collective name
    # in the header. Location artwork is still the primary visual identity.
    logo_url: str | None = None
    pathways: list[PathwaySummary] = []
    pricing_type: str = 'free'
    pricing_amount_cents: int | None = None
    pricing_currency: str = 'AUD'
    pricing_note: str | None = None
    has_paid_internal_content: bool = False
    included_access_summary: str | None = None
    paid_content_summary: str | None = None
    guidance_start_title: str | None = None
    guidance_start_body: str | None = None
    guidance_focus_title: str | None = None
    guidance_focus_body: str | None = None
    guidance_links_title: str | None = None
    guidance_links_body: str | None = None
    show_member_directory: bool = False
    # Authoritative aggregate counts — injected by the get_space
    # route, sourced from a DB aggregate on ``space_memberships``.
    # Frontend sidebar/stats surfaces MUST consume these fields
    # rather than deriving counts from the privacy-filtered
    # ``/api/spaces/{slug}/members`` list; that list hides learner
    # rows from ordinary members when ``show_member_directory=False``
    # and would silently render an incorrect "0 members" in the
    # shared Collective sidebar for every learner-role viewer.
    learner_count: int = 0
    leader_count: int = 0
    # Atlas v1.2 identity fields — Location provides artwork, Colour Palette
    # drives the collective's visual interface, atmosphere + identity + welcome
    # personalise the experience. All nullable while existing collectives
    # migrate.
    location: dict | None = None
    colour_palette: dict | None = None
    colour_palette_key: str | None = None
    atmosphere_keys: list[str] = []
    # Human-readable atmosphere names, resolved via atmosphere_options.
    # Same order as `atmosphere_keys` but with any unknown keys dropped.
    atmosphere_labels: list[str] = []
    identity_statement: str | None = None
    welcome_message: str | None = None
    # When set, this space auto-grants membership to every user whose
    # ``users.role`` matches this value. Read-only signal for member
    # surfaces so About-page CTAs can render the "For Fresh Collective
    # Creators" soft-restricted state instead of the standard Join
    # button. See Space.auto_grant_role in models/platform.py.
    auto_grant_role: str | None = None

    @field_validator("atmosphere_keys", mode="before")
    @classmethod
    def _coerce_atmosphere_keys(cls, v: object) -> list[str]:
        # Legacy rows may store None where the migration expected a list.
        if v is None:
            return []
        return v  # type: ignore[return-value]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def derived_has_paid_internal_content(self) -> bool:
        """True if at least one active pathway requires separate payment."""
        paid_access = {'one_time', 'subscription'}
        return any(
            p.access_type in paid_access
            and p.status == 'active'
            and p.price_cents is not None
            and p.price_cents > 0
            for p in (self.pathways or [])
        )


class SpaceSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    slug: str
    name: str
    tagline: str | None
    status: str
    is_public: bool


class StepAvailability(BaseModel):
    """Whether a step is available to the current member right now, and
    why not if it isn't. See app.services.pathway_release for the rules."""
    is_locked: bool = False
    reason: str | None = None
    unlocks_at: datetime | None = None
    message: str | None = None
    # Echoed so the client can render creator-friendly summaries even
    # while a step is locked (e.g. "Releases 7 days after enrolment").
    release_type: str = "immediate"
    release_offset_days: int | None = None
    release_at: datetime | None = None
    release_timezone: str | None = None
    release_previous_state: str = "completed"


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
    banner_image_url: str | None = None
    availability: StepAvailability = StepAvailability()


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
    reflection_enabled: bool = True
    discussion_enabled: bool = True
    banner_image_url: str | None = None
    # Set ONLY when this step is the first step in its section — used by the
    # member step page to render a "welcome to Week N" banner at the top.
    section_banner_image_url: str | None = None
    section_title: str | None = None
    availability: StepAvailability = StepAvailability()


class SectionWithSteps(BaseModel):
    """A pathway section/module with its nested steps."""

    id: str
    # URL-safe chapter identifier derived from title + id. Stable
    # enough for member bookmarks; the id suffix keeps the slug
    # unique even if two sections share a title. Used by the
    # Knowledge Guide chapter switcher; ignored by the Guided
    # Experience surface.
    slug: str = ''
    title: str
    position: int
    steps: list[StepSummary]
    banner_image_url: str | None = None


class PaymentOptionScheduleSummary(BaseModel):
    """Member-facing payment schedule — internal_note excluded."""

    id: str
    name: str
    description: str | None = None
    schedule_type: str
    status: str
    total_amount_cents: int | None = None
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None
    currency: str
    buyer_note: str | None = None
    position: int


class PaymentOptionSummary(BaseModel):
    """Member-facing payment option — internal_note excluded."""

    id: str
    name: str
    description: str | None
    payment_type: str
    status: str
    term_start_date: date | None = None
    term_end_date: date | None = None
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    price_per_session_cents: int | None = None
    calculated_total_cents: int | None = None
    override_total_cents: int | None = None
    effective_price_cents: int | None = None
    currency: str
    buyer_note: str | None = None
    position: int
    schedules: list[PaymentOptionScheduleSummary] = []


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
    pricing_mode: str = 'legacy'
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    # 'guided_experience' | 'knowledge_guide'. The member frontend
    # branches on this to render either the per-step Guided flow or
    # the continuous Knowledge Guide document.
    pathway_type: str = 'guided_experience'
    user_has_access: bool = False
    payment_options: list[PaymentOptionSummary] = []


# ── Knowledge Guide continuous view ──────────────────────────────────


class GuideStep(BaseModel):
    """One step's ordered blocks, embedded inline into a KG chapter."""

    id: str
    slug: str
    title: str
    blocks: list[dict]


class GuideSection(BaseModel):
    """One chapter of a Knowledge Guide — a section with its steps."""

    id: str
    slug: str
    title: str
    banner_image_url: str | None = None
    steps: list[GuideStep] = []


class KnowledgeGuideResponse(BaseModel):
    """Full continuous document for a Knowledge Guide pathway.

    Returns every section + every step + every block in one round
    trip. Not used for Guided Experience pathways — those use the
    existing per-step endpoints.
    """

    id: str
    slug: str
    title: str
    description: str | None
    cover_image_url: str | None = None
    pathway_type: str = 'knowledge_guide'
    # Ungrouped steps — steps with no section, rendered above the
    # sectioned chapters. Empty for well-organised guides.
    orphan_steps: list[GuideStep] = []
    sections: list[GuideSection] = []


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
    id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime | None
    location_type: str
    # Booking state — computed in routes, not read from ORM attributes directly
    requires_booking: bool = False
    capacity: int | None = None
    booked_count: int = 0
    spots_remaining: int | None = None
    booking_closes_at: datetime | None = None
    booking_note: str | None = None
    my_booking_status: str | None = None   # 'confirmed' | 'cancelled' | None
    can_book: bool = False
    can_cancel_booking: bool = False
    # Recurrence
    recurrence_series_id: str | None = None
    recurrence_label: str | None = None
    recurrence_index: int | None = None
    recurrence_total: int | None = None
    # Semantic Gathering Series membership (migration 105). Distinct
    # from the recurrence bulk-create tag above. Frontend uses these
    # to render "Included with {series_title}" copy on the public
    # Gathering detail when the access type is 'included_with_series'.
    series_id: str | None = None
    series_title: str | None = None
    # Series slug so the client can eventually link to a Series
    # page. Cheap to include today; no UI depends on it yet.
    series_slug: str | None = None
    # Cover art for the parent Series. Used as a hero-image
    # fallback when the Event itself has no ``thumbnail_url``.
    series_cover_image_url: str | None = None
    # Slug of the *published* Offer Page whose ``target_kind='event_series'``
    # points at this event's Series, if one exists. Null when the Series
    # has no published Offer Page. Lets the member UI route a "Buy series
    # pass" CTA to the right public page without a second round-trip.
    series_offer_page_slug: str | None = None
    # ``True`` when the viewer holds a valid, in-window AccessPass
    # scoped to this Series. Lets the booking UI show the correct
    # state (Reserve vs Pass required) without a preemptive POST.
    user_has_series_pass: bool = False
    # Visibility
    is_public: bool = False
    # Thumbnail
    thumbnail_url: str | None = None
    # Lifecycle: active | cancelled | archived
    status: str = "active"
    # Booking access control — Gatherings 2.0 vocabulary. See
    # services/gathering_types.py. Values: free | included_with_collective |
    # included_with_pathway | paid_separately | invitation_only.
    booking_access_type: str = "included_with_collective"
    booking_required_pathway_id: str | None = None
    # Whether the current user has access to the required pathway (True when no restriction)
    user_has_pathway_access: bool = True
    # Remaining credits on the user's active AccessPass for this pathway (None = no pass / unlimited)
    pass_credits_remaining: int | None = None
    # Gatherings 2.0 — visible identity + attendance metadata.
    gathering_type: str = "other"
    attendance_format: str = "online"
    venue_name: str | None = None
    # Member-safe locality — same derivation rule as the detail
    # endpoint (see ``_derive_venue_locality``); always exposed.
    venue_locality: str | None = None
    # Human name of the Gathering's host (the User who created the row).
    # Kept as a plain string so the member-facing "Hosted by" line
    # doesn't need an extra profile round-trip.
    host_name: str | None = None
    # Public recording URL, when the caretaker has added one. Kept on
    # the summary so archive cards can surface a "Watch replay" CTA
    # without an extra detail round-trip. Sensitive meeting links +
    # arrival instructions remain on the detail endpoint (attendee-only).
    recording_url: str | None = None
    # Standalone paid Gatherings (Stage 4). Both are null for non-paid
    # access types. `sales_enabled` mirrors the platform feature flag so
    # the member UI can present a calm "Ticket sales aren't open yet"
    # state instead of a Buy button that would immediately 503.
    ticket_price_cents: int | None = None
    ticket_currency: str | None = None
    sales_enabled: bool = False


class EventDetail(EventSummary):
    location_url: str | None = None
    recording_url: str | None = None
    # Full venue details + access/arrival instructions. Endpoint scrubs
    # these for non-attendees so the schema always includes them.
    venue_address: str | None = None
    access_instructions: str | None = None
    # Member-safe locality (suburb + region) derived server-side from
    # ``venue_address``. Always exposed — filters out street-address
    # fragments so a public reader can see "South Croydon, VIC" while
    # ``venue_address`` (the full street address) stays behind the
    # attendee gate.
    venue_locality: str | None = None


class SeriesBookingResponse(BaseModel):
    booked: int
    already_booked: int
    skipped_full: int
    skipped_closed: int
    total_in_series: int



class BookingResponse(BaseModel):
    status: str
    booking_id: str | None = None


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
    pricing_type: str = 'free'
    pricing_amount_cents: int | None = None
    pricing_currency: str = 'AUD'
    pricing_note: str | None = None
    has_paid_internal_content: bool = False
    included_access_summary: str | None = None
    paid_content_summary: str | None = None
    # Auto-derived: True if the collective has at least one active paid pathway.
    derived_has_paid_internal_content: bool = False
    # Minimum price of any published paid pathway inside this collective (cents).
    # None means no paid pathways exist or pricing is not yet set.
    min_paid_pathway_price_cents: int | None = None
    # Atlas v1.2 — the collective's assigned Location artwork. Consumers
    # prefer the thumbnail for card displays and the hero for large previews,
    # falling back to `cover_image_url` for legacy spaces with no Location.
    location_hero_artwork_url: str | None = None
    location_thumbnail_artwork_url: str | None = None


# ---------------------------------------------------------------------------
# Space Resources (member-facing)
# ---------------------------------------------------------------------------

class CollectiveResourceResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    title: str
    description: str | None
    resource_type: str
    url: str | None
    file_name: str | None
    file_size: int | None
    sort_order: int
    created_at: datetime
    scope: str = "general"
    pathway_id: str | None = None
    source: str = "standalone"


class PathwayResourceItem(BaseModel):
    id: str
    title: str
    description: str | None
    resource_type: str
    url: str | None
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    is_downloadable: bool = True
    step_id: str | None = None
    step_title: str | None = None
    # general | pathway_resource | pathway_step | pathway_step_content
    source: str = "pathway_step"


class PathwayResourceGroup(BaseModel):
    pathway_id: str
    pathway_title: str
    pathway_slug: str
    access_label: str
    resources: list[PathwayResourceItem]


class AggregatedResourcesResponse(BaseModel):
    standalone_resources: list[CollectiveResourceResponse]
    pathway_resource_groups: list[PathwayResourceGroup]


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


class SpaceAccessStatus(BaseModel):
    """Current caller's access state for a specific Space."""
    is_member: bool
    membership_role: str | None       # learner | moderator | creator | None
    has_pending_request: bool          # pending access request exists
    has_pending_invite: bool           # invite exists for caller's email


class AccessRequestOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    user_display_name: str
    user_email: str
    status: str                        # pending | approved | declined
    message: str | None
    created_at: datetime


class InviteLookupResponse(BaseModel):
    """Public info about an invite, returned by token lookup (no auth required)."""
    id: str
    space_id: str
    space_name: str
    space_slug: str
    email: str
    name: str | None
    role: str


class AccessPassOut(BaseModel):
    """Member-facing AccessPass summary."""

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


# ---------------------------------------------------------------------------
# Offer Pages — public read shape
# ---------------------------------------------------------------------------


class PublicPaymentOptionSchedule(BaseModel):
    """A published PaymentOptionSchedule row exposed on the public
    Offer Page. Frontend uses ``schedule_type`` to decide the CTA
    label (Pay in full vs Weekly instalments) and which checkout
    endpoint to call. Recurring instalments are exposed for display
    but not yet purchasable — the checkout endpoint returns 503.

    ``is_member_checkoutable`` is the single source of truth for the
    member surface: True only when unified checkout can actually
    complete this schedule end-to-end today (``schedule_type ==
    'pay_in_full'``). Everything else (recurring_installments,
    manual, draft) is False. The member frontend must not surface a
    payment method the backend would refuse — this flag keeps the two
    layers honest without the frontend re-encoding checkout policy."""

    id: str
    name: str
    description: str | None = None
    schedule_type: str                       # 'pay_in_full' | 'recurring_installments' | 'manual'
    total_amount_cents: int | None = None
    upfront_amount_cents: int | None = None
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None
    currency: str
    buyer_note: str | None = None
    is_member_checkoutable: bool = False


class PublicPaymentOption(BaseModel):
    """A published PaymentOption attached to the Offer Page's target
    (e.g. an EventSeries). Includes its published Schedules so the
    public renderer can show tiered pricing (Awaken / Activate /
    Empower) alongside each tier's payment methods."""

    id: str
    name: str
    description: str | None = None
    payment_type: str                        # 'free' | 'one_time' | 'term_pass' | 'subscription'
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    price_per_session_cents: int | None = None
    effective_price_cents: int | None = None
    currency: str
    buyer_note: str | None = None
    schedules: list[PublicPaymentOptionSchedule] = []


class PublicOfferCreator(BaseModel):
    """The real Creator profile behind the Space that owns this
    Offer Page. Used by the "Meet your guide" section on the public
    page. Falls back to bare user identity when the CreatorProfile
    row is missing or ``is_public=False``."""

    display_name: str | None = None
    tagline: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    website_url: str | None = None


class OfferPageTargetSnapshot(BaseModel):
    """A small denormalised snapshot of the target so the public
    Offer Page can render pricing + CTA target without a second
    round trip. Populated at request time; the fields exposed are
    intentionally minimal to avoid coupling the Offer Page to the
    full target schema.
    """

    kind: str                                 # 'pathway' | 'event_series' | 'gathering'
    id: str
    slug: str
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    # Pricing (target-live — Offer Page does not override in V1).
    # For ``event_series`` targets ``access_type`` / ``price_cents`` /
    # ``billing_interval`` are None: pricing lives on the attached
    # ``payment_options`` instead. For ``gathering`` targets they
    # describe the standalone ticket where present.
    access_type: str | None = None
    price_cents: int | None = None
    currency: str | None = None
    billing_interval: str | None = None
    # CTA routing hint — the frontend uses this to build the button
    # href without knowing per-target checkout paths itself. For
    # ``event_series`` this stays None (checkout is driven by a
    # PaymentOption + Schedule selection, not a single URL).
    checkout_path: str | None = None
    # The target's landing URL — used by the "You already have this"
    # CTA state so a member with access is sent straight to the
    # content, not the checkout.
    enter_path: str | None = None
    # Series/gathering window — populated for ``event_series`` and
    # ``gathering`` targets, None for ``pathway``.
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    # Series-specific — the published PaymentOptions attached to this
    # Series, each with its published Schedules nested. Empty list
    # for other kinds.
    payment_options: list[PublicPaymentOption] = []
    # Gathering-specific — standalone ticket price for a paid single
    # Gathering. None for other kinds and for free/included gatherings.
    ticket_price_cents: int | None = None
    ticket_currency: str | None = None


class PublicOfferPage(BaseModel):
    """Public shape of an Offer Page. Only ``published`` pages are
    exposed to non-owners; owners see drafts through the same
    endpoint (mirrors the existing About-page visibility pattern).
    """

    id: str
    slug: str
    title: str
    promise: str | None
    hero_image_url: str | None
    status: str
    sections_config: dict
    target: OfferPageTargetSnapshot
    # Real Creator profile — used by the public "Meet your guide"
    # section. ``None`` when no personal Creator identity is available
    # (no CreatorProfile and no usable User.name). Never falls back
    # to the Collective's name/tagline/description/logo — the
    # Collective is not the Creator. A future "About this Collective"
    # section will present that separately.
    creator: PublicOfferCreator | None = None
    # ``true`` when the requesting member (or admin/creator) already
    # holds access to the target. The frontend swaps the primary CTA
    # from "Purchase" to "Continue" in this case.
    user_has_target_access: bool = False
