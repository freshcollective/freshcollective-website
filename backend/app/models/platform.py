"""
SQLAlchemy models for the Fresh Collective Space-based platform architecture.

Entities:
  spaces              — a creator's home on the platform
  space_memberships   — user access relationship to a Space (role + status)
  creator_profiles    — extended profile data for creator-role users
  pathways            — structured learning journeys within a Space
  pathway_steps       — individual content units within a Pathway
  enrollments         — a learner's relationship to a Pathway
  step_progress       — completion records for individual Steps
  events              — live experiences within a Space
  community_posts     — posts in a Space's community feed
  post_comments       — replies to community posts

Design notes:
  - All IDs are string UUID4, consistent with existing tables.
  - Money is not stored here — see sales.py / member_subscriptions.
  - Soft-delete via is_visible / status fields rather than deleted_at,
    except where noted.
  - creator_id on spaces uses RESTRICT so a creator cannot be deleted
    while they own a Space.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SpaceStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class SpaceRole(str, enum.Enum):
    learner = "learner"
    moderator = "moderator"
    creator = "creator"


class SpaceMembershipStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    removed = "removed"


class PathwayStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    coming_soon = "coming_soon"
    archived = "archived"


class PathwayType(str, enum.Enum):
    """How members experience a Pathway.

    ``guided_experience`` (default) — the original per-step flow with
    progress, reflections, next/previous navigation.

    ``knowledge_guide`` — one continuous reference document rendered on
    the pathway landing page. Sections become chapters, steps render
    inline. No progress or completion is displayed.
    """

    guided_experience = "guided_experience"
    knowledge_guide = "knowledge_guide"


class StepContentType(str, enum.Enum):
    text = "text"
    video = "video"
    reflection = "reflection"
    exercise = "exercise"
    audio = "audio"


class MediaType(str, enum.Enum):
    image = "image"
    video = "video"
    audio = "audio"
    document = "document"
    other = "other"


class MediaStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class StepBlockType(str, enum.Enum):
    heading = "heading"
    text = "text"
    image = "image"
    video_embed = "video_embed"
    audio = "audio"
    file_download = "file_download"
    link = "link"
    reflection_prompt = "reflection_prompt"
    exercise = "exercise"
    callout = "callout"
    divider = "divider"
    embed = "embed"
    button = "button"
    # Reference to a collective-level SpaceResource. The block holds only
    # the FK (resource_id) plus optional overrides; everything else is
    # read live from the linked resource so edits flow through.
    resource = "resource"
    # Multi-column layout container. Structured JSON in ``content`` holds
    # one TipTap document per column plus a layout descriptor; extensible
    # to further layouts (cards, comparison) via layout.kind/variant.
    columns = "columns"


class EnrollmentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"


class EntitlementSource(str, enum.Enum):
    free = "free"
    included = "included"
    manual_grant = "manual_grant"
    one_time_purchase = "one_time_purchase"
    subscription = "subscription"
    admin = "admin"


class EntitlementStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"
    expired = "expired"
    cancelled = "cancelled"
    pending = "pending"
    # FIP3: plan-derived entitlement paused by plan suspension.
    # Distinct from ``revoked`` (permanent) so the reinstatement
    # path can restore access without minting a new row.
    suspended = "suspended"


class EventLocationType(str, enum.Enum):
    zoom = "zoom"
    in_person = "in_person"
    async_recorded = "async_recorded"


class BookingStatus(str, enum.Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"
    # Temporary hold for a standalone paid Gathering while the buyer is in
    # Stripe Checkout. Expires via `hold_expires_at`. Converted to
    # `confirmed` by the webhook on successful payment; converted to
    # `cancelled` on payment failure, Session expiry, or capacity queries
    # that opportunistically prune stale holds. Never grants access.
    pending_payment = "pending_payment"


class PostType(str, enum.Enum):
    # Legacy values kept for existing rows.
    prompt = "prompt"
    reflection = "reflection"
    discussion = "discussion"
    announcement = "announcement"
    # Community Phase 1 — the extended type vocabulary the creator can
    # choose from in the composer.
    poll = "poll"
    question = "question"
    celebration = "celebration"
    share = "share"


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tagline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Optional "hosted by" mark shown subtly beside the collective name.
    # Not brand chrome — the Location artwork remains the primary visual
    # identity. Nullable; most collectives will not set one.
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # NULL creator_id means the space is owned by the platform itself
    creator_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    timezone: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Australia/Melbourne", server_default="Australia/Melbourne"
    )
    status: Mapped[SpaceStatus] = mapped_column(
        SAEnum(SpaceStatus, name="space_status_enum", create_type=True),
        nullable=False,
        default=SpaceStatus.active,
        server_default="active",
    )
    themes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="'[]'"
    )
    # Public pricing display — display/config only; payment processing is separate
    pricing_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="free", server_default="free"
    )
    pricing_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pricing_currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="AUD", server_default="AUD"
    )
    pricing_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Access model — distinguishes join cost from what is included / paid separately inside
    has_paid_internal_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    included_access_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    paid_content_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Build Your Place — aesthetic identity fields set during the guided
    # creator ritual. All nullable while old collectives coexist with the
    # new flow. See migration 063 and the Atlas (Chapter 4).
    landscape_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    atmosphere_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    colour_story_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    element_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # The heart of the collective, in one sentence — set during Build Your
    # Place. Guides future design and AI assistance, not member-facing copy.
    identity_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The first thing visitors read when they arrive at the collective.
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reserved for archipelago clustering; taxonomy grows over time and is
    # not yet exposed in UI.
    archipelago_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Visibility model — three levels. Existing rows backfilled from
    # is_public in migration 063. is_public is kept in sync for read paths
    # that haven't migrated yet ('public' → True, else False).
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public", server_default="public"
    )
    # Island artwork — the illustrated map that replaces the procedural SVG
    # fallback once ready. Status flow: not_started → generating → ready
    # (or failed). Prompt is filled the moment the collective is opened;
    # url is set on upload (or by a future generator). Version bumps every
    # replace, so caching / cache-busting can key on it. See migration 064.
    island_artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    island_artwork_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_started", server_default="not_started"
    )
    island_artwork_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    island_artwork_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    island_artwork_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    # The curated Location this collective lives inside (Atlas v1.1).
    # Nullable while the migration to Locations is in progress; Build Your
    # Collective will populate this in a later change. See migration 065.
    location_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Creator-managed guidance panel shown in member-facing sidebar
    guidance_start_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_start_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_focus_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_focus_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_links_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_links_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Member directory — False (default): learners see count only; True: all members visible
    show_member_directory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ---- Platform-managed auto-grant --------------------------------------
    # When set, users whose ``users.role`` matches this value receive an
    # automatic ``SpaceMembership`` (source='auto_role') for this space
    # for as long as they remain eligible (see
    # ``services.creator_eligibility.is_eligible_creator``). Currently
    # only used by the World Builders collective with the value
    # ``'creator'``. Not exposed in Creator Studio; set via migration or
    # by a platform admin. Any space with this flag is:
    #   * hidden from the public collective explore list
    #   * un-joinable via the public join endpoint (403)
    #   * shown with a locked "access managed automatically" panel in
    #     Settings instead of the standard visibility/pricing controls
    auto_grant_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ---- Discovery, Connection & Belonging — Collective Kind -------------
    # Distinguishes creator-led collectives (the default) from peer-led
    # Local Circles. Schema-only in Phase 0 — no behavioural branching
    # yet; a later phase adds Local-Circle-specific defaults, discovery
    # placement, and creation flow. Existing rows backfill to 'standard'.
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="standard", server_default="standard"
    )

    # ---- Discovery, Connection & Belonging — Connection style ------------
    # How this Collective connects: 'online' (default — safe for every
    # existing row, since none have a Geographic Location yet), 'in_person'
    # or 'both'. Drives whether a primary Geographic Location is
    # required at publish time and whether this Collective appears on
    # Discover Places. See
    # ``docs/foundations/discovery-connection-belonging-location-model.md``.
    connection_style: Mapped[str] = mapped_column(
        String(16), nullable=False, default="online", server_default="online"
    )

    # ---- Community Care — collective suspension (Stage 2A reservation) ----
    # These columns landed with Stage 2A for future use; Stage 2C uses
    # the dedicated ``frozen_*`` columns below to represent an active
    # collective freeze so freeze and any future space-level
    # suspension can be distinguished at the schema layer.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Community Care — collective closure (resolution, terminal) ------
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    closure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stage 2D — link back to the resolution action that closed the
    # collective so the audit trail names the specific case + admin.
    closed_by_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- Community Care Stage 2C — collective freeze (protective) ---------
    # When ``frozen_at`` is set and (``frozen_until`` IS NULL OR in the
    # future), the collective is read-only. Existing members keep read
    # access but no writes, purchases, joins, renewals or new bookings
    # are permitted. Reversal clears these fields.
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    frozen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    freeze_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_by_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('standard', 'local_circle')",
            name="spaces_kind_check",
        ),
        CheckConstraint(
            "connection_style IN ('online', 'in_person', 'both')",
            name="spaces_connection_style_check",
        ),
    )

    @property
    def platform_owned(self) -> bool:
        """True when creator_id IS NULL — space belongs to Fresh Collective, not an external creator."""
        return self.creator_id is None

    memberships: Mapped[list["SpaceMembership"]] = relationship(
        "SpaceMembership", back_populates="space", cascade="all, delete-orphan"
    )
    pathways: Mapped[list["Pathway"]] = relationship(
        "Pathway", back_populates="space", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="space", cascade="all, delete-orphan"
    )
    community_posts: Mapped[list["CommunityPost"]] = relationship(
        "CommunityPost", back_populates="space", cascade="all, delete-orphan"
    )
    resources: Mapped[list["SpaceResource"]] = relationship(
        "SpaceResource", back_populates="space", cascade="all, delete-orphan"
    )


class SpaceMembership(Base):
    """
    Access relationship between a user and a Space.
    Separate from billing (MemberSubscription in sales.py).
    A user can have different roles in different spaces.
    """

    __tablename__ = "space_memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[SpaceRole] = mapped_column(
        SAEnum(SpaceRole, name="space_role_enum", create_type=True),
        nullable=False,
        default=SpaceRole.learner,
        server_default="learner",
    )
    status: Mapped[SpaceMembershipStatus] = mapped_column(
        SAEnum(SpaceMembershipStatus, name="space_membership_status_enum", create_type=True),
        nullable=False,
        default=SpaceMembershipStatus.active,
        server_default="active",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    # How this membership came into existence. Nullable for legacy rows;
    # migration 089 backfills existing rows to 'joined'. Values:
    #   'joined'         — user pressed the public Join button
    #   'invited'        — someone was invited and accepted
    #   'purchase'       — auto-created by the post-payment webhook
    #   'creator_owner'  — the collective's owner at creation time
    #   'auto_role'      — auto-granted via Space.auto_grant_role
    # Only ``auto_role`` rows are ever touched by
    # ``services.creator_eligibility.apply_creator_eligibility_change``;
    # everything else is preserved untouched.
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # type: ignore[name-defined]
    space: Mapped[Space] = relationship("Space", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("user_id", "space_id", name="space_memberships_user_space_unique"),
        Index("ix_space_memberships_space_user", "space_id", "user_id"),
    )


# ---------------------------------------------------------------------------
# Creator Profiles
# ---------------------------------------------------------------------------

class CreatorProfile(Base):
    """One-to-one extension of users for creator-role accounts."""

    __tablename__ = "creator_profiles"

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_tagline: Mapped[str | None] = mapped_column(String(150), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

class Pathway(Base):
    """
    A structured learning journey inside a Space.
    REAL Journey, Growth, Transformation, Essence are all Pathways
    within the Fresh Collective Space.
    """

    __tablename__ = "pathways"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Whether steps must be completed in order before the next unlocks
    is_sequential: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[PathwayStatus] = mapped_column(
        SAEnum(PathwayStatus, name="pathway_status_enum", create_type=True),
        nullable=False,
        default=PathwayStatus.active,
        server_default="active",
    )
    # How members experience the content. Existing rows default to
    # ``guided_experience`` so the change is a no-op for them; new
    # pathways can opt into ``knowledge_guide`` for a continuous
    # reference-document presentation. Same content model either way.
    pathway_type: Mapped[PathwayType] = mapped_column(
        SAEnum(PathwayType, name="pathway_type_enum", create_type=False),
        nullable=False,
        default=PathwayType.guided_experience,
        server_default="guided_experience",
    )
    # Display order within the Space
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Access / pricing — see access_type values: free | included | one_time | subscription
    access_type: Mapped[str] = mapped_column(String(20), nullable=False, default="free", server_default="free")
    # pricing_mode: legacy (single price_cents) | payment_options (multiple PaymentOption rows)
    pricing_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="legacy", server_default="legacy")
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="AUD", server_default="AUD")
    billing_interval: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Narrative description of what learners will practise
    practice_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    space: Mapped[Space] = relationship("Space", back_populates="pathways")
    steps: Mapped[list["PathwayStep"]] = relationship(
        "PathwayStep", back_populates="pathway", cascade="all, delete-orphan",
        order_by="PathwayStep.position",
    )
    sections: Mapped[list["PathwaySection"]] = relationship(
        "PathwaySection", back_populates="pathway", cascade="all, delete-orphan",
        order_by="PathwaySection.position",
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment", back_populates="pathway", cascade="all, delete-orphan"
    )
    about_blocks: Mapped[list["PathwayAboutBlock"]] = relationship(
        "PathwayAboutBlock", back_populates="pathway", cascade="all, delete-orphan",
        order_by="PathwayAboutBlock.position",
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="pathways_space_slug_unique"),
        Index("ix_pathways_space_position", "space_id", "position"),
    )


class PathwaySection(Base):
    """A named module/section grouping steps within a Pathway."""

    __tablename__ = "pathway_sections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Optional banner image (resolved URL — Media Library upload or pasted https URL)
    banner_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pathway: Mapped[Pathway] = relationship("Pathway", back_populates="sections")
    steps: Mapped[list["PathwayStep"]] = relationship(
        "PathwayStep", back_populates="section", order_by="PathwayStep.section_position"
    )

    __table_args__ = (
        Index("ix_pathway_sections_pathway_position", "pathway_id", "position"),
    )


class PathwayStep(Base):
    """
    A single content unit within a Pathway.
    Steps are ordered by `position` and optionally sequential (gated by prior completion).
    """

    __tablename__ = "pathway_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[StepContentType] = mapped_column(
        SAEnum(StepContentType, name="step_content_type_enum", create_type=True),
        nullable=False,
        default=StepContentType.text,
        server_default="text",
    )
    # Rich text / markdown body for text, reflection, exercise steps
    content_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # URL for video/audio steps
    content_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Display order within the Pathway (used for flat pathways and unsectioned steps)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Display order within a section (null for unsectioned steps)
    section_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional section grouping
    section_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathway_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Per-step feature toggles — default True to preserve existing behaviour
    reflection_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    discussion_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Optional banner image (resolved URL — Media Library upload or pasted https URL)
    banner_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # ------------------------------------------------------------------
    # Pathway drip scheduling — per-step release rule.
    #
    # release_type is a discriminator; the columns below are populated
    # or ignored depending on which type is selected. Every existing
    # step defaults to 'immediate' so no member loses access after
    # migration. Adding new release types later means adding new
    # columns (or reusing these); no restructuring is required.
    #
    #   'immediate'              — always available (default)
    #   'days_after_enrollment'  — releases N days after enrollment
    #                              → release_offset_days
    #   'fixed_date'             — releases at a wall-clock date/time
    #                              → release_at (UTC), release_timezone
    #   'after_previous'         — releases when the previous step
    #                              (by section_position NULLS LAST,
    #                              position) hits `release_previous_state`
    #   'manual'                 — released per member via the
    #                              pathway_step_manual_releases table
    # ------------------------------------------------------------------
    release_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="immediate", server_default="immediate"
    )
    release_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    release_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 'completed' | 'started'. Only 'completed' is enforced today.
    release_previous_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="completed", server_default="completed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pathway: Mapped[Pathway] = relationship("Pathway", back_populates="steps")
    section: Mapped["PathwaySection | None"] = relationship("PathwaySection", back_populates="steps")
    progress_records: Mapped[list["StepProgress"]] = relationship(
        "StepProgress", back_populates="step", cascade="all, delete-orphan"
    )
    resources: Mapped[list["StepResource"]] = relationship(
        "StepResource", back_populates="step", cascade="all, delete-orphan",
        order_by="StepResource.position",
    )
    blocks: Mapped[list["PathwayStepBlock"]] = relationship(
        "PathwayStepBlock", back_populates="step", cascade="all, delete-orphan",
        order_by="PathwayStepBlock.position",
    )
    manual_releases: Mapped[list["PathwayStepManualRelease"]] = relationship(
        "PathwayStepManualRelease", back_populates="step", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("pathway_id", "slug", name="pathway_steps_pathway_slug_unique"),
        Index("ix_pathway_steps_pathway_position", "pathway_id", "position"),
    )


class PathwayStepManualRelease(Base):
    """A caretaker's decision to release a specific step for a specific member.

    Presence of a row means the step is unlocked for that user, regardless
    of the step's other release rule. Rows are idempotent — the unique
    constraint on (step_id, user_id) means "release this again" collides
    on the DB rather than duplicating notification-side effects."""

    __tablename__ = "pathway_step_manual_releases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    step_id: Mapped[str] = mapped_column(
        String, ForeignKey("pathway_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    released_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    step: Mapped[PathwayStep] = relationship(
        "PathwayStep", back_populates="manual_releases", foreign_keys=[step_id],
    )

    __table_args__ = (
        UniqueConstraint("step_id", "user_id", name="uq_pathway_step_manual_release"),
    )


# ---------------------------------------------------------------------------
# Enrollment & Progress
# ---------------------------------------------------------------------------

class Enrollment(Base):
    """A learner's relationship to a specific Pathway."""

    __tablename__ = "enrollments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        SAEnum(EnrollmentStatus, name="enrollment_status_enum", create_type=True),
        nullable=False,
        default=EnrollmentStatus.active,
        server_default="active",
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    pathway: Mapped[Pathway] = relationship("Pathway", back_populates="enrollments")

    __table_args__ = (
        UniqueConstraint("user_id", "pathway_id", name="enrollments_user_pathway_unique"),
        Index("ix_enrollments_user_pathway", "user_id", "pathway_id"),
    )


