"""
Direct messaging routes — creator ↔ member within a collective.

Creator-facing  (requires creator/admin role):
  POST   /api/creator/spaces/{slug}/messages                  send first message / reply
  GET    /api/creator/spaces/{slug}/messages/broadcast/recipients  how many would receive
  POST   /api/creator/spaces/{slug}/messages/broadcast        same message to every member
  GET    /api/creator/spaces/{slug}/messages                  list threads
  GET    /api/creator/spaces/{slug}/messages/{thread_id}      get thread with messages
  POST   /api/creator/spaces/{slug}/messages/{thread_id}/read mark thread read (creator side)

Member-facing  (requires active membership):
  GET    /api/spaces/{slug}/messages                          list my threads
  GET    /api/spaces/{slug}/messages/{thread_id}              get thread with messages
  POST   /api/spaces/{slug}/messages/{thread_id}/reply        reply to creator
  POST   /api/spaces/{slug}/messages/{thread_id}/read         mark thread read (member side)
"""

import logging
import re
from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.database import get_db
from app.models.messages import DirectMessage, MessageThread
from app.models.platform import (
    CreatorProfile,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.member_identity import (
    NEUTRAL_DISPLAY_NAME,
    display_name as member_display_name,
)

logger = logging.getLogger(__name__)

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
    """SEC-005-E — creator-side direct-message management gate.

    Deliberately stricter than the generic Collective helpers: neither
    platform ``creator`` role nor platform ``admin`` role grants
    automatic access to a Collective's DMs. Authority requires one of:

      * ``Space.creator_id`` ownership;
      * active ``SpaceMembership`` with role in {creator, moderator}.

    Consistent with the sibling ``_get_message_member_space`` (SEC-005-D)
    stance: private/direct-message access is not inherited from
    platform-wide roles. A future explicit safety/reporting workflow
    for DMs must go through its own gated endpoint, not through this
    helper.
    """
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")
    if space.creator_id == user.id:
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


def _get_message_member_space(slug: str, user: User, db: Session) -> Space:
    """SEC-005-D — direct-message member gate.

    Deliberately stricter than the community-facing
    ``spaces.routes._get_member_space``:

      * NO platform-role bypass. A platform admin or platform-role
        creator without a real ``SpaceMembership`` in this Collective
        is refused. Direct messages are 1:1 conversations between a
        member and the collective's creator; admin snooping is not a
        supported access path. If SEC-005-E later grants admins a
        formal DM-audit surface, that must go through its own gated
        endpoint, not through this helper.
      * NO space-owner bypass. Owners see their creator side of
        threads via the creator endpoints; the member side is only
        for the participant.
      * 403 (not 404) on failure — the endpoint's existence is not a
        secret to authenticated callers.

    Named ``_get_message_member_space`` so the divergence from
    ``spaces.routes._get_member_space`` is obvious at every call site
    and cannot silently drift into that helper's broader bypass set
    during a future refactor.
    """
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


def _display_names(db: Session, user_ids: Iterable[str | None]) -> dict[str, str]:
    """Names for a request's worth of people, resolved once.

    The helper this replaces read ``user.display_name`` first — a column
    ``User`` does not have. It is only ever handed ``User`` rows, so every
    call raised ``AttributeError`` and every messages endpoint that
    serialises a thread or a message answered 500. There were no tests
    over this router, which is why a passing suite never noticed.

    ``display_name`` lives on ``CreatorProfile``, so that is what gets
    looked up — the intent the broken line was reaching for. Resolved in
    one pair of queries rather than one per message, because the old
    ``_message_out`` re-queried the sender for every message in a thread.
    """
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}

    users = db.query(User).filter(User.id.in_(ids)).all()
    # ``is_public`` filtered, as on every other member surface: a private
    # profile must not supply a display name here either.
    profiles = {
        cp.user_id: cp
        for cp in db.query(CreatorProfile)
        .filter(
            CreatorProfile.user_id.in_(ids),
            CreatorProfile.is_public.is_(True),
        )
        .all()
    }
    return {u.id: member_display_name(u, profiles.get(u.id)) for u in users}


def _one_display_name(db: Session, user: User) -> str:
    """The same ladder, for a single person."""
    return _display_names(db, [user.id]).get(user.id, NEUTRAL_DISPLAY_NAME)


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


class BroadcastRequest(BaseModel):
    body: str


class BroadcastRecipients(BaseModel):
    """What the creator is told *before* they send."""
    count: int


class BroadcastFailure(BaseModel):
    member_id: str
    reason: str


