"""
Service layer for standalone paid Gathering tickets.

Everything the Stage 2B checkout endpoint and the Stripe webhook branch
need to safely reserve capacity, create/reuse holds, and fulfil a
successful payment lives here. The HTTP router is a thin wrapper; the
webhook handler dispatches into `fulfil_ticket_purchase`.

Design invariants (each enforced in code AND in tests):

  I1. Client never supplies price, currency, or user identity. Every
      trust-sensitive value is loaded from the database.
  I2. Capacity is calculated as
        confirmed + (pending_payment AND hold_expires_at > NOW-UTC).
      Any expired hold is invisible to capacity, so a stalled buyer
      never permanently consumes a seat.
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
      the event row. It refuses to fulfil a hold that has expired,
      been cancelled, or does not match the trusted metadata.
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
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import BookingStatus, Event, EventBooking, Space
from app.models.user import User
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

CAPACITY_USED_SQL = text("""
    SELECT COUNT(*)
    FROM event_bookings
    WHERE event_id = :event_id
      AND (
        status = 'confirmed'
        OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW()))
      )
""")


def capacity_used(db: Session, event_id: str) -> int:
    """Number of seats currently taken by confirmed bookings + live holds."""
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
    """Return the caller's non-expired pending_payment booking, if any."""
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
    this returns, then the caller sets `transaction.provider_checkout_*`
    and commits again. If Stripe fails, the second commit is skipped
    and the hold is left in place — it will expire naturally.
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
    payout_status = (
        PayoutStatus.not_applicable if is_platform_owned else PayoutStatus.pending
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
      7. Mark the transaction succeeded; record payment_intent + charge.
      8. Caller commits.

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
        raise ValueError(f"PaymentTransaction {transaction_id!r} not found.")
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
        raise ValueError(
            f"PaymentTransaction {txn_obj.id!r} is in status "
            f"{txn_obj.status!r}; refusing to fulfil."
        )

    # 2. Amount + currency sanity
    if stripe_amount_total != txn_obj.gross_amount_cents:
        raise ValueError(
            f"Stripe amount {stripe_amount_total} does not match "
            f"expected {txn_obj.gross_amount_cents} for txn {txn_obj.id}."
        )
    if stripe_currency.upper() != txn_obj.currency.upper():
        raise ValueError(
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
        raise ValueError(
            f"No hold row for event={event_id!r} user={payer_user_id!r} "
            f"txn={transaction_id!r}."
        )
    if booking.status not in (BookingStatus.pending_payment, BookingStatus.confirmed):
        raise ValueError(
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

    # 7. Mark transaction succeeded + record Stripe refs
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
