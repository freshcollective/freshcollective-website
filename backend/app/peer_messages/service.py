"""Peer conversations: authorisation, get-or-create, send, read.

Authorisation is the persisted mutual hello — deliberately not current
Ways to Connect eligibility. Eligibility governs *discovery* and the
first hello; once two people have both said hello, the connection they
made is theirs. Recomputing eligibility here would close a conversation
because a Gathering passed or a Pathway changed state, which is the one
thing 5b's persistence rule exists to prevent.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.connections import MemberHello
from app.models.peer_messages import PeerMessage, PeerThread, canonical_pair

logger = logging.getLogger(__name__)

#: Plain text only, matching the creator↔member threads: tags are
#: stripped rather than escaped, so nothing downstream has to decide
#: whether a body is markup. Reused verbatim rather than imported from
#: ``app.messages.routes`` to avoid a service depending on a route
#: module; the behaviour is asserted identical in the tests.
_HTML_RE = re.compile(r"<[^>]+>")

#: A conversation message, not an essay. The creator↔member threads have
#: no explicit cap (``body`` is TEXT and only emptiness is checked),
#: which is a gap rather than a precedent worth copying: an uncapped
#: field reachable by any connected member is an abuse surface. Chosen
#: generously enough that no genuine message hits it.
MAX_BODY_CHARS = 4000


class NotConnected(Exception):
    """The two members are not mutually connected."""


class NotAParticipant(Exception):
    """The caller is not in this thread."""


class EmptyMessage(Exception):
    """Nothing but whitespace or markup."""


class MessageTooLong(Exception):
    """Over ``MAX_BODY_CHARS``."""


def sanitize_body(text: str) -> str:
    """Strip tags and surrounding whitespace. Plain text only."""
    return _HTML_RE.sub("", text).strip()


def are_mutually_connected(db: Session, user_a: str, user_b: str) -> bool:
    """Do both directional hello rows exist?

    Two rows, counted in one query. A one-sided hello — in either
    direction — is not a connection and grants nothing.
    """
    if user_a == user_b:
        return False
    count = (
        db.query(func.count(MemberHello.id))
        .filter(
            or_(
                (MemberHello.from_user_id == user_a)
                & (MemberHello.to_user_id == user_b),
                (MemberHello.from_user_id == user_b)
                & (MemberHello.to_user_id == user_a),
            )
        )
        .scalar()
    )
    return count == 2


def get_or_create_thread(db: Session, user_a: str, user_b: str) -> PeerThread:
    """The single conversation for this pair, creating it if needed.

    Raises :class:`NotConnected` unless both hello rows exist — the only
    thing that authorises a peer conversation to exist at all.

    Lazy: a mutual hello does not create a thread, so people who never
    message never accumulate empty conversations. The first person to
    open it creates it.

    Race-safe without a read-then-write: the pair is canonicalised, so
    both participants resolve to the same row, and the insert is
    conflict-tolerant. If both press Message at the same moment one
    insert wins and the other reads the winner's row — there is no
    window in which two threads can exist, because the database will not
    allow a second.
    """
    if user_a == user_b:
        # Redundant against the check below — ``are_mutually_connected``
        # returns False for an identical pair, and a self-hello is
        # impossible anyway (``ck_member_hellos_not_self``). Kept
        # because "nobody messages themselves" should be readable here
        # rather than inferred from two other places. Mutation-testing
        # note: deleting this line alone does not fail the suite, for
        # exactly that reason.
        raise NotConnected("A member cannot hold a conversation with themselves.")
    if not are_mutually_connected(db, user_a, user_b):
        raise NotConnected("These members are not mutually connected.")

    low, high = canonical_pair(user_a, user_b)
    db.execute(
        pg_insert(PeerThread.__table__)
        .values(
            id=str(uuid4()),
            participant_a_user_id=low,
            participant_b_user_id=high,
        )
        .on_conflict_do_nothing(constraint="uq_peer_threads_pair")
    )
    thread = (
        db.query(PeerThread)
        .filter(
            PeerThread.participant_a_user_id == low,
            PeerThread.participant_b_user_id == high,
        )
        .one()
    )
    return thread


def thread_for_participant(
    db: Session, thread_id: str, viewer_id: str,
) -> PeerThread:
    """Load a thread the viewer is actually in.

    Raises :class:`NotAParticipant` both when the thread does not exist
    and when it exists but belongs to other people. The caller turns
    both into the same 404, so thread ids are not probeable and the
    error does not disclose that a conversation exists.
    """
    thread = db.query(PeerThread).filter(PeerThread.id == thread_id).first()
    if thread is None or not thread.involves(viewer_id):
        raise NotAParticipant("No such conversation.")
    return thread


def list_threads(db: Session, viewer_id: str) -> list[PeerThread]:
    """The viewer's conversations, most recently active first.

    Threads with no messages yet sort last rather than being hidden:
    somebody who opened a conversation and did not type should still
    find it where they left it.
    """
    return (
        db.query(PeerThread)
        .filter(
            or_(
                PeerThread.participant_a_user_id == viewer_id,
                PeerThread.participant_b_user_id == viewer_id,
            )
        )
        .order_by(
            PeerThread.last_message_at.is_(None),
            PeerThread.last_message_at.desc(),
            PeerThread.created_at.desc(),
        )
        .all()
    )


def send_message(
    db: Session, thread: PeerThread, sender_id: str, raw_body: str,
) -> PeerMessage:
    """Append a message. The sender must be a participant.

    ``sender_id`` comes from the authenticated caller; there is no path
    by which a request body can name a sender. Re-checks mutual
    connection as well as participation, so revoking a connection (if
    that is ever added) closes sending without needing to find and
    delete threads.
    """
    if not thread.involves(sender_id):
        raise NotAParticipant("No such conversation.")
    other = thread.other_participant(sender_id)
    if not are_mutually_connected(db, sender_id, other):
        raise NotConnected("These members are not mutually connected.")

    body = sanitize_body(raw_body)
    if not body:
        raise EmptyMessage("Message body cannot be empty.")
    if len(body) > MAX_BODY_CHARS:
        raise MessageTooLong(
            f"Message is too long (limit {MAX_BODY_CHARS} characters)."
        )

    now = datetime.utcnow()
    message = PeerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sender_user_id=sender_id,
        body=body,
        is_read=False,
        # Set here rather than left to the column's ``now()`` default:
        # in Postgres ``now()`` is the *transaction* start time, so two
        # messages written in one transaction share a timestamp and the
        # conversation falls back to ordering by a random uuid. Taking
        # the clock at insert time keeps the thread in the order it was
        # actually typed.
        created_at=now,
    )
    db.add(message)
    thread.last_message_at = now
    db.flush()
    return message


def mark_read(db: Session, thread: PeerThread, viewer_id: str) -> int:
    """Mark the other person's messages in this thread as read.

    Only messages *sent to* the viewer. A sender never marks their own
    message read, which is what keeps their own unread count honest.
    Returns how many rows changed, so a repeat call reports zero rather
    than pretending to work.
    """
    if not thread.involves(viewer_id):
        raise NotAParticipant("No such conversation.")
    now = datetime.utcnow()
    return (
        db.query(PeerMessage)
        .filter(
            PeerMessage.thread_id == thread.id,
            PeerMessage.sender_user_id != viewer_id,
            PeerMessage.is_read.is_(False),
        )
        .update({"is_read": True, "read_at": now}, synchronize_session=False)
    )


def unread_counts(db: Session, viewer_id: str) -> dict[str, int]:
    """Unread messages per thread for this viewer, in one query."""
    rows = (
        db.query(PeerMessage.thread_id, func.count(PeerMessage.id))
        .join(PeerThread, PeerThread.id == PeerMessage.thread_id)
        .filter(
            or_(
                PeerThread.participant_a_user_id == viewer_id,
                PeerThread.participant_b_user_id == viewer_id,
            ),
            PeerMessage.sender_user_id != viewer_id,
            PeerMessage.is_read.is_(False),
        )
        .group_by(PeerMessage.thread_id)
        .all()
    )
    return {thread_id: count for thread_id, count in rows}


def messages_for(db: Session, thread: PeerThread) -> list[PeerMessage]:
    """Every message in the thread, oldest first.

    No pagination in v1. A pair conversation is small, and the
    creator↔member threads load whole as well — adding a cursor here
    would be the only paginated message surface in the product.
    """
    return (
        db.query(PeerMessage)
        .filter(PeerMessage.thread_id == thread.id)
        .order_by(PeerMessage.created_at, PeerMessage.id)
        .all()
    )
