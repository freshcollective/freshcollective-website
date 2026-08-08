"""Pydantic response schemas for the comms surface.

Admin: event log browse + registry (Milestone 1).
Member: preference matrix, consent state, member settings (Milestone 2).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminEventRow(BaseModel):
    """Compact row for the events list view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence_number: int
    event_type: str
    topic_key: str
    category_key: str
    source_type: str
    source_id: str | None
    priority_hint: str
    actor_user_id: str | None
    subject_type: str | None
    subject_id: str | None
    dedupe_key: str | None
    occurred_at: datetime


class AdminEventDetail(AdminEventRow):
    """Full detail — adds context + payload."""

    context: dict[str, Any]
    payload: dict[str, Any]


class AdminEventListResponse(BaseModel):
    items: list[AdminEventRow]
    total: int
    limit: int
    offset: int


class AdminRegisteredEventType(BaseModel):
    """Diagnostic — every registered event_type and its default topic /
    priority. Useful when planning which types are wired up.
    """

    event_type: str
    topic: str
    category: str
    default_priority: str


class AdminRegistryResponse(BaseModel):
    events: list[AdminRegisteredEventType]


# ---------------------------------------------------------------------------
# Member — preferences, consents, member settings (Milestone 2)
# ---------------------------------------------------------------------------


class PreferenceCell(BaseModel):
    """One (category × channel) cell in the member's matrix."""

    channel: str
    priority: str
    is_locked: bool
    # "override" when a preference row wins; "default" when the seed
    # channel default wins.
    origin: Literal["override", "default"]


class PreferenceCategoryRow(BaseModel):
    category_key: str
    category_label: str
    category_description: str
    sort_order: int
    is_critical: bool
    cells: list[PreferenceCell]


class MemberSettingsResponse(BaseModel):
    """Timezone + quiet-hours + digest arrival times. Every field is
    nullable; NULL means "use platform default".
    """

    timezone: str | None
    quiet_hours_start_local: time | None
    quiet_hours_end_local: time | None
    daily_digest_send_local_time: time | None
    weekly_digest_send_local_weekday: int | None
    weekly_digest_send_local_time: time | None


class ConsentStateRow(BaseModel):
    """The latest state for one consent kind."""

    consent_kind: str
    state: Literal["granted", "revoked"] | None = Field(
        default=None,
        description=(
            "None when the user has never interacted with this consent kind."
        ),
    )
    policy_version: str | None = None
    occurred_at: datetime | None = None


class MyPreferencesResponse(BaseModel):
    """Full member-facing response — categories, member settings, consents."""

    categories: list[PreferenceCategoryRow]
    member_settings: MemberSettingsResponse
    consents: list[ConsentStateRow]


# ── PATCH bodies ────────────────────────────────────────────────────


class PreferenceUpdate(BaseModel):
    category_key: str
    channel: str
    # ``None`` clears the override, letting the category default apply.
    priority: str | None


class MemberSettingsPatch(BaseModel):
    """Fields provided are updated; fields omitted are unchanged.
    Provide ``None`` for a field to reset it to the platform default.
    Unlike a partial dict this preserves the "not passed" vs "set to
    NULL" distinction via Pydantic's ``model_fields_set``.
    """

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = None
    quiet_hours_start_local: time | None = None
    quiet_hours_end_local: time | None = None
    daily_digest_send_local_time: time | None = None
    weekly_digest_send_local_weekday: int | None = None
    weekly_digest_send_local_time: time | None = None


class ConsentUpdate(BaseModel):
    consent_kind: str
    state: Literal["granted", "revoked"]
    # Populated by the endpoint from the request when applicable.
    policy_version: str | None = None


class MyPreferencesPatch(BaseModel):
    """Partial update payload. Any of the three sub-lists may be
    omitted; provided items are applied together in one transaction.
    """

    model_config = ConfigDict(extra="forbid")

    preferences: list[PreferenceUpdate] | None = None
    member_settings: MemberSettingsPatch | None = None
    consents: list[ConsentUpdate] | None = None


