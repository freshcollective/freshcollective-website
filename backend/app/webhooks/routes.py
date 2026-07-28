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

import json
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
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.access_pass import AccessPass, AccessPassSource, AccessPassStatus, AccessPassType
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    SpaceMembership,
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

    # Convert the Stripe SDK object to a plain dict so handlers can use .get()
    # (StripeObject does not expose a .get() method in newer stripe-python versions)
    event_object: dict = json.loads(str(event["data"]["object"]))

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event_object, db)
    elif event_type == "checkout.session.expired":
        _handle_checkout_expired(event_object, db)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event_object, db)
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"received": True}


# ---------------------------------------------------------------------------
# Standalone paid Gathering fulfilment (Stage 2B)
# ---------------------------------------------------------------------------

def _handle_gathering_ticket_completed(
    session: dict, db: Session, metadata: dict,
) -> None:
    """
    Convert a paid standalone-Gathering hold into a confirmed ticket.

    Called from `_handle_checkout_completed` when
    metadata.purchase_type == "standalone_gathering".

    All heavy lifting lives in `services.gathering_tickets.fulfil_ticket_purchase`,
    which is idempotent and holds the correct row locks. This wrapper only
    parses the Stripe payload, invokes the service, and commits.
    """
    from app.services.gathering_tickets import fulfil_ticket_purchase  # local import — avoid cycles

    session_id: str = session.get("id", "")
    payment_status: str = session.get("payment_status", "")
    if payment_status != "paid":
        logger.warning(
            "gathering ticket: payment_status=%s session=%s — skipping.",
            payment_status, session_id,
        )
        return

    txn_id = metadata.get("transaction_id", "")
    event_id = metadata.get("event_id", "")
    payer_user_id = metadata.get("payer_user_id", "")
    if not all([txn_id, event_id, payer_user_id]):
        logger.error(
            "gathering ticket: missing metadata session=%s meta=%s",
            session_id, metadata,
        )
        return

    amount_total = int(session.get("amount_total") or 0)
    currency = (session.get("currency") or "").upper()
    payment_intent_id = session.get("payment_intent") or None

    # Stripe Session doesn't expose the charge_id directly on the Session
    # object — it lives on the PaymentIntent. Leaving None here; a future
    # backfill or a PI-based webhook can populate it.
    try:
        outcome = fulfil_ticket_purchase(
            db,
            transaction_id=txn_id,
            event_id=event_id,
            payer_user_id=payer_user_id,
            stripe_amount_total=amount_total,
            stripe_currency=currency,
            stripe_payment_intent_id=payment_intent_id,
            stripe_charge_id=None,
        )
    except ValueError as exc:
        # Amount/currency mismatch, missing hold, wrong status. Log loudly
        # and re-raise so Stripe retries — but only ONCE this returns a
        # non-500, which currently we do not do. For MVP, log and return
        # to acknowledge the delivery; the mismatch is investigable via
        # the pending PaymentTransaction row.
        logger.error(
            "gathering ticket fulfilment refused: session=%s txn=%s err=%s",
            session_id, txn_id, exc,
        )
        db.rollback()
        return

    db.commit()
    if outcome.already_fulfilled:
        logger.info(
            "gathering ticket: webhook re-delivery, no-op — txn=%s booking=%s",
            txn_id, outcome.booking.id if outcome.booking else None,
        )
    else:
        logger.info(
            "gathering ticket: fulfilled txn=%s booking=%s access_pass=%s",
            txn_id, outcome.booking.id, outcome.access_pass.id,
        )
        # Notify the creator (and any moderators) that a new attendee has
        # booked — same in-app notification hook used by the free-booking
        # flow. Only fires on the first fulfilment (webhook re-delivery
        # short-circuits above via already_fulfilled=True, so duplicates
        # are impossible). Email is a graceful no-op when RESEND_API_KEY
        # is unset.
        try:
            from app.services.notification_service import (
                trigger_booking_confirmed,
                trigger_event_booking_creator,
            )
            trigger_event_booking_creator(event_id, payer_user_id)
            trigger_booking_confirmed(event_id, payer_user_id)
        except Exception as exc:  # noqa: BLE001 — never let notify failure block fulfilment
            logger.warning(
                "gathering ticket: notification failed for txn=%s: %s",
                txn_id, exc,
            )


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
    payer_user_id: str = metadata.get("payer_user_id", "")

    # ---------------------------------------------------------------
    # Purchase-type discriminator (added Stage 2B for paid Gatherings).
    # Standalone ticket purchases have their own fulfilment path that
    # does NOT create pathway entitlements or space memberships.
    # ---------------------------------------------------------------
    if metadata.get("purchase_type") == "standalone_gathering":
        _handle_gathering_ticket_completed(session, db, metadata)
        return

    pathway_id: str = metadata.get("pathway_id", "")
    space_id: str = metadata.get("space_id", "")
    payment_option_id: str = metadata.get("payment_option_id", "")
    payment_option_schedule_id: str = metadata.get("payment_option_schedule_id", "")

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

    # --- Store schedule_id on transaction (best-effort) -----------------------
    if payment_option_schedule_id and txn.payment_option_schedule_id is None:
        sched = (
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.id == payment_option_schedule_id)
            .first()
        )
        if sched:
            txn.payment_option_schedule_id = sched.id

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

    # --- Auto-join space as learner if not already a member -----------------
    existing_membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == payer_user_id,
        )
        .first()
    )
    if not existing_membership:
        membership = SpaceMembership(
            id=str(uuid4()),
            space_id=space_id,
            user_id=payer_user_id,
            role="learner",
            status="active",
            source="purchase",
            joined_at=now,
        )
        db.add(membership)
        logger.info(
            "checkout.session.completed: auto-joined user=%s as learner in space=%s",
            payer_user_id, space_id,
        )

    # --- Create AccessPass for term_pass purchases (Phase B) ----------------
    # Only create for payment types that require booking credit enforcement.
    # Legacy one_time purchases (R.E.A.L. Journey) do NOT create AccessPass.
    if payment_option:
        opt_type_val = (
            payment_option.payment_type.value
            if hasattr(payment_option.payment_type, "value")
            else str(payment_option.payment_type)
        )
        if opt_type_val in ("term_pass",):
            # Idempotency: skip if an AccessPass already exists for this transaction
            existing_pass = (
                db.query(AccessPass)
                .filter(AccessPass.payment_transaction_id == txn.id)
                .first()
            )
            if existing_pass is None:
                valid_from_dt = (
                    _dt.combine(payment_option.term_start_date, _dt.min.time())
                    if payment_option.term_start_date
                    else now
                )
                access_pass = AccessPass(
                    id=str(uuid4()),
                    user_id=payer_user_id,
                    space_id=space_id,
                    payment_transaction_id=txn.id,
                    payment_option_id=payment_option.id,
                    payment_option_schedule_id=payment_option_schedule_id or None,
                    pass_type=AccessPassType.term_pass,
                    status=AccessPassStatus.active,
                    valid_from=valid_from_dt,
                    valid_until=term_ends_at,
                    total_credits=payment_option.total_sessions,
                    used_credits=0,
                    credits_per_week=payment_option.sessions_per_week,
                    eligible_pathway_id=entitlement_pathway_id,
                    grants_pathway_id=entitlement_pathway_id,
                    pathway_entitlement_id=ent.id,
                    source=AccessPassSource.one_time_purchase,
                    created_at=now,
                    updated_at=now,
                )
                db.add(access_pass)
                logger.info(
                    "checkout.session.completed: created AccessPass %s type=term_pass "
                    "credits=%s credits_per_week=%s valid=%s→%s user=%s",
                    access_pass.id,
                    payment_option.total_sessions,
                    payment_option.sessions_per_week,
                    valid_from_dt,
                    term_ends_at,
                    payer_user_id,
                )
            else:
                logger.info(
                    "checkout.session.completed: AccessPass already exists for txn=%s — skipping",
                    txn.id,
                )

    db.commit()

    logger.info(
        "checkout.session.completed: SUCCESS txn=%s entitlement=%s user=%s pathway=%s",
        txn.id, ent.id, payer_user_id, pathway_id,
    )


