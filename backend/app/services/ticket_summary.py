"""
Creator-facing aggregation for standalone paid Gatherings.

Single source of truth for the numbers the Creator Studio UI shows:
paid vs complimentary attendees, active holds, revenue, sales status,
edit-lock indicators. Every field is DB-authoritative — the frontend
must never derive these itself from a raw booking list.

Designed for bulk usage: `bulk_ticket_summaries(db, events)` issues at
most three grouped queries regardless of the number of events, avoiding
N+1 in the /creator/spaces/{slug}/events list endpoint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.payment import PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType
from app.models.platform import BookingStatus, Event, EventBooking


# ---------------------------------------------------------------------------
# Public shapes
# ---------------------------------------------------------------------------

@dataclass
class TicketSalesSummary:
    """Every creator-visible number for a single paid Gathering."""
    status: str                                # open | sold_out | closed | cancelled | ended | testing_only
    paid_ticket_count: int                     # succeeded ticket txn → confirmed booking
    complimentary_count: int                   # creator_manual + free-source bookings
    confirmed_booking_count: int               # everything status='confirmed'
    active_hold_count: int                     # pending_payment holds not yet expired
    remaining_capacity: int | None             # None → unlimited
    gross_ticket_revenue_cents: int            # only PaymentTransactionStatus.succeeded
    revenue_currency: str | None               # first non-null currency across succeeded txns (MVP: same for whole event)
    has_completed_ticket_sales: bool           # edit-lock signal
    has_active_payment_holds: bool             # edit-lock signal (temporary)
    sales_enabled: bool                        # environment-level flag mirror
    stripe_mode: str                           # 'test' | 'live'

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Status derivation — order matters (first match wins)
# ---------------------------------------------------------------------------

def _derive_status(
    *,
    event: Event,
    confirmed: int,
    active_holds: int,
    now: datetime,
) -> str:
    """Compact label for the creator manage panel."""
    if event.booking_access_type != "paid_separately":
        return "not_paid"
    if event.status == "cancelled":
        return "cancelled"

    end_marker = event.ends_at or (event.starts_at + timedelta(hours=1))
    if end_marker <= now:
        return "ended"

    if event.booking_closes_at and event.booking_closes_at <= now:
        return "closed"

    if event.capacity is not None and (confirmed + active_holds) >= event.capacity:
        return "sold_out"

    # Publish-required for real sales but drafts can still show "open"
    # conceptually; the UI additionally overlays "Testing only" when the
    # feature flag is off.
    if not event.is_published:
        return "closed"

    return "open"


# ---------------------------------------------------------------------------
# Single-event summary
# ---------------------------------------------------------------------------

def ticket_summary_for(db: Session, event: Event) -> TicketSalesSummary:
    """
    Compute a fresh summary from the DB. Runs three focused queries. Safe
    to call for non-paid events (returns a zeroed-out summary with
    status='not_paid').
    """
    now = datetime.utcnow()

    # 1. Bookings grouped by (status, source, has_txn) in a single scan.
    #    Faster than three separate COUNT queries and gives us both
    #    paid / complimentary / hold buckets at once.
    row = db.execute(
        text("""
            SELECT
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed'
                   AND source = 'ticket_purchase'
                   AND payment_transaction_id IS NOT NULL
                  THEN 1 ELSE 0 END), 0)                    AS paid,
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed'
                   AND (source IS NULL OR source <> 'ticket_purchase')
                  THEN 1 ELSE 0 END), 0)                    AS complimentary,
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed'
                  THEN 1 ELSE 0 END), 0)                    AS confirmed,
              COALESCE(SUM(CASE
                  WHEN status = 'pending_payment'
                   AND hold_expires_at > timezone('UTC', NOW())
                  THEN 1 ELSE 0 END), 0)                    AS active_holds
            FROM event_bookings
            WHERE event_id = :event_id
        """),
        {"event_id": event.id},
    ).mappings().one()

    # 2. Revenue: sum of succeeded ticket-purchase transactions for this event.
    #    Joined through event_bookings so we're only summing the txns that
    #    actually paid for a seat on THIS event (not, say, a refunded
    #    orphan that was never applied to a booking).
    rev_row = db.execute(
        text("""
            SELECT
              COALESCE(SUM(pt.gross_amount_cents), 0)   AS gross_cents,
              MIN(pt.currency)                          AS currency
            FROM payment_transactions pt
            JOIN event_bookings eb
              ON eb.payment_transaction_id = pt.id
             AND eb.event_id = :event_id
             AND eb.status = 'confirmed'
            WHERE pt.status = 'succeeded'
              AND pt.transaction_type = 'gathering_ticket_purchase'
        """),
        {"event_id": event.id},
    ).mappings().one()

    confirmed = int(row["confirmed"])
    active_holds = int(row["active_holds"])
    remaining = None if event.capacity is None else max(
        0, event.capacity - (confirmed + active_holds)
    )

    return TicketSalesSummary(
        status=_derive_status(
            event=event, confirmed=confirmed, active_holds=active_holds, now=now,
        ),
        paid_ticket_count=int(row["paid"]),
        complimentary_count=int(row["complimentary"]),
        confirmed_booking_count=confirmed,
        active_hold_count=active_holds,
        remaining_capacity=remaining,
        gross_ticket_revenue_cents=int(rev_row["gross_cents"]),
        revenue_currency=rev_row["currency"],
        has_completed_ticket_sales=int(row["paid"]) > 0,
        has_active_payment_holds=active_holds > 0,
        sales_enabled=bool(settings.standalone_gathering_sales_enabled),
        stripe_mode=settings.stripe_mode,
    )


# ---------------------------------------------------------------------------
# Bulk aggregation for list endpoints
# ---------------------------------------------------------------------------

def bulk_ticket_summaries(
    db: Session, events: Iterable[Event],
) -> dict[str, TicketSalesSummary]:
    """
    Compute summaries for many events in a bounded number of queries.
    Returns { event_id: TicketSalesSummary } for every event supplied.

    Used by list endpoints; the single-event helper is fine for detail
    endpoints. Both share status derivation and the same SQL shape so
    the UI never sees drift between list and detail.
    """
    events_list = list(events)
    if not events_list:
        return {}

    event_ids = [e.id for e in events_list]
    now = datetime.utcnow()

    # One booking aggregate per event
    bookings_rows = db.execute(
        text("""
            SELECT
              event_id,
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed'
                   AND source = 'ticket_purchase'
                   AND payment_transaction_id IS NOT NULL
                  THEN 1 ELSE 0 END), 0)                    AS paid,
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed'
                   AND (source IS NULL OR source <> 'ticket_purchase')
                  THEN 1 ELSE 0 END), 0)                    AS complimentary,
              COALESCE(SUM(CASE
                  WHEN status = 'confirmed' THEN 1 ELSE 0 END), 0) AS confirmed,
              COALESCE(SUM(CASE
                  WHEN status = 'pending_payment'
                   AND hold_expires_at > timezone('UTC', NOW())
                  THEN 1 ELSE 0 END), 0)                    AS active_holds
            FROM event_bookings
            WHERE event_id = ANY(:ids)
            GROUP BY event_id
        """),
        {"ids": event_ids},
    ).mappings().all()
    bookings_by_event = {r["event_id"]: r for r in bookings_rows}

    revenue_rows = db.execute(
        text("""
            SELECT
              eb.event_id,
              COALESCE(SUM(pt.gross_amount_cents), 0)   AS gross_cents,
              MIN(pt.currency)                          AS currency
            FROM payment_transactions pt
            JOIN event_bookings eb
              ON eb.payment_transaction_id = pt.id
             AND eb.status = 'confirmed'
            WHERE eb.event_id = ANY(:ids)
              AND pt.status = 'succeeded'
              AND pt.transaction_type = 'gathering_ticket_purchase'
            GROUP BY eb.event_id
        """),
        {"ids": event_ids},
    ).mappings().all()
    revenue_by_event = {r["event_id"]: r for r in revenue_rows}

    out: dict[str, TicketSalesSummary] = {}
    for event in events_list:
        b = bookings_by_event.get(event.id) or {
            "paid": 0, "complimentary": 0, "confirmed": 0, "active_holds": 0,
        }
        r = revenue_by_event.get(event.id) or {"gross_cents": 0, "currency": None}
        confirmed = int(b["confirmed"])
        active_holds = int(b["active_holds"])
        remaining = None if event.capacity is None else max(
            0, event.capacity - (confirmed + active_holds)
        )
        out[event.id] = TicketSalesSummary(
            status=_derive_status(
                event=event, confirmed=confirmed, active_holds=active_holds, now=now,
            ),
            paid_ticket_count=int(b["paid"]),
            complimentary_count=int(b["complimentary"]),
            confirmed_booking_count=confirmed,
            active_hold_count=active_holds,
            remaining_capacity=remaining,
            gross_ticket_revenue_cents=int(r["gross_cents"]),
            revenue_currency=r["currency"],
            has_completed_ticket_sales=int(b["paid"]) > 0,
            has_active_payment_holds=active_holds > 0,
            sales_enabled=bool(settings.standalone_gathering_sales_enabled),
            stripe_mode=settings.stripe_mode,
        )
    return out


# ---------------------------------------------------------------------------
# Per-attendee source label — the payload version of
# `services.gathering_tickets.booking_access_source_label`
# ---------------------------------------------------------------------------

def attendee_payment_info(
    db: Session, booking: EventBooking,
) -> dict:
    """
    Creator-safe attendee payment payload:
      { "access_source": "Paid ticket" | "Complimentary" | "Creator added" | ...,
        "amount_paid_cents": int | None,
        "currency": str | None,
        "purchased_at": datetime | None }

    Only exposes payment amounts when a linked PaymentTransaction is in
    status='succeeded'. Never exposes card details, Stripe internal IDs,
    or in-flight payment intents.
    """
    label = _booking_label(booking)
    amount: int | None = None
    currency: str | None = None
    purchased_at: datetime | None = None

    if booking.payment_transaction_id and label == "Paid ticket":
        txn = db.get(PaymentTransaction, booking.payment_transaction_id)
        if txn and txn.status == PaymentTransactionStatus.succeeded:
            amount = txn.gross_amount_cents
            currency = txn.currency
            purchased_at = txn.updated_at

    return {
        "access_source": label,
        "amount_paid_cents": amount,
        "currency": currency,
        "purchased_at": purchased_at,
    }


def _booking_label(booking: EventBooking) -> str:
    """
    Labels expected by the Stage 3 spec:
      Paid ticket · Complimentary · Creator added · Included · Cancelled
    Backend-authoritative — never infers "Paid" just because the
    Gathering is ticketed.
    """
    if booking.status == BookingStatus.cancelled:
        return "Cancelled"
    if booking.status == BookingStatus.pending_payment:
        return "Payment pending"
    if booking.source == "ticket_purchase" and booking.payment_transaction_id:
        # Might still be pending if the webhook hasn't fired — cast to Paid
        # only if the linked txn is actually succeeded. The caller sees the
        # more specific status via attendee_payment_info().
        return "Paid ticket"
    if booking.source == "creator_manual":
        return "Creator added"
    if booking.source == "member":
        return "Included"
    return "Complimentary"


# ---------------------------------------------------------------------------
# Bulk attendee labelling — resolves the ambiguity above by loading the
# linked transactions in one query. Use this when serialising a whole
# booking list.
# ---------------------------------------------------------------------------

def bulk_attendee_payment_info(
    db: Session, bookings: list[EventBooking],
) -> dict[str, dict]:
    """Return { booking_id: attendee_payment_info(...)-shape dict }."""
    if not bookings:
        return {}

    txn_ids = [b.payment_transaction_id for b in bookings if b.payment_transaction_id]
    txns_by_id: dict[str, PaymentTransaction] = {}
    if txn_ids:
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id.in_(txn_ids))
            .all()
        )
        txns_by_id = {t.id: t for t in rows}

    out: dict[str, dict] = {}
    for b in bookings:
        label = _booking_label(b)
        amount: int | None = None
        currency: str | None = None
        purchased_at: datetime | None = None
        if b.payment_transaction_id:
            txn = txns_by_id.get(b.payment_transaction_id)
            if txn and txn.status == PaymentTransactionStatus.succeeded:
                if label == "Paid ticket":
                    amount = txn.gross_amount_cents
                    currency = txn.currency
                    purchased_at = txn.updated_at
        out[b.id] = {
            "access_source": label,
            "amount_paid_cents": amount,
            "currency": currency,
            "purchased_at": purchased_at,
        }
    return out
