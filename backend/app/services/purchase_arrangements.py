"""How an experience can be bought — one answer, one price each.

Stage 1A. **Nothing in production calls this yet**, deliberately: it is
built and proved here so Stage 1B can integrate it one surface at a
time with a rollback path. Every live purchase decision still runs
through the code it ran through yesterday.

The problem it exists to solve
-----------------------------
A Pathway sat on ``pricing_mode='legacy'`` with ``price_cents=500``
while a published Payment Option granted it for 200. Checkout charged
$5. Nothing was wrong with the Option or the grant — every consumer
asked ``Pathway.pricing_mode`` which price to use, and a *mode* cannot
answer a question about *which of two arrangements the member chose*.
``pricing_mode`` became a one-way switch to make the ambiguous state
unreachable, which is a sound guard and a dead end for the product: a
direct price and a bundle are both legitimate ways to sell the same
Pathway.

So this module replaces the question rather than the answer. Instead of
"what mode is this experience in", it asks "what arrangements exist,
and what does each one cost" — and gives every arrangement its own
identity and its own authoritative price. Two arrangements for one
Pathway stop being ambiguous because neither is "the" price; the member
picks one by id, and :func:`resolve_arrangement` re-derives that one's
price from the record that owns it.

Three concepts, kept apart
--------------------------
``experience``
    What is being bought: a Pathway, a Gathering Series, a standalone
    Gathering, an Offering.
``arrangement``
    A way to buy it: a direct price, or one schedule of one Payment
    Option. This is what a member selects and what a price belongs to.
``schedule``
    How an arrangement is paid: in full, or in instalments. A Payment
    Option commonly has two, and they are not interchangeable — EMBODY
    Awaken is $180 in full *or* 10 × $18, and ``total_amount_cents``
    and ``installment_amount_cents`` must never be read as each other.

One arrangement therefore wraps exactly one schedule. "Awaken" is not
an arrangement; "Awaken, paid in full" and "Awaken, 10 weekly
payments" are two, with two ids and two price shapes.

What this module does NOT do
----------------------------
* **No member context, and no eligibility.** It answers what the
  *creator* configured, not whether a given person may buy it. Who may
  buy is already decided by guards that must stay single-sourced —
  ``check_same_option_not_active``, the legacy single-Pathway 409,
  ``AlreadyHasTicket``, ``check_not_banned_or_raise`` and the
  creator-plan gate. Re-deriving any of those here would recreate
  exactly the duplication Stage 0 removed.
* **It never reads ``pricing_mode``.** Not to relax it — the live
  routes still enforce it and Stage 1A does not touch them — but
  because a mode is the wrong shape of answer. An arrangement named by
  id needs no mode to price it.
* **It writes nothing** and takes no locks.
* **It does not decide fulfilment.** Whether a purchase can be applied
  is ``checkout_orchestration.unfulfillable_grant_reason``, reused here
  rather than restated.

Reuse, not re-implementation
----------------------------
``option_is_fulfillable`` (Stage 0's shared rule),
``_schedule_is_member_checkoutable`` (the predicate the till agrees
with), ``validate_paid_gathering_price`` (trusted ticket pricing) and
``published_options_for_pathway`` (grant-or-legacy association) are all
called, not copied. The cross-check in
``tests/test_purchase_arrangements.py`` asserts this module and that
predicate agree on every shape, so a third opinion cannot appear.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.offering import Offering
from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_GATHERING,
    GRANT_KIND_OFFERING,
    GRANT_KIND_PATHWAY,
    PaymentOptionGrant,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Event, EventSeries, Pathway

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Experience kinds. Deliberately the same strings as
#: ``PaymentOptionGrant.grant_kind`` so a grant row and a resolver
#: request never need translating between them.
KIND_PATHWAY = GRANT_KIND_PATHWAY
KIND_SERIES = GRANT_KIND_EVENT_SERIES
KIND_GATHERING = GRANT_KIND_GATHERING
KIND_OFFERING = GRANT_KIND_OFFERING

ALL_KINDS: tuple[str, ...] = (
    KIND_PATHWAY, KIND_SERIES, KIND_GATHERING, KIND_OFFERING,
)

#: Where an arrangement's price comes from.
SOURCE_DIRECT = "direct"
SOURCE_PAYMENT_OPTION = "payment_option"

#: ``schedule_type`` for a direct price. The Payment Option values
#: (``pay_in_full``, ``recurring_installments``, ``manual``) are the
#: schedule's own and pass through unchanged.
SCHEDULE_DIRECT = "direct"

#: Machine-readable reasons an arrangement is not available for a new
#: purchase. Stable strings — a caller may branch on them, and copy
#: lives with the caller rather than here.
REASON_OPTION_DRAFT = "option_not_published"
REASON_OPTION_ARCHIVED = "option_archived"
REASON_SCHEDULE_DRAFT = "schedule_not_published"
REASON_UNSUPPORTED_INCLUSION = "unsupported_inclusion"
REASON_INSTALMENTS_NOT_ENABLED = "instalments_not_enabled"
REASON_SCHEDULE_INVALID = "schedule_invalid"
REASON_SCHEDULE_UNSUPPORTED = "schedule_type_unsupported"
REASON_PRICE_NOT_SET = "price_not_set"
REASON_PRICE_INVALID = "price_invalid"
REASON_EXPERIENCE_UNAVAILABLE = "experience_unavailable"
#: Stage 2B — the Pathway has a price, and the creator has not put it
#: on sale. A stored price is not an offer; see
#: ``Pathway.direct_purchase_enabled``.
REASON_DIRECT_PURCHASE_OFF = "direct_purchase_not_offered"


class ArrangementError(Exception):
    """Base for the resolver's refusals."""


