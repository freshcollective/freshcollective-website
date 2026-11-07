"""Stage 2C — the member "Ways to join" cards for one Pathway.

Built from the shared resolver, for the same reason the Series version
is: the resolver already knows every arrangement, what each one charges,
what it includes and whether it can be sold. A second opinion assembled
from the raw columns is how a page ends up advertising a price the till
would refuse.

Why this is a separate module from ``series_arrangement_display``
----------------------------------------------------------------
A Series has no price of its own — every way in is a Payment Option. A
Pathway can be sold directly *and* through Options at once, which is
the whole of Stage 2B, so this builder has to carry two kinds of card
rather than one. Folding that into the Series builder would have meant
changing a module the Gathering Series page depends on, and §2 requires
that page to stay functionally unchanged.

What they do share is the resolver underneath, which is where the
prices and the ordering actually come from, so the two surfaces cannot
disagree about what an Option costs.

Ordering
--------
The resolver's own: the direct arrangement first where there is one,
then Payment Options in the creator's ``position`` order, then each
Option's schedules in theirs. Nothing here re-sorts, and nothing sorts
by price — a cheaper arrangement is not a better one, and choosing for
the member is the product decision this stage exists to undo.

Availability
------------
Unavailable arrangements are dropped rather than rendered greyed out,
matching the Series card and the legacy payload: a draft schedule is
simply absent. The *reasons* are kept for the caller, so a Pathway with
nothing purchasable can say something true instead of rendering an
empty column.

One thing this deliberately does **not** decide: creator-plan
eligibility. ``_schedule_is_member_checkoutable`` does not consult it
and neither does the Series display, so a Collective with no plan shows
buy buttons on both surfaces today. Adding the check here only would
make Pathways and Series disagree, which §2 forbids; it is recorded as
a pre-existing gap instead of half-fixed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.services import pathway_direct_offer as _direct_offer
from app.services.purchase_arrangements import (
    Arrangement,
    REASON_OPTION_ARCHIVED,
    REASON_OPTION_DRAFT,
    REASON_SCHEDULE_DRAFT,
    REASON_UNSUPPORTED_INCLUSION,
    arrangements_for,
)

KIND_PATHWAY = "pathway"
KIND_GATHERING = "gathering"
SOURCE_DIRECT = "direct"
SOURCE_PAYMENT_OPTION = "payment_option"

#: Reasons that disqualify a whole Option, not one schedule on it.
OPTION_LEVEL_REASONS: frozenset[str] = frozenset({
    REASON_OPTION_DRAFT,
    REASON_OPTION_ARCHIVED,
    REASON_UNSUPPORTED_INCLUSION,
})

#: Reasons that hide a single schedule row.
HIDDEN_SCHEDULE_REASONS: frozenset[str] = frozenset({
    REASON_SCHEDULE_DRAFT,
})


@dataclass(frozen=True)
class DisplaySchedule:
    """One way to pay for one Option — a row inside an Option card.

    Shaped to match ``PaymentOptionScheduleSummary`` so the frontend's
    existing ``ScheduleChoice`` component renders it unchanged.
    """

    id: str
    name: str
    schedule_type: str
    total_amount_cents: int
    installment_amount_cents: int | None
    installment_count: int | None
    interval: str | None
    currency: str
    is_member_checkoutable: bool

    def as_payload(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule_type": self.schedule_type,
            "total_amount_cents": self.total_amount_cents,
            "installment_amount_cents": self.installment_amount_cents,
            "installment_count": self.installment_count,
            "interval": self.interval,
            "currency": self.currency,
            "is_member_checkoutable": self.is_member_checkoutable,
        }


@dataclass(frozen=True)
class DisplayArrangement:
    """One card. Either the Pathway's own price or one Payment Option.

    ``source`` is what the frontend branches on, and it is also what
    decides which checkout the button calls — the direct card has no
    Option identifiers to send, which is precisely why substituting one
    arrangement for another is not expressible here.
    """

    source: str
    #: Option name. ``None`` for the direct card, which the member
    #: surface labels itself — the Pathway's title is already the page
    #: heading, so repeating it inside the card says nothing.
    name: str | None = None
    description: str | None = None
    #: Direct card only.
    price_cents: int | None = None
    currency: str | None = None
    #: Option card only.
    payment_option_id: str | None = None
    schedules: list[DisplaySchedule] = field(default_factory=list)
    #: Everything the arrangement grants, the viewed Pathway first.
    #: Empty for a direct purchase: it grants this Pathway and nothing
    #: else, which the card says in words.
    included_titles: list[str] = field(default_factory=list)
    is_bundle: bool = False

    def as_payload(self) -> dict:
        return {
            "source": self.source,
            "name": self.name,
            "description": self.description,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "payment_option_id": self.payment_option_id,
            "schedules": [s.as_payload() for s in self.schedules],
            "included_titles": self.included_titles,
            "is_bundle": self.is_bundle,
        }


def _schedule_from(arrangement: Arrangement) -> DisplaySchedule:
    """``total_amount_cents`` is coerced to 0 the way the legacy
    payload does, so the two shapes agree where there is no difference
    in the price.

    ``installment_amount_cents`` is the resolver's figure — what
    Stripe's subscription price actually charges. The schedule's stored
    ``upfront_amount_cents`` is deliberately not consulted: nothing
    collects it, so presenting it as a first payment would repeat a
    creator's mistake back to a member as a fact.
    """
    return DisplaySchedule(
        id=arrangement.payment_option_schedule_id or "",
        name=arrangement.schedule_name or "",
        schedule_type=arrangement.schedule_type,
        total_amount_cents=arrangement.total_amount_cents or 0,
        installment_amount_cents=arrangement.installment_amount_cents,
        installment_count=arrangement.installment_count,
        interval=arrangement.interval,
        currency=arrangement.currency,
        is_member_checkoutable=arrangement.available_for_new_purchase,
    )


def _included_titles(
    arrangement: Arrangement, experience_id: str, kind: str = KIND_PATHWAY,
) -> list[str]:
    """"Includes New Pathway for Moonlit Circle · Know Yourself".

    The Pathway being viewed comes first, then everything else in the
    resolver's order. Both halves matter: it is the right sentence for
    somebody looking at that Pathway, and the resolver returns
    ``included`` in grant *query* order, which is not deterministic —
    an equivalence test caught that ordering flipping between runs on
    the Series side. A card whose "Includes" line reorders itself
    between page loads would be a bug nobody could reproduce.
    """
    titles = [inc.title for inc in arrangement.included if inc.title]
    this_one = [
        inc.title for inc in arrangement.included
        if inc.kind == kind
        and inc.experience_id == experience_id
        and inc.title
    ]
    if not this_one:
        return titles
    head = this_one[0]
    return [head] + [t for t in titles if t != head]


def build_gathering_ways_to_join(
    db: Session, *, event,
) -> list[DisplayArrangement]:
    """Every arrangement a member could buy one standalone Gathering
    through — Stage 3.

    The same cards, the same resolver and the same availability rules
    as the Pathway list. Only two things differ, and both are about
    the direct door rather than the Options:

    * A Gathering's own price is a ticket, sold by
      ``POST /api/spaces/{slug}/events/{id}/ticket-checkout`` rather
      than the Pathway endpoint, so the caller renders it with its own
      control. ``source='direct'`` still marks it.
    * Whether that door is open is decided by the resolver alone. There
      is no Gathering equivalent of ``pathway_direct_offer``, because
      there is no Stage 2B gate here — ``_direct_gathering`` already
      consults the ticket-sales flag and the shared price validator,
      which is the till's own rule.

    An Option is listed only when it can actually be sold, which while
    ``standalone_gathering_payment_options_enabled`` is off means never:
    ``unfulfillable_grant_reason`` refuses any Option carrying a
    Gathering grant, so this returns the ticket alone.
    """
    return _build(db, kind=KIND_GATHERING, experience=event,
                  direct_is_sellable=True)


def build_ways_to_join(
    db: Session, *, pathway,
) -> list[DisplayArrangement]:
    """Every arrangement a member could buy this Pathway through.

    Returns an empty list when there is nothing to sell — a free or
    members-only Pathway, or one whose only arrangements are
    unavailable. The caller renders no purchase section at all in that
    case rather than an empty one.

    Takes the Pathway row rather than its id because the direct card
    needs the till's own answer about whether that door is open; see
    the comment on ``direct_is_sellable`` below.
    """
    # The direct door, as the *till* decides it — not as the resolver
    # reports it.
    #
    # These genuinely differ, and the difference is load-bearing. The
    # resolver deliberately ignores the Stage 2B gate when it is shut,
    # answering as it did before the gate existed so the shadow
    # comparisons stay meaningful; it therefore calls a dormant price
    # behind a Payment Option "available". ``pathway_direct_offer`` is
    # the rule ``POST /api/checkout/pathway`` applies, so asking it is
    # what keeps this list from advertising a price checkout would
    # refuse. A test asserting the gate-shut case caught this.
    #
    # ``check_status`` is left on: a draft Pathway sells nothing, and
    # unlike the till this builder has not already refused it upstream.
    return _build(
        db, kind=KIND_PATHWAY, experience=pathway,
        direct_is_sellable=(
            _direct_offer.direct_purchase_block_reason(pathway) is None
        ),
    )


def _build(
    db: Session, *, kind: str, experience, direct_is_sellable: bool,
) -> list[DisplayArrangement]:
    """Shared body. ``direct_is_sellable`` is the caller's answer about
    the experience's own price, because only the caller knows which
    till decides it."""
    experience_id = experience.id
    found = arrangements_for(db, kind=kind, experience_id=experience_id)
    if found is None:
        return []

    direct: DisplayArrangement | None = None
    order: list[str] = []
    grouped: dict[str, list[Arrangement]] = {}
    dropped_options: set[str] = set()

    for arrangement in found.arrangements:
        if arrangement.source == SOURCE_DIRECT:
            # Dropped when unavailable for any reason — a dormant
            # price, a Pathway not yet active, an amount that cannot be
            # charged. The reason is not shown to members: it describes
            # a creator's configuration, not anything they can act on.
            if not arrangement.available_for_new_purchase:
                continue
            if not direct_is_sellable:
                continue
            direct = DisplayArrangement(
                source=SOURCE_DIRECT,
                price_cents=arrangement.total_amount_cents,
                currency=arrangement.currency,
            )
            continue

        option_id = arrangement.payment_option_id
        if option_id is None or arrangement.payment_option_schedule_id is None:
            continue
        if arrangement.unavailable_reason in OPTION_LEVEL_REASONS:
            dropped_options.add(option_id)
            continue
        if arrangement.unavailable_reason in HIDDEN_SCHEDULE_REASONS:
            continue
        if not arrangement.available_for_new_purchase:
            # Any other reason a single schedule cannot be sold —
            # instalments switched off, an invalid schedule. Hidden for
            # the same reason: a button that 400s is worse than no
            # button.
            continue
        if option_id not in grouped:
            grouped[option_id] = []
            order.append(option_id)
        grouped[option_id].append(arrangement)

    # An Option disqualified by one of its arrangements is disqualified
    # entirely: the OPTION_LEVEL_REASONS are properties of the Option,
    # so they hold for every schedule on it, and a partial card would
    # be one the member cannot use.
    for option_id in dropped_options:
        grouped.pop(option_id, None)
    order = [o for o in order if o in grouped]

    out: list[DisplayArrangement] = []
    if direct is not None:
        out.append(direct)

    if not order:
        return out

    # Descriptions are Collective prose rather than a property of an
    # arrangement, so they are read here rather than widened onto the
    # resolver. One query for the Options the resolver already chose.
    descriptions = dict(
        db.query(PaymentOption.id, PaymentOption.description)
        .filter(PaymentOption.id.in_(order))
        .all()
    )

    for option_id in order:
        arrangements = grouped[option_id]
        first = arrangements[0]
        out.append(DisplayArrangement(
            source=SOURCE_PAYMENT_OPTION,
            name=first.name,
            description=descriptions.get(option_id),
            payment_option_id=option_id,
            schedules=[_schedule_from(a) for a in arrangements],
            included_titles=_included_titles(first, experience_id, kind),
            is_bundle=first.is_bundle,
        ))

    return out
