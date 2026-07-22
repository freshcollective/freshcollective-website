"""Scheduled community-post publisher.

Runs both as a periodic background loop (started from the FastAPI
lifespan) and as an on-demand helper called at the start of read
endpoints. Idempotence is enforced at the row level:

    UPDATE community_posts
       SET publication_status = 'published',
           published_at = NOW(),
           notifications_processed_at = NOW()
     WHERE id = :id
       AND publication_status = 'scheduled'
       AND notifications_processed_at IS NULL

If the UPDATE affects zero rows the caller silently drops the post
from its notification batch — another process (or a previous
scheduler tick) already published it. Retries therefore cannot
duplicate posts or notifications.

The publisher deliberately does NOT publish scheduled posts whose
collective has fallen back to draft. That's an unusual state
(usually a creator unpublishes their collective after scheduling)
but keeping the guard here means we don't need to also clean up
scheduled posts when a collective changes status.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.platform import CommunityPost, ConversationChannel, Space
from app.services.notification_service import trigger_mention, trigger_new_post

logger = logging.getLogger(__name__)

# How often the background loop wakes up. Small enough that the
# perceived delay between "scheduled_for" and "actually visible" is at
# most a few seconds; large enough that idle collectives don't spam
# the DB.
_TICK_SECONDS = 30


def publish_due_posts(db: Session) -> list[str]:
    """Publish any posts whose `scheduled_for` has passed.

    Returns the list of post IDs that this call actually transitioned
    from scheduled to published. The caller is responsible for firing
    notification triggers for those IDs (see `_dispatch_notifications`).
    """
    now = datetime.utcnow()
    due = (
        db.query(CommunityPost.id, CommunityPost.space_id, CommunityPost.author_id)
        .filter(
            CommunityPost.publication_status == "scheduled",
            CommunityPost.scheduled_for.isnot(None),
            CommunityPost.scheduled_for <= now,
            CommunityPost.notifications_processed_at.is_(None),
        )
        .all()
    )
    if not due:
        return []

    # Skip posts in collectives that are no longer active — leave
    # them scheduled until the collective is republished. Also skip
    # posts whose destination Channel has been archived — the
    # caretaker gets to decide (restore, cancel, or reschedule); the
    # row stays `scheduled` and resumes automatically on restore.
    active_space_ids = {
        row.id for row in db.query(Space.id)
        .filter(Space.id.in_({row.space_id for row in due}), Space.status == "active")
        .all()
    }
    due_post_ids = [row.id for row in due]
    post_channels: dict[str, str] = dict(
        db.query(CommunityPost.id, CommunityPost.channel_id)
        .filter(CommunityPost.id.in_(due_post_ids))
        .all()
    )
    archived_channel_ids: set[str] = {
        row.id for row in db.query(ConversationChannel.id)
        .filter(
            ConversationChannel.id.in_(set(post_channels.values())),
            ConversationChannel.is_archived.is_(True),
        )
        .all()
    }
    winnable = [
        row for row in due
        if row.space_id in active_space_ids
        and post_channels.get(row.id) not in archived_channel_ids
    ]

    published_ids: list[tuple[str, str, str]] = []
    for row in winnable:
        # Atomic transition — the WHERE clause guarantees exactly one
        # process wins even if two publishers race.
        affected = db.execute(
            text(
                "UPDATE community_posts "
                "SET publication_status = 'published', "
                "    published_at = :now, "
                "    notifications_processed_at = :now "
                "WHERE id = :id "
                "  AND publication_status = 'scheduled' "
                "  AND notifications_processed_at IS NULL"
            ),
            {"id": row.id, "now": now},
        )
        if affected.rowcount == 1:
            published_ids.append((row.id, row.space_id, row.author_id))

    if published_ids:
        db.commit()

    # Fire triggers OUTSIDE the transaction. Each trigger opens its own
    # session (see notification_service), so we don't tie their success
    # to our commit.
    for post_id, space_id, author_id in published_ids:
        _dispatch_notifications(post_id, space_id, author_id)

    return [pid for pid, _s, _a in published_ids]


def _dispatch_notifications(post_id: str, space_id: str, author_id: str) -> None:
    """Fire the same notifications as immediate publication."""
    # New-post broadcast to space members (author excluded inside).
    try:
        trigger_new_post(post_id, space_id, author_id)
    except Exception:
        logger.exception("scheduled trigger_new_post failed for %s", post_id)

    # Mentions — read the stored list and notify each recipient.
    db = SessionLocal()
    try:
        post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if not post:
            return
        for uid in list(post.mentioned_user_ids or []):
            if uid and uid != author_id:
                try:
                    trigger_mention(post_id, None, author_id, uid)
                except Exception:
                    logger.exception(
                        "scheduled trigger_mention failed for post %s user %s",
                        post_id, uid,
                    )
    finally:
        db.close()


def publish_due_posts_from_pool() -> list[str]:
    """Session-managing wrapper for callers that don't already hold one."""
    db = SessionLocal()
    try:
        return publish_due_posts(db)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Background loop — started from the FastAPI lifespan hook
# ---------------------------------------------------------------------------

_task: asyncio.Task | None = None


async def _loop() -> None:
    logger.info("scheduled_publisher loop starting (tick=%ss)", _TICK_SECONDS)
    while True:
        try:
            await asyncio.to_thread(publish_due_posts_from_pool)
        except Exception:
            logger.exception("scheduled_publisher loop iteration failed")
        await asyncio.sleep(_TICK_SECONDS)


def start_publisher() -> None:
    """Fire-and-forget task launcher used from the app lifespan."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="scheduled_publisher")


async def stop_publisher() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
