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
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
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


class EnrollmentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"


class EventLocationType(str, enum.Enum):
    zoom = "zoom"
    in_person = "in_person"
    async_recorded = "async_recorded"


class PostType(str, enum.Enum):
    prompt = "prompt"
    reflection = "reflection"
    discussion = "discussion"
    announcement = "announcement"


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
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    status: Mapped[SpaceStatus] = mapped_column(
        SAEnum(SpaceStatus, name="space_status_enum", create_type=True),
        nullable=False,
        default=SpaceStatus.active,
        server_default="active",
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
    # Display order within the Space
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Access / pricing — see access_type values: free | included | one_time | subscription
    access_type: Mapped[str] = mapped_column(String(20), nullable=False, default="free", server_default="free")
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

    __table_args__ = (
        UniqueConstraint("pathway_id", "slug", name="pathway_steps_pathway_slug_unique"),
        Index("ix_pathway_steps_pathway_position", "pathway_id", "position"),
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

    __table_args__ = (
        Index("ix_events_space_starts_at", "space_id", "starts_at"),
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
    post_type: Mapped[PostType] = mapped_column(
        SAEnum(PostType, name="post_type_enum", create_type=True),
        nullable=False,
        default=PostType.discussion,
        server_default="discussion",
    )
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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

    space: Mapped[Space] = relationship("Space", back_populates="community_posts")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])  # type: ignore[name-defined]
    comments: Mapped[list["PostComment"]] = relationship(
        "PostComment", back_populates="post", cascade="all, delete-orphan",
        order_by="PostComment.created_at",
    )

    __table_args__ = (
        Index("ix_community_posts_space_created", "space_id", "created_at"),
        Index("ix_community_posts_space_pinned", "space_id", "is_pinned"),
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

    post: Mapped[CommunityPost] = relationship("CommunityPost", back_populates="comments")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_post_comments_post_created", "post_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Space Invitations
# ---------------------------------------------------------------------------

class SpaceInvitation(Base):
    """
    A creator-issued invitation for someone to join a Space.
    Stored independently of SpaceMembership because the invitee may not
    have a platform account yet. When they accept and create an account,
    a SpaceMembership is created and the invitation can be deleted or
    marked accepted by a future migration.
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    space: Mapped[Space] = relationship("Space")

    __table_args__ = (
        UniqueConstraint("space_id", "email", name="space_invitations_space_email_unique"),
        Index("ix_space_invitations_space_id", "space_id"),
    )


# ---------------------------------------------------------------------------
# Media Library
# ---------------------------------------------------------------------------

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

    __table_args__ = (
        Index("ix_pathway_step_blocks_step_position", "step_id", "position"),
    )


class PathwayAboutBlock(Base):
    """
    A single content block on a Pathway's About/preview page.

    Mirrors PathwayStepBlock column-for-column but is keyed to a pathway
    rather than a step.  Same block types and rendering rules apply.
    """

    __tablename__ = "pathway_about_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pathway_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="CASCADE"),
        nullable=False,
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

    __table_args__ = (
        Index("ix_pathway_about_blocks_pathway_position", "pathway_id", "position"),
    )
