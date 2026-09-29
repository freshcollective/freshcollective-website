"""The Accounts v2 intake: ``POST /api/webhooks/stripe/v2``.

A second endpoint rather than a branch in the existing one, because v2
core events are a different contract end to end: different delivery
mechanism (event destinations, not webhook endpoints), different payload
shape (thin notifications carrying identifiers, not objects), and a
different signing secret. The v1 endpoint, its secret and its handlers are
untouched.

What a thin event is allowed to tell us
---------------------------------------
Only *which* account changed, and which event this is. Nothing about the
account's state is read from the payload — FC re-fetches v2 and v1 and
runs the same projection service the creator endpoints use. A thin
notification is a doorbell, not a status report, and treating it as one
would mean writing state that was already stale when Stripe serialised it.

Retryable versus terminal
-------------------------
The distinction the v1 webhook work established, applied here:

* **Retryable** — a Stripe re-fetch that did not answer. The handler
  re-raises, ``process_webhook_event`` marks the row ``failed``, and this
  endpoint returns non-2xx so Stripe delivers again. Nothing stored is
  mutated, because the sync service fetches both objects before it writes.
* **Terminal** — an event FC will never act on: an account it does not
  know, an event type it does not handle, a livemode mismatch, or a
  request Stripe refused outright. The handler raises
  :class:`SkipWebhookEvent`, the row is recorded ``skipped``, and this
  endpoint returns 2xx. Acknowledged deliberately, never swallowed.

Retrying a terminal case would have Stripe redeliver for days against an
answer that cannot change; failing a retryable case silently would lose a
capability change FC needs.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.checkout.stripe_client import get_stripe_client
from app.core.config import settings
from app.core.database import get_db
from app.models.creator_stripe_account import CreatorStripeAccount, SyncSource
from app.services import connect_account_sync as sync
from app.services import stripe_connect_accounts as connect
from app.services.webhook_idempotency import SkipWebhookEvent, process_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

#: Kept distinct from the v1 provider so a v1 and a v2 event id can never
#: collide in ``webhook_events``, whose key is
#: ``(provider, provider_event_id)``.
PROVIDER = "stripe_v2"

#: Verified against the SDK's own ``LOOKUP_TYPE`` constants rather than
#: transcribed from documentation.
CAPABILITY_STATUS_UPDATED = (
    "v2.core.account[configuration.recipient].capability_status_updated"
)
REQUIREMENTS_UPDATED = "v2.core.account[requirements].updated"
RECIPIENT_UPDATED = "v2.core.account[configuration.recipient].updated"
ACCOUNT_LINK_RETURNED = "v2.core.account_link.returned"
ACCOUNT_CLOSED = "v2.core.account.closed"

#: The five FC subscribes to. Anything else is a deliberate skip — an
#: event destination can be edited in the Dashboard, so the code must not
#: assume its own list is the only one in force.
SUPPORTED_EVENTS = frozenset({
    CAPABILITY_STATUS_UPDATED,
    REQUIREMENTS_UPDATED,
    RECIPIENT_UPDATED,
    ACCOUNT_LINK_RETURNED,
    ACCOUNT_CLOSED,
})


def _account_id_from(notification: Any) -> str | None:
    """Which account this event is about.

    Four of the five carry it as ``related_object.id`` on the thin
    notification. ``account_link.returned`` does not — its notification has
    no ``related_object`` at all, and the account id lives on the *full*
    event as ``data.account_id``. So that one costs an extra fetch, and a
    failure of that fetch is retryable like any other unanswered question.
    """
    related = getattr(notification, "related_object", None)
    if related is not None and getattr(related, "id", None):
        return str(related.id)

    if notification.type == ACCOUNT_LINK_RETURNED:
        try:
            event = notification.fetch_event()
        except stripe.StripeError as exc:
            raise connect.ConnectUnavailable(
                f"could not fetch event {notification.id} to learn its account: {exc}"
            ) from exc
        account_id = getattr(getattr(event, "data", None), "account_id", None)
        return str(account_id) if account_id else None

    return None


def _handle(db: Session, *, notification: Any, account_id: str | None) -> None:
    """Re-read Stripe for ``account_id`` and persist the projection.

    Idempotent, as ``process_webhook_event`` requires: it recomputes the
    projection from Stripe rather than applying a delta, so running twice
    lands the same row state.
    """
    if not account_id:
        raise SkipWebhookEvent(
            f"event {notification.id} ({notification.type}) names no account"
        )

    # Mode safety, before any lookup. A live event arriving at a test
    # deployment (or the reverse) is a misconfigured destination, not
    # something to act on — and the row it would match does not belong to
    # this environment's keys.
    expected_livemode = settings.stripe_mode == "live"
    if bool(notification.livemode) is not expected_livemode:
        raise SkipWebhookEvent(
            f"event {notification.id} livemode={notification.livemode} does not "
            f"match this environment's Stripe mode ({settings.stripe_mode})"
        )

    row = (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.stripe_account_id == account_id,
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
        )
        .first()
    )
    if row is None:
        # Terminal on purpose. Stripe will redeliver for days otherwise,
        # and no amount of retrying makes FC aware of an account it never
        # created. Recorded as ``skipped`` so it is visible rather than
        # silently dropped.
        raise SkipWebhookEvent(
            f"no creator_stripe_accounts row for {account_id} in "
            f"{settings.stripe_mode} mode"
        )

    try:
        sync.sync_from_stripe(db, row, source=SyncSource.webhook)
    except connect.ConnectUnavailable:
        # Retryable: re-raise so the event is marked failed and Stripe
        # delivers again. Nothing has been written.
        raise
    except connect.ConnectAccountNotFound as exc:
        # Also what a mode mismatch looks like, so never grounds for
        # rewriting the projection — and retrying will not change it.
        sync.record_sync_failure(db, row, str(exc))
        raise SkipWebhookEvent(f"Stripe does not recognise {account_id}: {exc}")
    except connect.ConnectRejected as exc:
        # Stripe decided. The identical request gets the identical answer.
        sync.record_sync_failure(db, row, str(exc))
        raise SkipWebhookEvent(f"Stripe refused the re-read for {account_id}: {exc}")


@router.post("/stripe/v2")
async def stripe_v2_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Receive an Accounts v2 event notification.

    Signature verification uses ``StripeClient.parse_event_notification``,
    the v2 counterpart of ``construct_event``, with the dedicated v2
    secret. It verifies the same HMAC header scheme over the raw body, so
    the body must be read before any parsing — and refuses a v1 webhook
    payload sent here by mistake, which is a useful guard against the two
    endpoints being crossed in configuration.
    """
    if not settings.stripe_v2_webhooks_enabled:
        # Refuse rather than accept-and-drop: a 503 is visible in Stripe's
        # delivery log, whereas a 200 would make an unconfigured
        # environment look like a working one.
        raise HTTPException(
            status_code=503,
            detail="The Stripe Accounts v2 webhook is not configured.",
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        notification = get_stripe_client().parse_event_notification(
            payload, sig_header, settings.stripe_v2_webhook_secret,
        )
    except stripe.SignatureVerificationError:
        logger.warning("stripe v2 webhook: signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")
    except ValueError as exc:
        # Raised when a v1 webhook payload arrives at the v2 endpoint.
        logger.warning("stripe v2 webhook: wrong payload shape: %s", exc)
        raise HTTPException(status_code=400, detail="Unexpected webhook payload.")
    except Exception as exc:
        logger.error("stripe v2 webhook: parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook parse error.")

    event_type = notification.type
    logger.info(
        "stripe v2 webhook received: %s id=%s livemode=%s",
        event_type, notification.id, notification.livemode,
    )

    if event_type not in SUPPORTED_EVENTS:
        # Recorded, not ignored: an event destination can be edited outside
        # this codebase, and "we saw it and chose not to act" is worth
        # being able to see.
        def _unsupported() -> None:
            raise SkipWebhookEvent(f"unsupported v2 event type {event_type}")

        process_webhook_event(
            db,
            provider=PROVIDER,
            provider_event_id=notification.id,
            event_type=event_type,
            handler=_unsupported,
        )
        return {"received": True, "handled": False}

    try:
        account_id = _account_id_from(notification)
    except connect.ConnectUnavailable as exc:
        logger.warning("stripe v2 webhook: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Could not read the event from Stripe. Please redeliver.",
        ) from exc

    try:
        outcome = process_webhook_event(
            db,
            provider=PROVIDER,
            provider_event_id=notification.id,
            event_type=event_type,
            handler=lambda: _handle(
                db, notification=notification, account_id=account_id,
            ),
        )
    except connect.ConnectUnavailable as exc:
        # Non-2xx so Stripe retries. The stored projection is untouched.
        logger.warning(
            "stripe v2 webhook: retryable failure for event %s: %s",
            notification.id, exc,
        )
        raise HTTPException(
            status_code=503,
            detail="Stripe could not be re-read. Please redeliver.",
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "stripe v2 webhook: handler failed for event %s", notification.id,
        )
        raise HTTPException(
            status_code=500, detail="Webhook processing failed.",
        ) from exc

    return {"received": True, "handled": outcome.result == "processed"}