class UnknownExperienceKind(ArrangementError):
    pass


class ArrangementNotFound(ArrangementError):
    """The named arrangement does not exist, or does not belong to the
    experience it was claimed for."""


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IncludedExperience:
    """One experience an arrangement grants. Mirrors the grant model
    rather than inventing a parallel description of a bundle."""

    kind: str
    experience_id: str
    title: str | None
    #: Series-grant allowances, carried through verbatim. ``None`` on
    #: every other kind — the grant table's CHECK constraints forbid
    #: them there, so a value would be a corrupted row.
    sessions_per_week: int | None = None
    total_sessions: int | None = None


@dataclass(frozen=True)
class Arrangement:
    """One way to buy one experience, with one authoritative price.

    ``arrangement_id`` is the whole point. It is stable, derivable from
    the rows it describes, and parseable back into them — so a client
    can hand one back and :func:`resolve_arrangement` can re-derive the
    price without ever being told what the price is.
    """

    arrangement_id: str
    source: Literal["direct", "payment_option"]

    # What is being bought.
    experience_kind: str
    experience_id: str
    space_id: str

    # Which rows this arrangement is made of. Both ``None`` for a
    # direct price — there is no Option behind it.
    payment_option_id: str | None
    payment_option_schedule_id: str | None

    #: Member-facing label. The Option's name for an Option
    #: arrangement, the experience's own title for a direct price.
    name: str
    #: The schedule's name ("Pay in full", "Weekly payments"), or None
    #: for a direct price.
    schedule_name: str | None

    # The price. Exactly one record owns it; see the module docstring.
    currency: str
    schedule_type: str
    total_amount_cents: int | None
    #: What actually leaves the member's account first. For an
    #: instalment plan this is the first instalment, because that is
    #: what Stripe's subscription price charges — see
    #: ``unsupported_upfront_amount_cents`` for why it is never the
    #: schedule's own ``upfront_amount_cents``.
    upfront_amount_cents: int | None
    installment_amount_cents: int | None
    installment_count: int | None
    interval: str | None

    # Presentation.
    is_bundle: bool
    included: tuple[IncludedExperience, ...]

    # Availability. ``available_for_new_purchase`` is about selling it
    # today; it says nothing about access somebody already bought —
    # see ``is_historical_source``.
    available_for_new_purchase: bool
    unavailable_reason: str | None
    #: True when this arrangement can still legitimately be the source
    #: of access a member already holds, even though no new purchase
    #: may be made through it. An archived Option is the case this
    #: exists for: ``unlock_option_ids_for_pathway`` accepts
    #: ``archived`` precisely so historical buyers keep what they paid
    #: for, and conflating that with "sellable" would either strand
    #: those members or quietly put a retired price back on sale.
    is_historical_source: bool = False
    #: A deposit the creator configured on the schedule that nothing
    #: collects.
    #:
    #: ``PaymentOptionSchedule.upfront_amount_cents`` is settable in
    #: three creator editors and stored, and **no billing code reads
    #: it**: ``stripe_finite_plan`` builds the subscription price from
    #: ``installment_amount_cents`` at a fixed interval and there is no
    #: separate deposit charge anywhere in the plan lifecycle. So a
    #: creator who sets one believes they are collecting a deposit and
    #: are not.
    #:
    #: Reporting it as ``upfront_amount_cents`` would repeat the
    #: creator's mistake back to them as a fact. It is carried
    #: separately instead, set only when a value is stored and differs
    #: from what Stripe will charge, so a surface can warn rather than
    #: either lying or hiding it.
    unsupported_upfront_amount_cents: int | None = None

    @property
    def is_instalment_plan(self) -> bool:
        return self.schedule_type == "recurring_installments"

    @property
    def is_free(self) -> bool:
        """Nothing to pay. ``total_amount_cents`` of 0 and of ``None``
        are both free, and are different states: 0 is a price the
        creator set, ``None`` is one they have not."""
        return (self.total_amount_cents or 0) == 0


