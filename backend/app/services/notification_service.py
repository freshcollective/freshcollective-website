"""
Notification service — creates in-app notification records and optionally
sends email based on per-user preference flags.

All public functions that are called from BackgroundTasks create their own
DB session and close it when done, so they are safe to run after the
request-scoped session has been closed.
"""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.notification import Notification
from app.models.platform import (
    CommunityPost,
    Event,
    EventBooking,
    BookingStatus,
    Pathway,
    PostComment,
    Space,
    SpaceMembership,
    SpaceMemberNotificationPrefs,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.email_service import email_service, notification_email_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def create_notification(
    db: Session,
    recipient_id: str,
    notification_type: str,
    title: str,
    message: str,
    url: str | None = None,
) -> Notification:
    """Create an in-app notification record and persist it."""
    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=recipient_id,
        notification_type=notification_type,
        title=title,
        message=message,
        url=url,
        is_read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def _get_notification_pref(
    db: Session,
    user_id: str,
    space_id: str,
    pref_key: str,
) -> bool:
    """Return the value of a notification preference for a user+space pair.
    Falls back to the column default (True for most email prefs) when no row exists."""
    prefs = (
        db.query(SpaceMemberNotificationPrefs)
        .filter(
            SpaceMemberNotificationPrefs.user_id == user_id,
            SpaceMemberNotificationPrefs.space_id == space_id,
        )
        .first()
    )
    if prefs is None:
        # No row → use model default (True for most email prefs)
        defaults: dict[str, bool] = {
            "weekly_digest_email": True,
            "daily_digest_email": False,
            "admin_broadcast_email": True,
            "gathering_reminder_email": True,
            "new_post_email": False,
            "comment_reply_email": True,
            "pathway_comment_email": True,
            "new_pathway_email": True,
        }
        return defaults.get(pref_key, False)
    return bool(getattr(prefs, pref_key, False))


def send_notification(
    recipient_id: str,
    notification_type: str,
    title: str,
    message: str,
    url: str | None = None,
    space_id: str | None = None,
    pref_key: str | None = None,
) -> None:
    """
    Background-task-safe: creates its own DB session.
    Creates an in-app notification.  If pref_key and space_id are given,
    checks the user's email preference before sending an email.
    """
    db = SessionLocal()
    try:
        notif = create_notification(
            db=db,
            recipient_id=recipient_id,
            notification_type=notification_type,
            title=title,
            message=message,
            url=url,
        )

        # Email — only if preference check passes
        should_email = False
        if pref_key and space_id:
            should_email = _get_notification_pref(db, recipient_id, space_id, pref_key)

        if should_email:
            user = db.query(User).filter(User.id == recipient_id).first()
            if user:
                html = notification_email_html(title=title, message=message, url=url)
                email_service.send(to=user.email, subject=title, html_body=html)
                # Record email sent timestamp
                notif.email_sent_at = datetime.utcnow()
                db.commit()
    except Exception:
        logger.exception("send_notification failed for recipient %s", recipient_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Trigger helpers — called from BackgroundTasks
# ---------------------------------------------------------------------------

def trigger_comment_reply(post_id: str, comment_id: str, commenter_id: str) -> None:
    """Notify the post author when someone comments (unless the commenter is the author)."""
    db = SessionLocal()
    try:
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post:
            return

        # Don't notify if the commenter is the post author
        if post.author_id == commenter_id:
            return

        commenter = db.query(User).filter(User.id == commenter_id).first()
        commenter_name = commenter.name or "Someone" if commenter else "Someone"

        post_title = post.title or "your post"
        title = "New reply on your post"
        message = f"{commenter_name} replied to \"{post_title}\"."
        space = db.query(Space).filter(Space.id == post.space_id).first() if post.space_id else None
        notif_url = f"/spaces/{space.slug}/community/{post.id}" if space else None

        notif = create_notification(
            db=db,
            recipient_id=post.author_id,
            notification_type="comment_reply",
            title=title,
            message=message,
            url=notif_url,
        )

        # Email pref check
        if _get_notification_pref(db, post.author_id, post.space_id, "comment_reply_email"):
            author = db.query(User).filter(User.id == post.author_id).first()
            if author:
                html = notification_email_html(title=title, message=message, url=notif_url)
                email_service.send(to=author.email, subject=title, html_body=html)
                notif.email_sent_at = datetime.utcnow()
                db.commit()
    except Exception:
        logger.exception("trigger_comment_reply failed for post %s, comment %s", post_id, comment_id)
    finally:
        db.close()


def trigger_new_post(post_id: str, space_id: str, author_id: str) -> None:
    """Notify all space members with new_post_email=True (excluding the author)."""
    db = SessionLocal()
    try:
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post:
            return

        author = db.query(User).filter(User.id == author_id).first()
        author_name = author.name or "A member" if author else "A member"

        post_title = post.title or "a new post"
        title = "New post in the community"
        message = f"{author_name} shared {post_title}."
        space = db.query(Space).filter(Space.id == space_id).first()
        space_slug = space.slug if space else space_id
        notif_url = f"/spaces/{space_slug}/community/{post_id}"

        # Get all active members in the space (excluding author)
        memberships = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space_id,
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.user_id != author_id,
            )
            .all()
        )

        for membership in memberships:
            try:
                notif = create_notification(
                    db=db,
                    recipient_id=membership.user_id,
                    notification_type="new_post",
                    title=title,
                    message=message,
                    url=notif_url,
                )

                # Only email if pref enabled (new_post_email defaults to False)
                if _get_notification_pref(db, membership.user_id, space_id, "new_post_email"):
                    member = db.query(User).filter(User.id == membership.user_id).first()
                    if member:
                        html = notification_email_html(title=title, message=message, url=notif_url)
                        email_service.send(to=member.email, subject=title, html_body=html)
                        notif.email_sent_at = datetime.utcnow()
                        db.commit()
            except Exception:
                logger.exception("trigger_new_post failed for member %s", membership.user_id)
    except Exception:
        logger.exception("trigger_new_post failed for post %s in space %s", post_id, space_id)
    finally:
        db.close()