class StepProgress(Base):
    """
    Records a learner's completion of a specific Step.
    One record per user per step — upserted on completion.
    reflection_text is populated for reflection-type steps.
    """

    __tablename__ = "step_progress"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathway_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = notes saved but step not yet marked complete
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    reflection_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    step: Mapped[PathwayStep] = relationship("PathwayStep", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("user_id", "step_id", name="step_progress_user_step_unique"),
        Index("ix_step_progress_user_step", "user_id", "step_id"),
    )


# ---------------------------------------------------------------------------
# Step Resources
# ---------------------------------------------------------------------------

class StepResource(Base):
    """
    Supplementary resources attached to a pathway step.
    resource_type: link | video | audio | pdf | file
    For uploaded files, url holds the relative path served by /api/uploads/{url}.
    For external links, url holds the full external URL.
    """

    __tablename__ = "step_resources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    step_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathway_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # link | video | audio | pdf | file
    resource_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="link", server_default="link"
    )
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_downloadable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    step: Mapped[PathwayStep] = relationship("PathwayStep", back_populates="resources")

    __table_args__ = (
        Index("ix_step_resources_step_position", "step_id", "position"),
    )


# ---------------------------------------------------------------------------
# Event Series (Gathering Series / Term)
# ---------------------------------------------------------------------------

