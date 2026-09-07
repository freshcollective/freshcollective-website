"""Creator Studio attendance dashboard endpoints.

Scope: one route file for the four new endpoints that back the
gathering check-in dashboard. All mounted under ``/api/creator`` at
paths ``/spaces/{slug}/events/{event_id}/attendance*``. The existing
per-booking mutation stays where it lives in ``creator/routes.py``
(same URL, backwards compatible payload) — this module never redefines
it.

Design commitments (from the SEC-scoped review that authored these
routes):

  * **Per-occurrence isolation.** Every mutation queries by the exact
    ``event_id`` in the URL and the exact ``booking_id`` in the URL.
    A term-pass or series-pass holder has one ``EventBooking`` row per
    occurrence they enrolled in; a check-in on session 3 never mutates
    session 4, and Finish on session 3 never touches session 4's
    completion state. The two lock helpers below take ``FOR UPDATE``
    only on the specific ``events`` row.

  * **Booking-event-space chain.** ``_load_gathering_for_manage`` and
    ``_load_booking_scoped`` verify: (a) the caller manages the space;
    (b) the event belongs to that space; (c) the booking belongs to
    that event. 404 on any break in the chain. This closes the "guess
    a booking id from another creator" attack shape end-to-end.

  * **Concurrency.** Finish/Reopen take ``SELECT … FOR UPDATE`` on the
    ``events`` row (Postgres row-level lock) before deciding whether
    to write. A per-booking PATCH also takes the same lock in the same
    transaction so a check-in racing with Finish cannot land after the
    completion is written. Two concurrent per-booking PATCHes serialise
    on the same event row; the second sees the first's state.

  * **Payment / entitlement separation.** Every write in this module
    touches only ``attendance_status``, ``attendance_marked_at``,
    ``attendance_marked_by``, ``attendance_source`` on ``event_bookings``
    and ``attendance_completed_at`` / ``attendance_completed_by`` on
    ``events``. Never ``booking.status``, ``payment_transaction_id``,
    ``credits_used``, ``access_pass_id``, or anything else. A check-in
    or absence cannot charge, refund, cancel or otherwise change a
    booking's payment or entitlement state.

  * **API vocabulary vs DB vocabulary.** DB stores ``attended`` /
    ``no_show`` / NULL — those columns predate this feature and are
    read by two existing frontend callers (``EventManagePanel``,
    ``CreatorStudioLiteMobile``). This module surfaces the prototype's
    calmer wording (``attended`` / ``absent`` / ``booked``) on the
    wire. Translation happens in a single tiny helper at the top of
    the file; the DB values are never renamed.

  * **Denominator = confirmed bookings only.** Cancelled bookings are
    excluded from counts, from the roster, and from CSV. If a booking
    is cancelled after Finish, its historical attendance value (if
    any) is preserved on the row but no longer contributes to the
    summary — that matches the "attendance is a live view of confirmed
    bookings" policy and keeps refunds side-effect free.

  * **Post-completion arrivals.** A confirmed booking that arrives
    AFTER Finish (booked_at > attendance_completed_at) shows in the
    roster with attendance_status=NULL and is surfaced as
    ``pending_post_completion=True``. The completion summary numbers
    (attended / absent / rate) exclude these arrivals so the summary
    cannot silently change or gain unresolved bookings. The dashboard
    surfaces the count and instructs the creator to Reopen to include.

  * **CSV.** The export endpoint applies RFC 4180 quoting AND
    formula-injection protection (leading ``=``, ``+``, ``-``, ``@``,
    tab, CR are prefixed with a single quote). The row set is the same
    as the roster the caller just saw; auth is identical.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_verified_creator_user
from app.core.database import get_db
from app.models.platform import Event, EventBooking, Space
from app.models.user import User
from app.creator.routes import _get_managed_space


router = APIRouter(prefix="/api/creator", tags=["creator-attendance"])


# ---------------------------------------------------------------------------
# Vocabulary translation. DB stores 'attended' / 'no_show' / NULL. API
# accepts either the DB values or the prototype's 'attended' / 'absent'
# / 'booked'. Existing callers (EventManagePanel, CreatorStudioLiteMobile)
# keep working unchanged.
# ---------------------------------------------------------------------------

_API_TO_DB: dict[str, str | None] = {
    "attended": "attended",
    "absent": "no_show",
    "no_show": "no_show",  # accepted alias for existing callers
    "booked": None,
    "pending": None,       # accepted alias for existing callers
}

_DB_TO_API: dict[str | None, str] = {
    "attended": "attended",
    "no_show": "absent",
    None: "booked",
}


def translate_api_status(api_value: str) -> str | None:
    """Map a wire-format status string to a DB value. Raises 400 on
    unknown input. Kept public because ``creator/routes.py`` shares it."""
    if api_value not in _API_TO_DB:
        raise HTTPException(
            status_code=400,
            detail="status must be one of: attended, absent, booked",
        )
    return _API_TO_DB[api_value]


def db_status_to_api(db_value: str | None) -> str:
    return _DB_TO_API.get(db_value, "booked")


# ---------------------------------------------------------------------------
# Load helpers with row-locking.
# ---------------------------------------------------------------------------


def _load_gathering_for_manage(
    slug: str, event_id: str, user: User, db: Session, *, for_update: bool = False,
) -> tuple[Space, Event]:
    """Auth chain: caller manages space AND event belongs to space.
    404 on either break, matching the existing endpoint's shape.

    When ``for_update`` is True the events row is locked with
    ``SELECT … FOR UPDATE`` so a concurrent finish/reopen/patch on the
    same gathering serialises through this row. Only lock when the
    caller is about to write."""
    space = _get_managed_space(slug, user, db)
    q = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id)
    if for_update:
        q = q.with_for_update()
    event = q.first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return space, event


def _load_booking_scoped(
    booking_id: str, event: Event, db: Session, *, for_update: bool = False,
) -> EventBooking:
    """Verify the booking belongs to the exact event in the URL.
    Prevents a caller from mutating a booking that isn't part of the
    gathering they're managing. 404 on mismatch or missing."""
    q = db.query(EventBooking).filter(
        EventBooking.id == booking_id, EventBooking.event_id == event.id,
    )
    if for_update:
        q = q.with_for_update()
    booking = q.first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking


