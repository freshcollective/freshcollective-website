"""
SQLAlchemy model + Python enumerations for the Fresh Collective Activity
Engine.

This is the platform-wide event hub. Every feature that used to send an
email or write a notification directly now creates an Activity Event
through ``app.services.activity_service.ActivityService.create``. The
delivery channels (Notification Centre API today; email digests, push,
"My World" history, automation engine tomorrow) subscribe to those
events and never inspect feature internals.

The existing ``notifications`` table + service is intentionally left in
place — this migration adds the Activity Engine alongside it. Existing
UI, delivery, and callers keep working. New features build against
ActivityService only.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# Categories, priorities, and the event-type catalogue
# ---------------------------------------------------------------------------

class ActivityCategory(str, enum.Enum):
    """Broad grouping of activity events. Used by delivery channels to
    filter what a user has opted into (e.g. email digest for
    ``gatherings`` but not ``account``)."""

    personal      = "personal"
    conversations = "conversations"
    gatherings    = "gatherings"
    pathways      = "pathways"
    collective    = "collective"
    account       = "account"


class ActivityPriority(str, enum.Enum):
    """Priority influences future delivery behaviour:

    - ``critical``  → immediate delivery, always
    - ``important`` → default delivery, respects quiet hours
    - ``standard``  → digestible; rolled into batches by default
    - ``passive``   → history-only; never emailed unless user opts in
    """

    critical  = "critical"
    important = "important"
    standard  = "standard"
    passive   = "passive"


class ActivityType(str, enum.Enum):
    """The canonical event-type catalogue.

    Adding a new type: append it here, then extend both
    ``CATEGORY_OF`` and ``DEFAULT_PRIORITY_OF`` below. Feature code
    references types by symbol, not by string, so a rename here is
    caught at import time.
    """

    # ── Personal ──────────────────────────────────────────────────────
    reply_received           = "reply_received"
    mention_received         = "mention_received"
    private_message_received = "private_message_received"
    booking_confirmed        = "booking_confirmed"
    payment_successful       = "payment_successful"
    payment_failed           = "payment_failed"

    # ── Conversations ─────────────────────────────────────────────────
    conversation_created  = "conversation_created"
    conversation_replied  = "conversation_replied"
    conversation_followed = "conversation_followed"
    reaction_received     = "reaction_received"

    # ── Gatherings ────────────────────────────────────────────────────
    gathering_created          = "gathering_created"
    gathering_booking          = "gathering_booking"
    gathering_reminder         = "gathering_reminder"
    gathering_changed          = "gathering_changed"
    gathering_cancelled        = "gathering_cancelled"
    gathering_replay_available = "gathering_replay_available"

    # ── Pathways ──────────────────────────────────────────────────────
    pathway_published     = "pathway_published"
    pathway_step_released = "pathway_step_released"
    pathway_completed     = "pathway_completed"
    pathway_comment       = "pathway_comment"

    # ── Collective ────────────────────────────────────────────────────
    member_joined         = "member_joined"
    member_left           = "member_left"
    creator_announcement  = "creator_announcement"
    resource_added        = "resource_added"
    resource_updated      = "resource_updated"

    # ── Account ───────────────────────────────────────────────────────
    subscription_started   = "subscription_started"
    subscription_renewed   = "subscription_renewed"
    subscription_cancelled = "subscription_cancelled"
    password_changed       = "password_changed"
    creator_payout         = "creator_payout"
    invitation_received    = "invitation_received"
    invitation_accepted    = "invitation_accepted"


CATEGORY_OF: dict[ActivityType, ActivityCategory] = {
    # personal
    ActivityType.reply_received:           ActivityCategory.personal,
    ActivityType.mention_received:         ActivityCategory.personal,
    ActivityType.private_message_received: ActivityCategory.personal,
    ActivityType.booking_confirmed:        ActivityCategory.personal,
    ActivityType.payment_successful:       ActivityCategory.personal,
    ActivityType.payment_failed:           ActivityCategory.personal,
    # conversations
    ActivityType.conversation_created:  ActivityCategory.conversations,
    ActivityType.conversation_replied:  ActivityCategory.conversations,
    ActivityType.conversation_followed: ActivityCategory.conversations,
    ActivityType.reaction_received:     ActivityCategory.conversations,
    # gatherings
    ActivityType.gathering_created:          ActivityCategory.gatherings,
    ActivityType.gathering_booking:          ActivityCategory.gatherings,
    ActivityType.gathering_reminder:         ActivityCategory.gatherings,
    ActivityType.gathering_changed:          ActivityCategory.gatherings,
    ActivityType.gathering_cancelled:        ActivityCategory.gatherings,
    ActivityType.gathering_replay_available: ActivityCategory.gatherings,
    # pathways
    ActivityType.pathway_published:     ActivityCategory.pathways,
    ActivityType.pathway_step_released: ActivityCategory.pathways,
    ActivityType.pathway_completed:     ActivityCategory.pathways,
    ActivityType.pathway_comment:       ActivityCategory.pathways,
    # collective
    ActivityType.member_joined:        ActivityCategory.collective,
    ActivityType.member_left:          ActivityCategory.collective,
    ActivityType.creator_announcement: ActivityCategory.collective,
    ActivityType.resource_added:       ActivityCategory.collective,
    ActivityType.resource_updated:     ActivityCategory.collective,
    # account
    ActivityType.subscription_started:   ActivityCategory.account,
    ActivityType.subscription_renewed:   ActivityCategory.account,
    ActivityType.subscription_cancelled: ActivityCategory.account,
    ActivityType.password_changed:       ActivityCategory.account,
    ActivityType.creator_payout:         ActivityCategory.account,
    ActivityType.invitation_received:    ActivityCategory.account,
    ActivityType.invitation_accepted:    ActivityCategory.account,
}


# Default priority per event type. Callers may override on create() but
# most events resolve here.
DEFAULT_PRIORITY_OF: dict[ActivityType, ActivityPriority] = {
    # ── Critical ──────────────────────────────────────────────────────
    ActivityType.payment_failed:           ActivityPriority.critical,
    ActivityType.gathering_cancelled:      ActivityPriority.critical,
    ActivityType.invitation_received:      ActivityPriority.critical,
    ActivityType.subscription_cancelled:   ActivityPriority.critical,
    ActivityType.password_changed:         ActivityPriority.critical,

    # ── Important ─────────────────────────────────────────────────────
    ActivityType.reply_received:           ActivityPriority.important,
    ActivityType.mention_received:         ActivityPriority.important,
    ActivityType.private_message_received: ActivityPriority.important,
    ActivityType.booking_confirmed:        ActivityPriority.important,
    ActivityType.payment_successful:       ActivityPriority.important,
    ActivityType.gathering_changed:        ActivityPriority.important,
    ActivityType.gathering_reminder:       ActivityPriority.important,
    ActivityType.pathway_step_released:    ActivityPriority.important,
    ActivityType.invitation_accepted:      ActivityPriority.important,

    # ── Standard ──────────────────────────────────────────────────────
    ActivityType.conversation_created:     ActivityPriority.standard,
    ActivityType.conversation_replied:     ActivityPriority.standard,
    ActivityType.conversation_followed:    ActivityPriority.standard,
    ActivityType.reaction_received:        ActivityPriority.standard,
    ActivityType.gathering_created:        ActivityPriority.standard,
    ActivityType.gathering_booking:        ActivityPriority.standard,
    ActivityType.gathering_replay_available: ActivityPriority.standard,
    ActivityType.pathway_published:        ActivityPriority.standard,
    ActivityType.pathway_comment:          ActivityPriority.standard,
    ActivityType.member_joined:            ActivityPriority.standard,
    ActivityType.member_left:              ActivityPriority.standard,
    ActivityType.creator_announcement:     ActivityPriority.standard,
    ActivityType.resource_added:           ActivityPriority.standard,
    ActivityType.resource_updated:         ActivityPriority.standard,
    ActivityType.subscription_started:     ActivityPriority.standard,
    ActivityType.subscription_renewed:     ActivityPriority.standard,

    # ── Passive ───────────────────────────────────────────────────────
    ActivityType.pathway_completed:        ActivityPriority.passive,
    ActivityType.creator_payout:           ActivityPriority.passive,
}


assert set(CATEGORY_OF.keys())        == set(ActivityType), "CATEGORY_OF drifted from ActivityType"
assert set(DEFAULT_PRIORITY_OF.keys()) == set(ActivityType), "DEFAULT_PRIORITY_OF drifted from ActivityType"


# ---------------------------------------------------------------------------
# Recent Moments whitelist
#
# The Activity Engine is the platform's event ledger; Recent Moments is a
# curated view of that ledger. This set enumerates every event type that
# belongs on the "Recent Moments" surface (Your World dashboard section,
# collective sidebar panel, future digest).
#
# Everything not in this set is either:
#   * Attention Required — recorded but surfaced elsewhere (payment
#     failure, gathering cancelled, invitation received, subscription
#     cancelled, password changed, gathering reminder, gathering changed).
#   * History Only — recorded for audit / receipts / future features
#     but never surfaced in Recent Moments (payments, subscription
#     started/renewed, creator payout, resource metadata edits, silent
#     platform events).
#
# Guidance for writers (repeated in the service): if an event is not a
# meaningful community moment, prefer NOT creating an Activity row at
# all. Reactions, private messages, silent renewals and creator-owned
# content edits should live in their own systems (message inbox,
# billing, audit log) rather than in the activities table.
# ---------------------------------------------------------------------------

RECENT_MOMENTS: frozenset[ActivityType] = frozenset({
    # Personal — meaningful things someone did TO you
    ActivityType.reply_received,
    ActivityType.mention_received,
    ActivityType.booking_confirmed,

    # Conversations — community life
    ActivityType.conversation_created,
    ActivityType.conversation_replied,   # writer scopes audience to OP + participants

    # Gatherings — scheduling + turnout + aftermath
    ActivityType.gathering_created,
    ActivityType.gathering_booking,      # aggregate for the Creator at read time
    ActivityType.gathering_replay_available,

    # Pathways — journeys unfolding
    ActivityType.pathway_published,
    ActivityType.pathway_step_released,  # writer scopes to enrolled members
    ActivityType.pathway_completed,      # Creator-facing; writer skips actor's own row
    ActivityType.pathway_comment,        # writer scopes to step author + prior commenters

    # Collective — growth + creator voice
    ActivityType.member_joined,
    ActivityType.creator_announcement,
    ActivityType.resource_added,

    # Account — one warm moment; everything else is receipt / audit
    ActivityType.invitation_accepted,    # inviter-facing
})


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class Activity(Base):
    """One row per recipient per event.

    Fan-out (a single feature-side event that fires for many recipients)
    creates one row per recipient. That keeps read/unread/emailed state
    per-user without a join table and lets delivery channels query with
    a simple ``WHERE recipient_user_id = ...``.

    Foreign keys to subject entities are all nullable + ON DELETE SET
    NULL: activities are a historical record and should survive the
    deletion of the thing they describe.
    """

    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # ── Event identity ──────────────────────────────────────────────
    # Stored as string, not enum, so migrations can add new event types
    # without an ALTER TYPE. Validation lives in Python (ActivityType).
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category:   Mapped[str] = mapped_column(String(32), nullable=False)
    priority:   Mapped[str] = mapped_column(String(16), nullable=False)

    # ── Who ──────────────────────────────────────────────────────────
    # actor  = who performed the action (may be null for system events)
    # recipient = the user this row is delivered to
    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    recipient_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )

    # ── Subject entities (all nullable) ─────────────────────────────
    collective_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True,
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True,
    )
    gathering_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("events.id", ondelete="SET NULL"), nullable=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("community_posts.id", ondelete="SET NULL"), nullable=True,
    )
    resource_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("space_resources.id", ondelete="SET NULL"), nullable=True,
    )

    # ── Human-readable payload ──────────────────────────────────────
    # Everything a delivery channel needs to render the event without a
    # further DB round-trip: title, message, url, actor_name, etc.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── Delivery state timestamps ───────────────────────────────────
    read_at:     Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    emailed_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    pushed_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # ── Timestamps ──────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        # Recipient-first indexes: every read query starts with the
        # signed-in user, filters unread / recent, orders by created_at
        # desc, and paginates.
        Index(
            "ix_activities_recipient_created",
            "recipient_user_id", "created_at",
        ),
        Index(
            "ix_activities_recipient_unread",
            "recipient_user_id", "read_at",
        ),
        # Collective feed (Creator Dashboard) — filter by collective +
        # newest-first.
        Index(
            "ix_activities_collective_created",
            "collective_id", "created_at",
        ),
    )
