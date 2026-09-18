"""Comms emit helpers for the creator monthly-subscription lifecycle.

Mirrors ``app/services/purchase_lifecycle_emit.py`` for the member
finite-plan lifecycle: one helper per genuine state transition, each
wrapped so a comms failure can never break the billing webhook that
called it.

Transition points (all in ``app/webhooks/creator_billing_handlers.py``):

===========================================  ==================================
Transition                                   Event
===========================================  ==================================
``invoice.payment_failed`` opens a NEW        ``creator.subscription.payment_failed``
grace window (``grace_expires_at`` was NULL)
``invoice.paid`` while ``past_due``           ``creator.subscription.recovered``
``cancel_at_period_end`` False → True         ``creator.subscription.cancellation_scheduled``
``customer.subscription.deleted``             ``creator.subscription.cancelled``
===========================================  ==================================

Each helper is called only on the genuine transition, so Stripe's
retry cadence (several ``invoice.payment_failed`` events inside one
grace window) produces exactly one email. Duplicate webhook deliveries
are already short-circuited upstream by ``claim_event``.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.creator_billing import CreatorSubscription
from app.models.user import User
from app.services.creator_plan_labels import creator_facing_plan_label

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent


logger = logging.getLogger(__name__)


def _safe_emit(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Never let a comms failure break a billing webhook.

    The billing state transition is the fact of record; the email is a
    courtesy on top of it. A raising emit would roll back the caller's
    transaction and leave Stripe retrying a webhook we already handled.
    """
    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> "CommunicationEvent | None":
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "creator_billing_emit: %s failed — billing state is "
                "unaffected, no email will be sent for this transition",
                fn.__name__,
            )
            return None
    return _wrapped


def _billing_url() -> str:
    return f"{settings.frontend_origin.rstrip('/')}/creator-studio/billing"


def _first_name(user: User | None) -> str:
    if user is None or not user.name:
        return ""
    return user.name.strip().split(" ", 1)[0]


def _plan_label(sub: CreatorSubscription) -> str:
    """Creator-facing plan label. Never the internal ``Pro``."""
    plan = getattr(sub, "plan", None)
    return creator_facing_plan_label(
        slug=getattr(plan, "slug", None),
        name=getattr(plan, "name", None),
    )


def _base_payload(db: Session, sub: CreatorSubscription) -> dict[str, Any]:
    user = db.query(User).filter(User.id == sub.user_id).first()
    return {
        "first_name":  _first_name(user),
        "plan_label":  _plan_label(sub),
        "billing_url": _billing_url(),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@_safe_emit
def emit_subscription_payment_failed(
    db: Session, *, sub: CreatorSubscription,
) -> "CommunicationEvent | None":
    """A creator invoice failed and a NEW grace window just opened.

    Called only when ``grace_expires_at`` moved from NULL to a date, so
    repeated failures inside one window stay silent — the window runs
    from the first failure and does not extend.
    """
    from app.comms import Source, emit as comms_emit
    payload = _base_payload(db, sub)
    payload["grace_expires_at"] = _iso(sub.grace_expires_at)
    return comms_emit(
        db,
        event_type="creator.subscription.payment_failed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="creator_subscription",
        subject_id=sub.id,
        context={"creator_subscription_id": sub.id},
        payload=payload,
        # One email per grace window. Keyed on the window's own expiry
        # so a later, genuinely separate failure gets its own email.
        dedupe_key=f"creator_sub_failed:{sub.id}:{_iso(sub.grace_expires_at)}",
    )


@_safe_emit
def emit_subscription_recovered(
    db: Session, *, sub: CreatorSubscription, period_end: Any = None,
) -> "CommunicationEvent | None":
    """An invoice was paid while the subscription was ``past_due``.

    Only fires on genuine recovery — an ``invoice.paid`` for an already
    ``active`` subscription is the ordinary monthly renewal and sends
    nothing.
    """
    from app.comms import Source, emit as comms_emit
    payload = _base_payload(db, sub)
    payload["current_period_end"] = _iso(period_end or sub.current_period_end)
    return comms_emit(
        db,
        event_type="creator.subscription.recovered",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="creator_subscription",
        subject_id=sub.id,
        context={"creator_subscription_id": sub.id},
        payload=payload,
        dedupe_key=(
            f"creator_sub_recovered:{sub.id}:"
            f"{_iso(period_end or sub.current_period_end)}"
        ),
    )


@_safe_emit
def emit_subscription_cancellation_scheduled(
    db: Session, *, sub: CreatorSubscription,
) -> "CommunicationEvent | None":
    """``cancel_at_period_end`` flipped False → True.

    The subscription stays active until ``current_period_end``; nothing
    is lost yet. Only the transition emits, so repeated
    ``customer.subscription.updated`` deliveries that merely restate an
    already-scheduled cancellation stay silent.
    """
    from app.comms import Source, emit as comms_emit
    payload = _base_payload(db, sub)
    payload["current_period_end"] = _iso(sub.current_period_end)
    return comms_emit(
        db,
        event_type="creator.subscription.cancellation_scheduled",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="creator_subscription",
        subject_id=sub.id,
        context={"creator_subscription_id": sub.id},
        payload=payload,
        dedupe_key=(
            f"creator_sub_cancel_scheduled:{sub.id}:"
            f"{_iso(sub.current_period_end)}"
        ),
    )


@_safe_emit
def emit_subscription_cancelled(
    db: Session, *, sub: CreatorSubscription,
) -> "CommunicationEvent | None":
    """The Stripe subscription has actually ended.

    Distinct from ``cancellation_scheduled`` — this is the moment paid
    capability stops, not the moment it was scheduled to stop.
    """
    from app.comms import Source, emit as comms_emit
    payload = _base_payload(db, sub)
    payload["ended_at"] = _iso(sub.ends_at)
    return comms_emit(
        db,
        event_type="creator.subscription.cancelled",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="creator_subscription",
        subject_id=sub.id,
        context={"creator_subscription_id": sub.id},
        payload=payload,
        # A subscription ends once. Keyed on the row alone so any
        # replay is collapsed.
        dedupe_key=f"creator_sub_cancelled:{sub.id}",
    )


__all__ = [
    "emit_subscription_cancellation_scheduled",
    "emit_subscription_cancelled",
    "emit_subscription_payment_failed",
    "emit_subscription_recovered",
]
