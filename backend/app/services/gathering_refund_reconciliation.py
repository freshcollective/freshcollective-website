"""When a Gathering ticket is fully refunded, the seat should go back.

The gap this closes
-------------------
``charge.refunded`` has always reconciled the *money* completely and
idempotently — cumulative amounts, fee-split reversal, transaction
status, the member's refund confirmation. It has never touched the
booking. A fully refunded $45 ticket therefore left a **confirmed**
booking occupying one of eighteen places, and an **active** AccessPass
granting entry to a Gathering the member had been paid back for. The
note in ``spaces/routes.py`` called this a documented MVP gap; with
ticket sales live it stopped being theoretical.

What this does and deliberately does not do
-------------------------------------------
Financial refunds and access revocation were separated on purpose in
this architecture, and that separation is kept. This is **not** a rule
that revokes access whenever money moves back. It is narrow on three
axes:

``transaction_type``
    Only ``gathering_ticket_purchase``. A refunded Pathway purchase,
    Series pass or Offering is not this function's business.
``fully refunded``
    Only when the transaction has reached ``refunded``. A partial
    refund keeps the booking, the seat and the access — the member is
    still coming, and the creator has made a goodwill adjustment, not
    a cancellation.
``this ticket's own records``
    The booking carrying this ``payment_transaction_id`` and the
    AccessPass carrying it. Nothing else. A member who also holds a
    Series pass, a Pathway entitlement or a second ticket keeps every
    one of them, because those are different rows with different
    payment transactions behind them.

Explicitly untouched, each for a stated reason:

* **Collective membership.** Buying a seat brings somebody into the
  Collective; being refunded for one seat is not grounds for removing
  them from it. Reversing that would evict people from Collectives they
  may have been part of for months.
* **Channel membership.** The Conversations seat admitted at
  fulfilment. Removing somebody from a conversation is a social act
  with its own notification consequences, and nothing here is urgent
  enough to justify one. Noted as a gap rather than acted on.
* **Attendance records.** History. If a creator marked somebody
  present, they were present, whatever happened to the money.
* **Every financial field.** Amounts, fee reversals, payout snapshots
  and the transaction's own status belong to the refund handler. This
  function reads the status and writes none of it.

Capacity
--------
No new accounting. The capacity predicate counts bookings with
``status IN ('confirmed','pending_payment')``, so moving the row to
``cancelled`` *is* releasing the seat — there is one definition of a
taken seat and this does not add a second.

Idempotency
-----------
Stripe redelivers, and a refund can arrive as several events. Every
decision is made from current row state under a lock, and a booking
that is already ``cancelled`` is left alone. Running this ten times
produces the same single cancellation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import BookingStatus, EventBooking

logger = logging.getLogger(__name__)

#: The note appended to a booking cancelled this way, so the reason is
#: legible to a creator reading the booking later.
CANCELLATION_NOTE = "cancelled automatically — ticket fully refunded"


@dataclass(frozen=True)
class ReconcileOutcome:
    """What happened, in terms safe to log.

    ``skipped_reason`` is the interesting field: almost every call is a
    skip, because almost every refunded transaction is not a fully
    refunded Gathering ticket.
    """

    applied: bool
    skipped_reason: str | None = None
    booking_id: str | None = None
    access_pass_id: str | None = None
    event_id: str | None = None


def _skip(reason: str) -> ReconcileOutcome:
    return ReconcileOutcome(applied=False, skipped_reason=reason)


def reconcile_fully_refunded_ticket(
    db: Session, *, txn: PaymentTransaction,
) -> ReconcileOutcome:
    """Cancel the booking and ticket access behind a fully refunded
    Gathering ticket.

    Called from the ``charge.refunded`` handler **inside its
    transaction**, deliberately. If this fails, the ledger write rolls
    back with it and Stripe retries the whole event — which is the
    outcome to want: a recorded refund whose seat stayed sold is the
    exact inconsistency being fixed here, so a half-applied refund is
    worse than a retried one. Every unexpected condition is a *skip*
    rather than a raise, so only a genuine database failure can reach
    that path.

    Returns an outcome rather than raising on "nothing to do", because
    nothing to do is the normal case.
    """
    if txn.transaction_type != PaymentTransactionType.gathering_ticket_purchase:
        return _skip("not_a_gathering_ticket")

    # The refund handler owns this status and has already applied its
    # monotonic guard, so reading it here means a partial refund that
    # later completes is handled by the event that completes it — no
    # separate arithmetic, and no second opinion about what "fully
    # refunded" means.
    if txn.status != PaymentTransactionStatus.refunded:
        return _skip("not_fully_refunded")

    booking = (
        db.query(EventBooking)
        .filter(EventBooking.payment_transaction_id == txn.id)
        .first()
    )
    if booking is None:
        # A refunded ticket with no booking: a hold released before
        # fulfilment, or a Dashboard refund against a transaction that
        # never completed. Nothing to release.
        return _skip("no_booking")

    event_id = booking.event_id

    # Lock the Event row first, then the booking — the same order
    # ``fulfil_ticket_purchase`` and ``create_or_reuse_hold`` use, so a
    # refund arriving while somebody is buying the last seat serialises
    # with them instead of deadlocking against them.
    db.execute(text("SELECT id FROM events WHERE id = :id FOR UPDATE"),
               {"id": event_id})
    db.execute(text("SELECT id FROM event_bookings WHERE id = :id FOR UPDATE"),
               {"id": booking.id})
    db.refresh(booking)

    if booking.status == BookingStatus.cancelled:
        # Already released — a redelivered event, or a member who
        # cancelled before the refund landed. Leave the existing
        # ``cancelled_at`` alone: the first cancellation is the true
        # one, and overwriting it would rewrite history to match a
        # webhook's arrival time.
        return ReconcileOutcome(
            applied=False, skipped_reason="booking_already_cancelled",
            booking_id=booking.id, event_id=event_id,
        )

    now = datetime.utcnow()
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = now
    # A confirmed booking has no hold, but a ``pending_payment`` row
    # refunded mid-flight would; clearing it keeps the two consistent.
    booking.hold_expires_at = None
    booking.note = f"{booking.note or ''}\n[{CANCELLATION_NOTE}]".strip()

    # The ticket's own AccessPass, found by the same transaction that
    # paid for it — never by user and event, which would also match a
    # pass somebody holds through a Series or a second purchase.
    access_pass = (
        db.query(AccessPass)
        .filter(AccessPass.payment_transaction_id == txn.id)
        .first()
    )
    pass_id = None
    if access_pass is not None:
        pass_id = access_pass.id
        if access_pass.status == AccessPassStatus.active:
            access_pass.status = AccessPassStatus.cancelled

    db.flush()

    logger.info(
        "gathering ticket refund reconciled: txn=%s event=%s booking=%s "
        "access_pass=%s seat released",
        txn.id, event_id, booking.id, pass_id or "-",
    )
    return ReconcileOutcome(
        applied=True, booking_id=booking.id,
        access_pass_id=pass_id, event_id=event_id,
    )


__all__ = [
    "CANCELLATION_NOTE",
    "ReconcileOutcome",
    "reconcile_fully_refunded_ticket",
]
