"""Admin surface for the Communications event log.

Endpoints:

  * ``GET /api/admin/comms/events``           — paginated list
  * ``GET /api/admin/comms/events/{event_id}`` — full detail
  * ``GET /api/admin/comms/registry``         — every registered event_type

Every route requires role='admin'. Milestone 1 gives admins visibility
into what the system is emitting so shadow rollouts (Milestone 5) have a
console to watch.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.comms.categories import (
    ALL_CATEGORIES,
    ALL_SOURCES,
    TOPIC_TO_CATEGORY,
)
from app.comms.models import CommunicationEvent
from app.comms.registry import registered_event_types, get_event_definition
from app.comms.schemas import (
    AdminEventDetail,
    AdminEventListResponse,
    AdminEventRow,
    AdminRegisteredEventType,
    AdminRegistryResponse,
)
from app.core.database import get_db
from app.models.user import User


router = APIRouter(prefix="/api/admin/comms", tags=["admin", "comms"])


@router.get(
    "/events",
    response_model=AdminEventListResponse,
    summary="List communication events",
)
def list_events(
    limit: int = 50,
    offset: int = 0,
    event_type: str | None = None,
    source_type: str | None = None,
    category: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> AdminEventListResponse:
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200.",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset must be >= 0.",
        )
    if source_type is not None and source_type not in ALL_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"source_type must be one of {ALL_SOURCES}",
        )
    if category is not None and category not in ALL_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"category must be one of {ALL_CATEGORIES}",
        )

    q = select(CommunicationEvent)
    count_q = select(func.count()).select_from(CommunicationEvent)

    if event_type is not None:
        q = q.where(CommunicationEvent.event_type == event_type)
        count_q = count_q.where(CommunicationEvent.event_type == event_type)
    if source_type is not None:
        q = q.where(CommunicationEvent.source_type == source_type)
        count_q = count_q.where(CommunicationEvent.source_type == source_type)
    if category is not None:
        q = q.where(CommunicationEvent.category_key == category)
        count_q = count_q.where(CommunicationEvent.category_key == category)
    if since is not None:
        q = q.where(CommunicationEvent.occurred_at >= since)
        count_q = count_q.where(CommunicationEvent.occurred_at >= since)
    if until is not None:
        q = q.where(CommunicationEvent.occurred_at < until)
        count_q = count_q.where(CommunicationEvent.occurred_at < until)

    total = db.execute(count_q).scalar_one()
    rows = (
        db.execute(
            q.order_by(desc(CommunicationEvent.occurred_at))
             .limit(limit)
             .offset(offset)
        )
        .scalars()
        .all()
    )

    return AdminEventListResponse(
        items=[AdminEventRow.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/events/{event_id}",
    response_model=AdminEventDetail,
    summary="Get one communication event",
)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> AdminEventDetail:
    row = db.get(CommunicationEvent, event_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found.",
        )
    return AdminEventDetail.model_validate(row)


@router.get(
    "/registry",
    response_model=AdminRegistryResponse,
    summary="List every event_type registered for emit",
)
def list_registry(
    _: User = Depends(get_admin_user),
) -> AdminRegistryResponse:
    events = []
    for event_type in registered_event_types():
        d = get_event_definition(event_type)
        assert d is not None  # registered_event_types() derives from _BY_TYPE
        events.append(
            AdminRegisteredEventType(
                event_type=d.event_type,
                topic=d.topic,
                category=TOPIC_TO_CATEGORY[d.topic],
                default_priority=d.default_priority,
            )
        )
    return AdminRegistryResponse(events=events)
