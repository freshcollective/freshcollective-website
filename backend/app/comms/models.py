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

from datetime import time as _time

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
    SmallInteger,
    String,
    Text,
    Time,
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


# ---------------------------------------------------------------------------
# Preferences, consents, member settings (Milestone 2)
# ---------------------------------------------------------------------------


_CONSENT_KIND_ENUM = Enum(
    "terms_of_service",
    "privacy_policy",
    "marketing",
    "product_updates",
    "creator_broadcast",
    name="communication_consent_kind_enum",
    create_type=False,
)

_CONSENT_STATE_ENUM = Enum(
    "granted",
    "revoked",
    name="communication_consent_state_enum",
    create_type=False,
)


class CommunicationPreference(Base):
    """A single (user × category × channel) deviation from the default.

    Rows are written only when a member deviates from the seeded
    ``communication_channel_defaults``. Effective preference resolution
    is therefore ``preference override, else channel default``.

    Locked channels (``is_locked=True`` on the channel default) refuse
    override writes — the resolution helpers enforce this so callers
    receive a clear error rather than a silent no-op.
    """

    __tablename__ = "communication_preferences"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_categories.key", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(_CHANNEL_ENUM, nullable=False)
    priority: Mapped[str] = mapped_column(_PRIORITY_ENUM, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_key", "channel",
            name="uq_comm_pref_user_category_channel",
        ),
        Index("ix_communication_preferences_user", "user_id"),
    )


class CommunicationConsent(Base):
    """Append-only consent log.

    A new row is inserted for every consent state transition; the
    latest row for (user, consent_kind) is authoritative. Never
    updated in place.

    ``source`` records what captured the consent (form URL, event
    key, migration source). ``evidence_ip_hash`` and
    ``evidence_ua_hash`` store hashed request signals for audit
    without retaining identifying data.
    """

    __tablename__ = "communication_consents"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_kind: Mapped[str] = mapped_column(_CONSENT_KIND_ENUM, nullable=False)
    state: Mapped[str] = mapped_column(_CONSENT_STATE_ENUM, nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_ua_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_communication_consents_user_kind_occurred_at",
            "user_id",
            "consent_kind",
            "occurred_at",
        ),
    )


