"""Stripe events for a paid Collective membership.

Routed by metadata
------------------
Every Stripe object this system creates carries
``metadata.purchase_type='collective_membership'``, and
``owns_event`` is the gate the dispatcher asks before any other handler
sees the event. Creator subscriptions (``creator_subscription``) and
finite instalment plans (``finite_plan_setup``) are untouched: the
dispatcher tries each system's gate in turn and only one can claim an
event.

What each event does
--------------------
``checkout.session.completed``
    A card was captured. **Grants nothing** — it records the Stripe
    subscription id against the agreement so the invoice that follows
    can be found, and that is all. Stripe tells us separately whether
    the card could actually be charged.

``invoice.payment_succeeded``
    The authoritative one. Verified, matched against the agreement's own
    frozen terms, recorded in the ledger, and only then does membership
    appear.

Why the feature flag is not consulted here
------------------------------------------
Deliberate, and required: an agreement that exists must stay serviceable
whatever the flag says. A flag switched off after a subscription was
created must never leave its payments unrecorded — that would be money
taken and nothing written down. The flag gates *opening* a subscription,
which is the checkout route's business, not servicing one.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.services.collective_membership_billing import (
    METADATA_PURCHASE_TYPE,
)
from app.services.collective_membership_lifecycle import (
    AmountMismatch, activate_from_first_invoice,
)

logger = logging.getLogger(__name__)


def _subscription_details(obj: dict[str, Any]) -> dict[str, Any]:
    """An invoice's subscription details, across Stripe API versions.

    On ``2026-05-27.dahlia`` — the version this account serves — an
    invoice carries them at ``parent.subscription_details``, with the
    subscription id *inside* it and no top-level ``subscription`` field
    at all. Older versions put a flat ``subscription`` on the invoice
    and the metadata under ``subscription_details``.

    Both shapes are read because the first was found only by driving a
    real test-mode invoice through this handler: against the flat shape
    alone, ``owns_event`` would have missed every renewal and the
    agreement would never have recorded its Stripe subscription id.
    """
    parent = obj.get("parent") or {}
    nested = parent.get("subscription_details")
    if isinstance(nested, dict):
        return nested
    legacy = obj.get("subscription_details")
    return legacy if isinstance(legacy, dict) else {}


def _subscription_id_from(obj: dict[str, Any]) -> str | None:
    """The Stripe subscription id an invoice belongs to, either shape."""
    flat = obj.get("subscription")
    if isinstance(flat, str) and flat:
        return flat
    nested = _subscription_details(obj).get("subscription")
    return nested if isinstance(nested, str) and nested else None


def owns_event(obj: dict[str, Any]) -> bool:
    """Does this Stripe object belong to Collective membership billing?

    Checks the object's own metadata and, for an invoice, the
    subscription metadata Stripe copies onto it. An object with absent
    or foreign metadata is not ours and this returns False — the same
    discipline as ``stripe_creator_billing.is_creator_subscription``.
    """
    meta = obj.get("metadata") or {}
    if meta.get("purchase_type") == METADATA_PURCHASE_TYPE:
        return True
    sub_meta = _subscription_details(obj).get("metadata") or {}
    return sub_meta.get("purchase_type") == METADATA_PURCHASE_TYPE


def _find_by_metadata(
    db: Session, obj: dict[str, Any],
) -> CollectiveMembership | None:
    """The agreement this event is about.

    Three ways in, most specific first. The id in metadata is what we
    put there; the Stripe subscription id is what later events carry;
    the Session id covers the window before a subscription exists.
    """
    meta = obj.get("metadata") or {}
    sub_meta = _subscription_details(obj).get("metadata") or {}

    row_id = meta.get("collective_membership_id") or sub_meta.get(
        "collective_membership_id"
    )
    if row_id:
        row = (
            db.query(CollectiveMembership)
            .filter(CollectiveMembership.id == row_id)
            .first()
        )
        if row is not None:
            return row

    sub_id = _subscription_id_from(obj) or obj.get("id")
    if isinstance(sub_id, str) and sub_id.startswith("sub_"):
        row = (
            db.query(CollectiveMembership)
            .filter(CollectiveMembership.stripe_subscription_id == sub_id)
            .first()
        )
        if row is not None:
            return row

    session_id = obj.get("id")
    if isinstance(session_id, str) and session_id.startswith("cs_"):
        return (
            db.query(CollectiveMembership)
            .filter(
                CollectiveMembership.stripe_checkout_session_id == session_id
            )
            .first()
        )
    return None


def handle_checkout_completed(
    obj: dict[str, Any], db: Session, *, event_id: str,
) -> bool:
    """Link the Stripe subscription onto the agreement. Grants nothing.

    Returns True when this system claimed the event.
    """
    row = _find_by_metadata(db, obj)
    if row is None:
        logger.warning(
            "collective membership: checkout.session.completed %s names no "
            "known agreement (event=%s)", obj.get("id"), event_id,
        )
        return True

    sub_id = _subscription_id_from(obj) or obj.get("subscription")
    if isinstance(sub_id, str) and sub_id and not row.stripe_subscription_id:
        row.stripe_subscription_id = sub_id
    customer = obj.get("customer")
    if isinstance(customer, str) and customer and not row.stripe_customer_id:
        row.stripe_customer_id = customer
    row.updated_at = datetime.utcnow()
    db.flush()
    logger.info(
        "collective membership: card captured sub=%s stripe_sub=%s "
        "(no access granted — awaiting invoice.payment_succeeded)",
        row.id, sub_id,
    )
    return True


def _ts(value: Any) -> datetime | None:
    return datetime.utcfromtimestamp(value) if isinstance(value, int) else None


def handle_invoice_payment_succeeded(
    obj: dict[str, Any], db: Session, *, event_id: str,
) -> bool:
    """The authoritative activation. Returns True when claimed."""
    row = _find_by_metadata(db, obj)
    if row is None:
        logger.warning(
            "collective membership: invoice %s names no known agreement "
            "(event=%s)", obj.get("id"), event_id,
        )
        return True

    if row.status in (
        CollectiveMembershipStatus.cancelled.value,
        CollectiveMembershipStatus.failed.value,
    ):
        # A superseded or operator-cancelled agreement must not come
        # back to life because a late invoice arrived for it. Recorded
        # loudly: money may have moved against something closed.
        logger.error(
            "collective membership: invoice %s arrived for %s agreement "
            "sub=%s — not activating, needs reconciliation",
            obj.get("id"), row.status, row.id,
        )
        return True

    lines = (obj.get("lines") or {}).get("data") or []
    period = (lines[0].get("period") or {}) if lines else {}

    try:
        outcome = activate_from_first_invoice(
            db,
            subscription=row,
            invoice_id=obj.get("id") or "",
            invoice_amount_cents=int(
                obj.get("amount_paid") or obj.get("total") or 0
            ),
            invoice_currency=(obj.get("currency") or "").upper(),
            stripe_subscription_id=_subscription_id_from(obj),
            charge_id=obj.get("charge"),
            payment_intent_id=obj.get("payment_intent"),
            period_start=_ts(period.get("start")),
            period_end=_ts(period.get("end")),
            now=datetime.utcnow(),
        )
    except AmountMismatch:
        # Refused rather than recorded. A wrong figure in the creator's
        # earnings is worse than an unprocessed event, and Stripe will
        # retry while we investigate.
        logger.exception(
            "collective membership: invoice %s does not match agreement "
            "sub=%s — refusing to record", obj.get("id"), row.id,
        )
        raise

    logger.info(
        "collective membership: invoice %s applied=%s membership=%s sub=%s",
        obj.get("id"), outcome.applied, outcome.membership, row.id,
    )
    return True
