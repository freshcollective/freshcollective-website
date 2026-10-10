"""Fill in the Stripe processing fee on succeeded payments that lack one.

Why this exists
---------------
Fresh Collective absorbs Stripe's processing fee, so the creator's transfer
is ``net_creator_amount_cents`` and does not reference the fee at all. That
is what lets a transfer go out the moment a payment succeeds, instead of
waiting for Stripe to report a figure the creator was never going to be
charged.

The cost is still Fresh Collective's, though, and it still has to be
reported accurately: it is FC's cost of sale, it feeds the admin totals, and
it is shown to creators for transparency. A row the webhook could not price
would otherwise stay ``NULL`` for ever, because the transfer sweeper only
looks at rows that still owe a transfer — a sent row is out of its reach.
This closes that gap.

What it will not do
-------------------
It writes two columns and no others: ``processing_fee_cents``, and
``provider_charge_id`` when the charge id was not recorded and had to be
looked up to find the fee. In particular it never touches
``net_creator_amount_cents``, ``platform_fee_cents``,
``transfer_amount_cents`` or any transfer state, so it cannot change what a
creator earns, re-price a historical commission, or cause a transfer. It
only ever fills a ``NULL``; an existing figure is never overwritten, which
is also what makes it safe to run again.

It never estimates. A fee Stripe will not report stays ``NULL`` and is
logged, and the next run tries again.

Where it runs
-------------
Inside the existing ``fc-connect-transfer-sweeper`` cron, after the sweep.
No new service, no new schedule, no blueprint change. The sweeper itself
still opportunistically records a fee for the rows it handles, because it
has the PaymentIntent in hand anyway; this picks up everything the sweeper
never sees, including manual-payout and creator-billing rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction
from app.services.stripe_finite_plan import retrieve_processing_fee_for_charge

logger = logging.getLogger(__name__)

#: One pass is bounded so a long-standing backlog cannot turn a 15-minute
#: cron into a long-running job. The queue is drained oldest-first across
#: successive runs.
DEFAULT_BATCH_SIZE = 200


@dataclass
class FeeReconciliationReport:
    considered: int = 0
    #: Rows that now carry the fee Stripe actually charged.
    resolved: int = 0
    #: Rows Stripe would not price on this pass. Still ``NULL``, logged, and
    #: retried next run — never guessed at.
    unreadable: list[str] = field(default_factory=list)
    #: Rows whose charge id had to be learned from the PaymentIntent.
    charge_ids_learned: int = 0

    def as_log_fields(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "resolved": self.resolved,
            "unreadable": len(self.unreadable),
            "charge_ids_learned": self.charge_ids_learned,
        }


def _claim_ids(db: Session, *, limit: int) -> list[str]:
    """Succeeded Stripe payments with no fee recorded, oldest first.

    Deliberately narrow. A row with no charge *and* no payment intent has
    nothing to read a fee from, and a row that was never a Stripe payment
    never had a processing fee, so neither is a gap — including them would
    mean retrying rows that can never resolve, every fifteen minutes, for
    ever.
    """
    rows = db.execute(
        text(
            """
            SELECT id
            FROM payment_transactions
            WHERE processing_fee_cents IS NULL
              AND status = 'succeeded'
              AND payment_provider = 'stripe'
              AND gross_amount_cents > 0
              AND (provider_charge_id IS NOT NULL
                   OR provider_payment_intent_id IS NOT NULL)
            ORDER BY created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).fetchall()
    return [row[0] for row in rows]


def _charge_id_for(db: Session, txn: PaymentTransaction) -> tuple[str | None, bool]:
    """The charge to read the fee from, and whether it had to be looked up.

    Prefers the recorded charge id. Falls back to the PaymentIntent's
    ``latest_charge``, which is the case for rows written before the charge
    id was captured, or where the webhook could not expand it.
    """
    if txn.provider_charge_id:
        return txn.provider_charge_id, False
    if not txn.provider_payment_intent_id:
        return None, False

    # Imported here so the module can be imported without a Stripe client.
    from app.checkout.stripe_client import get_stripe

    try:
        pi = get_stripe().PaymentIntent.retrieve(txn.provider_payment_intent_id)
    except Exception as exc:  # noqa: BLE001 — logged, retried next run
        logger.warning(
            "fee reconciliation: txn=%s could not read its payment: %s",
            txn.id, exc,
        )
        return None, False

    charge = getattr(pi, "latest_charge", None)
    # ``latest_charge`` is an id when unexpanded and an object when expanded;
    # accept either rather than assume which this SDK version returned.
    charge_id = charge if isinstance(charge, str) else getattr(charge, "id", None)
    return (str(charge_id), True) if charge_id else (None, False)


def reconcile_missing_fees(
    db: Session, *, limit: int = DEFAULT_BATCH_SIZE,
) -> FeeReconciliationReport:
    """One bounded pass. Commits per row so partial progress survives.

    Safe to run again at any time: every write is conditional on the column
    still being ``NULL``, so a repeat pass over the same rows resolves the
    ones Stripe can now price and leaves everything else exactly as it was.
    """
    report = FeeReconciliationReport()

    for txn_id in _claim_ids(db, limit=limit):
        txn = db.get(PaymentTransaction, txn_id)
        if txn is None:
            continue
        report.considered += 1

        # Re-checked under the current read: another writer — the webhook, or
        # the transfer sweeper — may have filled this in since the claim.
        if txn.processing_fee_cents is not None:
            continue

        charge_id, learned = _charge_id_for(db, txn)
        if not charge_id:
            report.unreadable.append(txn_id)
            continue

        fee = retrieve_processing_fee_for_charge(charge_id)
        if fee is None:
            # Already logged by the helper. Nothing is written, nothing is
            # guessed, and the row stays in the queue for the next run.
            # Nothing has been written at this point — the charge id is only
            # recorded alongside a fee — so there is nothing to undo.
            report.unreadable.append(txn_id)
            continue

        # A conditional UPDATE rather than an attribute assignment, so the
        # "only ever fills a NULL" rule is enforced by the database at the
        # moment of writing. The re-check above is a stale read by the time
        # Stripe has answered: the webhook or the transfer sweeper may have
        # landed during the call. Both would be writing the same real figure
        # for the same charge, so a clobber would be harmless — but an
        # invariant worth stating is worth actually holding.
        values: dict[str, object] = {"processing_fee_cents": int(fee)}
        if learned:
            values["provider_charge_id"] = charge_id
        updated = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.id == txn_id,
                PaymentTransaction.processing_fee_cents.is_(None),
            )
            .update(values, synchronize_session=False)
        )
        db.commit()
        if not updated:
            logger.info(
                "fee reconciliation: txn=%s was priced by another writer "
                "during the Stripe call; left as it stands", txn_id,
            )
            continue
        report.resolved += 1
        if learned:
            report.charge_ids_learned += 1
        logger.info(
            "fee reconciliation: txn=%s processing fee recorded as %s",
            txn_id, fee,
        )

    if report.unreadable:
        logger.warning(
            "fee reconciliation: %s row(s) still have no processing fee; "
            "Stripe would not report one on this pass. Retried next run, "
            "never estimated: %s",
            len(report.unreadable), ", ".join(report.unreadable),
        )
    logger.info("fee reconciliation complete: %s", report.as_log_fields())
    return report
