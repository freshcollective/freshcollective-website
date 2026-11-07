"""Is a Pathway's own price on sale — the one rule, in one place.

Stage 2B lets a Pathway be sold individually *and* through a Payment
Option at the same time. The moment those stop being mutually
exclusive, "what does this Pathway cost" stops having a single answer,
and the only safe way to present two answers is for each door to say
whether it is open and what it charges.

This module is the direct door's answer. It exists because the question
is asked in two places that must never disagree:

* ``POST /api/checkout/pathway`` — the till, which refuses a closed
  door.
* ``GET`` the member Pathway payload — which must not show a price the
  till would refuse, and must not hide one it would accept.

A disagreement between those two is the worst failure available here:
either a member is shown a price and then told they cannot pay it, or a
creator's live offer becomes invisible. So neither caller re-derives
the rule.

What is deliberately *not* here
-------------------------------
Member eligibility. Whether *this person* may buy — already owns it, is
banned, holds a plan in trouble — belongs to the guards that already
own those questions, and re-deriving any of them here would recreate
the duplication Stage 0 removed. This answers only whether the offer
exists.
"""
from __future__ import annotations

from app.core.config import settings

#: The Pathway is not in a state where anything can be bought.
REASON_NOT_ACTIVE = "pathway_not_active"
#: An Option prices this Pathway, and the Stage 2B gate is shut, so the
#: stored ``price_cents`` beside it is dormant by design.
REASON_REQUIRES_OPTION = "requires_payment_option"
#: The gate is open and the creator has not put this price on sale.
REASON_NOT_OFFERED = "direct_purchase_not_offered"
#: The Pathway is not the kind that has an individual price.
REASON_NOT_ONE_TIME = "access_type_not_one_time"
#: A price that cannot be charged.
REASON_NO_PRICE = "no_valid_price"


def direct_purchase_block_reason(pathway, *, check_status: bool = True) -> str | None:
    """Why the direct door is shut, or ``None`` if it is open.

    Mirrors the till's guards in the till's order, so the till can keep
    its own wording while both callers obey one rule.

    ``check_status`` is False for the till, which has already refused
    every non-active Pathway further up — for *any* request shape,
    including a Payment Option purchase — and whose error message for
    that case is therefore already written and more specific than this
    one.
    """
    if check_status:
        status = getattr(pathway.status, "value", pathway.status)
        if str(status) != "active":
            return REASON_NOT_ACTIVE

    # The gate. Which column decides is the whole of Stage 2B; see
    # ``Pathway.direct_purchase_enabled`` and migration 183.
    #
    # Shut: ``pricing_mode`` decides, exactly as it has. Open:
    # ``direct_purchase_enabled`` decides, because a mode can only ever
    # describe one door and there may now be two. Both default to
    # refusing, so opening the gate puts nothing new on sale by itself.
    if settings.pathway_multiple_purchase_options_enabled:
        if not getattr(pathway, "direct_purchase_enabled", False):
            return REASON_NOT_OFFERED
    else:
        mode = getattr(pathway, "pricing_mode", "legacy") or "legacy"
        if mode == "payment_options":
            return REASON_REQUIRES_OPTION

    access = getattr(pathway.access_type, "value", pathway.access_type)
    if str(access or "free") != "one_time":
        return REASON_NOT_ONE_TIME

    if not pathway.price_cents or pathway.price_cents <= 0:
        return REASON_NO_PRICE

    return None


def direct_purchase_is_available(pathway) -> bool:
    """True when a member could buy this Pathway at its own price."""
    return direct_purchase_block_reason(pathway) is None


def sync_direct_offer_flag(pathway) -> None:
    """Keep ``direct_purchase_enabled`` true to what the till does today.

    Called whenever a creator changes a Pathway's access configuration
    **while the Stage 2B gate is shut**, and it is what makes opening
    that gate a safe, boring act.

    Without it there would be a trap. Migration 183 set the column from
    the state of the world on the day it ran, but with the gate shut
    nothing reads the column and — without this — nothing would write
    it either. Every Pathway a creator put on a direct price in the
    meantime would sit at ``false``, and the day the gate opened their
    live offer would vanish. The creator would have changed nothing.

    So the column is maintained continuously, by exactly the rule the
    183 backfill used: a Pathway the direct door sells is ``true``, and
    anything else is ``false``. While the gate is shut this column is a
    mirror of ``pricing_mode`` + ``access_type`` + ``price_cents``, and
    flipping the gate therefore changes no Pathway's behaviour. Once
    the gate is open the creator's own control owns it, and this is not
    called — which is the point: that is when the two can legitimately
    differ, because an Option no longer implies the direct price is
    off.

    ``status`` is excluded for the reason the backfill excludes it: a
    draft Pathway is refused by the status guard at the door, and
    writing ``false`` here would mean publishing a previously-drafted
    priced Pathway found its price silently off sale.
    """
    if settings.pathway_multiple_purchase_options_enabled:
        return

    mode = getattr(pathway, "pricing_mode", "legacy") or "legacy"
    access = getattr(pathway.access_type, "value", pathway.access_type)
    pathway.direct_purchase_enabled = bool(
        mode != "payment_options"
        and str(access or "free") == "one_time"
        and pathway.price_cents
        and pathway.price_cents > 0
    )
