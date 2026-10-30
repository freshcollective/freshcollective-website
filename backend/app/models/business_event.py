"""The append-only record of what happened to the business.

Separate from ``activities`` on purpose. That table is a member's
notification feed — it carries read, emailed and archived state, and its
rows exist to be shown to somebody. These rows exist to be counted, are
never displayed to a member, and must outlive any inbox.

Nothing reads this table in BI-1. It is written by
``app.services.business_events`` and read by the metric registry in a
later release; recording starts now because the facts it holds are
destroyed as they happen, and every day without it is a day of history
that cannot be recovered.

See ``alembic/versions/171_business_events.py`` for the reasoning behind
the column set, the SET NULL user references and the settlement
provenance columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusinessEvent(Base):
    __tablename__ = "business_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    #: A value from ``BusinessEventType``. Never a free string — the
    #: producer rejects anything the registry does not declare.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    #: When the thing happened, naive UTC. Taken from the business fact,
    #: not the clock at write time, so a Stripe event delivered an hour
    #: late still lands in the hour it occurred.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
    )
    #: When this row was written. The gap between the two is how a late
    #: arrival is detected, and the minimum of this column across the
    #: table is the activation boundary that separates history predating
    #: BI-1 from a genuinely missing event.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String, nullable=False)

    #: Who caused it, where that is meaningful. Null for anything the
    #: system did on its own — a grace period expiring, a cron sweep.
    actor_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    #: Who it happened to. Denormalised so aggregation never needs a join.
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    #: The Collective it belongs to. Present on every event that has one,
    #: because this is what scopes a creator's own reporting.
    space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True,
    )
    #: The creator it is attributable to, for the same reason.
    creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    #: Identifiers, amounts and enum values only. Never free text and
    #: never member-authored content — ``business_events`` is checked
    #: against a per-event-type schema before anything is written.
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )

    #: Unique. The entire idempotency mechanism: a webhook retry, a
    #: re-run or two concurrent writers yield one row.
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)

    #: Monotonic, from a database sequence. Stable ordering, and the
    #: cursor a later incremental aggregation reads from.
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ux_business_events_dedupe", "dedupe_key", unique=True),
        Index("ix_business_events_occurred", "occurred_at"),
        Index("ix_business_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_business_events_space_occurred", "space_id", "occurred_at"),
        Index("ix_business_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_business_events_creator_occurred", "creator_user_id", "occurred_at"),
        Index("ix_business_events_subject", "subject_type", "subject_id"),
        CheckConstraint(
            "subject_type IN ('membership', 'subscription', 'collective', 'transaction')",
            name="ck_business_events_subject_type",
        ),
    )
