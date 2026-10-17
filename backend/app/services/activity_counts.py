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

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session, aliased

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
    #: Which Channels the ``conversations`` number came from — the ids
    #: with anything unseen, not a count each.
    #:
    #: Ids rather than numbers on purpose. The selector shows one dot
    #: per Channel however many unseen discussions it holds, and the
    #: tally belongs to the one badge in the navigation. Shipping a set
    #: makes that true by construction instead of by convention at the
    #: render site.
    conversation_channels: tuple[str, ...] = ()

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



def _liveness_filters(scope: MemberScope, moment: datetime) -> list:
    """The predicates that decide whether an activity row is still
    about something this member can open, right now.

    One definition, used by the count, the clamp and the presented-id
    resolver. Three copies of a permission rule is three chances for
    one of them to drift, and a drift here either hides activity or
    leaks it.
    """
    from app.models.platform import (
        CommunityPost,
        Event,
        EventSeries,
        Pathway,
    )

    return [
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
                    Event.is_published.is_(True),
                    Event.status == "active",
                    # Only what the Gatherings page renders. It shows
                    # the ``upcoming`` scope; a past Gathering sits
                    # behind a link to the archive and is never on
                    # screen, so counting one leaves a badge no visit
                    # can clear. This is the page's own rule for past.
                    func.coalesce(
                        Event.ends_at,
                        Event.starts_at + text("interval '1 hour'"),
                    ) >= moment,
                )
            ),
        ),
        or_(
            Activity.series_id.is_(None),
            Activity.series_id.in_(
                select(EventSeries.id).where(EventSeries.status == "published")
            ),
        ),
        or_(
            Activity.conversation_id.is_(None),
            Activity.conversation_id.in_(
                select(CommunityPost.id).where(
                    CommunityPost.publication_status == "published",
                    # Mirrors the community feed. A post hidden by
                    # Community Care, or made invisible, never renders
                    # — counting it leaves a badge no visit can clear.
                    CommunityPost.is_visible.is_(True),
                    CommunityPost.cc_hidden_at.is_(None),
                    # The *notifiable* set, not the accessible one. A
                    # Channel hidden from navigation stays readable by
                    # direct link and findable in search, but it is
                    # absent from the selector — so an indicator
                    # pointing at it could never be cleared by any
                    # visit. One definition, used by the count, the
                    # clamp and the presented-id resolver alike, so a
                    # hidden Channel is uncounted, un-clamped and
                    # un-markable together.
                    CommunityPost.channel_id.in_(scope.notifiable_channel_ids)
                    if scope.notifiable_channel_ids
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
    ]


def scope_key_for(category: str, channel_id: str | None) -> str:
    """Which part of a category a mark covers.

    Conversations is the only category the interface sub-divides, so
    it is the only one with a non-empty scope.
    """
    if category == "conversations":
        return channel_id or ""
    return ""


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

    rows = _unseen_rows(db, scope, now=now)

    tally: dict[str, dict[str, int]] = {
        sid: {c: 0 for c in COUNTED_CATEGORIES} for sid in scope.space_ids
    }
    channels: dict[str, set[str]] = {sid: set() for sid in scope.space_ids}
    for space_id, category, n, scope_key in rows:
        # Area policy is a decision per (Collective, category), not per
        # row, so it is applied here rather than in SQL — the grouped
        # result is a handful of rows per Collective, which makes this
        # exactly equivalent and free.
        if category not in scope.categories_for(space_id):
            continue
        count = int(n)
        # Summed, not assigned: the query now returns one row per
        # scope, and a category's number is the whole category.
        tally[space_id][category] += count
        if category == "conversations" and scope_key and count > 0:
            channels[space_id].add(str(scope_key))

    return [
        CollectiveCounts(
            collective_id=sid,
            conversations=t["conversations"],
            pathways=t["pathways"],
            gatherings=t["gatherings"],
            conversation_channels=tuple(sorted(channels[sid])),
        )
        for sid, t in sorted(tally.items())
    ]


def _unseen_rows(db: Session, scope: MemberScope, *, now: datetime | None = None):
    """The grouped ``(collective, category, count, scope_key)`` rows,
    before Area filtering.

    One row per Channel for conversations and a single empty-scope row
    for the other two categories, so one query answers both the
    category totals and which Channels they came from. The clamp in
    ``max_visible_sequence`` does not call this — it shares
    ``_liveness_filters`` instead, which is the part that must not
    drift.
    """
    from app.models.platform import (
        CommunityPost,
        Event,
        EventSeries,
        Pathway,
    )

    me = scope.user_id
    moment = now or datetime.utcnow()
    cursor = CollectiveActivityCursor

    joined_cases = [
        (Activity.collective_id == sid, joined)
        for sid, joined in scope.joined_at.items()
    ]

    # The Channel a conversation row belongs to, which is also its
    # cursor scope. Outer-joined because only conversation rows have
    # one; liveness is still decided by the subquery below.
    post_for_scope = aliased(CommunityPost)
    row_scope = case(
        (
            Activity.category == "conversations",
            func.coalesce(post_for_scope.channel_id, ""),
        ),
        else_="",
    )

    q = (
        db.query(
            Activity.collective_id,
            Activity.category,
            func.count(func.distinct(_subject())),
            row_scope,
        )
        .outerjoin(
            post_for_scope, post_for_scope.id == Activity.conversation_id,
        )
        .outerjoin(
            cursor,
            (cursor.user_id == me)
            & (cursor.collective_id == Activity.collective_id)
            & (cursor.category == Activity.category)
            # Scoped: a mark for one Channel says nothing about
            # another. Without this, reading Channel A clears B.
            & (cursor.scope_key == row_scope),
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
    q = q.filter(*_liveness_filters(scope, moment))

    # Unseen: above the cursor, or since joining when there is none.
    if joined_cases:
        # ``case`` is imported at module level. A local re-import here
        # would make the name a local for this whole function and
        # shadow it from its first use above — the FC-API-8 shape.
        joined_for_row = case(*joined_cases, else_=None)
        q = q.filter(
            or_(
                cursor.seen_through_seq.is_(None)
                & (Activity.created_at > joined_for_row),
                Activity.sequence_number > cursor.seen_through_seq,
            )
        )

    # Grouped one level finer than the caller needs, so the per-Channel
    # breakdown the selector dots want comes out of the query that was
    # already running rather than a second one.
    #
    # The per-category totals stay exact under this: a post belongs to
    # exactly one Channel, so ``count(DISTINCT subject)`` partitions
    # cleanly across scopes and the sums agree. Pathways and
    # Gatherings have no sub-division and collapse to a single empty
    # scope, exactly as before.
    return q.group_by(
        Activity.collective_id, Activity.category, row_scope,
    ).all()


def max_visible_sequence(
    db: Session,
    scope: MemberScope,
    *,
    collective_id: str,
    category: str,
    now: datetime | None = None,
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
    moment = now or datetime.utcnow()
    q = (
        db.query(func.max(Activity.sequence_number))
        .filter(
            Activity.collective_id == collective_id,
            Activity.category == category,
            Activity.recipient_user_id.is_(None),
            Activity.archived_at.is_(None),
            Activity.actor_user_id.is_distinct_from(me),
            _subject().isnot(None),
            *_liveness_filters(scope, moment),
        )
    )
    return q.scalar()


def resolve_presented(
    db: Session,
    scope: MemberScope,
    *,
    collective_id: str,
    category: str,
    subject_ids: list[str],
    boundary_sequence: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """The furthest each scope may advance, given what was rendered.

    Two independent limits, and both are needed.

    ``subject_ids`` says *which* content was on screen. It is what
    stops a visit to one Channel clearing another, and a visit to
    upcoming Gatherings clearing the archive.

    ``boundary_sequence`` says *when* the page was built. Subject ids
    alone are not enough: a member reading a Pathway while a second
    step is published in it would submit that same Pathway id, and the
    new step's row hangs off it. The boundary excludes anything
    numbered after the render, so the new step survives.

    Returns ``{scope_key: max_sequence}`` — one entry per scope the
    submitted content actually touched, so a page that rendered one
    Channel moves exactly one cursor.
    """
    from app.models.platform import CommunityPost

    moment = now or datetime.utcnow()
    if not subject_ids:
        return {}

    post_for_scope = aliased(CommunityPost)
    row_scope = case(
        (
            Activity.category == "conversations",
            func.coalesce(post_for_scope.channel_id, ""),
        ),
        else_="",
    )

    rows = (
        db.query(row_scope, func.max(Activity.sequence_number))
        .outerjoin(
            post_for_scope, post_for_scope.id == Activity.conversation_id,
        )
        .filter(
            Activity.collective_id == collective_id,
            Activity.category == category,
            Activity.recipient_user_id.is_(None),
            Activity.archived_at.is_(None),
            Activity.actor_user_id.is_distinct_from(scope.user_id),
            _subject().isnot(None),
            # What the page said it showed...
            _subject().in_(subject_ids),
            # ...as it was when the page was built.
            Activity.sequence_number <= boundary_sequence,
            # ...and only what this member may actually see. A crafted
            # id for someone else's private thread resolves to nothing.
            *_liveness_filters(scope, moment),
        )
        .group_by(row_scope)
        .all()
    )
    return {str(k): int(v) for k, v in rows if v is not None}


def current_boundary(db: Session, scope: MemberScope) -> int:
    """The highest activity sequence that exists for this member's
    Collectives right now.

    Captured when a section page begins rendering and sent back with
    the ids it displayed. Anything published afterwards is numbered
    higher and therefore cannot be marked seen, whether or not it
    shares a subject with something on the page.
    """
    if not scope.space_ids:
        return 0
    return int(
        db.query(func.coalesce(func.max(Activity.sequence_number), 0))
        .filter(Activity.collective_id.in_(scope.space_ids))
        .scalar()
        or 0
    )