def _bstatus(booking: EventBooking) -> str:
    """The BookingStatus enum uses SQLAlchemy Enum; SQLA returns the
    Python enum instance in some contexts and a raw string in others.
    Normalise to a plain lowercase string."""
    v = booking.status
    return v.value if hasattr(v, "value") else str(v)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _in_finish_cohort(event: Event, booking: EventBooking) -> bool:
    """The "completed cohort" — a durable, server-computed set that
    defines the completed summary's denominator and numerators. A
    booking is in the cohort iff:

      * the gathering has been finished at all (``completed_at``
        exists);
      * the booking has an attendance value recorded
        (``attendance_status`` is non-NULL — set for every confirmed
        row present at Finish, plus any pre-Finish manual mark);
      * AND the booking was still active at Finish — either currently
        ``confirmed`` OR ``cancelled AFTER`` the finish moment.

    Rows cancelled BEFORE Finish are excluded even if they had a
    pre-cancellation attendance mark. Rows arriving after Finish
    (new bookings, pending→confirmed webhooks) have
    ``attendance_status IS NULL`` and are also excluded — they surface
    in the roster as ``pending_post_completion`` but never contribute
    to the summary.

    This is a pure function of DB state: opening the completed
    summary in another browser or after a hard refresh will always
    yield the same numbers. No dependence on browser-held finish-time
    values.
    """
    if event.attendance_completed_at is None:
        return False
    if booking.attendance_status is None:
        return False
    b_status = _bstatus(booking)
    if b_status == "confirmed":
        return True
    if b_status == "cancelled":
        c_at = _aware(booking.cancelled_at)
        f_at = _aware(event.attendance_completed_at)
        if c_at is None or f_at is None:
            # Defensive: if we can't tell, include (preserves the
            # historical value rather than silently dropping it).
            return True
        return c_at > f_at
    return False


