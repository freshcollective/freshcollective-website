"""
Notification API routes.

Endpoints:
  GET  /api/notifications                  — paginated list for current user
  GET  /api/notifications/unread-count     — lightweight badge count
  POST /api/notifications/{id}/read        — mark one as read
  POST /api/notifications/read-all         — mark all as read
  POST /api/spaces/{slug}/broadcast        — creator broadcast to all members
  POST /api/internal/send-event-reminders  — cron endpoint for event reminders
"""
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.internal_auth import verify_internal_token
from app.models.notification import Notification
from app.models.platform import (
    Event,
    EventBooking,
    BookingStatus,
    Space,
    SpaceMembership,
    SpaceMemberNotificationPrefs,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.email_service import email_service, notification_email_html
from app.services.notification_service import create_notification, _get_notification_pref

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    url: str | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationsListResponse(BaseModel):
    notifications: list[NotificationOut]
    unread_count: int


class UnreadCountResponse(BaseModel):
    count: int


class BroadcastRequest(BaseModel):
    title: str
    message: str
    url: str | None = None


# ---------------------------------------------------------------------------
# GET /api/notifications
# ---------------------------------------------------------------------------

@router.get("/api/notifications", response_model=NotificationsListResponse)
def list_notifications(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationsListResponse:
    """Return paginated notifications for the current user."""
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    unread_count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )

    return NotificationsListResponse(
        notifications=[NotificationOut.model_validate(n) for n in notifications],
        unread_count=unread_count,
    )


# ---------------------------------------------------------------------------
# GET /api/notifications/unread-count
# ---------------------------------------------------------------------------

@router.get("/api/notifications/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    """Lightweight endpoint for bell badge polling."""
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )
    return UnreadCountResponse(count=count)


# ---------------------------------------------------------------------------
# POST /api/notifications/{id}/read
# ---------------------------------------------------------------------------

@router.post("/api/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """Mark a single notification as read."""
    notif = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")

    if not notif.is_read:
        notif.is_read = True
        notif.read_at = datetime.utcnow()
        db.commit()
        db.refresh(notif)

    return NotificationOut.model_validate(notif)


# ---------------------------------------------------------------------------
# POST /api/notifications/read-all
# ---------------------------------------------------------------------------

@router.post("/api/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Mark all unread notifications for the current user as read."""
    now = datetime.utcnow()
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False),
    ).update({"is_read": True, "read_at": now})
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/spaces/{slug}/broadcast
# ---------------------------------------------------------------------------

