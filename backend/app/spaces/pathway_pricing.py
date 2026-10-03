"""The minimum price a visitor would pay for any paid Pathway inside a
Collective — the "Pathways from $X" headline.

Extracted so the Explore list and the Collective detail endpoint read
the same number. They did not: ``hydrate_public_space_cards`` derived
it here, while the public About page re-derived its own in the browser
from ``pathway.price_cents``. A Pathway on
``pricing_mode='payment_options'`` keeps its legacy ``price_cents``
column untouched after the switch, so that column is stale by design —
Test Pathway in production carries ``price_cents=500`` next to a
published $2 Option, and the About page advertised "Pathways from
$5 AUD" for a Pathway that costs $2.

The rule
--------

* ``pricing_mode='legacy'`` → ``Pathway.price_cents``. Unchanged, and
  deliberately still SQL: these Pathways have no schedules to consult.

* ``pricing_mode='payment_options'`` → the Option's headline price, as
  :func:`purchase_schedule_view.headline_price_cents` defines it. That
  is the pay-in-full total where one is checkoutable, otherwise the
  total of the cheapest checkoutable schedule, and only
  ``effective_price_cents`` when no schedule can describe the Option at
  all.

Both modes are considered together and the lower wins, so a Collective
holding one of each advertises the cheaper door.

Why the Option's own columns are not the price
----------------------------------------------
This used to be ``COALESCE(override_total_cents, calculated_total_cents)``
in SQL, which is the same mistake the joining doors made before
``purchase_schedule_view`` existed: those are *authoring* fields and are
routinely NULL on real Options, because the commerce UI treats schedules
as the source of truth. Test Connect Instalments in production has both
NULL and expresses its whole price through a published schedule — two
weekly payments of $2 — so the COALESCE produced NULL and the About page
fell back to "Paid pathways available separately" for a Collective that
plainly sells something.

The headline is the **total commitment**, not the instalment: that
Option's Collective headline is $4, not $2. A member comparing
Collectives is comparing what they are committing to.

Checkoutability is part of the price
------------------------------------
Only schedules ``_schedule_is_member_checkoutable`` accepts are
considered — the same predicate the checkout endpoint enforces, reached
through ``schedule_view``. A Collective must not advertise a price
whose only payment method the backend would refuse. One consequence
worth knowing: ``recurring_installments`` schedules are gated on
``settings.finite_plan_member_checkout_enabled``, so with that flag off
a plan-only Option contributes no price and the surface falls back to
generic copy — correctly, because nobody can buy it yet.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.payment_option import PaymentOption
from app.models.platform import Pathway
from app.services import pathway_payment_options as pathway_options
from app.spaces.purchase_schedule_view import (
    headline_price_cents,
    published_schedules_by_option,
    schedule_view,
)


# Pathways that cost something. A 'free' or 'included' Pathway has no
# price to advertise and must not drag the minimum to zero.
PAID_ACCESS_TYPES = ("one_time", "subscription")


def _legacy_minimums(db: Session, space_ids: list[str]) -> dict[str, int]:
    """Cheapest legacy-priced Pathway per space, from ``price_cents``."""
    out: dict[str, int] = {}
    rows = (
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
    for space_id, min_cents in rows:
        if min_cents is not None:
            out[space_id] = int(min_cents)
    return out


def _payment_option_minimums(
    db: Session, space_ids: list[str],
) -> dict[str, int]:
    """Cheapest Option headline per space, across payment-options Pathways.

    A constant number of queries regardless of how many Collectives
    are being listed: the pairs join, one batched grant fetch, and one
    bulk schedule fetch. The Explore page lists every public Collective
    at once, so a per-Option round trip here would be an N+1 on the
    busiest public endpoint.
    """
    out: dict[str, int] = {}

    # Which published Options sell an active payment-options Pathway,
    # and in which space. Joined through the grant/legacy union for the
    # same reason as the pathway projection: a grants-first Option has
    # no ``pathway_id``.
    _pairs = pathway_options.pathway_option_pairs()
    rows = (
        db.query(Pathway.space_id, PaymentOption)
        .join(_pairs, _pairs.c.pathway_id == Pathway.id)
        .join(PaymentOption, PaymentOption.id == _pairs.c.payment_option_id)
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.pricing_mode == "payment_options",
            PaymentOption.status == "published",
        )
        # ``_schedule_is_member_checkoutable`` reads ``option.grants``
        # to decide whether a finite plan is fulfillable, which is one
        # query per Option unless the collection is batched. The model
        # already declares ``lazy="selectin"``, so this is belt and
        # braces rather than the thing doing the work — stated here so
        # that a change to the model default cannot quietly make the
        # Explore listing quadratic. ``TestTheListingDoesNotGoQuadratic``
        # fails either way if it does.
        .options(selectinload(PaymentOption.grants))
        .all()
    )
    if not rows:
        return out

    # One Option can sell several Pathways in the same Collective, and
    # one Pathway can be sold by several Options. Collapse to unique
    # Options so each headline is computed once.
    options_by_id: dict[str, PaymentOption] = {}
    space_ids_by_option: dict[str, set[str]] = {}
    for space_id, option in rows:
        options_by_id[option.id] = option
        space_ids_by_option.setdefault(option.id, set()).add(space_id)

    schedules_by_option = published_schedules_by_option(
        db, list(options_by_id),
    )

    for option_id, option in options_by_id.items():
        # The canonical projection, identical to what the joining doors
        # and the Series sidebar show for the same Option.
        views = [
            schedule_view(s, option)
            for s in schedules_by_option.get(option_id, [])
        ]
        headline = headline_price_cents(views, option)
        # An Option with no describable price contributes nothing. Zero
        # is excluded for the same reason the legacy branch excludes it:
        # a free door is not a "from" price.
        if headline is None or headline <= 0:
            continue
        for space_id in space_ids_by_option[option_id]:
            existing = out.get(space_id)
            out[space_id] = (
                headline if existing is None else min(existing, headline)
            )
    return out


def min_paid_price_cents_by_space(
    db: Session, space_ids: list[str],
) -> dict[str, int]:
    """Map space id → cheapest paid Pathway price in cents.

    Spaces with no purchasable Pathway are absent from the mapping, so
    callers can use ``.get(space_id)`` to mean "nothing paid to show".
    """
    if not space_ids:
        return {}

    minimums = _legacy_minimums(db, space_ids)
    for space_id, cents in _payment_option_minimums(db, space_ids).items():
        existing = minimums.get(space_id)
        minimums[space_id] = cents if existing is None else min(existing, cents)
    return minimums


def min_paid_price_cents_for_space(db: Session, space_id: str) -> int | None:
    """Single-space convenience for the Collective detail endpoint."""
    return min_paid_price_cents_by_space(db, [space_id]).get(space_id)