def apply_attendance_mutation(
    *, slug: str, event_id: str, booking_id: str, api_status: str,
    user: User, db: Session,
) -> tuple[Event, EventBooking, str | None]:
    """Single write path shared by BOTH the dashboard PATCH and the
    pre-existing ``/bookings/{id}/attendance`` PATCH so their
    permission, locking, and state-transition semantics cannot drift.

    Returns ``(event, booking, new_db_status)`` on success. Raises
    ``HTTPException`` on any failure (403 / 404 / 400 / 409) with the
    same detail strings both endpoints emitted before extraction.

    Flow:
      1. ``translate_api_status`` — maps the wire value to the DB
         value or raises 400.
      2. ``_load_gathering_for_manage(for_update=True)`` — auth chain
         + row-lock on the event.
      3. Completion gate — 409 if ``attendance_completed_at`` is set.
      4. ``_load_booking_scoped(for_update=True)`` — booking-event
         ownership + row-lock.
      5. 400 for cancelled bookings.
      6. Write attendance columns only. Payment / entitlement columns
         are never touched.
    """
    from datetime import datetime as _dt, timezone as _tz

    new_db_status = translate_api_status(api_status)
    _space, event = _load_gathering_for_manage(
        slug, event_id, user, db, for_update=True,
    )
    if event.attendance_completed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Gathering attendance is finished. Reopen to make a correction.",
        )
    booking = _load_booking_scoped(booking_id, event, db, for_update=True)
    if _bstatus(booking) == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Cannot mark attendance for a cancelled booking.",
        )
    booking.attendance_status = new_db_status
    if new_db_status is None:
        booking.attendance_source = None
        booking.attendance_marked_at = None
    else:
        booking.attendance_source = "manual"
        booking.attendance_marked_at = _dt.now(_tz.utc)
    booking.attendance_marked_by = user.id
    return event, booking, new_db_status


# ---------------------------------------------------------------------------
# Response shapes.
# ---------------------------------------------------------------------------


class AttendanceEventOut(BaseModel):
    id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime | None
    attendance_format: str  # 'online' | 'in_person' | 'hybrid'
    venue_name: str | None
    venue_locality: str | None
    venue_address: str | None  # host-only surface, so present here
    location_url: str | None   # zoom/meet link, host-only
    capacity: int | None
    thumbnail_url: str | None
    status: str                # 'active' | 'cancelled' | 'archived'
    is_published: bool
    space_slug: str
    space_name: str
    attendance_completed_at: datetime | None
    attendance_completed_by: str | None


class AttendanceRowOut(BaseModel):
    booking_id: str
    user_id: str
    name: str | None
    email: str
    # Attendance vocabulary in the response is the API dialect: 'attended'
    # | 'absent' | 'booked'. Callers should not need to know about the
    # DB's older 'no_show'/NULL shape.
    attendance_status: str
    attendance_source: str | None  # 'manual' | 'auto' | null
    attendance_marked_at: datetime | None
    booking_reference: str
    booked_at: datetime
    ticket_label: str
    payment_label: str
    booking_note: str | None
    # True when this booking became confirmed AFTER the gathering was
    # finished. Covers both new post-Finish bookings AND
    # pending_payment→confirmed webhooks that landed after Finish.
    # The row is in the roster but NOT in the completed cohort.
    pending_post_completion: bool
    # True when the booking was cancelled AFTER Finish. Its attendance
    # value is frozen at the Finish-time state and IS in the completed
    # cohort. UI shows a "Cancelled after finish" tag.
    cancelled_after_completion: bool
    # True when this booking is a member of the completed cohort
    # (see ``_in_finish_cohort``). The frontend uses this to drive the
    # ticket-type breakdown and any other cohort-scoped rendering,
    # so the display rule matches the counts exactly.
    in_finish_cohort: bool


