"""Money Fresh Collective is still owed back by a creator.

Read-only. Nothing here retries, writes, or decides anything about a
recovery — ``connect_reversals`` owns the attempt and
``connect_recovery_sweeper`` owns the retry schedule. This module only
answers "what should a person be told about?", so that an outstanding
balance is visible to an operator rather than only to a log line.

Why it exists
-------------
A creator may now refund their own sale after the Connect transfer has
gone out. The customer's refund commits first and is never contingent on
recovery, so when the connected account cannot cover the clawback the
row records ``connect_recovery_state = required`` with the exact
shortfall. That is correct, and it is also the moment Fresh Collective
is owed money by one of its own creators — which nothing on the admin
side surfaced.

Deliberately broader than the sweeper's claim
---------------------------------------------
``connect_recovery_sweeper._claim_ids`` additionally requires a
``provider_transfer_id`` and a transfer status other than ``reversed``,
because it is deciding whether to ask Stripe for money *again*. This
asks a different question. A row the sweeper will never pick up is not
therefore resolved — if anything it needs a human sooner, because no
automatic process is going to clear it. So the three conditions here are
the state itself: Connect, recovery required, something still
outstanding.

Clearing
--------
There is nothing to clear. The rows fall out of this query the moment
``connect_recovery_state`` becomes ``recovered`` or the outstanding
amount reaches zero — both of which the existing reversal path already
writes. No dedup key, no resolve step, no row left asserting a debt that
has since been paid.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction, PayoutModel
from app.models.payment import ConnectRecoveryState


@dataclass(frozen=True)
class OutstandingRecovery:
    """What one creator still owes, in one currency."""

    creator_user_id: str
    currency: str
    outstanding_cents: int
    transaction_count: int
    #: Present when exactly one transaction is outstanding, so an admin
    #: can be sent to the payment itself rather than to a list.
    sample_transaction_id: str | None


def outstanding_recoveries(db: Session) -> list[OutstandingRecovery]:
    """Unrecovered Connect balances, grouped by creator and currency.

    Grouped by currency as well as creator because adding cents across
    currencies would produce a number that is not money. A creator with
    outstanding amounts in two currencies is two rows, which is the
    truthful shape even if it is rarer.

    Ordered by the largest debt first — with a limited operator day, the
    biggest outstanding amount is the one worth starting on.
    """
    rows = (
        db.query(
            PaymentTransaction.creator_user_id,
            PaymentTransaction.currency,
            func.sum(PaymentTransaction.connect_unrecovered_amount_cents),
            func.count(PaymentTransaction.id),
            func.min(PaymentTransaction.id),
        )
        .filter(
            PaymentTransaction.payout_model == PayoutModel.connect.value,
            PaymentTransaction.connect_recovery_state
            == ConnectRecoveryState.required.value,
            PaymentTransaction.connect_unrecovered_amount_cents > 0,
            PaymentTransaction.creator_user_id.isnot(None),
        )
        .group_by(
            PaymentTransaction.creator_user_id,
            PaymentTransaction.currency,
        )
        .order_by(func.sum(PaymentTransaction.connect_unrecovered_amount_cents).desc())
        .all()
    )

    return [
        OutstandingRecovery(
            creator_user_id=creator_id,
            currency=currency,
            outstanding_cents=int(total or 0),
            transaction_count=int(count or 0),
            sample_transaction_id=sample if count == 1 else None,
        )
        for creator_id, currency, total, count, sample in rows
    ]