class BroadcastResult(BaseModel):
    """What happened. ``recipients`` is what we set out to do, ``sent``
    is what landed — they differ only when something failed."""
    recipients: int
    sent: int
    failed: int
    failures: list[BroadcastFailure]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _message_out(msg: DirectMessage, names: dict[str, str]) -> MessageOut:
    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        # A message must name its sender, so a missing row still gets a
        # label. It means a deleted account rather than an unnamed one.
        sender_name=names.get(msg.sender_id, NEUTRAL_DISPLAY_NAME),
        body=msg.body,
        is_read=msg.is_read,
        created_at=msg.created_at.isoformat(),
    )


def _thread_detail(thread: MessageThread, viewer_id: str, db: Session) -> ThreadDetail:
    names = _display_names(
        db,
        [thread.creator_id, thread.member_id, *(m.sender_id for m in thread.messages)],
    )
    return ThreadDetail(
        thread_id=thread.id,
        space_id=thread.space_id,
        creator_id=thread.creator_id,
        creator_name=names.get(thread.creator_id, NEUTRAL_DISPLAY_NAME),
        member_id=thread.member_id,
        member_name=names.get(thread.member_id, NEUTRAL_DISPLAY_NAME),
        messages=[_message_out(m, names) for m in thread.messages],
        unread_count=_unread_count_for(db, thread.id, viewer_id),
    )


def _thread_summary(
    thread: MessageThread,
    viewer_id: str,
    db: Session,
    names: dict[str, str] | None = None,
) -> ThreadSummary:
    """One row of an inbox.

    ``names`` lets a list endpoint resolve every correspondent at once;
    without it the row resolves its own.
    """
    other_id = thread.member_id if viewer_id == thread.creator_id else thread.creator_id
    if names is None:
        names = _display_names(db, [other_id])
    last_msg = thread.messages[-1] if thread.messages else None
    return ThreadSummary(
        thread_id=thread.id,
        other_user_id=other_id,
        other_user_name=names.get(other_id, NEUTRAL_DISPLAY_NAME),
        last_message=last_msg.body[:120] if last_msg else None,
        last_message_at=last_msg.created_at.isoformat() if last_msg else None,
        unread_count=_unread_count_for(db, thread.id, viewer_id),
    )


def _thread_summaries(
    threads: list[MessageThread], viewer_id: str, db: Session
) -> list[ThreadSummary]:
    """A whole inbox, with its correspondents resolved in one go."""
    names = _display_names(
        db,
        [t.member_id if viewer_id == t.creator_id else t.creator_id for t in threads],
    )
    return [_thread_summary(t, viewer_id, db, names) for t in threads]


# ---------------------------------------------------------------------------
# Creator endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# One member's delivery — the single unit of work
# ---------------------------------------------------------------------------

def _deliver_to_member(
    db: Session,
    *,
    space: Space,
    slug: str,
    sender: User,
    member_id: str,
    text: str,
    background_tasks: BackgroundTasks,
) -> MessageThread:
    """Put one message in one member's thread, and tell them about it.

    Extracted unchanged from ``creator_send_message`` so that sending to
    one member and sending to all of them are the *same* code, not two
    implementations that drift. The broadcast calls this in a loop; the
    individual send calls it once.

    Commits on its own. For a broadcast that makes each member a
    separate unit of work: one member failing leaves the others' messages
    in place, and nobody receives two copies because the caller never
    retries a member it has already committed.
    """
    thread = (
        db.query(MessageThread)
        .filter(
            MessageThread.space_id == space.id,
            MessageThread.creator_id == sender.id,
            MessageThread.member_id == member_id,
        )
        .first()
    )
    if thread is None:
        thread = MessageThread(
            id=str(uuid4()),
            space_id=space.id,
            creator_id=sender.id,
            member_id=member_id,
        )
        db.add(thread)
        db.flush()

    db.add(DirectMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sender_id=sender.id,
        body=text,
        is_read=False,
    ))
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(thread)

    # Notify the member. A BackgroundTask, so neither the individual
    # send nor a broadcast waits on email inside the request.
    sender_name = _one_display_name(db, sender)
    thread_url = f"/spaces/{slug}/messages/{thread.id}"
    background_tasks.add_task(
        _notify_direct_message,
        recipient_id=member_id,
        sender_name=sender_name,
        space_id=space.id,
        space_name=space.name,
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
        source_id=sender.id,
        actor_user_id=sender.id,
        subject_type="thread", subject_id=thread.id,
        context={"space_id": space.id},
        payload={
            "recipient_id": member_id,
            "sender_name": sender_name,
            "thread_id": thread.id,
            "excerpt": text[:80],
        },
    )
    db.commit()
    schedule_routing_if_needed(background_tasks, event, "dm.message.sent")
    return thread


