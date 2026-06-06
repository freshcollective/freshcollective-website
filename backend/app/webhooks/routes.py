"""
POST /api/webhooks/stripe — Stripe webhook receiver.

IMPORTANT: This endpoint must read the raw request body BEFORE any JSON
parsing, otherwise Stripe signature verification will fail.

Handled events:
  checkout.session.completed  → grant access, update PaymentTransaction
  checkout.session.expired    → mark PaymentTransaction cancelled
  payment_intent.payment_failed → mark PaymentTransaction failed

TODO (Phase 2+):
  charge.refunded             → revoke entitlement, update payout_status
  charge.dispute.created      → hold payout
  invoice.payment_succeeded   → creator subscription billing (Phase 3)
  invoice.payment_failed      → creator subscription past_due (Phase 3)
"""

import logging
from datetime import datetime
from uuid import uuid4

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """
    Receive and process Stripe webhook events.

    Stripe delivers events as signed POST requests. We must verify the
    signature using the raw body (before any parsing) and the webhook secret.
    """
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Stripe is not configured.")

    stripe.api_key = settings.stripe_secret_key

    # Read raw body — must happen before any JSON parsing
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
        )
    except stripe.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed.")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")
    except Exception as exc:
        logger.error("Stripe webhook parse error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook parse error.")

    event_type: str = event["type"]
    logger.info("Stripe webhook received: %s id=%s", event_type, event["id"])

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"], db)
    elif event_type == "checkout.session.expired":
        _handle_checkout_expired(event["data"]["object"], db)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event["data"]["object"], db)
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"received": True}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_checkout_completed(session: dict, db: Session) -> None:
    """
    checkout.session.completed — payment confirmed by Stripe.

    1. Find the pending PaymentTransaction via provider_checkout_session_id.
    2. Idempotency: skip if already succeeded.
    3. Confirm payment_status == 'paid'.
    4. Update transaction to succeeded, store Stripe IDs.
    5. Optionally capture Stripe processing fee from balance_transaction.
    6. Create or reactivate PathwayEntitlement.
    7. Link entitlement to transaction.
    """
    session_id: str = session.get("id", "")
    payment_status: str = session.get("payment_status", "")
    payment_intent_id: str | None = session.get("payment_intent")
    metadata: dict = session.get("metadata") or {}

    transaction_id: str = metadata.get("transaction_id", "")
    pathway_id: str = metadata.get("pathway_id", "")
    payer_user_id: str = metadata.get("payer_user_id", "")
    space_id: str = metadata.get("space_id", "")

    if not all([transaction_id, pathway_id, payer_user_id, space_id]):
        logger.error(
            "checkout.session.completed missing metadata: session=%s meta=%s",
            session_id, metadata,
        )
        return

    if payment_status != "paid":
        logger.warning(
            "checkout.session.completed with payment_status=%s for session=%s — skipping.",
            payment_status, session_id,
        )
        return

    # --- Find transaction via session ID (fast path) or metadata (fallback) --
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .first()
    )
    if txn is None:
        # Fallback: look up by ID from metadata
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.id == transaction_id).first()

    if txn is None:
        logger.error(
            "checkout.session.completed: no PaymentTransaction found for session=%s txn_id=%s",
            session_id, transaction_id,
        )
        return

    # --- Idempotency: already processed? ------------------------------------
    if txn.status == PaymentTransactionStatus.succeeded:
        logger.info(
            "checkout.session.completed: already processed for session=%s txn=%s — skipping.",
            session_id, txn.id,
        )
        return

    # --- Retrieve Stripe processing fee (best-effort) -----------------------
    processing_fee_cents: int | None = None
    if payment_intent_id:
        try:
            pi = stripe.PaymentIntent.retrieve(
                payment_intent_id,
                expand=["latest_charge.balance_transaction"],
            )
            charge = getattr(pi, "latest_charge", None)
            if charge:
                bt = getattr(charge, "balance_transaction", None)
                if bt and hasattr(bt, "fee"):
                    processing_fee_cents = int(bt.fee)
        except Exception as exc:
            logger.warning("Could not retrieve processing fee from Stripe: %s", exc)

    # --- Update transaction to succeeded ------------------------------------
    now = datetime.utcnow()
    txn.status = PaymentTransactionStatus.succeeded
    txn.provider_checkout_session_id = session_id
    txn.provider_payment_intent_id = payment_intent_id
    txn.processing_fee_cents = processing_fee_cents
    txn.payout_status = PayoutStatus.pending
    txn.updated_at = now

    # --- Create or reactivate PathwayEntitlement ----------------------------
    pathway = db.query(Pathway).filter(Pathway.id == pathway_id).first()
    if not pathway:
        logger.error(
            "checkout.session.completed: pathway %s not found — transaction updated but no entitlement created.",
            pathway_id,
        )
        db.commit()
        return

    existing_ent = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == payer_user_id,
            PathwayEntitlement.pathway_id == pathway_id,
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .first()
    )

    if existing_ent and existing_ent.status == EntitlementStatus.active:
        # Already active — update Stripe fields for completeness
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        existing_ent.updated_at = now
        ent = existing_ent
        logger.info(
            "checkout.session.completed: entitlement already active for user=%s pathway=%s",
            payer_user_id, pathway_id,
        )
    elif existing_ent:
        # Reactivate an inactive/revoked entitlement
        existing_ent.status = EntitlementStatus.active
        existing_ent.source = EntitlementSource.one_time_purchase
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        existing_ent.revoked_by_user_id = None
        existing_ent.revoked_at = None
        existing_ent.ends_at = None
        existing_ent.updated_at = now
        ent = existing_ent
        logger.info(
            "checkout.session.completed: reactivated entitlement for user=%s pathway=%s",
            payer_user_id, pathway_id,
        )
    else:
        # New entitlement
        ent = PathwayEntitlement(
            id=str(uuid4()),
            user_id=payer_user_id,
            space_id=space_id,
            pathway_id=pathway_id,
            source=EntitlementSource.one_time_purchase,
            status=EntitlementStatus.active,
            starts_at=now,
            stripe_checkout_session_id=session_id,
            stripe_payment_intent_id=payment_intent_id,
            created_at=now,
            updated_at=now,
        )
        db.add(ent)
        db.flush()
        logger.info(
            "checkout.session.completed: created entitlement %s for user=%s pathway=%s",
            ent.id, payer_user_id, pathway_id,
        )

    txn.entitlement_id = ent.id
    db.commit()

    logger.info(
        "checkout.session.completed: SUCCESS txn=%s entitlement=%s user=%s pathway=%s",
        txn.id, ent.id, payer_user_id, pathway_id,
    )


def _handle_checkout_expired(session: dict, db: Session) -> None:
    """
    checkout.session.expired — member did not complete checkout.
    Mark the pending PaymentTransaction as cancelled if it still exists.
    """
    session_id: str = session.get("id", "")
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .first()
    )
    if txn and txn.status == PaymentTransactionStatus.pending:
        txn.status = PaymentTransactionStatus.cancelled
        txn.payout_status = PayoutStatus.not_applicable
        txn.updated_at = datetime.utcnow()
        db.commit()
        logger.info("checkout.session.expired: cancelled txn=%s session=%s", txn.id, session_id)


def _handle_payment_failed(payment_intent: dict, db: Session) -> None:
    """
    payment_intent.payment_failed — Stripe could not collect payment.
    Mark the associated PaymentTransaction as failed.
    """
    pi_id: str = payment_intent.get("id", "")
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_payment_intent_id == pi_id)
        .first()
    )
    if txn and txn.status == PaymentTransactionStatus.pending:
        txn.status = PaymentTransactionStatus.failed
        txn.payout_status = PayoutStatus.not_applicable
        txn.updated_at = datetime.utcnow()
        db.commit()
        logger.info("payment_intent.payment_failed: failed txn=%s pi=%s", txn.id, pi_id)
