"""Private conversations between two mutually-connected members.

Why not reuse ``MessageThread``
-------------------------------
``message_threads`` is ``(space_id NOT NULL, creator_id, member_id)`` and
every route hangs off ``/api/spaces/{slug}/messages``. It models one
specific relationship — a Collective's creator talking to one of its
members — and the creator inbox reads it on exactly that assumption.

Two members who said hello to each other are not that pair. Forcing
them through it would mean nulling ``space_id`` (changing the meaning of
every existing row and every query that joins on it), inventing a
Collective, or designating one member "the creator" — which would put
peer conversations in that person's Creator Studio inbox. So the
existing table is left exactly as it is, and peer threads get their own
two tables beside it.

Unordered pair, enforced by the database
----------------------------------------
There must be one conversation per pair, and A+B must be the same
conversation as B+A. Rather than check for both orderings in
application code — which leaves a race between the check and the insert
— the pair is *canonicalised*: the lower user id is always
``participant_a_user_id``. A CHECK constraint makes the ordering an
invariant of the row rather than a convention callers remember, and the
UNIQUE constraint on the ordered pair then means a single conversation
per pair with no ambiguity about which row to look for.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def canonical_pair(user_id_a: str, user_id_b: str) -> tuple[str, str]:
    """The two ids in the order a thread row stores them.

    Lexicographic, which is total and stable for the string ids this
    codebase uses throughout. Callers never choose the order, so A
    opening the conversation and B opening it resolve to the same row.
    """
    return (user_id_a, user_id_b) if user_id_a < user_id_b else (user_id_b, user_id_a)


class PeerThread(Base):
    """One private conversation between two members."""

    __tablename__ = "peer_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: Always the lexicographically lower of the two ids — see
    #: ``canonical_pair`` and the CHECK below.
    participant_a_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    participant_b_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    #: Sort key for the conversation list. Null until the first message,
    #: because a thread is created when somebody opens the conversation
    #: rather than when they send.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    messages: Mapped[list["PeerMessage"]] = relationship(
        "PeerMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="PeerMessage.created_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "participant_a_user_id", "participant_b_user_id",
            name="uq_peer_threads_pair",
        ),
        # The canonical ordering is an invariant of the row, not a
        # convention. With it, the UNIQUE above genuinely means "one
        # conversation per pair"; without it, A+B and B+A would both be
        # insertable and both unique.
        CheckConstraint(
            "participant_a_user_id < participant_b_user_id",
            name="ck_peer_threads_canonical_order",
        ),
        Index("ix_peer_threads_participant_a", "participant_a_user_id"),
        Index("ix_peer_threads_participant_b", "participant_b_user_id"),
    )

    def involves(self, user_id: str) -> bool:
        return user_id in (self.participant_a_user_id, self.participant_b_user_id)

    def other_participant(self, user_id: str) -> str:
        """The id of the person the given participant is talking to."""
        if user_id == self.participant_a_user_id:
            return self.participant_b_user_id
        if user_id == self.participant_b_user_id:
            return self.participant_a_user_id
        raise ValueError("That user is not a participant in this thread.")


class PeerMessage(Base):
    """One message in a peer conversation. Plain text."""

    __tablename__ = "peer_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("peer_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Always taken from the authenticated caller, never from a request
    #: body — see the send route.
    sender_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Read state belongs to the *recipient*: a message is unread until
    #: the other participant opens the thread. Mirrors the column pair
    #: the creator↔member threads already use, so the two surfaces
    #: behave the same way.
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    thread: Mapped["PeerThread"] = relationship(
        "PeerThread", back_populates="messages",
    )

    __table_args__ = (
        # Unread counts are per thread, per reader.
        Index("ix_peer_messages_thread_created", "thread_id", "created_at"),
    )