def _handle_checkout_expired(session: dict, db: Session) -> None:
    """
    checkout.session.expired — member did not complete checkout within the session window.
    Cancel the pending PaymentTransaction if it still exists and is still pending.

    For standalone-gathering purchases the hold row on `event_bookings`
    must ALSO be cancelled so the seat is released for someone else.
    Delegates to `services.gathering_tickets.release_hold_for_transaction`
    which handles both txn + booking atomically and is idempotent.
    """
    session_id: str = session.get("id", "")
    txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_checkout_session_id == session_id)
        .with_for_update()
        .first()
    )
    if txn is None or txn.status != PaymentTransactionStatus.pending:
        return

    if txn.transaction_type == PaymentTransactionType.gathering_ticket_purchase:
        from app.services.gathering_tickets import release_hold_for_transaction  # local import — avoid cycles
        release_hold_for_transaction(
            db,
            transaction_id=txn.id,
            final_status=PaymentTransactionStatus.cancelled,
            reason="checkout_expired",
        )
        db.commit()
        logger.info("checkout.session.expired: released gathering hold txn=%s session=%s",
                    txn.id, session_id)
        return

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
        # Standalone gathering path: also release the hold row.
        if txn.transaction_type == PaymentTransactionType.gathering_ticket_purchase:
            from app.services.gathering_tickets import release_hold_for_transaction
            txn.provider_payment_intent_id = pi_id
            release_hold_for_transaction(
                db,
                transaction_id=txn.id,
                final_status=PaymentTransactionStatus.failed,
                reason="payment_failed",
            )
            db.commit()
            logger.info("payment_intent.payment_failed: released gathering hold txn=%s pi=%s",
                        txn.id, pi_id)
            return

        txn.status = PaymentTransactionStatus.failed
        txn.payout_status = PayoutStatus.not_applicable
        txn.provider_payment_intent_id = pi_id
        txn.updated_at = datetime.utcnow()
        db.commit()
        logger.info("payment_intent.payment_failed: failed txn=%s pi=%s", txn.id, pi_id)
    elif txn is None:
        logger.warning("payment_intent.payment_failed: no txn found for pi=%s meta_txn=%s", pi_id, txn_id_from_meta)