class EventSeries(Base):
    """A defined term / cohort / program grouping multiple Events.

    Introduced so a purchase can be scoped to *this term* rather than
    to a Pathway that happens to gate the sessions. An ``EventSeries``
    owns the term window (``starts_at`` / ``ends_at``); its
    membership is the set of Events whose ``series_id`` points here.

    Deliberately spare. Ordering + hero art beyond ``cover_image_url``
    are OfferPage concerns, not Series concerns — this table is the
    what/when, not the how-to-present.

    Distinct from ``Event.recurrence_series_id`` (a bulk-create UUID
    tag from migration 034) which just marks "these rows were created
    together". A Series is semantic membership; recurrence_series is
    provenance.
    """

    __tablename__ = "event_series"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Series window. ``starts_at`` is required — every Series begins
    # on some date. ``ends_at`` is nullable so an ongoing weekly
    # circle can be a Series without pretending to end. Finite terms
    # (cohorts / EMBODY Terms) simply set both. A ``term_pass``
    # PaymentOption attached to an ongoing Series can still bound
    # its own AccessPass window via the option's ``term_end_date``.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    # 'draft' | 'published' | 'archived'. String, not enum — mirrors
    # offer_pages.status.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
    )
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set the first time the Series transitions to ``status='published'``;
    # never cleared. Used to decide whether a hard-delete is safe: a
    # Series that has never been public can be removed with attached
    # events detached in-place; a once-published Series is archived
    # instead so historical AccessPass rows keep a resolvable target.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="event_series_space_slug_unique"),
        Index("ix_event_series_space_status", "space_id", "status"),
    )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class Event(Base):
    """Live experiences within a Space: calls, workshops, sessions, replays."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    location_type: Mapped[EventLocationType] = mapped_column(
        SAEnum(EventLocationType, name="event_location_type_enum", create_type=True),
        nullable=False,
        default=EventLocationType.zoom,
        server_default="zoom",
    )
    # Zoom/meet URL, shown to enrolled members only
    location_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Booking fields
    requires_booking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    booking_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    booking_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Recurrence — individual events are generated from a series; grouped by series_id
    recurrence_series_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    recurrence_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Semantic series/term membership — the ``EventSeries`` this event
    # belongs to. Distinct from ``recurrence_series_id`` above, which
    # is a low-level "these rows were created together" tag. A single
    # bulk-create may set both; a hand-created event can be added to
    # an existing series independently.
    series_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("event_series.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Visibility — public events are visible to logged-out/non-member users
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Thumbnail for visual identity in event lists and detail
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Lifecycle status: active | cancelled | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    # Gatherings 2.0 vocabulary — see app/services/gathering_types.py.
    # Every value is normalised through `normalise_access_type` on the
    # way in so legacy strings never leak past the API boundary.
    #
    #   gathering_type       — Circle, Workshop, Retreat, etc. Icon comes from type.
    #   attendance_format    — online | in_person | hybrid.
    #   venue_name/address   — for in_person + hybrid.
    #   access_instructions  — venue arrival / meeting join instructions.
    #   booking_access_type  — free | included_with_collective |
    #                          included_with_pathway | paid_separately |
    #                          invitation_only.  Column widened to 32 in
    #                          migration 079 to fit 'included_with_collective'.
    gathering_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other", server_default="other"
    )
    attendance_format: Mapped[str] = mapped_column(
        String(16), nullable=False, default="online", server_default="online"
    )
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Full private street address — attendee-gated on the API.
    venue_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Member-safe locality (suburb + region), always exposed. Explicit
    # Creator-controlled field introduced in migration 114 to replace
    # the prior derivation from ``venue_address`` (which wasn't robust
    # enough as a privacy boundary). Kept short (160) because it's a
    # locality label, not free-form copy.
    venue_locality: Mapped[str | None] = mapped_column(String(160), nullable=True)
    access_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_access_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default="included_with_collective", server_default="included_with_collective",
    )
    # Required pathway for booking — set when booking_access_type = 'included_with_pathway'
    booking_required_pathway_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pathways.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Standalone paid Gathering: ticket price + currency. Both NULL for
    # non-`paid_separately` events. Currency is uppercase ISO 4217; the
    # MVP whitelist is enforced at the schema/service layer, not by CHECK.
    # A CHECK constraint (see migration 080) guarantees that a published
    # `paid_separately` event has both fields set and price > 0.
    ticket_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ticket_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    space: Mapped[Space] = relationship("Space", back_populates="events")
    bookings: Mapped[list["EventBooking"]] = relationship("EventBooking", back_populates="event", lazy="dynamic")

    __table_args__ = (
        Index("ix_events_space_starts_at", "space_id", "starts_at"),
    )


# ---------------------------------------------------------------------------
# Event Bookings
# ---------------------------------------------------------------------------

class EventBooking(Base):
    """A member's booking for a gathering that requires_booking=True."""

    __tablename__ = "event_bookings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="bookingstatus", create_type=True),
        nullable=False,
        default=BookingStatus.confirmed,
        server_default="confirmed",
    )
    booked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    # Source: 'member' (self-booked) | 'creator_manual' (added by creator/moderator)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Optional note for manual bookings
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Attendance: 'pending' | 'attended' | 'no_show' — NULL until manually set
    attendance_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attendance_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attendance_marked_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # AccessPass credit tracking (Phase B+)
    access_pass_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("access_passes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Standalone paid Gathering: temporary hold expiry + link to the pending
    # PaymentTransaction. Populated only for status='pending_payment' rows
    # tied to a `paid_separately` Gathering. Cleared / left as-is when the
    # webhook flips the row to 'confirmed' or 'cancelled'. See migration 080.
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )
    payment_transaction_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship("Event", back_populates="bookings")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_event_bookings_event_user"),
        Index("ix_event_bookings_event_status", "event_id", "status"),
    )