# ---------------------------------------------------------------------------
# Intent + delivery surfaces (Milestone 4)
# ---------------------------------------------------------------------------


class DeliveryAttemptSummary(BaseModel):
    """One provider attempt summary — the sparse shape the history
    endpoint returns per intent.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_key: str
    attempt_number: int
    status: str
    provider_message_id: str | None
    error_class: str | None
    attempted_at: datetime
    settled_at: datetime | None


class DeliveryAttemptDetail(DeliveryAttemptSummary):
    """Full delivery record — includes error_detail + snapshots.
    Admin-only."""

    request_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any]
    error_detail: str | None


class HistoryIntentRow(BaseModel):
    """One entry in the member's communications history."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_id: str | None
    category_key: str
    channel: str
    priority: str
    human_reason: str
    subject: str = Field(alias="payload_subject")
    state: str
    scheduled_for: datetime | None
    created_at: datetime
    sent_at: datetime | None
    terminal_at: datetime | None
    deliveries: list[DeliveryAttemptSummary] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    items: list[HistoryIntentRow]
    total: int
    limit: int
    offset: int


class AdminIntentRow(BaseModel):
    """Compact row for the admin intents list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str | None
    recipient_user_id: str | None
    recipient_address: str
    source_type: str
    source_id: str | None
    category_key: str
    topic_key: str
    channel: str
    priority: str
    provider_key: str
    template_key: str | None
    template_version: str | None
    human_reason: str
    payload_subject: str
    state: str
    suppression_reason: str | None
    scheduled_for: datetime | None
    created_at: datetime
    queued_at: datetime | None
    dispatching_at: datetime | None
    sent_at: datetime | None
    terminal_at: datetime | None


class AdminIntentDetail(AdminIntentRow):
    """Intent + all its delivery attempts + full payload + template
    context. Everything an admin needs for debugging."""

    payload_body_html: str | None
    payload_body_text: str | None
    payload_metadata: dict[str, Any]
    template_context: dict[str, Any] | None
    deliveries: list[DeliveryAttemptDetail]


class AdminIntentListResponse(BaseModel):
    items: list[AdminIntentRow]
    total: int
    limit: int
    offset: int


class AdminDeliveryRow(BaseModel):
    """One row in the admin deliveries list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    intent_id: str
    provider_key: str
    attempt_number: int
    status: str
    provider_message_id: str | None
    error_class: str | None
    attempted_at: datetime
    settled_at: datetime | None


class AdminDeliveryListResponse(BaseModel):
    items: list[AdminDeliveryRow]
    total: int
    limit: int
    offset: int


class DispatchResultResponse(BaseModel):
    """Return shape for the internal dispatch endpoint."""

    processed: list[str]
    count: int


# ---------------------------------------------------------------------------
# Shadow parity (Milestone 5c)
# ---------------------------------------------------------------------------


class ShadowParityDayRow(BaseModel):
    day: str                           # ISO date, UTC calendar
    events_observed: int
    comparisons_recorded: int
    matches: int
    mismatches_by_dim: dict[str, int]
    day_qualifies: bool


class ShadowParityDiscrepancy(BaseModel):
    event_id: str
    parity: str
    detail: str | None = None
    compared_at: str                    # ISO


class ShadowParityReport(BaseModel):
    scope_kind: str                     # "topic" | "category"
    scope_key: str
    window_days: int
    events_observed: int
    comparisons_recorded: int
    parity_pct: float
    consecutive_perfect_days: int
    eligible_for_live: bool
    days: list[ShadowParityDayRow]
    recent_discrepancies: list[ShadowParityDiscrepancy]


class ReconcilerResultResponse(BaseModel):
    compared: list[str]
    count: int
    skipped_no_comparator: list[str]
    duplicate_skipped: int
