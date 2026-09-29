"""
Service layer for standalone paid Gathering tickets.

Everything the Stage 2B checkout endpoint and the Stripe webhook branch
need to safely reserve capacity, create/reuse holds, and fulfil a
successful payment lives here. The HTTP router is a thin wrapper; the
webhook handler dispatches into `fulfil_ticket_purchase`.

Design invariants (each enforced in code AND in tests):

  I1. Client never supplies price, currency, or user identity. Every
      trust-sensitive value is loaded from the database.
  I2. Capacity is calculated as confirmed + pending_payment. NO clock
      appears in that sum, and that is the whole point: a hold is a seat
      until FC has POSITIVE KNOWLEDGE the checkout behind it can no
      longer complete.

      The previous rule counted only holds whose ``hold_expires_at`` was
      still in the future, which oversold. A buyer who paid at 10:59:59
      against a hold expiring at 11:00, whose webhook arrived at 11:01,
      had their seat sold to somebody else at 11:00 — and then got it
      too, because fulfilment does not consult the clock either (I6). Two
      confirmed bookings, one seat.

      A stalled buyer therefore does hold a seat past the window. It is
      returned by ``release_hold_for_transaction`` on Stripe's expiry
      webhook, or by ``verify_stale_hold`` asking Stripe directly when
      another buyer wants it — never by the clock alone.
  I3. Hold creation acquires SELECT ... FOR UPDATE on the Event row.
      Concurrent last-seat buyers serialise on that lock; the loser
      sees sold_out before Stripe is ever contacted.
  I4. If the same user retries checkout with an EXPIRED hold, the
      existing row is reused (UPDATE) rather than a new row inserted.
      This avoids UNIQUE(event_id, user_id) violations and keeps the
      audit trail single-file per (user, event).
  I5. If the same user retries with an ACTIVE hold, they get the
      original Stripe Checkout URL back — no new Session, no new hold.
  I6. Fulfilment (webhook) SELECT ... FOR UPDATE both the hold row and
      the event row. It refuses to fulfil a hold that has been cancelled
      or does not match the trusted metadata.

      It deliberately does NOT check ``hold_expires_at``. This file used
      to claim it did; it never has, and it must not start. Stripe
      retries for days and our own processing can lag, so a completion
      arriving after the window is still a completion — refusing it would
      take the member's money and give them nothing, which is worse than
      the oversell the window exists to prevent. Capacity safety comes
      from I2 keeping the seat counted, not from rejecting late payment.
  I7. Repeated webhook delivery is a no-op after the first successful
      fulfilment (idempotency via status='succeeded' short-circuit and
      UNIQUE constraints on the resulting rows).
  I8. Live-mode guard: `standalone_gathering_sales_enabled` must be True.
      If Stripe is in live mode, this flag is the only path in — no
      accidental live-mode sales.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.access_pass import (
    AccessPass,
    AccessPassEvent,
    AccessPassStatus,
    AccessPassSource,
    AccessPassType,
)
from app.services.connect_payout_model import resolve_payout_model
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import BookingStatus, Event, EventBooking, Space
from app.models.user import User
from app.services import membership_grant as _membership_grant
from app.services.ticket_pricing import (
    SUPPORTED_CURRENCIES,
    TicketPricingError,
    validate_paid_gathering_price,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom, HTTP-agnostic exceptions. The router maps these to status codes.
# ---------------------------------------------------------------------------

class TicketCheckoutError(Exception):
    """Base — router maps to a specific HTTP code via subclass."""
    http_status: int = 400
    code: str = "ticket_checkout_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TicketSalesDisabled(TicketCheckoutError):
    http_status = 503
    code = "sales_disabled"


class NotAPaidGathering(TicketCheckoutError):
    http_status = 409
    code = "not_paid_gathering"


class GatheringUnavailable(TicketCheckoutError):
    """Event is unpublished, cancelled, ended, or booking has closed."""
    http_status = 409
    code = "gathering_unavailable"


class FulfilmentTerminal(TicketCheckoutError):
    """Fulfilment cannot succeed, and retrying will not change that.

    An amount that does not match, a currency that does not match, a
    transaction that does not exist, a booking already cancelled. Retrying
    these hammers Stripe for days and reaches the same answer; they need a
    person. Raised as a distinct type so the webhook can acknowledge the
    delivery deliberately rather than by swallowing everything.
    """


class FulfilmentRetryable(TicketCheckoutError):
    """Fulfilment failed for a reason that may not hold next time.

    A missing hold row is the real case: a read racing a write that has
    not committed yet. Stripe redelivers, and the second attempt usually
    finds it. Distinguished from terminal because the cost of getting this
    wrong is a member who paid and silently got nothing.
    """


class SoldOut(TicketCheckoutError):
    http_status = 409
    code = "sold_out"


class AlreadyHasTicket(TicketCheckoutError):
    """User already has a confirmed booking for this event."""
    http_status = 409
    code = "already_has_ticket"


class InvalidTicketConfig(TicketCheckoutError):
    """Event's ticket_price_cents / ticket_currency is missing or invalid.
    This should never happen at runtime — the CHECK constraint prevents
    publishing a paid event without valid price+currency."""
    http_status = 500
    code = "invalid_ticket_config"


# ---------------------------------------------------------------------------
# Configuration guard — invoked at the top of the checkout endpoint AND at
# the top of every webhook branch. If tests want to bypass, they patch
# `settings.standalone_gathering_sales_enabled` and `settings.stripe_mode`.
# ---------------------------------------------------------------------------

def ensure_sales_enabled_or_raise() -> None:
    """
    Two-tier live-mode guard:
      1. `standalone_gathering_sales_enabled` must be True. Default False.
      2. If Stripe is in live mode, `standalone_gathering_sales_enabled`
         alone is not enough — this is the tier where the operator has
         separately confirmed payout/merchant-of-record before flipping
         the flag on. Reported at Stage 1 as a live-mode blocker until
         Stripe Connect is implemented.

    In test mode with the flag set, we proceed. In dev with the flag
    unset (the default), we refuse — surfaces the misconfiguration
    early instead of failing at Stripe API time.
    """
    if not settings.standalone_gathering_sales_enabled:
        raise TicketSalesDisabled(
            "Standalone Gathering ticket sales are disabled on this "
            "environment. Set STANDALONE_GATHERING_SALES_ENABLED=true in "
            ".env to enable in Stripe test mode."
        )
    # NOTE: Stage 5 will add the additional live-mode confirmation gate
    # (`standalone_gathering_live_confirmed`). Until then, live keys are
    # refused outright by the operator convention (dev/test uses sk_test_).


# ---------------------------------------------------------------------------
# Capacity SQL — invariant I2. Copy-pasted deliberately so callers can't
# accidentally forget the timezone() call.
# ---------------------------------------------------------------------------

#: Seats taken. Both live states count, with no clock in the predicate —
#: see invariant I2. A ``pending_payment`` row stops consuming a seat only
#: when something moves it to ``cancelled`` or ``confirmed``, and only
#: positive knowledge does that.
CAPACITY_USED_SQL = text("""
    SELECT COUNT(*)
    FROM event_bookings
    WHERE event_id = :event_id
      AND status IN ('confirmed', 'pending_payment')
