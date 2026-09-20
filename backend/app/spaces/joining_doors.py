"""The Payment Options a visitor may buy to get into a Collective.

Only for ``join_policy='purchase_required'``. An open Collective has a
free door and this returns nothing — not because purchases there fail
to create membership (they do, for every purchase), but because an
open Collective does not need to sell entry.

Two filters, both deliberate:

* **nominated** — ``is_joining_option``. A Collective may sell many
  things; the creator decides which of them are *doors*. Defaulting
  every Option to a door would mean flipping a Collective to
  purchase-required silently reframed its entire catalogue as entry
  fees.
* **published** — a draft or archived Option is never shown to a
  visitor, whatever its nomination says. Creators can nominate a door
  before opening it.

An empty result is a real answer and must be rendered as one: a
purchase-required Collective with no published nominated Option is
closed for now. It is never a reason to fall back to free joining.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption, PaymentOptionStatus
from app.models.platform import Space
from app.spaces import join_policy


def effective_price_cents(option: PaymentOption) -> int | None:
    """Mirrors the model's documented rule: an override wins over the
    calculated total."""
    if option.override_total_cents is not None:
        return option.override_total_cents
    return option.calculated_total_cents


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

    return [
        {
            "id": opt.id,
            "name": opt.name,
            "description": opt.description,
            "buyer_note": opt.buyer_note,
            "price_cents": effective_price_cents(opt),
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
        }
        for opt in options
    ]
