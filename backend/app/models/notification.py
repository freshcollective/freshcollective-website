"""
SQLAlchemy model for the notifications table.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # comment_reply, new_post, event_reminder, new_pathway, admin_broadcast,
    # new_member, event_registration, pathway_completed
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Severity — added with Community Care Stage 2A. CHECK constraint on
    # the DB side allows: 'routine' | 'action' | 'urgent'.
    #   routine: guidance, reminders, support ack, ordinary CC updates.
    #   action:  warnings, content hidden, restrictions, freezes, outcomes.
    #   urgent:  suspension pending review, account/creator cancellation.
    # Default 'routine' preserves the behaviour of every existing caller
    # that did not set a severity value.
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="routine", server_default="routine",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        Index("ix_notifications_user_is_read", "user_id", "is_read"),
        Index("ix_notifications_user_created_at", "user_id", "created_at"),
    )
