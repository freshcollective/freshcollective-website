"""Inbound webhook framework — Milestone 6.

``WebhookProvider`` is a distinct Protocol from ``DeliveryProvider``.
Providers that ship email (``send``) are separate from providers that
receive delivery observations (``verify_webhook`` + ``parse_webhook``).
A single class MAY implement both — Resend does — but nothing forces
send-only providers (in_app, mock, capture) to stub webhook methods
they will never serve.

ARCHITECTURE NOTE — observation, not intent
--------------------------------------------

Every parsed :class:`WebhookEvent` represents a provider's observation
of what happened downstream from us. It is not the same as a user's
definitive action or expressed intent:

  * ``delivered`` = the recipient MTA accepted the handoff, not that
    a person read the message.
  * ``bounced`` = a downstream refused delivery; the recipient may or
    may not know.
  * ``opened`` / ``clicked`` = a tracking pixel or link-wrapper fired;
    unreliable across privacy settings, email clients that block
    tracking, forwarded messages, prefetching bots.
  * ``unsubscribed`` = provider-side evidence of an opt-out signal.
    In M6 we treat this as a suppression signal only; we do not
    infer or mutate consent records from provider payloads. Consent
    remains a member action captured through Fresh Collective's own
    surfaces.

Suppression can trust webhooks (a hard bounce is a durable signal
about the address, not the person). Consent cannot. Any future
change that lets providers influence consent must be an explicit,
reviewed architectural decision — not an incremental extension of
webhook handling.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Mapping, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


# Svix / Resend signature tolerance — reject payloads whose timestamp
# is more than this far from wall clock. Blunts replay of captured
# payloads.
SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60


# ---------------------------------------------------------------------------
# Parsed webhook event shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebhookEvent:
    """One provider observation, decoded from a raw webhook payload.

    ``provider_event_id`` is the provider's own unique id for this
    event (Svix's ``svix-id`` for Resend). Preferred idempotency key —
    when absent, downstream state machines and the suppression helper
    provide effective idempotency.

    ``event_type`` is normalised to Fresh Collective vocabulary:
    ``sent``, ``delivered``, ``bounced``, ``complained``,
    ``unsubscribed``, ``opened``, ``clicked``, ``other``. Providers
    translate their own event names during ``parse_webhook``.

    ``provider_message_id`` correlates to
    ``communication_deliveries.provider_message_id``.

    ``recipient_address`` is present for bounces / complaints /
    unsubscribes so the suppression helper can key off it without
    re-fetching the delivery row.
    """

    provider_event_id: str | None
    event_type: str
    provider_message_id: str | None
    recipient_address: str | None = None
    bounce_class: Literal["hard", "soft"] | None = None
    occurred_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol + registry
# ---------------------------------------------------------------------------


@runtime_checkable
class WebhookProvider(Protocol):
    """A provider that accepts inbound webhooks.

    Distinct from :class:`~app.comms.providers.base.DeliveryProvider`
    so send-only providers do not need to implement (or stub) the
    inbound surface. A single class MAY implement both — Resend does.
    """

    key: str

    def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes,
    ) -> bool: ...

    def parse_webhook(
        self, headers: Mapping[str, str], raw_body: bytes,
    ) -> list[WebhookEvent]: ...


def check_webhook_signature(
    provider: WebhookProvider,
    headers: Mapping[str, str],
    raw_body: bytes,
) -> str:
    """Return one of the ``SIG_*`` constants for a provider's payload.

    R4 introduced this indirection so the FastAPI route can distinguish
    missing-headers (HTTP 400) from bad-signature (HTTP 401) without
    each provider needing to implement a richer protocol method.
    Providers that ship a ``check_webhook`` method get its result;
    everything else falls back to :meth:`WebhookProvider.verify_webhook`
    and reports OK / INVALID (never MISSING_HEADERS).
    """
    checker = getattr(provider, "check_webhook", None)
    if callable(checker):
        return checker(headers, raw_body)
    return SIG_OK if provider.verify_webhook(headers, raw_body) else SIG_INVALID


_WEBHOOK_REGISTRY: dict[str, WebhookProvider] = {}


def register_webhook_provider(provider: WebhookProvider) -> None:
    """Register a webhook provider under its ``key``. Raises on duplicate."""
    if provider.key in _WEBHOOK_REGISTRY:
        raise ValueError(
            f"WebhookProvider {provider.key!r} is already registered."
        )
    _WEBHOOK_REGISTRY[provider.key] = provider


def get_webhook_provider(key: str) -> WebhookProvider | None:
    """Return the registered webhook provider, or None."""
    return _WEBHOOK_REGISTRY.get(key)


def registered_webhook_providers() -> tuple[str, ...]:
    return tuple(sorted(_WEBHOOK_REGISTRY.keys()))


def reset_webhook_registry() -> None:
    """For tests only."""
    _WEBHOOK_REGISTRY.clear()


def _bootstrap_webhook_providers() -> None:
    """Register the built-in webhook providers. Called once at import."""
    from app.comms.providers.resend import ResendProvider
    register_webhook_provider(ResendProvider())


# ---------------------------------------------------------------------------
# Svix (Resend) signature verification — module-level helper so the
# provider's ``verify_webhook`` stays a thin wrapper around ``settings``.
# ---------------------------------------------------------------------------


# R4 — distinguish "no Svix headers at all" (client hit the wrong URL
# or forgot to sign) from "headers present but signature invalid"
# (tampered payload / wrong secret / stale timestamp). The former is
# a 400, the latter is a 401.
SIG_OK = "ok"
SIG_MISSING_HEADERS = "missing_headers"
SIG_INVALID = "invalid"


def check_svix_signature(
    headers: Mapping[str, str],
    raw_body: bytes,
    *,
    secret: str,
    now_ts: int | None = None,
) -> str:
    """Verify a Svix-format signature and return one of
    ``SIG_OK`` / ``SIG_MISSING_HEADERS`` / ``SIG_INVALID``.

    Expects ``svix-id``, ``svix-timestamp``, ``svix-signature`` headers.
    The signature header can carry multiple space-separated
    ``v1,<base64>`` entries; any valid one accepts the payload.

    ``SIG_OK`` requires that a signature matches AND the timestamp is
    within :data:`SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS` of ``now_ts``.
    """
    svix_id = _header(headers, "svix-id")
    svix_ts = _header(headers, "svix-timestamp")
    svix_sig = _header(headers, "svix-signature")
    if not svix_id or not svix_ts or not svix_sig:
        return SIG_MISSING_HEADERS
    try:
        ts = int(svix_ts)
    except (TypeError, ValueError):
        return SIG_INVALID
    now = now_ts if now_ts is not None else int(time.time())
    if abs(now - ts) > SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS:
        return SIG_INVALID

    secret_key = secret
    if secret_key.startswith("whsec_"):
        secret_key = secret_key[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(secret_key)
    except Exception:
        return SIG_INVALID

    to_sign = f"{svix_id}.{svix_ts}.".encode("utf-8") + raw_body
    expected = base64.b64encode(
        hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
    ).decode("ascii")

    for entry in svix_sig.split():
        if "," not in entry:
            continue
        version, candidate = entry.split(",", 1)
        if version != "v1":
            continue
        if hmac.compare_digest(candidate, expected):
            return SIG_OK
    return SIG_INVALID


def verify_svix_signature(
    headers: Mapping[str, str],
    raw_body: bytes,
    *,
    secret: str,
    now_ts: int | None = None,
) -> bool:
    """Boolean-return wrapper around :func:`check_svix_signature`.

    Retained for callers (and tests) that only need "verified or not"
    and don't care whether the failure was missing headers vs bad sig.
    """
    return check_svix_signature(
        headers, raw_body, secret=secret, now_ts=now_ts,
    ) == SIG_OK


def sign_svix_payload(
    *,
    secret: str,
    svix_id: str,
    svix_ts: int,
    raw_body: bytes,
) -> str:
    """Build a valid ``v1,<sig>`` string for a payload. Used by tests
    to produce signatures without a real Resend account.
    """
    secret_key = secret
    if secret_key.startswith("whsec_"):
        secret_key = secret_key[len("whsec_"):]
    secret_bytes = base64.b64decode(secret_key)
    to_sign = f"{svix_id}.{svix_ts}.".encode("utf-8") + raw_body
    sig = base64.b64encode(
        hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
    ).decode("ascii")
    return f"v1,{sig}"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup that tolerates FastAPI's
    Headers proxy plus plain dicts.
    """
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return None


# ---------------------------------------------------------------------------
# Receiver — persist + map
# ---------------------------------------------------------------------------


@dataclass
class ReceiverOutcome:
    provider_key: str
    signature_verified: bool
    persisted_ids: list[str] = field(default_factory=list)
    duplicate_skipped: int = 0
    processed: int = 0
    process_errors: int = 0
    # R4 — populated when the receiver refuses the payload before any
    # audit-ledger write. The route surfaces this as a 4xx HTTP status
    # and MUST NOT persist any state. Values:
    #   "missing_signature_headers"
    #   "invalid_signature"
    #   "malformed_payload"
    # None means the payload was verified and processed (or is a
    # verified event that produced a mapping error, which is a 200 with
    # an audit row — see docstring on receive()).
    rejected_reason: str | None = None


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_webhook_event_id() -> str:
    return f"cwe_{uuid.uuid4().hex[:12]}"


# R4 — event types in scope for the delivery-status pipeline. Any
# other event type from a verified payload is logged at INFO and
# discarded (no audit row, no side effect).
_R4_IN_SCOPE_EVENT_TYPES = frozenset({"delivered", "bounced", "complained"})


def _persist_and_process(
    db: Session,
    *,
    provider_key: str,
    events: list[WebhookEvent],
) -> ReceiverOutcome:
    """Persist each in-scope parsed event to the ledger and run the
    mapping. Only called after signature verification and JSON parse
    have both succeeded — untrusted payloads NEVER reach this path.

    Events whose ``event_type`` is not one of
    ``delivered``, ``bounced``, ``complained`` are dropped with an
    INFO log (R4 scope decision). Nothing about them is persisted.
    """
    from app.comms.models import CommunicationWebhookEvent
    outcome = ReceiverOutcome(
        provider_key=provider_key,
        signature_verified=True,
    )

    for event in events:
        if event.event_type not in _R4_IN_SCOPE_EVENT_TYPES:
            logger.info(
                "comms.webhook.out_of_scope provider=%s event_type=%s "
                "provider_event_id=%s",
                provider_key, event.event_type, event.provider_event_id,
            )
            continue

        row = CommunicationWebhookEvent(
            id=_new_webhook_event_id(),
            provider_key=provider_key,
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            provider_message_id=event.provider_message_id,
            signature_verified=True,
            raw_payload=dict(event.raw),
        )
        # Use a per-row SAVEPOINT so a duplicate-key IntegrityError only
        # rolls back this insert, not prior successful inserts (or the
        # rest of the batch, or, in tests, the outer test transaction).
        sp = db.begin_nested()
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            sp.rollback()
            outcome.duplicate_skipped += 1
            continue
        sp.commit()

        outcome.persisted_ids.append(row.id)
        try:
            _apply_mapping(db, provider_key=provider_key, event=event)
            row.processed_at = _now_naive()
            outcome.processed += 1
        except _MappingError as exc:
            row.process_error = str(exc)
            outcome.process_errors += 1
        except Exception as exc:  # noqa: BLE001 — never crash the receiver
            logger.exception(
                "webhook mapping raised for %s / %s",
                provider_key, event.event_type,
            )
            row.process_error = f"{type(exc).__name__}: {exc}"
            outcome.process_errors += 1
        db.flush()

    db.commit()
    return outcome


class _MappingError(Exception):
    """Recorded as ``process_error``; does not crash the receiver."""


def _apply_mapping(
    db: Session,
    *,
    provider_key: str,
    event: WebhookEvent,
) -> None:
    """Correlate the webhook event to a delivery row (when possible),
    advance the intent state (for delivered / bounced / complained),
    and apply the suppression policy (hard bounce / complained /
    unsubscribed only).

    Raises :class:`_MappingError` for recoverable diagnostics — the
    receiver catches and records them as ``process_error``.
    """
    from app.comms.intents import (
        STATE_BOUNCED,
        STATE_COMPLAINED,
        STATE_DELIVERED,
        mark_intent_state,
    )
    from app.comms.models import CommunicationDelivery, CommunicationIntent
    from app.comms.suppressions import record_suppression

    et = event.event_type

    # R4 — receiver already filtered to delivered/bounced/complained.
    # Suppression policy (hard bounce + complaint) is applied here
    # even if the delivery row is missing, so an address-only signal
    # still protects future sends.
    if event.recipient_address:
        if et == "bounced" and event.bounce_class == "hard":
            record_suppression(
                db, address_type="email",
                address=event.recipient_address,
                reason="bounced", source_provider=provider_key,
            )
        elif et == "complained":
            record_suppression(
                db, address_type="email",
                address=event.recipient_address,
                reason="complained", source_provider=provider_key,
            )

    # State advance requires a delivery match.
    if not event.provider_message_id:
        raise _MappingError(
            "provider_message_id missing from verified in-scope event"
        )

    delivery = db.execute(
        select(CommunicationDelivery).where(
            CommunicationDelivery.provider_key == provider_key,
            CommunicationDelivery.provider_message_id == event.provider_message_id,
        )
    ).scalar_one_or_none()
    if delivery is None:
        raise _MappingError(
            f"no delivery for provider_message_id={event.provider_message_id!r}"
        )

    # Advance intent state via the M4 state machine FIRST. If the
    # transition is illegal (out-of-order: intent already terminal),
    # leave the delivery row untouched so a late `delivered` cannot
    # silently overwrite the earlier `bounced` terminal outcome.
    intent = db.get(CommunicationIntent, delivery.intent_id)
    if intent is None:
        raise _MappingError(f"delivery {delivery.id} has no intent")

    target_state = {
        "delivered": STATE_DELIVERED,
        "bounced": STATE_BOUNCED,
        "complained": STATE_COMPLAINED,
    }[et]
    try:
        mark_intent_state(db, intent, target_state)
    except Exception as exc:
        # Invalid transition (e.g. intent already terminal in a
        # different state). Recorded but not re-raised — the audit row
        # will carry the reason; delivery + intent stay as they were.
        raise _MappingError(
            f"cannot transition intent {intent.id} from {intent.state!r} "
            f"to {target_state!r}: {exc}"
        )

    # State advanced successfully — now mirror the outcome onto the
    # delivery row.
    when = event.occurred_at or _now_naive()
    if when.tzinfo is not None:
        when = when.astimezone(UTC).replace(tzinfo=None)
    delivery.terminal_outcome = et
    delivery.terminal_outcome_at = when
    if et == "bounced" and event.bounce_class in ("hard", "soft"):
        delivery.bounce_class = event.bounce_class


# ---------------------------------------------------------------------------
# Public entry point — used by the FastAPI route
# ---------------------------------------------------------------------------


def receive(
    db: Session,
    *,
    provider_key: str,
    headers: Mapping[str, str],
    raw_body: bytes,
) -> ReceiverOutcome:
    """The FastAPI receiver route calls this after resolving the
    provider. Handles verification, parsing, ledger persistence, and
    mapping in one call. Returns an outcome; the route inspects
    ``rejected_reason`` and translates it into an HTTP 4xx status
    when set.

    R4 — the audit ledger is TRUSTED history only. Missing headers,
    invalid signatures, and malformed bodies are rejected before any
    persistence happens (route returns 4xx). Only verified, parseable,
    in-scope events land in ``communication_webhook_events``.
    """
    provider = get_webhook_provider(provider_key)
    if provider is None:
        # Should be caught by the route earlier, but belt-and-braces.
        return ReceiverOutcome(
            provider_key=provider_key,
            signature_verified=False,
            rejected_reason="unknown_provider",
        )

    # 1. Signature check — distinguish missing headers from bad signature.
    sig_status = check_webhook_signature(provider, headers, raw_body)
    if sig_status == SIG_MISSING_HEADERS:
        logger.warning(
            "comms.webhook.rejected reason=missing_signature_headers "
            "provider=%s",
            provider_key,
        )
        return ReceiverOutcome(
            provider_key=provider_key,
            signature_verified=False,
            rejected_reason="missing_signature_headers",
        )
    if sig_status != SIG_OK:
        logger.warning(
            "comms.webhook.rejected reason=invalid_signature "
            "provider=%s",
            provider_key,
        )
        return ReceiverOutcome(
            provider_key=provider_key,
            signature_verified=False,
            rejected_reason="invalid_signature",
        )

    # 2. Body parse — malformed JSON is a client bug, reject with 400.
    try:
        json.loads(raw_body.decode("utf-8"))
    except Exception:
        logger.warning(
            "comms.webhook.rejected reason=malformed_payload "
            "provider=%s bytes=%d",
            provider_key, len(raw_body),
        )
        return ReceiverOutcome(
            provider_key=provider_key,
            signature_verified=True,
            rejected_reason="malformed_payload",
        )

    # 3. Provider-specific parse — verified body decoded but doesn't
    #    match the provider's schema. Treat as malformed_payload so
    #    the sender knows the shape is wrong.
    events = provider.parse_webhook(headers, raw_body)
    if not events:
        logger.warning(
            "comms.webhook.rejected reason=malformed_payload "
            "provider=%s parse=empty",
            provider_key,
        )
        return ReceiverOutcome(
            provider_key=provider_key,
            signature_verified=True,
            rejected_reason="malformed_payload",
        )

    # 4. Persist + map only the in-scope events. Everything else logs
    #    at INFO and is dropped inside _persist_and_process.
    return _persist_and_process(
        db,
        provider_key=provider_key,
        events=events,
    )
