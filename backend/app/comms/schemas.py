"""Pydantic response schemas for the admin comms surface.

Kept minimal for Milestone 1 — the admin page only needs to browse and
inspect the event log. Later milestones add intent, delivery, preference,
and consent schemas as their surfaces come online.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
