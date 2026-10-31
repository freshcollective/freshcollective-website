"""The metrics themselves.

Two families here, and both exist to correct something specific.

**Financial.** Each money metric names its own event date, because one
basis for everything is what produced the inconsistency this release
fixes. A sale is attributed to when it settled, a refund to when the
money went back, a payout to when it was marked paid. The arithmetic is
the payment system's — gross, platform fee, creator net, the three
refund-reversal columns — and is read, never recomputed. Fresh
Collective's revenue stays separate from the volume it processes on
creators' behalf, and creator *earnings* stay separate from what has
actually been *paid out*.

**Membership.** ``/platform/overview`` computes "members" as
``total_users − admins − creators``, which is users whose role is
``user`` — so a creator who joins somebody else's Collective is never
counted as a member, and a registered account that joined nothing is.
The metrics below count memberships, and keep three different questions
apart: how many people are registered, how many people are members, and
how many memberships exist.

Settlement provenance
---------------------
``payment_transactions.settled_at`` only exists for payments that
settled after BI-1. Older rows are NULL, deliberately — no estimate was
written. The sale metrics therefore fall back to ``created_at`` for those
rows and report a ``settlement_basis`` of ``observed``, ``approximate``
or ``mixed`` on the result, so a window spanning the boundary says so
instead of blending two kinds of knowledge silently.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.periods import completed_reporting_date
from app.models.payment import PaymentTransaction, PayoutStatus
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.models.user import User, UserRole
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    Metric,
    MetricValue,
    Unit,
    Window,
)
from app.reporting.classification import ALL_CLASSES, UNCLASSIFIED
from app.reporting.dates import settlement_date
from app.reporting.eligibility import (
    creator_plan_filters,
    member_purchase_filters,
    payout_obligation_filters,
)
from app.reporting.population import (
    ALL,
    DIMENSION as POPULATION_DIMENSION,
    Population,
    unclassified_account_count,
)
from app.reporting.scope import Access, ReportScope, platform_scope

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

# Which rows a money metric may see comes from
# ``app.reporting.eligibility`` and is deliberately not redeclared here.
# A second copy of the member transaction type set is what let EMBODY's
# purchases fall out of every revenue metric while still counting towards
# outstanding payouts; see that module's docstring.


#: The canonical financial date, shared with the admin reporting helpers
#: so there cannot be two answers for the same payment. See
#: ``app.reporting.dates`` for why each basis is what it is.
_settlement_date_column = settlement_date


def _platform_mode() -> str:
    """The Stripe mode this deployment is running in.

    Read at query time rather than captured at import, so a test that
    swaps the configured keys is reflected rather than ignored.
    """
    from app.core.config import settings

    return settings.stripe_mode


def _member_txn_query(
    db: Session, scope: ReportScope, population: Population = ALL,
):
    """Settled member purchases, the basis of every revenue metric."""
    q = db.query(PaymentTransaction).filter(
        *member_purchase_filters(_platform_mode())
    )
    return _apply_population(_apply_scope(q, scope), population)


def _payout_query(
    db: Session, scope: ReportScope, population: Population = ALL,
):
    """Rows that can carry a creator payout, paid or still owed.

    Shared by the paid and outstanding figures so the two cannot disagree
    about who is in scope — one is the other's complement, and a row
    that leaves one total must arrive in the other.

    The mode comes from the running deployment rather than a parameter,
    matching ``/admin/commerce/transactions``, so a caretaker is never
    shown sandbox rows as a liability.
    """
    q = db.query(PaymentTransaction).filter(
        *payout_obligation_filters(_platform_mode())
    )
    return _apply_population(_apply_scope(q, scope), population)


def _apply_population(q, population: Population):
    """Narrow a payment query to a reporting-class population.

    Two separate conditions, because a Collective's class and an
    account's class are independent questions — a test account buying
    from a production Collective must leave a production figure, and the
    row is still in the ledger.

    Both are written to be safe against NULL. ``payer_user_id`` and
    ``space_id`` are ``ON DELETE SET NULL``, so a purchase whose buyer or
    Collective was later deleted carries a NULL there. A bare ``NOT IN``
    evaluates to NULL for such a row and would drop it — silently
    removing a real payment from a production total because an account
    was closed. The payer condition therefore keeps NULLs explicitly.

    A NULL ``space_id`` is treated the other way, and deliberately: a
    population defined by Collective class cannot include a row that
    belongs to no Collective. Those rows are counted and reported rather
    than vanishing — see ``_population_qualifiers``.
    """
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.filter(PaymentTransaction.space_id.in_(spaces))
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(
            or_(
                PaymentTransaction.payer_user_id.is_(None),
                PaymentTransaction.payer_user_id.notin_(excluded),
            )
        )
    return q


def _population_qualifiers(
    db: Session, scope: ReportScope, window: Window, population: Population,
) -> dict:
    """The population's own disclosure, beside any value computed under it.

    Carries three things a reader needs and cannot infer: which
    population this is, how many settled member purchases it set aside,
    and — for the production view — how many of the accounts it *did*
    count have no reporting class yet. That last figure is the
    provisional half of the production rule, kept visible at the point
    the number is read rather than explained once in a document.
    """
    quals = population.qualifiers()
    if population.is_all:
        return quals

    unfiltered = _window(
        _member_txn_query(db, scope), _settlement_date_column(), window,
    )
    total = unfiltered.with_entities(func.count(PaymentTransaction.id)).scalar() or 0
    kept = (
        _apply_population(unfiltered, population)
        .with_entities(func.count(PaymentTransaction.id))
        .scalar()
        or 0
    )
    quals["rows_in_population"] = int(kept)
    quals["rows_outside_population"] = int(total) - int(kept)
    if total and not kept:
        quals["population_empty_note"] = (
            "No settled member purchases fall inside this population for "
            "this period. The money is still in the complete ledger — "
            "switch to All activity to see it."
        )

    if population.narrows_accounts:
        no_space = (
            unfiltered.filter(PaymentTransaction.space_id.is_(None))
            .with_entities(func.count(PaymentTransaction.id))
            .scalar()
            or 0
        )
        if no_space:
            quals["rows_without_collective"] = int(no_space)
            quals["rows_without_collective_note"] = (
                "Excluded because a population defined by Collective class "
                "cannot place a payment that belongs to no Collective. "
                "Present in the complete ledger."
            )
    return quals


def _apply_scope(q, scope: ReportScope):
    """Restrict a payment query to the Collectives a scope may see."""
    allowed = scope.space_filter
    if allowed is None:
        return q
    if not allowed:
        # Manages nothing, so the honest answer is zero rather than
        # everything — which is what an unfiltered query would return.
        return q.filter(False)
    return q.filter(PaymentTransaction.space_id.in_(allowed))


def _window(q, column, window: Window):
    if window.starts_at is not None:
        q = q.filter(column >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(column < window.ends_at)
    return q


def _settlement_basis(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> dict:
    """How much of this window's money has an observed settlement date."""
    q = _window(
        _member_txn_query(db, scope, population), _settlement_date_column(),
        window,
    )
    observed, approximate = (
        q.with_entities(
            func.count(PaymentTransaction.settled_at),
            func.count(PaymentTransaction.id) - func.count(PaymentTransaction.settled_at),
        ).one()
    )
    observed, approximate = int(observed or 0), int(approximate or 0)
    if observed and approximate:
        basis = "mixed"
    elif approximate:
        basis = "approximate"
    else:
        basis = "observed"
    return {
        "settlement_basis": basis,
        "observed_rows": observed,
        "approximated_rows": approximate,
        **(
            {
                "approximation_note": (
                    "Payments that settled before business-event recording "
                    "began have no observed settlement date and are "
                    "attributed by their creation date."
                )
            }
            if approximate
            else {}
        ),
    }