class AttendanceCountsOut(BaseModel):
    """Two orthogonal views on the roster:

    Live counts — the "what does the gathering look like right now"
    view. These change with any booking or cancellation activity.

      * ``total_confirmed`` — currently ``status='confirmed'`` bookings.
      * ``booked`` — currently-confirmed bookings with no attendance
        value yet (in-progress check-ins, or post-completion arrivals).
      * ``pending_post_completion`` — subset of ``booked`` that arrived
        AFTER Finish. Non-zero only when the gathering is completed
        AND at least one booking arrived / was confirmed after the
        finish moment.
      * ``capacity`` — inherited from Event.

    Cohort counts — the "completed summary" view. Derived durably
    from DB state via ``_in_finish_cohort``, so opening the page in
    another browser, after a hard refresh, or after new activity
    always yields the same numbers.

      * ``cohort_size`` — the completed summary denominator. NULL
        when the gathering has never been finished.
      * ``attended`` — bookings in the cohort with
        ``attendance_status='attended'``.
      * ``absent`` — bookings in the cohort with
        ``attendance_status='no_show'``.

    Attendance rate ALWAYS = ``attended / cohort_size`` when the
    gathering is completed. Never ``attended / total_confirmed``. The
    frontend follows this rule verbatim.
    """
    total_confirmed: int
    booked: int
    pending_post_completion: int
    capacity: int | None
    attended: int
    absent: int
    cohort_size: int | None


class AttendanceDashboardOut(BaseModel):
    event: AttendanceEventOut
    counts: AttendanceCountsOut
    bookings: list[AttendanceRowOut]


class AttendanceMutationOut(BaseModel):
    booking_id: str
    attendance_status: str          # API dialect
    attendance_source: str | None
    attendance_marked_at: datetime | None
    counts: AttendanceCountsOut


class AttendanceFinishResponse(BaseModel):
    attendance_completed_at: datetime
    attendance_completed_by: str
    counts: AttendanceCountsOut
    auto_marked_absent: int


class AttendanceReopenResponse(BaseModel):
    counts: AttendanceCountsOut
    restored_to_booked: int


# ---------------------------------------------------------------------------
# Serialisation helpers.
# ---------------------------------------------------------------------------


def _payment_label(booking: EventBooking) -> str:
    """Human-readable payment / entitlement descriptor. Uses ONLY the
    data already on EventBooking + PaymentTransaction — never invents a
    value. Never mutates payment state."""
    if booking.access_pass_id:
        return "Included in pass"
    if booking.payment_transaction_id:
        # The paid ticket amount lives on the transaction. Load lazily to
        # keep the base query slim.
        from app.models.platform import PaymentTransaction
        db = Session.object_session(booking)
        if db is not None:
            tx = db.query(PaymentTransaction).filter(
                PaymentTransaction.id == booking.payment_transaction_id
            ).first()
            if tx and tx.amount_cents is not None:
                cur = (tx.currency or "AUD").upper()
                amount = tx.amount_cents / 100
                return f"{cur} {amount:.2f} · Paid"
    if booking.source == "creator_manual":
        return "Complimentary (creator added)"
    return "Included with collective"


def _ticket_label(event: Event, booking: EventBooking) -> str:
    """The kind of place this booking represents. Reads from the event
    only — no invented fields."""
    if booking.access_pass_id:
        return "Term pass"
    if event.booking_access_type == "paid_separately":
        return "Standalone ticket"
    return "Included booking"


