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
from datetime import datetime

import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus, is_one_time,
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
    if is_one_time(subscription):
        # Nothing will ever be charged again, so there is no card to
        # keep current. Offering the member one would imply a future
        # payment that is not coming.
        raise PaymentMethodUnavailable(
            "a one-time membership has no recurring payment to update"
        )
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


def _session_field(session: object, name: str) -> object:
    """Read a field from a Stripe object or a webhook's plain dict.

    The two completion paths hand this module different shapes — the
    return page retrieves a ``StripeObject``, the webhook unpacks the
    event into a dict — and neither should have to convert for the
    other.
    """
    if isinstance(session, dict):
        return session.get(name)
    return getattr(session, name, None)


def _mapping_field(session: object, name: str) -> dict:
    """A nested Stripe field as a plain dict, whichever shape arrived.

    ``dict()`` on a ``StripeObject`` raises ``KeyError: 0``. In
    stripe-python 15.x a ``StripeObject`` is **not** a dict subclass
    and exposes neither ``keys()`` nor ``get()``, so ``dict()`` cannot
    use the mapping protocol and falls back to the legacy sequence
    protocol instead — asking for ``obj[0]``, which is a missing key.

    That only ever bit one of the two completion paths. The webhook
    unpacks its event with ``json.loads``, so its Session and the
    metadata inside it are plain dicts all the way down and converted
    cleanly. The return page retrieves a live ``StripeObject``, and
    converting its metadata is what raised a 500 in production on
    2026-11-22 — after Stripe had already accepted the card.

    An unreadable shape yields ``{}`` rather than a guess. The caller
    checks ownership against this mapping, so empty means the
    ownership checks fail and the update is refused: the safe
    direction, and the reason this cannot weaken them.
    """
    value = _session_field(session, name)
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:                        # pragma: no cover
            logger.warning(
                "collective membership: could not read %s from a %s",
                name, type(value).__name__,
            )
    return {}


def apply_session(
    db: Session, *, subscription: CollectiveMembership, session: object,
    now: datetime,
) -> dict:
    """Attach the card from this Session to **this** agreement.

    The one place a membership's payment method is ever changed. Both
    completion paths call it — the member returning from Stripe, and
    the ``checkout.session.completed`` webhook for the setup Session —
    so there is one set of checks and one outcome rather than two
    implementations that might disagree.

    Ownership is checked in both directions before anything moves: the
    Session must name this agreement in its metadata, *and* belong to
    this agreement's Stripe Customer. One alone is not enough — the
    first without the second would trust a value we put into a
    payload, and the second without the first would accept any Session
    the member happens to own, including one minted for a different
    Collective's membership.

    **Idempotent by Session**, which is what lets the two paths race
    safely. Whichever arrives first attaches the card and records the
    Session; the other recognises that Session as already applied and
    changes nothing. A duplicate webhook, a refreshed return page, or
    both at once settle on the same state. A *different* Session is
    applied — see migration 190 for why last-completed-wins is the
    rule, and why it is a product decision rather than an oversight.
    """
    meta = _mapping_field(session, "metadata")
    if meta.get("purchase_type") != METADATA_PURCHASE_TYPE:
        raise PaymentMethodUnavailable("not a payment-method session")
    if meta.get("collective_membership_id") != subscription.id:
        raise PaymentMethodUnavailable("session belongs to another agreement")
    if _session_field(session, "customer") != subscription.stripe_customer_id:
        raise PaymentMethodUnavailable("session belongs to another customer")

    session_id = _session_field(session, "id")
    if (
        session_id
        and subscription.payment_method_setup_session_id == session_id
    ):
        # The other path got here first. Not an error, and not a
        # reason to call Stripe again.
        return {
            "updated": True, "already_applied": True, "payment_retried": False,
        }

    # An agreement that has stopped has no card to change. Reported
    # rather than raised: a webhook for a member who cancelled while
    # inside Stripe's form is an ordinary race, not a fault.
    if subscription.status in (
        CollectiveMembershipStatus.ended.value,
        CollectiveMembershipStatus.cancelled.value,
        CollectiveMembershipStatus.failed.value,
    ):
        return {
            "updated": False, "reason": f"agreement_{subscription.status}",
        }
    if not subscription.stripe_subscription_id:
        return {"updated": False, "reason": "no_stripe_subscription"}

    payment_method_id = _resolve_payment_method(session)
    if not payment_method_id:
        # The member reached the return URL without completing, or
        # Stripe has not finished. Reported rather than guessed at.
        return {"updated": False, "reason": "no_payment_method_yet"}

    _bind_key()
    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        default_payment_method=payment_method_id,
    )
    subscription.payment_method_setup_session_id = (
        session_id if isinstance(session_id, str) else None
    )
    subscription.payment_method_updated_at = now
    subscription.updated_at = now
    db.flush()
    logger.info(
        "collective membership: payment method updated sub=%s user=%s "
        "space=%s session=%s", subscription.id, subscription.user_id,
        subscription.space_id, session_id,
    )

    # Confirmed only here: past the Stripe call, past the recording,
    # and only on the path that actually changed something. The
    # already-applied branch above returns before this, so the two
    # completion paths for one change confirm once between them.
    from app.services import collective_membership_emit as _emit

    _emit.emit_membership_payment_method_updated(
        db, sub=subscription,
        setup_session_id=session_id if isinstance(session_id, str) else "",
    )

    retried = _retry_open_invoice(subscription)
    return {"updated": True, "already_applied": False, "payment_retried": retried}


def _resolve_payment_method(session: object) -> str | None:
    """The card Stripe collected, from either shape of Session.

    A webhook's Session carries ``setup_intent`` as a bare id, so the
    SetupIntent is fetched when that is all there is. The return path
    expands it and this costs nothing.
    """
    setup_intent = _session_field(session, "setup_intent")
    if setup_intent is None:
        return None
    if isinstance(setup_intent, str):
        _bind_key()
        setup_intent = stripe.SetupIntent.retrieve(setup_intent)
    payment_method = _session_field(setup_intent, "payment_method")
    if isinstance(payment_method, str):
        return payment_method
    return getattr(payment_method, "id", None)


def apply_collected_method(
    db: Session, *, subscription: CollectiveMembership, session_id: str,
    now: datetime,
) -> dict:
    """The member has come back from Stripe. Re-read and apply.

    A return URL is a navigation, not evidence, so the Session is
    fetched from the provider rather than trusted from the query
    string. Everything after that is :func:`apply_session`.
    """
    _bind_key()
    session = stripe.checkout.Session.retrieve(
        session_id, expand=["setup_intent"],
    )
    return apply_session(db, subscription=subscription, session=session, now=now)


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
