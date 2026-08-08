"""Delivery worker (Milestone 4).

Given a queue of intents, claim a batch, dispatch each through its
configured provider, record the delivery attempt, and transition the
intent state. The worker is a pure pass-through in M4 — no routing
rules, no preference/consent checks, no rendering. Those upstream
concerns live in the M5 decision layer.

Two public entry points:

* :func:`dispatch_due` — takes an existing session; used by tests
  and by the internal cron endpoint.
* :func:`dispatch_due_from_pool` — opens its own session; used by
  scheduled runs.

Dispatch flow per intent (:func:`_dispatch_one`):

    1. Load intent + build RenderedPayload from stored snapshot.
    2. Look up provider by key.
    3. Try ``provider.send(payload)``. Any exception is caught and
       turned into a rejected ProviderResult.
    4. Record delivery row + transition intent state.
    5. Commit.

The claim (state=queued → dispatching) commits *before* the send so
a worker crash between the claim and the delivery record leaves the
intent visibly in ``dispatching``. A future recovery job will detect
stale ``dispatching`` rows and either retry or mark failed.

ARCHITECTURE NOTE — ambiguous dispatching intents
--------------------------------------------------

The multi-transaction dispatch pattern introduces a specific class of
ambiguous state that MUST be resolved before real production
communications begin flowing through this pipeline:

    If a worker crashes AFTER the provider accepts a delivery but
    BEFORE the delivery-row insert / intent-state-update transaction
    commits, the intent stays in ``dispatching`` with no delivery row
    — yet the recipient has (or is imminently going to) receive the
    message. A naive recovery process that retries every stuck
    ``dispatching`` intent would create duplicate communications.

Any future stuck-dispatching recovery process therefore MUST NOT
automatically resend such an intent until idempotency and
reconciliation semantics are defined. Requirements to satisfy before
real production delivery / cutover:

  1. Idempotency key. An idempotency identifier must be attached to
     the request handed to the provider so the provider (or a
     later inbound webhook) can be interrogated to determine whether
     a message with that key was actually accepted. Providers vary
     in what they support natively — Resend accepts an
     ``Idempotency-Key`` header, MailerLite treats subscriber
     operations as idempotent per email, etc. The chosen key should
     be stable across retries of the same intent.
  2. Reconciliation-before-retry. The recovery process MUST
     reconcile against provider records (webhook feedback matched
     via ``provider_message_id``, or a provider-side lookup by
     idempotency key) BEFORE deciding whether to retry, mark
     ``failed``, or mark ``sent``. It must never blindly re-invoke
     ``provider.send()`` on a stuck intent.
  3. Fail-closed default. Absent reconciliation evidence, the safest
     default is to mark the intent as ``failed`` with a specific
     ``error_class`` such as ``dispatching_unresolved`` and surface
     for operator review, rather than auto-retry.

M4 does not implement recovery because no production traffic reaches
this pipeline yet — every emit still flows through the legacy
notification/email code path. This requirement is scheduled to land
before M5's shadow rollout enables real routing to attempt real
sends.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.comms.intents import (
    DELIVERY_STATUS_ACCEPTED,
    DELIVERY_STATUS_FAILED,
    STATE_FAILED,
    STATE_SENT,
    claim_next_batch,
    mark_intent_state,
    record_delivery,
)
from app.comms.models import CommunicationIntent
from app.comms.providers import get as get_provider
from app.comms.providers.base import ProviderResult, RenderedPayload
from app.core.database import SessionLocal


logger = logging.getLogger(__name__)


def _payload_from_intent(intent: CommunicationIntent) -> RenderedPayload:
    """Rebuild the RenderedPayload that was stored on the intent at
    creation time.
    """
    return RenderedPayload(
        to=intent.recipient_address,
        subject=intent.payload_subject,
        body_html=intent.payload_body_html,
        body_text=intent.payload_body_text,
        reply_to=None,  # M4 doesn't persist reply_to on intents
        metadata=dict(intent.payload_metadata or {}),
    )


def _request_snapshot(payload: RenderedPayload) -> dict[str, Any]:
    return {
        "to": payload.to,
        "subject": payload.subject,
        "body_html": payload.body_html,
        "body_text": payload.body_text,
        "reply_to": payload.reply_to,
        "metadata": dict(payload.metadata),
    }


def _response_snapshot(result: ProviderResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "provider_message_id": result.provider_message_id,
        "error_class": result.error_class,
        "error_detail": result.error_detail,
    }


def _dispatch_one(db: Session, intent: CommunicationIntent) -> None:
    """Attempt one delivery against one intent already in state
    ``dispatching``. Records a delivery row and transitions state.
    Never raises — provider failures become ``failed`` transitions
    with the error captured on the delivery row.
    """
    payload = _payload_from_intent(intent)
    request_snap = _request_snapshot(payload)

    try:
        provider = get_provider(intent.provider_key)
    except KeyError as exc:
        # No such provider registered. The intent can never succeed
        # in this runtime; mark it failed with a clear reason.
        logger.error(
            "Intent %s references unknown provider %r — marking failed.",
            intent.id, intent.provider_key,
        )
        record_delivery(
            db,
            intent=intent,
            provider_key=intent.provider_key,
            status=DELIVERY_STATUS_FAILED,
            request_snapshot=request_snap,
            response_snapshot={},
            error_class="UnknownProvider",
            error_detail=str(exc),
        )
        mark_intent_state(db, intent, STATE_FAILED)
        return

    try:
        result = provider.send(payload)
    except Exception as exc:  # noqa: BLE001 — provider contract violation
        # DeliveryProvider.send is meant to never raise. If a provider
        # does, we treat it as a rejected send with the exception
        # captured verbatim.
        logger.exception(
            "Provider %r raised while dispatching intent %s.",
            intent.provider_key, intent.id,
        )
        record_delivery(
            db,
            intent=intent,
            provider_key=intent.provider_key,
            status=DELIVERY_STATUS_FAILED,
            request_snapshot=request_snap,
            response_snapshot={},
            error_class=type(exc).__name__,
            error_detail=str(exc),
        )
        mark_intent_state(db, intent, STATE_FAILED)
        return

    resp_snap = _response_snapshot(result)
    if result.accepted:
        record_delivery(
            db,
            intent=intent,
            provider_key=intent.provider_key,
            status=DELIVERY_STATUS_ACCEPTED,
            request_snapshot=request_snap,
            response_snapshot=resp_snap,
            provider_message_id=result.provider_message_id,
        )
        mark_intent_state(db, intent, STATE_SENT)
    else:
        record_delivery(
            db,
            intent=intent,
            provider_key=intent.provider_key,
            status=DELIVERY_STATUS_FAILED,
            request_snapshot=request_snap,
            response_snapshot=resp_snap,
            error_class=result.error_class,
            error_detail=result.error_detail,
        )
        mark_intent_state(db, intent, STATE_FAILED)


def dispatch_due(db: Session, *, limit: int = 50) -> list[str]:
    """Claim + dispatch up to ``limit`` queued intents.

    Returns the list of intent ids that were processed (regardless of
    outcome). An empty return means nothing was due.

    Callers are responsible for the surrounding transaction. In
    tests, the outer transaction/SAVEPOINT rolls back at teardown so
    intermediate ``commit()``s don't leak. In production,
    :func:`dispatch_due_from_pool` opens a fresh session and commits
    after the claim + after each dispatch so a worker crash cannot
    lose more than the in-flight send.
    """
    ids = claim_next_batch(db, limit=limit)
    if not ids:
        return []
    db.commit()

    processed: list[str] = []
    for intent_id in ids:
        intent = db.get(CommunicationIntent, intent_id)
        if intent is None:
            # Unlikely — someone deleted the row between claim + load.
            # Skip; the claim is on our side and the row is gone.
            logger.warning(
                "Claimed intent %s vanished before dispatch.", intent_id,
            )
            continue
        try:
            _dispatch_one(db, intent)
        except Exception:  # noqa: BLE001 — never let one bad intent kill the loop
            logger.exception(
                "Unhandled error while dispatching intent %s.", intent_id,
            )
            db.rollback()
        else:
            db.commit()
        processed.append(intent_id)

    return processed


def dispatch_due_from_pool(*, limit: int = 50) -> list[str]:
    """Session-owning variant. Used by the internal cron endpoint and
    (once M5 wires the async loop) the FastAPI lifespan hook.
    """
    db = SessionLocal()
    try:
        return dispatch_due(db, limit=limit)
    finally:
        db.close()
