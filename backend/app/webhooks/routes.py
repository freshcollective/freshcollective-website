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

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.services.purchase_fulfilment import (
    FulfilmentStatus,
    apply_intent,
    resolve_intent_for_option,
    validate_intent,
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

    # ``event`` is a Stripe SDK ``StripeObject`` (from
    # ``stripe.Webhook.construct_event``). StripeObject supports
    # dict-style subscript access (``event["type"]``) but does NOT
    # expose ``.get()``. Every field read below therefore uses ``[]``
    # — the same access pattern the outer dispatcher already uses
    # for ``event["type"]`` / ``event["id"]``. ``livemode`` is a
    # required top-level field on every Stripe event per the API
    # contract, so subscript access is safe without a default.
    event_livemode = bool(event["livemode"])

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(
            event_object, db,
            event_livemode=event_livemode,
        )
    elif event_type == "checkout.session.expired":
        _handle_checkout_expired(event_object, db)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event_object, db)
    elif event_type == "invoice.payment_succeeded":
        # FIP2 — first-invoice fulfilment for finite payment plans.
        # FIP3 — later-instalment recording, recovery from
        # payment_problem, completion transition; all inside the
        # same handler which dispatches on plan.status.
        from app.webhooks.finite_plan_handlers import (
            handle_invoice_payment_succeeded,
        )
        handle_invoice_payment_succeeded(
            event_object, db,
            provider_event_id=event["id"],
            event_livemode=event_livemode,
        )
    elif event_type == "invoice.payment_failed":
        # FIP3 — later-instalment failure opens the 7-day grace
        # window. Payment_intent-level failures on the pay-in-full
        # path continue to be handled by the legacy
        # ``payment_intent.payment_failed`` branch above.
        from app.webhooks.finite_plan_handlers import (
            handle_invoice_payment_failed,
        )
        handle_invoice_payment_failed(
            event_object, db,
            provider_event_id=event["id"],
            event_livemode=event_livemode,
        )
    elif event_type == "customer.subscription.deleted":
        # FIP3 — reconcile plan state with Stripe subscription end.
        # Distinguishes normal finite end (installments_paid ==
        # expected → completed) from abnormal end (paid < expected
        # → failed + suspend access, source-aware).
        from app.webhooks.finite_plan_handlers import (
            handle_subscription_deleted,
        )
        handle_subscription_deleted(
            event_object, db,
            provider_event_id=event["id"],
            event_livemode=event_livemode,
        )
    elif event_type == "subscription_schedule.completed":
        # FIP3 — belt-and-braces companion to subscription.deleted.
        from app.webhooks.finite_plan_handlers import (
            handle_schedule_completed,
        )
        handle_schedule_completed(
            event_object, db,
            provider_event_id=event["id"],
            event_livemode=event_livemode,
        )
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"received": True}


# ---------------------------------------------------------------------------
# PurchaseIntent-backed fulfilment (Stage 3+)
# ---------------------------------------------------------------------------