""")


def capacity_used(db: Session, event_id: str) -> int:
    """Seats taken: confirmed bookings plus every unresolved hold.

    "Unresolved" is a status, not a deadline. A hold past its window is
    still counted, because the buyer behind it may be completing payment
    at this moment and a seat given away on that assumption is a seat
    sold twice.
    """
    return int(db.execute(CAPACITY_USED_SQL, {"event_id": event_id}).scalar_one())


# ---------------------------------------------------------------------------
# Trusted event validation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrustedTicketOffer:
    """Everything the checkout endpoint needs, resolved from the DB — never
    from client input."""
    event: Event
    space: Space
    price_cents: int
    currency: str


def load_and_validate_offer(
    db: Session,
    space_slug: str,
    event_id: str,
) -> TrustedTicketOffer:
    """
    Load Space + Event and enforce every precondition for a paid-ticket
    purchase. Raises the appropriate TicketCheckoutError subclass on
    the first failed check. Never touches user input.
    """
    space = db.query(Space).filter(Space.slug == space_slug).first()
    if space is None:
        raise GatheringUnavailable(f"Collective '{space_slug}' not found.")

    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id)
        .first()
    )
    if event is None:
        raise GatheringUnavailable("Gathering not found in this Collective.")

    if event.booking_access_type != "paid_separately":
        raise NotAPaidGathering(
            "This Gathering does not sell standalone tickets."
        )
    if not event.is_published:
        raise GatheringUnavailable("This Gathering is not published.")
    if event.status != "active":
        raise GatheringUnavailable(
            f"This Gathering is {event.status} and no longer available."
        )

    # Ended-check uses the same end_marker convention the archive uses
    # (ends_at IS NULL → starts_at + 1 hour). We do it in Python since
    # we already have the row.
    end_marker = event.ends_at or (event.starts_at + timedelta(hours=1))
    if end_marker <= datetime.utcnow():
        raise GatheringUnavailable("This Gathering has already ended.")

    if event.booking_closes_at and event.booking_closes_at <= datetime.utcnow():
        raise GatheringUnavailable("Ticket sales for this Gathering have closed.")

    # Trust-sensitive: price and currency come from the DB.
    try:
        price_cents, currency = validate_paid_gathering_price(
            event.ticket_price_cents,
            event.ticket_currency,
        )
    except TicketPricingError as exc:
        # This means the DB row somehow got past the CHECK constraint —
        # should be impossible unless the constraint was disabled or the
        # row was mutated outside the app. Loud failure.
        logger.error(
            "Paid event %s has invalid ticket config: %s", event.id, exc
        )
        raise InvalidTicketConfig(
            "This Gathering is misconfigured. Please contact the creator."
        ) from exc

    return TrustedTicketOffer(
        event=event, space=space, price_cents=price_cents, currency=currency,
    )


# ---------------------------------------------------------------------------
# Duplicate-purchase checks
# ---------------------------------------------------------------------------

def _existing_confirmed_booking(db: Session, event_id: str, user_id: str) -> EventBooking | None:
    return (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event_id,
            EventBooking.user_id == user_id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    )


def _existing_active_hold(db: Session, event_id: str, user_id: str) -> EventBooking | None:
    """Return the caller's non-expired pending_payment booking, if any.

    **This one is deliberately clock-based, and must stay that way.**

    It asks a different question from ``capacity_used``. That one asks "is
    this seat still taken?", which must ignore the clock — a past-due hold
    keeps its seat until Stripe confirms the checkout is dead (invariant
    I2). This asks "does this member still have a payment page worth
    sending them back to?", and that genuinely expires: past the window
    the Stripe Session is closed and its URL leads nowhere, so the caller
    should fall through and open a fresh one.

    Aligning this with I2 would hand a member a dead Stripe URL instead of
    a working checkout. Two questions, two rules, one timestamp.
    """
    row = db.execute(
        text("""
            SELECT id FROM event_bookings
            WHERE event_id = :e AND user_id = :u
              AND status = 'pending_payment'
              AND hold_expires_at > timezone('UTC', NOW())
            LIMIT 1
        """),
        {"e": event_id, "u": user_id},
    ).first()
    if row is None:
        return None
    return db.get(EventBooking, row[0])


# ---------------------------------------------------------------------------
# Hold create-or-reuse (invariants I2, I3, I4)
# ---------------------------------------------------------------------------

@dataclass
class HoldOutcome:
    booking: EventBooking
    transaction: PaymentTransaction
    reused: bool  # True if we UPDATE-reused an expired row


def create_or_reuse_hold(
    db: Session,
    *,
    offer: TrustedTicketOffer,
    buyer: User,
    fee_bps: int,
    creator_plan_id: str | None,
    creator_subscription_id: str | None,
    hold_ttl_minutes: int,
) -> HoldOutcome:
    """
    Atomically:
      1. Lock the Event row (SELECT ... FOR UPDATE).
      2. Compute capacity_used inside the lock; refuse if full.
      3. Reject if buyer already has a confirmed booking.
      4. If buyer has an EXPIRED hold → UPDATE-reuse the same row.
      5. Else INSERT a new pending_payment booking row.
      6. Create the pending PaymentTransaction.

    Caller must commit. The Stripe Checkout Session is created AFTER
    this returns; the caller then writes the Session's own ``expires_at``
    back into ``booking.hold_expires_at`` (so the two cannot disagree)
    along with ``transaction.provider_checkout_*``, and commits.

    If Stripe fails the caller ROLLS BACK, so this hold never existed —
    it is not "left in place to expire naturally", as this docstring
    previously claimed.

    The expiry set here is PROVISIONAL and deliberately generous. Stripe
    enforces a minimum Session lifetime measured from its own clock, and
    work happens between this call and that one, so an exact figure
    computed here can be rejected or can undercut the Session. Erring
    long only over-counts a seat briefly; erring short reopens the
    oversell window.
    """
    # 1. Row lock the event
    db.execute(text("SELECT id FROM events WHERE id = :id FOR UPDATE"),
               {"id": offer.event.id})

    # 3. Duplicate confirmed guard (do first — cheaper than hold check)
    if _existing_confirmed_booking(db, offer.event.id, buyer.id):
        raise AlreadyHasTicket("You already have a ticket for this Gathering.")

    # 2. Capacity math under lock
    used = capacity_used(db, offer.event.id)
    if offer.event.capacity is not None and used >= offer.event.capacity:
        raise SoldOut("This Gathering is sold out.")

    now_utc = datetime.utcnow()
    new_expiry = now_utc + timedelta(minutes=hold_ttl_minutes)

    # 4/5. Reuse-or-insert. Query first, then decide — because we've
    # taken the FOR UPDATE lock on the event, no other checkout for this
    # (event, user) can slip in between the SELECT and INSERT/UPDATE.
    existing = db.execute(
        text("""
            SELECT id, status, hold_expires_at
            FROM event_bookings
            WHERE event_id = :e AND user_id = :u
            LIMIT 1
        """),
        {"e": offer.event.id, "u": buyer.id},
    ).first()

    txn = _build_pending_transaction(
        db,
        offer=offer,
        buyer=buyer,
        fee_bps=fee_bps,
        creator_plan_id=creator_plan_id,
        creator_subscription_id=creator_subscription_id,
    )
    db.add(txn)
    db.flush()

    if existing is None:
        booking = EventBooking(
            id=f"bk_{uuid.uuid4().hex[:20]}",
            event_id=offer.event.id,
            user_id=buyer.id,
            status=BookingStatus.pending_payment,
            source="ticket_purchase",
            hold_expires_at=new_expiry,
            payment_transaction_id=txn.id,
        )
        db.add(booking)
        db.flush()
        return HoldOutcome(booking=booking, transaction=txn, reused=False)

    # existing row present — verify shape and reuse
    if existing.status == BookingStatus.confirmed.value:
        # Should have been caught by _existing_confirmed_booking above;
        # this is a belt-and-braces guard against enum-value drift.
        raise AlreadyHasTicket("You already have a ticket for this Gathering.")

    # Must be pending_payment. It could be expired or (rare, if we race
    # ourselves) still valid — the caller should have caught the active
    # case before entering this function. We accept both here to keep
    # this function self-contained, and the endpoint has a separate
    # early-return path for "still active" that avoids ever reaching here.
    booking = db.get(EventBooking, existing.id)
    booking.status = BookingStatus.pending_payment
    booking.hold_expires_at = new_expiry
    booking.payment_transaction_id = txn.id
    booking.cancelled_at = None
    booking.source = "ticket_purchase"
    db.flush()
    return HoldOutcome(booking=booking, transaction=txn, reused=True)


def _build_pending_transaction(
    db: Session,
    *,
    offer: TrustedTicketOffer,
    buyer: User,
    fee_bps: int,
    creator_plan_id: str | None,
    creator_subscription_id: str | None,
) -> PaymentTransaction:
    """PaymentTransaction row for a pending gathering ticket purchase."""
    gross = offer.price_cents
    platform_fee = gross * fee_bps // 10_000
    net_creator = gross - platform_fee

    # Platform-owned Collective: fee=0, payout_status=not_applicable.
    is_platform_owned = offer.space.creator_id is None
    # Decided now and frozen onto the row. A creator who completes Connect
    # onboarding while this buyer is away at Stripe must not change how
    # this ticket pays out.
    payout = resolve_payout_model(
        db,
        creator_user_id=offer.space.creator_id,
        is_platform_owned=is_platform_owned,
    )
    # Connect rows are not_applicable: FC's manual payout process does not
    # cover them.
    payout_status = (
        PayoutStatus.pending if payout.manual_payout_applies
        else PayoutStatus.not_applicable
    )

    return PaymentTransaction(
        id=f"txn_{uuid.uuid4().hex[:20]}",
        transaction_type=PaymentTransactionType.gathering_ticket_purchase,
        status=PaymentTransactionStatus.pending,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=buyer.id,
        creator_user_id=offer.space.creator_id,
        space_id=offer.space.id,
        currency=offer.currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=fee_bps,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        creator_plan_id=creator_plan_id,
        creator_subscription_id=creator_subscription_id,
        stripe_mode=settings.stripe_mode,
        payout_status=payout_status,
        payout_model=payout.payout_model,
        connect_destination_account_id=payout.destination_account_id,
        connect_transfer_status=payout.initial_transfer_status,
    )


# ---------------------------------------------------------------------------
# Webhook fulfilment (invariants I6, I7)
# ---------------------------------------------------------------------------

@dataclass
class FulfilOutcome:
    already_fulfilled: bool           # True → webhook re-delivery, no-op
    booking: EventBooking | None
    access_pass: AccessPass | None
    transaction: PaymentTransaction


def fulfil_ticket_purchase(
    db: Session,
    *,
    transaction_id: str,
    event_id: str,
    payer_user_id: str,
    stripe_amount_total: int,
    stripe_currency: str,
    stripe_payment_intent_id: str | None,
    stripe_charge_id: str | None,
) -> FulfilOutcome:
    """
    Convert a paid hold into a confirmed booking + AccessPass.

    Atomically:
      1. Lock the PaymentTransaction row. If already succeeded → no-op.
      2. Verify Stripe-reported amount+currency match the pending txn.
      3. Lock the Event row.
      4. Load the buyer's hold; verify it matches txn/event/user AND is
         either 'pending_payment' with unexpired hold OR was already
         flipped to 'confirmed' (idempotent re-delivery mid-fulfilment).
      5. Convert to confirmed; clear hold_expires_at.
      6. Insert the event_ticket AccessPass, source=one_time_purchase.
         Link back to the booking (booking.access_pass_id).
      7. Create or reactivate the buyer's Collective membership.
      8. Mark the transaction succeeded; record payment_intent + charge.
      9. Caller commits.

    Any failure aborts the transaction without side effects (Postgres
    rolls back). The caller — the webhook — will then return non-2xx
    so Stripe retries; the FIRST successful run will short-circuit
    subsequent deliveries via step 1.
    """
    # 1. Lock the transaction
    txn = db.execute(
        text("SELECT * FROM payment_transactions WHERE id = :id FOR UPDATE"),
        {"id": transaction_id},
    ).first()
    if txn is None:
        # A transaction id that does not exist will not start existing.
        raise FulfilmentTerminal(
            f"PaymentTransaction {transaction_id!r} not found."
        )
    # Reload as ORM object for convenience
    txn_obj = db.get(PaymentTransaction, transaction_id)

    if txn_obj.status == PaymentTransactionStatus.succeeded:
        booking = (
            db.query(EventBooking)
            .filter(EventBooking.payment_transaction_id == txn_obj.id)
            .first()
        )
        access_pass = (
            db.query(AccessPass)
            .filter(AccessPass.payment_transaction_id == txn_obj.id)
            .first()
        )
        return FulfilOutcome(
            already_fulfilled=True,
            booking=booking,
            access_pass=access_pass,
            transaction=txn_obj,
        )

    if txn_obj.status not in (PaymentTransactionStatus.pending,):
        # e.g. already 'failed' or 'cancelled' — refuse to un-fail it.
        # Already failed or cancelled. Un-failing it on a redelivery
        # would resurrect state we deliberately ended.
        raise FulfilmentTerminal(
            f"PaymentTransaction {txn_obj.id!r} is in status "
            f"{txn_obj.status!r}; refusing to fulfil."
        )

    # 2. Amount + currency sanity
    if stripe_amount_total != txn_obj.gross_amount_cents:
        # The figures disagree. That is a real problem for a human, and
        # no number of retries will reconcile them.
        raise FulfilmentTerminal(
            f"Stripe amount {stripe_amount_total} does not match "
            f"expected {txn_obj.gross_amount_cents} for txn {txn_obj.id}."
        )
    if stripe_currency.upper() != txn_obj.currency.upper():
        raise FulfilmentTerminal(
            f"Stripe currency {stripe_currency!r} does not match "
            f"expected {txn_obj.currency!r} for txn {txn_obj.id}."
        )

    # 3. Lock the Event row
    db.execute(text("SELECT id FROM events WHERE id = :id FOR UPDATE"),
               {"id": event_id})

    # 4. Find the hold
    booking = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event_id,
            EventBooking.user_id == payer_user_id,
            EventBooking.payment_transaction_id == transaction_id,
        )
        .first()
    )
    if booking is None:
        # Retryable: most likely a read that raced the hold's own
        # commit. Stripe redelivers and the next attempt finds it.
        raise FulfilmentRetryable(
            f"No hold row for event={event_id!r} user={payer_user_id!r} "
            f"txn={transaction_id!r}."
        )
    if booking.status not in (BookingStatus.pending_payment, BookingStatus.confirmed):
        # ``cancelled`` is terminal — the hold was verified dead or
        # released, and a payment against it needs a human deciding
        # between granting a seat and refunding. Any other unexpected
        # status is treated the same way rather than retried blindly.
        raise FulfilmentTerminal(
            f"Booking {booking.id!r} is {booking.status!r}; cannot fulfil."
        )

    # 5. Flip to confirmed (idempotent if already flipped)
    booking.status = BookingStatus.confirmed
    booking.hold_expires_at = None

    # 6. AccessPass — the event-specific entitlement
    access_pass = (
        db.query(AccessPass)
        .filter(AccessPass.payment_transaction_id == txn_obj.id)
        .first()
    )
    if access_pass is None:
        access_pass = AccessPass(
            id=f"ap_{uuid.uuid4().hex[:20]}",
            user_id=payer_user_id,
            space_id=txn_obj.space_id,
            payment_transaction_id=txn_obj.id,
            pass_type=AccessPassType.event_ticket,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
            valid_from=datetime.utcnow(),
        )
        db.add(access_pass)
        db.flush()
        # Scope the pass to exactly this event via the join table so
        # access checks can positively prove "this pass unlocks THIS
        # event" (and nothing else in the Collective).
        db.add(AccessPassEvent(access_pass_id=access_pass.id, event_id=event_id))
        db.flush()

    booking.access_pass_id = access_pass.id

    # 7. Membership — buying a seat brings you into the Collective, the
    # same as every other purchase. This path used to be the exception:
    # it minted the booking and the pass and left the buyer a
    # non-member, so a purchase-required Collective could sell a
    # Gathering to someone who then could not enter. Same session, same
    # transaction as the booking above — it lands or it doesn't,
    # together with the seat it accompanies.
    membership_outcome = _membership_grant.ensure_membership_for_purchase(
        db,
        user_id=payer_user_id,
        space_id=txn_obj.space_id,
        now=datetime.utcnow(),
        source="ticket_purchase",
    )
    if membership_outcome.skipped_reason:
        logger.info(
            "gathering_tickets: membership unchanged user=%s space=%s reason=%s",
            payer_user_id, txn_obj.space_id, membership_outcome.skipped_reason,
        )

    # 8. Mark transaction succeeded + record Stripe refs
    txn_obj.status = PaymentTransactionStatus.succeeded
    if stripe_payment_intent_id and not txn_obj.provider_payment_intent_id:
        txn_obj.provider_payment_intent_id = stripe_payment_intent_id
    if stripe_charge_id and not txn_obj.provider_charge_id:
        txn_obj.provider_charge_id = stripe_charge_id

    db.flush()

    return FulfilOutcome(
        already_fulfilled=False,
        booking=booking,
        access_pass=access_pass,
        transaction=txn_obj,
    )


# ---------------------------------------------------------------------------
# Expiry / failure release (invariants I2, I7)
# ---------------------------------------------------------------------------

def release_hold_for_transaction(
    db: Session,
    *,
    transaction_id: str,
    final_status: PaymentTransactionStatus,
    reason: str,
) -> None:
    """
    Called by webhook when Stripe reports:
      - checkout.session.expired  → final_status=cancelled
      - payment_intent.payment_failed → final_status=failed

    Marks the PaymentTransaction as terminal AND flips the associated
    hold to 'cancelled' with cancelled_at populated. Idempotent: if the
    transaction is already succeeded/failed/cancelled we leave the row
    alone (never resurrect state).
    """
    assert final_status in (
        PaymentTransactionStatus.cancelled,
        PaymentTransactionStatus.failed,
    ), f"unexpected release status {final_status!r}"

    txn = db.get(PaymentTransaction, transaction_id)
    if txn is None:
        logger.warning("release_hold_for_transaction: no txn %s", transaction_id)
        return
    if txn.status != PaymentTransactionStatus.pending:
        # Already terminal — nothing to do (idempotency)
        return

    txn.status = final_status

    booking = (
        db.query(EventBooking)
        .filter(EventBooking.payment_transaction_id == transaction_id)
        .first()
    )
    if booking is not None and booking.status == BookingStatus.pending_payment:
        booking.status = BookingStatus.cancelled
        booking.cancelled_at = datetime.utcnow()
        booking.hold_expires_at = None
        booking.note = (booking.note or "") + f"\n[{reason}]"

    db.flush()


# ---------------------------------------------------------------------------
# Access-source label — used by creator UI + attendee list
# ---------------------------------------------------------------------------

def booking_access_source_label(booking: EventBooking) -> str:
    """
    Human label for the creator-facing attendee list. Mirrors your spec:
      - Paid          → confirmed + source='ticket_purchase' + access_pass
      - Complimentary → confirmed + source='creator_manual' + no txn
      - Creator added → confirmed + source='creator_manual'
      - Payment pending → status='pending_payment'
      - Cancelled     → status='cancelled'
    """
    if booking.status == BookingStatus.pending_payment:
        return "Payment pending"
    if booking.status == BookingStatus.cancelled:
        return "Cancelled"
    if booking.source == "ticket_purchase" and booking.payment_transaction_id:
        return "Paid"
    if booking.source == "creator_manual":
        return "Creator added"
    return "Complimentary"


# ---------------------------------------------------------------------------
# Verification — the positive knowledge invariant I2 depends on
# ---------------------------------------------------------------------------
#
# A hold past its window keeps its seat until FC learns what happened to
# the checkout behind it. Usually Stripe tells us, via
# ``checkout.session.expired`` or ``payment_intent.payment_failed``. When
# it has not, and another buyer wants the seat, we ask.
#
# Asking is a network call, so it happens with NO Event row lock held: a
# lock spanning a third-party request makes a slow provider into a stuck
# table, with every other buyer of that Gathering queued behind it.

#: Structured cancellation reasons. A closed set rather than free prose,
#: so a cancelled hold can be told apart from a buyer who changed their
#: mind, and so nothing can invent a reason that means "we guessed".
CANCEL_CHECKOUT_EXPIRED = "checkout_expired"
CANCEL_PAYMENT_FAILED = "payment_failed"
CANCEL_VERIFIED_EXPIRED = "verified_expired"

VERIFY_CONFIRMED = "confirmed"
VERIFY_CANCELLED = "cancelled"
VERIFY_UNKNOWN = "unknown"


def stale_holds_for_event(db: Session, event_id: str) -> list[EventBooking]:
    """Holds past their window, oldest first.

    Past the window makes a hold eligible for verification. It is
    emphatically not what makes its seat available.
    """
    return (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event_id,
            EventBooking.status == BookingStatus.pending_payment,
            EventBooking.hold_expires_at.isnot(None),
            EventBooking.hold_expires_at <= datetime.utcnow(),
        )
        .order_by(EventBooking.hold_expires_at.asc())
        .all()
    )


def verify_stale_hold(db: Session, *, booking_id: str) -> str:
    """Ask Stripe what became of one stale hold, and act on the answer.

    Commits. Returns one of the ``VERIFY_*`` constants.

    No Event lock is taken here, and no Stripe call happens under one.
    Each database mutation takes a short lock on the single booking row it
    touches; the caller reacquires the Event lock afterwards and recounts.

    The ladder, and why each rung is where it is:

      * Session ``complete`` → the buyer paid and we missed the webhook.
        Their seat is theirs. Fulfilment is left to the webhook path
        rather than duplicated here, so there is exactly one place that
        grants a pass; this only records that the hold must not be
        released.
      * Session ``expired`` → cancel, seat returns.
      * Session ``open`` past its intended window → expire it explicitly
        rather than waiting on Stripe's own timeout, then re-read. The
        expire call can lose a race with a buyer paying at that instant,
        which is exactly why the answer comes from the re-read.
      * anything unreadable → leave the hold alone. An unanswered
        question is not permission to sell the seat twice.
    """
    from app.services import discount_stripe_sessions as _sessions

    booking = db.get(EventBooking, booking_id)
    if booking is None or booking.status != BookingStatus.pending_payment:
        return VERIFY_UNKNOWN

    txn = (
        db.get(PaymentTransaction, booking.payment_transaction_id)
        if booking.payment_transaction_id else None
    )
    session_id = getattr(txn, "provider_checkout_session_id", None)
    if not session_id:
        # No Session was ever recorded against this hold. The endpoint
        # commits the Session id in the same transaction as the hold and
        # rolls back when Stripe fails, so a hold without one means the
        # Session never existed — nothing can charge this buyer.
        _cancel_hold(db, booking=booking, txn=txn,
                     reason=CANCEL_VERIFIED_EXPIRED)
        return VERIFY_CANCELLED

    try:
        status = _sessions.session_status(session_id)
    except _sessions.StripeUnavailable as exc:
        logger.warning(
            "gathering hold unverifiable: booking=%s session=%s err=%s — "
            "seat stays held rather than risking a double sale.",
            booking.id, session_id, exc,
        )
        return VERIFY_UNKNOWN

    if status == "complete":
        logger.warning(
            "gathering hold found COMPLETE during verification: booking=%s "
            "session=%s — completion webhook was missed; seat is theirs.",
            booking.id, session_id,
        )
        return VERIFY_CONFIRMED

    if status == "expired":
        _cancel_hold(db, booking=booking, txn=txn,
                     reason=CANCEL_VERIFIED_EXPIRED)
        return VERIFY_CANCELLED

    # 'open' past its window — close it, then let the re-read decide.
    try:
        _sessions.expire_session(session_id)
    except _sessions.StripeStateChanged:
        pass
    except _sessions.StripeUnavailable as exc:
        logger.warning(
            "gathering hold expire failed: booking=%s err=%s — staying held.",
            booking.id, exc,
        )
        return VERIFY_UNKNOWN

    try:
        status = _sessions.session_status(session_id)
    except _sessions.StripeUnavailable:
        return VERIFY_UNKNOWN

    if status == "complete":
        logger.warning(
            "gathering hold completed during expire attempt: booking=%s — "
            "treating as paid, not released.", booking.id,
        )
        return VERIFY_CONFIRMED
    if status == "expired":
        _cancel_hold(db, booking=booking, txn=txn,
                     reason=CANCEL_VERIFIED_EXPIRED)
        return VERIFY_CANCELLED
    return VERIFY_UNKNOWN


def _cancel_hold(
    db: Session, *, booking: EventBooking,
    txn: PaymentTransaction | None, reason: str,
) -> None:
    """Release one seat, under a short lock on that booking row only."""
    db.execute(
        text("SELECT id FROM event_bookings WHERE id = :id FOR UPDATE"),
        {"id": booking.id},
    )
    db.refresh(booking)
    if booking.status != BookingStatus.pending_payment:
        db.commit()
        return
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = datetime.utcnow()
    booking.hold_expires_at = None
    booking.note = f"{booking.note or ''}\n[{reason}]".strip()
    if txn is not None and txn.status == PaymentTransactionStatus.pending:
        txn.status = PaymentTransactionStatus.cancelled
    db.commit()
    logger.info(
        "gathering hold released: booking=%s reason=%s", booking.id, reason,
    )


def sweep_stale_holds(db: Session, *, event_id: str) -> int:
    """Verify every stale hold on one Gathering; return how many resolved.

    Called when a buyer has been refused for capacity, from OUTSIDE the
    Event row lock. The caller retakes the lock and recounts afterwards.

    A hold that cannot be verified is left alone, so the waiting buyer is
    refused. That is the cost of never selling one seat twice.
    """
    resolved = 0
    for booking in stale_holds_for_event(db, event_id):
        try:
            outcome = verify_stale_hold(db, booking_id=booking.id)
        except Exception:
            logger.exception(
                "gathering hold verification raised: booking=%s — leaving held.",
                booking.id,
            )
            continue
        if outcome == VERIFY_CANCELLED:
            resolved += 1
    return resolved