def _serialize_row(
    event: Event, booking: EventBooking, user: User,
) -> AttendanceRowOut:
    completed = event.attendance_completed_at is not None
    b_status = _bstatus(booking)
    # Simpler than a booked_at vs completed_at comparison: Finish sets
    # attendance_status on every confirmed booking that existed at that
    # instant, so any confirmed row still holding NULL after Finish must
    # be a post-completion arrival (new create OR pending→confirmed).
    pending_flag = (
        completed
        and b_status == "confirmed"
        and booking.attendance_status is None
    )
    cancelled_after_completion_flag = (
        completed
        and b_status == "cancelled"
        and booking.attendance_status is not None
    )

    return AttendanceRowOut(
        booking_id=booking.id,
        user_id=user.id,
        name=user.name,
        email=user.email,
        attendance_status=db_status_to_api(booking.attendance_status),
        attendance_source=booking.attendance_source,
        attendance_marked_at=booking.attendance_marked_at,
        booking_reference=booking.id,
        booked_at=booking.booked_at,
        ticket_label=_ticket_label(event, booking),
        payment_label=_payment_label(booking),
        booking_note=booking.note,
        pending_post_completion=pending_flag,
        cancelled_after_completion=cancelled_after_completion_flag,
        in_finish_cohort=_in_finish_cohort(event, booking),
    )


def _dashboard_bookings_query(event: Event, db: Session):
    """The canonical roster query. Rule set:

      * Gathering IN PROGRESS (``attendance_completed_at IS NULL``):
        only ``status='confirmed'`` rows.

      * Gathering FINISHED: ``status='confirmed'`` rows AND
        ``status='cancelled'`` rows that were counted at Finish
        (attendance_status set) AND cancelled AFTER the finish
        moment. Rows cancelled BEFORE Finish never appear even if
        they had a pre-cancellation attendance mark — the creator
        chose to remove them from the gathering before finalising,
        so they aren't part of the completed record.

    The cancelled-branch condition is filtered in Python via
    ``_in_finish_cohort`` after the SQL fetch — the timestamp
    comparison is easier to read there and this table is tiny
    per-event (bounded by gathering capacity).
    """
    from app.models.platform import BookingStatus
    q = (
        db.query(EventBooking, User)
        .join(User, User.id == EventBooking.user_id)
        .filter(EventBooking.event_id == event.id)
        .order_by(User.name.asc(), EventBooking.booked_at.asc())
    )
    if event.attendance_completed_at is None:
        return q.filter(EventBooking.status == BookingStatus.confirmed)
    rows = q.filter(
        (EventBooking.status == BookingStatus.confirmed)
        | (
            (EventBooking.status == BookingStatus.cancelled)
            & (EventBooking.attendance_status.isnot(None))
        )
    ).all()
    # Post-filter cancelled rows on cancelled_at > completed_at using
    # the shared cohort helper. Confirmed rows always pass through.
    kept = [
        (b, u) for (b, u) in rows
        if _bstatus(b) == "confirmed" or _in_finish_cohort(event, b)
    ]
    # Return a lightweight object that quacks like a query for the
    # existing ``.all()`` call sites.
    class _RowList:
        def __init__(self, items): self._items = items
        def all(self): return self._items
        def __iter__(self): return iter(self._items)
        def __len__(self): return len(self._items)
    return _RowList(kept)


def _compute_counts(event: Event, rows: list[tuple[EventBooking, User]]) -> AttendanceCountsOut:
    """See ``AttendanceCountsOut`` for the field-by-field policy.
    Everything derives from the server-visible DB state — the counts
    are stable across refresh, cross-device open, and any post-Finish
    booking activity."""
    completed = event.attendance_completed_at is not None
    total_confirmed = 0
    booked_confirmed = 0
    pending_post_completion = 0
    attended = 0
    absent = 0
    # The query already filters cancelled-before-finish rows out via
    # ``_in_finish_cohort``, so every row we see here is either
    # currently confirmed OR a cohort member. attended/absent can be
    # simple totals.
    for (b, _u) in rows:
        b_status = _bstatus(b)
        if b_status == "confirmed":
            total_confirmed += 1
            if b.attendance_status is None:
                booked_confirmed += 1
                if completed:
                    pending_post_completion += 1
        if b.attendance_status == "attended":
            attended += 1
        elif b.attendance_status == "no_show":
            absent += 1
    return AttendanceCountsOut(
        total_confirmed=total_confirmed,
        booked=booked_confirmed,
        pending_post_completion=pending_post_completion,
        capacity=event.capacity,
        attended=attended,
        absent=absent,
        cohort_size=(attended + absent) if completed else None,
    )


