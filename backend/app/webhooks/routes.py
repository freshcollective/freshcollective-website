"""
POST /api/webhooks/stripe — Stripe webhook receiver.

IMPORTANT: This endpoint must read the raw request body BEFORE any JSON
parsing, otherwise Stripe signature verification will fail.

Idempotency strategy:
  - Transaction rows are locked with SELECT FOR UPDATE before any update,
    preventing concurrent webhook deliveries from racing into duplicate processing.
  - Status checks after the lock ensure idempotent handling of re-delivered events.
  - A partial unique index on provider_checkout_session_id prevents duplicate rows.

Handled events:
  checkout.session.completed    → grant access, update PaymentTransaction
  checkout.session.expired      → mark PaymentTransaction cancelled
  payment_intent.payment_failed → mark PaymentTransaction failed

TODO (Phase 2+):
  charge.refunded               → revoke entitlement, update payout_status
  charge.dispute.created        → hold payout
  invoice.payment_succeeded     → creator subscription billing (Phase 3)
  invoice.payment_failed        → creator subscription past_due (Phase 3)
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
from app.models.payment_option import PaymentOption
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

    Idempotency: rows are locked with SELECT FOR UPDATE before mutation.
    Re-delivered events that arrive after status==succeeded are skipped cleanly.
    """
    session_id: str = session.get("id", "")
    payment_status: str = session.get("payment_status", "")
    payment_intent_id: str | None = session.get("payment_intent")
    metadata: dict = session.get("metadata") or {}

    transaction_id: str = metadata.get("transaction_id", "")
    pathway_id: str = metadata.get("pathway_id", "")
    payer_user_id: str = metadata.get("payer_user_id", "")
    space_id: str = metadata.get("space_id", "")
    payment_option_id: str = metadata.get("payment_option_id", "")

    if not all([transaction_id, pathway_id, payer_user_id, space_id]):
        logger.error(
            "checkout.session.completed missing metadata: session=%s meta=%s",
            session_id, metadata,
        )
        return

    if payment_status != "paid":
        logger.warning(
            "checkout.session.completed payment_status=%s session=%s — skipping.",
            payment_status, session_id,
        )
        return

    # --- Lock transaction row to prevent concurrent duplicate processing -----
    # with_for_update() issues SELECT ... FOR UPDATE, serialising concurrent
    # webhook deliveries for the same session. The second delivery will wait
    # for the first to commit, then see status==succeeded and return early.
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .with_for_update()
        .first()
    )
    if txn is None:
        # Fallback: look up by transaction_id from metadata (handles edge case
        # where session_id was not stored before server restart)
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == transaction_id)
            .with_for_update()
            .first()
        )

    if txn is None:
        logger.error(
            "checkout.session.completed: no PaymentTransaction found session=%s txn_id=%s",
            session_id, transaction_id,
        )
        return

    # --- Idempotency: already processed? ------------------------------------
    if txn.status == PaymentTransactionStatus.succeeded:
        logger.info(
            "checkout.session.completed: already processed session=%s txn=%s — skipping.",
            session_id, txn.id,
        )
        return

    # --- Retrieve Stripe processing fee (best-effort, informational only) ---
    # FC absorbs the Stripe fee — it is NOT deducted from creator net.
    # Stored for reporting purposes only.
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
            logger.warning("Could not retrieve Stripe processing fee: %s", exc)

    # --- Update transaction to succeeded ------------------------------------
    now = datetime.utcnow()
    txn.status = PaymentTransactionStatus.succeeded
    txn.provider_checkout_session_id = session_id   # ensure it's set (fallback path)
    txn.provider_payment_intent_id = payment_intent_id
    txn.processing_fee_cents = processing_fee_cents
    txn.payout_status = PayoutStatus.pending
    txn.updated_at = now

    # --- Resolve payment option for term_pass expiry / grants_pathway_id -----
    payment_option: PaymentOption | None = None
    if payment_option_id:
        payment_option = db.query(PaymentOption).filter(PaymentOption.id == payment_option_id).first()
        if not payment_option:
            logger.warning(
                "checkout.session.completed: payment_option %s not found — proceeding without option",
                payment_option_id,
            )

    # Entitlement targets the grants_pathway_id if set, otherwise pathway_id
    entitlement_pathway_id = (
        payment_option.grants_pathway_id
        if payment_option and payment_option.grants_pathway_id
        else pathway_id
    )

    # For term_pass options, set ends_at to term_end_date (as a datetime)
    from datetime import datetime as _dt
    term_ends_at: _dt | None = None
    if payment_option and payment_option.term_end_date:
        opt_type = (
            payment_option.payment_type.value
            if hasattr(payment_option.payment_type, "value")
            else str(payment_option.payment_type)
        )
        if opt_type == "term_pass":
            term_ends_at = _dt.combine(payment_option.term_end_date, _dt.min.time())

    # --- Create or reactivate PathwayEntitlement ----------------------------
    pathway = db.query(Pathway).filter(Pathway.id == entitlement_pathway_id).first()
    if not pathway:
        logger.error(
            "checkout.session.completed: pathway %s not found — txn updated but no entitlement.",
            entitlement_pathway_id,
        )
        db.commit()
        return

    existing_ent = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == payer_user_id,
            PathwayEntitlement.pathway_id == entitlement_pathway_id,
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .first()
    )

    if existing_ent and existing_ent.status == EntitlementStatus.active:
        # Already active (e.g. re-delivered after first processing) — update Stripe fields only
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        existing_ent.updated_at = now
        ent = existing_ent
        logger.info(
            "checkout.session.completed: entitlement already active user=%s pathway=%s",
            payer_user_id, entitlement_pathway_id,
        )
    elif existing_ent:
        # Reactivate a revoked/expired/cancelled entitlement
        existing_ent.status = EntitlementStatus.active
        existing_ent.source = EntitlementSource.one_time_purchase
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        existing_ent.revoked_by_user_id = None
        existing_ent.revoked_at = None
        existing_ent.ends_at = term_ends_at
        existing_ent.updated_at = now
        ent = existing_ent
        logger.info(
            "checkout.session.completed: reactivated entitlement user=%s pathway=%s",
            payer_user_id, entitlement_pathway_id,
        )
    else:
        ent = PathwayEntitlement(
            id=str(uuid4()),
            user_id=payer_user_id,
            space_id=space_id,
            pathway_id=entitlement_pathway_id,
            source=EntitlementSource.one_time_purchase,
            status=EntitlementStatus.active,
            starts_at=now,
            ends_at=term_ends_at,
            stripe_checkout_session_id=session_id,
            stripe_payment_intent_id=payment_intent_id,
            created_at=now,
            updated_at=now,
        )
        db.add(ent)
        db.flush()  # populate ent.id so we can reference it below
        logger.info(
            "checkout.session.completed: created entitlement %s user=%s pathway=%s ends_at=%s",
            ent.id, payer_user_id, entitlement_pathway_id, term_ends_at,
        )

    txn.entitlement_id = ent.id
    db.commit()

    logger.info(
        "checkout.session.completed: SUCCESS txn=%s entitlement=%s user=%s pathway=%s",
        txn.id, ent.id, payer_user_id, pathway_id,
    )