def _money(key: str, expr, *, basis_note: bool = True):
    """A summed money metric over the settlement date."""

    def compute(
        db: Session, scope: ReportScope, window: Window,
        population: Population = ALL,
    ) -> MetricValue:
        q = _window(
            _member_txn_query(db, scope, population),
            _settlement_date_column(), window,
        )
        total = q.with_entities(func.coalesce(func.sum(expr), 0)).scalar() or 0
        quals = (
            _settlement_basis(db, scope, window, population)
            if basis_note else {}
        )
        quals.update(_population_qualifiers(db, scope, window, population))
        return MetricValue(key=key, value=int(total), qualifiers=quals)

    return compute


# ---------------------------------------------------------------------------
# Financial — volume, which is not revenue
# ---------------------------------------------------------------------------

REGISTRY.add(Metric(
    key="gross_collective_sales_cents",
    display_name="Gross Collective sales",
    definition=(
        "Everything members paid for creator products, Gatherings, Pathways "
        "and Offerings, before any deduction. This is transaction volume "
        "processed on creators' behalf — it is NOT Fresh Collective revenue, "
        "and most of it belongs to creators."
    ),
    source_of_truth="payment_transactions.gross_amount_cents",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "Attributed by observed settlement date where available; payments "
        "predating business-event recording fall back to their creation "
        "date. The result reports which basis applied."
    ),
    dimensions=("space_id", "creator_user_id", "stripe_mode", POPULATION_DIMENSION),
    compute=_money("gross_collective_sales_cents", PaymentTransaction.gross_amount_cents),
))

REGISTRY.add(Metric(
    key="platform_fee_revenue_cents",
    display_name="Platform fee revenue",
    definition=(
        "Fresh Collective's share of member purchases, net of fees reversed "
        "by refunds. One of the two streams that make up Fresh Collective's "
        "own revenue."
    ),
    source_of_truth=(
        "payment_transactions.platform_fee_cents − refunded_platform_fee_cents"
    ),
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Refund reversals are netted against the original sale's period "
        "rather than the refund's. Use the refunds metric for refund-period "
        "reporting."
    ),
    dimensions=("space_id", "creator_user_id", "stripe_mode", POPULATION_DIMENSION),
    compute=_money(
        "platform_fee_revenue_cents",
        PaymentTransaction.platform_fee_cents
        - func.coalesce(PaymentTransaction.refunded_platform_fee_cents, 0),
    ),
))

REGISTRY.add(Metric(
    key="creator_earnings_cents",
    display_name="Creator earnings",
    definition=(
        "What creators have earned from member purchases, net of refunds. An "
        "obligation Fresh Collective owes them — distinct from what has "
        "actually been paid out."
    ),
    source_of_truth=(
        "payment_transactions.net_creator_amount_cents − "
        "refunded_creator_amount_cents"
    ),
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations="Earned, not paid. See 'Paid out' for cash actually transferred.",
    dimensions=("space_id", "creator_user_id", "stripe_mode", POPULATION_DIMENSION),
    compute=_money(
        "creator_earnings_cents",
        func.coalesce(PaymentTransaction.net_creator_amount_cents, 0)
        - func.coalesce(PaymentTransaction.refunded_creator_amount_cents, 0),
    ),
))


