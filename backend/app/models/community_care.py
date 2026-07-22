"""
SQLAlchemy models for the Community Care domain — Stage 2A.

Shape follows the locked design:

    CommunityCareCase          — the review object
    CommunityCareReport        — each intake event; multiple attach to a case
    CommunityCareCaseEvent     — append-only audit trail (state changes)
    CommunityCareCaseNote      — append-only reviewer notes
    CommunityCareAction        — every action FC takes on a case; three layers
                                 (supportive / protective / resolution)
    MemberRestriction          — scoped, temporary restrictions (posting)

Column definitions and CHECK constraints mirror migration 084 exactly.
Priority is set by admins only — nothing in the model auto-suggests.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enum-shaped string constants — kept in sync with migration 084's CHECKs.
# ---------------------------------------------------------------------------

CASE_STATUSES: tuple[str, ...] = (
    "new", "reviewing", "waiting_info", "action_required",
    "resolved", "closed_no_action",
)
CASE_PRIORITIES: tuple[str, ...] = ("low", "moderate", "high", "immediate")
CASE_CONTENT_TYPES: tuple[str, ...] = (
    "post", "comment", "member_behaviour", "creator_request", "other",
)
REPORT_CATEGORIES: tuple[str, ...] = (
    "harassment_or_bullying", "hate_or_discrimination", "spam_or_scam",
    "unsafe_behaviour", "misinformation", "inappropriate_content",
    "privacy_information", "something_else",
)
CREATOR_REQUEST_SCOPES: tuple[str, ...] = (
    "community_wellbeing", "member_concern", "platform_feature",
    "technical_issue", "community_expectations",
)
REPORTER_KINDS: tuple[str, ...] = ("member", "creator", "admin", "system")
CASE_EVENT_KINDS: tuple[str, ...] = (
    "case_opened", "report_attached", "assigned", "status_changed",
    "priority_changed", "note_added", "information_requested",
    "information_received", "action_issued", "action_reversed",
    "closed", "reopened",
)
ACTION_LAYERS: tuple[str, ...] = ("supportive", "protective", "resolution")
ACTION_KINDS: tuple[str, ...] = (
    # supportive
    "guidance", "reminder", "warning",
    # protective
    "content_hidden", "content_removed_from_public",
    "posting_restriction", "creator_restriction",
    "collective_freeze", "suspension_pending_review",
    # resolution
    "no_further_action",
    "restore_content", "restore_account", "restore_collective",
    "account_cancellation", "creator_account_cancellation",
    "collective_closure_removal",
)
RESTRICTION_KINDS: tuple[str, ...] = ("posting", "creator")
NOTIFICATION_SEVERITIES: tuple[str, ...] = ("routine", "action", "urgent")

# Convenience groupings by layer — used by write-path code.
SUPPORTIVE_KINDS: frozenset[str] = frozenset({"guidance", "reminder", "warning"})
PROTECTIVE_KINDS: frozenset[str] = frozenset({
    "content_hidden", "content_removed_from_public",
    "posting_restriction", "creator_restriction",
    "collective_freeze", "suspension_pending_review",
})
RESOLUTION_KINDS: frozenset[str] = frozenset({
    "no_further_action",
    "restore_content", "restore_account", "restore_collective",
    "account_cancellation", "creator_account_cancellation",
    "collective_closure_removal",
})


def layer_for_kind(kind: str) -> str | None:
    """Return the layer that owns a given action kind, or None if the
    kind is unknown to the model. Used by request validation before we
    write to the DB (defence in depth alongside the CHECK constraints)."""
    if kind in SUPPORTIVE_KINDS:
        return "supportive"
    if kind in PROTECTIVE_KINDS:
        return "protective"
    if kind in RESOLUTION_KINDS:
        return "resolution"
    return None


# ---------------------------------------------------------------------------


class CommunityCareCase(Base):
    """The review object. One row per care case.

    A case aggregates one or more :class:`CommunityCareReport` rows about
    the same subject. Duplicate reports about the same content attach to
    the case's existing open row rather than opening a second.

    Priority is set by admin only — nothing in the model auto-suggests.
    Every state change also writes a :class:`CommunityCareCaseEvent`.
    """

    __tablename__ = "community_care_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    subject_post_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_posts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    subject_comment_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("post_comments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    subject_member_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    subject_creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    subject_space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Point-in-time copy of the reported content. Kept for review and
    # audit even if the source is later edited or removed. Retention:
    # 12 months after case is resolved or closed_no_action.
    content_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    creator_request_scope: Mapped[str | None] = mapped_column(String(48), nullable=True)

    status: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)

    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    assigned_reviewer_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    first_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stage 2D — operational summary. Editable while the case is open,
    # required before any final resolution, included in reporting.
    case_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )


class CommunityCareReport(Base):
    """One intake event. Attached to a case (either freshly opened for
    this report or an existing open case on the same subject)."""

    __tablename__ = "community_care_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String, ForeignKey("community_care_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reporter_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reporter_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    target_post_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_posts.id", ondelete="SET NULL"), nullable=True,
    )
    target_comment_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("post_comments.id", ondelete="SET NULL"), nullable=True,
    )
    target_member_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    category: Mapped[str] = mapped_column(String(48), nullable=False)
    reporter_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )


class CommunityCareCaseEvent(Base):
    """Append-only history of state changes on a case. Never mutated
    once written."""

    __tablename__ = "community_care_case_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String, ForeignKey("community_care_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    previous_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_content_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CommunityCareCaseNote(Base):
    """Reviewer notes on a case. Append-only, admin-only."""

    __tablename__ = "community_care_case_notes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String, ForeignKey("community_care_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )


class CommunityCareAction(Base):
    """Every action Fresh Collective takes on a case.

    One row per action; the ``layer`` column classifies it as one of
    the three domains:

    - ``supportive`` — educational; ``guidance``, ``reminder``, ``warning``
    - ``protective`` — temporary, pending review; hides, restrictions,
      freezes, suspension pending review
    - ``resolution`` — post-review outcome; restores, cancellations,
      collective closure

    Rows are never mutated except to fill reversal fields (protective
    layer only). Resolution rows are terminal — reversing a resolution
    is a new case, never an edit on the original.
    """

    __tablename__ = "community_care_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String, ForeignKey("community_care_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)

    issued_by_admin_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Public-facing message included in notification body. Deliberately
    # separate from `internal_note` so the composer function can never
    # accidentally leak reviewer thoughts to recipients.
    explanation_to_recipient: Mapped[str | None] = mapped_column(Text, nullable=True)

    affected_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    affected_space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True,
    )
    affected_post_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_posts.id", ondelete="SET NULL"), nullable=True,
    )
    affected_comment_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("post_comments.id", ondelete="SET NULL"), nullable=True,
    )

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    reversed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    reversed_by_admin_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reversal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    restores_action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )


class MemberRestriction(Base):
    """Scoped, temporary restriction on a member.

    Currently supports ``kind='posting'`` (blocks new posts, comments,
    reactions). Login and reads are unaffected — this is a light-touch
    layer that sits below account suspension.
    """

    __tablename__ = "member_restrictions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by_admin_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    action_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_care_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    reversed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
