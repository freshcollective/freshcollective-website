"""One member has blocked another.

Directed, and deliberately separate from ``member_hellos``. A hello and
a block are different kinds of fact: one is an invitation, the other is
a boundary, and overloading the hello row with block state would mean
the thing that records consent is also the thing that records its
withdrawal. Keeping them apart is also what lets block *outrank* mutual
connection without either having to know about the other — the hello
rows stay exactly as they were, and authorisation simply asks both
questions.

Directed because the two directions mean different things and must be
independently reversible: if A blocks B and B also blocks A, A
unblocking must not restore messaging while B's block stands. Two rows
express that; one shared row would need a state machine to say which
side may clear it.

Append-and-delete rather than a status column: unblocking removes the
row, so "is there an active block" is a question about existence. There
is no "inactive block" state to accidentally treat as active.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MemberBlock(Base):
    __tablename__ = "member_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: Who set the boundary. Only this person may remove it.
    blocker_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    blocked_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        # Makes a repeated block a no-op at the database, so the action
        # is idempotent under retries and double clicks without the
        # service having to read first.
        UniqueConstraint(
            "blocker_user_id", "blocked_user_id", name="uq_member_blocks_pair",
        ),
        CheckConstraint(
            "blocker_user_id <> blocked_user_id",
            name="ck_member_blocks_not_self",
        ),
        # Both directions are asked on every authorisation check: "have
        # I blocked them" and "have they blocked me".
        Index("ix_member_blocks_blocker", "blocker_user_id"),
        Index("ix_member_blocks_blocked", "blocked_user_id"),
    )
