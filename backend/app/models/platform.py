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
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment", back_populates="pathway", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="pathways_space_slug_unique"),
        Index("ix_pathways_space_position", "space_id", "position"),
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
    # Display order within the Pathway
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

    pathway: Mapped[Pathway] = relationship("Pathway", back_populates="steps")
    progress_records: Mapped[list["StepProgress"]] = relationship(
        "StepProgress", back_populates="step", cascade="all, delete-orphan"
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
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    reflection_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    step: Mapped[PathwayStep] = relationship("PathwayStep", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("user_id", "step_id", name="step_progress_user_step_unique"),
        Index("ix_step_progress_user_step", "user_id", "step_id"),
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
    comments: Mapped[list["PostComment"]] = relationship(
        "PostComment", back_populates="post", cascade="all, delete-orphan"
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

    __table_args__ = (
        Index("ix_post_comments_post_created", "post_id", "created_at"),
    )