def trigger_event_booking_creator(event_id: str, booking_user_id: str) -> None:
    """Notify space creators and moderators when someone books an event."""
    db = SessionLocal()
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return

        booker = db.query(User).filter(User.id == booking_user_id).first()
        booker_name = booker.name or "A member" if booker else "A member"

        title = "New event booking"
        message = f"{booker_name} booked a spot for \"{event.title}\"."
        notif_url = None  # TODO: link to creator studio event detail when available

        # Notify all creators and moderators in the space
        privileged_memberships = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == event.space_id,
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
                SpaceMembership.user_id != booking_user_id,
            )
            .all()
        )

        for membership in privileged_memberships:
            try:
                create_notification(
                    db=db,
                    recipient_id=membership.user_id,
                    notification_type="event_registration",
                    title=title,
                    message=message,
                    url=notif_url,
                )
            except Exception:
                logger.exception(
                    "trigger_event_booking_creator failed for creator %s", membership.user_id
                )
    except Exception:
        logger.exception("trigger_event_booking_creator failed for event %s", event_id)
    finally:
        db.close()


def trigger_new_pathway(pathway_id: str) -> None:
    """Notify all space members with new_pathway_email=True when a pathway is published."""
    db = SessionLocal()
    try:
        pathway = db.query(Pathway).filter(Pathway.id == pathway_id).first()
        if not pathway:
            return

        title = "New pathway available"
        message = f"A new pathway has been added: \"{pathway.title}\"."
        space = db.query(Space).filter(Space.id == pathway.space_id).first() if pathway.space_id else None
        notif_url = f"/spaces/{space.slug}/pathways/{pathway.slug}" if space else None

        memberships = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == pathway.space_id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        )

        for membership in memberships:
            try:
                notif = create_notification(
                    db=db,
                    recipient_id=membership.user_id,
                    notification_type="new_pathway",
                    title=title,
                    message=message,
                    url=notif_url,
                )

                if _get_notification_pref(db, membership.user_id, pathway.space_id, "new_pathway_email"):
                    member = db.query(User).filter(User.id == membership.user_id).first()
                    if member:
                        html = notification_email_html(title=title, message=message, url=notif_url)
                        email_service.send(to=member.email, subject=title, html_body=html)
                        notif.email_sent_at = datetime.utcnow()
                        db.commit()
            except Exception:
                logger.exception("trigger_new_pathway failed for member %s", membership.user_id)
    except Exception:
        logger.exception("trigger_new_pathway failed for pathway %s", pathway_id)
    finally:
        db.close()
