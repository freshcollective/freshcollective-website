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

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.comms.intents import DELIVERY_MODE_LIVE, DELIVERY_MODE_SHADOW
from app.comms.models import CommunicationEvent
from app.comms.routing.decision import DecisionOutcome, process_one
from app.comms.routing.provider_map import supported_channels_for_category
from app.comms.routing.resolver import ResolvedRecipient, get_resolver_for


logger = logging.getLogger(__name__)


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
        # Surface this loudly rather than silently. An emit reaching
        # routing without a resolver means either (a) a new event type
        # was emitted before its resolver landed, or (b) the routing
        # registry failed to bootstrap. Both are worth an operator's
        # attention.
        logger.warning(
            "comms routing: no resolver registered for event_type=%s "
            "(event_id=%s, delivery_mode=%s) — routing skipped",
            event.event_type, event.id, delivery_mode,
        )
        result.skipped.append({
            "reason": "no_resolver_registered",
            "event_type": event.event_type,
        })
        return result

    recipients = [
        _canonicalise_recipient_links(r) for r in resolver.resolve(db, event)
    ]
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


def _canonicalise_recipient_links(
    recipient: "ResolvedRecipient",
) -> "ResolvedRecipient":
    """Move any non-public origin in the template context onto the
    public address, before anything is rendered.

    Why this is here rather than in the stored event
    ------------------------------------------------
    ``CommunicationEvent`` is "an immutable record that something
    communication-worthy happened", and its ``payload`` is documented as
    "structured facts … never rendered content". Absolute URLs were put
    in payloads anyway, and a batch of historical events consequently
    carries the old Render origin. Editing them would make the ledger
    say something other than what happened, for a cosmetic reason.

    So the origin is corrected on the way *out* instead. An old event
    re-routed today produces a link on today's public domain while its
    record keeps saying what it said. The same applies to the next time
    the public address changes: nothing needs a migration.

    ``route_event`` is the single funnel every emit passes through, and
    ``template_context`` is the only channel event data has into a
    template — no template reads ``event.payload`` directly. One place
    covers every event type, every resolver and both channels.

    External links are untouched: the rewrite fires only on a host
    carrying a non-public marker, so a Stripe or Resend URL passes
    through, and relative in-app paths have no origin to correct.
    """
    context = recipient.template_context
    if not context:
        return recipient

    from app.core.public_url import public_app_url
    from app.core.url_policy import canonicalise_origin

    public_base = public_app_url()
    corrected: dict[str, Any] = {}
    changed = False
    for key, value in context.items():
        if isinstance(value, str):
            moved = canonicalise_origin(value, public_base)
            if moved != value:
                changed = True
                logger.info(
                    "comms routing: canonicalised %s for recipient %s",
                    key, recipient.user_id,
                )
            corrected[key] = moved
        else:
            corrected[key] = value

    if not changed:
        return recipient
    return replace(recipient, template_context=corrected)


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
