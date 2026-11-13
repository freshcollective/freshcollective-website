"""Transactional messages for the paid Collective membership lifecycle.

Every member-facing fact is resolved **here**, at emit time, from the
member's own agreement — never later from live rows. A resolver or
template that re-derived a price would describe the creator's current
catalogue rather than what this member agreed to pay, which is the one
thing these messages must get right.

Two properties carried over from ``creator_billing_emit`` because both
were learned the hard way:

* **A comms failure never breaks a billing webhook.** The state
  transition is the fact of record and the email is a courtesy on top
  of it. A raising emit would roll back the caller's transaction and
  leave Stripe retrying something already handled.
* **Dedupe keys are per-occurrence, not per-subscription.** A renewal
  is keyed on its invoice, a failure on the window it opened, an ending
  on when it ended — so a replayed webhook sends nothing while a
  genuinely new occurrence still sends.

The creator is never a recipient. What they get is their Payments
received ledger; the rest of a member's billing is not theirs.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy.orm import Session

from app.core.public_url import public_app_url
from app.models.collective_membership import CollectiveMembership
from app.models.platform import Space
from app.models.user import User

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


def _safe_emit(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> "CommunicationEvent | None":
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "collective_membership_emit: %s failed — the membership "
                "state is unaffected, no message will be sent for this "
                "transition", fn.__name__,
            )
            return None
    return _wrapped


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _money(cents: int | None, currency: str | None) -> str:
    """"A$29" — the member's agreed amount, formatted once, here.

    Whole amounts lose their trailing zeros, because "A$29.00 per month"
    reads like a system and "A$29 per month" reads like a price.
    """
    if cents is None:
        return ""
    symbol = "A$" if (currency or "").upper() == "AUD" else (
        f"{(currency or '').upper()} "
    )
    whole, remainder = divmod(int(cents), 100)
    return f"{symbol}{whole}" if remainder == 0 else (
        f"{symbol}{whole}.{remainder:02d}"
    )


_INTERVALS = {"month": "per month", "year": "per year"}


def _base_payload(
    db: Session, sub: CollectiveMembership,
) -> dict[str, Any]:
    space = db.query(Space).filter(Space.id == sub.space_id).first()
    user = db.query(User).filter(User.id == sub.user_id).first()
    slug = space.slug if space else ""
    return {
        "first_name": ((getattr(user, "name", "") or "").split(" ") or [""])[0],
        "collective_name": space.name if space else "",
        "collective_url": public_app_url(f"/spaces/{slug}") if slug else "",
        "membership_url": public_app_url("/settings/membership"),
        # The agreement, not the catalogue.
        "amount_label": _money(sub.amount_cents, sub.currency),
        "interval_label": _INTERVALS.get(sub.interval, ""),
        "one_time": False,
    }


@_safe_emit
def emit_membership_purchased(
    db: Session, *, sub: CollectiveMembership,
) -> "CommunicationEvent | None":
    """The first verified payment made them a member."""
    from app.comms import Source, emit as comms_emit

    payload = _base_payload(db, sub)
    payload["next_renewal_at"] = _iso(sub.current_period_end)
    return comms_emit(
        db,
        event_type="collective.membership.purchased",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id, "space_id": sub.space_id},
        payload=payload,
        # One welcome per agreement, however many times the activating
        # webhook is replayed.
        dedupe_key=f"cmem_purchased:{sub.id}",
    )


@_safe_emit
def emit_membership_renewed(
    db: Session, *, sub: CollectiveMembership, invoice_id: str,
) -> "CommunicationEvent | None":
    """A later payment landed. Keyed on the invoice, so a replay is silent."""
    from app.comms import Source, emit as comms_emit

    payload = _base_payload(db, sub)
    payload["next_renewal_at"] = _iso(sub.current_period_end)
    start, end = sub.current_period_start, sub.current_period_end
    payload["period_label"] = (
        f"{start.strftime('%-d %B')} to {end.strftime('%-d %B %Y')}"
        if start and end else ""
    )
    return comms_emit(
        db,
        event_type="collective.membership.renewed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id, "invoice_id": invoice_id},
        payload=payload,
        dedupe_key=f"cmem_renewed:{sub.id}:{invoice_id}",
    )


@_safe_emit
def emit_membership_payment_failed(
    db: Session, *, sub: CollectiveMembership,
) -> "CommunicationEvent | None":
    """A NEW grace window opened.

    Keyed on the window's own expiry, so repeated failures inside one
    window stay silent — the window runs from the first failure and does
    not extend — while a later, genuinely separate failure gets its own
    message.
    """
    from app.comms import Source, emit as comms_emit

    payload = _base_payload(db, sub)
    payload["grace_expires_at"] = _iso(sub.grace_expires_at)
    return comms_emit(
        db,
        event_type="collective.membership.payment_failed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id},
        payload=payload,
        dedupe_key=f"cmem_failed:{sub.id}:{_iso(sub.grace_expires_at)}",
    )


@_safe_emit
def emit_membership_cancellation_scheduled(
    db: Session, *, sub: CollectiveMembership,
) -> "CommunicationEvent | None":
    """Renewal stopped; the paid period continues.

    Deliberately not an ending, and the template says so with a date.
    """
    from app.comms import Source, emit as comms_emit

    payload = _base_payload(db, sub)
    payload["access_until"] = _iso(sub.current_period_end)
    return comms_emit(
        db,
        event_type="collective.membership.cancellation_scheduled",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id},
        payload=payload,
        # Keyed on the period it preserves, so cancelling, resuming and
        # cancelling again inside one period sends once, while the same
        # choice in a later period sends again.
        dedupe_key=(
            f"cmem_cancel_sched:{sub.id}:{_iso(sub.current_period_end)}"
        ),
    )


@_safe_emit
def emit_membership_ended(
    db: Session, *, sub: CollectiveMembership,
) -> "CommunicationEvent | None":
    """Access has actually ended — not merely scheduled to."""
    from app.comms import Source, emit as comms_emit

    return comms_emit(
        db,
        event_type="collective.membership.ended",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id},
        payload=_base_payload(db, sub),
        dedupe_key=f"cmem_ended:{sub.id}:{_iso(sub.ended_at)}",
    )


@_safe_emit
def emit_membership_reactivated(
    db: Session, *, sub: CollectiveMembership,
) -> "CommunicationEvent | None":
    """A paused membership came back after a payment."""
    from app.comms import Source, emit as comms_emit

    payload = _base_payload(db, sub)
    payload["next_renewal_at"] = _iso(sub.current_period_end)
    return comms_emit(
        db,
        event_type="collective.membership.reactivated",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=sub.user_id,
        subject_type="collective_membership",
        subject_id=sub.id,
        context={"collective_membership_id": sub.id},
        payload=payload,
        dedupe_key=(
            f"cmem_reactivated:{sub.id}:{_iso(sub.current_period_start)}"
        ),
    )