# ---------------------------------------------------------------------------
# Conversations (Community) — Channels
# ---------------------------------------------------------------------------
# One Collective (Space) → many Channels → many CommunityPosts.
#
# Every Space is initialised (migrations 077 + 078, `ensure_system_channels`
# for new collectives) with two SYSTEM Channels:
#
#   Start Here  (channel_type='start_here', is_system=True)  🌱
#     Welcome + introductions + community guidelines. Cannot be
#     renamed, archived, deleted, or converted.
#
#   Common Room (channel_type='general',    is_system=True)  🏡
#     The everyday shared conversation space for everyone in the
#     collective. Remains the default routing target when a post is
#     created without a `channel_slug` (the internal channel_type
#     stays 'general' so permission logic and existing URLs remain
#     stable). Renamable by the creator but cannot be archived,
#     deleted, or converted.
#
# `channel_type` is a discriminator that also drives icon selection:
#
#   'start_here' 🌱 — every active Space member (system).
#   'general'    🏡 — every active Space member (system, default; the
#                    visible name is "Common Room").
#   'open'       💬 — every active Space member (creator-made).
#   'private'    🔒 — access requires a row in `channel_memberships`.
#   'pathway'    🛤 — access requires an active Enrollment on `pathway_id`.
#   'gathering'  📅 — access requires a confirmed EventBooking on
#                     `gathering_id`.
#
# Icons are strictly type-driven for consistency. `icon_emoji` is
# preserved for edge-cases (custom overrides via direct DB action);
# creators no longer choose icons in the UI.
#
# All access checks funnel through `app.services.channel_permissions`.
# No endpoint should implement its own access logic.

class ConversationChannel(Base):
    __tablename__ = "conversation_channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    channel_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    archived_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    show_in_navigation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    member_posting_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    comments_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    polls_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    scheduling_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    gathering_id: Mapped[str | None] = mapped_column(
        String, nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    memberships: Mapped[list["ChannelMembership"]] = relationship(
        "ChannelMembership", back_populates="channel", cascade="all, delete-orphan",
    )
    posts: Mapped[list["CommunityPost"]] = relationship(
        "CommunityPost", back_populates="channel",
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="uq_conversation_channels_space_slug"),
    )


