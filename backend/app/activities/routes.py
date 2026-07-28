"""
Activity Engine — HTTP API surface.

Two audiences:

  * Notification Centre (per-user)
      GET  /api/activities                    — recent activities for the caller
      GET  /api/activities/unread-count       — badge count for the bell
      POST /api/activities/{id}/read          — mark one as read
      POST /api/activities/read-all           — mark all as read

  * Creator Dashboard feed (per-collective)
      GET  /api/creator/collectives/{slug}/activity
          — newest-first activity for one of the caller's own
            collectives (owner or admin).

All read paths are strictly scoped: they never leak activity that
doesn't belong to the caller (per-user routes) or to a collective the
caller doesn't manage (creator route).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.activity import Activity, ActivityType
from app.models.platform import Space
from app.models.user import User
from app.services.activity_service import ActivityService


router = APIRouter(tags=["activities"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class ActivityOut(BaseModel):
    """A single activity, ready for a UI to render.

    Kept intentionally close to the DB row so future rendering channels
    (My World history, email digest) can consume the same payload.
    """

    id: str
    event_type: str
    category: str
    priority: str
    actor_user_id: str | None
    recipient_user_id: str
    collective_id: str | None
    pathway_id: str | None
    gathering_id: str | None
    conversation_id: str | None
    resource_id: str | None
    payload: dict[str, Any]
    read_at: datetime | None
    archived_at: datetime | None
    created_at: datetime


class ActivityListResponse(BaseModel):
    activities: list[ActivityOut]
    # ``next_before`` is the cursor for the next page: pass it back
    # unchanged to the same endpoint's ``?before=…`` param. Null when
    # there are no more pages.
    next_before: datetime | None


class UnreadCountResponse(BaseModel):
    unread: int


class MarkAllReadResponse(BaseModel):
    marked_read: int


def _to_out(a: Activity) -> ActivityOut:
    return ActivityOut(
        id=a.id,
        event_type=a.event_type,
        category=a.category,
        priority=a.priority,
        actor_user_id=a.actor_user_id,
        recipient_user_id=a.recipient_user_id,
        collective_id=a.collective_id,
        pathway_id=a.pathway_id,
        gathering_id=a.gathering_id,
        conversation_id=a.conversation_id,
        resource_id=a.resource_id,
        payload=a.payload or {},
        read_at=a.read_at,
        archived_at=a.archived_at,
        created_at=a.created_at,
    )


def _next_before(rows: list[Activity], limit: int) -> datetime | None:
    """Return the pagination cursor: the created_at of the last row
    when the page is full; None when we know there are no more."""
    if len(rows) < limit:
        return None
    return rows[-1].created_at


# ---------------------------------------------------------------------------
# Notification Centre — per-user routes
# ---------------------------------------------------------------------------

@router.get("/api/activities", response_model=ActivityListResponse)
def list_activities(
    unread_only: bool = Query(False, description="Only return activities where read_at is null."),
    include_archived: bool = Query(False, description="Include archived activities."),
    limit: int = Query(20, ge=1, le=100),
    before: datetime | None = Query(
        None,
        description="Cursor: return activities with created_at strictly less than this timestamp.",
    ),
    collective_id: str | None = Query(
        None,
        description=(
            "Optional collective (space) id filter. Recipient scope is unchanged — "
            "results still contain only the caller's own activities — the filter is "
            "additive so the same endpoint powers both the global 'Recent Moments' "
            "list on Your World and the per-collective sidebar panel."
        ),
    ),
    recent_moments: bool = Query(
        False,
        description=(
            "When true, restrict the result to the curated 'Recent Moments' "
            "event-type whitelist (see RECENT_MOMENTS in app.models.activity). "
            "Attention-required and history-only events are excluded. The Recent "
            "Moments UI passes this; other consumers (audit / history / future "
            "digest) pass false to see the full ledger."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivityListResponse:
    rows = ActivityService.list_for_recipient(
        db,
        recipient_user_id=current_user.id,
        unread_only=unread_only,
        include_archived=include_archived,
        limit=limit,
        before=before,
        collective_id=collective_id,
        recent_moments_only=recent_moments,
    )
    return ActivityListResponse(
        activities=[_to_out(r) for r in rows],
        next_before=_next_before(rows, limit),
    )


@router.get("/api/activities/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountResponse:
    return UnreadCountResponse(
        unread=ActivityService.unread_count(db, recipient_user_id=current_user.id),
    )


@router.post("/api/activities/{activity_id}/read", response_model=ActivityOut)
def mark_activity_read(
    activity_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivityOut:
    row = ActivityService.mark_read(
        db,
        activity_id=activity_id,
        recipient_user_id=current_user.id,
    )
    if row is None:
        # 404 (never 403) — don't leak the existence of someone else's
        # activity id.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found.")
    db.commit()
    return _to_out(row)


@router.post("/api/activities/read-all", response_model=MarkAllReadResponse)
def mark_all_activities_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkAllReadResponse:
    n = ActivityService.mark_all_read(db, recipient_user_id=current_user.id)
    db.commit()
    return MarkAllReadResponse(marked_read=n)


# ---------------------------------------------------------------------------
# Creator Dashboard feed — per-collective
# ---------------------------------------------------------------------------

@router.get(
    "/api/creator/collectives/{slug}/activity",
    response_model=ActivityListResponse,
)
def list_collective_activity(
    slug: str,
    limit: int = Query(30, ge=1, le=100),
    before: datetime | None = Query(
        None,
        description="Cursor: return activities with created_at strictly less than this timestamp.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivityListResponse:
    space = db.query(Space).filter(Space.slug == slug).one_or_none()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collective not found.")

    # Ownership check — a creator only sees their own collective's
    # feed; admins can see any collective's feed.
    is_admin = current_user.role == "admin"
    is_owner = space.creator_id == current_user.id
    if not (is_admin or is_owner):
        # 404 keeps the collective's existence deniable from a
        # non-manager perspective.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collective not found.")

    rows = ActivityService.list_for_collective(
        db,
        collective_id=space.id,
        limit=limit,
        before=before,
    )
    return ActivityListResponse(
        activities=[_to_out(r) for r in rows],
        next_before=_next_before(rows, limit),
    )


# Re-exported so downstream code can reference the enum from the routes
# module in the standard `from app.activities.routes import ActivityType`
# shape if it prefers.
__all__ = ["router", "ActivityType"]
