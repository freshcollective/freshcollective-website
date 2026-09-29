"""The Stripe calls a discount reservation needs, and nothing else.

Isolated in its own module for one reason: every function here is a
network call whose *failure mode* is part of the correctness argument.
``discount_reservations`` must be able to tell "Stripe says this is dead"
from "Stripe did not answer", because it releases a slot on the first and
must not on the second. Two exception types make that distinction
explicit rather than leaving it to error-message matching.

Nothing here writes to the database, and nothing here decides policy — it
reports what Stripe said.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.core.config import settings
from app.models.discount_code import DiscountReservation

logger = logging.getLogger(__name__)


class StripeUnavailable(RuntimeError):
    """Stripe could not be asked, or gave an answer we cannot act on.

    The caller must treat this as "unknown", never as "dead". Releasing a
    slot on an unanswered question is how a member who has already paid
    loses it to someone else.
    """


class StripeStateChanged(RuntimeError):
    """The object moved between our read and our write.

    Not an error in itself — it means re-read and decide again. Raised
    separately so the caller does not conflate a lost race with an
    outage.
    """


def _bind_key() -> None:
    stripe.api_key = settings.stripe_secret_key


def session_status(session_id: str) -> str:
    """``'open' | 'complete' | 'expired'`` as Stripe reports it.

    Any other value, or any failure to read, is raised as
    :class:`StripeUnavailable` — an unrecognised status is not something
    to guess about when the consequence is a possible second charge.
    """
    _bind_key()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.InvalidRequestError as exc:
        # A Session id we hold but Stripe does not recognise is not
        # evidence of anything safe — it may be a mode mismatch (test key
        # reading a live object). Refuse to conclude.
        raise StripeUnavailable(f"session {session_id} not retrievable: {exc}") from exc
    except stripe.StripeError as exc:
        raise StripeUnavailable(f"session {session_id} retrieve failed: {exc}") from exc

    status = (
        session["status"] if isinstance(session, dict)
        else getattr(session, "status", None)
    )
    if status not in ("open", "complete", "expired"):
        raise StripeUnavailable(
            f"session {session_id} has unrecognised status {status!r}"
        )
    return status


def expire_session(session_id: str) -> None:
    """Close an open Session so it can never be paid.

    Raises :class:`StripeStateChanged` when Stripe refuses because the
    Session is no longer open — the caller re-reads rather than assuming
    which way it went.
    """
    _bind_key()
    try:
        stripe.checkout.Session.expire(session_id)
    except stripe.InvalidRequestError as exc:
        raise StripeStateChanged(f"session {session_id} not expirable: {exc}") from exc
    except stripe.StripeError as exc:
        raise StripeUnavailable(f"session {session_id} expire failed: {exc}") from exc


def recover_session_id(*, reservation: DiscountReservation) -> str | None:
    """Did a Stripe Session get created for this reservation after all?

    The case: FC created a Session, then crashed before storing its id.
    The reservation looks like it never reached Stripe, but a live payment
    page exists.

    Answered by replaying ``Session.create`` with the reservation's
    original idempotency key AND its original persisted parameters.
    Stripe returns the cached original response rather than creating a
    second Session, so a replay reveals the first one. This is only valid
    while Stripe still holds that key — the caller is responsible for the
    age check, because a pruned key turns this replay into a genuine new
    request.

    Returns the Session id if one exists, or ``None`` when the persisted
    parameters show no request was ever built — in which case nothing can
    charge the member.

    Never recomputes anything. The stored ``expires_at`` is an absolute
    instant and is re-sent as-is; deriving a fresh ``now + 60 minutes``
    would change the payload and make Stripe treat it as a different
    request under the same key, which is an error rather than a replay.
    """
    params = reservation.session_create_params_json
    if not params:
        # The params are persisted in the same commit that records the
        # Session id, so their absence means the Stripe call was never
        # reached. Nothing exists to recover.
        return None

    _bind_key()
    try:
        session = stripe.checkout.Session.create(
            idempotency_key=reservation.session_idempotency_key,
            **params,
        )
    except stripe.IdempotencyError as exc:
        # Same key, different parameters — meaning a request under this
        # key exists but we can no longer reproduce it. That is positive
        # evidence a Session was created and we cannot identify it, so it
        # must NOT be read as "nothing exists".
        raise StripeUnavailable(
            f"idempotency replay for reservation {reservation.id} was rejected "
            f"as a parameter mismatch; a Session likely exists: {exc}"
        ) from exc
    except stripe.StripeError as exc:
        raise StripeUnavailable(
            f"idempotency replay for reservation {reservation.id} failed: {exc}"
        ) from exc

    return session["id"] if isinstance(session, dict) else getattr(session, "id", None)


def build_session_params(
    *,
    currency: str,
    unit_amount: int,
    product_name: str,
    product_description: str,
    customer_email: str | None,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str],
    payment_intent_metadata: dict[str, str],
    expires_at: int | None = None,
) -> dict[str, Any]:
    """The exact kwargs for ``Session.create``, built once.

    Built here and persisted before the call so the replay above has
    something byte-identical to re-send. ``expires_at`` is a Unix
    timestamp chosen by the caller, never derived inside this function —
    that is the whole point.
    """
    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": [{
            "price_data": {
                "currency": currency.lower(),
                "product_data": {
                    "name": product_name,
                    "description": product_description,
                },
                "unit_amount": unit_amount,
            },
            "quantity": 1,
        }],
        "metadata": metadata,
        "payment_intent_data": {"metadata": payment_intent_metadata},
        "customer_email": customer_email,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    # Omitted rather than defaulted when absent: undiscounted checkouts
    # keep Stripe's own 24h Session lifetime, which is existing
    # behaviour and not this feature's business to change.
    if expires_at is not None:
        params["expires_at"] = expires_at
    return params