def _handle_purchase_intent_completed(
    session: dict, db: Session, metadata: dict,
) -> None:
    """
    checkout.session.completed for a Session created from a
    PurchaseIntent (metadata carries ``purchase_intent_id``).

    Responsibilities are deliberately narrow:

      1. Locate the intent by id (with row lock).
      2. Idempotency: skip if already ``consumed`` / ``refunded``,
         and skip mark-paid work if already ``paid``.
      3. On first delivery, transition ``pending → paid``, snapshot
         Stripe's subscription/customer IDs, and record the
         customer_details.email as ``claim_email``.
      4. If ``payer_user_id`` is set, immediately claim the intent
         for that user via the shared claim orchestrator. Otherwise
         leave the intent in ``paid`` for the frontend claim flow.

    All business logic lives in ``app.purchases.claim`` and
    ``app.creator.plan_activation``. This handler is a dispatcher.
    """
    from app.models.purchase_intent import (
        PurchaseIntent,
        PurchaseIntentKind,
        PurchaseIntentStatus,
    )
    from app.models.user import User
    from app.purchases.claim import ClaimError, claim_intent

    intent_id = metadata.get("purchase_intent_id", "")
    if not intent_id:
        logger.error(
            "purchase_intent webhook: missing purchase_intent_id in metadata "
            "session=%s", session.get("id"),
        )
        return

    intent = (
        db.query(PurchaseIntent)
        .filter(PurchaseIntent.id == intent_id)
        .with_for_update()
        .one_or_none()
    )
    if intent is None:
        # Same policy as the pathway path — event is already
        # dispatched by Stripe; log and return 200 so Stripe stops
        # retrying (retries won't help find a missing row).
        logger.error(
            "purchase_intent webhook: intent %s not found "
            "(session=%s)", intent_id, session.get("id"),
        )
        return

    # Idempotency: terminal states are safe no-ops.
    if intent.status in (
        PurchaseIntentStatus.consumed,
        PurchaseIntentStatus.refunded,
    ):
        logger.info(
            "purchase_intent webhook: intent %s already %s — skipping.",
            intent.id, intent.status.value,
        )
        return

    # Payment must actually have been made. Stripe's payment_status
    # on subscription-mode sessions is 'paid' on success and 'unpaid'
    # otherwise; refuse to progress if we somehow got the wrong event.
    payment_status = session.get("payment_status", "")
    if payment_status not in ("paid", "no_payment_required"):
        logger.warning(
            "purchase_intent webhook: payment_status=%s intent=%s "
            "session=%s — skipping.",
            payment_status, intent.id, session.get("id"),
        )
        return

    # First-time delivery: mark paid + snapshot provider IDs.
    if intent.status == PurchaseIntentStatus.pending:
        intent.status = PurchaseIntentStatus.paid
        intent.paid_at = datetime.utcnow()
        intent.provider_subscription_id = session.get("subscription")
        intent.provider_customer_id = session.get("customer")
        customer_details = session.get("customer_details") or {}
        email = (customer_details.get("email") or "").strip().lower()
        if email:
            intent.claim_email = email
        db.flush()

    # If the payer is a known Fresh Collective user, activate now.
    # Otherwise leave the intent in ``paid`` — the visitor's return
    # to /checkout/complete drives activation via the claim endpoint.
    if intent.payer_user_id:
        user = (
            db.query(User)
            .filter(User.id == intent.payer_user_id)
            .one_or_none()
        )
        if user is None:
            logger.error(
                "purchase_intent webhook: payer_user_id %s for intent "
                "%s no longer exists — leaving intent paid for claim.",
                intent.payer_user_id, intent.id,
            )
            # Persist the mark-paid so the frontend claim path can
            # still recover the purchase.
            db.commit()
            return
        try:
            claim_result = claim_intent(db, intent, user)
        except ClaimError as exc:
            # Deliberate: activation failure must NOT swallow the
            # paid status. Roll back this delivery's writes so Stripe
            # retries and the next delivery finds the intent in its
            # actual state (either still paid, if the mark-paid was
            # from a prior delivery, or still pending here).
            logger.exception(
                "purchase_intent webhook: auto-claim failed for intent "
                "%s user=%s: %s", intent.id, user.id, exc,
            )
            db.rollback()
            raise
    else:
        logger.info(
            "purchase_intent webhook: intent %s marked paid; awaiting "
            "visitor claim (no payer_user_id).", intent.id,
        )
        claim_result = None

    # Persist everything: the mark-paid transition and, when the payer
    # was known, the full activation (subscription + role + WB + audit
    # + consumption). Without this commit the SQLAlchemy session
    # rolls back on request end and none of the above survives.
    db.commit()

    # R2B: route creator.plan_activated (if the auto-claim produced
    # one) AFTER commit so ``_route_event_bg``'s fresh session sees
    # the committed event. No BackgroundTasks in the webhook path —
    # schedule sync; ``_route_event_bg`` runs inline before returning
    # to Stripe, which mirrors the R2A pattern for forgot-password.
    if claim_result is not None and claim_result.activation_event is not None:
        from app.comms.rollout import schedule_routing_if_needed
        schedule_routing_if_needed(
            None, claim_result.activation_event, "creator.plan_activated",
        )


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

