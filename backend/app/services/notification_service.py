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
    ConversationChannel,
    Event,
    EventBooking,
    BookingStatus,
    Pathway,
    PathwayStep,
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


def _channel_name(channel_id: str | None, db: Session) -> str | None:
    """Human-readable Channel name for use inside notification copy.
    Returns None for system Channels (Start Here + Common Room) so
    notifications coming from them read as "New conversation" rather
    than the noisier "New conversation in Common Room"."""
    if not channel_id:
        return None
    c = db.query(ConversationChannel).filter(ConversationChannel.id == channel_id).first()
    if c is None:
        return None
    if c.is_system:
        return None
    return c.name


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
            "direct_message_email": True,
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

        post_title = post.title or "a new conversation"
        # Terminology shift — "the community" is retired as a visible label
        # in favour of "Conversations". Backend internals + routes keep
        # the community_posts naming for now.
        # Include the Channel name so a member scanning notifications can
        # tell where the conversation belongs (General vs. a specific
        # Pathway / Private Channel).
        channel_name = _channel_name(post.channel_id, db)
        title = f"New conversation in {channel_name}" if channel_name else "New conversation"
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


def trigger_new_step(step_id: str, creator_id: str) -> None:
    """Notify active space members when a new step is added to a pathway (excluding the creator)."""
    db = SessionLocal()
    try:
        step = db.query(PathwayStep).filter(PathwayStep.id == step_id).first()
        if not step:
            return

        pathway = db.query(Pathway).filter(Pathway.id == step.pathway_id).first()
        if not pathway or not pathway.space_id:
            return

        space = db.query(Space).filter(Space.id == pathway.space_id).first()
        if not space:
            return

        title = f"New step added: \"{step.title}\""
        message = f"A new step has been added to the pathway \"{pathway.title}\"."
        notif_url = f"/spaces/{space.slug}/pathways/{pathway.slug}/{step.slug}"

        memberships = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == pathway.space_id,
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.user_id != creator_id,
            )
            .all()
        )

        for membership in memberships:
            try:
                notif = create_notification(
                    db=db,
                    recipient_id=membership.user_id,
                    notification_type="new_pathway_step",
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
                logger.exception("trigger_new_step failed for member %s", membership.user_id)
    except Exception:
        logger.exception("trigger_new_step failed for step %s", step_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Community Phase 1 — reply, mention, caretaker-answer triggers
# ---------------------------------------------------------------------------
#
# Each trigger creates a distinct notification_type so the notifications
# UI can label + colour it appropriately. Email preferences reuse the
# existing `comment_reply_email` flag for reply-shaped events; mentions
# and caretaker-answers ignore email prefs for now (in-app only) so we
# don't inbox-spam members while the feature settles.

def _short(text: str, max_len: int = 120) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def trigger_reply_to_comment(
    post_id: str,
    comment_id: str,
    parent_comment_id: str,
    commenter_id: str,
) -> None:
    """Notify the parent comment's author when someone replies to them."""
    db = SessionLocal()
    try:
        parent = db.query(PostComment).filter(PostComment.id == parent_comment_id).first()
        if not parent or parent.author_id == commenter_id:
            return
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post:
            return
        commenter = db.query(User).filter(User.id == commenter_id).first()
        commenter_name = (commenter.name if commenter and commenter.name else "Someone")
        title = "New reply to your comment"
        message = f"{commenter_name} replied to your comment."
        space = db.query(Space).filter(Space.id == post.space_id).first()
        notif_url = f"/spaces/{space.slug}/community/{post.id}" if space else None

        notif = create_notification(
            db=db,
            recipient_id=parent.author_id,
            notification_type="comment_reply",
            title=title,
            message=message,
            url=notif_url,
        )
        if _get_notification_pref(db, parent.author_id, post.space_id, "comment_reply_email"):
            recipient = db.query(User).filter(User.id == parent.author_id).first()
            if recipient:
                html = notification_email_html(title=title, message=message, url=notif_url)
                email_service.send(to=recipient.email, subject=title, html_body=html)
                notif.email_sent_at = datetime.utcnow()
                db.commit()
    except Exception:
        logger.exception("trigger_reply_to_comment failed for comment %s", comment_id)
    finally:
        db.close()


def trigger_mention(
    post_id: str,
    comment_id: str | None,
    author_id: str,
    mentioned_user_id: str,
) -> None:
    """Notify a member when they've been @mentioned in a post or comment.

    Scope-safety: mention resolution already filtered to active members
    of the target space, so this trigger only needs to render the
    notification.
    """
    if mentioned_user_id == author_id:
        return
    db = SessionLocal()
    try:
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post:
            return
        author = db.query(User).filter(User.id == author_id).first()
        author_name = (author.name if author and author.name else "Someone")
        space = db.query(Space).filter(Space.id == post.space_id).first()
        notif_url = f"/spaces/{space.slug}/community/{post.id}" if space else None
        channel_name = _channel_name(post.channel_id, db)
        where = "in a comment" if comment_id else (
            f"in \"{post.title}\"" if post.title else "in a conversation"
        )
        if channel_name:
            where = f"{where} in {channel_name}"
        title = f"{author_name} mentioned you"
        message = f"{author_name} mentioned you {where}."
        create_notification(
            db=db,
            recipient_id=mentioned_user_id,
            notification_type="mention",
            title=title,
            message=message,
            url=notif_url,
        )
    except Exception:
        logger.exception("trigger_mention failed for user %s", mentioned_user_id)
    finally:
        db.close()


def trigger_caretaker_reply_to_question(
    post_id: str,
    comment_id: str,
    responder_id: str,
) -> None:
    """When a caretaker (space creator/moderator, or platform admin) answers
    a Question post, ping the question's author with a distinct notification.

    This fires *in addition to* the normal comment_reply trigger, so the
    original poster feels seen when the person who runs the collective
    replies. Idempotent: if the responder is the question's own author,
    or not a caretaker, we noop.
    """
    db = SessionLocal()
    try:
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post or post.author_id == responder_id:
            return
        responder = db.query(User).filter(User.id == responder_id).first()
        if not responder:
            return

        is_caretaker = responder.role in ("admin", "creator")
        if not is_caretaker:
            membership_role = (
                db.query(SpaceMembership.role)
                .filter(
                    SpaceMembership.space_id == post.space_id,
                    SpaceMembership.user_id == responder_id,
                    SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
                    SpaceMembership.status == SpaceMembershipStatus.active,
                )
                .first()
            )
            is_caretaker = membership_role is not None
        if not is_caretaker:
            return

        responder_name = responder.name or "A Creator"
        title = "A Creator replied to your question"
        message = f"{responder_name} replied to your question."
        space = db.query(Space).filter(Space.id == post.space_id).first()
        notif_url = f"/spaces/{space.slug}/community/{post.id}" if space else None
        create_notification(
            db=db,
            recipient_id=post.author_id,
            notification_type="caretaker_answer",
            title=title,
            message=message,
            url=notif_url,
        )
    except Exception:
        logger.exception("trigger_caretaker_reply_to_question failed for post %s", post_id)
    finally:
        db.close()


def trigger_booking_confirmed(event_id: str, user_id: str) -> None:
    """Confirmation email to the member who booked a gathering.

    Companion to :func:`trigger_event_booking_creator` — that one tells
    the Creator; this one thanks the booker. In-app + email if the
    caller opted in via ``gathering_reminder_email`` (same pref used by
    the reminder job — bookers who mute reminders also opt out of the
    confirmation).
    """
    from app.services.email_service import email_service
    from app.services.email_templates import booking_confirmation_email
    from app.core.config import settings

    db = SessionLocal()
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return
        booker = db.query(User).filter(User.id == user_id).first()
        if not booker:
            return
        space = db.query(Space).filter(Space.id == event.space_id).first() if event.space_id else None

        booker_name = booker.name or booker.email.split("@", 1)[0]
        # Pre-format the "when" using the space's timezone if we have one,
        # else UTC as a safe fallback. The template doesn't need to know
        # anything about tz handling — it just prints what we hand it.
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(space.timezone) if space and space.timezone else None
        except Exception:
            tz = None
        starts_local = event.starts_at.astimezone(tz) if tz else event.starts_at
        starts_when = starts_local.strftime("%A %-d %B %Y at %-I:%M %p")

        location_line = _format_event_location(event)

        view_url = None
        if space:
            view_url = f"{settings.frontend_origin.rstrip('/')}/spaces/{space.slug}/events/{event.id}"

        title = f"Booking confirmed: {event.title}"
        message = f'Your place is held at "{event.title}" on {starts_when}.'

        notif = create_notification(
            db=db,
            recipient_id=user_id,
            notification_type="booking_confirmed",
            title=title,
            message=message,
            url=view_url,
        )

        should_email = _get_notification_pref(
            db, user_id, event.space_id, "gathering_reminder_email",
        )
        if should_email and view_url:
            subject, html = booking_confirmation_email(
                member_name=booker_name,
                gathering_title=event.title,
                starts_when=starts_when,
                location_line=location_line,
                view_url=view_url,
                add_to_calendar_url=None,   # feature TODO — no ICS endpoint yet
            )
            email_service.send(to=booker.email, subject=subject, html_body=html)
            notif.email_sent_at = datetime.utcnow()
            db.commit()
    except Exception:
        logger.exception("trigger_booking_confirmed failed for event %s user %s", event_id, user_id)
    finally:
        db.close()


def _format_event_location(event: Event) -> str:
    """Short human-readable location string for booking emails."""
    loc = getattr(event, "location_type", None)
    if loc == "zoom":
        return "Zoom link — shared before the gathering"
    if loc == "in_person":
        return "In person"
    if loc == "async_recorded":
        return "Recorded — available in the gathering page"
    return "Details in the gathering page"