def _processing_costs(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Stripe's fee, which Fresh Collective absorbs.

    ``processing_fee_cents`` is NULL until the reconciliation cron reads
    the real figure from Stripe — it is never estimated. Those rows are
    excluded and counted, so a cost total is never quietly understated.
    """
    q = _window(
        _member_txn_query(db, scope, population), _settlement_date_column(),
        window,
    )
    total, unknown = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.processing_fee_cents), 0),
        func.count(PaymentTransaction.id)
        - func.count(PaymentTransaction.processing_fee_cents),
    ).one()
    quals = _settlement_basis(db, scope, window, population)
    quals.update(_population_qualifiers(db, scope, window, population))
    quals["rows_without_a_known_fee"] = int(unknown or 0)
    if unknown:
        quals["fee_note"] = (
            "Stripe has not yet reported a fee for these payments. They are "
            "excluded rather than estimated, so this total is a lower bound."
        )
    return MetricValue(
        key="processing_costs_cents", value=int(total or 0), qualifiers=quals,
    )


REGISTRY.add(Metric(
    key="processing_costs_cents",
    display_name="Processing costs",
    definition=(
        "Stripe's processing fees, which Fresh Collective absorbs rather than "
        "passing on. A cost of sale, not a deduction from creator earnings."
    ),
    source_of_truth="payment_transactions.processing_fee_cents",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Fees Stripe has not yet reported are NULL and excluded. The result "
        "reports how many rows that affected."
    ),
    dimensions=("space_id", "creator_user_id", "stripe_mode", POPULATION_DIMENSION),
    compute=_processing_costs,
))


def _subscription_revenue(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creator plan fees paid to Fresh Collective.

    Platform-only and never scoped to a creator: a creator's own plan fee
    is Fresh Collective's revenue, not theirs, and showing it inside
    their earnings reporting would misstate both.
    """
    q = db.query(PaymentTransaction).filter(
        *creator_plan_filters(_platform_mode()),
    )
    # The account dimension only, and this is the one money metric where
    # that is the whole story. A creator's plan fee buys their *account*
    # a plan, not a Collective — somebody running a production Collective
    # and a demonstration one pays once, and there is no honest way to
    # attribute that payment to one of them. Narrowing it by Collective
    # class would therefore either double-count the fee or drop it
    # entirely depending on which Collective was consulted.
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(
            or_(
                PaymentTransaction.payer_user_id.is_(None),
                PaymentTransaction.payer_user_id.notin_(excluded),
            )
        )
    q = _window(q, _settlement_date_column(), window)
    total = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.gross_amount_cents), 0)
    ).scalar() or 0
    quals = population.qualifiers()
    if not population.is_all:
        quals["population_basis"] = (
            "Narrowed by the paying creator's account class only. A plan fee "
            "belongs to an account rather than to one Collective, so a "
            "Collective-class filter does not apply to it."
        )
    return MetricValue(
        key="subscription_revenue_cents", value=int(total), qualifiers=quals,
    )


REGISTRY.add(Metric(
    key="subscription_revenue_cents",
    display_name="Creator subscription revenue",
    definition=(
        "Fees creators pay Fresh Collective for their platform plans. The "
        "second of the two streams that make up Fresh Collective's revenue."
    ),
    source_of_truth="payment_transactions where type = creator_subscription_payment",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Attributed by observed settlement date where available; plan "
        "payments predating business-event recording fall back to their "
        "creation date."
    ),
    dimensions=(POPULATION_DIMENSION,),
    compute=_subscription_revenue,
))