class ChannelMembership(Base):
    """Presence of a row grants access to a private Channel.

    Not used for start_here / general / open / pathway / gathering
    Channels — those derive access from Space membership, Pathway
    Enrollment, or EventBooking through the permission service.
    """
    __tablename__ = "channel_memberships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversation_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default="member",
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    channel: Mapped[ConversationChannel] = relationship(
        "ConversationChannel", back_populates="memberships",
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_channel_memberships"),
    )


# ---------------------------------------------------------------------------
# Community
# ---------------------------------------------------------------------------

class CommunityPost(Base):
    """A post in a Space's community feed."""

    __tablename__ = "community_posts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Every conversation post belongs to a Channel. Backfilled to the
    # collective's General Channel by migration 076; enforced NOT NULL
    # thereafter so post creation always names a Channel explicitly.
    channel_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversation_channels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    post_type: Mapped[PostType] = mapped_column(
        SAEnum(PostType, name="post_type_enum", create_type=True),
        nullable=False,
        default=PostType.discussion,
        server_default="discussion",
    )
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Community Phase 1 — resolved user IDs parsed from `@Display Name`
    # tokens in the body. Populated by the API layer on write; drives
    # the mention notification without extra parsing at read time.
    mentioned_user_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Community Care Stage 2C — content hidden by an admin action. When
    # `cc_hidden_at` is not null the post is invisible to ordinary
    # members regardless of `is_visible`; caretakers reviewing the case
    # still see it via the admin review surface.
    cc_hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True,
    )
    cc_hidden_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Community Phase 2 — scheduled posts.
    #   publication_status: 'published' (default, immediate) | 'scheduled'
    #   scheduled_for:      when the post should transition to published
    #   scheduling_timezone: display timezone the creator chose
    #   published_at:       actual publish timestamp (backfilled to created_at
    #                       for existing rows)
    #   notifications_processed_at: idempotency marker — non-null means
    #                       new-post + mention notifications have fired
    publication_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="published", server_default="published"
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True,
    )
    scheduling_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    notifications_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    space: Mapped[Space] = relationship("Space", back_populates="community_posts")
    channel: Mapped[ConversationChannel] = relationship(
        "ConversationChannel", back_populates="posts", foreign_keys=[channel_id],
    )
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])  # type: ignore[name-defined]
    comments: Mapped[list["PostComment"]] = relationship(
        "PostComment", back_populates="post", cascade="all, delete-orphan",
        order_by="PostComment.created_at",
    )
    reactions: Mapped[list["PostReaction"]] = relationship(
        "PostReaction", back_populates="post", cascade="all, delete-orphan",
    )
    poll: Mapped["Poll | None"] = relationship(
        "Poll", back_populates="post", cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_community_posts_space_created", "space_id", "created_at"),
        Index("ix_community_posts_space_pinned", "space_id", "is_pinned"),
        # Composite index that supports the publisher's "find due posts"
        # scan without touching the wider `space_id` btree.
        Index(
            "ix_community_posts_status_scheduled",
            "publication_status", "scheduled_for",
        ),
    )


class PostComment(Base):
    """A reply to a community post."""

    __tablename__ = "post_comments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("community_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Community Phase 1 — parent for threaded replies. NULL means this is
    # a top-level comment on the post; otherwise the FK points at the
    # comment this one replies to.
    parent_comment_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("post_comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Community Phase 1 — resolved user IDs parsed from `@Display Name`
    # tokens in the body.
    mentioned_user_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Community Care Stage 2C — mirrors the post-level fields; a hide
    # taken via Community Care is a distinct state from the member's
    # own "Remove" action so reversal can restore cleanly.
    cc_hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True,
    )
    cc_hidden_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    post: Mapped[CommunityPost] = relationship("CommunityPost", back_populates="comments")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])  # type: ignore[name-defined]
    parent: Mapped["PostComment | None"] = relationship(
        "PostComment", remote_side="PostComment.id", foreign_keys=[parent_comment_id],
    )
    reactions: Mapped[list["CommentReaction"]] = relationship(
        "CommentReaction", back_populates="comment", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_post_comments_post_created", "post_id", "created_at"),
    )


class PostReaction(Base):
    """An emoji reaction on a community post."""

    __tablename__ = "post_reactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("community_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    post: Mapped[CommunityPost] = relationship("CommunityPost", back_populates="reactions")

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", "emoji", name="uq_post_reaction"),
    )


class CommentReaction(Base):
    """An emoji reaction on a post comment."""

    __tablename__ = "comment_reactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    comment_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("post_comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    comment: Mapped[PostComment] = relationship("PostComment", back_populates="reactions")

    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", "emoji", name="uq_comment_reaction"),
    )


# ---------------------------------------------------------------------------
# Polls (Community Phase 1) — first-class post type; one row per post
# ---------------------------------------------------------------------------
# Rules enforced at the API layer:
#   - Question (community_post.title) is editable only while no votes exist.
#   - Existing options may not be removed once a vote exists.
#   - Additional options may be appended even after voting starts.
#   - Single-choice enforcement deletes the voter's other votes on this
#     poll when a new choice arrives.

class Poll(Base):
    __tablename__ = "polls"

    post_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("community_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    allow_multiple: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    show_results_before_vote: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    post: Mapped[CommunityPost] = relationship("CommunityPost", back_populates="poll")
    options: Mapped[list["PollOption"]] = relationship(
        "PollOption", back_populates="poll", cascade="all, delete-orphan",
        order_by="PollOption.position",
    )
    votes: Mapped[list["PollVote"]] = relationship(
        "PollVote", back_populates="poll", cascade="all, delete-orphan",
    )


class PollOption(Base):
    __tablename__ = "poll_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    poll_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("polls.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    poll: Mapped[Poll] = relationship("Poll", back_populates="options")

    __table_args__ = (
        Index("ix_poll_options_poll", "poll_id", "position"),
    )


class PollVote(Base):
    __tablename__ = "poll_votes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    poll_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("polls.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    option_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("poll_options.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    poll: Mapped[Poll] = relationship("Poll", back_populates="votes")

    __table_args__ = (
        UniqueConstraint("poll_id", "option_id", "user_id",
                         name="uq_poll_votes_option_user"),
        Index("ix_poll_votes_poll", "poll_id"),
        Index("ix_poll_votes_poll_user", "poll_id", "user_id"),
    )


# ---------------------------------------------------------------------------
# Pathway Step Comments (public/shared discussion per step)
# ---------------------------------------------------------------------------

class StepComment(Base):
    """A public discussion comment on a specific pathway step."""

    __tablename__ = "step_comments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    step_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathway_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    step: Mapped["PathwayStep"] = relationship("PathwayStep")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_step_comments_step_created", "step_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Space Member Notification Preferences
# ---------------------------------------------------------------------------

class SpaceMemberNotificationPrefs(Base):
    """
    Per-member, per-collective notification preferences.
    Row is created on first save; defaults are served without a row.
    """

    __tablename__ = "space_member_notification_prefs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ── Email ──
    weekly_digest_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    daily_digest_email: Mapped[bool]  = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    admin_broadcast_email: Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    gathering_reminder_email: Mapped[bool]  = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    new_post_email: Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    comment_reply_email: Mapped[bool]       = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    pathway_comment_email: Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    new_pathway_email: Mapped[bool]         = mapped_column(Boolean, nullable=False, default=True,  server_default="true")
    # ── Push (TODO: wire up delivery when push system is implemented) ──
    push_enabled: Mapped[bool]              = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    push_gathering_reminders: Mapped[bool]  = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    push_replies: Mapped[bool]              = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    push_announcements: Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "space_id", name="notif_prefs_user_space_unique"),
        Index("ix_notif_prefs_user_space", "user_id", "space_id"),
    )


