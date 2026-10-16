"""Advancing a member's seen mark, forwards only.

The rule is "visiting clears what was presented", so the mark is the
newest thing the member was actually shown — never ``now()``. That one
choice is what makes activity created while the page was open survive
the visit: it is newer than anything rendered, so it stays above the
mark without anybody having to special-case it.

Two things are enforced here rather than trusted:

* **Forward only.** ``GREATEST`` on the stored value, so a slow
  response, a second browser tab, or a replayed request can never
  reopen activity that was already cleared — and never clear more
  than the request that arrived last and highest.
* **Clamped to reality.** The client reports what its own screen
  showed. That is a claim, not evidence, so it is capped at the
  highest position the member could legitimately have been shown
  (``max_visible_sequence``). Without the clamp a crafted request
  could skip a member past activity they never saw, and nothing would
  ever surface it again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.activity import Activity, CollectiveActivityCursor
from app.services.activity_counts import (
    current_boundary,
    max_visible_sequence,
    resolve_presented,
    scope_key_for,
)
from app.services.activity_visibility import (
    CATEGORY_AREA,
    MemberScope,
    resolve_member_scope,
)

VALID_CATEGORIES = frozenset(CATEGORY_AREA.keys())


class CursorRefused(Exception):
    """The request named something this member may not advance.

    Carries a reason for the route to turn into a status code; the
    member never sees these strings.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


#: A page cannot submit an unbounded id list. Far above any real
#: section — the busiest Channel renders tens — and low enough that a
#: crafted request cannot turn one POST into a scan.
MAX_SUBJECT_IDS = 500


@dataclass(frozen=True)
class CursorState:
    collective_id: str
    category: str
    #: One entry per scope actually advanced. Conversations moves the
    #: visited Channel only; the other categories move their single
    #: unscoped cursor.
    advanced: dict[str, int]


def advance(
    db: Session,
    user,
    *,
    collective_id: str,
    category: str,
    subject_ids: list[str],
    boundary_sequence: int,
    now: datetime | None = None,
    scope: MemberScope | None = None,
) -> CursorState:
    """Record what a section visit actually put on screen.

    The page sends the content it rendered and the boundary it
    rendered against. The server decides what that means — which
    activity rows those subjects carry, which of them this member may
    see, and which scope each belongs to. Nothing about the result is
    taken from the client.

    The caller owns ``db.commit()``.
    """
    if user is None or not getattr(user, "id", None):
        raise CursorRefused("not_authenticated")
    if category not in VALID_CATEGORIES:
        raise CursorRefused("unknown_category")
    if not isinstance(subject_ids, list):
        raise CursorRefused("invalid_subjects")
    if len(subject_ids) > MAX_SUBJECT_IDS:
        raise CursorRefused("too_many_subjects")
    if any(not isinstance(i, str) or not i for i in subject_ids):
        raise CursorRefused("invalid_subjects")
    if not isinstance(boundary_sequence, int) or isinstance(boundary_sequence, bool):
        raise CursorRefused("invalid_boundary")
    if boundary_sequence < 0:
        raise CursorRefused("invalid_boundary")

    scope = scope or resolve_member_scope(
        db, user, collective_id=collective_id, now=now,
    )
    # Membership is established by resolving the scope, not by
    # trusting the id in the request.
    if collective_id not in scope.space_ids:
        raise CursorRefused("not_a_member")
    if category not in scope.categories_for(collective_id):
        raise CursorRefused("area_unreachable")

    presented = resolve_presented(
        db, scope,
        collective_id=collective_id,
        category=category,
        subject_ids=subject_ids,
        boundary_sequence=boundary_sequence,
        now=now,
    )
    if not presented:
        # An empty section, a page of content with no activity behind
        # it, or ids this member cannot see. None of those is an
        # error, and none of them may move a cursor.
        return CursorState(collective_id, category, {})

    advanced: dict[str, int] = {}
    for key, seq in presented.items():
        advanced[key] = _upsert(
            db,
            user_id=user.id,
            collective_id=collective_id,
            category=category,
            scope_key=key,
            sequence=seq,
            now=now,
        )
    return CursorState(collective_id, category, advanced)


def _upsert(
    db: Session, *, user_id: str, collective_id: str, category: str,
    scope_key: str, sequence: int, now: datetime | None,
) -> int:
    """Move one scope's mark forward, never back."""
    stamp = (
        db.query(Activity.created_at)
        .filter(
            Activity.collective_id == collective_id,
            Activity.category == category,
            Activity.sequence_number <= sequence,
        )
        .order_by(Activity.sequence_number.desc())
        .limit(1)
        .scalar()
    ) or (now or datetime.utcnow())

    table = CollectiveActivityCursor.__table__
    stmt = (
        pg_insert(table)
        .values(
            id=f"cur_{uuid.uuid4().hex[:20]}",
            user_id=user_id,
            collective_id=collective_id,
            category=category,
            scope_key=scope_key,
            seen_through=stamp,
            seen_through_seq=sequence,
        )
        .on_conflict_do_update(
            constraint="ux_activity_cursor_member_scope",
            set_={
                # Forward only. A slow response, a second tab, or a
                # replayed request cannot reopen cleared activity —
                # and cannot clear more than the highest visit.
                "seen_through_seq": func_greatest(
                    table.c.seen_through_seq, sequence,
                ),
                "seen_through": func_greatest(table.c.seen_through, stamp),
                "updated_at": datetime.utcnow(),
            },
        )
        .returning(table.c.seen_through_seq)
    )
    return int(db.execute(stmt).scalar())


def func_greatest(column, value):
    from sqlalchemy import func

    return func.greatest(column, value)


def _existing(db: Session, user_id: str, collective_id: str, category: str,
              scope_key: str = ""):
    return (
        db.query(CollectiveActivityCursor)
        .filter(
            CollectiveActivityCursor.user_id == user_id,
            CollectiveActivityCursor.collective_id == collective_id,
            CollectiveActivityCursor.category == category,
            CollectiveActivityCursor.scope_key == scope_key,
        )
        .first()
    )
