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

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

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
from app.reporting.scope import Access, ReportScope

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


def _member_txn_query(db: Session, scope: ReportScope):
    """Settled member purchases, the basis of every revenue metric."""
    q = db.query(PaymentTransaction).filter(
        *member_purchase_filters(_platform_mode())
    )
    return _apply_scope(q, scope)


def _payout_query(db: Session, scope: ReportScope):
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
    return _apply_scope(q, scope)


def _apply_scope(q, scope: ReportScope):
    """Restrict a payment query to the Collectives a scope may see."""
    if scope.is_platform:
        return q
    if not scope.space_ids:
        # Manages nothing, so the honest answer is zero rather than
        # everything — which is what an unfiltered query would return.
        return q.filter(False)
    return q.filter(PaymentTransaction.space_id.in_(scope.space_ids))


def _window(q, column, window: Window):
    if window.starts_at is not None:
        q = q.filter(column >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(column < window.ends_at)
    return q


def _settlement_basis(db: Session, scope: ReportScope, window: Window) -> dict:
    """How much of this window's money has an observed settlement date."""
    q = _window(_member_txn_query(db, scope), _settlement_date_column(), window)
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

    def compute(db: Session, scope: ReportScope, window: Window) -> MetricValue:
        q = _window(_member_txn_query(db, scope), _settlement_date_column(), window)
        total = q.with_entities(func.coalesce(func.sum(expr), 0)).scalar() or 0
        quals = _settlement_basis(db, scope, window) if basis_note else {}
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
    dimensions=("space_id", "creator_user_id", "stripe_mode"),
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
    dimensions=("space_id", "creator_user_id", "stripe_mode"),
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
    dimensions=("space_id", "creator_user_id", "stripe_mode"),
    compute=_money(
        "creator_earnings_cents",
        func.coalesce(PaymentTransaction.net_creator_amount_cents, 0)
        - func.coalesce(PaymentTransaction.refunded_creator_amount_cents, 0),
    ),
))


def _processing_costs(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Stripe's fee, which Fresh Collective absorbs.

    ``processing_fee_cents`` is NULL until the reconciliation cron reads
    the real figure from Stripe — it is never estimated. Those rows are
    excluded and counted, so a cost total is never quietly understated.
    """
    q = _window(_member_txn_query(db, scope), _settlement_date_column(), window)
    total, unknown = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.processing_fee_cents), 0),
        func.count(PaymentTransaction.id)
        - func.count(PaymentTransaction.processing_fee_cents),
    ).one()
    quals = _settlement_basis(db, scope, window)
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
    dimensions=("space_id", "creator_user_id", "stripe_mode"),
    compute=_processing_costs,
))


def _subscription_revenue(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Creator plan fees paid to Fresh Collective.

    Platform-only and never scoped to a creator: a creator's own plan fee
    is Fresh Collective's revenue, not theirs, and showing it inside
    their earnings reporting would misstate both.
    """
    q = db.query(PaymentTransaction).filter(
        *creator_plan_filters(_platform_mode()),
    )
    q = _window(q, _settlement_date_column(), window)
    total = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.gross_amount_cents), 0)
    ).scalar() or 0
    return MetricValue(key="subscription_revenue_cents", value=int(total))


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
    compute=_subscription_revenue,
))


def _refunds(db: Session, scope: ReportScope, window: Window) -> MetricValue:
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
    q = _apply_scope(q, scope)
    q = _window(q, PaymentTransaction.last_refunded_at, window)
    total, rows = q.with_entities(
        func.coalesce(func.sum(PaymentTransaction.refunded_amount_cents), 0),
        func.count(PaymentTransaction.id),
    ).one()
    return MetricValue(
        key="refunds_cents",
        value=int(total or 0),
        qualifiers={
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
    dimensions=("space_id", "creator_user_id"),
    compute=_refunds,
))