# ---------------------------------------------------------------------------
# Space Invitations
# ---------------------------------------------------------------------------

class SpaceInvitation(Base):
    """
    A creator-issued invitation for someone to join a Space.
    Stored independently of SpaceMembership because the invitee may not
    have a platform account yet. When they accept and create an account,
    a SpaceMembership is created and the invitation is deleted.

    token is a secret UUID used to build an accept URL: /invites/{token}.

    sent_at=None  → draft (created by creator but email not yet sent)
    sent_at=<ts>  → email/link has been explicitly sent
    """

    __tablename__ = "space_invitations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[SpaceRole] = mapped_column(
        # create_type=False — space_role_enum already exists in the database
        SAEnum(SpaceRole, name="space_role_enum", create_type=False),
        nullable=False,
        default=SpaceRole.learner,
        server_default="learner",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    invited_by_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Payment metadata captured at time of manual add
    payment_option_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_options.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unpaid", server_default="unpaid"
    )
    # sent_at=None → draft; sent_at set → invite link has been explicitly sent
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    space: Mapped[Space] = relationship("Space")

    __table_args__ = (
        UniqueConstraint("space_id", "email", name="space_invitations_space_email_unique"),
        Index("ix_space_invitations_space_id", "space_id"),
    )


class SpaceAccessRequest(Base):
    """
    A request from a user to join a private Space.
    One row per user per space; status transitions: pending → approved | declined.
    On approval, a SpaceMembership is created and status is set to 'approved'.
    """

    __tablename__ = "space_access_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # pending | approved | declined
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # type: ignore[name-defined]
    space: Mapped[Space] = relationship("Space")

    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="space_access_requests_space_user_unique"),
        Index("ix_access_requests_space_user", "space_id", "user_id"),
    )


# ---------------------------------------------------------------------------
# Library — one creator surface over the two asset stores
#
# ``LibraryFolder`` is a flat organisational group that spans both the
# media-asset table (files) and the resource table (links). Every
# folder belongs to exactly one Space; items reference the folder via
# a nullable ``folder_id`` FK on both asset tables so an item can
# also live in "All items" without a folder.
#
# Nesting is deliberately left out of v1. A later migration can add a
# ``parent_folder_id`` without breaking existing rows.
# ---------------------------------------------------------------------------


class LibraryFolder(Base):
    """One creator-named folder in the unified Library.

    Folders are optional — an asset with ``folder_id = NULL`` appears
    in "All items". A folder can hold both file-backed assets
    (``CreatorMediaAsset``) and link-backed items (``SpaceResource``);
    the creator never sees the split.
    """

    __tablename__ = "space_library_folders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_space_library_folders_space_position", "space_id", "position"),
    )


