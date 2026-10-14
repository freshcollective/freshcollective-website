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

import logging
import uuid
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
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

logger = logging.getLogger(__name__)

#: The three categories a member-facing Collective feed may show.
#: ``personal`` and ``account`` are the bell's business; ``collective``
#: (member joins) is creator-facing only.
SHARED_MEMBER_CATEGORIES = ("conversations", "pathways", "gatherings")

#: Postgres ``unique_violation``. The dedupe index is the only
#: constraint whose breach means "already recorded"; see below.
_UNIQUE_VIOLATION = "23505"

#: The partial unique index created by migration 155.
_DEDUPE_INDEX = "ux_activities_dedupe"


def _is_dedupe_conflict(exc: IntegrityError) -> bool:
    """True only when this row lost a race to an identical one.

    Narrow on purpose. ``IntegrityError`` also covers a foreign key
    that does not resolve and a NOT NULL that is violated — both mean
    the row was *wrong*, not repeated. Treating those as an idempotent
    no-op loses a real bug twice over: the activity never appears, and
    the log line says it was already there, which is the one message
    guaranteed to stop anybody looking.
    """
    orig = getattr(exc, "orig", None)
    if getattr(orig, "pgcode", None) != _UNIQUE_VIOLATION:
        return False
    # A unique violation on some *other* index is still not a repeat of
    # this content, so the constraint has to be named. When the driver
    # declines to name it, fall back to the text.
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if constraint:
        return constraint == _DEDUPE_INDEX
    return _DEDUPE_INDEX in str(orig)


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
    def create_shared(
        db: Session,
        *,
        event_type: ActivityType,
        dedupe_key: str,
        collective_id: str,
        actor_user_id: str | None = None,
        pathway_id: str | None = None,
        gathering_id: str | None = None,
        series_id: str | None = None,
        conversation_id: str | None = None,
        resource_id: str | None = None,
        payload: dict | None = None,
        priority: ActivityPriority | None = None,
    ) -> Activity | None:
        """Create one row describing one piece of Collective content.

        No recipient. Who may see it is decided when it is read, from
        the permissions that already govern the content itself, so
        publishing costs one insert whether the Collective has five
        members or five thousand.

        ``dedupe_key`` is required and is the whole idempotency story.
        Returns ``None`` when the key is already present — the content
        has been announced before, and a retry, a double-click or two
        racing requests all land here.

        Insert-and-catch rather than check-then-insert: the check loses
        the race precisely when two publishes arrive together, which is
        the case worth surviving. The savepoint keeps the conflict from
        poisoning the caller's transaction, so a publish that happens to
        be a repeat still commits its own work.

        The caller owns ``db.commit()``, as with every method here.
        """
        if not isinstance(event_type, ActivityType):
            raise TypeError(
                f"event_type must be an ActivityType, got {type(event_type).__name__}"
            )
        if not dedupe_key:
            raise ValueError("create_shared requires a dedupe_key")

        category = CATEGORY_OF[event_type]
        resolved_priority = priority or DEFAULT_PRIORITY_OF[event_type]

        activity = Activity(
            id=f"act_{uuid.uuid4().hex[:20]}",
            event_type=event_type.value,
            category=category.value,
            priority=resolved_priority.value,
            actor_user_id=actor_user_id,
            recipient_user_id=None,
            collective_id=collective_id,
            pathway_id=pathway_id,
            gathering_id=gathering_id,
            series_id=series_id,
            conversation_id=conversation_id,
            resource_id=resource_id,
            payload=payload or {},
            dedupe_key=dedupe_key,
        )
        try:
            with db.begin_nested():
                db.add(activity)
                db.flush()
        except IntegrityError as exc:
            if not _is_dedupe_conflict(exc):
                # Not a repeat — a genuinely bad row. Let it out, so the
                # producer logs it at ERROR (and Sentry raises it)
                # rather than filing it as "already announced".
                raise
            logger.info(
                "activity already recorded for dedupe_key=%s", dedupe_key,
            )
            return None
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
    def list_shared_for_member(
        db: Session,
        *,
        user,
        collective_id: str | None = None,
        limit: int = 20,
        since: "datetime | None" = None,
        before: "datetime | None" = None,
        recent_moments_only: bool = False,
    ) -> list[Activity]:
        """Shared Collective activity this member is allowed to see.

        A shared row has no recipient, so access is decided here. The
        filters run cheapest-first and each one is the rule that already
        governs the underlying content — none of them is a second
        opinion invented for activity:

          1. active membership of the Collective;
          2. the Area must be reachable by this member;
          3. the entity itself must be visible to them;
          4. the entity must still be live.

        (4) is a join rather than a cleanup job, so unpublishing or
        deleting content removes it from every feed at once and cannot
        drift out of step with the rows.

        A member never sees their own action. Ordered newest-first.
        """
        from app.models.platform import (
            CommunityPost,
            Event,
            EventSeries,
            Pathway,
            SpaceMembership,
            SpaceMembershipStatus,
        )

        if user is None:
            return []

        memberships = (
            db.query(SpaceMembership.space_id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        )
        space_ids = {m[0] for m in memberships}
        if collective_id is not None:
            space_ids &= {collective_id}
        if not space_ids:
            return []

        q = (
            db.query(Activity)
            .filter(
                Activity.recipient_user_id.is_(None),
                Activity.collective_id.in_(space_ids),
                Activity.archived_at.is_(None),
                Activity.category.in_(SHARED_MEMBER_CATEGORIES),
            )
        )
        # Recent Moments is a narrower set than "everything in this
        # category" — see RECENT_MOMENTS. It has to be applied here as
        # well as to the personal query, or a shared row reaches the
        # panel on category alone and the two halves of one feed
        # disagree about what belongs in it.
        if recent_moments_only:
            q = q.filter(
                Activity.event_type.in_([t.value for t in RECENT_MOMENTS])
            )
        if since is not None:
            q = q.filter(Activity.created_at > since)
        # `before` is applied in SQL, not to the returned page. Trimming
        # afterwards would cap the rows at `limit` *first* and then
        # throw most of them away, so a Collective with a busy first
        # page would appear to have no older shared activity at all.
        if before is not None:
            q = q.filter(Activity.created_at < before)
        if user.id:
            q = q.filter(Activity.actor_user_id.is_distinct_from(user.id))

        # Over-fetch: permission filtering below removes rows, and the
        # caller asked for `limit` visible ones, not `limit` candidates.
        rows = q.order_by(Activity.created_at.desc()).limit(limit * 5).all()

        return ActivityService._visible_only(db, user, rows)[:limit]

    @staticmethod
    def _visible_only(db: Session, user, rows: list[Activity]) -> list[Activity]:
        """Drop rows whose subject this member may not see or which no
        longer exist. Resolves each permission set once, not per row."""
        from app.models.platform import (
            CommunityPost,
            Event,
            EventSeries,
            Pathway,
            Space,
        )
        from app.services.channel_permissions import accessible_channels_for_user
        from app.spaces import area_policies
        from app.spaces.area_access import resolve_area_access

        if not rows:
            return []

        spaces = {
            s.id: s
            for s in db.query(Space)
            .filter(Space.id.in_({r.collective_id for r in rows if r.collective_id}))
            .all()
        }

        area_of = {
            "conversations": area_policies.AREA_CONVERSATIONS,
            "pathways": area_policies.AREA_PATHWAYS,
            "gatherings": area_policies.AREA_GATHERINGS,
        }
        # One resolve per Collective — it answers every area at once —
        # rather than one per (space, area) or, worse, one per row.
        area_cache: dict[str, object] = {}
        channel_cache: dict[str, set[str]] = {}

        # One liveness lookup per entity kind, not one per row.
        live_pathways = {
            p.id
            for p in db.query(Pathway.id)
            .filter(
                Pathway.id.in_({r.pathway_id for r in rows if r.pathway_id} or {""}),
                Pathway.status.in_(["active", "coming_soon"]),
            )
            .all()
        }
        live_gatherings = {
            e.id
            for e in db.query(Event.id)
            .filter(
                Event.id.in_({r.gathering_id for r in rows if r.gathering_id} or {""}),
                Event.is_published.is_(True),
                Event.status == "active",
            )
            .all()
        }
        live_series = {
            x.id
            for x in db.query(EventSeries.id)
            .filter(
                EventSeries.id.in_({r.series_id for r in rows if r.series_id} or {""}),
                EventSeries.status == "published",
            )
            .all()
        }
        live_posts = {
            c.id
            for c in db.query(CommunityPost.id)
            .filter(
                CommunityPost.id.in_(
                    {r.conversation_id for r in rows if r.conversation_id} or {""}
                ),
                CommunityPost.publication_status == "published",
            )
            .all()
        }

        out: list[Activity] = []
        for r in rows:
            # A shared row is *about* something, and the entity id is
            # the only link to the content whose liveness and
            # permissions decide visibility. Every one of those columns
            # is ON DELETE SET NULL, so deleting the content does not
            # delete the row — it empties it, and an empty row would
            # then pass every check below by having nothing left to
            # check. Require a subject, so deleted content disappears.
            if not (
                r.pathway_id
                or r.gathering_id
                or r.series_id
                or r.conversation_id
            ):
                continue

            space = spaces.get(r.collective_id or "")
            if space is None or space.status != "active":
                continue

            area = area_of.get(r.category)
            if area is not None:
                if space.id not in area_cache:
                    try:
                        area_cache[space.id] = resolve_area_access(db, space, user)
                    except Exception:
                        logger.exception(
                            "activity: area access failed for space %s", space.id,
                        )
                        area_cache[space.id] = None
                access = area_cache[space.id]
                # Fail closed: an unresolvable policy hides the row
                # rather than exposing it.
                if access is None or not access.can_reach(area):
                    continue

            if r.pathway_id and r.pathway_id not in live_pathways:
                continue
            if r.gathering_id and r.gathering_id not in live_gatherings:
                continue
            if r.series_id and r.series_id not in live_series:
                continue
            if r.conversation_id:
                if r.conversation_id not in live_posts:
                    continue
                if space.id not in channel_cache:
                    channel_cache[space.id] = {
                        c.id
                        for c in accessible_channels_for_user(user, space, db)
                    }
                post = (
                    db.query(CommunityPost)
                    .filter(CommunityPost.id == r.conversation_id)
                    .first()
                )
                chan = getattr(post, "channel_id", None) if post else None
                if chan is not None and chan not in channel_cache[space.id]:
                    continue

            out.append(r)
        return out

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