def _handle_checkout_expired(session: dict, db: Session) -> None:
    """
    checkout.session.expired — member did not complete checkout within the session window.
    Cancel the pending PaymentTransaction if it still exists and is still pending.
    """
    session_id: str = session.get("id", "")
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .with_for_update()
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

    Lookup strategy:
      1. transaction_id from payment intent metadata (set via payment_intent_data at session creation)
      2. provider_payment_intent_id (set once checkout.session.completed fires — usually not needed here)

    Note: For Stripe Checkout, this event fires when the customer's payment attempt
    fails mid-session (e.g. card declined). Stripe will let them retry within the
    same session. The session only fully fails once it expires, at which point
    checkout.session.expired fires. This handler is a belt-and-suspenders cleanup.
    """
    pi_id: str = payment_intent.get("id", "")
    pi_metadata: dict = payment_intent.get("metadata") or {}
    txn_id_from_meta: str = pi_metadata.get("transaction_id", "")

    txn = None

    # Primary: look up by transaction_id embedded in PI metadata
    if txn_id_from_meta:
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.id == txn_id_from_meta)
            .with_for_update()
            .first()
        )

    # Fallback: look up by PI ID (only works if checkout.session.completed already ran,
    # which shouldn't happen here, but covers edge cases)
    if txn is None and pi_id:
        txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_payment_intent_id == pi_id)
            .with_for_update()
            .first()
        )

    if txn and txn.status == PaymentTransactionStatus.pending:
        txn.status = PaymentTransactionStatus.failed
        txn.payout_status = PayoutStatus.not_applicable
        txn.provider_payment_intent_id = pi_id
        txn.updated_at = datetime.utcnow()
        db.commit()
        logger.info("payment_intent.payment_failed: failed txn=%s pi=%s", txn.id, pi_id)
    elif txn is None:
        logger.warning("payment_intent.payment_failed: no txn found for pi=%s meta_txn=%s", pi_id, txn_id_from_meta)
