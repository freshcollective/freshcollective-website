"""SQLAlchemy models for the Communications Layer (Milestone 1).

Four tables land in this milestone:

  * ``CommunicationTopic``           — internal engineering topic registry
  * ``CommunicationCategory``        — nine member-facing categories
  * ``CommunicationChannelDefault``  — per (category × channel) default
  * ``CommunicationEvent``           — the immutable event log

Later milestones add ``CommunicationIntent``, ``CommunicationDelivery``,
``CommunicationPreference``, ``CommunicationConsent``, and provider /
broadcast / digest tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------


class CommunicationTopic(Base):
    """Internal engineering topic. Domain code rarely names these
    directly — the registry resolves an event_type to its topic.
    """

    __tablename__ = "communication_topics"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )


class CommunicationCategory(Base):
    """Member-facing category (nine total). This is what appears in
    /settings/communications and in every rendered communication footer.
    Multiple internal topics map to a single category.
    """

    __tablename__ = "communication_categories"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Locked-in-app categories cannot be silenced by members. Currently:
    # account, purchases, safety.
    is_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )


# Native enum types — instantiated once at module scope and reused across
# ``CommunicationEvent`` and (later milestones) intent/delivery tables. The
# ``create_type=False`` guard means SQLAlchemy will not try to re-create
# the type; migration 097 owns creation and drop.
_SOURCE_TYPE_ENUM = Enum(
    "fresh_collective",
    "collective",
    "creator",
    name="communication_source_type_enum",
    create_type=False,
)

_CHANNEL_ENUM = Enum(
    "in_app",
    "email_transactional",
    "email_marketing",
    "push",
    "webhook_outbound",
    name="communication_channel_enum",
    create_type=False,
)

_PRIORITY_ENUM = Enum(
    "immediate",
    "scheduled",
    "daily_digest",
    "weekly_digest",
    "silent",
    name="communication_priority_enum",
    create_type=False,
)


class CommunicationChannelDefault(Base):
    """One row per (category × channel) declaring:
      * the default enabled state (per new member),
      * whether that combination is locked (member cannot silence it).

    Preferences created in Milestone 2 start from these defaults.
    """

    __tablename__ = "communication_channel_defaults"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    category_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_categories.key", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(_CHANNEL_ENUM, nullable=False)
    default_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "category_key", "channel", name="uq_channel_default_category_channel"
        ),
    )


# ---------------------------------------------------------------------------
# The event log
# ---------------------------------------------------------------------------


class CommunicationEvent(Base):
    """An immutable record that something communication-worthy happened.

    Events are written by ``app.comms.emit()``. Milestone 1 does no
    routing, decisioning, or delivery — the event is persisted and the
    caller returns. Later milestones fanout to intents and providers.

    Fields worth noting:

    * ``source_type`` + ``source_id`` — the Communication Source
      (Refinement 3). ``fresh_collective`` sources have NULL id;
      ``collective`` and ``creator`` sources carry an id.
    * ``topic_key`` — the internal topic (engineering vocabulary).
    * ``category_key`` — the member-facing category, resolved at emit
      time from the topic via ``TOPIC_TO_CATEGORY``. Denormalised for
      efficient history queries.
    * ``priority_hint`` — the pacing default for this event; the
      decision layer may override per recipient.
    * ``payload`` — structured facts (IDs, counts, structured booleans).
      Never rendered content. Rendering pulls fresh data at delivery
      time so redacted / deleted material never leaks.
    * ``dedupe_key`` — optional; the unique index on
      (event_type, dedupe_key) makes a repeat emit a no-op.
    """

    __tablename__ = "communication_events"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    sequence_number: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False, start=1),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    topic_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_topics.key", ondelete="RESTRICT"),
        nullable=False,
    )
    category_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_categories.key", ondelete="RESTRICT"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(_SOURCE_TYPE_ENUM, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    priority_hint: Mapped[str] = mapped_column(_PRIORITY_ENUM, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    context: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    payload: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_communication_events_event_type_occurred_at",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_communication_events_subject",
            "subject_type",
            "subject_id",
        ),
        Index(
            "ix_communication_events_source",
            "source_type",
            "source_id",
        ),
        Index(
            "ix_communication_events_sequence_number",
            "sequence_number",
            unique=True,
        ),
        # Note: the partial unique index on (event_type, dedupe_key)
        # WHERE dedupe_key IS NOT NULL is created in migration 097 via
        # raw SQL — SQLAlchemy's Index() does not model partial
        # PostgreSQL indexes portably.
    )