@dataclass(frozen=True)
class ExperienceArrangements:
    """Every arrangement configured for one experience."""

    experience_kind: str
    experience_id: str
    space_id: str
    title: str | None
    arrangements: tuple[Arrangement, ...] = field(default_factory=tuple)

    @property
    def purchasable(self) -> tuple[Arrangement, ...]:
        return tuple(a for a in self.arrangements if a.available_for_new_purchase)

    @property
    def direct(self) -> Arrangement | None:
        """At most one. A direct price is a single column on the
        experience, so there cannot be two."""
        return next(
            (a for a in self.arrangements if a.source == SOURCE_DIRECT), None,
        )

    def by_id(self, arrangement_id: str) -> Arrangement | None:
        return next(
            (a for a in self.arrangements if a.arrangement_id == arrangement_id),
            None,
        )


# ---------------------------------------------------------------------------
# Arrangement identity
# ---------------------------------------------------------------------------


def direct_arrangement_id(kind: str, experience_id: str) -> str:
    return f"direct:{kind}:{experience_id}"


def option_arrangement_id(option_id: str, schedule_id: str) -> str:
    return f"option:{option_id}:schedule:{schedule_id}"


# ---------------------------------------------------------------------------
# Experience loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Experience:
    kind: str
    id: str
    space_id: str
    title: str | None
    row: object


def _load_experience(db: Session, kind: str, experience_id: str) -> _Experience | None:
    if kind == KIND_PATHWAY:
        row = db.get(Pathway, experience_id)
    elif kind == KIND_SERIES:
        row = db.get(EventSeries, experience_id)
    elif kind == KIND_GATHERING:
        row = db.get(Event, experience_id)
    elif kind == KIND_OFFERING:
        row = db.get(Offering, experience_id)
    else:
        raise UnknownExperienceKind(
            f"{kind!r} is not an experience kind; expected one of {ALL_KINDS}"
        )
    if row is None:
        return None
    return _Experience(
        kind=kind, id=experience_id, space_id=row.space_id,
        title=getattr(row, "title", None), row=row,
    )


# ---------------------------------------------------------------------------
# Direct prices
# ---------------------------------------------------------------------------


def _direct_arrangement(exp: _Experience) -> Arrangement | None:
    """The experience's own price, where its editor has one.

    Returns ``None`` when the experience has no direct-price concept at
    all, as distinct from having one that is unset — an unset price
    still produces an arrangement, marked unavailable with
    ``price_not_set``, because a creator who meant to set a price and
    did not should be visible to a creator preview rather than absent
    from it.

    **Offerings deliberately have no direct arrangement.** Their
    Pricing tab does not write a standalone price path: it provisions a
    mirror ``PaymentOption`` with an ``offering`` grant and a
    pay-in-full schedule (``services/offering_commerce.sync``). That
    Option is found by the Payment Option pass below, so emitting a
    direct arrangement as well would list one price twice.
    """
    if exp.kind == KIND_PATHWAY:
        return _direct_pathway(exp)
    if exp.kind == KIND_GATHERING:
        return _direct_gathering(exp)
    return None


