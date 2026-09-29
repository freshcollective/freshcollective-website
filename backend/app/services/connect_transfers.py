"""Send a Connect-routed purchase's creator share to the creator.

Separate charges and transfers: the charge already happened on Fresh
Collective's platform account, and this module moves the creator's share
afterwards as a ``/v1/transfers`` transfer. The amount is exact rather than
estimated, which is the whole reason FC is not using destination charges —

    transfer_amount_cents = net_creator_amount_cents - processing_fee_cents

Stripe bills the processing fee to FC as the platform merchant, so FC
accounts for that cost by retaining it before transferring. That is why the
deduction lives here and not in the gross split: ``net_creator_amount_cents``
still means ``gross - platform_fee`` and never moves.

Two invariants this module exists to protect
-------------------------------------------
**Never send money twice.** Three mechanisms, deliberately overlapping,
because any one of them alone has a hole: a ``SELECT … FOR UPDATE`` row lock
serialises concurrent attempts, a deterministic idempotency key makes Stripe
itself return the original transfer if a duplicate request ever escapes, and
a partial unique index on ``provider_transfer_id`` makes a second distinct
transfer unrecordable. The lock is what makes the other two rarely matter.

**Never guess.** If the processing fee is not known, nothing is sent — no
estimate, no partial. The row stays owed and the sweeper tries again. A
transfer computed from a guessed fee would pay the creator the wrong amount
and there is no clean way to correct it afterwards.

Retry classification
--------------------
``balance_insufficient`` is the one that matters most, and it is *retryable*.
Verified against real Stripe behaviour in Phase 0: a transfer tied to a
freshly created charge can be refused for insufficient balance while that
charge is still settling, and the identical call succeeds once the funds land.
Treating it as a failure would abandon a transfer Stripe was always going to
allow.

Retryable failures stay ``pending`` forever rather than eventually flipping to
``failed``. A row sitting at ``pending`` with a rising attempt count and a
recorded error is visibly still owed; a row marked ``failed`` looks resolved.
The sweeper surfaces long-stuck rows as structured warnings instead — bounded
work per run, never a silent write-off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import stripe
from sqlalchemy.orm import Session

from app.checkout.stripe_client import get_stripe
from app.models.payment import (
    ConnectTransferStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PayoutModel,
)

logger = logging.getLogger(__name__)

#: Attempt count at which a still-pending transfer is surfaced as needing a
#: look. Not a give-up: the row stays owed and the sweeper keeps trying.
ATTENTION_ATTEMPTS = 6

#: ``InvalidRequestError`` codes Stripe raises for conditions that clear on
#: their own. Everything else Stripe *understood and refused* is terminal —
#: repeating an identical request gets an identical answer.
RETRYABLE_CODES = frozenset({
    # The source charge has not settled into the platform's available
    # balance yet. Observed in test mode against a real charge; the same
    # call succeeded once the funds landed.
    "balance_insufficient",
    "lock_timeout",
    "rate_limit",
    # The destination lost its transfers capability. It may come back when
    # the creator resolves whatever Stripe asked for, so this is worth
    # retrying rather than writing off.
    "insufficient_capabilities_for_transfer",
})


class TransferError(RuntimeError):
    """Base for a failed transfer attempt."""


class TransferRetryable(TransferError):
    """Try again later. The row stays ``pending`` and keeps its place."""


class TransferTerminal(TransferError):
    """This transfer, as computed, can never succeed. The row goes ``failed``."""


@dataclass(frozen=True)
class TransferOutcome:
    """What an attempt did.

    ``status`` is the resulting ``connect_transfer_status``, except for
    ``skipped`` — which means the row was not eligible and nothing was
    touched.
    """

    status: str
    transfer_id: str | None = None
    amount_cents: int | None = None
    detail: str = ""

    @property
    def sent(self) -> bool:
        return self.status == ConnectTransferStatus.sent.value


SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------


def compute_transfer_amount(txn: PaymentTransaction) -> int:
    """The creator's share, net of both fees.

    Raises :class:`TransferTerminal` when the result is not a sendable
    amount. Stripe would refuse a zero or negative transfer anyway; refusing
    here means the row records *why* rather than carrying an opaque Stripe
    error, and it can never be mistaken for a transfer that was sent.
    """
    net_creator = txn.net_creator_amount_cents
    processing_fee = txn.processing_fee_cents

    if net_creator is None:
        raise TransferTerminal(
            f"txn {txn.id} has no net_creator_amount_cents; nothing to transfer"
        )
    if processing_fee is None:
        # Not terminal — the fee is retrievable, we just do not have it yet.
        raise TransferRetryable(
            f"txn {txn.id} has no processing_fee_cents yet; refusing to estimate"
        )

    amount = net_creator - processing_fee
    if amount <= 0:
        raise TransferTerminal(
            f"txn {txn.id} transfer amount is {amount} "
            f"(net_creator={net_creator}, processing_fee={processing_fee}); "
            "Stripe's fee met or exceeded the creator's share, so there is "
            "nothing to send"
        )
    return amount


def idempotency_key(payment_transaction_id: str) -> str:
    """Deterministic, so every attempt for a transaction is the same request.

    Derived from the transaction id alone — not from the amount — so a
    retry cannot become a second transfer by recomputing to a different
    figure.
    """
    return f"txn:{payment_transaction_id}:transfer:v1"


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def classify(exc: Exception) -> TransferError:
    """Map a failure onto retryable or terminal.

    The default is retryable. Only an error Stripe *decided* — an
    ``InvalidRequestError`` outside :data:`RETRYABLE_CODES` — counts as
    positive evidence that repeating the request is pointless. Transport
    failures, 5xx, rate limits, and even auth or permission faults are
    retryable, because none of them is evidence the transfer itself is
    impossible and a wrongly-terminal row is money nobody sends.
    """
    code = getattr(exc, "code", None)

    if isinstance(exc, stripe.IdempotencyError):
        # Same key, different parameters. A request under this key already
        # exists, so a transfer may well have been created — this must never
        # be read as "nothing happened", and retrying cannot fix it.
        return TransferTerminal(
            f"idempotency key reused with different parameters, so a transfer "
            f"may already exist and cannot be identified from here: {exc}"
        )

    if isinstance(exc, stripe.InvalidRequestError):
        if code in RETRYABLE_CODES:
            return TransferRetryable(f"{code}: {exc}")
        return TransferTerminal(f"Stripe refused the transfer ({code}): {exc}")

    if isinstance(exc, stripe.StripeError):
        return TransferRetryable(f"Stripe error ({code or type(exc).__name__}): {exc}")

    return TransferRetryable(f"unclassified failure ({type(exc).__name__}): {exc}")


# ---------------------------------------------------------------------------
# Becoming owed
# ---------------------------------------------------------------------------


def mark_transfer_owed(db: Session, txn: PaymentTransaction) -> bool:
    """``awaiting_payment`` → ``pending``: a transfer is now due.

    Only once the payment has definitely succeeded *and* the actual
    processing fee is known, because ``pending`` is what the sweeper acts on
    and a row in it must be immediately computable. Returns False, having
    changed nothing, whenever those conditions do not hold — including for
    rows that are not Connect-routed at all.

    Does not commit; the caller decides the transaction boundary.
    """
    if txn.payout_model != PayoutModel.connect.value:
        return False
    if txn.connect_transfer_status != ConnectTransferStatus.awaiting_payment.value:
        return False
    if txn.status != PaymentTransactionStatus.succeeded:
        return False
    if txn.processing_fee_cents is None:
        # Deliberately stays ``awaiting_payment``. The sweeper resolves the
        # fee before it will consider the row owed.
        logger.warning(
            "connect transfer: txn=%s payment succeeded but the Stripe "
            "processing fee is not known; not marking the transfer owed",
            txn.id,
        )
        return False

    txn.connect_transfer_status = ConnectTransferStatus.pending.value
    logger.info("connect transfer: txn=%s is now owed a transfer", txn.id)
    return True


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _record_failure(
    db: Session, txn: PaymentTransaction, exc: TransferError, *, now: datetime,
) -> TransferOutcome:
    txn.transfer_attempted_at = now
    txn.transfer_attempt_count = (txn.transfer_attempt_count or 0) + 1
    txn.transfer_last_error = str(exc)[:2000]

    if isinstance(exc, TransferTerminal):
        txn.connect_transfer_status = ConnectTransferStatus.failed.value
        db.commit()
        logger.error(
            "connect transfer: txn=%s TERMINAL after %s attempt(s): %s",
            txn.id, txn.transfer_attempt_count, exc,
        )
        return TransferOutcome(
            status=ConnectTransferStatus.failed.value, detail=str(exc),
        )

    # Retryable: stays owed. A rising attempt count on a pending row is a
    # transfer still expected, not one written off.
    txn.connect_transfer_status = ConnectTransferStatus.pending.value
    db.commit()
    log = logger.warning if txn.transfer_attempt_count < ATTENTION_ATTEMPTS else logger.error
    log(
        "connect transfer: txn=%s retryable after %s attempt(s)%s: %s",
        txn.id, txn.transfer_attempt_count,
        " — NEEDS ATTENTION" if txn.transfer_attempt_count >= ATTENTION_ATTEMPTS else "",
        exc,
    )
    return TransferOutcome(
        status=ConnectTransferStatus.pending.value, detail=str(exc),
    )


def execute_transfer(
    db: Session,
    *,
    payment_transaction_id: str,
    now: datetime | None = None,
) -> TransferOutcome:
    """Send the creator's share for one transaction, at most once.

    Takes an id rather than an instance so the row is re-read under a lock
    inside this function — the caller's copy may be stale, and the lock is
    what makes two concurrent attempts safe.

    Eligibility is re-checked under that lock: Connect-routed, ``pending``,
    and no transfer already recorded. Anything else returns ``skipped``
    without touching the row, which is how webhook/sweeper and
    sweeper/sweeper races resolve to a single transfer.

    The destination is read **only** from the transaction's snapshot. The
    creator's current Connect account is never consulted, so a creator who
    changes accounts after checkout cannot redirect an existing sale.
    """
    now = now or datetime.utcnow()

    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == payment_transaction_id)
        .with_for_update()
        # Overwrite anything this session already loaded. A caller that read
        # the row before taking the lock — the sweeper does — would otherwise
        # decide from a copy that predates another worker's commit, and send
        # the same transfer twice.
        .populate_existing()
        .first()
    )
    if txn is None:
        return TransferOutcome(status=SKIPPED, detail="transaction not found")

    if txn.payout_model != PayoutModel.connect.value:
        return TransferOutcome(
            status=SKIPPED,
            detail=f"payout_model={txn.payout_model!r}: not Connect-routed",
        )
    if txn.provider_transfer_id:
        # Already sent. The lock means a racing attempt reads this rather
        # than sending a second transfer.
        return TransferOutcome(
            status=txn.connect_transfer_status,
            transfer_id=txn.provider_transfer_id,
            amount_cents=txn.transfer_amount_cents,
            detail="a transfer already exists for this transaction",
        )
    if txn.connect_transfer_status != ConnectTransferStatus.pending.value:
        return TransferOutcome(
            status=SKIPPED,
            detail=(
                f"connect_transfer_status={txn.connect_transfer_status!r}: "
                "only an owed transfer is sent"
            ),
        )
    if not txn.connect_destination_account_id:
        # Unreachable while the ledger's CHECK constraint holds; refusing
        # beats transferring somewhere unspecified.
        return _record_failure(
            db, txn,
            TransferTerminal(f"txn {txn.id} is Connect-routed but names no destination"),
            now=now,
        )

    try:
        amount = compute_transfer_amount(txn)
    except TransferError as exc:
        return _record_failure(db, txn, exc, now=now)

    params: dict[str, Any] = {
        "amount": amount,
        "currency": txn.currency.lower(),
        "destination": txn.connect_destination_account_id,
        "metadata": {
            "payment_transaction_id": txn.id,
            "fc_payout_model": txn.payout_model,
        },
    }
    if txn.provider_charge_id:
        # Ties the transfer to the charge that funded it: Stripe holds it
        # until those funds are available instead of refusing outright, and
        # the transfer inherits the charge's availability.
        params["source_transaction"] = txn.provider_charge_id

    api = get_stripe()
    try:
        transfer = api.Transfer.create(
            idempotency_key=idempotency_key(txn.id), **params,
        )
    except Exception as exc:  # noqa: BLE001 — classified, then re-recorded
        return _record_failure(db, txn, classify(exc), now=now)

    transfer_id = (
        transfer.get("id") if isinstance(transfer, dict)
        else getattr(transfer, "id", None)
    )
    if not transfer_id:
        return _record_failure(
            db, txn,
            TransferRetryable("Stripe returned a transfer with no id"),
            now=now,
        )

    txn.provider_transfer_id = str(transfer_id)
    txn.transfer_amount_cents = amount
    txn.transfer_attempted_at = now
    txn.transfer_sent_at = now
    txn.transfer_attempt_count = (txn.transfer_attempt_count or 0) + 1
    txn.transfer_last_error = None
    txn.connect_transfer_status = ConnectTransferStatus.sent.value
    db.commit()

    logger.info(
        "connect transfer: txn=%s sent %s %s to %s as %s",
        txn.id, amount, txn.currency, txn.connect_destination_account_id, transfer_id,
    )
    return TransferOutcome(
        status=ConnectTransferStatus.sent.value,
        transfer_id=str(transfer_id),
        amount_cents=amount,
        detail="sent",
    )
