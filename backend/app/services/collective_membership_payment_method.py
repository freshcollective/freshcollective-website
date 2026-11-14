"""Changing the card behind one Collective membership — and only that one.

The hazard this module exists to avoid
--------------------------------------
One person is one Stripe Customer (see
``collective_membership_billing.resolve_customer_id``). That Customer
may carry their Creator subscription, several Collective memberships,
and finite instalment plans at once. So "update my payment method" is
an ambiguous request, and the obvious implementations answer it wrongly:

* the **Billing Portal** operates on the Customer. Its
  ``payment_method_update`` flow replaces the Customer's default, which
  every subscription without its own default falls back to — one
  member updating a card for one Collective would silently re-point
  their Creator plan and every other membership too.
* a **custom card form** would put card numbers through our own
  frontend, which is not something to do for a convenience.

What is done instead, and the evidence for it
---------------------------------------------
A Checkout Session in ``mode='setup'`` collects the card on Stripe's
own hosted page, and the resulting payment method is then set as the
**subscription's** ``default_payment_method``. A subscription-level
default overrides the customer default for that subscription alone.

Verified against real Stripe test mode rather than assumed, on
API version ``2026-05-27.dahlia``: with two subscriptions on one
customer, pointing the first at a new payment method left the second
reading ``default_payment_method=None`` — still falling back to the
customer default, which was itself unchanged.

That probe also turned up the one API detail worth remembering: a
``mode='setup'`` Checkout Session on this version **requires
``currency``**, and 400s without it.
"""

from __future__ import annotations

import logging

import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import Space

logger = logging.getLogger(__name__)

#: Marks a Session this module opened. The confirm path refuses
#: anything else, so a Session minted for a *subscription purchase*
#: can never be replayed here to move a card.
METADATA_PURCHASE_TYPE = "collective_membership_payment_method"


class PaymentMethodUnavailable(RuntimeError):
    """Stripe is not configured, or the agreement cannot take a card."""


def _bind_key() -> None:
    if not settings.stripe_secret_key:
        raise PaymentMethodUnavailable(
            "Stripe is not configured — cannot collect a payment method."
        )
    stripe.api_key = settings.stripe_secret_key


def open_collection_session(
    *,
    subscription: CollectiveMembership,
    space: Space,
    success_url: str,
    cancel_url: str,
) -> str:
    """A hosted page for this member to enter a new card.

    Deliberately **not** gated on the membership billing flag. An
    agreement that exists has to remain serviceable whatever the flag
    says — a member whose card expires must not be told to come back
    when a feature switch is flipped. The flag governs opening *new*
    agreements, which is a different question and a different module.
    """
    _bind_key()
    if not subscription.stripe_customer_id:
        raise PaymentMethodUnavailable(
            f"agreement {subscription.id} has no Stripe customer"
        )
    if not subscription.stripe_subscription_id:
        raise PaymentMethodUnavailable(
            f"agreement {subscription.id} has no Stripe subscription"
        )

    session = stripe.checkout.Session.create(
        mode="setup",
        customer=subscription.stripe_customer_id,
        # Required on this API version for a setup-mode Session, and
        # the agreement's own currency rather than a platform default
        # so the member sees their own.
        currency=(subscription.currency or "AUD").lower(),
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "purchase_type": METADATA_PURCHASE_TYPE,
            "collective_membership_id": subscription.id,
            "space_id": space.id,
            "user_id": subscription.user_id,
        },
        idempotency_key=f"cmem_pm:{subscription.id}:{subscription.updated_at}",
    )
    logger.info(
        "collective membership: payment-method session=%s sub=%s user=%s",
        session.id, subscription.id, subscription.user_id,
    )
    return session.url


def apply_collected_method(
    db: Session, *, subscription: CollectiveMembership, session_id: str,
) -> dict:
    """Attach the card the member just entered to **this** agreement.

    Ownership is checked in both directions before anything moves: the
    Session must name this agreement in its metadata, *and* belong to
    this agreement's Stripe Customer. One alone is not enough — the
    first without the second would trust a value we put in a payload,
    and the second without the first would accept any Session the
    member happens to own, including one minted for a different
    Collective's membership.

    Safe to repeat: setting the same default twice is the same state.
    """
    _bind_key()
    session = stripe.checkout.Session.retrieve(
        session_id, expand=["setup_intent"],
    )

    meta = dict(getattr(session, "metadata", None) or {})
    if meta.get("purchase_type") != METADATA_PURCHASE_TYPE:
        raise PaymentMethodUnavailable("not a payment-method session")
    if meta.get("collective_membership_id") != subscription.id:
        raise PaymentMethodUnavailable("session belongs to another agreement")
    if session.customer != subscription.stripe_customer_id:
        raise PaymentMethodUnavailable("session belongs to another customer")

    setup_intent = session.setup_intent
    payment_method = getattr(setup_intent, "payment_method", None)
    if isinstance(payment_method, str):
        payment_method_id = payment_method
    else:
        payment_method_id = getattr(payment_method, "id", None)
    if not payment_method_id:
        # The member reached the return URL without completing, or
        # Stripe has not finished. Reported rather than guessed at.
        return {"updated": False, "reason": "no_payment_method_yet"}

    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        default_payment_method=payment_method_id,
    )
    logger.info(
        "collective membership: payment method updated sub=%s user=%s "
        "space=%s", subscription.id, subscription.user_id,
        subscription.space_id,
    )

    retried = _retry_open_invoice(subscription)
    return {"updated": True, "payment_retried": retried}


def _retry_open_invoice(subscription: CollectiveMembership) -> bool:
    """Ask Stripe to try the failed payment again, now there is a card.

    Only while recovery is actually running. Outside ``past_due`` there
    is nothing outstanding, and paying an invoice that is not open
    would be inventing a charge.

    A failure here is swallowed deliberately: the card *has* been
    attached, which is what the member asked for, and Stripe retries
    on its own schedule regardless. Turning a successful card update
    into an error because the immediate retry did not land would be
    the wrong report.
    """
    if subscription.status != CollectiveMembershipStatus.past_due.value:
        return False
    try:
        invoices = stripe.Invoice.list(
            customer=subscription.stripe_customer_id,
            subscription=subscription.stripe_subscription_id,
            status="open", limit=1,
        )
        if not invoices.data:
            return False
        stripe.Invoice.pay(invoices.data[0].id)
        logger.info(
            "collective membership: retried invoice=%s after card update "
            "sub=%s", invoices.data[0].id, subscription.id,
        )
        return True
    except Exception:
        logger.warning(
            "collective membership: invoice retry after card update failed "
            "sub=%s — the card is attached and Stripe will retry on its own "
            "schedule", subscription.id, exc_info=True,
        )
        return False
