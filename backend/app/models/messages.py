"""
SQLAlchemy models for direct messaging (creator ↔ member threads).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MessageThread(Base):
    """
    One conversation between a creator/admin and a member within a space.
    Unique per (space, creator, member) trio — re-opening the same conversation
    always returns the existing thread.
    """
    __tablename__ = "message_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    creator_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list["DirectMessage"]] = relationship(
        "DirectMessage", back_populates="thread", order_by="DirectMessage.created_at"
    )

    __table_args__ = (
        UniqueConstraint("space_id", "creator_id", "member_id", name="uq_thread_space_creator_member"),
    )


class DirectMessage(Base):
    """A single message within a MessageThread."""
    __tablename__ = "direct_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String, ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )

    thread: Mapped["MessageThread"] = relationship("MessageThread", back_populates="messages")

    __table_args__ = (
        Index("ix_direct_messages_thread_created", "thread_id", "created_at"),
    )