def _active_member_ids(db: Session, space: Space, exclude_user_id: str) -> list[str]:
    """Everyone a Collective-wide message goes to.

    The same eligibility the Communications Layer's one-to-many resolver
    uses for ``community.post.published``: active membership, sender
    excluded. Evaluated when the message is sent and never again — a
    member who leaves afterwards keeps the thread they were given, and
    one who joins afterwards does not receive a message sent before they
    arrived.
    """
    rows = (
        db.query(SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.user_id != exclude_user_id,
        )
        .all()
    )
    # Dedupe defensively: one message per person, whatever the
    # membership table happens to hold.
    seen: set[str] = set()
    out: list[str] = []
    for (user_id,) in rows:
        if user_id and user_id not in seen:
            seen.add(user_id)
            out.append(user_id)
    return out


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
    return _thread_summaries(threads, current_user.id, db)


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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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

    thread = _deliver_to_member(
        db,
        space=space,
        slug=slug,
        sender=current_user,
        member_id=body.member_id,
        text=text,
        background_tasks=background_tasks,
    )
    return _thread_detail(thread, current_user.id, db)


@creator_router.get(
    "/spaces/{slug}/messages/broadcast/recipients",
    response_model=BroadcastRecipients,
)
def creator_broadcast_recipients(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BroadcastRecipients:
    """How many members a Collective-wide message would reach.

    Exists so the confirmation can name a real number rather than the
    interface guessing one from a page of members it happens to have
    loaded.
    """
    space = _get_managed_space(slug, current_user, db)
    return BroadcastRecipients(
        count=len(_active_member_ids(db, space, exclude_user_id=current_user.id)),
    )


@creator_router.post(
    "/spaces/{slug}/messages/broadcast",
    response_model=BroadcastResult,
    status_code=201,
)
def creator_broadcast_message(
    slug: str,
    body: BroadcastRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
) -> BroadcastResult:
    """Send one message to every active member, privately.

    Not an announcement: each member gets the message in their own
    one-to-one thread with the creator and can reply there. Nobody can
    see who else received it, because there is no shared object to see —
    a Collective-wide message is N ordinary direct messages, and after
    it is sent it is indistinguishable from N messages typed by hand.

    Authorisation is ``_get_managed_space`` (SEC-005-E), the same gate
    the individual send uses: Collective owner, or an active
    creator/moderator membership. A platform admin role grants nothing
    here.

    Each member is its own transaction. A failure part-way through
    leaves earlier members' messages in place and is reported rather
    than rolled back — and because the loop never revisits a member it
    has committed, nobody receives two copies.
    """
    space = _get_managed_space(slug, current_user, db)

    text = _sanitize(body.body)
    if not text:
        raise HTTPException(status_code=422, detail="Message body cannot be empty.")

    member_ids = _active_member_ids(db, space, exclude_user_id=current_user.id)
    if not member_ids:
        raise HTTPException(
            status_code=422,
            detail="This Collective has no other active members to message.",
        )

    failures: list[BroadcastFailure] = []
    sent = 0
    for member_id in member_ids:
        try:
            _deliver_to_member(
                db,
                space=space,
                slug=slug,
                sender=current_user,
                member_id=member_id,
                text=text,
                background_tasks=background_tasks,
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001 — one member must not end the send
            db.rollback()
            logger.exception(
                "broadcast: delivery failed for member %s in space %s",
                member_id, space.id,
            )
            failures.append(BroadcastFailure(
                member_id=member_id,
                # The creator is shown a count and a list; the detail
                # goes to the log, not into the response.
                reason=type(exc).__name__,
            ))

    return BroadcastResult(
        recipients=len(member_ids),
        sent=sent,
        failed=len(failures),
        failures=failures,
    )


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
    _get_message_member_space(slug, current_user, db)
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
    return _thread_summaries(threads, current_user.id, db)


@member_router.get("/{slug}/messages/{thread_id}", response_model=ThreadDetail)
def member_get_thread(
    slug: str,
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ThreadDetail:
    space = _get_message_member_space(slug, current_user, db)
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
) -> ThreadDetail:
    space = _get_message_member_space(slug, current_user, db)
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
    sender_name = _one_display_name(db, current_user)
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
    space = _get_message_member_space(slug, current_user, db)
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
    space_name: str | None = None,
) -> None:
    # M5c cutover guard — when dm.message.sent is live, the routing
    # pipeline handles delivery and this legacy notify no-ops.
    from app.comms.rollout import is_event_live
    if is_event_live("dm.message.sent"):
        return
    from app.services.notification_service import send_notification
    # In the app the member is already inside the Collective, so the
    # title needs no more than the sender. An inbox is not: a member of
    # several Collectives needs to know which one wrote. The subject
    # carries it, and the email repeats it under the heading.
    title = f"Message from {sender_name}"
    send_notification(
        recipient_id=recipient_id,
        notification_type="direct_message",
        title=title,
        message=preview if len(preview) < 80 else preview[:77] + "…",
        url=thread_url,
        space_id=space_id,
        pref_key="direct_message_email",
        email_subject=(
            f"New message from {sender_name} · {space_name}"
            if space_name else f"New message from {sender_name}"
        ),
        email_subheading=space_name,
    )