def _base_direct(
    exp: _Experience, *, currency: str, total: int | None,
    reason: str | None, name: str,
) -> Arrangement:
    return Arrangement(
        arrangement_id=direct_arrangement_id(exp.kind, exp.id),
        source=SOURCE_DIRECT,
        experience_kind=exp.kind,
        experience_id=exp.id,
        space_id=exp.space_id,
        payment_option_id=None,
        payment_option_schedule_id=None,
        name=name,
        schedule_name=None,
        currency=currency,
        schedule_type=SCHEDULE_DIRECT,
        total_amount_cents=total,
        upfront_amount_cents=total,
        installment_amount_cents=None,
        installment_count=None,
        interval=None,
        is_bundle=False,
        # A direct price buys exactly the experience it sits on.
        included=(
            IncludedExperience(
                kind=exp.kind, experience_id=exp.id, title=exp.title,
            ),
        ),
        available_for_new_purchase=reason is None,
        unavailable_reason=reason,
    )


def _direct_offer_is_on(pathway) -> bool:
    """Is the Pathway's own price an active offer?

    Consulted only once the Stage 2B gate is open. While it is shut
    this returns True unconditionally, so every answer this module
    gives is byte-identical to the one it gave before the column
    existed — ``pricing_mode`` is still the thing the live routes
    enforce, and §20 requires flag-off behaviour to be unchanged.

    This is not the ``pricing_mode`` rule the module docstring declines
    to read, and it is not a mode. ``direct_purchase_enabled`` is a
    fact about one arrangement — whether *this* price is for sale —
    which is exactly the shape of answer an arrangement carries. A mode
    could only ever describe one door at a time, which is the
    assumption Stage 2B removes.
    """
    from app.core.config import settings

    if not settings.pathway_multiple_purchase_options_enabled:
        return True
    return bool(getattr(pathway, "direct_purchase_enabled", False))


def _direct_pathway(exp: _Experience) -> Arrangement | None:
    """``Pathway.price_cents``, the price the option-less checkout door
    reads. Only ``one_time`` is offered: ``access_type='subscription'``
    is settable on the row but ``POST /api/checkout/pathway`` refuses
    anything but ``one_time``, so a subscription arrangement would be
    one nothing can sell."""
    p = exp.row
    access = getattr(p.access_type, "value", p.access_type) or "free"
    if access != "one_time":
        return None

    status = getattr(p.status, "value", p.status)
    reason: str | None = None
    if status != "active":
        reason = REASON_EXPERIENCE_UNAVAILABLE
    elif p.price_cents is None:
        reason = REASON_PRICE_NOT_SET
    elif p.price_cents <= 0:
        reason = REASON_PRICE_INVALID
    elif not _direct_offer_is_on(p):
        reason = REASON_DIRECT_PURCHASE_OFF

    return _base_direct(
        exp,
        currency=(p.currency or "AUD").upper(),
        total=p.price_cents,
        reason=reason,
        name=exp.title or "This Pathway",
    )


def _direct_gathering(exp: _Experience) -> Arrangement | None:
    """``Event.ticket_price_cents``, through the same validator the
    ticket checkout trusts.

    Only a ``paid_separately`` Gathering has a direct price. Every
    other ``booking_access_type`` is an access rule rather than a
    price — included with the Collective, with a Pathway, with a Series
    pass, or invitation only — and none of them is purchased.
    """
    e = exp.row
    if getattr(e, "booking_access_type", None) != "paid_separately":
        return None

    from app.services.ticket_pricing import (
        TicketPricingError,
        normalise_currency,
        validate_paid_gathering_price,
    )

    reason: str | None = None
    currency = "AUD"
    if not e.is_published or getattr(e, "status", "active") != "active":
        reason = REASON_EXPERIENCE_UNAVAILABLE
    if e.ticket_price_cents is None:
        reason = reason or REASON_PRICE_NOT_SET
    if reason is None:
        try:
            _price, currency = validate_paid_gathering_price(
                e.ticket_price_cents, e.ticket_currency,
            )
        except TicketPricingError:
            # Reachable only if the row got past
            # ``ck_events_ticket_price_valid_when_published``. Reported
            # rather than raised: a creator preview should say the
            # price is wrong, not fail to load.
            reason = REASON_PRICE_INVALID
    if currency == "AUD" and e.ticket_currency:
        try:
            currency = normalise_currency(e.ticket_currency)
        except Exception:  # pragma: no cover - defensive
            currency = "AUD"

    return _base_direct(
        exp,
        currency=currency,
        total=e.ticket_price_cents,
        reason=reason,
        name=exp.title or "This Gathering",
    )


