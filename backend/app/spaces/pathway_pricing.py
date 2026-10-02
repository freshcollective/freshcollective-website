"""The minimum price a visitor would pay for any paid Pathway inside a
Collective.

Extracted so the Explore list and the Collective detail endpoint read
the same number. They did not: ``hydrate_public_space_cards`` derived
it correctly here, while the public About page re-derived its own
version in the browser from ``pathway.price_cents`` alone. A Pathway on
``pricing_mode='payment_options'`` keeps its legacy ``price_cents``
column untouched after the switch, so that column is stale by design —
Test Pathway in production carries ``price_cents=500`` next to a
published $2 Payment Option, and the About page advertised
"Pathways from $5 AUD" for a Pathway that costs $2.

The rule, unchanged from the original derivation:

* ``pricing_mode='legacy'`` → ``Pathway.price_cents``.
* ``pricing_mode='payment_options'`` → the lowest effective price among
  that Pathway's PUBLISHED Payment Options, where effective price is
  ``COALESCE(override_total_cents, calculated_total_cents)``. Draft and
  archived Options are excluded: a price nobody can buy yet must not
  set the headline.

Both modes are considered together and the lower wins, so a Collective
holding one of each advertises the cheaper door.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.platform import Pathway
from app.services import pathway_payment_options as pathway_options


# Pathways that cost something. A 'free' or 'included' Pathway has no
# price to advertise and must not drag the minimum to zero.
PAID_ACCESS_TYPES = ("one_time", "subscription")


def min_paid_price_cents_by_space(
    db: Session, space_ids: list[str],
) -> dict[str, int]:
    """Map space id → cheapest paid Pathway price in cents.

    Spaces with no purchasable Pathway are absent from the mapping, so
    callers can use ``.get(space_id)`` to mean "nothing paid to show".
    """
    if not space_ids:
        return {}

    min_pathway_prices: dict[str, int] = {}

    # Legacy pathway prices.
    legacy_rows = (
        db.query(Pathway.space_id, func.min(Pathway.price_cents))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.access_type.in_(PAID_ACCESS_TYPES),
            Pathway.pricing_mode == "legacy",
            Pathway.price_cents.isnot(None),
            Pathway.price_cents > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in legacy_rows:
        if min_cents is not None:
            min_pathway_prices[space_id] = int(min_cents)

    # Payment-options pathway prices — derived from published options only.
    effective_price_expr = func.coalesce(
        PaymentOption.override_total_cents,
        PaymentOption.calculated_total_cents,
    )
    # Joined through the grant/legacy union for the same reason as the
    # pathway projection: a grants-first Option has no ``pathway_id``.
    _pairs = pathway_options.pathway_option_pairs()
    options_rows = (
        db.query(Pathway.space_id, func.min(effective_price_expr))
        .join(_pairs, _pairs.c.pathway_id == Pathway.id)
        .join(PaymentOption, PaymentOption.id == _pairs.c.payment_option_id)
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.pricing_mode == "payment_options",
            PaymentOption.status == "published",
            effective_price_expr.isnot(None),
            effective_price_expr > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in options_rows:
        if min_cents is not None:
            existing = min_pathway_prices.get(space_id)
            min_pathway_prices[space_id] = (
                int(min_cents) if existing is None else min(existing, int(min_cents))
            )

    return min_pathway_prices


def min_paid_price_cents_for_space(db: Session, space_id: str) -> int | None:
    """Single-space convenience for the Collective detail endpoint."""
    return min_paid_price_cents_by_space(db, [space_id]).get(space_id)
