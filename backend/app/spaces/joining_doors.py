"""The Payment Options a visitor may buy to get into a Collective.

Only for ``join_policy='purchase_required'``. An open Collective has a
free door and this returns nothing — not because purchases there fail
to create membership (they do, for every purchase), but because an
open Collective does not need to sell entry.

Three filters, all deliberate:

* **nominated** — ``is_joining_option``. A Collective may sell many
  things; the creator decides which of them are *doors*. Defaulting
  every Option to a door would mean flipping a Collective to
  purchase-required silently reframed its entire catalogue as entry
  fees.
* **published** — a draft or archived Option is never shown to a
  visitor, whatever its nomination says. Creators can nominate a door
  before opening it.
* **checkoutable** — the Option must have at least one published
  schedule the checkout endpoint would actually accept. A door that
  cannot complete a purchase is not a door, and advertising one is
  worse than showing none.

The price comes from those schedules, never from the Option's
``override_total_cents`` / ``calculated_total_cents``, which are
authoring fields and are routinely NULL on real Options. See
``purchase_schedule_view``.

An empty result is a real answer and must be rendered as one: a
purchase-required Collective with no usable door is closed for now. It
is never a reason to fall back to free joining.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption, PaymentOptionStatus
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import EventSeries, Pathway, Space
from app.spaces import join_policy
from app.spaces.purchase_schedule_view import (
    headline_price_cents,
    published_schedules_by_option,
    schedule_view,
)


def list_joining_doors(db: Session, space: Space) -> list[dict]:
    """Public projection of this Collective's ways in."""
    if join_policy.allows_free_join(space.join_policy):
        return []

    options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.is_joining_option.is_(True),
            PaymentOption.status == PaymentOptionStatus.published,
        )
        .order_by(PaymentOption.position.asc(), PaymentOption.created_at.asc())
        .all()
    )
    if not options:
        return []

    option_ids = [o.id for o in options]
    schedules_by_option = published_schedules_by_option(db, option_ids)

    # What each door actually grants, read from the same
    # ``PaymentOptionGrant`` rows fulfilment uses. The About page
    # describes the purchase from these rather than from the
    # creator-authored "included / paid separately" summaries, which
    # describe the older shape — free membership with paid content
    # inside — and say the opposite of what a joining purchase does.
    grants_by_option: dict[str, list[PaymentOptionGrant]] = {}
    if option_ids:
        for g in (
            db.query(PaymentOptionGrant)
            .filter(PaymentOptionGrant.payment_option_id.in_(option_ids))
            .order_by(PaymentOptionGrant.position)
            .all()
        ):
            grants_by_option.setdefault(g.payment_option_id, []).append(g)

    series_titles: dict[str, str] = {}
    pathway_titles: dict[str, str] = {}
    series_ids = {g.series_id for gs in grants_by_option.values() for g in gs if g.series_id}
    pathway_ids = {g.pathway_id for gs in grants_by_option.values() for g in gs if g.pathway_id}
    if series_ids:
        series_titles = dict(
            db.query(EventSeries.id, EventSeries.title)
            .filter(EventSeries.id.in_(series_ids)).all()
        )
    if pathway_ids:
        pathway_titles = dict(
            db.query(Pathway.id, Pathway.title)
            .filter(Pathway.id.in_(pathway_ids)).all()
        )

    doors: list[dict] = []
    for opt in options:
        schedules = [
            schedule_view(s, opt) for s in schedules_by_option.get(opt.id, [])
        ]
        # Only offer methods the checkout endpoint would accept. An
        # Option whose every published schedule is currently
        # un-checkoutable is withheld entirely rather than rendered as
        # a button that 4xx's.
        buyable = [s for s in schedules if s["is_member_checkoutable"]]
        if not buyable:
            continue

        doors.append({
            "id": opt.id,
            "name": opt.name,
            "description": opt.description,
            "buyer_note": opt.buyer_note,
            "price_cents": headline_price_cents(schedules, opt),
            "currency": opt.currency,
            "payment_type": (
                opt.payment_type.value
                if hasattr(opt.payment_type, "value") else str(opt.payment_type)
            ),
            "term_start_date": (
                opt.term_start_date.isoformat() if opt.term_start_date else None
            ),
            "term_end_date": (
                opt.term_end_date.isoformat() if opt.term_end_date else None
            ),
            # Every way to pay for this door. The client renders one
            # CTA per schedule and sends the chosen schedule's id to
            # the checkout endpoint, which requires it.
            "schedules": buyable,
            # What buying this brings, in the creator's own titles.
            "included_titles": [
                t for t in (
                    series_titles.get(g.series_id) if g.series_id
                    else pathway_titles.get(g.pathway_id) if g.pathway_id
                    else None
                    for g in grants_by_option.get(opt.id, [])
                ) if t
            ],
            # Session allowance from the Series grant, where there is
            # one. Lets the summary say honestly that bookings differ
            # between options instead of implying one flat entitlement.
            "sessions_per_week": next(
                (g.sessions_per_week for g in grants_by_option.get(opt.id, [])
                 if g.grant_kind == "event_series"), None,
            ),
            "sessions_total": next(
                (g.total_sessions for g in grants_by_option.get(opt.id, [])
                 if g.grant_kind == "event_series"), None,
            ),
        })
    return doors