class CommunicationMemberSettings(Base):
    """Per-user global settings — timezone, quiet hours, digest arrival
    times. One row per user, lazily created the first time the member
    changes anything. All fields are nullable; NULL means "use platform
    default" (see :mod:`app.comms.preferences` for the effective
    defaults).
    """

    __tablename__ = "communication_member_settings"

    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quiet_hours_start_local: Mapped[_time | None] = mapped_column(Time(), nullable=True)
    quiet_hours_end_local: Mapped[_time | None] = mapped_column(Time(), nullable=True)
    daily_digest_send_local_time: Mapped[_time | None] = mapped_column(Time(), nullable=True)
    # ISO weekday: 0=Monday .. 6=Sunday. NULL → platform default (6, Sunday).
    weekly_digest_send_local_weekday: Mapped[int | None] = mapped_column(
        SmallInteger(), nullable=True
    )
    weekly_digest_send_local_time: Mapped[_time | None] = mapped_column(Time(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Intent + delivery (Milestone 4)
# ---------------------------------------------------------------------------


_INTENT_STATE_ENUM = Enum(
    "queued",
    "dispatching",
    "sent",
    "delivered",
    "bounced",
    "complained",
    "failed",
    "suppressed",
    "recorded",
    name="communication_intent_state_enum",
    create_type=False,
)

_DELIVERY_STATUS_ENUM = Enum(
    "pending",
    "accepted",
    "failed",
    name="communication_delivery_status_enum",
    create_type=False,
)


# ── M5a additions ────────────────────────────────────────────────────

_DELIVERY_MODE_ENUM = Enum(
    "shadow",
    "live",
    name="communication_delivery_mode_enum",
    create_type=False,
)

_DIGEST_CADENCE_ENUM = Enum(
    "daily",
    "weekly",
    name="communication_digest_cadence_enum",
    create_type=False,
)

_SUPPRESSION_REASON_ENUM = Enum(
    "bounced",
    "complained",
    "manual",
    "unsubscribed",
    name="communication_suppression_reason_enum",
    create_type=False,
)

_SUPPRESSION_ADDRESS_TYPE_ENUM = Enum(
    "email",
    "phone",
    "push_token",
    name="communication_suppression_address_type_enum",
    create_type=False,
)

_SHADOW_PARITY_ENUM = Enum(
    "match",
    "shadow_extra",
    "legacy_extra",
    "payload_mismatch",
    name="communication_shadow_parity_enum",
    create_type=False,
)


class CommunicationIntent(Base):
    """A decision to deliver a specific event to a specific recipient
    on a specific channel via a specific provider.

    Carries denormalised event context (source/category/topic) for
    efficient history queries, the rendered payload snapshot for
    "what was sent", and template provenance
    (``template_key``/``template_version``/``template_context``) for
    "what was intended" — so re-rendering remains possible as
    templates evolve.

    State machine (enforced in ``app.comms.intents``):

        creation → recorded (priority=silent, terminal)
                 → queued
                    → suppressed (decision layer, terminal)
                    → dispatching (worker claim)
                        → sent → delivered | bounced | complained (webhooks)
                        → failed (terminal)

    The ``dispatching`` state gives crash recovery a foothold — a
    worker that dies mid-send leaves visible evidence, and a future
    recovery job can reset stuck rows.
    """

    __tablename__ = "communication_intents"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(
        String(),
        ForeignKey("communication_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_user_id: Mapped[str | None] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_address: Mapped[str] = mapped_column(Text(), nullable=False)
    source_type: Mapped[str] = mapped_column(_SOURCE_TYPE_ENUM, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    category_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_categories.key", ondelete="RESTRICT"),
        nullable=False,
    )
    topic_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_topics.key", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(_CHANNEL_ENUM, nullable=False)
    priority: Mapped[str] = mapped_column(_PRIORITY_ENUM, nullable=False)
    # Immutable classification (M5a): "shadow" intents are observations
    # of what the M5 routing pipeline would have produced; the worker
    # only ever claims "live" intents. See migration 100's docstring
    # for the architectural invariant.
    delivery_mode: Mapped[str] = mapped_column(
        _DELIVERY_MODE_ENUM,
        nullable=False,
        default="live",
        server_default="live",
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    human_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    payload_subject: Mapped[str] = mapped_column(Text(), nullable=False)
    payload_body_html: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload_body_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload_metadata: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    state: Mapped[str] = mapped_column(_INTENT_STATE_ENUM, nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    dispatching_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


class CommunicationDelivery(Base):
    """One provider attempt against a :class:`CommunicationIntent`.

    Retries produce multiple deliveries per intent (M5+). Each row
    records the RenderedPayload handed to the provider
    (``request_snapshot``) and the ProviderResult it returned
    (``response_snapshot``) — so post-hoc debugging never needs to
    re-derive what was sent.
    """

    __tablename__ = "communication_deliveries"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    intent_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("communication_intents.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    status: Mapped[str] = mapped_column(_DELIVERY_STATUS_ENUM, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    request_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    response_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "intent_id", "attempt_number",
            name="uq_comm_delivery_intent_attempt",
        ),
    )


# ---------------------------------------------------------------------------
# Digest buffer, suppression list, shadow comparisons (Milestone 5a)
# ---------------------------------------------------------------------------


class CommunicationDigestItem(Base):
    """One unit of content that will be aggregated into a future digest.

    When the M5b decision layer resolves a priority of ``daily_digest``
    or ``weekly_digest``, it inserts one row here rather than creating
    a queued intent. The ordinary M4 delivery worker never looks at
    this table — digest items can never be dispatched as individual
    sends. The M13 digest worker consumes unconsumed items in a
    scheduled window, groups by ``(user_id, category_key, cadence)``,
    renders one digest, creates a single ``CommunicationIntent``, and
    marks the items ``consumed_at`` + ``consumed_by_intent_id``.
    """

    __tablename__ = "communication_digest_items"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("communication_categories.key", ondelete="RESTRICT"),
        nullable=False,
    )
    cadence: Mapped[str] = mapped_column(_DIGEST_CADENCE_ENUM, nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(),
        ForeignKey("communication_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(_SOURCE_TYPE_ENUM, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    human_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    item_payload: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    scheduled_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    scheduled_window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    consumed_by_intent_id: Mapped[str | None] = mapped_column(
        String(),
        ForeignKey("communication_intents.id", ondelete="SET NULL"),
        nullable=True,
    )


class CommunicationSuppression(Base):
    """Hard-block list keyed by hashed address.

    Populated automatically by M6's inbound provider webhooks (bounce,
    complaint, unsubscribe) and manually via the admin surface for
    operator quarantine. The M5b decision layer reads this table
    before creating any live intent — a hit produces a
    ``state='suppressed'`` intent with the reason recorded.

    The address itself is never stored — only a SHA-256 hex digest of
    the lowercased, whitespace-stripped value. This preserves lookup
    while ensuring the suppression list doesn't itself become a
    PII inventory.
    """

    __tablename__ = "communication_suppressions"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    address_type: Mapped[str] = mapped_column(
        _SUPPRESSION_ADDRESS_TYPE_ENUM, nullable=False,
    )
    address_value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(_SUPPRESSION_REASON_ENUM, nullable=False)
    source_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "address_type", "address_value_hash",
            name="uq_comm_suppression_address",
        ),
    )


class CommunicationShadowComparison(Base):
    """Reconciliation record produced by the M5c cron. One row per
    event compared, capturing the parity verdict between the legacy
    trigger's output and the M5b routing pipeline's shadow intents.

    Deprecated after every topic is live and dropped in the M15
    cleanup pass. Never referenced by delivery code — this table
    exists solely for cutover confidence.
    """

    __tablename__ = "communication_shadow_comparisons"

    id: Mapped[str] = mapped_column(String(), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("communication_events.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    shadow_intent_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    legacy_notification_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    parity: Mapped[str] = mapped_column(_SHADOW_PARITY_ENUM, nullable=False)
    discrepancy_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    compared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_comm_shadow_comparison_event"),
    )
