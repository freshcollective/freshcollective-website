"""What a creator sees about money routed through Connect.

Kept apart from the manual payout figures on purpose. For a Connect-routed sale
Fresh Collective owes the creator nothing by hand — Stripe does — so folding
these into "pending payout" would tell a creator FC is holding money it is not.
The two answers are different and are presented as different things.

What is shown, and what is not
------------------------------
Every row breaks the sale into the three parts that account for it: the sale
amount, FC's platform fee, Stripe's processing fee, and what is left for the
creator. That is the fee model made concrete per sale, which is more use than
any percentage.

Not shown: Stripe account ids, transfer ids, charge ids, attempt counts, raw
Stripe errors, recovery amounts. A creator needs to know where their money is,
not how the plumbing is spelled — and an unrecovered balance is a conversation
FC should have with them, not a number to discover in a list.

Status wording
--------------
``connect_transfer_status`` is an engineering vocabulary. These are the
creator's:

    awaiting_payment    → Waiting for payment
    pending             → Preparing payout
    sent                → Sent to Stripe
    failed              → Needs attention
    partially_reversed  → Partly refunded
    reversed            → Refunded

``sent`` says "Sent to Stripe" rather than "Paid" deliberately. A completed
transfer puts money in the creator's Stripe balance; Stripe pays their bank on
its own schedule, and those are not the same event.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.payment import (
    ConnectRecoveryState,
    ConnectTransferStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PayoutModel,
)

#: Creator-facing wording for each transfer status.
STATUS_LABELS: dict[str, str] = {
    ConnectTransferStatus.awaiting_payment.value: "Waiting for payment",
    ConnectTransferStatus.pending.value: "Preparing payout",
    ConnectTransferStatus.sent.value: "Sent to Stripe",
    ConnectTransferStatus.failed.value: "Needs attention",
    ConnectTransferStatus.partially_reversed.value: "Partly refunded",
    ConnectTransferStatus.reversed.value: "Refunded",
}

NEEDS_ATTENTION = "Needs attention"


@dataclass(frozen=True)
class ConnectEarningRow:
    """One Connect-routed sale, as the creator sees it."""

    payment_transaction_id: str
    created_at: str
    currency: str

    sale_amount_cents: int
    platform_fee_cents: int
    #: ``None`` until Stripe has told us — shown as "being confirmed" rather
    #: than as zero, because zero would be a lie about a real cost.
    processing_fee_cents: int | None
    #: What was transferred, or what will be once the fee is known.
    creator_amount_cents: int | None

    status: str
    status_label: str
    #: True while the amount cannot be stated exactly yet.
    amount_is_estimate: bool
    #: Set when part or all of the sale came back.
    refunded_amount_cents: int
    #: Present only for a plan instalment.
    installment_number: int | None


@dataclass(frozen=True)
class ConnectEarningsSummary:
    """Totals across the rows returned, in one currency."""

    currency: str
    sale_total_cents: int
    platform_fee_total_cents: int
    processing_fee_total_cents: int
    creator_total_cents: int
    sent_total_cents: int
    awaiting_total_cents: int
    row_count: int


def creator_amount_for(txn: PaymentTransaction) -> int | None:
    """What the creator gets from this sale, net of both fees.

    Prefers the figure actually transferred. Falls back to the arithmetic when
    a transfer has not happened yet, and returns ``None`` when the processing
    fee is still unknown rather than implying a precision we do not have.
    """
    if txn.transfer_amount_cents is not None:
        return txn.transfer_amount_cents
    if txn.net_creator_amount_cents is None or txn.processing_fee_cents is None:
        return None
    return max(0, txn.net_creator_amount_cents - txn.processing_fee_cents)


def status_label_for(txn: PaymentTransaction) -> str:
    """The creator-facing status.

    Outstanding recovery is folded into "Needs attention" rather than shown as
    an amount owed. A creator who is being chased for money should hear it from
    a person, not read it in a table.
    """
    if txn.connect_recovery_state == ConnectRecoveryState.required.value:
        return NEEDS_ATTENTION
    return STATUS_LABELS.get(txn.connect_transfer_status, NEEDS_ATTENTION)


def to_row(txn: PaymentTransaction) -> ConnectEarningRow:
    creator_amount = creator_amount_for(txn)
    return ConnectEarningRow(
        payment_transaction_id=txn.id,
        created_at=txn.created_at.isoformat() if txn.created_at else "",
        currency=txn.currency,
        sale_amount_cents=txn.gross_amount_cents or 0,
        platform_fee_cents=txn.platform_fee_cents or 0,
        processing_fee_cents=txn.processing_fee_cents,
        creator_amount_cents=creator_amount,
        status=txn.connect_transfer_status,
        status_label=status_label_for(txn),
        amount_is_estimate=txn.transfer_amount_cents is None,
        refunded_amount_cents=txn.refunded_amount_cents or 0,
        installment_number=txn.installment_number,
    )


def list_connect_earnings(
    db: Session,
    *,
    creator_user_id: str,
    limit: int = 100,
) -> list[ConnectEarningRow]:
    """Connect-routed sales for this creator, newest first.

    Scoped by ``payout_model`` rather than by transfer status, so a creator sees
    the whole picture — including sales still waiting on payment — rather than
    only the ones already sent.
    """
    rows = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.creator_user_id == creator_user_id,
            PaymentTransaction.payout_model == PayoutModel.connect.value,
            PaymentTransaction.status.in_([
                PaymentTransactionStatus.succeeded,
                PaymentTransactionStatus.partially_refunded,
                PaymentTransactionStatus.refunded,
            ]),
        )
        .order_by(PaymentTransaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [to_row(txn) for txn in rows]


def summarise(
    rows: list[ConnectEarningRow], *, currency: str = "AUD",
) -> ConnectEarningsSummary:
    """Totals over the rows given.

    Rows whose processing fee is not yet known contribute nothing to the fee or
    creator totals: a partial sum presented as a total would be wrong in the
    one direction that matters.
    """
    in_currency = [r for r in rows if r.currency == currency]
    priced = [r for r in in_currency if r.creator_amount_cents is not None]

    return ConnectEarningsSummary(
        currency=currency,
        sale_total_cents=sum(r.sale_amount_cents for r in in_currency),
        platform_fee_total_cents=sum(r.platform_fee_cents for r in in_currency),
        processing_fee_total_cents=sum(
            r.processing_fee_cents or 0 for r in in_currency
        ),
        creator_total_cents=sum(r.creator_amount_cents or 0 for r in priced),
        sent_total_cents=sum(
            r.creator_amount_cents or 0 for r in priced
            if r.status == ConnectTransferStatus.sent.value
        ),
        awaiting_total_cents=sum(
            r.creator_amount_cents or 0 for r in priced
            if r.status in (
                ConnectTransferStatus.awaiting_payment.value,
                ConnectTransferStatus.pending.value,
            )
        ),
        row_count=len(in_currency),
    )
