"""Per-recipient-per-channel decision pipeline.

Every call to :func:`process_one` runs the same sequence:

    1. Effective preference    → silent shortcut
    2. Consent check           → suppressed if consent-gated and missing
    3. Suppression check       → suppressed if address is blocked
    4. Priority resolution     → may downgrade to digest (rate limit)
    5. Digest branch           → insert digest item, done
    6. Quiet-hours evaluation  → may set scheduled_for
    7. Provider selection      → suppressed if no provider mapped
    8. Template render         → skip if no template registered
    9. Intent creation         → dedupe collision → skip

Every outcome is captured in a :class:`DecisionOutcome` for the
caller (the router) to summarise. This layer does not commit — the
caller owns the transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.comms.categories import (
    CATEGORY_CREATOR_UPDATES,
    CATEGORY_PLATFORM_UPDATES,
    CHANNEL_EMAIL_MARKETING,
    CHANNEL_EMAIL_TRANSACTIONAL,
    PRIORITY_IMMEDIATE,
    PRIORITY_SILENT,
)
from app.comms.digest import insert_digest_item
from app.comms.intents import (
    STATE_SUPPRESSED,
    create_intent,
    mark_intent_state,
)
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.preferences import (
    UnsupportedChannelError,
    get_effective_preference,
)
from app.comms.preferences import get_consent_state
from app.comms.routing.pacing import (
    evaluate_quiet_hours,
    resolve_priority,
    should_route_to_digest,
)
from app.comms.routing.provider_map import get_provider_for
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.suppressions import is_address_suppressed


# (category, channel) → consent kind required. Missing → not gated.
# The M5b live rules:
#   * All creator_updates channels require creator_broadcast consent.
#   * platform_updates × email_marketing requires marketing consent
#     (channel not routed until M11 but the gate is defined for
#     future-safety).
CONSENT_GATES: dict[tuple[str, str], str] = {
    (CATEGORY_CREATOR_UPDATES,  "in_app"):                     "creator_broadcast",
    (CATEGORY_CREATOR_UPDATES,  CHANNEL_EMAIL_TRANSACTIONAL): "creator_broadcast",
    (CATEGORY_PLATFORM_UPDATES, CHANNEL_EMAIL_MARKETING):     "marketing",
}


@dataclass
class DecisionOutcome:
    """What the decision pipeline produced for one (event × recipient
    × channel). Exactly one of ``intent_id``, ``digest_item_id``, or
    ``skipped_reason`` is non-None. When a suppressed intent is
    created (which itself is a form of "not delivered") the outcome
    carries both ``intent_id`` and ``suppression_reason``.
    """

    channel: str
    intent_id: str | None = None
    digest_item_id: str | None = None
    skipped_reason: str | None = None
    suppression_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _resolve_address(recipient: ResolvedRecipient, db: Session) -> str | None:
    """Recipient address for the payload. Uses the resolver's override
    when supplied; otherwise looks up ``users.email``.
    """
    if recipient.recipient_address_override:
        return recipient.recipient_address_override
    from app.models.user import User  # local import — avoid heavy import at module load
    user = db.get(User, recipient.user_id)
    if user is None or not user.email:
        return None
    return user.email


def _create_suppressed_intent(
    db: Session,
    *,
    event: CommunicationEvent,
    recipient: ResolvedRecipient,
    address: str,
    channel: str,
    priority: str,
    delivery_mode: str,
    reason: str,
    detail: str | None = None,
) -> CommunicationIntent | None:
    """Intents created in suppressed state carry ``priority`` = the
    priority that would have been used, and their state is transitioned
    immediately to ``suppressed`` with the reason recorded.
    """
    # Suppressed intents still need a subject + body so the model's
    # NOT NULL constraint is respected. Use the human_reason itself
    # as the placeholder subject; no rendering happened, no template.
    try:
        intent = create_intent(
            db,
            event_id=event.id,
            recipient_user_id=recipient.user_id,
            recipient_address=address,
            source_type=event.source_type,
            source_id=event.source_id,
            category_key=event.category_key,
            topic_key=event.topic_key,
            channel=channel,
            priority=priority if priority != PRIORITY_SILENT else PRIORITY_IMMEDIATE,
            provider_key="none",
            human_reason=recipient.human_reason,
            payload_subject="(suppressed — not rendered)",
            payload_body_text=f"Suppressed at decision time. Reason: {reason}.",
            delivery_mode=delivery_mode,
        )
    except IntegrityError:
        db.rollback()
        return None
    mark_intent_state(db, intent, STATE_SUPPRESSED, suppression_reason=reason)
    return intent


def process_one(
    db: Session,
    *,
    event: CommunicationEvent,
    recipient: ResolvedRecipient,
    channel: str,
    delivery_mode: str,
    now: datetime | None = None,
) -> DecisionOutcome:
    category = event.category_key
    address = _resolve_address(recipient, db)

    # ── 1. Effective preference ──────────────────────────────────────
    try:
        pref_priority, is_locked, _origin = get_effective_preference(
            db,
            user_id=recipient.user_id,
            category_key=category,
            channel=channel,
        )
    except UnsupportedChannelError:
        # Channel not offered for this category → do nothing at all.
        # No intent, no digest item, no skip reason worth recording.
        return DecisionOutcome(
            channel=channel,
            skipped_reason="channel_not_supported_by_category",
        )

    if pref_priority == PRIORITY_SILENT and not is_locked:
        # Member has silenced this — create a silent recorded intent
        # so history shows we noticed the event even though nothing
        # was sent.
        if address is None:
            return DecisionOutcome(channel=channel, skipped_reason="no_recipient_address")
        try:
            intent = create_intent(
                db,
                event_id=event.id,
                recipient_user_id=recipient.user_id,
                recipient_address=address,
                source_type=event.source_type,
                source_id=event.source_id,
                category_key=event.category_key,
                topic_key=event.topic_key,
                channel=channel,
                priority=PRIORITY_SILENT,
                provider_key="none",
                human_reason=recipient.human_reason,
                payload_subject="(silent — not rendered)",
                payload_body_text="Silent per member preference.",
                delivery_mode=delivery_mode,
            )
        except IntegrityError:
            db.rollback()
            return DecisionOutcome(channel=channel, skipped_reason="duplicate_intent")
        return DecisionOutcome(channel=channel, intent_id=intent.id)

    if address is None:
        return DecisionOutcome(channel=channel, skipped_reason="no_recipient_address")

    # ── 2. Consent check ─────────────────────────────────────────────
    required_consent = CONSENT_GATES.get((category, channel))
    if required_consent is not None:
        latest = get_consent_state(
            db, user_id=recipient.user_id, consent_kind=required_consent,
        )
        if latest is None or latest.state != "granted":
            supp = _create_suppressed_intent(
                db,
                event=event, recipient=recipient, address=address,
                channel=channel, priority=pref_priority,
                delivery_mode=delivery_mode,
                reason="no_consent",
            )
            return DecisionOutcome(
                channel=channel,
                intent_id=supp.id if supp else None,
                suppression_reason="no_consent",
                detail={"consent_kind": required_consent},
            )

    # ── 3. Suppression check ─────────────────────────────────────────
    if channel in (CHANNEL_EMAIL_TRANSACTIONAL, CHANNEL_EMAIL_MARKETING):
        supp_row = is_address_suppressed(
            db, address_type="email", address=address,
        )
        if supp_row is not None:
            supp = _create_suppressed_intent(
                db,
                event=event, recipient=recipient, address=address,
                channel=channel, priority=pref_priority,
                delivery_mode=delivery_mode,
                reason=supp_row.reason,
            )
            return DecisionOutcome(
                channel=channel,
                intent_id=supp.id if supp else None,
                suppression_reason=supp_row.reason,
            )

    # ── 4. Priority resolution + rate limit ─────────────────────────
    final_priority = resolve_priority(
        db,
        user_id=recipient.user_id,
        category_key=category,
        channel=channel,
        preferred_priority=pref_priority,
        delivery_mode=delivery_mode,
        now=now,
    )

    # ── 5. Digest branch ─────────────────────────────────────────────
    if should_route_to_digest(final_priority):
        cadence = "daily" if final_priority == "daily_digest" else "weekly"
        item = insert_digest_item(
            db,
            user_id=recipient.user_id,
            category_key=category,
            cadence=cadence,
            source_type=event.source_type,
            source_id=event.source_id,
            human_reason=recipient.human_reason,
            item_payload={
                "event_id": event.id,
                "event_type": event.event_type,
                "template_context": recipient.template_context,
                # Structured summary the M13 digest renderer will use.
                # Kept small — the digest renderer can re-fetch details
                # from the event / subject if needed.
                "payload": dict(event.payload or {}),
            },
            event_id=event.id,
            now=now,
        )
        return DecisionOutcome(channel=channel, digest_item_id=item.id)

    # ── 6. Quiet hours (immediate email/push only) ───────────────────
    scheduled_for: datetime | None = None
    if final_priority == PRIORITY_IMMEDIATE:
        qh = evaluate_quiet_hours(
            db, user_id=recipient.user_id, channel=channel, now=now,
        )
        if qh.in_quiet_hours:
            scheduled_for = qh.scheduled_for_utc

    # ── 7. Provider selection ────────────────────────────────────────
    provider_key = get_provider_for(category, channel)
    if provider_key is None:
        supp = _create_suppressed_intent(
            db,
            event=event, recipient=recipient, address=address,
            channel=channel, priority=final_priority,
            delivery_mode=delivery_mode,
            reason="no_provider_configured",
        )
        return DecisionOutcome(
            channel=channel,
            intent_id=supp.id if supp else None,
            suppression_reason="no_provider_configured",
        )

    # ── 8. Template render ───────────────────────────────────────────
    from app.comms.templates import get_template_for  # local — avoid cycle
    template = get_template_for(event.event_type, channel)
    if template is None:
        return DecisionOutcome(
            channel=channel, skipped_reason="no_template_registered",
        )
    payload = template.render(db, event, recipient)

    # ── 9. Intent creation (dedupe via DB partial unique) ────────────
    try:
        intent = create_intent(
            db,
            event_id=event.id,
            recipient_user_id=recipient.user_id,
            recipient_address=address,
            source_type=event.source_type,
            source_id=event.source_id,
            category_key=event.category_key,
            topic_key=event.topic_key,
            channel=channel,
            priority=final_priority,
            provider_key=provider_key,
            template_key=template.key,
            template_version=template.version,
            template_context=dict(recipient.template_context or {}),
            human_reason=recipient.human_reason,
            payload_subject=payload.subject,
            payload_body_html=payload.body_html,
            payload_body_text=payload.body_text,
            payload_metadata=dict(payload.metadata or {}),
            scheduled_for=scheduled_for,
            delivery_mode=delivery_mode,
        )
    except IntegrityError:
        db.rollback()
        return DecisionOutcome(channel=channel, skipped_reason="duplicate_intent")

    return DecisionOutcome(channel=channel, intent_id=intent.id)
