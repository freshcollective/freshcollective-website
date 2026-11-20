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
from typing import TYPE_CHECKING, Any, Callable, Final

from sqlalchemy.orm import Session

from app.core.public_url import public_app_url
from app.models.collective_membership import (
    CollectiveMembership, is_one_time,
)
from app.models.platform import Space
from app.models.user import User

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


#: Session key holding events emitted here and not yet routed.
#:
#: Routing cannot run inside the transaction that produced the event.
#: ``_route_event_bg`` opens its **own** session and looks the event up
#: by id, so an event that is merely flushed is invisible to it — it
#: logs "event … vanished before routing" and delivers nothing. The
#: queue exists so the decision to route survives until after the
#: commit, which is the only moment it can succeed.
_PENDING_ROUTING: Final = "collective_membership_pending_routing"


def _queue_for_routing(db: Session, event: "CommunicationEvent | None") -> None:
    """Remember an emitted event so it can be routed after the commit."""
    if event is None:
        return
    db.info.setdefault(_PENDING_ROUTING, []).append(event)


def route_pending(db: Session) -> int:
    """Schedule routing for every membership event this session committed.

    **Call only after a successful commit.** The caller owns the
    transaction and only the caller knows it succeeded; this function
    deliberately does not commit, check, or guess.

    ``schedule_routing_if_needed`` is the one call every other trigger
    site in the codebase makes after ``emit()`` — twenty-four modules
    do, and membership did not, which is why the first real membership
    payment produced an event that was written, committed, and never
    delivered. ``background_tasks=None`` runs it inline, matching
    ``creator_billing_handlers``: a webhook has no request-scoped
    background tasks to hang it on.

    Never raises. A message that cannot be scheduled must not turn a
    collected payment into a failed one.
    """
    pending = db.info.pop(_PENDING_ROUTING, [])
    if not pending:
        return 0
    from app.comms.rollout import schedule_routing_if_needed

    routed = 0
    for event in pending:
        try:
            schedule_routing_if_needed(None, event, event.event_type)
            routed += 1
        except Exception:
            logger.exception(
                "collective_membership_emit: could not schedule routing "
                "for event %s — the membership and the payment are "
                "unaffected and the event remains routable",
                getattr(event, "id", "?"),
            )
    return routed


def discard_pending(db: Session) -> None:
    """Forget queued events after a rollback.

    The events went away with the transaction. Routing them would ask
    the delivery layer for rows that no longer exist.
    """
    db.info.pop(_PENDING_ROUTING, None)


def _safe_emit(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> "CommunicationEvent | None":
        try:
            event = fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "collective_membership_emit: %s failed — the membership "
                "state is unaffected, no message will be sent for this "
                "transition", fn.__name__,
            )
            return None
        # Queued here rather than at each call site, so all six
        # notifications are covered by one rule and a seventh cannot
        # be added without it.
        db = kwargs.get("db")
        if db is None and args and isinstance(args[0], Session):
            db = args[0]
        if db is not None:
            _queue_for_routing(db, event)
        return event
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


#: How an agreement's interval is said to a member.
#:
#: ``one_time`` reads "once", not "per once" — the templates compose
#: this straight after the amount, so "A$199 once" is the sentence.
_INTERVALS = {"month": "per month", "year": "per year", "one_time": "once"}


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
        # Derived, not assumed. This was hard-coded False while a
        # one-off joining fee could not be bought; once 5A.3c made it
        # buyable, leaving it would have told somebody who paid once
        # that their membership "continues until you cancel it" —
        # the misleading renewal reference §13 forbids, sent to the
        # one member it is least true of.
        "one_time": is_one_time(sub),
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
