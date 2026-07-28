"""
ActivityService — the single writer for the Fresh Collective Activity
Engine.

Feature code MUST NOT insert into the ``activities`` table directly.
Every future feature that used to send email or write notifications
calls ``ActivityService.create(...)`` (or ``.create_for_recipients``
for fan-out) and lets delivery channels — Notification Centre,
Creator Dashboard feed, future email digest / push / My World — read
from the engine.

Concentrating writes here gives us:

* one place to validate event_type + category
* one place to apply default priority (still overridable per call)
* one place to instrument metrics, hook up publishers, etc.

The service intentionally does no delivery of its own. Callers pass in
a live SQLAlchemy Session; commit semantics stay with the caller so
activity writes participate in the caller's own transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.activity import (
    Activity,
    ActivityCategory,
    ActivityPriority,
    ActivityType,
    CATEGORY_OF,
    DEFAULT_PRIORITY_OF,
    RECENT_MOMENTS,
)


class ActivityService:
    """Namespace-style helper (class-with-staticmethods) so callers read
    naturally: ``ActivityService.create(db, ...)``. Keeps the writer
    grep-able across the codebase."""

    # -----------------------------------------------------------------
    # Writers
    # -----------------------------------------------------------------

    @staticmethod
    def create(
        db: Session,
        *,
        event_type: ActivityType,
        recipient_user_id: str,
        actor_user_id: str | None = None,
        collective_id: str | None = None,
        pathway_id: str | None = None,
        gathering_id: str | None = None,
        conversation_id: str | None = None,
        resource_id: str | None = None,
        payload: dict | None = None,
        priority: ActivityPriority | None = None,
    ) -> Activity:
        """Create one activity row for one recipient.

        The category is derived from the event_type. Priority defaults
        to the event's canonical priority but may be overridden per
        call (e.g. a normally-standard event promoted to important for
        a Community Care escalation).

        Returns the new Activity. The caller is responsible for
        ``db.commit()`` — this lets the write participate in a broader
        transaction (e.g. "create post + notify replier" as one atomic
        unit).
        """
        if not isinstance(event_type, ActivityType):
            raise TypeError(
                f"event_type must be an ActivityType, got {type(event_type).__name__}"
            )

        category = CATEGORY_OF[event_type]
        resolved_priority = priority or DEFAULT_PRIORITY_OF[event_type]

        activity = Activity(
            id=f"act_{uuid.uuid4().hex[:20]}",
            event_type=event_type.value,
            category=category.value,
            priority=resolved_priority.value,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            collective_id=collective_id,
            pathway_id=pathway_id,
            gathering_id=gathering_id,
            conversation_id=conversation_id,
            resource_id=resource_id,
            payload=payload or {},
        )
        db.add(activity)
        db.flush()
        return activity

    @staticmethod
    def create_for_recipients(
        db: Session,
        *,
        event_type: ActivityType,
        recipient_user_ids: Iterable[str],
        actor_user_id: str | None = None,
        collective_id: str | None = None,
        pathway_id: str | None = None,
        gathering_id: str | None = None,
        conversation_id: str | None = None,
        resource_id: str | None = None,
        payload: dict | None = None,
        priority: ActivityPriority | None = None,
    ) -> list[Activity]:
        """Fan-out helper: create one row per recipient for a single
        feature-side event (e.g. "new pathway published" → an activity
        for every member of the collective).

        Deduplicates recipient ids in-place. Skips a self-notify if
        the actor happens to be in the recipient list — features
        typically don't want to notify a user about their own action.
        """
        seen: set[str] = set()
        rows: list[Activity] = []
        for rid in recipient_user_ids:
            if not rid or rid in seen:
                continue
            if actor_user_id and rid == actor_user_id:
                continue
            seen.add(rid)
            rows.append(
                ActivityService.create(
                    db,
                    event_type=event_type,
                    recipient_user_id=rid,
                    actor_user_id=actor_user_id,
                    collective_id=collective_id,
                    pathway_id=pathway_id,
                    gathering_id=gathering_id,
                    conversation_id=conversation_id,
                    resource_id=resource_id,
                    payload=payload,
                    priority=priority,
                )
            )
        return rows

    # -----------------------------------------------------------------
    # Read helpers — the same primitives the API routes use, exposed on
    # the service so background workers (digest builder, "My World"
    # history compiler, automation engine) can reuse them.
    # -----------------------------------------------------------------

    @staticmethod
    def list_for_recipient(
        db: Session,
        *,
        recipient_user_id: str,
        unread_only: bool = False,
        include_archived: bool = False,
        limit: int = 20,
        before: datetime | None = None,
        collective_id: str | None = None,
        recent_moments_only: bool = False,
    ) -> list[Activity]:
        """Newest-first page of activities for a user.

        ``before`` is a cursor: pass the ``created_at`` of the last
        item on the previous page to load the next page.

        ``collective_id`` optionally scopes the result to a single
        collective. Recipient scope is unchanged — the caller only
        ever sees their own activities; the filter is additive.

        ``recent_moments_only`` narrows the result to the curated
        Recent Moments whitelist (see ``RECENT_MOMENTS`` in
        ``app.models.activity``). Attention-required and history-only
        event types are excluded. Every writer is free to record any
        event type; this flag decides which ones bubble up to the
        Recent Moments surfaces.
        """
        q = db.query(Activity).filter(Activity.recipient_user_id == recipient_user_id)
        if collective_id is not None:
            q = q.filter(Activity.collective_id == collective_id)
        if recent_moments_only:
            q = q.filter(Activity.event_type.in_([t.value for t in RECENT_MOMENTS]))
        if unread_only:
            q = q.filter(Activity.read_at.is_(None))
        if not include_archived:
            q = q.filter(Activity.archived_at.is_(None))
        if before is not None:
            q = q.filter(Activity.created_at < before)
        return q.order_by(Activity.created_at.desc()).limit(limit).all()

    @staticmethod
    def unread_count(db: Session, *, recipient_user_id: str) -> int:
        """Count of unread, non-archived activities for the bell."""
        return (
            db.query(func.count(Activity.id))
            .filter(
                Activity.recipient_user_id == recipient_user_id,
                Activity.read_at.is_(None),
                Activity.archived_at.is_(None),
            )
            .scalar()
            or 0
        )

    @staticmethod
    def mark_read(
        db: Session,
        *,
        activity_id: str,
        recipient_user_id: str,
    ) -> Activity | None:
        """Mark a single activity as read. Returns the row or None if
        it doesn't belong to the caller (never leaks the existence of
        someone else's activity)."""
        row = (
            db.query(Activity)
            .filter(
                Activity.id == activity_id,
                Activity.recipient_user_id == recipient_user_id,
            )
            .one_or_none()
        )
        if row is None:
            return None
        if row.read_at is None:
            row.read_at = datetime.utcnow()
            db.flush()
        return row

    @staticmethod
    def mark_all_read(db: Session, *, recipient_user_id: str) -> int:
        """Mark every unread activity for the recipient as read.
        Returns the number updated."""
        now = datetime.utcnow()
        n = (
            db.query(Activity)
            .filter(
                Activity.recipient_user_id == recipient_user_id,
                Activity.read_at.is_(None),
            )
            .update({Activity.read_at: now}, synchronize_session=False)
        )
        db.flush()
        return int(n)

    @staticmethod
    def list_for_collective(
        db: Session,
        *,
        collective_id: str,
        categories: Sequence[ActivityCategory] | None = None,
        limit: int = 30,
        before: datetime | None = None,
    ) -> list[Activity]:
        """Newest-first page of activities scoped to a collective.

        The Creator Dashboard feed calls this to surface "Emily joined
        EMBODY", "Sarah completed Week 4", "Replay uploaded", "New
        discussion started" without going through the per-recipient
        table. Rows here may belong to many recipients; the caller
        deduplicates for display if needed.
        """
        conditions = [Activity.collective_id == collective_id]
        if categories:
            conditions.append(Activity.category.in_([c.value for c in categories]))
        if before is not None:
            conditions.append(Activity.created_at < before)
        return (
            db.query(Activity)
            .filter(and_(*conditions))
            .order_by(Activity.created_at.desc())
            .limit(limit)
            .all()
        )