def _paid_out(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Cash actually transferred, on the date it was marked paid.

    Only ever written by a recorded payout batch. A Stripe payout into
    Fresh Collective's own bank account is a different event and does not
    appear here — nor should it, since money reaching the platform is not
    the same act as money reaching a creator.
    """
    q = _payout_query(db, scope).filter(
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
    dimensions=("space_id", "creator_user_id"),
    compute=_paid_out,
))


def _outstanding_payouts(db: Session, scope: ReportScope, window: Window) -> MetricValue:
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

    q = _payout_query(db, scope)
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
    founder_space_ids = (
        select(Space.id)
        .join(User, User.id == Space.creator_id)
        .where(User.role == UserRole.admin.value)
    )

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
    dimensions=("space_id", "creator_user_id"),
    compute=_outstanding_payouts,
))


def _contribution(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """What Fresh Collective keeps after directly attributable costs.

    **Not net profit.** It excludes every operating expense — hosting,
    software, the founder's time — so calling it profit would overstate
    the health of the business. The name says what it is.
    """
    fee = REGISTRY.get("platform_fee_revenue_cents").evaluate(db, scope, window)
    subs = REGISTRY.get("subscription_revenue_cents").evaluate(db, scope, window)
    costs = REGISTRY.get("processing_costs_cents").evaluate(db, scope, window)
    value = int(fee.value or 0) + int(subs.value or 0) - int(costs.value or 0)
    return MetricValue(
        key="contribution_after_processing_cents",
        value=value,
        qualifiers={
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


def _registered_users(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Accounts in existence as at the measurement date.

    A snapshot, not a flow: asking for "this month" asks how many
    accounts existed at the end of this month, not how many signed up
    during it. ``accounts_registered`` is the flow.
    """
    as_at = _as_at(window)
    q = db.query(func.count(User.id))
    if as_at is not None:
        q = q.filter(User.created_at <= as_at)
    n = q.scalar() or 0
    return MetricValue(
        key="registered_users", value=int(n),
        qualifiers={"as_at": _as_at_label(db, window)},
    )


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
    compute=_registered_users,
))


def _registered_creators(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Creator accounts in existence as at the measurement date."""
    as_at = _as_at(window)
    q = db.query(func.count(User.id)).filter(User.role == "creator")
    if as_at is not None:
        q = q.filter(User.created_at <= as_at)
    n = q.scalar() or 0
    return MetricValue(
        key="registered_creators", value=int(n),
        qualifiers={"as_at": _as_at_label(db, window)},
    )


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
    compute=_registered_creators,
))


def _membership_query(db: Session, scope: ReportScope, *, as_at=None):
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
    if not scope.is_platform:
        if not scope.space_ids:
            return q.filter(False)
        q = q.filter(SpaceMembership.space_id.in_(scope.space_ids))
    return q


def _unique_members(db: Session, scope: ReportScope, window: Window) -> MetricValue:
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
    n = (
        _membership_query(db, scope, as_at=_as_at(window))
        .with_entities(func.count(func.distinct(SpaceMembership.user_id)))
        .scalar() or 0
    )
    return MetricValue(
        key="unique_members", value=int(n),
        qualifiers=_snapshot_qualifiers(db, window),
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
    dimensions=("space_id",),
    personal_data=True,
    compute=_unique_members,
))


def _total_memberships(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Memberships in force as at the measurement date. A snapshot."""
    n = (
        _membership_query(db, scope, as_at=_as_at(window))
        .with_entities(func.count(SpaceMembership.id))
        .scalar() or 0
    )
    return MetricValue(
        key="total_memberships", value=int(n),
        qualifiers=_snapshot_qualifiers(db, window),
    )


def _memberships_started(
    db: Session, scope: ReportScope, window: Window,
) -> MetricValue:
    """Memberships that began in the window. The flow beside the snapshot.

    Counts memberships rather than people, so it adds up across periods —
    which is exactly why it is a separate metric from ``unique_members``
    rather than the same one with a date filter.
    """
    q = db.query(SpaceMembership)
    if not scope.is_platform:
        if not scope.space_ids:
            q = q.filter(False)
        else:
            q = q.filter(SpaceMembership.space_id.in_(scope.space_ids))
    if window.starts_at is not None:
        q = q.filter(SpaceMembership.joined_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(SpaceMembership.joined_at < window.ends_at)
    n = q.with_entities(func.count(SpaceMembership.id)).scalar() or 0
    return MetricValue(key="memberships_started", value=int(n))


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
    dimensions=("space_id",),
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
    dimensions=("space_id",),
    compute=_memberships_started,
))


