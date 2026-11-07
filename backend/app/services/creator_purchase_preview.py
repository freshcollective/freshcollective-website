"""What a creator sees when they ask "how can members buy this?"

Stage 1B.1. The first consumer of
:mod:`app.services.purchase_arrangements`, and deliberately a
**read-only creator surface** rather than a checkout path: it answers a
question, takes no money, and writes nothing.

Why a layer at all
------------------
The resolver answers *what the creator configured*. A creator preview
has to answer something slightly different — *what a member could
actually complete today* — and those two answers genuinely differ in
two places. Neither difference belongs in the resolver: both are
live-environment gates rather than configuration, and the resolver is
deliberately ignorant of them (see its module docstring).

1. **A Pathway on ``pricing_mode='payment_options'``.** Its
   ``price_cents`` may still hold a real figure, and the resolver
   reports that direct arrangement because a mode is the wrong shape of
   answer to "what does this arrangement cost". But
   ``POST /api/checkout/pathway`` refuses the option-less door with a
   400 for exactly that mode. Configured, not purchasable.

2. **Standalone Gathering ticket sales switched off.** A $20 ticket is
   configured perfectly; ``ensure_sales_enabled_or_raise`` refuses it
   on an environment where the two-key guard is not satisfied.
   Configured, not purchasable.

So this module keeps the two answers apart and labels them, which is
what Stage 1B.1 asked for: a creator should be able to tell "I have not
finished setting this up" from "I have set this up and the platform is
not selling it yet". Collapsing them would either accuse the creator of
a mistake they did not make, or promise a sale that cannot happen.

What it does not do
-------------------
* **No pricing of its own.** Every figure comes from
  ``arrangements_for``. This module never multiplies an instalment by a
  count, never picks between two prices, and never falls back to a
  price of its own when one is missing.
* **No eligibility.** Still no member in the question. ``with_reason``
  is the resolver's own hook for marking an arrangement unavailable, so
  the overlay is expressed in the resolver's vocabulary instead of a
  parallel one.
* **No relaxing.** It reads ``pricing_mode`` to *report* the
  restriction, never to bypass it. The restriction stays exactly where
  it is, in the checkout route.
* **It writes nothing** and takes no locks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services import pathway_direct_offer as _direct_offer

from app.services.purchase_arrangements import (
    KIND_GATHERING,
    KIND_OFFERING,
    KIND_PATHWAY,
    KIND_SERIES,
    SOURCE_DIRECT,
    Arrangement,
    arrangements_for,
    with_reason,
)

logger = logging.getLogger(__name__)

#: The one-way switch installed after the $5/$2 mispricing incident.
#: Read here to *report* it; never to work around it.
# Kept exported for callers, but no longer consulted here: Stage 2C
# moved the direct-door question to ``pathway_direct_offer``, which
# is the rule the till applies. A mode could only ever describe one
# door, and a Pathway may now have two.
PRICING_MODE_PAYMENT_OPTIONS = "payment_options"

# ---------------------------------------------------------------------------
# Overlay reasons
# ---------------------------------------------------------------------------

#: Reasons that belong to the live platform rather than to the
#: creator's configuration. Kept distinct from the resolver's reasons
#: because the creator can act on a resolver reason ("publish the
#: schedule") and cannot act on one of these — the honest advice is
#: "ask us", not "fix it".
REASON_PATHWAY_REQUIRES_OPTION = "pathway_requires_payment_option"
REASON_GATHERING_SALES_DISABLED = "gathering_sales_disabled"
#: The Collective's own commercial terms are not in place. Every paid
#: door refuses with a 409; the creator cannot fix this themselves.
REASON_CREATOR_PLAN_NOT_CONFIGURED = "creator_plan_not_configured"
#: The plan exists and forbids commercial use (Community). Every paid
#: door refuses with a 403; the fix is an upgrade.
REASON_CREATOR_PLAN_FORBIDS_PAID = "creator_plan_forbids_paid_offers"

PLATFORM_REASONS: tuple[str, ...] = (
    REASON_PATHWAY_REQUIRES_OPTION,
    REASON_GATHERING_SALES_DISABLED,
    REASON_CREATOR_PLAN_NOT_CONFIGURED,
    REASON_CREATOR_PLAN_FORBIDS_PAID,
)


# ---------------------------------------------------------------------------
# The live-checkout overlay
# ---------------------------------------------------------------------------


def _gathering_sales_blocked() -> bool:
    """Would the ticket till refuse a sale on this environment?

    Calls the real guard rather than reading
    ``standalone_gathering_sales_enabled`` directly, because the guard
    is two-key: the flag alone is not enough in Stripe live mode. A
    preview that read only the first key would promise a sale that the
    second key refuses.
    """
    from app.services.gathering_tickets import (
        TicketSalesDisabled,
        ensure_sales_enabled_or_raise,
    )

    try:
        ensure_sales_enabled_or_raise()
    except TicketSalesDisabled:
        return True
    return False


def _creator_plan_block_reason(db: Session, space: object) -> str | None:
    """Would the creator-plan gate refuse a paid sale in this
    Collective, and why?

    Reuses ``try_resolve_fee_context`` — the display-safe variant of the
    very function every paid door calls — so the preview cannot form a
    second opinion about plan eligibility. ``None`` back from it means
    the guard is on and the creator has no active subscription, which is
    the 409 case; ``permits_paid_offers`` False is the 403 case.

    This was the Stage 1B.1 gap: the overlay asked only whether ticket
    sales were switched on, so a Collective with no Creator Plan showed
    its $45 ticket as **Available** while checkout refused it.
    """
    from app.services.checkout_orchestration import try_resolve_fee_context

    fee_context = try_resolve_fee_context(space, db)
    if fee_context is None:
        return REASON_CREATOR_PLAN_NOT_CONFIGURED
    if not fee_context.permits_paid_offers:
        return REASON_CREATOR_PLAN_FORBIDS_PAID
    return None


def platform_block_reason(
    db: Session,
    arrangement: Arrangement,
    experience_row: object,
    space: object,
) -> str | None:
    """Why live checkout would refuse an arrangement the creator has
    configured correctly, or ``None`` when it would not.

    Only ever consulted for an arrangement the resolver already called
    available — there is nothing to add to one that is already
    unavailable, and the creator's own reason is the more useful of the
    two.

    **The order below is checkout's order**, deliberately, so the
    preview names the same reason the member's refusal would name:

    * a direct Pathway price is refused for ``pricing_mode`` before the
      plan gate is reached (``POST /api/checkout/pathway``);
    * a Gathering ticket is refused for the sales flags first, since
      ``ensure_sales_enabled_or_raise`` is the first line of that
      endpoint;
    * the creator-plan gate then applies to **every paid arrangement**,
      direct or Option, because ``orchestrate_paid_checkout`` and
      ``start_finite_plan_setup`` both enforce it too.

    A free arrangement is not gated: checkout's free path resolves its
    fee context through ``try_resolve_fee_context`` precisely so a
    Collective with no plan can still give things away.
    """
    if arrangement.source == SOURCE_DIRECT:
        if arrangement.experience_kind == KIND_PATHWAY:
            # Stage 2C — asked of the shared rule rather than read off
            # ``pricing_mode`` directly.
            #
            # This branch used to test the mode alone, which was right
            # while a direct price and a Payment Option were mutually
            # exclusive. Once Stage 2B is on they are not, and a
            # creator may deliberately re-enable individual purchase on
            # a Pathway that previously adopted Option pricing. The
            # mode still reads ``payment_options`` on such a row — it
            # is deliberately left alone, because that is what makes
            # the Stage 2B gate reversible — so this reported the
            # direct price as withdrawn while the member surface
            # offered it and the till charged it. The creator was told
            # their live price was not being sold.
            #
            # ``pathway_direct_offer`` is the rule the till itself
            # applies, so the preview now agrees with checkout by
            # construction instead of by coincidence. It is also
            # gate-aware, which keeps the old answer exactly while the
            # gate is shut.
            # Only ``REASON_REQUIRES_OPTION`` is handled here, and
            # that is all this overlay has to handle. The gate-open
            # case — a saved price the creator has not switched on —
            # is already reported by the resolver itself, which marks
            # that arrangement unavailable before this function is
            # reached (``build_preview`` consults the overlay only for
            # arrangements the resolver found available). The mode is
            # the one rule the resolver deliberately declines to read.
            block = _direct_offer.direct_purchase_block_reason(
                experience_row, check_status=False,
            )
            if block == _direct_offer.REASON_REQUIRES_OPTION:
                return REASON_PATHWAY_REQUIRES_OPTION
        elif arrangement.experience_kind == KIND_GATHERING:
            if _gathering_sales_blocked():
                return REASON_GATHERING_SALES_DISABLED

    # Nothing is charged, so nothing is gated.
    if arrangement.is_free:
        return None

    return _creator_plan_block_reason(db, space)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewArrangement:
    """One arrangement, with the two availability answers kept apart."""

    arrangement: Arrangement
    #: The resolver's answer: is the creator's configuration complete
    #: and sellable in principle?
    configured_available: bool
    #: True when configuration is complete but the live platform would
    #: still refuse the sale. The state that needs its own copy.
    blocked_by_platform: bool

    @property
    def available_for_new_purchase(self) -> bool:
        return self.arrangement.available_for_new_purchase

    def as_dict(self) -> dict:
        """The creator-facing shape.

        Carries no ``arrangement_id`` and no schedule id. The preview
        selects nothing and buys nothing, so an identifier would be
        payload a read-only surface has no use for — and Stage 1B.1 is
        explicitly not a checkout path. ``payment_option_id`` *is*
        carried: the preview has to link to the Option editor.

        Field names match ``AnyPaymentSchedule`` in
        ``frontend/src/lib/paymentPlan.ts`` so the existing shared
        schedule formatters read this response unchanged — the member
        wording and the creator wording stay one implementation.
        """
        a = self.arrangement
        return {
            "source": a.source,
            "name": a.name,
            "schedule_name": a.schedule_name,
            "schedule_type": a.schedule_type,
            "currency": a.currency,
            "total_amount_cents": a.total_amount_cents,
            "upfront_amount_cents": a.upfront_amount_cents,
            # A configured deposit nothing collects. Carried so the
            # creator can be warned rather than shown a figure Stripe
            # will never charge — see the resolver's field docstring.
            "unsupported_upfront_amount_cents": (
                a.unsupported_upfront_amount_cents
            ),
            "installment_amount_cents": a.installment_amount_cents,
            "installment_count": a.installment_count,
            "interval": a.interval,
            "is_bundle": a.is_bundle,
            "is_free": a.is_free,
            "included": [
                {"kind": inc.kind, "title": inc.title} for inc in a.included
            ],
            "payment_option_id": a.payment_option_id,
            "available_for_new_purchase": a.available_for_new_purchase,
            "unavailable_reason": a.unavailable_reason,
            "configured_available": self.configured_available,
            "blocked_by_platform": self.blocked_by_platform,
            "is_historical_source": a.is_historical_source,
        }


@dataclass(frozen=True)
class PurchasePreview:
    """Every way one experience can currently be bought."""

    experience_kind: str
    experience_id: str
    title: str | None
    #: The creator's own access setting, so the preview can explain a
    #: free or members-only experience rather than showing an empty
    #: purchase list and implying something is missing.
    access_type: str | None
    arrangements: tuple[PreviewArrangement, ...]

    @property
    def purchasable(self) -> tuple[PreviewArrangement, ...]:
        return tuple(p for p in self.arrangements if p.available_for_new_purchase)

    def as_dict(self) -> dict:
        return {
            "experience_kind": self.experience_kind,
            "experience_id": self.experience_id,
            "title": self.title,
            "access_type": self.access_type,
            "has_purchasable_arrangement": len(self.purchasable) > 0,
            "arrangements": [p.as_dict() for p in self.arrangements],
        }


# ---------------------------------------------------------------------------
# Access setting
# ---------------------------------------------------------------------------


def _access_type_of(kind: str, row: object) -> str | None:
    """The creator's access setting, normalised to a plain string.

    Two different columns answer this depending on the kind, and the
    preview wants one field. Returned as the stored value and mapped to
    copy by the caller — a creator never reads these strings.
    """
    if kind == KIND_PATHWAY:
        raw = getattr(row, "access_type", None)
        return getattr(raw, "value", raw) or "free"
    if kind == KIND_GATHERING:
        # Through the existing normaliser, so a legacy row ("all_members",
        # "pathway_required") reports the current vocabulary rather than a
        # value the client has no copy for.
        from app.services.gathering_types import normalise_access_type

        return normalise_access_type(getattr(row, "booking_access_type", None))
    if kind in (KIND_SERIES, KIND_OFFERING):
        # Neither carries a single access column of its own; access
        # follows from the Options that grant it, which the
        # arrangement list already describes.
        return None
    return None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def build_preview(
    db: Session, *, kind: str, experience_row: object, space: object,
) -> PurchasePreview:
    """The purchase preview for one experience.

    ``experience_row`` and ``space`` are passed in rather than loaded
    here so the caller stays responsible for ownership: the route has
    already proved this row belongs to the Collective being managed.
    Loading either here from an id would move that check into a module
    that has no business making it.

    ``space`` is what the creator-plan gate reads. It must be the
    Collective the experience belongs to — the route resolves it from
    the managed-space check, so the two cannot disagree.
    """
    experience_id = experience_row.id
    found = arrangements_for(db, kind=kind, experience_id=experience_id)
    if found is None:  # pragma: no cover - the route loaded the row
        raise ValueError(f"No {kind} {experience_id!r}")

    previews: list[PreviewArrangement] = []
    for arrangement in found.arrangements:
        configured_available = arrangement.available_for_new_purchase
        blocked = False
        final = arrangement
        if configured_available:
            reason = platform_block_reason(
                db, arrangement, experience_row, space,
            )
            if reason is not None:
                final = with_reason(arrangement, reason)
                blocked = True
        previews.append(
            PreviewArrangement(
                arrangement=final,
                configured_available=configured_available,
                blocked_by_platform=blocked,
            )
        )

    return PurchasePreview(
        experience_kind=found.experience_kind,
        experience_id=found.experience_id,
        title=found.title,
        access_type=_access_type_of(kind, experience_row),
        arrangements=tuple(previews),
    )


__all__ = [
    "PLATFORM_REASONS",
    "PRICING_MODE_PAYMENT_OPTIONS",
    "REASON_GATHERING_SALES_DISABLED",
    "REASON_PATHWAY_REQUIRES_OPTION",
    "PreviewArrangement",
    "PurchasePreview",
    "build_preview",
    "platform_block_reason",
]