def _serialize_event(space: Space, event: Event) -> AttendanceEventOut:
    return AttendanceEventOut(
        id=event.id,
        title=event.title,
        description=event.description,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        attendance_format=event.attendance_format,
        venue_name=event.venue_name,
        venue_locality=event.venue_locality,
        venue_address=event.venue_address,
        location_url=event.location_url,
        capacity=event.capacity,
        thumbnail_url=event.thumbnail_url,
        status=event.status,
        is_published=event.is_published,
        space_slug=space.slug,
        space_name=space.name,
        attendance_completed_at=event.attendance_completed_at,
        attendance_completed_by=event.attendance_completed_by,
    )


# ---------------------------------------------------------------------------
# GET /attendance — the whole dashboard in one round-trip.
# ---------------------------------------------------------------------------


@router.get(
    "/spaces/{slug}/events/{event_id}/attendance",
    response_model=AttendanceDashboardOut,
)
def get_attendance_dashboard(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> AttendanceDashboardOut:
    """Full payload for the attendance dashboard: event details, roster,
    counts, completion state. One call so the page hydrates fast without
    a burst of secondary requests. Read-only; no locking."""
    space, event = _load_gathering_for_manage(slug, event_id, current_user, db)
    rows = _dashboard_bookings_query(event, db).all()
    return AttendanceDashboardOut(
        event=_serialize_event(space, event),
        counts=_compute_counts(event, rows),
        bookings=[_serialize_row(event, b, u) for (b, u) in rows],
    )


# ---------------------------------------------------------------------------
# PATCH — dashboard-native version. The pre-existing endpoint at
# `.../bookings/{id}/attendance` in creator/routes.py stays where it is
# to keep the wire contract for existing callers unchanged. THIS
# endpoint adds: refresh of the whole counts block in the response,
# 409 when the gathering is completed, and the attendance_source is
# always set to 'manual' since the acting host is by definition a human.
# ---------------------------------------------------------------------------


class DashboardAttendanceRequest(BaseModel):
    # Accepts the API dialect. Also accepts 'no_show'/'pending' as
    # aliases (see translate_api_status).
    status: str = Field(..., description="attended | absent | booked")


@router.patch(
    "/spaces/{slug}/events/{event_id}/attendance/bookings/{booking_id}",
    response_model=AttendanceMutationOut,
)
def dashboard_patch_attendance(
    slug: str,
    event_id: str,
    booking_id: str,
    body: DashboardAttendanceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> AttendanceMutationOut:
    event, booking, _new_db_status = apply_attendance_mutation(
        slug=slug, event_id=event_id, booking_id=booking_id,
        api_status=body.status, user=current_user, db=db,
    )
    db.commit()

    # Re-read the roster so the counts reflect the mutation and any
    # concurrent changes. Same query the GET uses.
    rows = _dashboard_bookings_query(event, db).all()
    return AttendanceMutationOut(
        booking_id=booking.id,
        attendance_status=db_status_to_api(booking.attendance_status),
        attendance_source=booking.attendance_source,
        attendance_marked_at=booking.attendance_marked_at,
        counts=_compute_counts(event, rows),
    )


# ---------------------------------------------------------------------------
# POST /attendance/finish — mark remaining booked as auto-absent and
# lock the gathering. Idempotent (409 if already completed).
# ---------------------------------------------------------------------------


@router.post(
    "/spaces/{slug}/events/{event_id}/attendance/finish",
    response_model=AttendanceFinishResponse,
    status_code=200,
)
def finish_attendance(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> AttendanceFinishResponse:
    _space, event = _load_gathering_for_manage(
        slug, event_id, current_user, db, for_update=True,
    )
    if event.attendance_completed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Gathering attendance is already finished.",
        )

    now = datetime.now(timezone.utc)
    # Mark every unresolved confirmed booking as auto-absent. Payment
    # fields are never touched. Cancelled bookings never enter this
    # loop — the query already excludes them while completed_at is
    # NULL (the state at this point in the function).
    rows = _dashboard_bookings_query(event, db).all()
    auto_marked = 0
    for (b, _u) in rows:
        if _bstatus(b) != "confirmed":
            continue
        if b.attendance_status is None:
            b.attendance_status = "no_show"
            b.attendance_source = "auto"
            b.attendance_marked_at = now
            b.attendance_marked_by = current_user.id
            auto_marked += 1
    event.attendance_completed_at = now
    event.attendance_completed_by = current_user.id
    db.commit()

    rows = _dashboard_bookings_query(event, db).all()
    return AttendanceFinishResponse(
        attendance_completed_at=event.attendance_completed_at,
        attendance_completed_by=event.attendance_completed_by,
        counts=_compute_counts(event, rows),
        auto_marked_absent=auto_marked,
    )


# ---------------------------------------------------------------------------
# POST /attendance/reopen — clear completion, revert auto absences.
# ---------------------------------------------------------------------------


@router.post(
    "/spaces/{slug}/events/{event_id}/attendance/reopen",
    response_model=AttendanceReopenResponse,
    status_code=200,
)
def reopen_attendance(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> AttendanceReopenResponse:
    _space, event = _load_gathering_for_manage(
        slug, event_id, current_user, db, for_update=True,
    )
    if event.attendance_completed_at is None:
        raise HTTPException(
            status_code=409,
            detail="Gathering attendance is not currently finished.",
        )

    # Query includes cancelled-with-attendance rows while the
    # gathering is still marked completed. We skip those in the
    # revert loop — a cancelled row's historical attendance value
    # is a snapshot, not something to reset. Only currently-confirmed
    # rows with auto-absence are reverted. After clearing completed_at
    # the cancelled rows drop out of the dashboard entirely, matching
    # the "in-progress = confirmed only" rule.
    rows = _dashboard_bookings_query(event, db).all()
    restored = 0
    for (b, _u) in rows:
        if _bstatus(b) != "confirmed":
            continue
        if b.attendance_status == "no_show" and b.attendance_source == "auto":
            b.attendance_status = None
            b.attendance_source = None
            b.attendance_marked_at = None
            b.attendance_marked_by = None  # reset audit trail alongside status
            restored += 1
    event.attendance_completed_at = None
    event.attendance_completed_by = None
    db.commit()

    rows = _dashboard_bookings_query(event, db).all()
    return AttendanceReopenResponse(
        counts=_compute_counts(event, rows),
        restored_to_booked=restored,
    )


# ---------------------------------------------------------------------------
# GET /attendance/export.csv — CSV of the same roster.
# ---------------------------------------------------------------------------


# Characters that trigger spreadsheet formula evaluation. Prefixing any
# offending cell with a single quote turns it into a literal in Excel /
# Google Sheets / Numbers. See OWASP CSV injection prevention.
_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _FORMULA_PREFIX:
        s = "'" + s
    return s


@router.get(
    "/spaces/{slug}/events/{event_id}/attendance/export.csv",
)
def export_attendance_csv(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
):
    space, event = _load_gathering_for_manage(slug, event_id, current_user, db)
    rows = _dashboard_bookings_query(event, db).all()
    counts = _compute_counts(event, rows)

    buf = io.StringIO()
    # UTF-8 BOM so Excel opens it correctly.
    buf.write("\ufeff")
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")

    w.writerow([_csv_safe(f"Fresh Collective — {event.title}")])
    w.writerow([_csv_safe("Collective"), _csv_safe(space.name)])
    w.writerow([_csv_safe("Starts at (UTC)"), _csv_safe(event.starts_at.isoformat() if event.starts_at else "")])
    w.writerow([_csv_safe("Venue"), _csv_safe(event.venue_name or ""), _csv_safe(event.venue_locality or "")])
    w.writerow([_csv_safe("Status"), _csv_safe("Completed" if event.attendance_completed_at else "In progress")])
    if event.attendance_completed_at is not None:
        w.writerow([_csv_safe("Completed at (UTC)"), _csv_safe(event.attendance_completed_at.isoformat())])
    w.writerow([_csv_safe("Currently confirmed bookings (live)"), counts.total_confirmed])
    if counts.cohort_size is not None:
        # Cohort-based numbers for the completed record — stable across
        # any post-Finish booking or cancellation activity.
        w.writerow([_csv_safe("Completed cohort size"), counts.cohort_size])
        w.writerow([_csv_safe("Attended"), counts.attended])
        w.writerow([_csv_safe("Absent"), counts.absent])
        rate = (100 * counts.attended / counts.cohort_size) if counts.cohort_size else 0
        w.writerow([_csv_safe("Attendance rate"), f"{rate:.0f}%"])
        if counts.pending_post_completion:
            w.writerow([
                _csv_safe("Bookings arrived after finish (not in cohort)"),
                counts.pending_post_completion,
            ])
    else:
        w.writerow([_csv_safe("Attended (live)"), counts.attended])
        w.writerow([_csv_safe("Absent (live)"), counts.absent])
        w.writerow([_csv_safe("Awaiting check-in"), counts.booked])
    w.writerow([])
    w.writerow([
        _csv_safe("Name"), _csv_safe("Email"), _csv_safe("Booking reference"),
        _csv_safe("Booked at (UTC)"), _csv_safe("Ticket"), _csv_safe("Payment"),
        _csv_safe("Attendance"), _csv_safe("Attendance source"),
        _csv_safe("Attendance marked at (UTC)"), _csv_safe("Booking note"),
        _csv_safe("Booking state"),
    ])
    for (b, u) in rows:
        b_status = _bstatus(b)
        if b_status == "cancelled":
            state_label = "Cancelled after finish (attendance frozen)"
        elif (
            event.attendance_completed_at is not None
            and b.attendance_status is None
        ):
            state_label = "Booked after finish (not in summary)"
        else:
            state_label = "Confirmed"
        w.writerow([
            _csv_safe(u.name or ""),
            _csv_safe(u.email),
            _csv_safe(b.id),
            _csv_safe(b.booked_at.isoformat() if b.booked_at else ""),
            _csv_safe(_ticket_label(event, b)),
            _csv_safe(_payment_label(b)),
            _csv_safe(db_status_to_api(b.attendance_status)),
            _csv_safe(b.attendance_source or ""),
            _csv_safe(b.attendance_marked_at.isoformat() if b.attendance_marked_at else ""),
            _csv_safe(b.note or ""),
            _csv_safe(state_label),
        ])

    filename_slug = (event.title or "gathering").lower().replace(" ", "-")
    filename_slug = "".join(c for c in filename_slug if c.isalnum() or c in ("-", "_"))[:60] or "gathering"
    date_stamp = (event.starts_at.date().isoformat() if event.starts_at else "unknown-date")
    filename = f"attendance-{filename_slug}-{date_stamp}.csv"

    csv_bytes = buf.getvalue().encode("utf-8")

    def _iter() -> Iterable[bytes]:
        yield csv_bytes

    return StreamingResponse(
        _iter(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=0, no-store",
        },
    )


__all__ = [
    "router",
    "translate_api_status",
    "db_status_to_api",
]
