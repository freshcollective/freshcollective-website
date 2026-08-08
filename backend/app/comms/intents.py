"""Intent + delivery helpers (Milestone 4).

Public entry points:

* :func:`create_intent` — build one intent from the caller-supplied
  rendered payload + provenance. Callers own the payload; M5's
  routing layer will call this once per (event × recipient × channel)
  after applying preference / consent / suppression checks.
* :func:`claim_next_batch` — atomic worker claim; moves intents from
  ``queued`` to ``dispatching`` and returns their ids.
* :func:`mark_intent_state` — safe state transition with validation.
* :func:`record_delivery` — insert a delivery attempt row.

State machine transitions
-------------------------

    queued        → dispatching | suppressed
    dispatching   → sent | failed
    sent          → delivered | bounced | complained
    (terminal)    → —

Invalid transitions raise :class:`InvalidStateTransitionError` so bugs
surface at call sites rather than corrupting the audit trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.comms.categories import (
    ALL_CATEGORIES,
    ALL_CHANNELS,
    ALL_PRIORITIES,
    ALL_SOURCES,
    ALL_TOPICS,
    PRIORITY_SILENT,
    SOURCE_FRESH_COLLECTIVE,
)
from app.comms.models import (
    CommunicationDelivery,
    CommunicationIntent,
)


# ---------------------------------------------------------------------------
# State constants + transition table
# ---------------------------------------------------------------------------

STATE_QUEUED = "queued"
STATE_DISPATCHING = "dispatching"
STATE_SENT = "sent"
STATE_DELIVERED = "delivered"
STATE_BOUNCED = "bounced"
STATE_COMPLAINED = "complained"
STATE_FAILED = "failed"
STATE_SUPPRESSED = "suppressed"
STATE_RECORDED = "recorded"

ALL_STATES = (
    STATE_QUEUED,
    STATE_DISPATCHING,
    STATE_SENT,
    STATE_DELIVERED,
    STATE_BOUNCED,
    STATE_COMPLAINED,
    STATE_FAILED,
    STATE_SUPPRESSED,
    STATE_RECORDED,
)

TERMINAL_STATES = frozenset({
    STATE_DELIVERED,
    STATE_BOUNCED,
    STATE_COMPLAINED,
    STATE_FAILED,
    STATE_SUPPRESSED,
    STATE_RECORDED,
})

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_QUEUED:      frozenset({STATE_DISPATCHING, STATE_SUPPRESSED}),
    STATE_DISPATCHING: frozenset({STATE_SENT, STATE_FAILED}),
    STATE_SENT:        frozenset({STATE_DELIVERED, STATE_BOUNCED, STATE_COMPLAINED}),
    # Terminal states — no outgoing transitions.
    STATE_DELIVERED:   frozenset(),
    STATE_BOUNCED:     frozenset(),
    STATE_COMPLAINED:  frozenset(),
    STATE_FAILED:      frozenset(),
    STATE_SUPPRESSED:  frozenset(),
    STATE_RECORDED:    frozenset(),
}


DELIVERY_STATUS_PENDING = "pending"
DELIVERY_STATUS_ACCEPTED = "accepted"
DELIVERY_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnknownStateError(ValueError):
    """State value is not a member of the intent state enum."""


class InvalidStateTransitionError(ValueError):
    """The requested state transition is not permitted from the current state."""


class InvalidIntentError(ValueError):
    """The intent fields fail a domain invariant (e.g. unknown category)."""


class InvalidSourceError(ValueError):
    """Source type / id combination is inconsistent (mirrors emit()'s check)."""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_intent_id() -> str:
    return f"cin_{uuid.uuid4().hex[:12]}"


def _new_delivery_id() -> str:
    return f"cde_{uuid.uuid4().hex[:12]}"


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
    else:
        if not source_id:
            raise InvalidSourceError(
                f"source_id is required when source_type={source_type!r}."
            )


# ---------------------------------------------------------------------------
# create_intent
# ---------------------------------------------------------------------------


def create_intent(
    db: Session,
    *,
    recipient_user_id: str | None,
    recipient_address: str,
    source_type: str,
    source_id: str | None,
    category_key: str,
    topic_key: str,
    channel: str,
    priority: str,
    provider_key: str,
    human_reason: str,
    payload_subject: str,
    event_id: str | None = None,
    template_key: str | None = None,
    template_version: str | None = None,
    template_context: dict[str, Any] | None = None,
    payload_body_html: str | None = None,
    payload_body_text: str | None = None,
    payload_metadata: dict[str, Any] | None = None,
    scheduled_for: datetime | None = None,
) -> CommunicationIntent:
    """Create + persist a single intent.

    Initial state:

    * ``recorded`` when ``priority == silent`` — the intent exists for
      history / audit and is never picked up by the worker.
    * ``queued`` otherwise. ``queued_at`` is set at creation.

    All validation is field-shape only. Whether this recipient
    *should* receive this is upstream: the M5 routing / decision
    layer runs preference / consent / suppression checks before
    calling this helper. Duplicate protection (one intent per event
    × recipient × channel) is enforced by the DB partial unique
    index — an IntegrityError from this function is a signal the
    caller has re-emitted.
    """
    if category_key not in ALL_CATEGORIES:
        raise InvalidIntentError(f"Unknown category_key: {category_key!r}")
    if topic_key not in ALL_TOPICS:
        raise InvalidIntentError(f"Unknown topic_key: {topic_key!r}")
    if channel not in ALL_CHANNELS:
        raise InvalidIntentError(f"Unknown channel: {channel!r}")
    if priority not in ALL_PRIORITIES:
        raise InvalidIntentError(f"Unknown priority: {priority!r}")
    _validate_source(source_type, source_id)
    if not recipient_address:
        raise InvalidIntentError("recipient_address is required (empty string received).")
    if not human_reason:
        raise InvalidIntentError("human_reason is required.")
    if not provider_key:
        raise InvalidIntentError("provider_key is required.")
    if not payload_body_html and not payload_body_text:
        raise InvalidIntentError(
            "At least one of payload_body_html or payload_body_text is required."
        )

    now = _now_naive()
    is_silent = priority == PRIORITY_SILENT
    initial_state = STATE_RECORDED if is_silent else STATE_QUEUED

    intent = CommunicationIntent(
        id=_new_intent_id(),
        event_id=event_id,
        recipient_user_id=recipient_user_id,
        recipient_address=recipient_address,
        source_type=source_type,
        source_id=source_id,
        category_key=category_key,
        topic_key=topic_key,
        channel=channel,
        priority=priority,
        provider_key=provider_key,
        template_key=template_key,
        template_version=template_version,
        template_context=template_context,
        human_reason=human_reason,
        payload_subject=payload_subject,
        payload_body_html=payload_body_html,
        payload_body_text=payload_body_text,
        payload_metadata=payload_metadata or {},
        scheduled_for=scheduled_for,
        state=initial_state,
        created_at=now,
        queued_at=None if is_silent else now,
        terminal_at=now if is_silent else None,
    )
    db.add(intent)
    db.flush()
    return intent


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def mark_intent_state(
    db: Session,
    intent: CommunicationIntent,
    new_state: str,
    *,
    suppression_reason: str | None = None,
) -> CommunicationIntent:
    """Transition an intent's state, enforcing the state machine.

    Sets the appropriate timestamp columns (``dispatching_at``,
    ``sent_at``, ``terminal_at``) as a side effect so time-in-state
    is always queryable.

    Raises :class:`UnknownStateError` for unknown states and
    :class:`InvalidStateTransitionError` for illegal transitions.
    Passing the current state as ``new_state`` is a no-op.
    """
    if new_state not in ALL_STATES:
        raise UnknownStateError(f"Unknown state: {new_state!r}")
    if new_state == intent.state:
        return intent
    allowed = VALID_TRANSITIONS.get(intent.state, frozenset())
    if new_state not in allowed:
        raise InvalidStateTransitionError(
            f"Cannot transition intent {intent.id} from {intent.state!r} "
            f"to {new_state!r}. Allowed from {intent.state!r}: "
            f"{sorted(allowed)}"
        )

    now = _now_naive()
    intent.state = new_state
    if new_state == STATE_DISPATCHING:
        intent.dispatching_at = now
    elif new_state == STATE_SENT:
        intent.sent_at = now
    if new_state in TERMINAL_STATES:
        intent.terminal_at = now
        if new_state == STATE_SUPPRESSED and suppression_reason:
            intent.suppression_reason = suppression_reason
    db.flush()
    return intent


# ---------------------------------------------------------------------------
# Worker claim
# ---------------------------------------------------------------------------


def claim_next_batch(
    db: Session,
    *,
    limit: int = 50,
    now: datetime | None = None,
) -> list[str]:
    """Atomically claim up to ``limit`` queued intents whose
    ``scheduled_for`` is due (NULL counts as due).

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent workers
    partition the queue without contention. Marks each claimed row
    ``dispatching`` and sets ``dispatching_at`` in a single UPDATE.
    Returns the claimed ids in creation order.

    The caller is expected to ``commit`` immediately after this
    function returns so the claim is visible and other workers /
    admin surfaces see the intents in ``dispatching`` state before
    the send is attempted. Recovery for intents stuck in
    ``dispatching`` beyond a threshold is future work (M5+).
    """
    check_at = now or _now_naive()
    # FOR UPDATE SKIP LOCKED is Postgres-specific. Emitted as text so
    # SQLAlchemy doesn't try to rewrite it under a different dialect.
    rows = db.execute(
        text(
            """
            SELECT id
              FROM communication_intents
             WHERE state = 'queued'
               AND (scheduled_for IS NULL OR scheduled_for <= :check_at)
             ORDER BY created_at
             LIMIT :limit
               FOR UPDATE SKIP LOCKED
            """
        ),
        {"check_at": check_at, "limit": limit},
    ).all()
    ids: list[str] = [r[0] for r in rows]
    if not ids:
        return []

    db.execute(
        update(CommunicationIntent)
        .where(CommunicationIntent.id.in_(ids))
        .values(state=STATE_DISPATCHING, dispatching_at=check_at)
    )
    db.flush()
    return ids


# ---------------------------------------------------------------------------
# Delivery record
# ---------------------------------------------------------------------------


def record_delivery(
    db: Session,
    *,
    intent: CommunicationIntent,
    provider_key: str,
    status: str,
    request_snapshot: dict[str, Any],
    response_snapshot: dict[str, Any],
    provider_message_id: str | None = None,
    error_class: str | None = None,
    error_detail: str | None = None,
) -> CommunicationDelivery:
    """Insert a delivery attempt row against an intent.

    ``attempt_number`` is derived from the number of existing rows +
    1, so the caller doesn't have to track retries. Concurrent
    attempt inserts against the same intent would violate the
    ``uq_comm_delivery_intent_attempt`` constraint — that's
    intentional protection against double-dispatch.
    """
    if status not in (
        DELIVERY_STATUS_PENDING,
        DELIVERY_STATUS_ACCEPTED,
        DELIVERY_STATUS_FAILED,
    ):
        raise ValueError(f"Unknown delivery status: {status!r}")

    prior = db.execute(
        select(CommunicationDelivery.attempt_number).where(
            CommunicationDelivery.intent_id == intent.id,
        )
    ).scalars().all()
    next_attempt = max(prior, default=0) + 1

    now = _now_naive()
    settled = None if status == DELIVERY_STATUS_PENDING else now

    row = CommunicationDelivery(
        id=_new_delivery_id(),
        intent_id=intent.id,
        provider_key=provider_key,
        attempt_number=next_attempt,
        status=status,
        provider_message_id=provider_message_id,
        request_snapshot=request_snapshot,
        response_snapshot=response_snapshot,
        error_class=error_class,
        error_detail=error_detail,
        attempted_at=now,
        settled_at=settled,
    )
    db.add(row)
    db.flush()
    return row
