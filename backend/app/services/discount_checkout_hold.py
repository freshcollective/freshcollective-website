"""Holding a discount code's slot while a member is away at Stripe.

The protocol itself is not new — the unified Payment Option checkout has
run it since discounts shipped. What is new in Stage 4 is that three more
doors need it: a direct Pathway purchase, a standalone Gathering ticket,
and the Gathering Series entry point. Each builds its Stripe Session a
different way, and none of them can reach the Payment Option
orchestrator's override hooks.

So the protocol moved here rather than being written a second time. §19
rules out a parallel reservation system, and this is the thing that
would have become one: the ordering below is load-bearing in five
separate places, and a near-copy of it in a second door would be a
near-copy of its correctness argument.

The ordering, stated once:

1. **Price the code and take the slot**, under the code's row lock, with
   a single stale-hold sweep if it looks full. Before Stripe, so two
   members cannot both reach a payment page with the last use of a
   one-use code.
2. **Hand back an existing live page** when this member already has one
   for exactly this purchase. A second Session is a second way to pay
   once.
3. **Refuse, and verify, when their own hold is past its window.**
   Whether it is dead is a question for Stripe, not for this request.
4. **Persist the Stripe parameters before calling Stripe**, so a crash
   between the call and recording its id leaves evidence rather than a
   silently free slot.
5. **Release only on positive knowledge.** A failure *before* the
   parameters were persisted is knowledge: we are the party who knows no
   payment page exists. A failure after is not, and falls to the
   verification ladder.

What this module deliberately does not do is build a Stripe Session or
write a ledger row. Each door keeps its own, because what they charge
for and how they record it is genuinely different — and the one thing
they must share is exactly the part that is here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.discount_application import find_code
from app.services.discount_pricing import (
    AppliedDiscount,
    DiscountError,
    DiscountRejection,
)
from app.services.discount_reservations import (
    ReservationAttempt,
    attach_session,
    release,
    reserve_or_reuse,
    sweep_stale_reservations,
    verify_stale_reservation,
    _jsonable,
)

logger = logging.getLogger(__name__)


class LiveSessionExists(Exception):
    """This member already has a payment page for exactly this purchase.

    Raised rather than returned so a caller cannot accidentally continue
    and open a second one. Carries what the door needs to answer with.
    """

    def __init__(self, *, checkout_url: str, transaction_id: str) -> None:
        super().__init__("a live checkout session already exists")
        self.checkout_url = checkout_url
        self.transaction_id = transaction_id


@dataclass
class DiscountHold:
    """A reserved slot, and the Stripe parameters it pins down.

    ``txn_id`` is decided here rather than by the door, because the
    reservation recorded an intended transaction id before Stripe was
    ever called — that is what lets a recovery replay identify the same
    purchase instead of creating a second one.
    """

    applied: AppliedDiscount
    reservation: Any
    db: Session
    #: Whatever the pricing step returned. For a single charge that is
    #: ``applied`` again; for a finite plan it is the
    #: ``DiscountedPlanQuote``, which carries the instalment schedule the
    #: plan row needs. Declared rather than attached afterwards so a
    #: reader can see that a plan door has somewhere to find its
    #: schedule without resolving the code a third time.
    quote: Any = None

    @property
    def txn_id(self) -> str | None:
        return self.reservation.intended_payment_transaction_id

    @property
    def session_expires_at(self) -> datetime:
        return self.reservation.session_expires_at

    @property
    def idempotency_key(self) -> str:
        return self.reservation.session_idempotency_key

    @property
    def expires_at_unix(self) -> int:
        """``session_expires_at`` as Stripe's ``expires_at``.

        The SAME instant the reservation will be judged stale against, so
        "past expiry" cannot come to mean two different things on the two
        sides of the boundary.
        """
        return int(self.reservation.session_expires_at.timestamp())

    def persist_params(self, params: dict) -> None:
        """Store the exact Stripe kwargs, and commit, before the call.

        This runs microseconds before the network request, and it is the
        only reason a crash between creating a Session and recording its
        id is recoverable: without the params the reservation looks like
        one that never reached Stripe, and releasing it would free a slot
        a member may already have paid for.
        """
        self.reservation.session_create_params_json = _jsonable(params)
        self.db.commit()

    def attach(self, *, session_id: str, session_url: str | None, txn_id: str,
               now: datetime) -> None:
        """Record the Session this hold produced."""
        self.reservation.provider_checkout_session_url = session_url
        attach_session(
            self.db,
            reservation=self.reservation,
            session_id=session_id,
            session_params=self.reservation.session_create_params_json or {},
            payment_transaction_id=txn_id,
            now=now,
        )

    def abandon(self, *, now: datetime, reason: str = "session_create_failed") -> None:
        """Give the slot back — but only if we know nothing can charge.

        Guarded on the parameters never having been persisted. If they
        were, a Session may exist despite the error, and releasing would
        be a guess rather than knowledge; those fall to the verification
        ladder instead.
        """
        self.db.rollback()
        self.db.refresh(self.reservation)
        if self.reservation.session_create_params_json is None:
            release(self.db, reservation=self.reservation, reason=reason, now=now)
            return
        logger.warning(
            "Discount reservation %s left held after a failed checkout: "
            "Stripe params were already sent, so a Session may exist. "
            "Verification will decide.",
            self.reservation.id,
        )


def open_hold(
    db: Session,
    *,
    raw_code: str | None,
    space_id: str,
    attempt: ReservationAttempt,
    price: Callable[[ReservationAttempt], Any],
    now: datetime,
) -> DiscountHold | None:
    """Price the code and hold its slot, or explain why not.

    Returns ``None`` when no code was supplied, so a door can call this
    unconditionally and branch on the result.

    ``price`` takes the attempt and returns either an
    :class:`AppliedDiscount` or anything carrying one as ``.applied`` —
    the finite-plan resolver returns the latter. Parameterised rather
    than branched on, because what differs between a single charge and a
    commitment is only the price.

    Raises:

    * :class:`DiscountError` — the code cannot be used. The door maps it
      to its own status and wording.
    * :class:`LiveSessionExists` — hand the member back the page they
      already have.
    * ``HTTPException(409)`` — their own hold is past its window and
      Stripe has now been asked about it.
    """
    if not raw_code:
        return None

    quote, outcome = _reserve_with_sweep(
        db, raw_code=raw_code, space_id=space_id, attempt=attempt,
        price=price, now=now,
    )
    reservation = outcome.reservation
    applied = quote if isinstance(quote, AppliedDiscount) else quote.applied

    if outcome.reused:
        if (
            reservation.provider_checkout_session_id
            and now < reservation.session_expires_at
            and reservation.provider_checkout_session_url
        ):
            logger.info(
                "Discount checkout: reusing reservation=%s session=%s user=%s",
                reservation.id, reservation.provider_checkout_session_id,
                attempt.user_id,
            )
            raise LiveSessionExists(
                checkout_url=reservation.provider_checkout_session_url,
                transaction_id=(
                    reservation.payment_transaction_id
                    or reservation.intended_payment_transaction_id
                    or reservation.id
                ),
            )
        if now >= reservation.session_expires_at:
            # Their own hold is past its window. Whether it is dead is a
            # question for Stripe, not for this request — opening a
            # second Session before knowing could charge them twice.
            verdict = verify_stale_reservation(db, reservation=reservation, now=now)
            raise HTTPException(
                status_code=409,
                detail=(
                    "That checkout has already been completed."
                    if verdict == "completed" else
                    "Your previous checkout for this offer timed out. "
                    "Please start again."
                ),
            )

    return DiscountHold(
        applied=applied, reservation=reservation, db=db, quote=quote,
    )


def _reserve_with_sweep(
    db: Session, *, raw_code, space_id, attempt, price, now,
):
    """Resolve and reserve, sweeping stale holds once if the code looks full.

    Both steps live behind one sweep because either can be the thing that
    reports a full code: the resolver refuses when the slot count has
    reached the limit, and ``reserve_or_reuse`` refuses again under the
    row lock. A stale hold — one whose checkout window elapsed but which
    nothing has verified — makes both refuse for a reason that may not be
    true any more.

    So on the first ``LIMIT_REACHED`` from either step, the stale holds
    for that code are verified against Stripe, OUTSIDE the row lock, and
    the pair is attempted once more. One retry only: if the second
    attempt still refuses, the holds are genuinely live or genuinely
    unverifiable, and looping would spend more time reaching the same
    answer.
    """
    def once():
        quote = price(attempt)
        applied = quote if isinstance(quote, AppliedDiscount) else quote.applied
        code_row = find_code(db, raw_code=raw_code, space_id=space_id)
        outcome = reserve_or_reuse(
            db, applied=applied, code=code_row, attempt=attempt, now=now,
        )
        return quote, outcome

    try:
        return once()
    except DiscountError as first:
        if first.reason is not DiscountRejection.LIMIT_REACHED:
            raise
        code_row = find_code(db, raw_code=raw_code, space_id=space_id)
        if code_row is None:
            raise
        if not sweep_stale_reservations(db, discount_code_id=code_row.id, now=now):
            raise
        logger.info(
            "Discount slot freed by verification sweep: code=%s user=%s",
            code_row.id, attempt.user_id,
        )
        return once()
