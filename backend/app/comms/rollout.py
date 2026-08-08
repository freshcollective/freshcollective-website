"""Rollout wiring — the single place trigger sites go through.

Every emit call site follows the same shape::

    event = emit(db, event_type="...", ...)
    schedule_routing_if_needed(background_tasks, event, "...")

Callers do not need to know whether shadow mode is on, whether the
topic is live, or which delivery_mode to use — this module resolves
it from ``settings`` and dispatches accordingly.

Legacy triggers add a matching top-of-function guard::

    def trigger_new_post(...):
        if is_event_live("community.post.published"):
            return
        ...existing logic...

The two together ensure that for a non-live topic the legacy path
is authoritative and shadow observes; for a live topic the legacy
path no-ops and the routing pipeline creates the delivery intents.
No duplicate-send window.

Configuration
-------------

Both ``COMMS_SHADOW`` and ``COMMS_LIVE_TOPICS`` are consulted here.
``COMMS_LIVE_TOPICS`` accepts either topic keys or category keys —
a match on either promotes the event to live. This matters because
the design roadmap mixes both: ``direct_messages`` (topic),
``conversations`` (topic), ``creator_updates`` (category),
``platform_updates`` (category).
"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from app.comms.categories import TOPIC_TO_CATEGORY
from app.comms.intents import DELIVERY_MODE_LIVE, DELIVERY_MODE_SHADOW
from app.comms.models import CommunicationEvent
from app.comms.registry import get_event_definition
from app.core.config import settings
from app.core.database import SessionLocal


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def parsed_live_topics() -> frozenset[str]:
    """Parse ``COMMS_LIVE_TOPICS`` into a frozenset. Comma-separated,
    whitespace-tolerant, empty by default.
    """
    raw = (settings.comms_live_topics or "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def is_event_live(event_type: str) -> bool:
    """True when this event_type's topic OR category appears in
    ``COMMS_LIVE_TOPICS``. Returns False for unregistered event_types.
    """
    live = parsed_live_topics()
    if not live:
        return False
    definition = get_event_definition(event_type)
    if definition is None:
        return False
    if definition.topic in live:
        return True
    category = TOPIC_TO_CATEGORY.get(definition.topic)
    if category and category in live:
        return True
    return False


def resolve_delivery_mode(event_type: str) -> str | None:
    """Decide whether (and how) to route an event. Live wins over
    shadow; if neither applies, returns ``None`` and no routing runs.
    """
    if is_event_live(event_type):
        return DELIVERY_MODE_LIVE
    if settings.comms_shadow:
        return DELIVERY_MODE_SHADOW
    return None


# ---------------------------------------------------------------------------
# Background routing
# ---------------------------------------------------------------------------


def _route_event_bg(event_id: str, delivery_mode: str) -> None:
    """Background wrapper — opens its own session. Never raises;
    logs any failure so a broken shadow path can't crash the
    scheduling site.
    """
    from app.comms.routing import route_event  # local import — avoids cycle at package load
    db = SessionLocal()
    try:
        event = db.get(CommunicationEvent, event_id)
        if event is None:
            logger.warning(
                "comms rollout: event %s vanished before routing", event_id,
            )
            return
        try:
            route_event(db, event, delivery_mode=delivery_mode)
            db.commit()
        except Exception:
            logger.exception(
                "comms rollout: route_event failed for %s (mode=%s)",
                event_id, delivery_mode,
            )
            db.rollback()
    finally:
        db.close()


def schedule_routing_if_needed(
    background_tasks: BackgroundTasks | None,
    event: CommunicationEvent | None,
    event_type: str,
) -> None:
    """The single call every trigger site makes after ``emit()``.

    * If ``event`` is ``None`` (deduped emit) — no-op.
    * If shadow is off and the topic is not live — no-op.
    * Otherwise schedule ``_route_event_bg`` on the request's
      BackgroundTasks (preferred) or run synchronously if the caller
      is outside a request context.

    Never raises. A routing failure is logged, not propagated —
    shadow mode must never destabilise a domain code path.
    """
    if event is None:
        return
    mode = resolve_delivery_mode(event_type)
    if mode is None:
        return
    if background_tasks is None:
        _route_event_bg(event.id, mode)
        return
    background_tasks.add_task(_route_event_bg, event.id, mode)
