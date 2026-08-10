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
    EventSeries,
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
            claim_intent(db, intent, user)
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

    # Persist everything: the mark-paid transition and, when the payer
    # was known, the full activation (subscription + role + WB + audit
    # + consumption). Without this commit the SQLAlchemy session
    # rolls back on request end and none of the above survives.
    db.commit()


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

    # ``pathway_id`` in metadata is only required for pathway-attached
    # options. For series-attached options the target is derived from
    # ``payment_option.attaches_to_id`` (an EventSeries id) and no
    # pathway metadata is expected on the Session.
    _series_purchase = False
    if payment_option_id:
        _po_probe = db.query(PaymentOption).filter(PaymentOption.id == payment_option_id).first()
        if _po_probe and _po_probe.attaches_to_kind == "event_series":
            _series_purchase = True

    required_meta = [transaction_id, payer_user_id, space_id]
    if not _series_purchase:
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

    # ── Series purchases: resolve the EventSeries and derive the term
    #    window from it. AccessPass validity is scoped to the series;
    #    any included Pathway entitlement gets its ``ends_at`` from
    #    the series end but its ``starts_at`` stays at ``now`` so a
    #    future-term buyer gets immediate access to included content
    #    without waiting for the term to begin. This decoupling is
    #    intentional — see clarification 1 in the Step 1 spec.
    from datetime import datetime as _dt
    series: EventSeries | None = None
    if payment_option and payment_option.attaches_to_kind == "event_series":
        series = (
            db.query(EventSeries)
            .filter(EventSeries.id == payment_option.attaches_to_id)
            .first()
        )
        if not series:
            logger.error(
                "checkout.session.completed: series %s not found for option %s — aborting",
                payment_option.attaches_to_id, payment_option.id,
            )
            return

    # ── Entitlement target + window ─────────────────────────────────────
    #
    # Pathway-attached options: entitlement targets grants_pathway_id or
    # falls back to pathway_id metadata (legacy behaviour). ``ends_at`` is
    # driven by ``term_end_date`` for term_pass, else null.
    #
    # Series-attached options: entitlement is created only when the option
    # explicitly sets ``grants_pathway_id``. Its ``starts_at`` is ``now``
    # (immediate access), ``ends_at`` follows the precedence below.
    #
    # Window precedence for a series-attached term_pass:
    #   1. ``series.ends_at`` if the series has a defined end.
    #   2. ``payment_option.term_end_date`` otherwise (an ongoing series
    #      can still sell a bounded pass — "10 sessions over 3 months").
    #   3. NULL — a perpetual pass on an ongoing series. Legal in the
    #      data model; a future creator UI will make this explicit.
    entitlement_pathway_id: str | None
    term_ends_at: _dt | None = None

    def _po_term_end_dt() -> _dt | None:
        if payment_option and payment_option.term_end_date:
            opt_type = (
                payment_option.payment_type.value
                if hasattr(payment_option.payment_type, "value")
                else str(payment_option.payment_type)
            )
            if opt_type == "term_pass":
                return _dt.combine(payment_option.term_end_date, _dt.min.time())
        return None

    if series is not None:
        entitlement_pathway_id = payment_option.grants_pathway_id if payment_option else None
        term_ends_at = series.ends_at or _po_term_end_dt()
    else:
        entitlement_pathway_id = (
            payment_option.grants_pathway_id
            if payment_option and payment_option.grants_pathway_id
            else pathway_id
        )
        term_ends_at = _po_term_end_dt()

    # ── Create or reactivate PathwayEntitlement (when applicable) ───────
    #
    # ``ent`` is the PathwayEntitlement row id we then hang on the txn
    # (for pathway-attached purchases) and on the AccessPass (for term
    # passes that also grant pathway content). For a series purchase
    # without ``grants_pathway_id`` there is no entitlement to create;
    # the AccessPass alone represents what the buyer receives.
    ent: PathwayEntitlement | None = None
    if entitlement_pathway_id:
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
            # Already active (re-delivery) — update Stripe fields only.
            # ``ends_at`` is deliberately NOT extended here: an in-flight
            # term still has its own expiry; a follow-up purchase creates
            # a fresh window through the reactivation branch below when
            # the current one has ended.
            existing_ent.stripe_checkout_session_id = session_id
            existing_ent.stripe_payment_intent_id = payment_intent_id
            existing_ent.updated_at = now
            ent = existing_ent
            logger.info(
                "checkout.session.completed: entitlement already active user=%s pathway=%s",
                payer_user_id, entitlement_pathway_id,
            )
        elif existing_ent:
            # Reactivate a revoked/expired/cancelled entitlement with a
            # fresh window. ``starts_at`` is ``now`` — for series-included
            # pathway grants this means immediate access even when the
            # series hasn't begun (per Step 1 clarification 1).
            existing_ent.status = EntitlementStatus.active
            existing_ent.source = EntitlementSource.one_time_purchase
            existing_ent.stripe_checkout_session_id = session_id
            existing_ent.stripe_payment_intent_id = payment_intent_id
            existing_ent.revoked_by_user_id = None
            existing_ent.revoked_at = None
            existing_ent.starts_at = now
            existing_ent.ends_at = term_ends_at
            existing_ent.updated_at = now
            ent = existing_ent
            logger.info(
                "checkout.session.completed: reactivated entitlement user=%s pathway=%s ends_at=%s",
                payer_user_id, entitlement_pathway_id, term_ends_at,
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

    if ent is not None:
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
    #
    # Pathway-attached term_pass  → eligible_pathway_id set, series null,
    #                               valid_from = term_start_date (or now).
    # Series-attached  term_pass  → eligible_series_id set, pathway null,
    #                               valid_from = series.starts_at,
    #                               valid_until = series.ends_at.
    #                               A future-term pass therefore has
    #                               valid_from in the future — booking
    #                               eligibility (spaces/routes.py) rejects
    #                               it until the window opens.
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
                if series is not None:
                    valid_from_dt = series.starts_at
                    # AccessPass valid_until precedence matches the
                    # entitlement one — series end wins if set, else
                    # the option's own term_end_date, else null.
                    ap_valid_until = series.ends_at or (
                        _dt.combine(payment_option.term_end_date, _dt.min.time())
                        if payment_option.term_end_date else None
                    )
                    ap_eligible_series_id = series.id
                    ap_eligible_pathway_id = None
                else:
                    valid_from_dt = (
                        _dt.combine(payment_option.term_start_date, _dt.min.time())
                        if payment_option.term_start_date
                        else now
                    )
                    ap_valid_until = term_ends_at
                    ap_eligible_series_id = None
                    ap_eligible_pathway_id = entitlement_pathway_id

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
                    valid_until=ap_valid_until,
                    total_credits=payment_option.total_sessions,
                    used_credits=0,
                    credits_per_week=payment_option.sessions_per_week,
                    eligible_pathway_id=ap_eligible_pathway_id,
                    eligible_series_id=ap_eligible_series_id,
                    grants_pathway_id=entitlement_pathway_id,
                    pathway_entitlement_id=ent.id if ent is not None else None,
                    source=AccessPassSource.one_time_purchase,
                    created_at=now,
                    updated_at=now,
                )
                db.add(access_pass)
                logger.info(
                    "checkout.session.completed: created AccessPass %s type=term_pass "
                    "credits=%s credits_per_week=%s valid=%s→%s series=%s pathway=%s user=%s",
                    access_pass.id,
                    payment_option.total_sessions,
                    payment_option.sessions_per_week,
                    valid_from_dt,
                    ap_valid_until,
                    ap_eligible_series_id,
                    ap_eligible_pathway_id,
                    payer_user_id,
                )
            else:
                logger.info(
                    "checkout.session.completed: AccessPass already exists for txn=%s — skipping",
                    txn.id,
                )

    db.commit()

    logger.info(
        "checkout.session.completed: SUCCESS txn=%s entitlement=%s user=%s pathway=%s series=%s",
        txn.id,
        ent.id if ent is not None else None,
        payer_user_id,
        pathway_id,
        series.id if series is not None else None,
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
