"""Unread direct messages, per Collective, in one query.

Why this is not in ``activity_counts``
--------------------------------------
That module counts rows in ``activities`` — the shared feed — and says
so in its own docstring. Direct messages are not in that feed and are
deliberately excluded from it: ``COUNTED_CATEGORIES`` omits the
``personal`` category because "they are a different surface's
business". That decision stands. Your World now shows a *separate*
indicator, so the two numbers stay apart and neither is folded into
the other.

Why it is not a second request
------------------------------
``GET /api/activities/unseen-counts`` already answers "what has this
member not seen, per Collective" in a single round trip, and Your World
already calls it once for every card. Adding one grouped query to that
endpoint keeps the page at one request whatever a member's Collective
count; fetching per card, or polling, would not.

What counts as unread
---------------------
The same rule the thread list uses (``_unread_count_for`` in
``app/messages/routes.py``): a message is unread for someone when
``is_read`` is false and they did not send it. Either side of a thread
qualifies — a creator reading Your World has unread messages when a
member has replied, exactly as a member does when the creator writes.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.messages import DirectMessage, MessageThread


def unread_message_counts(
    db: Session,
    user_id: str,
    space_ids: Iterable[str],
) -> dict[str, int]:
    """``{space_id: unread}`` for the Collectives given.

    Spaces with nothing unread are omitted; the caller defaults to
    zero, which renders no indicator. Scoped to ``space_ids`` so a
    count can never cross into a Collective the caller is not in —
    the caller resolves that membership, and this trusts it rather
    than resolving it a second way.
    """
    ids = [s for s in space_ids if s]
    if not ids:
        return {}

    rows = db.execute(
        select(MessageThread.space_id, func.count(DirectMessage.id))
        .join(DirectMessage, DirectMessage.thread_id == MessageThread.id)
        .where(
            MessageThread.space_id.in_(ids),
            # Either side of the conversation — whichever one is me.
            or_(
                MessageThread.member_id == user_id,
                MessageThread.creator_id == user_id,
            ),
            # Not the ones I sent.
            DirectMessage.sender_id != user_id,
            DirectMessage.is_read.is_(False),
        )
        .group_by(MessageThread.space_id)
    ).all()

    return {space_id: count for space_id, count in rows if count}
