"""Routes for the Communications Layer.

Admin surface (Milestone 1)
---------------------------
  * ``GET /api/admin/comms/events``           — paginated list
  * ``GET /api/admin/comms/events/{event_id}`` — full detail
  * ``GET /api/admin/comms/registry``         — every registered event_type

Member surface (Milestone 2)
----------------------------
  * ``GET  /api/comms/preferences/me`` — full preference matrix + settings + consent
  * ``PATCH /api/comms/preferences/me`` — partial update
  * ``GET  /api/comms/consents/me``    — consent state (audit-oriented duplicate)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user, get_current_user
from app.comms.categories import (
    ALL_CATEGORIES,
    ALL_CHANNELS,
    ALL_PRIORITIES,
    ALL_SOURCES,
    TOPIC_TO_CATEGORY,
)
from app.comms.models import (
    CommunicationConsent,
    CommunicationEvent,
)
from app.comms.preferences import (
    LockedPreferenceError,
    UnknownCategoryError,
    UnknownChannelError,
    UnknownPriorityError,
    UnsupportedChannelError,
    clear_preference,
    get_consent_state,
    get_member_settings,
    get_preference_matrix,
    grant_consent,
    revoke_consent,
    set_preference,
    update_member_settings,
)
from app.comms.registry import registered_event_types, get_event_definition
from app.comms.schemas import (
    AdminEventDetail,
    AdminEventListResponse,
    AdminEventRow,
    AdminRegisteredEventType,
    AdminRegistryResponse,
    ConsentStateRow,
    MemberSettingsResponse,
    MyPreferencesPatch,
    MyPreferencesResponse,
    PreferenceCategoryRow,
)
from app.core.database import get_db
from app.models.user import User


router = APIRouter(prefix="/api/admin/comms", tags=["admin", "comms"])

# Member-scoped routes get their own router so the prefix is /api/comms
# rather than /api/admin/comms.
member_router = APIRouter(prefix="/api/comms", tags=["comms"])


# The five consent kinds tracked by the platform. Kept in this module
# so the response always returns a complete matrix, even when the user
# has never touched a particular consent (state=None).
_CONSENT_KINDS = (
    "terms_of_service",
    "privacy_policy",
    "marketing",
    "product_updates",
    "creator_broadcast",
)


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


# ---------------------------------------------------------------------------
# Member surface (Milestone 2)
# ---------------------------------------------------------------------------


def _member_settings_response(
    db: Session, user_id: str,
) -> MemberSettingsResponse:
    row = get_member_settings(db, user_id=user_id)
    if row is None:
        return MemberSettingsResponse(
            timezone=None,
            quiet_hours_start_local=None,
            quiet_hours_end_local=None,
            daily_digest_send_local_time=None,
            weekly_digest_send_local_weekday=None,
            weekly_digest_send_local_time=None,
        )
    return MemberSettingsResponse(
        timezone=row.timezone,
        quiet_hours_start_local=row.quiet_hours_start_local,
        quiet_hours_end_local=row.quiet_hours_end_local,
        daily_digest_send_local_time=row.daily_digest_send_local_time,
        weekly_digest_send_local_weekday=row.weekly_digest_send_local_weekday,
        weekly_digest_send_local_time=row.weekly_digest_send_local_time,
    )


def _consent_response(db: Session, user_id: str) -> list[ConsentStateRow]:
    out: list[ConsentStateRow] = []
    for kind in _CONSENT_KINDS:
        latest = get_consent_state(db, user_id=user_id, consent_kind=kind)
        if latest is None:
            out.append(ConsentStateRow(consent_kind=kind))
        else:
            out.append(
                ConsentStateRow(
                    consent_kind=kind,
                    state=latest.state,
                    policy_version=latest.policy_version,
                    occurred_at=latest.occurred_at,
                )
            )
    return out


@member_router.get(
    "/preferences/me",
    response_model=MyPreferencesResponse,
    summary="Read the current member's full communications preferences",
)
def get_my_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyPreferencesResponse:
    matrix = get_preference_matrix(db, user_id=current_user.id)
    return MyPreferencesResponse(
        categories=[PreferenceCategoryRow(**row) for row in matrix],
        member_settings=_member_settings_response(db, current_user.id),
        consents=_consent_response(db, current_user.id),
    )


@member_router.patch(
    "/preferences/me",
    response_model=MyPreferencesResponse,
    summary="Partially update the current member's communications preferences",
)
def patch_my_preferences(
    body: MyPreferencesPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyPreferencesResponse:
    # ── Preferences (per-cell) ──────────────────────────────────────
    if body.preferences is not None:
        for upd in body.preferences:
            if upd.category_key not in ALL_CATEGORIES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown category: {upd.category_key!r}",
                )
            if upd.channel not in ALL_CHANNELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown channel: {upd.channel!r}",
                )
            if upd.priority is not None and upd.priority not in ALL_PRIORITIES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown priority: {upd.priority!r}",
                )

            try:
                if upd.priority is None:
                    clear_preference(
                        db,
                        user_id=current_user.id,
                        category_key=upd.category_key,
                        channel=upd.channel,
                    )
                else:
                    set_preference(
                        db,
                        user_id=current_user.id,
                        category_key=upd.category_key,
                        channel=upd.channel,
                        priority=upd.priority,
                    )
            except LockedPreferenceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )
            except UnsupportedChannelError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )
            except (
                UnknownCategoryError, UnknownChannelError, UnknownPriorityError,
            ) as exc:
                # Already validated above; belt-and-braces.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )

    # ── Member settings ─────────────────────────────────────────────
    if body.member_settings is not None:
        # Only include fields the caller actually sent (Pydantic
        # ``model_fields_set``) so unspecified fields aren't reset to
        # NULL.
        changed = {
            f: getattr(body.member_settings, f)
            for f in body.member_settings.model_fields_set
        }
        if changed:
            try:
                update_member_settings(db, user_id=current_user.id, **changed)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )

    # ── Consents ────────────────────────────────────────────────────
    if body.consents is not None:
        for c in body.consents:
            if c.consent_kind not in _CONSENT_KINDS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown consent_kind: {c.consent_kind!r}",
                )
            if c.state == "granted":
                grant_consent(
                    db,
                    user_id=current_user.id,
                    consent_kind=c.consent_kind,
                    source="settings.communications.patch",
                    policy_version=c.policy_version,
                )
            else:
                revoke_consent(
                    db,
                    user_id=current_user.id,
                    consent_kind=c.consent_kind,
                    source="settings.communications.patch",
                )

    db.commit()

    # Fresh reads for the response body so the client sees the resolved
    # post-patch state.
    matrix = get_preference_matrix(db, user_id=current_user.id)
    return MyPreferencesResponse(
        categories=[PreferenceCategoryRow(**row) for row in matrix],
        member_settings=_member_settings_response(db, current_user.id),
        consents=_consent_response(db, current_user.id),
    )


@member_router.get(
    "/consents/me",
    response_model=list[ConsentStateRow],
    summary="Read the current member's consent state (audit-oriented)",
)
def get_my_consents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConsentStateRow]:
    return _consent_response(db, current_user.id)
