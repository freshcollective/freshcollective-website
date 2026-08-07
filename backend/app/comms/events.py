"""``emit()`` — the single entry point for domain code.

Milestone 1 scope: persist a ``CommunicationEvent`` and return. No
recipient resolution, no preference/consent checks, no rendering, no
delivery. All of those arrive in later milestones behind the same
public surface — callers of ``emit()`` should not need to change when
delivery goes live.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.comms.categories import (
    ALL_SOURCES,
    SOURCE_COLLECTIVE,
    SOURCE_CREATOR,
    SOURCE_FRESH_COLLECTIVE,
    PriorityType,
    SourceType,
)
from app.comms.models import CommunicationEvent
from app.comms.registry import category_for_topic, get_event_definition


log = logging.getLogger(__name__)


class UnknownEventTypeError(ValueError):
    """Raised when ``emit()`` receives an event type not in the registry.

    Registering a type is a deliberate act — silently accepting unknown
    types would let typos pass through and events would never be routed
    correctly. Registration lives in ``app/comms/registry.py``.
    """


class InvalidSourceError(ValueError):
    """Raised when the (source_type, source_id) pair is inconsistent.

    * ``fresh_collective`` sources must have a NULL source_id.
    * ``collective`` and ``creator`` sources must have a non-empty
      source_id.
    """


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def _validate_source(source_type: str, source_id: str | None) -> None:
    if source_type not in ALL_SOURCES:
        raise InvalidSourceError(
            f"Unknown source_type: {source_type!r}. Expected one of {ALL_SOURCES}."
        )
    if source_type == SOURCE_FRESH_COLLECTIVE:
        if source_id is not None:
            raise InvalidSourceError(
                "source_id must be NULL when source_type='fresh_collective'."
            )
    else:  # collective or creator
        if not source_id:
            raise InvalidSourceError(
                f"source_id is required when source_type={source_type!r}."
            )


def emit(
    db: Session,
    *,
    event_type: str,
    source_type: SourceType,
    source_id: str | None = None,
    actor_user_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    priority_hint: PriorityType | None = None,
    occurred_at: datetime | None = None,
) -> CommunicationEvent | None:
    """Persist a communication event.

    Parameters
    ----------
    db
        Active SQLAlchemy session. Emit is transactional with the
        caller's transaction — a rollback in domain code rolls back
        the event, which is the correct behaviour (no event without
        the underlying fact).
    event_type
        Dotted-namespace key. Must be pre-registered in
        ``app/comms/registry.py``. Unknown types raise
        ``UnknownEventTypeError``.
    source_type / source_id
        Communication Source — who this is from. See ``InvalidSourceError``
        for validation rules.
    actor_user_id
        The user who caused the event, if any. NULL for system events.
    subject_type / subject_id
        The object the event is about (post id, booking id, pathway id).
        Optional but usually populated.
    context
        Ambient facts (space_id, collective_id, etc.) — never rendered
        content, only structured facts.
    payload
        Event-type-specific structured data. Never rendered content.
    dedupe_key
        Optional idempotency key scoped to ``event_type``. A second
        emit with the same (event_type, dedupe_key) is a no-op and
        returns ``None``.
    priority_hint
        Override the registry's default pacing for this specific
        emission. Rare; usually the default is correct.
    occurred_at
        Override the timestamp — used when replaying historical events.

    Returns
    -------
    The persisted ``CommunicationEvent`` on success, or ``None`` if a
    duplicate ``dedupe_key`` prevented insertion.
    """
    definition = get_event_definition(event_type)
    if definition is None:
        raise UnknownEventTypeError(
            f"event_type={event_type!r} is not registered. Add it to "
            f"app/comms/registry.py before emitting."
        )

    _validate_source(source_type, source_id)

    topic = definition.topic
    category = category_for_topic(topic)
    resolved_priority: str = priority_hint or definition.default_priority

    event = CommunicationEvent(
        id=_new_event_id(),
        event_type=event_type,
        topic_key=topic,
        category_key=category,
        source_type=source_type,
        source_id=source_id,
        priority_hint=resolved_priority,
        actor_user_id=actor_user_id,
        subject_type=subject_type,
        subject_id=subject_id,
        context=context or {},
        payload=payload or {},
        dedupe_key=dedupe_key,
        occurred_at=occurred_at or datetime.now(UTC).replace(tzinfo=None),
    )

    if dedupe_key is None:
        # Fast path — no idempotency check needed.
        db.add(event)
        db.flush()
        return event

    # Dedupe path — wrap the insert in its own SAVEPOINT so a collision
    # rolls back only this attempt, not the caller's transaction. The
    # partial unique index on (event_type, dedupe_key) WHERE dedupe_key
    # IS NOT NULL enforces at-most-once semantics.
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        log.debug(
            "comms.emit deduped event_type=%s dedupe_key=%s",
            event_type,
            dedupe_key,
        )
        return None

    return event
