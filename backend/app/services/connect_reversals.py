"""Get the creator's share back when a Connect purchase is refunded or disputed.

Refunding a separate charge does nothing to the transfer that carried the
creator's share — Stripe is explicit that "refunding a charge has no impact on
any associated transfers". So the claw-back is FC's to do, and this is where.

The formula
-----------
The existing refund machinery already computes the authoritative cumulative
figure for the creator side of the gross split:
``refunded_creator_amount_cents``, derived by
``refund_reversal.compute_cumulative_reversal_targets`` from Stripe's
cumulative ``amount_refunded``. That number is in *gross-split* terms and is
larger than what was actually transferred, because FC retained the Stripe
processing fee before transferring:

    transfer_amount_cents = net_creator_amount_cents - processing_fee_cents

Reversing ``refunded_creator_amount_cents`` would therefore try to take back
more than the creator ever received, and Stripe would refuse. So the
cumulative reversal target is that same authoritative figure scaled onto the
amount actually sent:

    full refund   → transfer_amount_cents                       (exact)
    partial       → transfer_amount_cents
                    × refunded_creator_amount_cents
                    ÷ net_creator_amount_cents

The full-refund case is coerced rather than computed, mirroring the existing
machinery's short-circuit, so no rounding drift can leave a cent stranded.

Who absorbs the processing fee
------------------------------
FC does. Stripe does not return its processing fee on a refund, so that money
is gone; the creator never received it, so it is not theirs to give back.
Scaling onto the transfer keeps the creator returning exactly what they got
and leaves the fee where it fell. This is why the reversal target is *not*
``refunded_creator_amount_cents`` and why ``net_creator_amount_cents`` is
still not redefined.

Cumulative, never incremental
-----------------------------
Every attempt recomputes the target from the transaction's current cumulative
refund state and reverses only ``target - reversed_transfer_amount_cents``.
A re-delivered refund event therefore computes the same target, finds the
delta is zero, and does nothing. A second partial refund computes a larger
target and reverses only the difference. Same discipline as the fee-split
columns it is derived from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import stripe
from sqlalchemy.orm import Session

from app.checkout.stripe_client import get_stripe
from app.models.payment import (
    ConnectRecoveryState,
    ConnectTransferStatus,
    PaymentTransaction,
    PayoutModel,
)

logger = logging.getLogger(__name__)

#: Stripe codes meaning the creator simply does not have the money right now.
#: Not a failure to retry blindly and not a write-off — FC is owed it, and an
#: admin needs to know how much.
INSUFFICIENT_BALANCE_CODES = frozenset({
    "balance_insufficient",
    "insufficient_funds",
})

#: Transient, worth trying again unchanged.
RETRYABLE_CODES = frozenset({"lock_timeout", "rate_limit"})

#: The advisory recorded when Stripe could not return the money. Reuses the
#: existing vocabulary the refund routes already speak, so operational
#: tooling built for manual payouts understands Connect recovery too.
RECOVERY_ADVISORY = "post_payout_manual_recovery_required"


class ReversalError(RuntimeError):
    """Base for a failed reversal attempt."""


class ReversalRetryable(ReversalError):
    """Transient. Try the same reversal again later."""


class ReversalRecoveryRequired(ReversalError):
    """Stripe will not return the money — the creator's balance cannot cover it.

    Distinct from retryable on purpose: retrying does not help until the
    creator's balance changes, and distinct from terminal because FC is still
    owed the amount. The row records what remains outstanding.
    """


class ReversalTerminal(ReversalError):
    """Malformed or impossible as requested. Retrying gets the same answer."""


@dataclass(frozen=True)
class ReversalOutcome:
    """What an attempt did.

    ``reversed_now`` is the amount this attempt actually took back, which is
    zero for a no-op and for every failure.
    """

    status: str
    reversed_now: int = 0
    cumulative_reversed: int = 0
    target: int = 0
    unrecovered: int = 0
    detail: str = ""

    @property
    def fully_reversed(self) -> bool:
        return self.status == ConnectTransferStatus.reversed.value


NOOP = "noop"
SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# The target
# ---------------------------------------------------------------------------


def compute_reversal_target(txn: PaymentTransaction) -> int:
    """The cumulative amount of the transfer that should now be reversed.

    Anchored on ``refunded_creator_amount_cents`` — the figure the existing
    refund machinery already derived — rather than on a fresh proportional
    calculation from the refunded gross, so the two can never disagree about
    what share of a purchase has been returned.
    """
    transferred = txn.transfer_amount_cents or 0
    if transferred <= 0:
        return 0

    gross = txn.gross_amount_cents or 0
    refunded = txn.refunded_amount_cents or 0
    if refunded <= 0 or gross <= 0:
        return 0

    # Full refund: coerced, not computed. Identical intent to the fee-split
    # machinery's short-circuit — a partial's rounding must never leave a
    # cent stranded once everything has been returned.
    if refunded >= gross:
        return transferred

    net_creator = txn.net_creator_amount_cents or 0
    if net_creator <= 0:
        return 0

    refunded_creator = txn.refunded_creator_amount_cents or 0
    target = round(transferred * refunded_creator / net_creator)
    return max(0, min(target, transferred))


def current_recovery_target(txn: PaymentTransaction) -> int:
    """How much of the transfer should be back with FC right now.

    Covers both reasons money comes back, so no caller has to know the rule:

    * **disputed** — FC is liable for the whole charge, so the whole transfer
      is owed regardless of what has been refunded. A dispute usually arrives
      with no refund at all, where the refund-derived target would be zero.
    * **refunded** — the proportional cumulative target above.

    This is what makes a recovery row re-computable later: a sweeper picking it
    up days afterwards derives the same figure from stored state rather than
    needing the original event's context.
    """
    if txn.connect_dispute_opened_at is not None:
        return txn.transfer_amount_cents or 0
    return compute_reversal_target(txn)


def reversal_idempotency_key(payment_transaction_id: str, target: int) -> str:
    """Deterministic per (transaction, cumulative target).

    The target is part of the key on purpose. A re-delivered event computes
    the same target and is deduped by Stripe as well as by the delta check; a
    *second* partial refund computes a larger target and is legitimately a
    different request, which a transaction-only key would have wrongly
    collapsed into the first.
    """
    return f"txn:{payment_transaction_id}:reversal:{target}:v1"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(exc: Exception) -> ReversalError:
    """Three outcomes, not two.

    An insufficient connected balance is neither a transient blip nor a dead
    end: FC is owed the money and cannot take it right now. It gets its own
    class so the caller records the outstanding amount instead of retrying
    forever or writing it off.
    """
    code = getattr(exc, "code", None)

    if isinstance(exc, stripe.InvalidRequestError):
        if code in INSUFFICIENT_BALANCE_CODES:
            return ReversalRecoveryRequired(
                f"the creator's Stripe balance cannot cover the reversal "
                f"({code}): {exc}"
            )
        if code in RETRYABLE_CODES:
            return ReversalRetryable(f"{code}: {exc}")
        # Stripe understood and refused. An identical retry gets an identical
        # answer, so this is positive evidence rather than a guess.
        return ReversalTerminal(f"Stripe refused the reversal ({code}): {exc}")

    if isinstance(exc, stripe.IdempotencyError):
        return ReversalTerminal(
            f"idempotency key reused with different parameters, so a reversal "
            f"may already exist and cannot be identified from here: {exc}"
        )

    if isinstance(exc, stripe.StripeError):
        return ReversalRetryable(f"Stripe error ({code or type(exc).__name__}): {exc}")

    return ReversalRetryable(f"unclassified failure ({type(exc).__name__}): {exc}")


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def _status_for(txn: PaymentTransaction, *, transferred: int) -> str:
    """Transfer status implied by how much has been reversed."""
    reversed_total = txn.reversed_transfer_amount_cents or 0
    if reversed_total <= 0:
        return txn.connect_transfer_status
    if reversed_total >= transferred:
        return ConnectTransferStatus.reversed.value
    return ConnectTransferStatus.partially_reversed.value


def _record_failure(
    db: Session,
    txn: PaymentTransaction,
    exc: ReversalError,
    *,
    target: int,
    now: datetime,
) -> ReversalOutcome:
    txn.reversal_attempted_at = now
    txn.reversal_attempt_count = (txn.reversal_attempt_count or 0) + 1
    txn.reversal_last_error = str(exc)[:2000]
    outstanding = max(0, target - (txn.reversed_transfer_amount_cents or 0))

    if isinstance(exc, ReversalRecoveryRequired):
        # FC is owed this. Recorded as outstanding, with the amount, so an
        # admin can pursue it — never as a success and never as nothing.
        txn.connect_recovery_state = ConnectRecoveryState.required.value
        txn.connect_unrecovered_amount_cents = outstanding
        db.commit()
        logger.error(
            "connect reversal: txn=%s RECOVERY REQUIRED — %s of %s could not be "
            "reversed (%s). Advisory: %s",
            txn.id, outstanding, target, exc, RECOVERY_ADVISORY,
        )
        return ReversalOutcome(
            status=ConnectRecoveryState.required.value,
            cumulative_reversed=txn.reversed_transfer_amount_cents or 0,
            target=target,
            unrecovered=outstanding,
            detail=str(exc),
        )

    if isinstance(exc, ReversalTerminal):
        # Still owed — a terminal Stripe refusal does not mean FC has stopped
        # being owed the money, only that this request will never work.
        txn.connect_recovery_state = ConnectRecoveryState.required.value
        txn.connect_unrecovered_amount_cents = outstanding
        db.commit()
        logger.error(
            "connect reversal: txn=%s TERMINAL — %s still outstanding: %s",
            txn.id, outstanding, exc,
        )
        return ReversalOutcome(
            status=ConnectRecoveryState.required.value,
            cumulative_reversed=txn.reversed_transfer_amount_cents or 0,
            target=target,
            unrecovered=outstanding,
            detail=str(exc),
        )

    # Retryable, but still unresolved — and that has to be recorded, not just
    # logged. FC is owed this money whatever the reason the call failed, and a
    # row showing nothing outstanding is a row no sweeper can find.
    txn.connect_recovery_state = ConnectRecoveryState.required.value
    txn.connect_unrecovered_amount_cents = outstanding
    db.commit()
    logger.warning(
        "connect reversal: txn=%s retryable after %s attempt(s), %s outstanding: %s",
        txn.id, txn.reversal_attempt_count, outstanding, exc,
    )
    return ReversalOutcome(
        status="retryable",
        cumulative_reversed=txn.reversed_transfer_amount_cents or 0,
        target=target,
        unrecovered=outstanding,
        detail=str(exc),
    )


def reverse_to_target(
    db: Session,
    *,
    payment_transaction_id: str,
    target_override: int | None = None,
    now: datetime | None = None,
) -> ReversalOutcome:
    """Reverse the transfer up to its cumulative target, at most once per delta.

    Re-reads the row under ``SELECT … FOR UPDATE`` so two concurrent attempts
    cannot both send the same delta: the second computes a delta of zero
    against the first's committed total.

    The target defaults to :func:`current_recovery_target`, derived under the
    same lock, so refunds and disputes are handled by one rule and a retry
    days later recomputes the same figure. ``target_override`` remains for a
    caller that genuinely knows better.
    """
    now = now or datetime.utcnow()

    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == payment_transaction_id)
        .with_for_update()
        # ``populate_existing`` is load-bearing, not tidiness. Without it
        # SQLAlchemy returns the instance already in this session's identity
        # map and leaves its loaded attributes alone, so a caller that read the
        # row before taking the lock would compute its delta from values that
        # predate another worker's commit — and reverse the same amount twice.
        .populate_existing()
        .first()
    )
    if txn is None:
        return ReversalOutcome(status=SKIPPED, detail="transaction not found")
    if txn.payout_model != PayoutModel.connect.value:
        return ReversalOutcome(status=SKIPPED, detail="not Connect-routed")
    if not txn.provider_transfer_id:
        # Nothing was ever sent, so there is nothing to claw back. A refund
        # on such a row simply cancels the obligation.
        return ReversalOutcome(
            status=SKIPPED, detail="no transfer was sent for this transaction",
        )

    transferred = txn.transfer_amount_cents or 0
    target = (
        target_override if target_override is not None
        else current_recovery_target(txn)
    )
    target = max(0, min(target, transferred))
    already = txn.reversed_transfer_amount_cents or 0
    delta = target - already

    if delta <= 0:
        # Includes the re-delivered-event case and the already-fully-reversed
        # case. Both are no-ops by arithmetic rather than by a flag.
        return ReversalOutcome(
            status=NOOP,
            cumulative_reversed=already,
            target=target,
            detail=(
                "already reversed to target"
                if target > 0 else "nothing to reverse"
            ),
        )

    api = get_stripe()
    try:
        api.Transfer.create_reversal(
            txn.provider_transfer_id,
            amount=delta,
            metadata={
                "payment_transaction_id": txn.id,
                "fc_cumulative_target": str(target),
            },
            idempotency_key=reversal_idempotency_key(txn.id, target),
        )
    except Exception as exc:  # noqa: BLE001 — classified, then recorded
        return _record_failure(db, txn, classify(exc), target=target, now=now)

    # Cumulative, monotonic: derived from the target rather than accumulated,
    # so an out-of-order event cannot push it backwards.
    txn.reversed_transfer_amount_cents = max(already, target)
    txn.connect_transfer_status = _status_for(txn, transferred=transferred)
    txn.reversal_attempted_at = now
    txn.reversal_attempt_count = (txn.reversal_attempt_count or 0) + 1
    txn.reversal_last_error = None
    txn.connect_unrecovered_amount_cents = 0
    txn.connect_recovery_state = (
        ConnectRecoveryState.recovered.value
        if txn.reversed_transfer_amount_cents >= target
        else ConnectRecoveryState.required.value
    )
    db.commit()

    logger.info(
        "connect reversal: txn=%s reversed %s (cumulative %s of %s transferred) "
        "status=%s",
        txn.id, delta, txn.reversed_transfer_amount_cents, transferred,
        txn.connect_transfer_status,
    )
    return ReversalOutcome(
        status=txn.connect_transfer_status,
        reversed_now=delta,
        cumulative_reversed=txn.reversed_transfer_amount_cents,
        target=target,
        detail="reversed",
    )


def reconcile_from_stripe(
    db: Session, *, transfer_id: str, now: datetime | None = None,
) -> ReversalOutcome:
    """Catch FC's ledger up to a reversal it did not make.

    A transfer can be reversed from the Stripe Dashboard, or by Stripe itself.
    Without this the row would keep claiming ``sent`` while the money had
    already come back.

    The transfer is re-fetched rather than trusted from the event payload:
    ``amount_reversed`` on the live object is the authoritative cumulative
    total, and it is what gets persisted.
    """
    now = now or datetime.utcnow()

    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_transfer_id == transfer_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if txn is None:
        return ReversalOutcome(
            status=SKIPPED, detail=f"no transaction holds transfer {transfer_id}",
        )

    api = get_stripe()
    try:
        transfer = api.Transfer.retrieve(transfer_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "connect reversal: could not re-read transfer %s: %s", transfer_id, exc,
        )
        return ReversalOutcome(status="retryable", detail=str(exc))

    def _field(name: str, default=None):
        if isinstance(transfer, dict):
            return transfer.get(name, default)
        return getattr(transfer, name, default)

    amount_reversed = int(_field("amount_reversed", 0) or 0)
    fully = bool(_field("reversed", False))
    transferred = txn.transfer_amount_cents or int(_field("amount", 0) or 0)

    previous = txn.reversed_transfer_amount_cents or 0
    if amount_reversed <= previous and not fully:
        return ReversalOutcome(
            status=NOOP,
            cumulative_reversed=previous,
            detail="Stripe reports no more reversed than we already recorded",
        )

    # Monotonic: Stripe's cumulative figure, never lowered.
    txn.reversed_transfer_amount_cents = max(previous, amount_reversed)
    if fully or txn.reversed_transfer_amount_cents >= transferred > 0:
        txn.connect_transfer_status = ConnectTransferStatus.reversed.value
    elif txn.reversed_transfer_amount_cents > 0:
        txn.connect_transfer_status = ConnectTransferStatus.partially_reversed.value

    # An externally reversed transfer settles whatever FC was owed, up to the
    # amount that came back.
    outstanding = max(
        0, (txn.connect_unrecovered_amount_cents or 0) - (
            txn.reversed_transfer_amount_cents - previous
        ),
    )
    txn.connect_unrecovered_amount_cents = outstanding
    if outstanding == 0 and txn.connect_recovery_state == ConnectRecoveryState.required.value:
        txn.connect_recovery_state = ConnectRecoveryState.recovered.value
    db.commit()

    logger.info(
        "connect reversal: txn=%s reconciled from Stripe — cumulative reversed "
        "%s of %s, status=%s",
        txn.id, txn.reversed_transfer_amount_cents, transferred,
        txn.connect_transfer_status,
    )
    return ReversalOutcome(
        status=txn.connect_transfer_status,
        reversed_now=txn.reversed_transfer_amount_cents - previous,
        cumulative_reversed=txn.reversed_transfer_amount_cents,
        target=txn.reversed_transfer_amount_cents,
        unrecovered=outstanding,
        detail="reconciled from Stripe",
    )