# ---------------------------------------------------------------------------
# Payment Option arrangements
# ---------------------------------------------------------------------------


def _options_granting(db: Session, exp: _Experience) -> list[PaymentOption]:
    """Every Option in this Collective that grants this experience, at
    any status.

    Draft and archived are included on purpose — a creator preview
    wants to see them, and an archived Option has to be reportable as a
    historical access source. Each one is then marked unavailable with
    its own reason, so nothing can be sold by accident.

    Scoped to the experience's own Collective. A grant row cannot
    legitimately cross Collectives, and filtering here means a
    corrupted row cannot leak one Collective's price onto another's
    experience.
    """
    col = {
        KIND_PATHWAY: PaymentOptionGrant.pathway_id,
        KIND_SERIES: PaymentOptionGrant.series_id,
        KIND_GATHERING: PaymentOptionGrant.event_id,
        KIND_OFFERING: PaymentOptionGrant.offering_id,
    }[exp.kind]

    granted_ids = select(PaymentOptionGrant.payment_option_id).where(
        PaymentOptionGrant.grant_kind == exp.kind,
        col == exp.id,
    )

    clauses = [PaymentOption.id.in_(granted_ids)]
    if exp.kind == KIND_PATHWAY:
        # The legacy column. An Option authored through the old Pathway
        # editor carries ``pathway_id`` and no grant row, and those
        # Pathways must keep selling — the same both-links rule
        # ``pathway_payment_options`` states for the member surfaces.
        clauses.append(PaymentOption.pathway_id == exp.id)

    return (
        db.query(PaymentOption)
        .filter(PaymentOption.space_id == exp.space_id, or_(*clauses))
        .order_by(PaymentOption.position, PaymentOption.id)
        .all()
    )


def _included_for(db: Session, option: PaymentOption) -> tuple[IncludedExperience, ...]:
    """What an Option grants, titled. Reads the grant rows — the model
    that already answers this — rather than describing a bundle a
    second way."""
    grants = sorted(
        list(option.grants or []), key=lambda g: (g.position, g.id),
    )
    if not grants:
        return ()

    ids_by_kind: dict[str, set[str]] = {}
    for g in grants:
        target = (
            g.pathway_id or g.series_id or g.event_id or g.offering_id
        )
        if target:
            ids_by_kind.setdefault(g.grant_kind, set()).add(target)

    titles: dict[tuple[str, str], str] = {}
    for kind, model in (
        (KIND_PATHWAY, Pathway), (KIND_SERIES, EventSeries),
        (KIND_GATHERING, Event), (KIND_OFFERING, Offering),
    ):
        ids = ids_by_kind.get(kind)
        if not ids:
            continue
        for row_id, title in db.query(model.id, model.title).filter(
            model.id.in_(ids),
        ).all():
            titles[(kind, row_id)] = title

    out: list[IncludedExperience] = []
    for g in grants:
        target = g.pathway_id or g.series_id or g.event_id or g.offering_id
        if not target:  # pragma: no cover — CHECK constraint forbids it
            continue
        out.append(IncludedExperience(
            kind=g.grant_kind,
            experience_id=target,
            title=titles.get((g.grant_kind, target)),
            sessions_per_week=g.sessions_per_week,
            total_sessions=g.total_sessions,
        ))
    return tuple(out)