def _multi_collective_members(
    db: Session, scope: ReportScope, window: Window,
) -> MetricValue:
    """People belonging to more than one Collective.

    Always computed across the whole platform, even for a creator scope:
    the question is whether *this* member also belongs elsewhere, and
    restricting the count to the creator's own Collectives would answer a
    different one. Only the count is returned — never which other
    Collectives, which is not a creator's business.
    """
    inner = (
        select(SpaceMembership.user_id)
        .where(SpaceMembership.status == SpaceMembershipStatus.active)
        .group_by(SpaceMembership.user_id)
        .having(func.count(func.distinct(SpaceMembership.space_id)) > 1)
        .subquery()
    )
    q = db.query(func.count()).select_from(inner)
    if not scope.is_platform:
        if not scope.space_ids:
            return MetricValue(key="multi_collective_members", value=0)
        mine = (
            select(SpaceMembership.user_id)
            .where(
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.space_id.in_(scope.space_ids),
            )
            .subquery()
        )
        q = (
            db.query(func.count(func.distinct(inner.c.user_id)))
            .select_from(inner)
            .join(mine, mine.c.user_id == inner.c.user_id)
        )
    return MetricValue(key="multi_collective_members", value=int(q.scalar() or 0))


REGISTRY.add(Metric(
    key="multi_collective_members",
    display_name="Members in more than one Collective",
    definition=(
        "People holding active memberships in two or more Collectives. For a "
        "creator, this counts their own members who also belong elsewhere — "
        "the count only, never which Collectives."
    ),
    source_of_truth="space_memberships where status = active",
    grain=Grain.snapshot,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
    limitations="Non-additive across periods or Collectives.",
    personal_data=True,
    compute=_multi_collective_members,
))


def _memberships_per_member(
    db: Session, scope: ReportScope, window: Window,
) -> MetricValue:
    members = _unique_members(db, scope, window).value or 0
    memberships = _total_memberships(db, scope, window).value or 0
    if not members:
        return MetricValue(
            key="memberships_per_member",
            value=None,
            unavailable_reason="No members yet, so there is no average to report.",
        )
    return MetricValue(
        key="memberships_per_member",
        value=round(memberships / members, 2),
        qualifiers={"unique_members": members, "total_memberships": memberships},
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
    compute=_memberships_per_member,
))


# ---------------------------------------------------------------------------
# Collectives
# ---------------------------------------------------------------------------

def _collectives(status: str | None, key: str):
    def compute(db: Session, scope: ReportScope, window: Window) -> MetricValue:
        q = db.query(func.count(Space.id))
        if status is not None:
            q = q.filter(Space.status == status)
        if not scope.is_platform:
            if not scope.space_ids:
                return MetricValue(key=key, value=0)
            q = q.filter(Space.id.in_(scope.space_ids))
        return MetricValue(key=key, value=int(q.scalar() or 0))

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
        source_of_truth="spaces.status",
        grain=Grain.snapshot,
        aggregation=Aggregation.snapshot,
        date_basis=DateBasis.none,
        access=Access.creator_visible,
        availability=Availability.full,
        dimensions=("space_id",),
        compute=_collectives(_status, _key),
    ))
