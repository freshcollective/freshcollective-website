"""
Direct messaging routes — creator ↔ member within a collective.

Creator-facing  (requires creator/admin role):
  POST   /api/creator/spaces/{slug}/messages                  send first message / reply
  GET    /api/creator/spaces/{slug}/messages                  list threads
  GET    /api/creator/spaces/{slug}/messages/{thread_id}      get thread with messages
  POST   /api/creator/spaces/{slug}/messages/{thread_id}/read mark thread read (creator side)

Member-facing  (requires active membership):
  GET    /api/spaces/{slug}/messages                          list my threads
  GET    /api/spaces/{slug}/messages/{thread_id}              get thread with messages
  POST   /api/spaces/{slug}/messages/{thread_id}/reply        reply to creator
  POST   /api/spaces/{slug}/messages/{thread_id}/read         mark thread read (member side)
"""

import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.models.user import User

creator_router = APIRouter(prefix="/api/creator", tags=["messages-creator"])
member_router  = APIRouter(prefix="/api/spaces",  tags=["messages-member"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTML_RE = re.compile(r"<[^>]+>")


def _sanitize(text: str) -> str:
    """Strip HTML tags; normalise whitespace. Plain-text only."""
    return _HTML_RE.sub("", text).strip()


def _get_managed_space(slug: str, user: User, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")
    if user.role in ("admin", "creator"):
        return space
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorised to manage this space.")
    return space


def _get_member_space(slug: str, user: User, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this space.")
    return space


def _user_display(user: User) -> str:
    return user.display_name or user.name or user.email.split("@")[0]


def _unread_count_for(db: Session, thread_id: str, reader_id: str) -> int:
    """Count messages in thread that are unread and NOT sent by the reader."""
    return (
        db.query(DirectMessage)
        .filter(
            DirectMessage.thread_id == thread_id,
            DirectMessage.sender_id != reader_id,
            DirectMessage.is_read == False,  # noqa: E712
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MessageOut(BaseModel):
    id: str
    sender_id: str
    sender_name: str
    body: str
    is_read: bool
    created_at: str


class ThreadSummary(BaseModel):
    thread_id: str
    other_user_id: str
    other_user_name: str
    last_message: str | None
    last_message_at: str | None
    unread_count: int


class ThreadDetail(BaseModel):
    thread_id: str
    space_id: str
    creator_id: str
    creator_name: str
    member_id: str
    member_name: str
    messages: list[MessageOut]
    unread_count: int


class SendMessageRequest(BaseModel):
    member_id: str
    body: str


class ReplyRequest(BaseModel):
    body: str


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _message_out(msg: DirectMessage, db: Session) -> MessageOut:
    sender = db.query(User).filter(User.id == msg.sender_id).first()
    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        sender_name=_user_display(sender) if sender else "Unknown",
        body=msg.body,
        is_read=msg.is_read,
        created_at=msg.created_at.isoformat(),
    )


def _thread_detail(thread: MessageThread, viewer_id: str, db: Session) -> ThreadDetail:
    creator = db.query(User).filter(User.id == thread.creator_id).first()
    member  = db.query(User).filter(User.id == thread.member_id).first()
    msgs = [_message_out(m, db) for m in thread.messages]
    return ThreadDetail(
        thread_id=thread.id,
        space_id=thread.space_id,
        creator_id=thread.creator_id,
        creator_name=_user_display(creator) if creator else "Creator",
        member_id=thread.member_id,
        member_name=_user_display(member) if member else "Member",
        messages=msgs,
        unread_count=_unread_count_for(db, thread.id, viewer_id),
    )


def _thread_summary(thread: MessageThread, viewer_id: str, db: Session) -> ThreadSummary:
    if viewer_id == thread.creator_id:
        other_id = thread.member_id
    else:
        other_id = thread.creator_id
    other = db.query(User).filter(User.id == other_id).first()
    last_msg = thread.messages[-1] if thread.messages else None
    return ThreadSummary(
        thread_id=thread.id,
        other_user_id=other_id,
        other_user_name=_user_display(other) if other else "Unknown",
        last_message=last_msg.body[:120] if last_msg else None,
        last_message_at=last_msg.created_at.isoformat() if last_msg else None,
        unread_count=_unread_count_for(db, thread.id, viewer_id),
    )


# ---------------------------------------------------------------------------
# Creator endpoints
# ---------------------------------------------------------------------------

@creator_router.get("/spaces/{slug}/messages", response_model=list[ThreadSummary])
def creator_list_threads(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadSummary]:
    space = _get_managed_space(slug, current_user, db)
    threads = (
        db.query(MessageThread)
        .filter(
            MessageThread.space_id == space.id,
            MessageThread.creator_id == current_user.id,
        )
        .order_by(MessageThread.updated_at.desc())
        .all()
    )
    return [_thread_summary(t, current_user.id, db) for t in threads]


@creator_router.get("/spaces/{slug}/messages/{thread_id}", response_model=ThreadDetail)
def creator_get_thread(
    slug: str,
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadDetail:
    space = _get_managed_space(slug, current_user, db)
    thread = db.query(MessageThread).filter(
        MessageThread.id == thread_id,
        MessageThread.space_id == space.id,
        MessageThread.creator_id == current_user.id,
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return _thread_detail(thread, current_user.id, db)


@creator_router.post("/spaces/{slug}/messages", response_model=ThreadDetail, status_code=201)
def creator_send_message(
    slug: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadDetail:
    """Send a message to a member. Creates a thread if one doesn't exist."""
    space = _get_managed_space(slug, current_user, db)

    text = _sanitize(body.body)
    if not text:
        raise HTTPException(status_code=422, detail="Message body cannot be empty.")

    # Verify recipient is an active member of this space
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == body.member_id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    # Get or create thread
    thread = (
        db.query(MessageThread)
        .filter(
            MessageThread.space_id == space.id,
            MessageThread.creator_id == current_user.id,
            MessageThread.member_id == body.member_id,
        )
        .first()
    )
    is_new_thread = thread is None
    if thread is None:
        thread = MessageThread(
            id=str(uuid4()),
            space_id=space.id,
            creator_id=current_user.id,
            member_id=body.member_id,
        )
        db.add(thread)
        db.flush()

    msg = DirectMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sender_id=current_user.id,
        body=text,
        is_read=False,
    )
    db.add(msg)
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(thread)

    # Notify the member
    sender_name = _user_display(current_user)
    thread_url = f"/spaces/{slug}/messages/{thread.id}"
    background_tasks.add_task(
        _notify_direct_message,
        recipient_id=body.member_id,
        sender_name=sender_name,
        space_id=space.id,
        thread_url=thread_url,
        preview=text[:80],
    )
    # Communications Layer (M5c) — emit alongside the legacy notify.
    from app.comms import Source, emit
    from app.comms.rollout import schedule_routing_if_needed
    event = emit(
        db,
        event_type="dm.message.sent",
        source_type=Source.CREATOR,
        source_id=current_user.id,
        actor_user_id=current_user.id,
        subject_type="thread", subject_id=thread.id,
        context={"space_id": space.id},
        payload={
            "recipient_id": body.member_id,
            "sender_name": sender_name,
            "thread_id": thread.id,
            "excerpt": text[:80],
        },
    )
    db.commit()
    schedule_routing_if_needed(background_tasks, event, "dm.message.sent")

    return _thread_detail(thread, current_user.id, db)


@creator_router.post("/spaces/{slug}/messages/{thread_id}/read", status_code=204)
def creator_mark_read(
    slug: str,
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    thread = db.query(MessageThread).filter(
        MessageThread.id == thread_id,
        MessageThread.space_id == space.id,
        MessageThread.creator_id == current_user.id,
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")
    now = datetime.utcnow()
    db.query(DirectMessage).filter(
        DirectMessage.thread_id == thread_id,
        DirectMessage.sender_id != current_user.id,
        DirectMessage.is_read == False,  # noqa: E712
    ).update({"is_read": True, "read_at": now})
    db.commit()


# ---------------------------------------------------------------------------
# Member endpoints
# ---------------------------------------------------------------------------

@member_router.get("/{slug}/messages", response_model=list[ThreadSummary])
def member_list_threads(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ThreadSummary]:
    _get_member_space(slug, current_user, db)
    space = db.query(Space).filter(Space.slug == slug).first()
    threads = (
        db.query(MessageThread)
        .filter(
            MessageThread.space_id == space.id,
            MessageThread.member_id == current_user.id,
        )
        .order_by(MessageThread.updated_at.desc())
        .all()
    )
    return [_thread_summary(t, current_user.id, db) for t in threads]


@member_router.get("/{slug}/messages/{thread_id}", response_model=ThreadDetail)
def member_get_thread(
    slug: str,
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadDetail:
    space = _get_member_space(slug, current_user, db)
    thread = db.query(MessageThread).filter(
        MessageThread.id == thread_id,
        MessageThread.space_id == space.id,
        MessageThread.member_id == current_user.id,
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return _thread_detail(thread, current_user.id, db)


@member_router.post("/{slug}/messages/{thread_id}/reply", response_model=ThreadDetail)
def member_reply(
    slug: str,
    thread_id: str,
    body: ReplyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadDetail:
    space = _get_member_space(slug, current_user, db)
    thread = db.query(MessageThread).filter(
        MessageThread.id == thread_id,
        MessageThread.space_id == space.id,
        MessageThread.member_id == current_user.id,
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    text = _sanitize(body.body)
    if not text:
        raise HTTPException(status_code=422, detail="Message body cannot be empty.")

    msg = DirectMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sender_id=current_user.id,
        body=text,
        is_read=False,
    )
    db.add(msg)
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(thread)

    # Notify the creator
    sender_name = _user_display(current_user)
    background_tasks.add_task(
        _notify_direct_message,
        recipient_id=thread.creator_id,
        sender_name=sender_name,
        space_id=space.id,
        thread_url=None,  # Creator views via Creator Studio
        preview=text[:80],
    )
    # Communications Layer (M5c) — emit alongside the legacy notify.
    from app.comms import Source, emit
    from app.comms.rollout import schedule_routing_if_needed
    event = emit(
        db,
        event_type="dm.message.sent",
        source_type=Source.CREATOR,
        source_id=current_user.id,
        actor_user_id=current_user.id,
        subject_type="thread", subject_id=thread.id,
        context={"space_id": space.id},
        payload={
            "recipient_id": thread.creator_id,
            "sender_name": sender_name,
            "thread_id": thread.id,
            "excerpt": text[:80],
        },
    )
    db.commit()
    schedule_routing_if_needed(background_tasks, event, "dm.message.sent")

    return _thread_detail(thread, current_user.id, db)


@member_router.post("/{slug}/messages/{thread_id}/read", status_code=204)
def member_mark_read(
    slug: str,
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    space = _get_member_space(slug, current_user, db)
    thread = db.query(MessageThread).filter(
        MessageThread.id == thread_id,
        MessageThread.space_id == space.id,
        MessageThread.member_id == current_user.id,
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")
    now = datetime.utcnow()
    db.query(DirectMessage).filter(
        DirectMessage.thread_id == thread_id,
        DirectMessage.sender_id != current_user.id,
        DirectMessage.is_read == False,  # noqa: E712
    ).update({"is_read": True, "read_at": now})
    db.commit()


# ---------------------------------------------------------------------------
# Notification helper (runs in background task)
# ---------------------------------------------------------------------------

def _notify_direct_message(
    recipient_id: str,
    sender_name: str,
    space_id: str,
    thread_url: str | None,
    preview: str,
) -> None:
    # M5c cutover guard — when dm.message.sent is live, the routing
    # pipeline handles delivery and this legacy notify no-ops.
    from app.comms.rollout import is_event_live
    if is_event_live("dm.message.sent"):
        return
    from app.services.notification_service import send_notification
    send_notification(
        recipient_id=recipient_id,
        notification_type="direct_message",
        title=f"Message from {sender_name}",
        message=preview if len(preview) < 80 else preview[:77] + "…",
        url=thread_url,
        space_id=space_id,
        pref_key="direct_message_email",
    )