def _option_unavailable_reason(
    option: PaymentOption, schedule: PaymentOptionSchedule,
) -> str | None:
    """Why this Option-and-schedule cannot be sold today, in the order
    the reasons matter.

    Checked most-structural first, so the reason a creator is shown is
    the one they can act on. An archived Option with a draft schedule
    is archived; telling them to publish the schedule would be useless
    advice.

    The fulfilment question comes from
    ``checkout_orchestration.unfulfillable_grant_reason`` — Stage 0's
    shared rule, reused rather than restated — and the schedule
    questions from ``_schedule_is_member_checkoutable``, the predicate
    the till agrees with. This function adds no rule of its own; it only
    distinguishes the reasons the booleans flatten.
    """
    from app.core.config import settings
    from app.services.checkout_orchestration import (
        unfulfillable_grant_reason,
    )

    status = getattr(option.status, "value", option.status)
    if status == "archived":
        return REASON_OPTION_ARCHIVED
    if status != "published":
        return REASON_OPTION_DRAFT

    if getattr(schedule, "status", None) != "published":
        return REASON_SCHEDULE_DRAFT

    if unfulfillable_grant_reason(option) is not None:
        return REASON_UNSUPPORTED_INCLUSION

    schedule_type = getattr(schedule, "schedule_type", None)
    if schedule_type == "pay_in_full":
        return None
    if schedule_type == "recurring_installments":
        if not settings.finite_plan_member_checkout_enabled:
            return REASON_INSTALMENTS_NOT_ENABLED
        from app.services.schedule_validation import (
            ScheduleValidationError,
            validate_recurring_installments_row,
        )
        try:
            validate_recurring_installments_row(schedule)
        except ScheduleValidationError:
            return REASON_SCHEDULE_INVALID
        return None
    return REASON_SCHEDULE_UNSUPPORTED


def _unsupported_upfront(schedule) -> int | None:
    """A configured deposit that nothing will collect, or ``None``.

    Only meaningful for an instalment plan — a pay-in-full schedule's
    single charge *is* its total, so an upfront on one says nothing
    different. Returns ``None`` when the stored value happens to equal
    the first instalment, because then there is no discrepancy to warn
    about.
    """
    if schedule.schedule_type != "recurring_installments":
        return None
    stored = schedule.upfront_amount_cents
    if stored is None:
        return None
    if stored == schedule.installment_amount_cents:
        return None
    return stored


def _option_arrangements(
    db: Session, exp: _Experience, option: PaymentOption,
) -> list[Arrangement]:
    """One arrangement per schedule.

    Every schedule, not only the published ones, for the same reason
    ``_options_granting`` returns every status: a creator preview
    should see a draft payment method as a draft rather than as
    nothing. Each carries its own reason.
    """
    schedules = (
        db.query(PaymentOptionSchedule)
        .filter(PaymentOptionSchedule.payment_option_id == option.id)
        .order_by(
            PaymentOptionSchedule.position, PaymentOptionSchedule.created_at,
        )
        .all()
    )
    included = _included_for(db, option)
    option_status = getattr(option.status, "value", option.status)
    out: list[Arrangement] = []

    for s in schedules:
        reason = _option_unavailable_reason(option, s)
        out.append(Arrangement(
            arrangement_id=option_arrangement_id(option.id, s.id),
            source=SOURCE_PAYMENT_OPTION,
            experience_kind=exp.kind,
            experience_id=exp.id,
            space_id=exp.space_id,
            payment_option_id=option.id,
            payment_option_schedule_id=s.id,
            name=option.name,
            schedule_name=s.name,
            # The schedule's currency, never the Option's. The Option's
            # authoring totals (``override_total_cents`` /
            # ``calculated_total_cents``) are frequently NULL in
            # production because the commerce UI treats schedules as the
            # source of truth — the bug ``purchase_schedule_view`` was
            # written to fix.
            currency=(s.currency or option.currency or "AUD").upper(),
            schedule_type=s.schedule_type,
            total_amount_cents=s.total_amount_cents,
            # What leaves the member's account first — taken from what
            # Stripe actually charges, not from what the schedule says.
            #
            # An earlier version preferred the schedule's stored
            # ``upfront_amount_cents`` when set. That was wrong: no
            # billing code reads that column, so the figure would never
            # be collected. For an instalment plan the first charge is
            # always the first instalment; for pay-in-full it is the
            # total.
            upfront_amount_cents=(
                s.installment_amount_cents
                if s.schedule_type == "recurring_installments"
                else s.total_amount_cents
            ),
            unsupported_upfront_amount_cents=_unsupported_upfront(s),
            installment_amount_cents=s.installment_amount_cents,
            installment_count=s.installment_count,
            interval=s.interval or s.stripe_interval,
            # A bundle is "grants more than the experience asked
            # about", counted from the grant rows.
            is_bundle=len(included) > 1,
            included=included,
            available_for_new_purchase=reason is None,
            unavailable_reason=reason,
            # Archived Options keep unlocking what their buyers bought
            # — ``unlock_option_ids_for_pathway`` accepts ``archived``
            # alongside ``published`` and refuses only ``draft``.
            is_historical_source=(option_status == "archived"),
        ))
    return out


