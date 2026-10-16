"""How much a member has not yet seen, per Collective, per category.

One grouped query over shared activity, filtered by a scope resolved
once (see ``activity_visibility``). A member in ten Collectives costs
the same as a member in one — which is the whole reason the shared-row
model was chosen over a row per recipient.

What "unseen" means
-------------------
Everything above the member's cursor for that Collective and category.
With no cursor, everything since they joined. The comparison is on
``sequence_number`` rather than ``created_at`` because rows written in
one commit share a timestamp exactly; see migration 156.

What is counted
---------------
Content items, not records. ``count(DISTINCT subject)`` means three
new steps in one Pathway are one Pathway, and a Gathering Series is
one offering however many occurrences it holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.activity import Activity, CollectiveActivityCursor
from app.services.activity_visibility import (
    CATEGORY_AREA,
    MemberScope,
    resolve_member_scope,
)

#: Categories a member-facing indicator may show. Messages
#: (``personal``) and member joins (``collective``) are deliberately
#: absent — they are a different surface's business.
COUNTED_CATEGORIES = tuple(CATEGORY_AREA.keys())

#: A step counts only when the member could open it. A Pathway's own
#: publication counts on listing visibility, which is looser — an
#: unbought paid Pathway is still news.
STEP_EVENT_TYPE = "pathway_step_released"


@dataclass(frozen=True)
class CollectiveCounts:
    collective_id: str
    conversations: int
    pathways: int
    gatherings: int

    @property
    def total(self) -> int:
        return self.conversations + self.pathways + self.gatherings


def _subject(model=Activity):
    """The content item an activity is about.

    Counting distinct subjects rather than rows is what turns "five
    activity records" into "two things happened".
    """
    return func.coalesce(
        model.pathway_id,
        model.series_id,
        model.gathering_id,
        model.conversation_id,
    )


def unseen_counts(
    db: Session,
    user,
    *,
    collective_id: str | None = None,
    now: datetime | None = None,
    scope: MemberScope | None = None,
) -> list[CollectiveCounts]:
    """Unseen counts for every Collective this member belongs to.

    Collectives with nothing unseen are returned as zeros rather than
    omitted, so a caller can render a complete list without having to
    know which Collectives exist.
    """
    scope = scope or resolve_member_scope(
        db, user, collective_id=collective_id, now=now,
    )
    if not scope.space_ids:
        return []

    rows = _unseen_rows(db, scope)

    tally: dict[str, dict[str, int]] = {
        sid: {c: 0 for c in COUNTED_CATEGORIES} for sid in scope.space_ids
    }
    for space_id, category, n in rows:
        # Area policy is a decision per (Collective, category), not per
        # row, so it is applied here rather than in SQL — the grouped
        # result is at most three rows per Collective, which makes this
        # exactly equivalent and free.
        if category in scope.categories_for(space_id):
            tally[space_id][category] = int(n)

    return [
        CollectiveCounts(
            collective_id=sid,
            conversations=t["conversations"],
            pathways=t["pathways"],
            gatherings=t["gatherings"],
        )
        for sid, t in sorted(tally.items())
    ]


def _unseen_rows(db: Session, scope: MemberScope):
    """The grouped (collective, category, count) rows, before Area
    filtering. Shared with the cursor clamp, which needs the same
    predicate to decide what a member could legitimately have seen."""
    from app.models.platform import (
        CommunityPost,
        Event,
        EventSeries,
        Pathway,
    )

    me = scope.user_id
    cursor = CollectiveActivityCursor

    joined_cases = [
        (Activity.collective_id == sid, joined)
        for sid, joined in scope.joined_at.items()
    ]

    q = (
        db.query(
            Activity.collective_id,
            Activity.category,
            func.count(func.distinct(_subject())),
        )
        .outerjoin(
            cursor,
            (cursor.user_id == me)
            & (cursor.collective_id == Activity.collective_id)
            & (cursor.category == Activity.category),
        )
        .filter(
            Activity.collective_id.in_(scope.space_ids),
            Activity.recipient_user_id.is_(None),
            Activity.archived_at.is_(None),
            Activity.category.in_(COUNTED_CATEGORIES),
            # Never your own doing.
            Activity.actor_user_id.is_distinct_from(me),
            # A row whose subject was deleted is empty, not new —
            # every subject column is ON DELETE SET NULL, so deletion
            # hollows the row out rather than removing it.
            #
            # Belt and braces here, and deliberately so: the DISTINCT
            # above already discards it, because count(DISTINCT NULL)
            # is zero. No test can tell this line apart from its
            # absence in *this* query, which is why it is stated
            # rather than relied upon. The same predicate in
            # ``max_visible_sequence`` is load-bearing and is tested —
            # there a hollow row would raise the ceiling.
            _subject().isnot(None),
        )
    )

    # Liveness, as joins rather than a cleanup job — unpublishing
    # removes a row from every count at once and cannot drift.
    q = q.filter(
        or_(
            Activity.pathway_id.is_(None),
            Activity.pathway_id.in_(
                select(Pathway.id).where(
                    Pathway.status.in_(["active", "coming_soon"])
                )
            ),
        ),
        or_(
            Activity.gathering_id.is_(None),
            Activity.gathering_id.in_(
                select(Event.id).where(
                    Event.is_published.is_(True), Event.status == "active"
                )
            ),
        ),
        or_(
            Activity.series_id.is_(None),
            Activity.series_id.in_(
                select(EventSeries.id).where(EventSeries.status == "published")
            ),
        ),
        # Conversations carry a channel, and channel access varies per
        # row — so unlike Area policy this one has to be in SQL.
        or_(
            Activity.conversation_id.is_(None),
            Activity.conversation_id.in_(
                select(CommunityPost.id).where(
                    CommunityPost.publication_status == "published",
                    CommunityPost.channel_id.in_(scope.accessible_channel_ids)
                    if scope.accessible_channel_ids
                    else False,
                )
            ),
        ),
        # A released step counts only where the member can open the
        # Pathway. The Pathway's own publication is governed by
        # listing visibility above, which is deliberately looser.
        or_(
            Activity.event_type != STEP_EVENT_TYPE,
            Activity.pathway_id.in_(scope.accessible_pathway_ids)
            if scope.accessible_pathway_ids
            else False,
        ),
    )

    # Unseen: above the cursor, or since joining when there is none.
    if joined_cases:
        from sqlalchemy import case

        joined_for_row = case(*joined_cases, else_=None)
        q = q.filter(
            or_(
                cursor.seen_through_seq.is_(None)
                & (Activity.created_at > joined_for_row),
                Activity.sequence_number > cursor.seen_through_seq,
            )
        )

    return q.group_by(Activity.collective_id, Activity.category).all()


def max_visible_sequence(
    db: Session,
    scope: MemberScope,
    *,
    collective_id: str,
    category: str,
) -> int | None:
    """The highest activity position this member could legitimately
    have been shown in this Collective and category.

    The cursor is clamped to this. A client reporting what it rendered
    is reporting a fact about its own screen, and a fact a client
    asserts about itself is not a fact the server may act on — without
    the clamp, a crafted request could skip the member past activity
    that was never presented, and nothing would ever show it again.
    """
    from app.models.platform import (
        CommunityPost,
        Event,
        EventSeries,
        Pathway,
    )

    if collective_id not in scope.space_ids:
        return None
    if category not in scope.categories_for(collective_id):
        return None

    me = scope.user_id
    q = (
        db.query(func.max(Activity.sequence_number))
        .filter(
            Activity.collective_id == collective_id,
            Activity.category == category,
            Activity.recipient_user_id.is_(None),
            Activity.archived_at.is_(None),
            Activity.actor_user_id.is_distinct_from(me),
            _subject().isnot(None),
            or_(
                Activity.pathway_id.is_(None),
                Activity.pathway_id.in_(
                    select(Pathway.id).where(
                        Pathway.status.in_(["active", "coming_soon"])
                    )
                ),
            ),
            or_(
                Activity.gathering_id.is_(None),
                Activity.gathering_id.in_(
                    select(Event.id).where(
                        Event.is_published.is_(True), Event.status == "active"
                    )
                ),
            ),
            or_(
                Activity.series_id.is_(None),
                Activity.series_id.in_(
                    select(EventSeries.id).where(
                        EventSeries.status == "published"
                    )
                ),
            ),
            or_(
                Activity.conversation_id.is_(None),
                Activity.conversation_id.in_(
                    select(CommunityPost.id).where(
                        CommunityPost.publication_status == "published",
                        CommunityPost.channel_id.in_(
                            scope.accessible_channel_ids
                        )
                        if scope.accessible_channel_ids
                        else False,
                    )
                ),
            ),
            or_(
                Activity.event_type != STEP_EVENT_TYPE,
                Activity.pathway_id.in_(scope.accessible_pathway_ids)
                if scope.accessible_pathway_ids
                else False,
            ),
        )
    )
    return q.scalar()
