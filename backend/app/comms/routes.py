"""Routes for the Communications Layer.

Admin surface
-------------
  * ``GET /api/admin/comms/events``           — event log list (M1)
  * ``GET /api/admin/comms/events/{event_id}`` — event detail (M1)
  * ``GET /api/admin/comms/registry``         — registered event_types (M1)
  * ``GET /api/admin/comms/intents``          — intent list (M4)
  * ``GET /api/admin/comms/intents/{id}``     — intent detail + deliveries (M4)
  * ``GET /api/admin/comms/deliveries``       — flat delivery list (M4)

Member surface
--------------
  * ``GET  /api/comms/preferences/me`` — preference matrix + settings + consent (M2)
  * ``PATCH /api/comms/preferences/me`` — partial update (M2)
  * ``GET  /api/comms/consents/me``    — consent state audit view (M2)
  * ``GET  /api/comms/history/me``     — communications history (M4)

Internal
--------
  * ``POST /api/internal/comms/dispatch-due`` — protected by
    X-Internal-Token; runs one worker cycle (M4)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
from app.comms.intents import ALL_STATES
from app.comms.models import (
    CommunicationConsent,
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationIntent,
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
    AdminDeliveryListResponse,
    AdminDeliveryRow,
    AdminEventDetail,
    AdminEventListResponse,
    AdminEventRow,
    AdminIntentDetail,
    AdminIntentListResponse,
    AdminIntentRow,
    AdminRegisteredEventType,
    AdminRegistryResponse,
    ConsentStateRow,
    DeliveryAttemptDetail,
    DeliveryAttemptSummary,
    DispatchResultResponse,
    HistoryIntentRow,
    HistoryResponse,
    MemberSettingsResponse,
    MyPreferencesPatch,
    MyPreferencesResponse,
    PreferenceCategoryRow,
    ReconcilerResultResponse,
    ShadowParityDayRow,
    ShadowParityDiscrepancy,
    ShadowParityReport,
)
from app.comms.shadow import compute_parity_report, reconcile_shadow
from app.comms.worker import dispatch_due
from app.core.config import settings
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


# ---------------------------------------------------------------------------
# Communications history (Milestone 4)
# ---------------------------------------------------------------------------


def _delivery_summary(row: CommunicationDelivery) -> DeliveryAttemptSummary:
    return DeliveryAttemptSummary(
        id=row.id,
        provider_key=row.provider_key,
        attempt_number=row.attempt_number,
        status=row.status,
        provider_message_id=row.provider_message_id,
        error_class=row.error_class,
        attempted_at=row.attempted_at,
        settled_at=row.settled_at,
    )


def _delivery_detail(row: CommunicationDelivery) -> DeliveryAttemptDetail:
    return DeliveryAttemptDetail(
        id=row.id,
        provider_key=row.provider_key,
        attempt_number=row.attempt_number,
        status=row.status,
        provider_message_id=row.provider_message_id,
        error_class=row.error_class,
        error_detail=row.error_detail,
        attempted_at=row.attempted_at,
        settled_at=row.settled_at,
        request_snapshot=dict(row.request_snapshot or {}),
        response_snapshot=dict(row.response_snapshot or {}),
    )


def _history_row(intent: CommunicationIntent) -> HistoryIntentRow:
    deliveries = sorted(
        [_delivery_summary(d) for d in getattr(intent, "deliveries", []) or []],
        key=lambda d: d.attempt_number,
    )
    return HistoryIntentRow(
        id=intent.id,
        source_type=intent.source_type,
        source_id=intent.source_id,
        category_key=intent.category_key,
        channel=intent.channel,
        priority=intent.priority,
        human_reason=intent.human_reason,
        payload_subject=intent.payload_subject,
        state=intent.state,
        scheduled_for=intent.scheduled_for,
        created_at=intent.created_at,
        sent_at=intent.sent_at,
        terminal_at=intent.terminal_at,
        deliveries=deliveries,
    )


@member_router.get(
    "/history/me",
    response_model=HistoryResponse,
    summary="Paginated communications history for the current member",
)
def get_my_history(
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HistoryResponse:
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 100.",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset must be >= 0.",
        )

    base_q = select(CommunicationIntent).where(
        CommunicationIntent.recipient_user_id == current_user.id,
    )
    total = db.execute(
        select(func.count()).select_from(base_q.subquery())
    ).scalar_one()

    intents = db.execute(
        base_q.order_by(desc(CommunicationIntent.created_at))
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    intent_ids = [i.id for i in intents]
    deliveries_by_intent: dict[str, list[CommunicationDelivery]] = {i.id: [] for i in intents}
    if intent_ids:
        rows = db.execute(
            select(CommunicationDelivery).where(
                CommunicationDelivery.intent_id.in_(intent_ids),
            )
        ).scalars().all()
        for r in rows:
            deliveries_by_intent[r.intent_id].append(r)

    items = []
    for intent in intents:
        # Attach deliveries as a plain list so _history_row can read
        # them without a relationship being defined on the model.
        object.__setattr__(intent, "deliveries", deliveries_by_intent.get(intent.id, []))
        items.append(_history_row(intent))

    return HistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Admin — intents + deliveries (Milestone 4)
# ---------------------------------------------------------------------------


def _admin_intent_row(intent: CommunicationIntent) -> AdminIntentRow:
    return AdminIntentRow.model_validate(intent)


@router.get(
    "/intents",
    response_model=AdminIntentListResponse,
    summary="List communication intents",
)
def list_intents(
    limit: int = 50,
    offset: int = 0,
    state: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    source_type: str | None = None,
    provider_key: str | None = None,
    recipient_user_id: str | None = None,
    event_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> AdminIntentListResponse:
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
    if state is not None and state not in ALL_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"state must be one of {ALL_STATES}",
        )
    if category is not None and category not in ALL_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"category must be one of {ALL_CATEGORIES}",
        )
    if channel is not None and channel not in ALL_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"channel must be one of {ALL_CHANNELS}",
        )
    if source_type is not None and source_type not in ALL_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"source_type must be one of {ALL_SOURCES}",
        )

    q = select(CommunicationIntent)
    count_q = select(func.count()).select_from(CommunicationIntent)

    def _apply(q_, filters):  # small local helper to keep repetition down
        for col, val in filters:
            if val is not None:
                q_ = q_.where(col == val)
        return q_

    conditions = [
        (CommunicationIntent.state, state),
        (CommunicationIntent.category_key, category),
        (CommunicationIntent.channel, channel),
        (CommunicationIntent.source_type, source_type),
        (CommunicationIntent.provider_key, provider_key),
        (CommunicationIntent.recipient_user_id, recipient_user_id),
        (CommunicationIntent.event_id, event_id),
    ]
    q = _apply(q, conditions)
    count_q = _apply(count_q, conditions)
    if since is not None:
        q = q.where(CommunicationIntent.created_at >= since)
        count_q = count_q.where(CommunicationIntent.created_at >= since)
    if until is not None:
        q = q.where(CommunicationIntent.created_at < until)
        count_q = count_q.where(CommunicationIntent.created_at < until)

    total = db.execute(count_q).scalar_one()
    rows = db.execute(
        q.order_by(desc(CommunicationIntent.created_at)).limit(limit).offset(offset)
    ).scalars().all()

    return AdminIntentListResponse(
        items=[_admin_intent_row(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/intents/{intent_id}",
    response_model=AdminIntentDetail,
    summary="Get one intent with all its deliveries",
)
def get_intent(
    intent_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> AdminIntentDetail:
    intent = db.get(CommunicationIntent, intent_id)
    if intent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Intent not found.",
        )
    deliveries = db.execute(
        select(CommunicationDelivery)
        .where(CommunicationDelivery.intent_id == intent_id)
        .order_by(CommunicationDelivery.attempt_number)
    ).scalars().all()

    return AdminIntentDetail(
        id=intent.id,
        event_id=intent.event_id,
        recipient_user_id=intent.recipient_user_id,
        recipient_address=intent.recipient_address,
        source_type=intent.source_type,
        source_id=intent.source_id,
        category_key=intent.category_key,
        topic_key=intent.topic_key,
        channel=intent.channel,
        priority=intent.priority,
        provider_key=intent.provider_key,
        template_key=intent.template_key,
        template_version=intent.template_version,
        template_context=intent.template_context,
        human_reason=intent.human_reason,
        payload_subject=intent.payload_subject,
        payload_body_html=intent.payload_body_html,
        payload_body_text=intent.payload_body_text,
        payload_metadata=dict(intent.payload_metadata or {}),
        state=intent.state,
        suppression_reason=intent.suppression_reason,
        scheduled_for=intent.scheduled_for,
        created_at=intent.created_at,
        queued_at=intent.queued_at,
        dispatching_at=intent.dispatching_at,
        sent_at=intent.sent_at,
        terminal_at=intent.terminal_at,
        deliveries=[_delivery_detail(d) for d in deliveries],
    )


@router.get(
    "/deliveries",
    response_model=AdminDeliveryListResponse,
    summary="List delivery attempts",
)
def list_deliveries(
    limit: int = 50,
    offset: int = 0,
    provider_key: str | None = None,
    delivery_status: str | None = None,
    intent_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> AdminDeliveryListResponse:
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200.",
        )
    if delivery_status is not None and delivery_status not in ("pending", "accepted", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="delivery_status must be one of pending|accepted|failed",
        )

    q = select(CommunicationDelivery)
    count_q = select(func.count()).select_from(CommunicationDelivery)
    if provider_key is not None:
        q = q.where(CommunicationDelivery.provider_key == provider_key)
        count_q = count_q.where(CommunicationDelivery.provider_key == provider_key)
    if delivery_status is not None:
        q = q.where(CommunicationDelivery.status == delivery_status)
        count_q = count_q.where(CommunicationDelivery.status == delivery_status)
    if intent_id is not None:
        q = q.where(CommunicationDelivery.intent_id == intent_id)
        count_q = count_q.where(CommunicationDelivery.intent_id == intent_id)

    total = db.execute(count_q).scalar_one()
    rows = db.execute(
        q.order_by(desc(CommunicationDelivery.attempted_at)).limit(limit).offset(offset)
    ).scalars().all()

    return AdminDeliveryListResponse(
        items=[AdminDeliveryRow.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Internal — worker dispatch (Milestone 4)
# ---------------------------------------------------------------------------


internal_router = APIRouter(prefix="/api/internal/comms", tags=["internal", "comms"])


@internal_router.post(
    "/dispatch-due",
    response_model=DispatchResultResponse,
    summary="Run one worker cycle — claim + dispatch queued intents",
)
def dispatch_due_endpoint(
    limit: int = 50,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    db: Session = Depends(get_db),
) -> DispatchResultResponse:
    """Cron-callable endpoint. Requires ``X-Internal-Token`` matching
    ``JWT_SECRET`` (same protection scheme as
    ``/api/internal/send-event-reminders``).
    """
    if not x_internal_token or x_internal_token != settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Internal-Token.",
        )
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 500.",
        )
    processed = dispatch_due(db, limit=limit)
    return DispatchResultResponse(processed=processed, count=len(processed))


@internal_router.post(
    "/reconcile-shadow",
    response_model=ReconcilerResultResponse,
    summary="Run one shadow reconciliation cycle",
)
def reconcile_shadow_endpoint(
    limit: int = 200,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    db: Session = Depends(get_db),
) -> ReconcilerResultResponse:
    """Cron-callable endpoint. Records one ``communication_shadow_
    comparisons`` row per event that has a registered comparator and
    doesn't yet have a comparison row. Idempotent — safe to call at
    any cadence.
    """
    if not x_internal_token or x_internal_token != settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Internal-Token.",
        )
    if limit < 1 or limit > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 2000.",
        )
    result = reconcile_shadow(db, limit=limit)
    return ReconcilerResultResponse(
        compared=result.compared_event_ids,
        count=len(result.compared_event_ids),
        skipped_no_comparator=result.skipped_no_comparator,
        duplicate_skipped=result.duplicate_skipped,
    )


@router.get(
    "/shadow-parity",
    response_model=ShadowParityReport,
    summary="Per-topic (or per-category) shadow parity metrics",
)
def shadow_parity(
    topic: str,
    window_days: int = 7,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> ShadowParityReport:
    """Read-only observational surface. Reports parity metrics for
    the given topic or category over a UTC-day window and states
    whether the topic is currently eligible for live cutover. Never
    mutates ``COMMS_LIVE_TOPICS`` — promotion is config-only.
    """
    if window_days < 1 or window_days > 90:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window_days must be between 1 and 90.",
        )
    report = compute_parity_report(
        db, scope_key=topic, window_days=window_days,
    )
    return ShadowParityReport(
        scope_kind=report.scope_kind,
        scope_key=report.scope_key,
        window_days=report.window_days,
        events_observed=report.events_observed,
        comparisons_recorded=report.comparisons_recorded,
        parity_pct=report.parity_pct,
        consecutive_perfect_days=report.consecutive_perfect_days,
        eligible_for_live=report.eligible_for_live,
        days=[
            ShadowParityDayRow(
                day=d.day.isoformat(),
                events_observed=d.events_observed,
                comparisons_recorded=d.comparisons_recorded,
                matches=d.matches,
                mismatches_by_dim=d.mismatches_by_dim,
                day_qualifies=d.day_qualifies,
            )
            for d in report.days
        ],
        recent_discrepancies=[
            ShadowParityDiscrepancy(**d) for d in report.recent_discrepancies
        ],
    )