@router.post("/api/spaces/{slug}/broadcast", status_code=status.HTTP_202_ACCEPTED)
def broadcast_to_space(
    slug: str,
    body: BroadcastRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Creator/moderator-only: send an announcement to all active space members.
    Creates in-app notifications immediately; emails queued as a background task.
    """
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    # Check caller is creator or moderator in this space
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership or membership.role not in (SpaceRole.creator, SpaceRole.moderator):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Creator or moderator access required.")

    # Collect all active members
    memberships = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .all()
    )

    recipient_ids = [m.user_id for m in memberships]
    space_id = space.id
    title = body.title
    message = body.message
    url = body.url

    # Create in-app notifications synchronously
    for recipient_id in recipient_ids:
        try:
            create_notification(
                db=db,
                recipient_id=recipient_id,
                notification_type="admin_broadcast",
                title=title,
                message=message,
                url=url,
            )
        except Exception:
            logger.exception("broadcast: failed to create notification for %s", recipient_id)

    # Send emails in background
    background_tasks.add_task(
        _send_broadcast_emails, recipient_ids=recipient_ids, space_id=space_id,
        title=title, message=message, url=url,
    )

    return {"ok": True, "recipients": len(recipient_ids)}


def _send_broadcast_emails(
    recipient_ids: list[str],
    space_id: str,
    title: str,
    message: str,
    url: str | None,
) -> None:
    """Background task: send broadcast emails to members who have opted in."""
    db = SessionLocal()
    try:
        for recipient_id in recipient_ids:
            try:
                if not _get_notification_pref(db, recipient_id, space_id, "admin_broadcast_email"):
                    continue
                user = db.query(User).filter(User.id == recipient_id).first()
                if not user:
                    continue
                html = notification_email_html(title=title, message=message, url=url)
                email_service.send(to=user.email, subject=title, html_body=html)
            except Exception:
                logger.exception("broadcast email failed for recipient %s", recipient_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/internal/send-event-reminders
# ---------------------------------------------------------------------------

@router.post("/api/internal/send-event-reminders", status_code=status.HTTP_202_ACCEPTED)
def send_event_reminders(
    background_tasks: BackgroundTasks,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Cron endpoint: query events starting in ~24h or ~1h and send reminders.
    Protected by X-Internal-Token matching ``INTERNAL_COMMS_SECRET``
    (SEC-007 — a dedicated internal-service credential, independent
    of ``JWT_SECRET`` so possession of this token cannot mint user
    session JWTs).

    Production cron configuration
    -----------------------------
    Frequency:  every 10 minutes.
                The reminder windows are 24h ±15min and 1h ±10min, so
                every event lands in at least one window if the caller
                fires at or below a 10-minute cadence.
    Endpoint:   POST {BACKEND_ORIGIN}/api/internal/send-event-reminders
    Headers:    X-Internal-Token: <value of INTERNAL_COMMS_SECRET on the same env>
                Content-Type:     application/json   (body may be empty)
    Env vars:   INTERNAL_COMMS_SECRET  must be set — the token is
                                       compared via ``secrets.compare_digest``
                RESEND_API_KEY         required for real email delivery
                EMAIL_FROM             required (no fallback domain)

    Recommended scheduler: whatever the host platform provides
    (Render Cron, Fly Machines cron, Cloudflare Cron Triggers, AWS
    EventBridge). No in-process scheduler is registered by the app
    itself so the reminder cadence is a deployment concern, not a
    code concern.
    """
    if not verify_internal_token(x_internal_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token.")

    now = datetime.utcnow()

    # Windows: 24h ±15min and 1h ±10min
    windows = [
        (now + timedelta(hours=24) - timedelta(minutes=15), now + timedelta(hours=24) + timedelta(minutes=15), "24 hours"),
        (now + timedelta(hours=1) - timedelta(minutes=10), now + timedelta(hours=1) + timedelta(minutes=10), "1 hour"),
    ]

    event_ids: list[tuple[str, str]] = []
    for window_start, window_end, label in windows:
        events = (
            db.query(Event)
            .filter(
                Event.is_published.is_(True),
                Event.starts_at >= window_start,
                Event.starts_at <= window_end,
                Event.status == "active",
            )
            .all()
        )
        for event in events:
            event_ids.append((event.id, label))

    if event_ids:
        background_tasks.add_task(_process_event_reminders, event_ids=event_ids)

    return {"ok": True, "events_queued": len(event_ids)}


def _process_event_reminders(event_ids: list[tuple[str, str]]) -> None:
    """Background task: create reminder notifications for booked members."""
    db = SessionLocal()
    try:
        for event_id, time_label in event_ids:
            try:
                event = db.query(Event).filter(Event.id == event_id).first()
                if not event:
                    continue

                title = f"Reminder: {event.title} starts in {time_label}"
                message = f"Your session \"{event.title}\" starts in {time_label}."
                notif_url = None

                # Get all confirmed bookings
                bookings = (
                    db.query(EventBooking)
                    .filter(
                        EventBooking.event_id == event_id,
                        EventBooking.status == BookingStatus.confirmed,
                    )
                    .all()
                )

                for booking in bookings:
                    try:
                        notif = create_notification(
                            db=db,
                            recipient_id=booking.user_id,
                            notification_type="event_reminder",
                            title=title,
                            message=message,
                            url=notif_url,
                        )

                        if _get_notification_pref(
                            db, booking.user_id, event.space_id, "gathering_reminder_email"
                        ):
                            user = db.query(User).filter(User.id == booking.user_id).first()
                            if user:
                                html = notification_email_html(
                                    title=title, message=message, url=notif_url
                                )
                                email_service.send(
                                    to=user.email, subject=title, html_body=html
                                )
                                notif.email_sent_at = datetime.utcnow()
                                db.commit()
                    except Exception:
                        logger.exception(
                            "event reminder failed for user %s event %s", booking.user_id, event_id
                        )
            except Exception:
                logger.exception("event reminder processing failed for event %s", event_id)
    finally:
        db.close()
