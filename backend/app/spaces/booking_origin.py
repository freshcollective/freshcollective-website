"""Where a member's place at a Gathering actually came from.

Why this exists
---------------
``my_booking_status`` answers "does this person have a place?". The
member surface was reading it as "did this person buy the standalone
ticket?", and those are different questions whenever a Gathering can be
reached by more than one route.

The production symptom: a member started an instalment checkout for a
Payment Option bundling a Gathering and a Pathway. That opens a seat
hold, so the Gathering's booking went to ``pending_payment`` — and the
*Individual ticket* card, which branches on exactly that value, showed
"Payment in progress / Continue checkout" for a purchase the member had
never begun. After the plan completed, the same card read "Ticket
purchased" for a ticket they had not bought.

Nothing was wrong with the booking. The seat is real either way; only
its provenance was being misreported.

No new tracking model is introduced, because the answer is already on
the row. ``EventBooking.source`` is stamped by whichever path created
the seat, and the two that matter here are already distinct:
``gathering_tickets`` writes ``ticket_purchase`` for a standalone
ticket, while both the plan hold and ``purchase_fulfilment`` write
``payment_option``. The Option itself is then named through the
``purchase_plan_id`` or ``payment_transaction_id`` the same row
carries.

====================  ==========================================
``direct_ticket``     ``source == 'ticket_purchase'``
``payment_option``    ``source == 'payment_option'``; the Option is
                      resolved through the plan or the transaction
``series_pass``       ``access_pass_id`` — a credit was spent
``creator_manual``    ``source in ('creator_manual', 'creator_pass')``
``other``             a place with none of the above — free,
                      included with the Collective, or a legacy row
====================  ==========================================

``source`` is checked before the id columns rather than after, because
it is the field each creating path sets deliberately; the ids are
plumbing for the expiry sweep and are nullable on purpose
(``ondelete='SET NULL'``). The ids are still consulted — to name the
Option, and to classify rows written before ``source`` was populated.

Related but deliberately not reused: ``ticket_summary._booking_label``
produces *creator*-facing labels (Paid ticket / Complimentary / Creator
added), mixes booking status into the answer, and does not separate a
Payment Option from a standalone ticket — which is the whole question
here.

Read-only and presentation-facing. It reads rows; it never writes one,
and it never decides whether access exists — that remains
``my_booking_status``'s job. A surface that cannot resolve an origin
shows the booking and says nothing about where it came from, which is
the honest answer rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction, PaymentTransactionType
from app.models.payment_option import PaymentOption
from app.models.platform import EventBooking
from app.models.purchase_plan import PurchasePlan

KIND_DIRECT_TICKET = "direct_ticket"
KIND_PAYMENT_OPTION = "payment_option"
KIND_SERIES_PASS = "series_pass"
KIND_CREATOR_MANUAL = "creator_manual"
KIND_OTHER = "other"


@dataclass(frozen=True)
class BookingOrigin:
    """What produced this place, in terms a member surface can render."""

    kind: str
    #: Set only for ``payment_option``. The surface uses it to show the
    #: status against the arrangement that actually earned the place,
    #: and to keep it off the others.
    payment_option_id: str | None = None
    #: The Option's name, for "Included with {name}". Resolved here so
    #: the page does not have to find a card to borrow it from — the
    #: Option may not even be among the cards on offer, having since
    #: been archived or restricted.
    payment_option_name: str | None = None

    def as_payload(self) -> dict:
        return {
            "kind": self.kind,
            "payment_option_id": self.payment_option_id,
            "payment_option_name": self.payment_option_name,
        }


def _option_name(db: Session, option_id: str | None) -> str | None:
    if not option_id:
        return None
    row = (
        db.query(PaymentOption.name)
        .filter(PaymentOption.id == option_id)
        .first()
    )
    return row[0] if row else None


def resolve_booking_origin(
    db: Session, booking: EventBooking | None,
) -> BookingOrigin | None:
    """The origin of one booking, or ``None`` when there is no booking.

    Ordered most specific first. A plan is checked before a transaction
    because an instalment plan's seat is held before any transaction
    exists, which is the case the production defect ran through.
    """
    if booking is None:
        return None

    source = (booking.source or "").strip()

    # 1. A Payment Option — bought outright or by instalments. Both
    #    fulfilment paths stamp this, and it is the case the production
    #    defect ran through.
    if source == "payment_option":
        option_id = _option_id_for(db, booking)
        return BookingOrigin(
            kind=KIND_PAYMENT_OPTION,
            payment_option_id=option_id,
            payment_option_name=_option_name(db, option_id),
        )

    # 2. The standalone ticket for this Gathering, bought on its own.
    if source == "ticket_purchase":
        return BookingOrigin(kind=KIND_DIRECT_TICKET)

    # 3. Added by a caretaker — complimentary, comped, or put right by
    #    hand. ``creator_pass`` spends a pass the creator holds; either
    #    way the member did not buy it here.
    if source in ("creator_manual", "creator_pass"):
        return BookingOrigin(kind=KIND_CREATOR_MANUAL)

    # 4. A Series pass spending a credit. Eligibility to book is not a
    #    reservation; this is the reservation, earned by the pass.
    if booking.access_pass_id:
        return BookingOrigin(kind=KIND_SERIES_PASS)

    # 5. Rows written before ``source`` carried these values still have
    #    their plumbing, so fall back to it rather than shrugging.
    option_id = _option_id_for(db, booking)
    if option_id:
        return BookingOrigin(
            kind=KIND_PAYMENT_OPTION,
            payment_option_id=option_id,
            payment_option_name=_option_name(db, option_id),
        )
    if booking.payment_transaction_id:
        txn_type = (
            db.query(PaymentTransaction.transaction_type)
            .filter(PaymentTransaction.id == booking.payment_transaction_id)
            .scalar()
        )
        if txn_type == PaymentTransactionType.gathering_ticket_purchase:
            return BookingOrigin(kind=KIND_DIRECT_TICKET)

    # 6. A real place with no purchase behind it — free, or included
    #    with membership of the Collective.
    return BookingOrigin(kind=KIND_OTHER)


def _option_id_for(db: Session, booking: EventBooking) -> str | None:
    """The Payment Option behind this seat, through whichever link it has.

    A plan is consulted first: an instalment seat is held before any
    transaction exists, which is exactly when the member is looking at
    the page and wondering what is happening.
    """
    if booking.purchase_plan_id:
        option_id = (
            db.query(PurchasePlan.payment_option_id)
            .filter(PurchasePlan.id == booking.purchase_plan_id)
            .scalar()
        )
        if option_id:
            return option_id
    if booking.payment_transaction_id:
        option_id = (
            db.query(PaymentTransaction.payment_option_id)
            .filter(PaymentTransaction.id == booking.payment_transaction_id)
            .scalar()
        )
        if option_id:
            return option_id
    return None