def _handle_checkout_completed(
    session: dict, db: Session, *, event_livemode: bool = False,
) -> None:
    """
    checkout.session.completed — payment confirmed by Stripe.

    Idempotency: rows are locked with SELECT FOR UPDATE before mutation.
    Re-delivered events that arrive after status==succeeded are skipped cleanly.

    ``event_livemode`` is threaded down to the FIP2 finite-plan setup
    handler so it can reject a mode-mismatched event before touching
    the plan (test event on a live plan or vice versa). The pay-in-
    full path does not currently mode-check, matching pre-FIP2
    behaviour.
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

    # ---------------------------------------------------------------
    # FIP2 — finite payment plan setup completion. Session was
    # created via ``services/finite_plan_orchestration.py`` with
    # ``mode='setup'`` and metadata carrying ``purchase_plan_id``.
    # Handler creates the Stripe SubscriptionSchedule + persists
    # provider ids on the plan; DOES NOT grant access. Access is
    # granted by the FIRST ``invoice.payment_succeeded`` event.
    # ---------------------------------------------------------------
    if metadata.get("purchase_type") == "finite_plan_setup":
        from app.webhooks.finite_plan_handlers import (
            handle_finite_plan_setup_completed,
        )
        # ``event_livemode`` came in from the top-level dispatcher —
        # the finite-plan handler enforces plan.stripe_mode alignment
        # before persisting any Stripe provider ids.
        handle_finite_plan_setup_completed(
            session, db, metadata,
            event_livemode=event_livemode,
        )
        return

    # ---------------------------------------------------------------
    # FIP4B2 — finite payment plan REPAIR setup completion. Session
    # was created via ``services/finite_plan_repair.create_repair_setup_session``
    # (invoked by ``POST /api/finite-plan/repair-session``) with
    # ``mode='setup'`` bound to the plan's existing Customer and
    # metadata carrying ``purchase_plan_id`` + ``payer_user_id``.
    # Handler swaps the default PaymentMethod on the Customer +
    # SubscriptionSchedule + Subscription (all three surfaces),
    # then retries the plan's overdue invoice. Does NOT create a
    # new SubscriptionSchedule, does NOT create a new PurchasePlan,
    # does NOT grant access. Access changes flow through the
    # existing FIP3 ``invoice.payment_succeeded`` pipeline.
    # ---------------------------------------------------------------
    if metadata.get("purchase_type") == "finite_plan_repair":
        from app.webhooks.finite_plan_handlers import (
            handle_finite_plan_repair_completed,
        )
        handle_finite_plan_repair_completed(
            session, db, metadata,
            event_livemode=event_livemode,
        )
        return

    # ---------------------------------------------------------------
    # PurchaseIntent-backed sessions (Stage 3+). The presence of
    # ``purchase_intent_id`` in metadata means the Session was
    # created via ``app.purchases.checkout``; dispatch to the
    # dedicated handler which routes further by intent.kind.
    # ---------------------------------------------------------------
    if metadata.get("purchase_intent_id"):
        _handle_purchase_intent_completed(session, db, metadata)
        return

    pathway_id: str = metadata.get("pathway_id", "")
    space_id: str = metadata.get("space_id", "")
    payment_option_id: str = metadata.get("payment_option_id", "")
    payment_option_schedule_id: str = metadata.get("payment_option_schedule_id", "")

    # ``pathway_id`` in metadata is a *legacy* hint used by
    # ``/api/checkout/pathway`` sessions. Only truly required for
    # the option-less pre-PaymentOptions purchase path — with any
    # ``payment_option_id`` on the Session the resolver derives
    # everything it needs from the option's grants (or legacy
    # shadow columns, when the option isn't grant-ready). The
    # unified checkout endpoint (B4B) writes no ``pathway_id``
    # metadata for option-based purchases.
    required_meta = [transaction_id, payer_user_id, space_id]
    if not payment_option_id:
        required_meta.append(pathway_id)
    if not all(required_meta):
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

    # --- Idempotency: already applied? --------------------------------------
    # A txn whose fulfilment already committed (``fulfilment_status
    # == applied``) is a re-delivery we skip entirely. A txn whose
    # payment succeeded but fulfilment is ``blocked`` (missing FK
    # target, resolver fatal_error) is deliberately allowed to fall
    # through — Stripe re-delivery is the natural retry once the
    # underlying data is fixed.
    if txn.fulfilment_status == PaymentFulfilmentStatus.applied:
        logger.info(
            "checkout.session.completed: already applied session=%s txn=%s — skipping.",
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

    # ── Delegate fulfilment to the shared service. B4A: source of
    #    truth is now ``PaymentOption.grants`` when the option has
    #    any grant rows; otherwise the legacy resolver runs (with a
    #    structured warning) as transition-period compatibility.
    #    The atomicity contract (resolve → validate → apply) is
    #    the same regardless of which resolver picks the intent. ──
    resolution = resolve_intent_for_option(
        db,
        payment_option=payment_option,
        metadata_pathway_id=pathway_id or None,
        now=now,
    )

    # ── Resolver-side hard error (e.g. series-attached option
    # pointing at a missing Series row). Payment succeeded, so the
    # txn's status update commits — but we mark
    # ``fulfilment_status='blocked'`` so operational tooling can
    # surface the state and a subsequent Stripe re-delivery (after
    # the data is fixed) can retry via the applied-vs-blocked
    # idempotency check above. ──
    if resolution.fatal_error:
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        logger.error(
            "checkout.session.completed: blocked session=%s txn=%s — %s",
            session_id, txn.id, resolution.fatal_error,
        )
        return

    # ── Pre-write validation. Every FK target the intent references
    # is checked against the DB *before any writes happen*. A
    # missing target means the whole bundle is blocked; the
    # applier is never called with a bad intent. ──
    validation = validate_intent(db, resolution.intent)
    if not validation.ok:
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        logger.error(
            "checkout.session.completed: blocked session=%s txn=%s — %s",
            session_id, txn.id, "; ".join(validation.errors),
        )
        return

    # ── Apply. All-or-nothing: any raise during apply propagates
    # out (rolling back the whole in-memory session, including the
    # txn.status='succeeded' update above); Stripe re-delivers on
    # 5xx and we get another attempt. On success we set
    # ``fulfilment_status='applied'`` and commit the whole bundle
    # in one shot. ──
    try:
        result = apply_intent(
            db,
            intent=resolution.intent,
            txn=txn,
            payer_user_id=payer_user_id,
            space_id=space_id,
            payment_option_id=payment_option.id if payment_option is not None else None,
            payment_option_schedule_id=payment_option_schedule_id or None,
            session_id=session_id,
            payment_intent_id=payment_intent_id,
            now=now,
        )
        txn.fulfilment_status = PaymentFulfilmentStatus.applied
        db.commit()
    except Exception:
        # Unexpected DB error during apply → roll back the whole
        # in-memory session (including the txn status/fulfilment
        # updates) and re-raise. FastAPI returns 500; Stripe retries.
        db.rollback()
        logger.exception(
            "checkout.session.completed: apply raised session=%s txn=%s — "
            "rolling back for Stripe retry", session_id, txn.id,
        )
        raise

    # Singular ``entitlement`` field in the summary line is kept
    # for log-scraping compatibility with the pre-B3 format.
    # Multi-entitlement purchases log the id list.
    ent_summary = (
        result.entitlements[0].id if len(result.entitlements) == 1
        else [e.id for e in result.entitlements] or None
    )
    logger.info(
        "checkout.session.completed: %s txn=%s entitlement=%s user=%s pathway=%s",
        result.status.upper() if isinstance(result.status, str) else result.status,
        txn.id,
        ent_summary,
        payer_user_id,
        pathway_id,
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
