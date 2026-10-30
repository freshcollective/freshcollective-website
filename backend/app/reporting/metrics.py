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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.models.user import User
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    Metric,
    MetricValue,
    Window,
)
from app.reporting.dates import settlement_date
from app.reporting.scope import Access, ReportScope

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

#: Member purchases — what a member paid a creator for something. These
#: make up gross volume, which is explicitly NOT Fresh Collective's
#: revenue. Mirrors ``_MEMBER_TXN_TYPES`` in the admin routes.
MEMBER_TXN_TYPES = (
    PaymentTransactionType.member_pathway_purchase,
    PaymentTransactionType.member_collective_purchase,
    PaymentTransactionType.member_pathway_subscription,
    PaymentTransactionType.member_collective_subscription,
    PaymentTransactionType.gathering_ticket_purchase,
)

#: Statuses where money genuinely moved. A partially refunded payment is
#: still a settled sale; the refund is accounted for separately, on its
#: own date.
SETTLED_STATUSES = (
    PaymentTransactionStatus.succeeded,
    PaymentTransactionStatus.partially_refunded,
    PaymentTransactionStatus.refunded,
)


#: The canonical financial date, shared with the admin reporting helpers
#: so there cannot be two answers for the same payment. See
#: ``app.reporting.dates`` for why each basis is what it is.
_settlement_date_column = settlement_date


def _member_txn_query(db: Session, scope: ReportScope):
    q = db.query(PaymentTransaction).filter(
        PaymentTransaction.transaction_type.in_([t.value for t in MEMBER_TXN_TYPES]),
        PaymentTransaction.status.in_([s.value for s in SETTLED_STATUSES]),
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
        PaymentTransaction.transaction_type
        == PaymentTransactionType.creator_subscription_payment.value,
        PaymentTransaction.status.in_([s.value for s in SETTLED_STATUSES]),
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
    q = db.query(PaymentTransaction).filter(
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
    """Cash actually transferred, on the date it was marked paid."""
    q = db.query(PaymentTransaction).filter(
        PaymentTransaction.payout_status == PayoutStatus.paid.value,
        PaymentTransaction.payout_marked_at.isnot(None),
    )
    q = _apply_scope(q, scope)
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
    source_of_truth="payment_transactions where payout_status = paid",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.payout_marked,
    access=Access.creator_visible,
    availability=Availability.full,
    dimensions=("space_id", "creator_user_id"),
    compute=_paid_out,
))


def _outstanding_payouts(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """What is still owed. A liability, measured now, not over a period."""
    q = db.query(PaymentTransaction).filter(
        PaymentTransaction.payout_status == PayoutStatus.pending.value,
    )
    q = _apply_scope(q, scope)
    total = q.with_entities(
        func.coalesce(
            func.sum(
                func.coalesce(PaymentTransaction.net_creator_amount_cents, 0)
                - func.coalesce(PaymentTransaction.refunded_creator_amount_cents, 0)
            ),
            0,
        )
    ).scalar() or 0
    return MetricValue(key="outstanding_payouts_cents", value=int(total))


REGISTRY.add(Metric(
    key="outstanding_payouts_cents",
    display_name="Outstanding payouts",
    definition=(
        "Creator earnings awaiting transfer. A liability at this moment, so "
        "a reporting period does not narrow it."
    ),
    source_of_truth="payment_transactions where payout_status = pending",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
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

def _registered_users(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    q = db.query(func.count(User.id))
    if window.starts_at is not None:
        q = q.filter(User.created_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(User.created_at < window.ends_at)
    return MetricValue(key="registered_users", value=int(q.scalar() or 0))


REGISTRY.add(Metric(
    key="registered_users",
    display_name="Registered users",
    definition=(
        "People with a Fresh Collective account, counted once each, "
        "regardless of role or how many Collectives they have joined."
    ),
    source_of_truth="users",
    grain=Grain.snapshot,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.created,
    access=Access.platform_only,
    availability=Availability.full,
    personal_data=True,
    compute=_registered_users,
))


def _registered_creators(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    q = db.query(func.count(User.id)).filter(User.role == "creator")
    if window.starts_at is not None:
        q = q.filter(User.created_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(User.created_at < window.ends_at)
    return MetricValue(key="registered_creators", value=int(q.scalar() or 0))


REGISTRY.add(Metric(
    key="registered_creators",
    display_name="Registered creators",
    definition="Accounts whose platform role is creator.",
    source_of_truth="users.role = 'creator'",
    grain=Grain.snapshot,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.created,
    access=Access.platform_only,
    availability=Availability.full,
    personal_data=True,
    compute=_registered_creators,
))


def _membership_query(db: Session, scope: ReportScope):
    q = db.query(SpaceMembership).filter(
        SpaceMembership.status == SpaceMembershipStatus.active,
    )
    if not scope.is_platform:
        if not scope.space_ids:
            return q.filter(False)
        q = q.filter(SpaceMembership.space_id.in_(scope.space_ids))
    return q


def _unique_members(db: Session, scope: ReportScope, window: Window) -> MetricValue:
    """Distinct people holding at least one active membership.

    The correction. ``/platform/overview`` derives "members" from roles,
    so a creator who joins another Collective is never counted and an
    account that joined nothing is. This counts memberships, and counts
    each person once however many Collectives they belong to — which is
    also what makes a creator's multi-Collective overview correct rather
    than triple-counting a shared member.
    """
    q = _membership_query(db, scope)
    if window.starts_at is not None:
        q = q.filter(SpaceMembership.joined_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(SpaceMembership.joined_at < window.ends_at)
    n = q.with_entities(
        func.count(func.distinct(SpaceMembership.user_id))
    ).scalar() or 0
    return MetricValue(key="unique_members", value=int(n))


REGISTRY.add(Metric(
    key="unique_members",
    display_name="Unique members",
    definition=(
        "Distinct people holding at least one active Collective membership. "
        "Somebody in three Collectives counts once."
    ),
    source_of_truth="space_memberships where status = active",
    grain=Grain.snapshot,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.membership_joined,
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
    q = _membership_query(db, scope)
    if window.starts_at is not None:
        q = q.filter(SpaceMembership.joined_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(SpaceMembership.joined_at < window.ends_at)
    n = q.with_entities(func.count(SpaceMembership.id)).scalar() or 0
    return MetricValue(key="total_memberships", value=int(n))


REGISTRY.add(Metric(
    key="total_memberships",
    display_name="Collective memberships",
    definition=(
        "Active memberships. Somebody in three Collectives contributes three. "
        "A different question from how many people are members."
    ),
    source_of_truth="space_memberships where status = active",
    grain=Grain.snapshot,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.membership_joined,
    access=Access.creator_visible,
    availability=Availability.full,
    dimensions=("space_id",),
    compute=_total_memberships,
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
    definition="Active memberships divided by unique members.",
    source_of_truth="derived from unique_members and total_memberships",
    grain=Grain.snapshot,
    aggregation=Aggregation.ratio,
    date_basis=DateBasis.none,
    access=Access.creator_visible,
    availability=Availability.full,
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
