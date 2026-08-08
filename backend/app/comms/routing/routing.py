"""Top-level ``route_event`` orchestration.

Given a persisted :class:`CommunicationEvent`, look up the registered
resolver, iterate its recipients × the category's supported channels,
run the decision pipeline for each pair, and return a summary.

M5b invariant: ``route_event`` never commits or dispatches. It
creates rows (intents, digest items) via the helpers, but the
caller owns the transaction boundary. In tests this lets a single
``db`` fixture drive an end-to-end assertion; in M5c the emit-site
wiring will invoke ``route_event`` and commit alongside the
originating write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.comms.intents import DELIVERY_MODE_LIVE, DELIVERY_MODE_SHADOW
from app.comms.models import CommunicationEvent
from app.comms.routing.decision import DecisionOutcome, process_one
from app.comms.routing.provider_map import supported_channels_for_category
from app.comms.routing.resolver import get_resolver_for


@dataclass
class RoutingResult:
    """Summary of what :func:`route_event` produced. Useful for tests,
    admin surfaces (M5c), and future observability.
    """

    event_id: str
    event_type: str
    delivery_mode: str
    intent_ids: list[str] = field(default_factory=list)
    digest_item_ids: list[str] = field(default_factory=list)
    suppressed_intent_ids: list[str] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_intents_created(self) -> int:
        return len(self.intent_ids) + len(self.suppressed_intent_ids)

    @property
    def had_resolver(self) -> bool:
        return not any(
            s.get("reason") == "no_resolver_registered" for s in self.skipped
        )


def route_event(
    db: Session,
    event: CommunicationEvent,
    *,
    delivery_mode: str = DELIVERY_MODE_SHADOW,
    now: datetime | None = None,
) -> RoutingResult:
    """Run routing for a single event.

    Default ``delivery_mode='shadow'`` — production runtimes get
    shadow-only behaviour unless the caller (M5c) explicitly asks
    for live. Tests exercise both modes.

    Never commits. Returns a :class:`RoutingResult` summarising what
    was created / skipped / suppressed.
    """
    if delivery_mode not in (DELIVERY_MODE_SHADOW, DELIVERY_MODE_LIVE):
        raise ValueError(
            f"Unknown delivery_mode: {delivery_mode!r}. "
            f"Expected 'shadow' or 'live'."
        )

    result = RoutingResult(
        event_id=event.id,
        event_type=event.event_type,
        delivery_mode=delivery_mode,
    )

    resolver = get_resolver_for(event.event_type)
    if resolver is None:
        result.skipped.append({
            "reason": "no_resolver_registered",
            "event_type": event.event_type,
        })
        return result

    recipients = resolver.resolve(db, event)
    channels = supported_channels_for_category(event.category_key)

    for recipient in recipients:
        for channel in channels:
            outcome: DecisionOutcome = process_one(
                db,
                event=event,
                recipient=recipient,
                channel=channel,
                delivery_mode=delivery_mode,
                now=now,
            )
            _absorb(result, outcome, recipient_user_id=recipient.user_id)

    return result


def _absorb(
    result: RoutingResult,
    outcome: DecisionOutcome,
    *,
    recipient_user_id: str,
) -> None:
    if outcome.digest_item_id:
        result.digest_item_ids.append(outcome.digest_item_id)
        return
    if outcome.intent_id and outcome.suppression_reason:
        result.suppressed_intent_ids.append(outcome.intent_id)
        return
    if outcome.intent_id:
        result.intent_ids.append(outcome.intent_id)
        return
    if outcome.skipped_reason:
        result.skipped.append({
            "reason": outcome.skipped_reason,
            "channel": outcome.channel,
            "recipient_user_id": recipient_user_id,
        })