# ---------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------


def arrangements_for(
    db: Session, *, kind: str, experience_id: str,
) -> ExperienceArrangements | None:
    """Every arrangement configured for one experience.

    Creator configuration only — no member, no eligibility. Returns
    ``None`` when the experience does not exist; raises
    :class:`UnknownExperienceKind` for a kind that is not one.

    Order: the direct price first where there is one, then Payment
    Options in the creator's own ``position`` order, then each Option's
    schedules in theirs. That matches the agreed presentation decision
    — show the individual purchase first — without the resolver
    deciding anything about presentation beyond a stable order.
    """
    exp = _load_experience(db, kind, experience_id)
    if exp is None:
        return None

    arrangements: list[Arrangement] = []
    direct = _direct_arrangement(exp)
    if direct is not None:
        arrangements.append(direct)
    for option in _options_granting(db, exp):
        arrangements.extend(_option_arrangements(db, exp, option))

    return ExperienceArrangements(
        experience_kind=exp.kind,
        experience_id=exp.id,
        space_id=exp.space_id,
        title=exp.title,
        arrangements=tuple(arrangements),
    )


def resolve_arrangement(
    db: Session, *, kind: str, experience_id: str, arrangement_id: str,
) -> Arrangement:
    """Re-derive one named arrangement from the database.

    **This is the price-integrity entry point.** A caller passes an
    *identifier* and gets back a price; it never passes a price. The
    arrangement is rebuilt from the rows that own it, so a client
    naming "the $2 Option" cannot be charged a Pathway's $5, and a
    client naming the direct price cannot be charged the bundle's.

    Also the authorisation half of the identity: the arrangement must
    belong to the experience it was claimed for. Naming a real
    arrangement from another experience — or another Collective — is an
    :class:`ArrangementNotFound`, not a silently different price.

    Raises rather than returning ``None`` so a caller cannot fall
    through to a default price by forgetting to check. Availability is
    returned rather than raised: a caller that wants to refuse an
    unavailable arrangement reads ``available_for_new_purchase`` and
    chooses its own status code, which keeps HTTP out of this module.
    """
    found = arrangements_for(db, kind=kind, experience_id=experience_id)
    if found is None:
        raise ArrangementNotFound(
            f"No {kind} {experience_id!r} in this platform."
        )
    arrangement = found.by_id(arrangement_id)
    if arrangement is None:
        raise ArrangementNotFound(
            f"Arrangement {arrangement_id!r} is not available for "
            f"{kind} {experience_id!r}."
        )
    return arrangement


def with_reason(arrangement: Arrangement, reason: str) -> Arrangement:
    """An arrangement marked unavailable for a caller-supplied reason.

    For Stage 1B, when a *member-specific* refusal — already owns it, a
    plan in progress, banned — has to be reflected onto an arrangement
    the creator has configured perfectly well. Kept here so eligibility
    stays outside this module while still being expressible in its
    vocabulary.
    """
    return replace(
        arrangement, available_for_new_purchase=False,
        unavailable_reason=reason,
    )


__all__ = [
    "ALL_KINDS",
    "Arrangement",
    "ArrangementError",
    "ArrangementNotFound",
    "ExperienceArrangements",
    "IncludedExperience",
    "KIND_GATHERING",
    "KIND_OFFERING",
    "KIND_PATHWAY",
    "KIND_SERIES",
    "REASON_EXPERIENCE_UNAVAILABLE",
    "REASON_INSTALMENTS_NOT_ENABLED",
    "REASON_OPTION_ARCHIVED",
    "REASON_OPTION_DRAFT",
    "REASON_PRICE_INVALID",
    "REASON_PRICE_NOT_SET",
    "REASON_SCHEDULE_DRAFT",
    "REASON_SCHEDULE_INVALID",
    "REASON_SCHEDULE_UNSUPPORTED",
    "REASON_UNSUPPORTED_INCLUSION",
    "SCHEDULE_DIRECT",
    "SOURCE_DIRECT",
    "SOURCE_PAYMENT_OPTION",
    "UnknownExperienceKind",
    "arrangements_for",
    "direct_arrangement_id",
    "option_arrangement_id",
    "resolve_arrangement",
    "with_reason",
]
