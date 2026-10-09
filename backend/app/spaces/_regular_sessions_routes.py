"""Reserve your regular sessions — member endpoints.

Appended to ``spaces.routes.router`` so these sit under the existing
``/api/spaces`` prefix, in their own module for the same reason
``_series_member_routes.py`` is separate: ``spaces/routes.py`` is long
enough.

Wire contract
-------------
    GET  /api/spaces/{slug}/gathering-series/{series_slug}/regular-sessions
        The weekly slots this Series still has ahead — "Mondays —
        6:00–7:00 pm" — in the Collective's timezone, with how many
        remaining occurrences each covers and how many of those the
        viewer already holds. Read-only; safe to poll.

    POST .../regular-sessions/preview
        Body: ``{"pattern_keys": [...]}``. What reserving that
        selection would do, occurrence by occurrence: new
        reservations, ones already booked, and ones unavailable with
        the reason. Creates nothing.

    POST .../regular-sessions/reserve
        Body: ``{"pattern_keys": [...], "expected_event_ids": [...]}``.
        Does it, under row locks, re-deciding everything. Reports what
        was reserved and — using ``expected_event_ids`` from the
        preview the member actually saw — which of those did not
        survive.

Why the preview is a POST
-------------------------
It takes a selection, which can be long enough to be awkward in a
query string, and it is not cacheable: its whole value is that it
reflects the state of the world right now. It still writes nothing.

Access
------
Every endpoint requires a verified session, and the reserve path
applies the same gate and allowance rules as booking a single
Gathering — see ``services.gathering_booking_rules``. Selecting
patterns grants no access and charges nothing.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_verified_current_user
from app.core.database import get_db
from app.models.platform import (
    BookingStatus,
    EventBooking,
    EventSeries,
    Space,
)
from app.models.user import User
from app.services import regular_sessions as rs
from app.spaces.routes import router


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SchedulePatternOut(BaseModel):
    key: str
    weekday: int
    weekday_label: str
    time_label: str
    label: str
    start_time: str
    end_time: str | None
    #: Remaining occurrences this slot covers.
    occurrence_count: int
    #: How many of those the viewer already has a confirmed booking for.
    already_booked_count: int
    #: True when this weekday has more than one slot, so the member can
    #: see that the time is what distinguishes them.
    shares_weekday: bool
    first_starts_at: datetime
    last_starts_at: datetime


class RegularSessionsResponse(BaseModel):
    timezone: str
    patterns: list[SchedulePatternOut]
    remaining_occurrence_count: int


class OccurrenceOut(BaseModel):
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None
    pattern_key: str
    reason: str | None = None
    message: str | None = None


class PreviewRequest(BaseModel):
    pattern_keys: list[str] = Field(default_factory=list)


class PreviewResponse(BaseModel):
    timezone: str
    selected_keys: list[str]
    new_reservation_count: int
    will_reserve: list[OccurrenceOut]
    already_booked: list[OccurrenceOut]
    unavailable: list[OccurrenceOut]


class ReserveRequest(BaseModel):
    pattern_keys: list[str] = Field(default_factory=list)
    #: The occurrences the preview showed as reservable. Optional, and
    #: purely so the response can name what changed in between.
    expected_event_ids: list[str] = Field(default_factory=list)


class ReserveResponse(BaseModel):
    timezone: str
    reserved_count: int
    reserved: list[OccurrenceOut]
    already_booked: list[OccurrenceOut]
    unavailable: list[OccurrenceOut]
    changed_since_preview: list[OccurrenceOut]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve(slug: str, series_slug: str, db: Session) -> tuple[Space, EventSeries]:
    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collective not found.",
        )
    series = (
        db.query(EventSeries)
        .filter(
            EventSeries.space_id == space.id,
            EventSeries.slug == series_slug,
            EventSeries.status == "published",
        )
        .first()
    )
    if series is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Series not found.",
        )
    return space, series


def _as_out(outcome: rs.OccurrenceOutcome) -> OccurrenceOut:
    return OccurrenceOut(
        event_id=outcome.event_id,
        title=outcome.title,
        starts_at=outcome.starts_at,
        ends_at=outcome.ends_at,
        pattern_key=outcome.pattern_key,
        reason=outcome.reason,
        message=outcome.message,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/gathering-series/{series_slug}/regular-sessions",
    response_model=RegularSessionsResponse,
)
def list_regular_session_patterns(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> RegularSessionsResponse:
    """The weekly slots this Series still has ahead."""
    space, series = _resolve(slug, series_slug, db)
    now = datetime.utcnow()

    events = rs.remaining_occurrences(db, series, space, now)
    patterns, tz_name = rs.build_patterns(events, rs.series_timezone(space))

    booked_event_ids = {
        row[0]
        for row in db.query(EventBooking.event_id)
        .filter(
            EventBooking.user_id == current_user.id,
            EventBooking.status == BookingStatus.confirmed,
            EventBooking.event_id.in_([e.id for e in events] or [""]),
        )
        .all()
    }

    return RegularSessionsResponse(
        timezone=tz_name,
        remaining_occurrence_count=len(events),
        patterns=[
            SchedulePatternOut(
                key=p.key,
                weekday=p.weekday,
                weekday_label=p.weekday_label,
                time_label=p.time_label,
                label=p.label,
                start_time=p.start_time,
                end_time=p.end_time,
                occurrence_count=len(p.occurrences),
                already_booked_count=sum(
                    1 for o in p.occurrences if o.event.id in booked_event_ids
                ),
                shares_weekday=p.shares_weekday,
                first_starts_at=p.occurrences[0].event.starts_at,
                last_starts_at=p.occurrences[-1].event.starts_at,
            )
            for p in patterns
        ],
    )


@router.post(
    "/{slug}/gathering-series/{series_slug}/regular-sessions/preview",
    response_model=PreviewResponse,
)
def preview_regular_sessions(
    slug: str,
    series_slug: str,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> PreviewResponse:
    """What this selection would reserve. Writes nothing."""
    space, series = _resolve(slug, series_slug, db)
    try:
        plan, _, _ = rs.evaluate_selection(
            db,
            user=current_user,
            space=space,
            series=series,
            pattern_keys=body.pattern_keys,
            now=datetime.utcnow(),
        )
    except rs.SeriesClosedError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message)

    return PreviewResponse(
        timezone=plan.timezone,
        selected_keys=plan.selected_keys,
        new_reservation_count=plan.new_reservation_count,
        will_reserve=[_as_out(o) for o in plan.will_reserve],
        already_booked=[_as_out(o) for o in plan.already_booked],
        unavailable=[_as_out(o) for o in plan.unavailable],
    )


@router.post(
    "/{slug}/gathering-series/{series_slug}/regular-sessions/reserve",
    response_model=ReserveResponse,
)
def reserve_regular_sessions(
    slug: str,
    series_slug: str,
    body: ReserveRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> ReserveResponse:
    """Reserve the selected slots, and say exactly what happened."""
    space, series = _resolve(slug, series_slug, db)
    if not body.pattern_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose at least one regular session.",
        )
    try:
        outcome = rs.commit_reservations(
            db,
            user=current_user,
            space=space,
            series=series,
            pattern_keys=body.pattern_keys,
            now=datetime.utcnow(),
            expected_event_ids=body.expected_event_ids,
            background_tasks=background_tasks,
        )
    except rs.SeriesClosedError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message)

    return ReserveResponse(
        timezone=outcome.timezone,
        reserved_count=outcome.reserved_count,
        reserved=[_as_out(o) for o in outcome.reserved],
        already_booked=[_as_out(o) for o in outcome.already_booked],
        unavailable=[_as_out(o) for o in outcome.unavailable],
        changed_since_preview=[_as_out(o) for o in outcome.changed_since_preview],
    )