class CreatorMediaAsset(Base):
    """
    A file uploaded by a creator to their collective's media library.

    Files are stored on local disk (uploads/media/{space_slug}/) in V1.
    TODO: Migrate to S3/Cloudflare R2 for production scale — follow the
    same save_file → presigned PUT pattern described in core/storage.py.

    Future join tables for attaching assets to content:
        pathway_step_media   — step_id + asset_id + position
        resource_media       — resource_id + asset_id
        gathering_replay_media — event_id + asset_id
    """

    __tablename__ = "creator_media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional accessibility text shown when the asset is used in places
    # that need alt text (image blocks, covers, banners).
    alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Comma-separated tag list. Lightweight — no separate tag table in v2.
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, name="media_type_enum", create_type=True),
        nullable=False,
    )
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[MediaStatus] = mapped_column(
        SAEnum(MediaStatus, name="media_status_enum", create_type=True),
        nullable=False,
        default=MediaStatus.active,
        server_default="active",
    )
    # Unified Library folder — nullable. When null, appears in "All items".
    folder_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("space_library_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Pathway Step Blocks
# ---------------------------------------------------------------------------

class PathwayStepBlock(Base):
    """
    A single content block within a PathwayStep, Notion-style.

    Block types and their relevant columns:
        heading          — content (text)
        text             — content (markdown)
        image            — media_asset_id OR embed_url (external), caption
        video_embed      — embed_url (YouTube/Vimeo/Loom), caption
        audio            — media_asset_id, caption
        file_download    — media_asset_id, label
        link             — embed_url (href), label, caption (description)
        reflection_prompt — content (prompt text)
        exercise         — content (instructions)
        callout          — content (text), label (callout style: info|tip|warning)
        divider          — no extra columns needed
        embed            — embed_url (allowlisted iframe src), label (title), caption (description)
        button           — embed_url (href), label (button text), caption (style: primary|secondary|outline|subtle),
                           content ("new_tab" | "same_tab" | None for smart default)
        resource         — resource_id (FK to space_resources). The card title/
                           description/type/url are read live from the linked
                           SpaceResource. label = optional title override,
                           caption = optional description override.

    position is zero-indexed within the step.
    """

    __tablename__ = "pathway_step_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    step_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathway_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_type: Mapped[StepBlockType] = mapped_column(
        SAEnum(StepBlockType, name="step_block_type_enum", create_type=True),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Primary text content (heading text, markdown body, prompt, instructions, callout text)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Short label/title (callout style, link label, file download label)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Caption shown below media or link blocks
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # External URL (video embed, link href, external image)
    embed_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # FK to media library asset (image, audio, file_download)
    media_asset_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK to a collective-level SpaceResource. Only used by `resource` blocks.
    # ON DELETE SET NULL so removing a resource leaves the block as a stub
    # rather than nuking the surrounding step content.
    resource_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("space_resources.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optional soft-coloured wrapper. NULL = no container. Values are palette
    # keys (teal | gold | blue | rose | sage | grey | lilac | orange) — same
    # palette used by callout blocks, see frontend/src/lib/calloutPalette.ts.
    container_style: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    step: Mapped[PathwayStep] = relationship("PathwayStep", back_populates="blocks")
    media_asset: Mapped["CreatorMediaAsset | None"] = relationship(
        "CreatorMediaAsset", foreign_keys=[media_asset_id]
    )
    resource: Mapped["SpaceResource | None"] = relationship(
        "SpaceResource", foreign_keys=[resource_id]
    )

    __table_args__ = (
        Index("ix_pathway_step_blocks_step_position", "step_id", "position"),
    )


class PathwayAboutBlock(Base):
    """
    A single content block on an owner's About page.

    Historically Pathway-only (hence the table name), the block was
    generalised in migration 113 so a Gathering Series can carry the
    same rich About content — same block types, same renderer, same
    editor primitives.

    Ownership model
    ---------------
    * ``owner_kind`` + ``owner_id``  → the canonical owner reference
      after migration 113. Values today: ``'pathway'`` or
      ``'event_series'``. New owner kinds slot in without a further
      migration.
    * ``pathway_id`` (nullable) → legacy pointer, still populated for
      pathway-owned rows so existing member-side / SQL readers keep
      working. Series-owned rows carry ``pathway_id=NULL`` and
      ``owner_kind='event_series'``.

    Two indexes: the legacy pathway-only compound index for readers
    that still filter on ``pathway_id`` alone, and the polymorphic
    ``owner_kind, owner_id, position`` index for the new endpoints.
    """

    __tablename__ = "pathway_about_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # Polymorphic owner (migration 113). Both nullable at the model
    # layer because legacy rows created before 113 haven't been
    # backfilled *in memory* if the ORM loads them without a fresh
    # DB read; the migration backfills the columns in-place so DB
    # state is complete. New rows written by application code
    # MUST populate both.
    owner_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Legacy Pathway pointer. Relaxed to nullable in migration 113
    # so Series-owned rows can coexist here.
    pathway_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    block_type: Mapped[StepBlockType] = mapped_column(
        SAEnum(StepBlockType, name="step_block_type_enum", create_type=False),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embed_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    media_asset_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # See PathwayStepBlock.resource_id — same semantics on About blocks.
    resource_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("space_resources.id", ondelete="SET NULL"),
        nullable=True,
    )
    # See PathwayStepBlock.container_style — same semantics on About blocks.
    container_style: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pathway: Mapped["Pathway"] = relationship("Pathway", back_populates="about_blocks")
    media_asset: Mapped["CreatorMediaAsset | None"] = relationship(
        "CreatorMediaAsset", foreign_keys=[media_asset_id]
    )
    resource: Mapped["SpaceResource | None"] = relationship(
        "SpaceResource", foreign_keys=[resource_id]
    )

    __table_args__ = (
        Index("ix_pathway_about_blocks_pathway_position", "pathway_id", "position"),
    )


# ---------------------------------------------------------------------------
# Pathway Entitlements
# ---------------------------------------------------------------------------

class PathwayEntitlement(Base):
    """
    Explicit access record for a member's entitlement to a pathway.

    This is the source of truth for paid pathway access.  Free and included
    pathways do not require a row here — access is derived from the pathway's
    access_type and the user's space membership.  Entitlement rows are needed
    only when access must be explicitly granted, tracked, or revoked:

      manual_grant      — creator grants access directly in Creator Studio
      one_time_purchase — Stripe checkout completes (TODO: wire up)
      subscription      — active Stripe subscription (TODO: wire up)
      admin             — platform admin override

    Stripe fields are present but always NULL until payments go live.
    """

    __tablename__ = "pathway_entitlements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[EntitlementSource] = mapped_column(
        SAEnum(EntitlementSource, name="entitlement_source_enum", create_type=True),
        nullable=False,
    )
    status: Mapped[EntitlementStatus] = mapped_column(
        SAEnum(EntitlementStatus, name="entitlement_status_enum", create_type=True),
        nullable=False,
        default=EntitlementStatus.active,
        server_default="active",
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    granted_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured grant reason — populated when the entitlement was created
    # (or reactivated) by the "Grant access" admin action. Nullable so
    # pre-existing rows remain valid without a backfill; a CHECK
    # constraint enforces the allowed set at the DB layer.
    #
    # Allowed: comp | beta | migration | correction | replacement | other
    grant_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # TODO: Stripe — populate on Stripe Checkout completion
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # TODO: Stripe — populate on Stripe PaymentIntent confirmation
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # TODO: Stripe Connect — populate when subscription entitlement is created
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Finite Payment Plan parent (FIP1, migration 116). Populated when
    # this entitlement was granted by a plan-derived first payment;
    # NULL for legacy pay-in-full / free / manual grants.
    purchase_plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("purchase_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Many-to-many join: a resource can belong to multiple pathways
# (and "General" is represented by an empty pathway set — no rows).
# See migration 062. The composite PK guarantees uniqueness and CASCADE
# means deleting a resource or pathway cleans its references up.
space_resource_pathways = Table(
    "space_resource_pathways",
    Base.metadata,
    Column("resource_id", String, ForeignKey("space_resources.id", ondelete="CASCADE"), primary_key=True),
    Column("pathway_id", String, ForeignKey("pathways.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=False), server_default=func.now(), nullable=False),
)


class SpaceResource(Base):
    """
    A collective-level resource shared by the creator with all members.

    Resources are distinct from StepResource (pathway step attachments).
    They live at the collective level and appear on the Resources tab.

    resource_type values: link | file | replay | guide | template | audio | video | other
    status values: draft | published | archived

    Pathway attachment (Resources v2):
        Use the `pathways` many-to-many relationship below. A resource with
        zero pathways is "General". A resource with one or more pathways
        is shown inside each of those pathway groups on the member view.

    The legacy `scope` and `pathway_id` columns are kept for back-compat
    during the v2 transition and are still written by the API alongside the
    join rows (scope = 'general' when pathways is empty, otherwise
    'pathway' with pathway_id = first attached pathway). They are not
    read by the new code paths. A follow-up migration can drop them once
    the new reads have been verified in production.

    TODO: add access_level field (included | paid | public_preview) when paid resources are needed.
    """

    __tablename__ = "space_resources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid4().hex)
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # link | file | replay | guide | template | audio | video | other
    resource_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="link", server_default="link"
    )
    # External URL for link resources; uploaded file URL for file resources
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # draft | published | archived
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    # LEGACY (Resources v1). Kept readable for rollback; new code reads
    # the `pathways` relationship below. Still written alongside the join
    # rows for back-compat.
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="general", server_default="general"
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )
    # Unified Library folder — nullable. When null, appears in "All items".
    folder_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("space_library_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    space: Mapped["Space"] = relationship("Space", back_populates="resources")
    # Legacy single-pathway relationship — kept for back-compat with the old
    # scope='pathway' path. New code should read `pathways` instead.
    pathway: Mapped["Pathway | None"] = relationship("Pathway", foreign_keys=[pathway_id])
    # Resources v2 many-to-many. Empty list = General.
    pathways: Mapped[list["Pathway"]] = relationship(
        "Pathway",
        secondary=space_resource_pathways,
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_space_resources_space_status", "space_id", "status"),
        Index("ix_space_resources_scope_status", "space_id", "scope", "status"),
    )



# ---------------------------------------------------------------------------
# Manual / Offline Members
# ---------------------------------------------------------------------------

class ManualMemberStatus(str, enum.Enum):
    offline = "offline"       # added manually, no account yet
    managed = "managed"       # promoted — can hold pass/pathway/payment data
    invited = "invited"       # invitation link created, awaiting signup
    converted = "converted"   # linked to a real user account


class ManualMemberPaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    pending = "pending"
    paid = "paid"
    complimentary = "complimentary"


class ManualMember(Base):
    """
    A real-world client/member recorded by a creator before they have
    (or need) a platform account.  No auth credentials are created.
    Completely separate from the User model so email is not required.

    Lifecycle: offline → managed → invited → converted
    - managed: creator has assigned a payment option, payment status, and/or pathway access
    - invited: creator has added an email and created a SpaceInvitation
    - converted: person accepted invite; converted_user_id is set
    """

    __tablename__ = "manual_members"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pass_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_option_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_options.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unpaid", server_default="unpaid"
    )
    status: Mapped[ManualMemberStatus] = mapped_column(
        SAEnum(ManualMemberStatus, name="manual_member_status_enum", create_type=False),
        nullable=False,
        default=ManualMemberStatus.offline,
        server_default="offline",
    )
    converted_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    space: Mapped["Space"] = relationship("Space")

    __table_args__ = (
        Index("ix_manual_members_space", "space_id"),
    )


class ManualMemberPathwayAccess(Base):
    """
    Records that a managed member has been granted access to a specific pathway.
    Used instead of PathwayEntitlement (which requires a User account).
    On conversion to a real user, these records can be migrated to PathwayEntitlements.
    """

    __tablename__ = "manual_member_pathway_access"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    manual_member_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("manual_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("manual_member_id", "pathway_id", name="uq_mm_pathway"),
        Index("ix_mm_pathway_access_member", "manual_member_id"),
    )


# ---------------------------------------------------------------------------

class PathwayUnlockRequirement(Base):
    """
    Join table: which PaymentOptions unlock a pathway with access_type='included_with_offer'.
    A member is granted access if they hold an active AccessPass whose payment_option_id
    matches any row here for the pathway.
    """

    __tablename__ = "pathway_unlock_requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_option_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("payment_options.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("pathway_id", "payment_option_id", name="uq_pathway_unlock_pathway_option"),
        Index("ix_pathway_unlock_pathway_id", "pathway_id"),
    )


# ---------------------------------------------------------------------------
# Build Your Place — configurable option tables (Atlas v1.0 vocabulary)
# ---------------------------------------------------------------------------
# Each of the four option tables shares the same shape so adding a new
# option (a new landscape, a new colour palette, a new element) is a
# single seed row rather than a code change. Seeded initially by
# migration 063 from Atlas Chapter 4.

class LandscapeOption(Base):
    __tablename__ = "landscape_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    whisper: Mapped[str | None] = mapped_column(String(300), nullable=True)
    motif_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class AtmosphereOption(Base):
    __tablename__ = "atmosphere_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ColourStory(Base):
    __tablename__ = "colour_stories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # palette JSON: { primary, secondary, accent, background } — all hex.
    palette: Mapped[dict] = mapped_column(JSON, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ElementOption(Base):
    __tablename__ = "element_options"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    glyph_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


# ---------------------------------------------------------------------------
# Build Your Place — in-progress drafts
# ---------------------------------------------------------------------------
# One draft per creator, held as a single JSON blob so the flow can evolve
# without migrations. When the creator "Opens their collective", we read
# the draft, materialise it into a Space, and delete the draft row.

class SpaceDraft(Base):
    __tablename__ = "space_drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="'{}'")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# The Atlas — curated Locations (Atlas Volume I, v1.1, Chapters Nine + Ten)
# ---------------------------------------------------------------------------
# Managed exclusively by Fresh Collective administrators through the Admin
# Portal. Creators never create or edit Locations — they choose one for
# their collective. A single Location may host many collectives.

class Location(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Short description — the concise reading used everywhere a summary is
    # needed. Multi-paragraph story lives in `atlas_entry`.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The long-form "page in the atlas" — an admin-authored, multi-paragraph
    # entry that may be surfaced across the platform. Plain text with
    # preserved newlines for MVP; a rich editor can slot in later.
    atlas_entry: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'active' visible to creators; 'hidden' available only in admin.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    # ATLAS       — a curated premium Location available to Creator and Pro
    #               collectives.
    # COMMUNITY   — an intentionally smaller, more intimate gathering place
    #               available only to Community (Free) collectives.
    # CORNERSTONE — a foundational Location reserved for Fresh Collective
    #               experiences (e.g. The Atlas Isles). Never surfaced to
    #               creators during Build Your Collective.
    # Any value other than these three is treated as invalid at the API layer.
    location_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ATLAS", server_default="ATLAS"
    )
    # Curated artwork uploaded through the Admin Portal.
    hero_artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Classification — kept as open strings while the taxonomy is being
    # felt out. Enums come later, once the shape of the taxonomy is clear.
    biome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archipelago: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Recommendation metadata — arrays of keys referring to atmosphere_options
    # and colour_stories, plus a free-form theme list.
    preferred_atmospheres: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    preferred_colour_stories: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    preferred_themes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Platform Artwork — a small, named collection of shared interface assets
# ---------------------------------------------------------------------------
# Distinct from Location artwork: these images are owned by the platform
# itself (e.g. the "Explore Collectives" dashboard tile) rather than by
# any Atlas Location. The table is a simple key/value store keyed by a
# stable string identifier; new artwork keys are added as needed without
# schema changes.

class PlatformArtwork(Base):
    __tablename__ = "platform_artwork"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Offer Pages — public presentation layer over existing sellables
# ---------------------------------------------------------------------------
#
# An Offer Page presents one sellable (Pathway in V1; Gathering,
# Space membership, or Bundle in later phases) as a beautiful,
# Fresh Collective-branded public page. It owns hero, invitation,
# what's-included, practical details and FAQs; it does NOT own
# commerce — the CTA deep-links to the existing target-specific
# checkout flow.
#
# Design invariants preserved:
#
#   * ``target_id`` is a plain string with no FK. Future target
#     kinds slot in without a migration.
#   * ``sections_config`` is a JSON blob. Sections have known
#     shapes and the "structured creative freedom" design intent
#     asks Fresh Collective to own the layout; typed inputs per
#     section are enough and let us iterate the shape without
#     migrations.
#   * ``published_at`` is set on the first publish and never
#     cleared. Slug is permanently locked once published_at is
#     non-null so a link a Creator has ever shared publicly always
#     resolves to the same Offer Page.
#
# See ``docs/offer-pages.md`` for the full V1 scope and the
# eventual generic Offer entity's relationship to this presentation
# layer.

class OfferPage(Base):
    """A public presentation page for a sellable in this Collective."""

    __tablename__ = "offer_pages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    promise: Mapped[str | None] = mapped_column(Text, nullable=True)
    hero_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # ``'pathway'`` for V1. Deliberately open-ended so gathering /
    # space_membership / bundle target kinds can slot in without a
    # migration.
    target_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # No FK — see model docstring above.
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    # ``'draft'`` | ``'published'`` | ``'archived'``.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft",
    )
    # Typed sections stored as a dict of ``{ section_key: content }``
    # so shapes can evolve without a migration. See the request /
    # response schemas in ``app/creator/schemas.py`` for the exact
    # shape each section holds.
    sections_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="offer_pages_space_slug_unique"),
        Index("ix_offer_pages_space_status", "space_id", "status"),
        Index("ix_offer_pages_target", "target_kind", "target_id"),
    )
