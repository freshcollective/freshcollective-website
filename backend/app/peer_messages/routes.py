"""Member-to-member conversation API.

Separate from ``app/messages/routes.py``, which is the creator↔member
surface and stays exactly as it is. These routes live under
``/api/messages`` with no Collective in the path, because a peer
conversation does not belong to one.

Every refusal that is about *who* the other party is — not connected,
not a participant, no such thread, no such member — is the same 404.
A distinct 403 would answer the question the 404 exists to refuse, and
would let the endpoints be used to discover who is connected to whom.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.peer_messages import PeerThread
from app.models.platform import CreatorProfile
from app.models.user import User
from app.community_care.peer_reports import REPORT_CATEGORIES, submit_peer_report
from app.peer_messages import service
from app.services import member_block_service
from app.services.member_identity import optional_display_name
from app.services.member_image import (
    MemberCardArtwork,
    MemberImagePayload,
)

router = APIRouter(prefix="/api/messages", tags=["peer-messages"])


# ---------------------------------------------------------------------------
# Wire shapes — the minimum a conversation needs
# ---------------------------------------------------------------------------


class PeerParticipant(BaseModel):
    """The other person, as a conversation needs to show them.

    Name and picture only. No email, no contact details, no profile
    metadata, and nothing about what the two of them share — the
    Recognition evidence belongs to Ways to Connect, not here.
    """
    id: str
    display_name: str | None = None
    image: MemberImagePayload


class PeerMessageOut(BaseModel):
    id: str
    sender_user_id: str
    body: str
    created_at: datetime
    #: Whether the *recipient* has read it. Shown to nobody in v1; the
    #: client uses it only to count what is waiting for the viewer.
    is_read: bool


class PeerThreadSummary(BaseModel):
    thread_id: str
    other: PeerParticipant
    last_message: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0


class PeerThreadDetail(BaseModel):
    thread_id: str
    other: PeerParticipant
    messages: list[PeerMessageOut]
    #: True when *the caller* has blocked the other person. One-sided on
    #: purpose: somebody who has been blocked is never told, so this is
    #: False for them and the composer is simply unavailable.
    blocked_by_me: bool = False
    #: Whether a message may be sent right now. False while a block
    #: stands in either direction — so the person who was blocked sees a
    #: closed composer without being told why, and without being told by
    #: whom.
    can_send: bool = True


class SendPeerMessageRequest(BaseModel):
    #: The sender is never in the body — it comes from the session.
    body: str = Field(min_length=1)


class OpenThreadRequest(BaseModel):
    """Who to open a conversation with."""
    user_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No such conversation.",
    )


def _participants(
    db: Session, user_ids: set[str], artwork: MemberCardArtwork,
) -> dict[str, PeerParticipant]:
    """Name and picture for each id, through the shared resolver.

    ``MemberImagePayload.resolve`` is the same path Ways to Connect and
    the member directory use, so one person cannot appear with a photo
    on one surface and a different fallback on another.
    """
    if not user_ids:
        return {}
    rows = (
        db.query(User, CreatorProfile)
        .outerjoin(CreatorProfile, CreatorProfile.user_id == User.id)
        .filter(User.id.in_(user_ids))
        .all()
    )
    out: dict[str, PeerParticipant] = {}
    for user, profile in rows:
        name = optional_display_name(user, profile)
        out[user.id] = PeerParticipant(
            id=user.id,
            display_name=name,
            image=MemberImagePayload.resolve(
                display_name=name, profile=profile, artwork=artwork,
            ),
        )
    return out


def _summary(
    thread: PeerThread,
    viewer_id: str,
    other: PeerParticipant,
    last_body: str | None,
    unread: int,
) -> PeerThreadSummary:
    return PeerThreadSummary(
        thread_id=thread.id,
        other=other,
        last_message=last_body,
        last_message_at=thread.last_message_at,
        unread_count=unread,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PeerThreadSummary])
def list_my_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PeerThreadSummary]:
    """The signed-in member's conversations.

    The subject is always the caller — there is no parameter naming a
    member, so reading somebody else's conversation list has no request
    shape to express.
    """
    threads = service.list_threads(db, current_user.id)
    if not threads:
        return []

    unread = service.unread_counts(db, current_user.id)
    artwork = MemberCardArtwork.load(db)
    others = {t.other_participant(current_user.id) for t in threads}
    people = _participants(db, others, artwork)

    out: list[PeerThreadSummary] = []
    for thread in threads:
        other_id = thread.other_participant(current_user.id)
        person = people.get(other_id)
        if person is None:
            # Account gone; nothing to show a conversation with.
            continue
        messages = service.messages_for(db, thread)
        out.append(_summary(
            thread, current_user.id, person,
            messages[-1].body if messages else None,
            unread.get(thread.id, 0),
        ))
    return out


@router.post("/open", response_model=PeerThreadDetail, status_code=200)
def open_thread(
    body: OpenThreadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PeerThreadDetail:
    """Open the conversation with a mutually-connected member.

    Get-or-create, so pressing Message twice — or both people pressing
    it at the same moment — yields the one conversation rather than a
    duplicate or an error. Opening does not send anything.

    404 unless both hello rows exist. Same status for a nonexistent
    member id, so this cannot be used to discover who exists.
    """
    try:
        thread = service.get_or_create_thread(db, current_user.id, body.user_id)
    except (service.NotConnected, service.Blocked):
        # Same 404 for both: a distinct status would tell the blocked
        # person that they have been blocked, which is exactly what the
        # product must not disclose.
        raise _not_found() from None

    db.commit()
    db.refresh(thread)
    return _detail(db, thread, current_user.id)


@router.get("/{thread_id}", response_model=PeerThreadDetail)
def get_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PeerThreadDetail:
    """One conversation, with its messages. Marks the other person's
    messages as read, because opening it is reading it."""
    try:
        thread = service.thread_for_participant(db, thread_id, current_user.id)
    except service.NotAParticipant:
        raise _not_found() from None

    service.mark_read(db, thread, current_user.id)
    db.commit()
    return _detail(db, thread, current_user.id)


@router.post("/{thread_id}/messages", response_model=PeerMessageOut, status_code=201)
def send_peer_message(
    thread_id: str,
    body: SendPeerMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PeerMessageOut:
    """Send a message. The sender is the authenticated caller."""
    try:
        thread = service.thread_for_participant(db, thread_id, current_user.id)
        message = service.send_message(
            db, thread, current_user.id, body.body,
        )
    except (service.NotAParticipant, service.NotConnected, service.Blocked):
        # Indistinguishable by design — see ``open_thread``.
        raise _not_found() from None
    except service.EmptyMessage as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from None
    except service.MessageTooLong as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from None

    recipient_id = thread.other_participant(current_user.id)
    sender_name = _first_name(
        optional_display_name(
            current_user,
            db.query(CreatorProfile)
            .filter(CreatorProfile.user_id == current_user.id)
            .first(),
        )
    )
    db.commit()
    db.refresh(message)

    # After the commit, and only for a message that genuinely persisted:
    # a failed send raises above and never reaches here, so there is no
    # notification without a message. ``send_notification`` opens its own
    # session — the established pattern for the creator↔member threads.
    #
    # No ``space_id``/``pref_key``: a peer conversation has no
    # Collective, and v1 is in-app only rather than email.
    background_tasks.add_task(
        _notify_peer_message,
        recipient_id=recipient_id,
        sender_name=sender_name,
        thread_id=thread.id,
    )
    return PeerMessageOut(
        id=message.id,
        sender_user_id=message.sender_user_id,
        body=message.body,
        created_at=message.created_at,
        is_read=message.is_read,
    )


def _first_name(name: str | None) -> str:
    if not name:
        return "Someone"
    return name.strip().split()[0] or "Someone"


def _notify_peer_message(
    *, recipient_id: str, sender_name: str, thread_id: str,
) -> None:
    """In-app only, and no message body.

    The creator↔member notification carries an 80-character preview.
    This one deliberately does not: that surface is a Collective's
    creator reading their own inbox, whereas a peer conversation is
    private between two people, and a notification is the one place its
    content could surface outside the thread.
    """
    from app.services.notification_service import send_notification

    send_notification(
        recipient_id=recipient_id,
        notification_type="peer_message",
        title=f"{sender_name} sent you a message",
        message="Open your messages to read it.",
        url=f"/messages/{thread_id}",
    )


def _detail(db: Session, thread: PeerThread, viewer_id: str) -> PeerThreadDetail:
    artwork = MemberCardArtwork.load(db)
    other_id = thread.other_participant(viewer_id)
    person = _participants(db, {other_id}, artwork).get(other_id)
    if person is None:
        raise _not_found()
    return PeerThreadDetail(
        thread_id=thread.id,
        other=person,
        blocked_by_me=member_block_service.has_blocked(db, viewer_id, other_id),
        can_send=service.may_interact(db, viewer_id, other_id),
        messages=[
            PeerMessageOut(
                id=m.id,
                sender_user_id=m.sender_user_id,
                body=m.body,
                created_at=m.created_at,
                is_read=m.is_read,
            )
            for m in service.messages_for(db, thread)
        ],
    )

# ---------------------------------------------------------------------------
# Safety — block, unblock, report
# ---------------------------------------------------------------------------


class BlockStateOut(BaseModel):
    """Whether the *caller* has blocked the other person.

    Deliberately one-sided. A member who has been blocked is never told
    so: they see a conversation they cannot send into, not a notice
    naming the person who closed it. Telling them would turn a boundary
    into a confrontation, and it is not information they need.
    """
    blocked_by_me: bool


class ReportPeerRequest(BaseModel):
    category: str
    reporter_note: str | None = None
    #: Optional. Must belong to this thread — checked server-side.
    message_id: str | None = None


class ReportPeerResult(BaseModel):
    case_number: str


@router.post("/{thread_id}/block", response_model=BlockStateOut)
def block_peer(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlockStateOut:
    """Block the other participant in this conversation.

    Reached from inside a conversation rather than from an arbitrary
    user id, so a block is always something a member does to someone
    they are actually talking to.

    Idempotent. No notification of any kind: the blocked person is not
    told, which is the whole point.
    """
    try:
        thread = service.thread_for_participant(db, thread_id, current_user.id)
    except service.NotAParticipant:
        raise _not_found() from None

    other_id = thread.other_participant(current_user.id)
    member_block_service.block(db, current_user.id, other_id)
    db.commit()
    return BlockStateOut(blocked_by_me=True)


@router.delete("/{thread_id}/block", response_model=BlockStateOut)
def unblock_peer(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlockStateOut:
    """Remove the block the caller set.

    Only ever clears the caller's own row. If the other person has also
    blocked them, the pair stays blocked — asymmetric state resolves
    only when both sides have cleared, and this endpoint has no way to
    reach somebody else's boundary.

    Messaging resumes only when no block remains in either direction
    *and* the mutual hello still stands; nobody has to say hello again,
    because the hello rows were never removed.
    """
    try:
        thread = service.thread_for_participant(db, thread_id, current_user.id)
    except service.NotAParticipant:
        raise _not_found() from None

    other_id = thread.other_participant(current_user.id)
    member_block_service.unblock(db, current_user.id, other_id)
    db.commit()
    return BlockStateOut(blocked_by_me=False)


@router.post("/{thread_id}/report", response_model=ReportPeerResult, status_code=201)
def report_peer(
    thread_id: str,
    body: ReportPeerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportPeerResult:
    """Report the other participant to Fresh Collective.

    Routes into the existing Community Care framework rather than a
    second reporting system, and needs no schema change to do it:
    ``member_behaviour`` is already a permitted case ``content_type``,
    ``subject_space_id`` is already nullable, and ``content_snapshot``
    already exists to hold "a point-in-time copy of the reported
    content... kept for review and audit even if the source is later
    edited or removed". The conversation reference and the messages go
    there.

    Reporting does not block. The two are offered together in the UI
    but are independent actions, so a member can report without
    withdrawing and withdraw without reporting.

    The reported person is not notified.
    """
    try:
        thread = service.thread_for_participant(db, thread_id, current_user.id)
    except service.NotAParticipant:
        raise _not_found() from None

    if body.category not in REPORT_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown report category.",
        )
    note = (body.reporter_note or "").strip() or None
    if body.category == "something_else" and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please tell us what happened.",
        )

    other_id = thread.other_participant(current_user.id)

    # An optional message reference must belong to this conversation —
    # otherwise the field would let a participant attach somebody
    # else's message to their report.
    messages = service.messages_for(db, thread)
    if body.message_id is not None and body.message_id not in {
        m.id for m in messages
    }:
        raise _not_found()

    case_number = submit_peer_report(
        db,
        reporter_user_id=current_user.id,
        reported_user_id=other_id,
        thread_id=thread.id,
        category=body.category,
        reporter_note=note,
        message_id=body.message_id,
        messages=messages,
    )
    db.commit()
    return ReportPeerResult(case_number=case_number)
