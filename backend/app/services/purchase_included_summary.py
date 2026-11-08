"""What a purchase actually produced, described for a member.

Stage 3E. The purchase confirmation named the Payment Option and said
"your access is now active" — true, and almost useless to somebody who
has just bought a bundle containing a Gathering on a particular Sunday
and a Pathway they can start now. It did not say what was included,
and its one button went to the dashboard, because a Payment Option is
not itself a destination.

Built from the fulfilment outcome, never from the Option
--------------------------------------------------------
The rows this reads are what ``apply_intent`` just created: the
entitlements, the access passes, the bookings. That matters for two
reasons the brief names.

A creator may edit a Payment Option after somebody buys it — adding a
Pathway, removing a Gathering — and the email must describe the
purchase that happened, not the Option as it stands when the webhook
runs. And a member may already have held one of the included Pathways,
in which case the honest word is "included", not "unlocked".

So each line states what is true of *this member* after *this*
purchase, and nothing is inferred from where they happened to be
standing when they checked out.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.platform import (
    BookingStatus, Event, EventBooking, EventSeries, Pathway, Space,
)

logger = logging.getLogger(__name__)

KIND_PATHWAY = "pathway"
KIND_GATHERING = "gathering"
KIND_SERIES = "event_series"
KIND_OFFERING = "offering"


@dataclass(frozen=True)
class IncludedItem:
    """One line in "here's what's included"."""

    kind: str
    title: str
    #: Where to go. Always a real destination for the thing itself —
    #: the Option has no page of its own, which is what made the old
    #: single button unhelpful.
    url: str
    #: What is true for this member now. "Your place is confirmed",
    #: "Your access is now available", "Already in your collection".
    status: str
    #: Gatherings only. A Gathering is identified by when it is as much
    #: as by its name.
    starts_at: datetime | None = None

    def as_payload(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "status": self.status,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
        }


@dataclass
class IncludedSummary:
    items: list[IncludedItem] = field(default_factory=list)

    def as_payload(self) -> list[dict]:
        return [i.as_payload() for i in self.items]


def _space_slug(db: Session, space_id: str | None) -> str | None:
    if not space_id:
        return None
    row = db.query(Space.slug).filter(Space.id == space_id).first()
    return row[0] if row else None


def build_included_summary(
    db: Session, *, result, payer_user_id: str,
) -> IncludedSummary:
    """Describe a fulfilment result as member-facing lines.

    Never raises: a confirmation email that fails to send because one
    title could not be looked up is worse than one that lists a little
    less. Anything unexpected is logged and skipped.
    """
    items: list[IncludedItem] = []

    # ── Pathways ──────────────────────────────────────────────────
    #
    # ``was_new`` distinguishes access this purchase created from
    # access the member already had. The applier is idempotent, so an
    # entitlement it returns may predate this purchase; saying
    # "unlocked" about something somebody already owned is the
    # misleading first-time message §12 rules out.
    for ent in getattr(result, "entitlements", []) or []:
        try:
            pathway = db.get(Pathway, ent.pathway_id)
            if pathway is None:
                continue
            slug = _space_slug(db, pathway.space_id)
            if not slug:
                continue
            already = bool(
                getattr(ent, "created_at", None)
                and getattr(result, "now", None)
                and ent.created_at < result.now
            )
            items.append(IncludedItem(
                kind=KIND_PATHWAY,
                title=pathway.title,
                url=f"/spaces/{slug}/pathways/{pathway.slug}",
                status=(
                    "Already in your collection" if already
                    else "Your access is now available"
                ),
            ))
        except Exception:  # pragma: no cover - defensive
            logger.exception("included summary: pathway line failed")

    # ── Gatherings ────────────────────────────────────────────────
    #
    # Only what this purchase actually booked, and only described as
    # confirmed when the booking is. A seat still pending payment is
    # not a place, and §8 forbids saying otherwise.
    for booking in getattr(result, "bookings", []) or []:
        try:
            event = db.get(Event, booking.event_id)
            if event is None:
                continue
            slug = _space_slug(db, event.space_id)
            if not slug:
                continue
            confirmed = booking.status == BookingStatus.confirmed
            items.append(IncludedItem(
                kind=KIND_GATHERING,
                title=event.title,
                url=f"/spaces/{slug}/events/{event.id}",
                status=(
                    "Your place is confirmed" if confirmed
                    else "Your place is being confirmed"
                ),
                starts_at=event.starts_at,
            ))
        except Exception:  # pragma: no cover - defensive
            logger.exception("included summary: gathering line failed")

    # ── Gathering Series ──────────────────────────────────────────
    #
    # A Series pass is eligibility to book, not a booking. Saying a
    # member has a confirmed place in every session would be false for
    # most passes, and §6 says so explicitly.
    for ap in getattr(result, "access_passes", []) or []:
        try:
            series_id = getattr(ap, "eligible_series_id", None)
            if not series_id:
                continue
            series = db.get(EventSeries, series_id)
            if series is None:
                continue
            slug = _space_slug(db, series.space_id)
            if not slug:
                continue
            items.append(IncludedItem(
                kind=KIND_SERIES,
                title=series.title,
                url=f"/spaces/{slug}/gathering-series/{series.slug}",
                status="Your pass is active — book the sessions you want",
            ))
        except Exception:  # pragma: no cover - defensive
            logger.exception("included summary: series line failed")

    # ── Offerings ─────────────────────────────────────────────────
    for off in getattr(result, "offering_entitlements", []) or []:
        try:
            from app.models.offering import Offering

            offering = db.get(Offering, off.offering_id)
            if offering is None:
                continue
            slug = _space_slug(db, offering.space_id)
            if not slug:
                continue
            items.append(IncludedItem(
                kind=KIND_OFFERING,
                title=offering.title,
                url=f"/spaces/{slug}/offerings/{offering.slug}",
                status="Ready to open",
            ))
        except Exception:  # pragma: no cover - defensive
            logger.exception("included summary: offering line failed")

    return IncludedSummary(items=items)


__all__ = ["IncludedItem", "IncludedSummary", "build_included_summary"]


# ---------------------------------------------------------------------------
# Stage 3E.3 — the same summary, rebuilt later from a transaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurchaseSummary:
    """A completed purchase, as its buyer should see it."""

    transaction_id: str
    option_name: str | None
    space_name: str | None
    space_slug: str | None
    #: ``pending`` | ``fulfilling`` | ``fulfilled`` | ``failed`` | ``refunded``
    state: str
    amount_cents: int | None
    currency: str | None
    payment_mode: str
    installments_paid: int | None = None
    installments_expected: int | None = None
    installment_amount_cents: int | None = None
    total_expected_cents: int | None = None
    interval: str | None = None
    items: list[IncludedItem] = field(default_factory=list)

    def as_payload(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "option_name": self.option_name,
            "space_name": self.space_name,
            "space_slug": self.space_slug,
            "state": self.state,
            "amount_cents": self.amount_cents,
            "currency": self.currency,
            "payment_mode": self.payment_mode,
            "installments_paid": self.installments_paid,
            "installments_expected": self.installments_expected,
            "installment_amount_cents": self.installment_amount_cents,
            "total_expected_cents": self.total_expected_cents,
            "interval": self.interval,
            "items": [i.as_payload() for i in self.items],
        }


def _purchase_state(txn) -> str:
    """Where this purchase has got to, from the ledger alone.

    The ``?checkout=success`` parameter in the return URL is a trigger
    to ask, never an answer: a member can reach that URL by pressing
    Back, by bookmarking it, or by editing it. Only these rows know.
    """
    from app.models.payment import (
        PaymentFulfilmentStatus, PaymentTransactionStatus,
    )

    status = txn.status
    if status in (
        PaymentTransactionStatus.refunded,
        PaymentTransactionStatus.partially_refunded,
    ):
        return "refunded"
    if status in (
        PaymentTransactionStatus.failed, PaymentTransactionStatus.cancelled,
    ):
        return "failed"
    if status == PaymentTransactionStatus.pending:
        return "pending"
    if status == PaymentTransactionStatus.succeeded:
        # Paid, but the grants may still be landing — the webhook does
        # both in one transaction, so this is a narrow window, and
        # saying "ready" during it would be a promise we cannot keep.
        if txn.fulfilment_status == PaymentFulfilmentStatus.applied:
            return "fulfilled"
        return "fulfilling"
    return "pending"


def _live_pathway_status(db, *, user_id: str, pathway_id: str) -> str:
    from app.services.pathway_access import has_active_pathway_entitlement

    if has_active_pathway_entitlement(
        db, user_id=user_id, pathway_id=pathway_id,
    ):
        return "Your access is ready"
    return "No longer available"


def _live_booking_status(db, *, user_id: str, event_id: str) -> str:
    booking = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event_id,
            EventBooking.user_id == user_id,
        )
        .first()
    )
    if booking is None:
        return "No place reserved"
    if booking.status == BookingStatus.confirmed:
        return "Your place is confirmed"
    if booking.status == BookingStatus.cancelled:
        # A refunded purchase, or a member who cancelled. Saying
        # "confirmed" here is the specific thing §12 rules out.
        return "This booking was cancelled"
    return "Your place is being confirmed"


def build_purchase_summary(db: Session, *, txn, user_id: str) -> PurchaseSummary:
    """Rebuild a purchase for its buyer, later.

    Two different sources, deliberately.

    **What was purchased** comes from ``txn.snapshot_grants_json`` —
    the intent serialised when the price was agreed. A creator may have
    edited the Payment Option since, and the member bought what they
    bought.

    **What is true now** comes from live rows. A refunded purchase
    whose Gathering booking was cancelled must not keep saying the
    place is confirmed, however the purchase looked on the day. So the
    contents are historical and the statuses are current, which is the
    only combination that stays honest.
    """
    from app.models.payment_option import PaymentOption
    from app.models.purchase_plan import PurchasePlan
    from app.services.purchase_fulfilment import deserialise_intent

    option = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == txn.payment_option_id)
        .first()
        if txn.payment_option_id else None
    )
    space = db.query(Space).filter(Space.id == txn.space_id).first()

    plan = (
        db.query(PurchasePlan)
        .filter(PurchasePlan.id == txn.purchase_plan_id)
        .first()
        if getattr(txn, "purchase_plan_id", None) else None
    )

    items: list[IncludedItem] = []
    snapshot = getattr(txn, "snapshot_grants_json", None)
    if snapshot:
        try:
            intent = deserialise_intent(snapshot)
        except Exception:  # pragma: no cover - defensive
            logger.exception("purchase summary: snapshot unreadable")
            intent = None
        if intent is not None:
            for ent in intent.entitlements:
                pathway = db.get(Pathway, ent.pathway_id)
                if pathway is None:
                    continue
                slug = _space_slug(db, pathway.space_id)
                if not slug:
                    continue
                items.append(IncludedItem(
                    kind=KIND_PATHWAY, title=pathway.title,
                    url=f"/spaces/{slug}/pathways/{pathway.slug}",
                    status=_live_pathway_status(
                        db, user_id=user_id, pathway_id=pathway.id,
                    ),
                ))
            for b in intent.bookings:
                event = db.get(Event, b.event_id)
                if event is None:
                    continue
                slug = _space_slug(db, event.space_id)
                if not slug:
                    continue
                items.append(IncludedItem(
                    kind=KIND_GATHERING, title=event.title,
                    url=f"/spaces/{slug}/events/{event.id}",
                    status=_live_booking_status(
                        db, user_id=user_id, event_id=event.id,
                    ),
                    starts_at=event.starts_at,
                ))
            for ap in intent.access_passes:
                series_id = getattr(ap, "eligible_series_id", None)
                if not series_id:
                    continue
                series = db.get(EventSeries, series_id)
                if series is None:
                    continue
                slug = _space_slug(db, series.space_id)
                if not slug:
                    continue
                items.append(IncludedItem(
                    kind=KIND_SERIES, title=series.title,
                    url=f"/spaces/{slug}/gathering-series/{series.slug}",
                    status="Your pass is active — book the sessions you want",
                ))
            for off in intent.offerings:
                from app.models.offering import Offering

                offering = db.get(Offering, off.offering_id)
                if offering is None:
                    continue
                slug = _space_slug(db, offering.space_id)
                if not slug:
                    continue
                items.append(IncludedItem(
                    kind=KIND_OFFERING, title=offering.title,
                    url=f"/spaces/{slug}/offerings/{offering.slug}",
                    status="Ready to open",
                ))

    return PurchaseSummary(
        transaction_id=txn.id,
        option_name=(option.name if option else None),
        space_name=(space.name if space else None),
        space_slug=(space.slug if space else None),
        state=_purchase_state(txn),
        amount_cents=txn.gross_amount_cents,
        currency=txn.currency,
        payment_mode="plan" if plan is not None else "single",
        installments_paid=(plan.installments_paid if plan else None),
        installments_expected=(plan.installments_expected if plan else None),
        installment_amount_cents=(
            plan.installment_amount_cents if plan else None
        ),
        total_expected_cents=(plan.total_expected_cents if plan else None),
        interval=(plan.stripe_interval if plan else None),
        items=items,
    )
