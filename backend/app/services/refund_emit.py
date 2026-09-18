"""Comms emit helper for confirmed refunds.

Called from ``app/webhooks/refund_handlers.py`` on ``charge.refunded``,
which Stripe fires only after a refund has actually succeeded. A refund
that is merely *requested* (a ``RefundOperation`` in ``in_flight`` or
``accepted``) never reaches here, so no member is ever told money is on
its way when it is not.

Only a genuine increase in the charge's cumulative refunded amount
emits. Same-value re-delivery and out-of-order events produce no event,
which is what keeps a duplicate webhook from producing a second email.

Deliberately member-facing only: platform fee, creator net and any
payout accounting stay out of the payload entirely.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction, PaymentTransactionStatus
from app.models.platform import Pathway, Space
from app.models.user import User

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent


logger = logging.getLogger(__name__)


def _safe_emit(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A comms failure must never break refund ledger accounting."""
    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> "CommunicationEvent | None":
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "refund_emit: %s failed — the refund ledger is unaffected, "
                "no email will be sent for this refund",
                fn.__name__,
            )
            return None
    return _wrapped


def _first_name(user: User | None) -> str:
    if user is None or not user.name:
        return ""
    return user.name.strip().split(" ", 1)[0]


def _context_labels(db: Session, txn: PaymentTransaction) -> tuple[str, str]:
    """(collective_name, item_name) — either may be empty.

    Best-effort: a transaction is not guaranteed to carry either
    reference, and the template copes with both being absent.
    """
    collective_name = ""
    item_name = ""
    if txn.space_id:
        space = db.query(Space).filter(Space.id == txn.space_id).first()
        if space is not None:
            collective_name = space.name or ""
    if txn.pathway_id:
        pathway = db.query(Pathway).filter(Pathway.id == txn.pathway_id).first()
        if pathway is not None:
            item_name = pathway.title or ""
    return collective_name, item_name


@_safe_emit
def emit_purchase_refunded(
    db: Session,
    *,
    txn: PaymentTransaction,
    refund_amount_cents: int,
    cumulative_refunded_cents: int,
) -> "CommunicationEvent | None":
    """Emit ``purchase.refunded`` for a refund Stripe has settled.

    ``refund_amount_cents`` is the increment this event represents —
    what the member actually sees land back on their card — not the
    running total.
    """
    if not txn.payer_user_id:
        logger.info(
            "refund_emit: txn=%s has no payer_user_id — nobody to notify",
            txn.id,
        )
        return None
    if refund_amount_cents <= 0:
        return None

    from app.comms import Source, emit as comms_emit

    user = db.query(User).filter(User.id == txn.payer_user_id).first()
    collective_name, item_name = _context_labels(db, txn)

    payload = {
        "first_name":       _first_name(user),
        "amount_cents":     refund_amount_cents,
        "currency":         (txn.currency or "").upper(),
        "collective_name":  collective_name,
        "item_name":        item_name,
        # A partial refund reads differently from a full one.
        "is_full_refund":   txn.status == PaymentTransactionStatus.refunded,
    }
    return comms_emit(
        db,
        event_type="purchase.refunded",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=txn.payer_user_id,
        subject_type="payment_transaction",
        subject_id=txn.id,
        context={"payment_transaction_id": txn.id},
        payload=payload,
        # Keyed on the cumulative total this event brought the charge to,
        # so a genuine second partial refund emits again while a replay
        # of the same event does not.
        dedupe_key=f"refund:{txn.id}:{cumulative_refunded_cents}",
    )


__all__ = ["emit_purchase_refunded"]
