"""The one place that decides which timestamp a money metric uses.

BI-2 gave each financial metric its own event date, which was right, but
it left two of the three implementations behind: the registry attributed
by settlement while ``_compute_payment_summary`` and
``_compute_revenue_summary`` still filtered on ``created_at``. The same
payment — created in September, settled in October — therefore counted
as October revenue through ``/reporting/query`` and as September revenue
through ``/commerce/overview``.

That is the original defect wearing different clothes, so the fix is not
"change the other two" but "stop there being more than one definition".
Everything that attributes money to a period imports from here.

Why these three bases
---------------------
**Settlement** for sales, fees, earnings and subscription revenue: the
period a payment belongs to is the period the money arrived, not the
period a checkout row happened to be created in. ``settled_at`` is NULL
for payments that settled before BI-1 — deliberately, because no
estimate was written — so those fall back to ``created_at``, and every
caller reports which basis applied rather than blending the two
silently.

**Refund date** for refunds: a refund belongs to the period it happened
in. Netting it against the original sale would make a closed month's
revenue move afterwards, which is the one thing a financial report must
never do.

**Payout date** for payouts: cash leaving is a different event from
revenue being earned, and it has its own date.
"""

from __future__ import annotations

from sqlalchemy import func

from app.models.payment import PaymentTransaction


def settlement_date():
    """When a payment's money arrived, as a SQL expression.

    ``COALESCE(settled_at, created_at)`` — observed where we have it,
    the creation date as an acknowledged approximation where we do not.
    Pair every use with ``settlement_basis`` reporting so a result that
    mixes the two says so.
    """
    return func.coalesce(PaymentTransaction.settled_at, PaymentTransaction.created_at)


def refund_date():
    """When money went back."""
    return PaymentTransaction.last_refunded_at


def payout_date():
    """When a payout was recorded as paid."""
    return PaymentTransaction.payout_marked_at


def settlement_basis_counts():
    """``(observed, approximated)`` row counts, for qualifying a result."""
    return (
        func.count(PaymentTransaction.settled_at),
        func.count(PaymentTransaction.id) - func.count(PaymentTransaction.settled_at),
    )