def _refunds(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Money returned, attributed to the refund date.

    Deliberately not netted into the sale's period: a closed month's
    revenue should not change because somebody was refunded in the next
    one.
    """
    # Member purchases only. Without the type filter a refunded *creator
    # plan fee* — Fresh Collective's own revenue going back to a creator —
    # was reported as money returned to a member, on a page whose whole
    # organising idea is keeping those two apart.
    q = db.query(PaymentTransaction).filter(
        *member_purchase_filters(_platform_mode()),
        PaymentTransaction.refunded_amount_cents > 0,
        PaymentTransaction.last_refunded_at.isnot(None),
    )
    q = _apply_population(_apply_scope(q, scope), population)
    q = _window(q, PaymentTransaction.last_refunded_at, window)
    total, rows = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.refunded_amount_cents), 0),
        func.count(PaymentTransaction.id),
    ).one()
    return MetricValue(
        key="refunds_cents",
        value=int(total or 0),
        qualifiers={
            **population.qualifiers(),
            "transactions_refunded": int(rows or 0),
            "note": (
                "Only the most recent refund date is stored per transaction, "
                "so a payment refunded twice in different periods is "
                "attributed wholly to the later one. Business events record "
                "each refund separately from BI-1 onwards."
            ),
        },
    )


REGISTRY.add(Metric(
    key="refunds_cents",
    display_name="Refunds",
    definition=(
        "Money returned to members, attributed to the period the refund "
        "happened in rather than the period of the original sale."
    ),
    source_of_truth="payment_transactions.refunded_amount_cents",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.refunded,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "Only the latest refund date per transaction is stored, so multiple "
        "refunds in different periods collapse into the later one."
    ),
    dimensions=("space_id", "creator_user_id", POPULATION_DIMENSION),
    compute=_refunds,
))


def _paid_out(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Cash actually transferred, on the date it was marked paid.

    Only ever written by a recorded payout batch. A Stripe payout into
    Fresh Collective's own bank account is a different event and does not
    appear here — nor should it, since money reaching the platform is not
    the same act as money reaching a creator.
    """
    q = _payout_query(db, scope, population).filter(
        PaymentTransaction.payout_status == PayoutStatus.paid.value,
        PaymentTransaction.payout_marked_at.isnot(None),
    )
    q = _window(q, PaymentTransaction.payout_marked_at, window)
    total = q.with_entities(
        func.coalesce(
            func.sum(
                func.coalesce(PaymentTransaction.net_creator_amount_cents, 0)
                - func.coalesce(PaymentTransaction.refunded_creator_amount_cents, 0)
            ),
            0,
        )
    ).scalar() or 0
    return MetricValue(key="paid_out_cents", value=int(total))


REGISTRY.add(Metric(
    key="paid_out_cents",
    display_name="Paid out",
    definition=(
        "Creator earnings that have actually been transferred, dated by when "
        "the payout was recorded. A cash movement — not the same question as "
        "what creators have earned."
    ),
    source_of_truth=(
        "payment_transactions where payout_status = paid, written only by a "
        "recorded payout batch"
    ),
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payout_marked,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations=(
        "Recorded payout batches only. A Stripe payout into Fresh "
        "Collective's own bank account is a different event and is not "
        "counted here, and Connect transfers are tracked separately."
    ),
    dimensions=("space_id", "creator_user_id", POPULATION_DIMENSION),
    compute=_paid_out,
))


def _outstanding_payouts(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """What is still owed, as at a moment.

    The complement of ``paid_out_cents`` over the same population, which
    is why both run through ``_payout_query``. Before that was true this
    figure counted abandoned checkouts, sandbox rows and platform-owned
    Collectives, and reported a liability larger than the earnings it was
    supposedly a share of.

    Connect rows never appear: their share reaches the creator through
    Stripe and they are created ``payout_status='not_applicable'`` so
    that Fresh Collective's manual payout queue cannot claim money Stripe
    has already sent.

    Two modes, because a liability has a date
    ----------------------------------------
    With no window — the live dashboard figure — the answer is read
    straight off ``payout_status``, which is what the column is for.

    With a window, the balance is reconstructed as at ``ends_at``, and
    that is not the same query: a row marked paid last week was *owed*
    the week before, so a historical snapshot has to consider rows that
    are no longer pending and decide by date. Without this the nightly
    job stored today's balance under every reporting date and the trend
    line was flat at the current value — a liability dated before the
    sale that created it.

    The ownership split is reporting only. It does not change the total
    and settles nothing — see ``_ownership_split``.
    """
    as_at = _as_at(window)
    retained = func.coalesce(
        PaymentTransaction.net_creator_amount_cents, 0
    ) - func.coalesce(
        case(
            (
                # A refund reverses the obligation from the day it
                # happened, not retroactively to the sale.
                _refund_known_by(as_at),
                PaymentTransaction.refunded_creator_amount_cents,
            ),
            else_=0,
        ),
        0,
    )

    q = _payout_query(db, scope, population)
    if as_at is None:
        q = q.filter(
            PaymentTransaction.payout_status == PayoutStatus.pending.value,
        )
        basis = "current payout status"
        caveat = None
    else:
        q = q.filter(
            # Settled by then, so the money existed to be owed.
            _settlement_date_column() < as_at,
            # Not yet paid by then. A row with no payout date has never
            # been paid, whatever its status says today.
            PaymentTransaction.payout_status.in_(
                [PayoutStatus.pending.value, PayoutStatus.paid.value]
            ),
            or_(
                PaymentTransaction.payout_marked_at.is_(None),
                PaymentTransaction.payout_marked_at >= as_at,
            ),
        )
        basis = "reconstructed as at the end of the period"
        caveat = (
            "Rows later put on hold or cancelled carry no transition date, "
            "so a historical balance treats them by their current status."
        )

    total = q.with_entities(func.coalesce(func.sum(retained), 0)).scalar() or 0
    quals = _ownership_split(q, retained)
    quals["as_at"] = _as_at_label(db, window)
    quals["basis"] = basis
    if caveat:
        quals["caveat"] = caveat
    return MetricValue(
        key="outstanding_payouts_cents",
        value=int(total),
        qualifiers=quals,
    )


def _refund_known_by(as_at):
    """Whether a refund had happened by ``as_at``.

    ``None`` means now, where every recorded refund counts. Only the
    latest refund date per transaction is stored, so a row refunded twice
    across the boundary is treated by the later date — stated in the
    metric's limitations rather than papered over.
    """
    if as_at is None:
        return PaymentTransaction.refunded_creator_amount_cents.isnot(None)
    return and_(
        PaymentTransaction.last_refunded_at.isnot(None),
        PaymentTransaction.last_refunded_at < as_at,
    )


def _ownership_split(q, retained) -> dict:
    """Split an obligation by who is actually owed it.

    Fresh Collective's owner is also the creator of some Collectives, so
    part of this liability is the platform owing itself. Reporting that
    beside a third-party obligation without distinguishing them overstates
    what the business owes other people — the whole of the $1,560 found in
    the October reconciliation turned out to be of this kind.

    Two separate questions are answered, and they are deliberately not
    merged:

    **Who holds it.** A Collective counts as founder-operated when its
    creator holds the ``admin`` role. Derived from the data rather than
    naming a person, so it stays true as the platform grows.

    **What kind of activity it is.** ``spaces.reporting_class`` —
    ``production``, ``internal_operations`` or ``demonstration``. It is
    NULL until an operator assigns one and nothing is ever inferred from
    a Collective's name, so unclassified Collectives are reported as
    ``unclassified`` rather than quietly folded into production. A
    demonstration Collective's live Stripe charge is still a real
    financial movement and is never dropped from the total.

    Reporting only. Nothing here marks anything settled, changes a payout
    status or reclassifies a row. Whether founder earnings *should* be
    treated as settled is an open accounting decision.
    """
    from app.reporting.creators import founder_operated_space_ids

    founder_space_ids = founder_operated_space_ids()

    def _sum_where(condition):
        return func.coalesce(
            func.sum(case((condition, retained), else_=0)), 0
        )

    is_founder = PaymentTransaction.space_id.in_(founder_space_ids)
    # The vocabulary comes from ``app.reporting.classification``; a
    # literal tuple here is how the member-type set drifted.
    classified = {
        name: select(Space.id).where(Space.reporting_class == name)
        for name in ALL_CLASSES
    }
    unclassified = select(Space.id).where(Space.reporting_class.is_(None))

    external, founder, *by_class = q.with_entities(
        _sum_where(~is_founder),
        _sum_where(is_founder),
        *(
            _sum_where(PaymentTransaction.space_id.in_(ids))
            for ids in (*classified.values(), unclassified)
        ),
    ).one()

    names = (*classified.keys(), UNCLASSIFIED)
    return {
        "owed_to_external_creators_cents": int(external or 0),
        "owed_to_founder_operated_collectives_cents": int(founder or 0),
        "by_reporting_class_cents": {
            name: int(amount or 0) for name, amount in zip(names, by_class)
        },
        "ownership_note": (
            "Founder-operated means the Collective's creator is a platform "
            "administrator. Both amounts are earned and unpaid as recorded; "
            "neither has been treated as settled."
        ),
        "classification_note": (
            "Reporting class is assigned by an operator and is never "
            "inferred. Unclassified Collectives are counted as such rather "
            "than assumed to be production, and a demonstration "
            "Collective's live charge is still a real financial movement."
        ),
    }


REGISTRY.add(Metric(
    key="outstanding_payouts_cents",
    display_name="Outstanding payouts",
    definition=(
        "Creator earnings awaiting transfer. A liability at this moment, so "
        "a reporting period does not narrow it."
    ),
    source_of_truth=(
        "payment_transactions where payout_status = pending, over settled "
        "member purchases with a creator, in the platform's Stripe mode; "
        "a past date is reconstructed from settlement and payout dates"
    ),
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations=(
        "Stripe Connect earnings are not here — those reach the creator "
        "through Stripe and are tracked by their transfer status. Part of "
        "this total may be owed to Collectives the platform owner operates; "
        "the breakdown beside it separates the two. A past day's balance is "
        "reconstructed from settlement and payout dates, so rows later put "
        "on hold or cancelled are treated by their current status."
    ),
    dimensions=("space_id", "creator_user_id", POPULATION_DIMENSION),
    compute=_outstanding_payouts,
))


def _contribution(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """What Fresh Collective keeps after directly attributable costs.

    **Not net profit.** It excludes every operating expense — hosting,
    software, the founder's time — so calling it profit would overstate
    the health of the business. The name says what it is.
    """
    # Composed through ``evaluate`` rather than by calling the compute
    # functions, so each component re-checks entitlement and the
    # population guard. Passing the population down is what keeps the
    # arithmetic internally consistent: a production contribution must
    # be production fees plus production subscriptions minus production
    # costs, never a mix of filtered and unfiltered terms.
    fee = REGISTRY.get("platform_fee_revenue_cents").evaluate(
        db, scope, window, population)
    subs = REGISTRY.get("subscription_revenue_cents").evaluate(
        db, scope, window, population)
    costs = REGISTRY.get("processing_costs_cents").evaluate(
        db, scope, window, population)
    value = int(fee.value or 0) + int(subs.value or 0) - int(costs.value or 0)
    return MetricValue(
        key="contribution_after_processing_cents",
        value=value,
        qualifiers={
            **population.qualifiers(),
            "components": {
                "platform_fee_revenue_cents": fee.value,
                "subscription_revenue_cents": subs.value,
                "processing_costs_cents": costs.value,
            },
            "not_net_profit": (
                "Excludes all operating expenses. This is contribution after "
                "directly attributable processing costs, not profit."
            ),
            **{k: v for k, v in costs.qualifiers.items() if k.startswith("rows_")},
        },
    )


REGISTRY.add(Metric(
    key="contribution_after_processing_cents",
    display_name="Contribution after processing costs",
    definition=(
        "Fresh Collective revenue (platform fees + creator subscriptions) "
        "less Stripe processing costs. NOT net profit — no operating "
        "expenses are included."
    ),
    source_of_truth="derived from platform fee, subscription revenue and processing costs",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payment_settled,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Must never be labelled profit. Operating expenses are outside the "
        "platform entirely."
    ),
    dimensions=(POPULATION_DIMENSION,),
    compute=_contribution,
))


# ---------------------------------------------------------------------------
# People — three different questions, kept apart
# ---------------------------------------------------------------------------

def _as_at(window: Window):
    """The moment a snapshot is measured at, or None for "now".

    A snapshot answers "how many, as at when" — so a period narrows the
    *measurement date*, not which rows are counted. ``ends_at`` is
    exclusive, so the state as at the end of a window is the state just
    before it closes.

    None means **now**, and a "now" snapshot must not filter by date at
    all. ``users.created_at`` is ``timestamp(3)`` — millisecond
    precision — while ``now()`` carries microseconds, so the stored
    value rounds and a row created in the same transaction can read as
    up to half a millisecond in the *future*. Filtering
    ``created_at <= now()`` then excludes it, and ``registered_users``
    reported zero. Every row that exists, exists now; no predicate is
    needed to say so.
    """
    return window.ends_at


def _as_at_label(db: Session, window: Window) -> str:
    """How the as-at moment is reported back. "now" says so."""
    at = _as_at(window)
    return at.isoformat() if at is not None else "now"


#: Reconstructing membership state at a past date leans on ``removed_at``,
#: which rejoining cleared before BI-1. A member who left in March and
#: returned in June has no departure on record, so a March snapshot counts
#: them as present. Snapshots on or after the business-event activation
#: floor are exact; earlier ones overstate membership and understate
#: churn, and say so in their qualifiers.
_SNAPSHOT_CAVEAT = (
    "Reconstructed from current membership rows. Departures were "
    "overwritten by rejoining before business-event recording began, so a "
    "snapshot dated before then may overstate membership."
)


def _snapshot_qualifiers(db: Session, window: Window) -> dict:
    from app.services.business_event_reconciliation import activation_floor

    as_at = _as_at(window)
    floor = activation_floor(db)
    # None as-at means now, which is always on or after the floor.
    exact = floor is not None and (as_at is None or as_at >= floor)
    return {
        "as_at": _as_at_label(db, window),
        "provenance": "observed" if exact else "reconstructed",
        **({} if exact else {"caveat": _SNAPSHOT_CAVEAT}),
    }


def _membership_population_qualifiers(
    db: Session, window: Window, population: Population, membership_q,
) -> dict:
    """Snapshot provenance, plus what the population filter did.

    The second half is the part worth having. Under the production view
    an account counts unless it is explicitly test or demonstration, so
    the figure includes everybody nobody has classified yet. That is a
    provisional inclusion, and it is reported as a number rather than
    described in a note: ``unclassified_accounts`` says how many of the
    people counted here have no reporting class, so the reader can see
    how much of the figure is still awaiting review.
    """
    quals = _snapshot_qualifiers(db, window)
    quals.update(population.qualifiers())
    if population.narrows_accounts:
        counted = membership_q.with_entities(
            func.distinct(SpaceMembership.user_id)
        ).subquery()
        unclassified = unclassified_account_count(
            db, select(counted.c[0])
        )
        quals["unclassified_accounts"] = unclassified
        if unclassified:
            quals["unclassified_accounts_note"] = (
                f"{unclassified} of the accounts counted here have no "
                "reporting class yet and are included provisionally. "
                "Classifying them can only reduce this figure, never "
                "raise it."
            )
    return quals


def _registered_users(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Accounts in existence as at the measurement date.

    A snapshot, not a flow: asking for "this month" asks how many
    accounts existed at the end of this month, not how many signed up
    during it. ``accounts_registered`` is the flow.
    """
    as_at = _as_at(window)
    q = db.query(func.count(User.id))
    if as_at is not None:
        q = q.filter(User.created_at <= as_at)
    # An account count has no Collective dimension, so only the account
    # half of the population applies. Narrowing it by Collective class
    # would silently become "accounts that belong to a production
    # Collective", which is a membership question, not this one.
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(User.id.notin_(excluded))
    n = q.scalar() or 0
    quals = {"as_at": _as_at_label(db, window), **population.qualifiers()}
    if not population.is_all:
        quals["population_basis"] = (
            "Narrowed by account class only — an account does not belong "
            "to a Collective, so a Collective-class filter does not apply."
        )
    return MetricValue(key="registered_users", value=int(n), qualifiers=quals)


REGISTRY.add(Metric(
    key="registered_users",
    display_name="Registered users",
    definition=(
        "People with a Fresh Collective account, counted once each, "
        "regardless of role or how many Collectives they have joined."
    ),
    source_of_truth="users.created_at, counted as-at",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.platform_only,
    availability=Availability.full,
    personal_data=True,
    dimensions=(POPULATION_DIMENSION,),
    compute=_registered_users,
))


def _registered_creators(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creator accounts in existence as at the measurement date."""
    as_at = _as_at(window)
    q = db.query(func.count(User.id)).filter(User.role == "creator")
    if as_at is not None:
        q = q.filter(User.created_at <= as_at)
    # An account count has no Collective dimension, so only the account
    # half of the population applies. Narrowing it by Collective class
    # would silently become "accounts that belong to a production
    # Collective", which is a membership question, not this one.
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(User.id.notin_(excluded))
    n = q.scalar() or 0
    quals = {"as_at": _as_at_label(db, window), **population.qualifiers()}
    if not population.is_all:
        quals["population_basis"] = (
            "Narrowed by account class only — an account does not belong "
            "to a Collective, so a Collective-class filter does not apply."
        )
    return MetricValue(key="registered_creators", value=int(n), qualifiers=quals)


REGISTRY.add(Metric(
    key="registered_creators",
    display_name="Registered creators",
    definition="Accounts whose platform role is creator.",
    source_of_truth="users.role = 'creator', counted as-at",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.platform_only,
    availability=Availability.full,
    personal_data=True,
    dimensions=(POPULATION_DIMENSION,),
    compute=_registered_creators,
))


def _membership_query(
    db: Session, scope: ReportScope, *, as_at=None, population: Population = ALL,
):
    """Memberships active at a moment.

    With ``as_at`` this reconstructs state from ``joined_at`` and
    ``removed_at`` rather than reading ``status``, which only ever
    describes now. See ``_SNAPSHOT_CAVEAT`` for what that cannot see
    before BI-1.
    """
    if as_at is None:
        q = db.query(SpaceMembership).filter(
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
    else:
        q = db.query(SpaceMembership).filter(
            SpaceMembership.joined_at <= as_at,
            # A row marked removed with no removal date is excluded from
            # every snapshot. We know the membership ended; we do not know
            # when, and counting it as present would be the wrong guess.
            # Legacy rows predating the removal-provenance migration look
            # like this.
            or_(
                SpaceMembership.status != SpaceMembershipStatus.removed,
                SpaceMembership.removed_at.isnot(None),
            ),
            or_(
                SpaceMembership.removed_at.is_(None),
                SpaceMembership.removed_at > as_at,
            ),
        )
    allowed = scope.space_filter
    if allowed is not None:
        if not allowed:
            return q.filter(False)
        q = q.filter(SpaceMembership.space_id.in_(allowed))
    # The two independent dimensions. Both columns are NOT NULL here, so
    # a plain IN / NOT IN is safe — unlike the payment equivalent, where
    # a deleted account leaves a NULL that must not drop the row.
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.filter(SpaceMembership.space_id.in_(spaces))
    excluded = population.excluded_account_select()
    if excluded is not None:
        # The case this exists for: a test account holding a membership
        # in a genuine production Collective. The Collective is in the
        # population and the person is not a member of anything real, so
        # the space filter alone would count them.
        q = q.filter(SpaceMembership.user_id.notin_(excluded))
    return q


def _unique_members(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Distinct people holding a membership, as at the measurement date.

    Two corrections in one metric. ``/platform/overview`` derived
    "members" from roles, so a creator who joined another Collective was
    never counted and an account that joined nothing was. And this is a
    **snapshot**: asking for "this month" asks how many members there
    were at the end of this month, not how many joined during it —
    ``memberships_started`` is the flow. Each person counts once however
    many Collectives they belong to, which is what keeps a creator's
    multi-Collective overview from triple-counting a shared member.
    """
    q = _membership_query(db, scope, as_at=_as_at(window), population=population)
    n = (
        q.with_entities(func.count(func.distinct(SpaceMembership.user_id)))
        .scalar() or 0
    )
    return MetricValue(
        key="unique_members", value=int(n),
        qualifiers=_membership_population_qualifiers(db, window, population, q),
    )


REGISTRY.add(Metric(
    key="unique_members",
    display_name="Unique members",
    definition=(
        "Distinct people holding at least one active Collective membership. "
        "Somebody in three Collectives counts once."
    ),
    source_of_truth="space_memberships.joined_at / removed_at, reconstructed as-at",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations=(
        "Non-additive. A monthly figure must be recomputed over the month, "
        "never summed from daily figures."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    personal_data=True,
    compute=_unique_members,
))


def _total_memberships(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Memberships in force as at the measurement date. A snapshot."""
    q = _membership_query(db, scope, as_at=_as_at(window), population=population)
    n = q.with_entities(func.count(SpaceMembership.id)).scalar() or 0
    return MetricValue(
        key="total_memberships", value=int(n),
        qualifiers=_membership_population_qualifiers(db, window, population, q),
    )


def _memberships_started(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Memberships that began in the window. The flow beside the snapshot.

    Counts memberships rather than people, so it adds up across periods —
    which is exactly why it is a separate metric from ``unique_members``
    rather than the same one with a date filter.
    """
    q = db.query(SpaceMembership)
    allowed = scope.space_filter
    if allowed is not None:
        q = q.filter(False) if not allowed else q.filter(
            SpaceMembership.space_id.in_(allowed)
        )
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.filter(SpaceMembership.space_id.in_(spaces))
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(SpaceMembership.user_id.notin_(excluded))
    if window.starts_at is not None:
        q = q.filter(SpaceMembership.joined_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(SpaceMembership.joined_at < window.ends_at)
    n = q.with_entities(func.count(SpaceMembership.id)).scalar() or 0
    return MetricValue(
        key="memberships_started", value=int(n),
        qualifiers=population.qualifiers(),
    )


REGISTRY.add(Metric(
    key="total_memberships",
    display_name="Collective memberships",
    definition=(
        "Active memberships. Somebody in three Collectives contributes three. "
        "A different question from how many people are members."
    ),
    source_of_truth="space_memberships.joined_at / removed_at, reconstructed as-at",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "A snapshot — take the latest, never sum across periods. "
        "Reconstructed from membership rows, so a date before "
        "business-event recording may overstate membership."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    compute=_total_memberships,
))

REGISTRY.add(Metric(
    key="memberships_started",
    display_name="Memberships started",
    definition=(
        "Memberships that began during the period. Counts memberships, not "
        "people, so it adds up across periods — the flow beside the "
        "'Collective memberships' snapshot."
    ),
    source_of_truth="space_memberships.joined_at",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.membership_joined,
    access=Access.creator_visible,
    availability=Availability.full,
    dimensions=("space_id", POPULATION_DIMENSION),
    compute=_memberships_started,
))


def _overlap_counts(
    db: Session, scope: ReportScope, window: Window, population: Population,
) -> dict[str, int]:
    """How many Collectives each visible member belongs to, as at a date.

    Reconstructed from ``joined_at`` / ``removed_at``, the same basis
    ``unique_members`` uses — so the buckets below and the member count
    above them are derived from one set of rows and cannot disagree.
    Previously this family read ``status == 'active'`` and ignored the
    window entirely, which made every past date silently report today.

    Two populations are in play and they are not the same one:

    * the **cohort** — members the asking scope may be told about, which
      for a creator is the members of their own Collectives;
    * the **count** — how many Collectives each of those people belongs
      to, measured across the whole population rather than across the
      creator's own Collectives. "Does this member also belong
      elsewhere" is the question worth answering, and restricting the
      count to the creator's own would answer a different one.

    Within the *population*, though, not platform-wide: under the
    production view a person in one production Collective and one test
    Collective belongs to one production Collective, and reporting them
    as two would contradict the label on the chart.

    Every member lands in exactly one bucket, so the three sum to
    ``unique_members`` for the same date and population.
    """
    as_at = _as_at(window)
    counted = _membership_query(
        db, platform_scope(), as_at=as_at, population=population,
    )
    per_user = (
        counted.with_entities(
            SpaceMembership.user_id.label("uid"),
            func.count(func.distinct(SpaceMembership.space_id)).label("n"),
        )
        .group_by(SpaceMembership.user_id)
        .subquery()
    )

    q = db.query(per_user.c.n, func.count()).group_by(per_user.c.n)
    if scope.space_filter is not None:
        if not scope.space_filter:
            return {"one": 0, "two": 0, "three_plus": 0, "multi": 0}
        cohort = (
            _membership_query(db, scope, as_at=as_at, population=population)
            .with_entities(func.distinct(SpaceMembership.user_id))
            .subquery()
        )
        q = q.filter(per_user.c.uid.in_(select(cohort.c[0])))

    tally = {int(n): int(c) for n, c in q.all()}
    return {
        "one": tally.get(1, 0),
        "two": tally.get(2, 0),
        "three_plus": sum(c for n, c in tally.items() if n >= 3),
        "multi": sum(c for n, c in tally.items() if n >= 2),
    }


def _multi_collective_members(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """People belonging to more than one Collective, as at a date."""
    counts = _overlap_counts(db, scope, window, population)
    return MetricValue(
        key="multi_collective_members",
        value=counts["multi"],
        qualifiers={
            **_snapshot_qualifiers(db, window),
            **population.qualifiers(),
            "buckets": {
                "one": counts["one"],
                "two": counts["two"],
                "three_plus": counts["three_plus"],
            },
        },
    )


def _overlap_bucket(key: str, bucket: str):
    """One mutually exclusive overlap bucket."""

    def compute(
        db: Session, scope: ReportScope, window: Window,
        population: Population = ALL,
    ) -> MetricValue:
        counts = _overlap_counts(db, scope, window, population)
        return MetricValue(
            key=key,
            value=counts[bucket],
            qualifiers={
                **_snapshot_qualifiers(db, window),
                **population.qualifiers(),
                "mutually_exclusive": (
                    "Each member appears in exactly one of the three "
                    "buckets, so they sum to unique members for the same "
                    "date and population."
                ),
            },
        )

    return compute


_OVERLAP_BUCKETS = (
    (
        "members_in_one_collective", "one", "Members in one Collective",
        "People holding an active membership in exactly one Collective.",
    ),
    (
        "members_in_two_collectives", "two", "Members in two Collectives",
        "People holding active memberships in exactly two Collectives.",
    ),
    (
        "members_in_three_plus_collectives", "three_plus",
        "Members in three or more Collectives",
        "People holding active memberships in three or more Collectives.",
    ),
)

for _key, _bucket, _name, _definition in _OVERLAP_BUCKETS:
    REGISTRY.add(Metric(
        key=_key,
        display_name=_name,
        definition=_definition,
        source_of_truth=(
            "space_memberships.joined_at / removed_at, reconstructed as-at"
        ),
        grain=Grain.snapshot,
        # A snapshot, not a distinct count. The three buckets partition
        # the members of a single date, so the value for a week is the
        # latest day in it — never the sum, which would count a person
        # once per day they were a member.
        aggregation=Aggregation.snapshot,
        date_basis=DateBasis.none,
        access=Access.creator_visible,
        availability=Availability.partial,
        limitations=(
            "Reconstructed from membership rows rather than recorded at the "
            "time. A membership removed before removal dates were stored is "
            "invisible to this, so a date well before business-event "
            "recording began may place a member in too high a bucket. The "
            "three buckets always partition the same members, so they sum "
            "to unique members for that date."
        ),
        dimensions=("space_id", POPULATION_DIMENSION),
        personal_data=True,
        compute=_overlap_bucket(_key, _bucket),
    ))


REGISTRY.add(Metric(
    key="multi_collective_members",
    display_name="Members in more than one Collective",
    definition=(
        "People holding active memberships in two or more Collectives. For a "
        "creator, this counts their own members who also belong elsewhere — "
        "the count only, never which Collectives."
    ),
    source_of_truth=(
        "space_memberships.joined_at / removed_at, reconstructed as-at"
    ),
    grain=Grain.snapshot,
    # Was ``distinct_count``, which kept it out of the stored dailies
    # and so out of any trend line. It is a snapshot of one date — take
    # the latest in a week, never the sum — and on that footing it can
    # be stored and charted like the member count beside it.
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.partial,
    limitations=(
        "A snapshot — take the latest, never sum across periods. "
        "Reconstructed from membership rows, so a date before removal "
        "dates were stored may overstate overlap."
    ),
    dimensions=("space_id", POPULATION_DIMENSION),
    personal_data=True,
    compute=_multi_collective_members,
))


def _memberships_per_member(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    members = _unique_members(db, scope, window, population).value or 0
    memberships = _total_memberships(db, scope, window, population).value or 0
    if not members:
        return MetricValue(
            key="memberships_per_member",
            value=None,
            unavailable_reason="No members yet, so there is no average to report.",
        )
    return MetricValue(
        key="memberships_per_member",
        value=round(memberships / members, 2),
        qualifiers={
            "unique_members": members,
            "total_memberships": memberships,
            **population.qualifiers(),
        },
    )


REGISTRY.add(Metric(
    key="memberships_per_member",
    display_name="Memberships per member",
    definition=(
        "Active memberships divided by unique members — how many "
        "Collectives the average person belongs to."
    ),
    source_of_truth="derived from unique_members and total_memberships",
    grain=Grain.snapshot,
    aggregation=Aggregation.ratio,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
    # A rate, not a proportion. 1.83 memberships per person is not 183%
    # of anything, and reading it as a percentage was a real misreport.
    unit=Unit.rate,
    limitations="A ratio — recompute it, never average two periods' values.",
    dimensions=(POPULATION_DIMENSION,),
    compute=_memberships_per_member,
))


# ---------------------------------------------------------------------------
# Collectives
# ---------------------------------------------------------------------------

#: How many days after a reporting day an observation of it still counts.
#:
#: A Collective count can only be taken by looking, and looking tonight
#: tells you about tonight. Running the night after day D is the
#: conventional end-of-day observation and is treated as genuine. A
#: missed night means tomorrow's run is the first and only chance to
#: record D, so a short grace follows the nightly lookback — but a
#: rebuild of last March is refused outright, because there is nothing
#: there to observe any more.
OBSERVATION_GRACE_DAYS = 3


def _observation_quality(window: Window) -> tuple[str | None, str | None]:
    """``(provenance, unavailable_reason)`` for observing a day's state.

    ``provenance`` is ``observed`` when the window closes on the last
    completed reporting day — the night the nightly job is built around —
    and ``observed_late`` within the grace that lets a missed night be
    repaired. Beyond that there is no honest answer, so the reason is
    returned instead and no row is written.
    """
    as_at = _as_at(window)
    if as_at is None:
        # Live question, live answer.
        return "observed", None

    now = datetime.utcnow()
    if as_at > now:
        # A day that has not finished. The nightly job asking for today
        # lands here — its window closes at tomorrow's local midnight —
        # and there is genuinely nothing to observe yet.
        return None, (
            "This day has not finished yet, so there is no end-of-day count "
            "for it."
        )

    today = completed_reporting_date(now)
    # ``ends_at`` is exclusive, so the day being described ends the
    # instant before it.
    day = (as_at - timedelta(microseconds=1)).date()
    behind = (today - day).days

    if behind <= 0:
        # Either the last completed day, or a window that closes at this
        # moment — "this month so far", "this financial year". The
        # second is a live question and was being refused as an
        # unfinished day, which put "Not yet" on every Collective-status
        # card for the periods a reader actually looks at.
        return "observed", None
    if behind <= OBSERVATION_GRACE_DAYS:
        return "observed_late", None
    return None, (
        "Collective status is not kept as history, so a past day's count "
        "cannot be reconstructed — only observed at the time. This day "
        "predates the first observation."
    )


def _collectives(status: str | None, key: str):
    """A count of Collectives, as observed rather than reconstructed.

    ``spaces.status`` holds one value and no history. There is no
    ``archived_at``, and a creation date is not a publication date — so
    the only honest past figure is one that was written down at the time.
    Asked about a day it cannot have seen, this returns unavailable, and
    the daily series carries a gap the chart can show as a gap.
    """
    def compute(
        db: Session, scope: ReportScope, window: Window,
        population: Population = ALL,
    ) -> MetricValue:
        provenance, unavailable = _observation_quality(window)
        if unavailable is not None:
            return MetricValue(
                key=key,
                value=None,
                unavailable_reason=unavailable,
                qualifiers={"observation_only": True},
            )

        q = db.query(func.count(Space.id))
        if status is not None:
            q = q.filter(Space.status == status)
        spaces = population.space_id_select()
        if spaces is not None:
            q = q.filter(Space.id.in_(spaces))
        allowed = scope.space_filter
        if allowed is not None:
            if not allowed:
                return MetricValue(
                    key=key, value=0,
                    qualifiers={"provenance": provenance, "observation_only": True},
                )
            q = q.filter(Space.id.in_(allowed))
        return MetricValue(
            key=key,
            value=int(q.scalar() or 0),
            qualifiers={
                "provenance": provenance,
                "observation_only": True,
                "as_at": _as_at_label(db, window),
                **population.qualifiers(),
            },
        )

    return compute


for _status, _key, _name in (
    (None, "total_collectives", "Collectives"),
    ("active", "active_collectives", "Active Collectives"),
    ("draft", "draft_collectives", "Draft Collectives"),
    ("archived", "archived_collectives", "Archived Collectives"),
):
    REGISTRY.add(Metric(
        key=_key,
        display_name=_name,
        definition=(
            f"Collectives with status {_status!r}."
            if _status
            else "All Collectives, whatever their status."
        ),
        source_of_truth="spaces.status, observed at the time",
        grain=Grain.snapshot,
        aggregation=Aggregation.snapshot,
        date_basis=DateBasis.none,
        access=Access.creator_visible,
        availability=Availability.from_instrumentation,
        observation_only=True,
        limitations=(
            "Observed, not reconstructed. A Collective's status is stored as "
            "one value with no history behind it, so this count is only "
            "known for days on which it was recorded. A trend begins when "
            "nightly recording began, and earlier days are a gap rather "
            "than a zero."
        ),
        dimensions=("space_id", POPULATION_DIMENSION),
        compute=_collectives(_status, _key),
    ))
