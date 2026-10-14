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
from app.services.activity_counts import max_visible_sequence
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


@dataclass(frozen=True)
class CursorState:
    collective_id: str
    category: str
    seen_through_seq: int
    seen_through: datetime


def advance(
    db: Session,
    user,
    *,
    collective_id: str,
    category: str,
    through_sequence: int,
    now: datetime | None = None,
    scope: MemberScope | None = None,
) -> CursorState:
    """Move this member's mark for one Collective and category.

    The caller owns ``db.commit()``.
    """
    if user is None or not getattr(user, "id", None):
        raise CursorRefused("not_authenticated")
    if category not in VALID_CATEGORIES:
        raise CursorRefused("unknown_category")
    if not isinstance(through_sequence, int) or isinstance(through_sequence, bool):
        raise CursorRefused("invalid_sequence")
    if through_sequence < 0:
        raise CursorRefused("invalid_sequence")

    scope = scope or resolve_member_scope(
        db, user, collective_id=collective_id, now=now,
    )
    # Membership is checked by resolving the scope, not by trusting the
    # id in the request — one member can never move another's state,
    # and a non-member cannot create one.
    if collective_id not in scope.space_ids:
        raise CursorRefused("not_a_member")
    if category not in scope.categories_for(collective_id):
        raise CursorRefused("area_unreachable")

    ceiling = max_visible_sequence(
        db, scope, collective_id=collective_id, category=category,
    )
    if ceiling is None:
        # Nothing this member could have been shown, so there is
        # nothing to clear. Not an error — an empty section is a
        # perfectly ordinary thing to visit.
        existing = _existing(db, user.id, collective_id, category)
        if existing is not None:
            return CursorState(
                collective_id, category,
                existing.seen_through_seq, existing.seen_through,
            )
        raise CursorRefused("nothing_to_advance")

    effective = min(through_sequence, ceiling)

    # The timestamp is carried for legibility only, so it is read from
    # the row the mark lands on rather than invented.
    stamp = (
        db.query(Activity.created_at)
        .filter(
            Activity.collective_id == collective_id,
            Activity.category == category,
            Activity.sequence_number <= effective,
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
            user_id=user.id,
            collective_id=collective_id,
            category=category,
            seen_through=stamp,
            seen_through_seq=effective,
        )
        .on_conflict_do_update(
            constraint="ux_activity_cursor_member_scope",
            set_={
                # Forward only. Both columns take the greater value so
                # they cannot disagree about which visit won.
                "seen_through_seq": func_greatest(
                    table.c.seen_through_seq, effective,
                ),
                "seen_through": func_greatest(table.c.seen_through, stamp),
                "updated_at": datetime.utcnow(),
            },
        )
        .returning(table.c.seen_through_seq, table.c.seen_through)
    )
    row = db.execute(stmt).first()
    return CursorState(collective_id, category, row[0], row[1])


def func_greatest(column, value):
    from sqlalchemy import func

    return func.greatest(column, value)


def _existing(db: Session, user_id: str, collective_id: str, category: str):
    return (
        db.query(CollectiveActivityCursor)
        .filter(
            CollectiveActivityCursor.user_id == user_id,
            CollectiveActivityCursor.collective_id == collective_id,
            CollectiveActivityCursor.category == category,
        )
        .first()
    )
