"""Stripe refund webhook handling.

MVP scope: exactly one event type — ``charge.refunded``. Fires each
time a Charge's cumulative refund amount changes (initial partial,
subsequent partial, full refund, or full refund reached via partials).
The payload's ``charge.amount_refunded`` is Stripe's authoritative
cumulative refunded value on the charge — the handler stamps that
value straight into ``PaymentTransaction.refunded_amount_cents``.

Deliberately not handled: ``refund.created`` / ``refund.updated`` /
``charge.refund.updated``. ``charge.refunded`` fires only after a
refund succeeds, so ignoring the finer Refund-object lifecycle
doesn't miss any settled state. Failed refunds correctly leave the
ledger unchanged.

Guardrails
----------

* **WebhookEvent idempotency** — the outer ``process_webhook_event``
  wrapper ensures a duplicate Stripe event id is a no-op. Existing
  exactly-once behaviour is preserved; lease reclaim continues to
  apply only to genuinely stale/incomplete rows.

* **Monotonic refund state** — distinct refund events for the same
  charge may arrive out of order. The handler:
    - refuses to lower ``refunded_amount_cents``;
    - refuses to downgrade ``status`` from ``refunded`` to
      ``partially_refunded``;
    - refuses to move ``last_refunded_at`` backwards.

* **Access is not touched.** Refund and access-revocation are
  entirely independent. This handler does not touch AccessPass,
  PathwayEntitlement, AccessGrantRecord, SpaceMembership, or
  EventBooking rows. A creator uses the whole-purchase revoke UI
  (Payments received) to revoke access separately.

* **Charge lookup** — ``provider_charge_id`` first, then
  ``provider_payment_intent_id`` (populated on the pay-in-full
  ``checkout.session.completed`` path). On successful PI-fallback
  match, ``provider_charge_id`` is opportunistically backfilled so
  subsequent refunds have the fastest lookup path.

* **Unknown charge** — the handler raises ``SkipWebhookEvent``.
  Stripe stops retrying; the event is recorded as ``skipped`` in
  the WebhookEvent table. No 500, no partial writes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
)
from app.services.webhook_idempotency import (
    SkipWebhookEvent,
    process_webhook_event,
)

logger = logging.getLogger(__name__)


def _sfield(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a Stripe-object-shaped dict without ever
    calling ``.get()``. Stripe SDK objects don't expose ``.get()``
    reliably across versions; the dict conversion in the top-level
    webhook dispatcher gives us plain dicts, but this helper matches
    the pattern used elsewhere in the webhook code."""
    try:
        v = obj[key]
    except (KeyError, TypeError):
        return default
    return default if v is None else v


def _stripe_created_to_datetime(created: Any) -> datetime | None:
    """Stripe emits ``created`` as a Unix epoch seconds int. Return a
    naive UTC ``datetime`` to match the rest of the DB (all
    ``DateTime(timezone=False)`` columns storing UTC by convention)."""
    if created is None:
        return None
    try:
        return datetime.fromtimestamp(int(created), tz=timezone.utc).replace(
            tzinfo=None,
        )
    except (TypeError, ValueError):
        return None


def _find_txn_for_charge(
    db: Session, charge: dict,
) -> PaymentTransaction | None:
    """Locate the ``PaymentTransaction`` this charge belongs to.

    Preference order:
      1. ``provider_charge_id == charge.id`` — matches finite-plan
         instalments (populated by the first-invoice handler) and
         any pay-in-full row that a previous refund event has
         already backfilled.
      2. Fallback: ``provider_payment_intent_id == charge.payment_intent``
         — matches pay-in-full rows populated by the
         ``checkout.session.completed`` handler.

    Returns None when neither matches (Stripe event for a charge
    outside our ledger — the outer handler treats this as
    ``SkipWebhookEvent``).
    """
    charge_id = _sfield(charge, "id")
    if charge_id:
        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_charge_id == charge_id)
            .first()
        )
        if row is not None:
            return row
    pi_id = _sfield(charge, "payment_intent")
    if pi_id:
        row = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_payment_intent_id == pi_id)
            .first()
        )
        if row is not None:
            # Opportunistic backfill so subsequent refund events on
            # this charge take the faster charge-id path.
            if charge_id and row.provider_charge_id is None:
                row.provider_charge_id = charge_id
            return row
    return None


def _do_charge_refunded(
    db: Session, *, charge: dict, event_created: datetime | None,
) -> None:
    txn = _find_txn_for_charge(db, charge)
    if txn is None:
        raise SkipWebhookEvent(
            f"charge.refunded: no PaymentTransaction matches "
            f"charge={_sfield(charge, 'id')!r} "
            f"payment_intent={_sfield(charge, 'payment_intent')!r}"
        )

    incoming_amount = int(_sfield(charge, "amount_refunded", default=0) or 0)
    is_fully_refunded = bool(_sfield(charge, "refunded", default=False))

    # Monotonic amount guard — never let an older event regress
    # cumulative refunded state. Same-value re-delivery is a no-op
    # write below (already-idempotent).
    if incoming_amount < txn.refunded_amount_cents:
        logger.info(
            "charge.refunded: skipping out-of-order event — "
            "incoming=%d < current=%d for txn=%s charge=%s",
            incoming_amount, txn.refunded_amount_cents,
            txn.id, _sfield(charge, "id"),
        )
        return

    txn.refunded_amount_cents = incoming_amount

    # Monotonic status guard — never downgrade from ``refunded`` to
    # ``partially_refunded``. Order preference:
    #   already refunded → stay refunded
    #   incoming fully refunded → refunded
    #   incoming > 0 → partially_refunded
    #   incoming == 0 (edge: same-event re-derivation) → don't change
    if txn.status == PaymentTransactionStatus.refunded:
        pass
    elif is_fully_refunded:
        txn.status = PaymentTransactionStatus.refunded
    elif incoming_amount > 0:
        txn.status = PaymentTransactionStatus.partially_refunded
    # incoming_amount == 0 is a no-op status change.

    # Monotonic timestamp guard — the LATER of current and event.
    now = datetime.utcnow()
    stamp = event_created or now
    if txn.last_refunded_at is None or stamp > txn.last_refunded_at:
        txn.last_refunded_at = stamp

    txn.updated_at = now

    logger.info(
        "charge.refunded: txn=%s charge=%s refunded_amount_cents=%d "
        "status=%s last_refunded_at=%s",
        txn.id, _sfield(charge, "id"),
        txn.refunded_amount_cents,
        (
            txn.status.value if hasattr(txn.status, "value")
            else str(txn.status)
        ),
        txn.last_refunded_at,
    )


def handle_charge_refunded(
    charge: dict, db: Session, *,
    provider_event_id: str,
    event_created: int | None,
    event_livemode: bool,
) -> None:
    """``charge.refunded`` handler. Idempotency + monotonic-guarded
    write to ``PaymentTransaction`` refund state.

    ``charge`` is the ``event.data.object`` (a Stripe Charge dict).
    ``event_created`` is the outer event's Unix-seconds timestamp —
    used for the monotonic ``last_refunded_at`` guard. When None
    the handler falls back to ``datetime.utcnow()`` inside the
    write path.

    Access-side revocation is a separate operator action and is NOT
    triggered here.
    """
    stamp = _stripe_created_to_datetime(event_created)

    def _handler() -> None:
        _do_charge_refunded(db, charge=charge, event_created=stamp)

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=provider_event_id,
        event_type="charge.refunded",
        handler=_handler,
    )
