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
