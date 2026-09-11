"""Thin wrapper around ``stripe.Refund.create`` for creator/admin-
initiated refunds.

Every call:

* binds the platform Stripe API key (same pattern as
  ``stripe_finite_plan._bind_key``);
* passes an idempotency-key derived from the RefundOperation.id so
  network retries + reconciliation replays are safe (Stripe caches
  by key for 24h);
* passes ``metadata.refund_operation_id`` so the webhook correlator
  can match the resulting ``charge.refunded`` event back to our
  RefundOperation regardless of ordering (Correction 1 —
  webhook-before-API-persist race).

The ledger is NOT mutated here — that stays webhook-authoritative.
This module returns the Stripe Refund object (or raises) and the
caller records the outcome on the RefundOperation using a
conditional UPDATE guarded on ``terminal_status='in_flight'``.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.core.config import settings
from app.models.refund_operation import (
    RefundOperationReason,
    StripeIdentifierKind,
)


logger = logging.getLogger(__name__)


# Idempotency-key prefix; version bump reserved for future
# operation-shape changes.
_KEY_VERSION = "v1"


# Restricted Stripe ``reason`` enum values. We map some of our own
# reasons onto ``requested_by_customer`` (the safest broad label);
# others map to their specific Stripe value where the semantics agree.
_REASON_TO_STRIPE = {
    RefundOperationReason.member_request.value: "requested_by_customer",
    RefundOperationReason.duplicate.value: "duplicate",
    RefundOperationReason.fraudulent.value: "fraudulent",
    RefundOperationReason.goodwill.value: "requested_by_customer",
    RefundOperationReason.error_correction.value: "requested_by_customer",
    RefundOperationReason.other.value: "requested_by_customer",
}


def _bind_key() -> None:
    if not settings.stripe_enabled:
        raise RuntimeError(
            "Stripe is not configured — cannot create refund."
        )
    stripe.api_key = settings.stripe_secret_key


def idempotency_key_for(refund_operation_id: str) -> str:
    """Derived once per RefundOperation.id. Reconciliation replay
    MUST use the same key — that's what makes the replay a Stripe
    cache hit rather than a fresh charge."""
    return f"refop:{refund_operation_id}:{_KEY_VERSION}"


def create_refund(
    *,
    refund_operation_id: str,
    payment_transaction_id: str,
    initiator_user_id: str | None,
    identifier_kind: str,
    identifier_value: str,
    amount_cents: int,
    reason: str,
) -> Any:
    """Submit ``stripe.Refund.create`` for a fresh RefundOperation.

    Idempotent by construction: Stripe's 24h cache keyed on
    ``idempotency_key_for(refund_operation_id)`` returns the same
    Refund object if the call is repeated with identical parameters
    (e.g. from network retry or Phase A reconciliation).

    ``identifier_kind`` selects between ``charge=<id>`` (preferred
    when the PaymentTransaction carries ``provider_charge_id``) and
    ``payment_intent=<id>`` (fallback for pay-in-full rows before
    the refund handler's opportunistic charge-id backfill has run).

    Raises the underlying ``stripe.*Error`` — caller decides how to
    transition the RefundOperation based on the error type.
    """
    _bind_key()
    kwargs: dict[str, Any] = {
        "amount": amount_cents,
        "reason": _REASON_TO_STRIPE.get(
            reason, "requested_by_customer",
        ),
        "metadata": {
            "refund_operation_id": refund_operation_id,
            "payment_transaction_id": payment_transaction_id,
            # initiator_user_id is nullable on the DB side (SET NULL
            # on user delete); metadata carries a string or empty.
            "initiator_user_id": initiator_user_id or "",
        },
        "idempotency_key": idempotency_key_for(refund_operation_id),
    }
    if identifier_kind == StripeIdentifierKind.charge.value:
        kwargs["charge"] = identifier_value
    elif identifier_kind == StripeIdentifierKind.payment_intent.value:
        kwargs["payment_intent"] = identifier_value
    else:
        raise ValueError(
            f"unknown stripe_identifier_kind={identifier_kind!r}"
        )

    logger.info(
        "creator refund: submitting stripe.Refund.create op=%s kind=%s "
        "amount=%d",
        refund_operation_id, identifier_kind, amount_cents,
    )
    return stripe.Refund.create(**kwargs)


def retrieve_refund(stripe_refund_id: str) -> Any:
    """Look up a Stripe Refund by id. Used by the reconciler to
    check status of an ``accepted`` op whose webhook never arrived."""
    _bind_key()
    return stripe.Refund.retrieve(stripe_refund_id)


def retrieve_charge(charge_id: str) -> Any:
    """Look up a Stripe Charge. Used by the reconciler to force-sync
    the ledger when a webhook was lost."""
    _bind_key()
    return stripe.Charge.retrieve(charge_id)


def list_refunds_for_charge(charge_id: str, *, limit: int = 100) -> Any:
    """Paginating iterator over all Refunds on a Charge. Used by
    Phase B reconciliation (>24h idempotency-cache-expired case) to
    find a Refund by ``metadata.refund_operation_id`` when replay
    is no longer safe."""
    _bind_key()
    return stripe.Refund.list(charge=charge_id, limit=limit).auto_paging_iter()
