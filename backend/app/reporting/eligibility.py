"""The one place that decides which ledger rows are a member purchase.

``dates.py`` exists because the same payment had two periods. This file
exists because the same payment had two *definitions*, which was worse.

What went wrong
---------------
``_MEMBER_TXN_TYPES`` in ``app.admin.routes`` carried seven transaction
types. The BI registry declared its own tuple of five, with a comment
claiming it mirrored the admin set, and the two missing types were
``member_series_pass_purchase`` and ``member_payment_option_purchase``
— the latter being the type the unified ``POST /api/checkout`` writes,
which is to say every modern PaymentOption purchase. EMBODY sells
through that route, so World Insights reported gross sales, creator
earnings, platform fee revenue, processing costs, refunds and
contribution with EMBODY absent from all six.

The admin set's own comment had recorded that exact hazard once
already::

    # Unified B4B checkout — the type modern PaymentOption purchases
    # write. Historically absent from this set, which silently
    # excluded every EMBODY row from admin revenue metrics.

A duplicated constant is how a fixed bug comes back. So there is now one
tuple, imported by both, and a test asserts no second definition appears.

Why a transaction type is not enough on its own
-----------------------------------------------
``outstanding_payouts_cents`` and ``paid_out_cents`` filtered on payout
status alone, while every revenue metric filtered on type and status.
A single dashboard therefore reported a *fuller* picture of liabilities
than of the revenue those liabilities came from — the asymmetry that
surfaced as $1,560 outstanding beside understated earnings.

Payout figures carry three further conditions, which are not a stricter
view of the same question but part of what makes a row an obligation at
all:

* a **settled status** — a row is created when the Checkout Session
  opens, already carrying ``payout_status='pending'``. Until the payment
  succeeds there is no money and so no obligation.
* a **creator** — a platform-owned Collective has no creator share.
* a **Stripe mode** — test-mode rows are a sandbox, never a liability.
  Rows predating migration 056 are labelled ``test``, which migration
  056 records as accurate: they were all taken on ``sk_test_`` keys.

Deliberately not here
---------------------
Nothing in this module changes how money is calculated. ``net_creator``,
platform fees and refund arithmetic are untouched; this only decides
which rows the arithmetic runs over.
"""

from __future__ import annotations

from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutModel,
)

#: Every transaction type that represents a member buying something from
#: a creator. Gross volume, which is explicitly *not* Fresh Collective's
#: own revenue.
#:
#: Ordered oldest-first so the history is readable. Add to this tuple and
#: both admin reporting and the BI registry pick the type up together —
#: that being the entire point of the file.
MEMBER_TXN_TYPES: tuple[PaymentTransactionType, ...] = (
    PaymentTransactionType.member_pathway_purchase,
    PaymentTransactionType.member_collective_purchase,
    PaymentTransactionType.member_pathway_subscription,
    PaymentTransactionType.member_collective_subscription,
    PaymentTransactionType.gathering_ticket_purchase,
    #: Pay-in-full for a bounded Gathering Series, e.g. an EMBODY term.
    PaymentTransactionType.member_series_pass_purchase,
    #: What the unified ``POST /api/checkout`` writes. A single
    #: PaymentOption can grant Pathways and Series together, so the row
    #: is not classified by a "primary" grant. Every modern EMBODY and
    #: Life in Full Colour purchase is this type.
    PaymentTransactionType.member_payment_option_purchase,
)

#: What a creator pays Fresh Collective for their plan. Fresh Collective's
#: revenue, not a creator's earnings, and never a member purchase — kept
#: beside ``MEMBER_TXN_TYPES`` so the distinction is read in one glance.
CREATOR_PLAN_TXN_TYPES: tuple[PaymentTransactionType, ...] = (
    PaymentTransactionType.creator_subscription_payment,
)

#: Statuses where money genuinely moved. A partially refunded payment is
#: still a settled sale; its refund is accounted for separately, on the
#: refund's own date.
SETTLED_STATUSES: tuple[PaymentTransactionStatus, ...] = (
    PaymentTransactionStatus.succeeded,
    PaymentTransactionStatus.partially_refunded,
    PaymentTransactionStatus.refunded,
)

#: Statuses where no money moved and none ever will. A row in one of
#: these states can hold no payout obligation, whatever its
#: ``payout_status`` column happens to say.
UNSETTLED_STATUSES: tuple[PaymentTransactionStatus, ...] = (
    PaymentTransactionStatus.pending,
    PaymentTransactionStatus.failed,
    PaymentTransactionStatus.cancelled,
)

#: Payout models that enter Fresh Collective's own payout bookkeeping.
#: A ``connect`` row's creator share reaches them through Stripe and is
#: tracked by ``connect_transfer_status`` instead; such rows are created
#: ``payout_status='not_applicable'`` precisely so they cannot appear in
#: a manual payout total.
MANUAL_PAYOUT_MODELS: tuple[PayoutModel, ...] = (
    PayoutModel.manual,
)


def member_txn_values() -> list[str]:
    """``MEMBER_TXN_TYPES`` as the strings stored in the column."""
    return [t.value for t in MEMBER_TXN_TYPES]


def settled_status_values() -> list[str]:
    """``SETTLED_STATUSES`` as the strings stored in the column."""
    return [s.value for s in SETTLED_STATUSES]


def unsettled_status_values() -> list[str]:
    return [s.value for s in UNSETTLED_STATUSES]


def mode_filter(stripe_mode: str) -> tuple:
    """Only the deployment's own Stripe mode.

    Required by every money figure, not only the payout ones. Without it
    the revenue metrics counted sandbox rows while the payout metrics
    did not, so the two families disagreed about the same dollar — the
    original defect in a new place. Admin's commerce endpoints have
    always defaulted to ``settings.stripe_mode``; this is the same rule
    written once.

    Rows predating migration 056 read ``test``, which that migration
    records as accurate rather than a backfill guess: they were all
    taken on ``sk_test_`` keys.
    """
    return (PaymentTransaction.stripe_mode == stripe_mode,)


def member_purchase_filters(stripe_mode: str) -> tuple:
    """SQL conditions for "a member bought something and paid for it".

    The shared basis of every revenue metric. Returned as a tuple so a
    caller spreads it into ``filter()`` rather than receiving a query it
    then has to unpick.
    """
    return (
        PaymentTransaction.transaction_type.in_(member_txn_values()),
        PaymentTransaction.status.in_(settled_status_values()),
        *mode_filter(stripe_mode),
    )


def creator_plan_filters(stripe_mode: str) -> tuple:
    """SQL conditions for "a creator paid Fresh Collective for a plan"."""
    return (
        PaymentTransaction.transaction_type.in_(
            [t.value for t in CREATOR_PLAN_TXN_TYPES]
        ),
        PaymentTransaction.status.in_(settled_status_values()),
        *mode_filter(stripe_mode),
    )


def payout_obligation_filters(stripe_mode: str) -> tuple:
    """SQL conditions for "this row can carry a creator payout".

    ``member_purchase_filters`` plus the two conditions that make a
    settled purchase an *obligation*: a creator to owe it to, and a
    known creator share. Applied to the paid and outstanding figures
    alike, so the two answer the same question from opposite sides and
    must therefore agree on who is in scope.
    """
    return (
        *member_purchase_filters(stripe_mode),
        PaymentTransaction.creator_user_id.isnot(None),
        PaymentTransaction.net_creator_amount_cents.isnot(None),
    )
