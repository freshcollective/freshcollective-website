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
