"""Mention resolution helpers for Community posts and comments.

Client-authored mentions: the composer inserts `@Display Name` into the
text visually and sends the resolved `mentioned_user_ids` list alongside
the body. The server does two things:

  1. Deduplicates the list.
  2. Filters it down to user IDs who are currently active members of
     the target space. Anything else is silently dropped, so a
     malformed / stale client cannot notify users outside the
     collective.

This keeps the mention feature strictly scoped to the current
collective (per the Phase 1 spec) without needing a fragile name
matcher on the server.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.platform import SpaceMembership


def sanitize_mentions(
    db: Session,
    space_id: str,
    author_id: str,
    raw_ids: list[str] | None,
) -> list[str]:
    """Return the subset of `raw_ids` that are active members of `space_id`.

    The author's own ID is dropped so mentioning yourself never fires a
    notification.
    """
    if not raw_ids:
        return []
    # Preserve authoring order while deduping.
    seen: set[str] = set()
    ordered: list[str] = []
    for uid in raw_ids:
        if uid and uid != author_id and uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    if not ordered:
        return []
    active = {
        row.user_id
        for row in db.query(SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id.in_(ordered),
            SpaceMembership.status == "active",
        )
        .all()
    }
    return [uid for uid in ordered if uid in active]
