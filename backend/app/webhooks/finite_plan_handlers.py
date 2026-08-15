"""FIP2 — Stripe webhook handlers for finite payment plans.

Two handlers:

* :func:`handle_finite_plan_setup_completed` — the
  ``checkout.session.completed`` event for a ``mode='setup'``
  Session opened by the FIP2 orchestrator. Retrieves the saved
  payment method + Customer, sets it as the Customer's default,
  creates the Stripe Product / Price / SubscriptionSchedule.
  Does NOT grant access.

* :func:`handle_invoice_payment_succeeded` — the
  ``invoice.payment_succeeded`` event. For FIP2 scope, ONLY the
  first invoice matters (transitions the plan to ``active`` and
  applies the full grant bundle). Later invoices are skipped
  cleanly — that behaviour lands in FIP3.

Both handlers use the FIP1 idempotency helper
:func:`process_webhook_event`. Both handlers themselves are
idempotent per the contract — they check natural keys before
writing, so a lease-triggered replay after a crash does not
duplicate Stripe objects, PaymentTransaction rows, or access grants.

Field access
------------
Stripe payloads reach these handlers as plain dicts (produced by
``json.loads(str(event["data"]["object"]))`` in the dispatcher).
Dict ``.get()`` is safe here, but any code path that reads from a
``stripe.*`` SDK object directly must use subscript / ``in`` /
``getattr`` — StripeObject does NOT expose ``.get()`` and raises
``AttributeError`` on access. The :func:`_sfield` helper below reads
a nested path with those semantics uniformly so callers don't have
to remember which shape they're holding.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import stripe
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.purchase_fulfilment import (
    FulfilmentStatus,
    apply_intent,
    deserialise_intent,
    validate_intent,
)
from app.services import stripe_finite_plan
from app.services.webhook_idempotency import (
    SkipWebhookEvent,
    process_webhook_event,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StripeObject-safe nested field access
# ---------------------------------------------------------------------------


def _sfield(obj: Any, *path: str, default: Any = None) -> Any:
    """Read ``obj[path[0]][path[1]]…`` returning ``default`` on any miss.

    Works on both plain ``dict`` and Stripe SDK ``StripeObject``
    (a dict subclass that raises ``KeyError`` on subscript miss and
    does NOT expose ``.get()``). Never calls ``.get()`` on the
    input — uses ``in`` + ``[]`` throughout so a StripeObject
    passing through this helper cannot re-hit the historical
    ``AttributeError: get`` bug.

    Any exception (missing key, wrong type, non-subscriptable
    interior) yields ``default``. The helper is intentionally
    quiet — callers decide whether ``None`` warrants a
    ``SkipWebhookEvent`` or a hard failure.
    """
    cur: Any = obj
    for key in path:
        if cur is None:
            return default
        try:
            if key in cur:
                cur = cur[key]
            else:
                return default
        except (TypeError, KeyError):
            return default
    return cur


def _extract_subscription_id(invoice: Any) -> str | None:
    """Return the Subscription id linked to a Stripe Invoice payload.

    Current Stripe API surfaces it at
    ``invoice.parent.subscription_details.subscription``, discriminated
    by ``invoice.parent.type == 'subscription_details'``. Older API
    versions exposed a top-level ``invoice.subscription``; we fall
    back to that for maximum tolerance across SDK versions.

    Returns ``None`` for non-subscription invoices (one-off, quote,
    or unknown-parent), which the caller treats as "not one of ours,
    skip cleanly".
    """
    # Preferred: current API — parent.subscription_details.subscription
    parent_type = _sfield(invoice, "parent", "type")
    if parent_type == "subscription_details":
        current = _sfield(invoice, "parent", "subscription_details", "subscription")
        if current:
            return current
    # Legacy fallback — deprecated top-level ``subscription`` field.
    legacy = _sfield(invoice, "subscription")
    if legacy:
        return legacy
    return None


# ---------------------------------------------------------------------------
# Setup completion — create SubscriptionSchedule
# ---------------------------------------------------------------------------


def handle_finite_plan_setup_completed(
    session: dict, db: Session, metadata: dict,
    *,
    event_livemode: bool,
) -> None:
    """``checkout.session.completed`` handler for finite-plan setup Sessions.

    Wrapped in :func:`process_webhook_event` for durable idempotency
    keyed on the Stripe Session id (one Session → exactly one
    completion event → one processing outcome).

    ``event_livemode`` is required and checked against
    ``PurchasePlan.stripe_mode`` BEFORE any provider ids are
    persisted or any downstream Stripe call is made — see
    :func:`_do_setup_completed` for the boundary logic.
    """
    session_id: str = session.get("id", "")
    plan_id: str = metadata.get("purchase_plan_id", "")

    def _handler() -> None:
        _do_setup_completed(
            db, session=session, plan_id=plan_id,
            event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=f"setup_session:{session_id}",
        event_type="checkout.session.completed:finite_plan_setup",
        handler=_handler,
    )


def _do_setup_completed(
    db: Session, *, session: dict, plan_id: str, event_livemode: bool,
) -> None:
    if not plan_id:
        logger.error(
            "finite plan setup: missing purchase_plan_id in metadata "
            "(session=%s)", session.get("id"),
        )
        raise SkipWebhookEvent("missing purchase_plan_id")

    plan = _load_plan_locked(db, plan_id)
    if plan is None:
        logger.error(
            "finite plan setup: PurchasePlan %s not found (session=%s)",
            plan_id, session.get("id"),
        )
        raise SkipWebhookEvent(f"plan {plan_id} not found")

    # ── Mode boundary — checked BEFORE any mutation ────────────────
    # A test-mode event MUST NOT touch a live plan (or vice versa).
    # Check happens after the plan load (so we know the plan's mode)
    # but before persisting provider_customer_id / payment_method,
    # before calling attach_payment_method_as_default, and before
    # creating any downstream Stripe object. Same rule as the
    # first-invoice handler.
    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        logger.warning(
            "finite plan setup: livemode mismatch event=%s plan=%s (plan.id=%s)",
            event_livemode, plan.stripe_mode, plan.id,
        )
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, plan.stripe_mode={plan.stripe_mode})"
        )

    # Idempotency: if the plan is already past pending_setup, we've
    # already processed this Session on a prior delivery. Skip.
    if plan.status != PurchasePlanStatus.pending_setup:
        logger.info(
            "finite plan setup: plan %s already in status=%s — skipping.",
            plan.id, plan.status,
        )
        return

    # Retrieve the fully-hydrated Session so we can read setup_intent
    # + customer + payment_method.
    stripe_session = stripe_finite_plan.retrieve_completed_setup_session(
        session.get("id", "")
    )
    setup_intent = getattr(stripe_session, "setup_intent", None)
    if setup_intent is None:
        raise RuntimeError(
            "finite plan setup: no setup_intent on completed Session"
        )
    payment_method_id = getattr(setup_intent, "payment_method", None)
    customer_id = getattr(stripe_session, "customer", None)
    # ``customer`` may be an id or an expanded object.
    if customer_id is not None and not isinstance(customer_id, str):
        customer_id = customer_id.id
    if not payment_method_id or not customer_id:
        raise RuntimeError(
            f"finite plan setup: missing payment_method or customer "
            f"(pm={payment_method_id!r} cust={customer_id!r})"
        )

    # Persist provider ids BEFORE creating downstream Stripe objects,
    # so a crash between persist + SubscriptionSchedule creation
    # can be re-driven: the Stripe idempotency keys prevent
    # duplicate SubscriptionSchedule creation, and the persisted
    # ids let the retry pick up where it left off.
    plan.provider_customer_id = customer_id
    plan.provider_payment_method_id = payment_method_id
    plan.updated_at = datetime.utcnow()
    db.commit()

    # Attach payment method as default on the Customer.
    stripe_finite_plan.attach_payment_method_as_default(
        customer_id=customer_id,
        payment_method_id=payment_method_id,
    )

    # Product + Price
    if plan.stripe_price_id is None:
        option = (
            db.query(PaymentOption)
            .filter(PaymentOption.id == plan.payment_option_id)
            .first()
        )
        product_name = (option.name if option else "Fresh Collective plan")
        product_description = (
            f"Payment plan × {plan.installments_expected}"
        )
        product_id, price_id = stripe_finite_plan.create_product_and_price(
            plan=plan,
            product_name=product_name,
            product_description=product_description,
        )
        plan.stripe_product_id = product_id
        plan.stripe_price_id = price_id
        db.commit()

    # SubscriptionSchedule — the finite billing agreement.
    if plan.provider_subscription_schedule_id is None:
        schedule_id, subscription_id = (
            stripe_finite_plan.create_finite_subscription_schedule(
                plan=plan,
                customer_id=customer_id,
                price_id=plan.stripe_price_id,
                default_payment_method_id=payment_method_id,
            )
        )
        plan.provider_subscription_schedule_id = schedule_id
        if subscription_id:
            plan.provider_subscription_id = subscription_id
        db.commit()

    logger.info(
        "FIP2 setup complete: plan=%s customer=%s pm=%s schedule=%s subscription=%s",
        plan.id, plan.provider_customer_id, plan.provider_payment_method_id,
        plan.provider_subscription_schedule_id, plan.provider_subscription_id,
    )


# ---------------------------------------------------------------------------
# First invoice — grant access, activate plan
# ---------------------------------------------------------------------------


def handle_invoice_payment_succeeded(
    invoice: dict, db: Session, *,
    provider_event_id: str, event_livemode: bool,
) -> None:
    """``invoice.payment_succeeded`` handler. FIP2 scope = first invoice only."""
    def _handler() -> None:
        _do_invoice_succeeded(
            db, invoice=invoice, event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=provider_event_id,
        event_type="invoice.payment_succeeded",
        handler=_handler,
    )


def _do_invoice_succeeded(
    db: Session, *, invoice: dict, event_livemode: bool,
) -> None:
    invoice_id = _sfield(invoice, "id", default="")
    # Current Stripe API nests the subscription link at
    # ``parent.subscription_details.subscription``; older versions
    # exposed a top-level ``invoice.subscription``. Helper handles
    # both without ever calling ``.get()`` on a StripeObject.
    subscription_id = _extract_subscription_id(invoice)
    if not subscription_id:
        # Non-subscription invoice — nothing for FIP2 to do.
        raise SkipWebhookEvent(
            f"invoice {invoice_id} has no subscription — not a plan invoice"
        )

    plan = _find_plan_by_subscription(db, subscription_id)
    if plan is None:
        # Might be a Stripe object we don't own (test-mode noise).
        raise SkipWebhookEvent(
            f"no PurchasePlan for subscription {subscription_id}"
        )

    # Mode boundary — a test event MUST NOT touch a live plan.
    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        logger.warning(
            "finite plan invoice: livemode mismatch event=%s plan=%s (plan.id=%s)",
            event_livemode, plan.stripe_mode, plan.id,
        )
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, plan.stripe_mode={plan.stripe_mode})"
        )

    # FIP2 scope guard: only the first invoice is handled here.
    # A later invoice for an already-active plan is deferred to FIP3.
    if plan.status == PurchasePlanStatus.active:
        logger.info(
            "FIP2 invoice: plan %s already active — later-instalment "
            "reconciliation deferred to FIP3 (invoice=%s)",
            plan.id, invoice_id,
        )
        raise SkipWebhookEvent(
            f"plan already active; later-instalment reconciliation is FIP3 scope"
        )
    if plan.status != PurchasePlanStatus.pending_setup:
        # ``failed`` / ``cancelled`` / ``completed`` — no-op.
        logger.warning(
            "FIP2 invoice: plan %s in unexpected status=%s for first-invoice "
            "handling — skipping (invoice=%s)",
            plan.id, plan.status, invoice_id,
        )
        raise SkipWebhookEvent(
            f"plan status={plan.status} unexpected for first-invoice handling"
        )

    if invoice.get("status") != "paid":
        raise SkipWebhookEvent(
            f"invoice {invoice_id} status={invoice.get('status')} != paid"
        )

    # Idempotency: existing PaymentTransaction row for this invoice
    # is a re-delivery.
    existing_txn_id = db.execute(
        text(
            "SELECT id FROM payment_transactions "
            "WHERE provider_invoice_id = :inv LIMIT 1"
        ),
        {"inv": invoice_id},
    ).first()
    if existing_txn_id is not None:
        logger.info(
            "FIP2 invoice: transaction for invoice %s already exists — "
            "skipping create (plan=%s txn=%s)",
            invoice_id, plan.id, existing_txn_id[0],
        )
        return

    # Sanity — expected amount + currency.
    amount_paid = invoice.get("amount_paid")
    invoice_currency = (invoice.get("currency") or "").upper()
    if amount_paid != plan.installment_amount_cents:
        logger.error(
            "FIP2 invoice: amount mismatch invoice=%s got=%s expected=%s plan=%s",
            invoice_id, amount_paid, plan.installment_amount_cents, plan.id,
        )
        raise RuntimeError(
            f"invoice amount {amount_paid} != plan instalment "
            f"{plan.installment_amount_cents}"
        )
    if invoice_currency != plan.currency:
        raise RuntimeError(
            f"invoice currency {invoice_currency} != plan {plan.currency}"
        )

    # ── Create PaymentTransaction (instalment #1) ──────────────────
    now = datetime.utcnow()
    gross = amount_paid
    platform_fee = round(gross * plan.platform_fee_basis_points / 10000)
    net_creator = gross - platform_fee

    charge_id = invoice.get("charge")
    payment_intent_id = invoice.get("payment_intent")

    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.pending,
        payer_user_id=plan.member_user_id,
        creator_user_id=plan.creator_user_id,
        space_id=plan.space_id,
        creator_plan_id=plan.creator_plan_id,
        currency=plan.currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=plan.platform_fee_basis_points,
        platform_fee_cents=platform_fee,
        net_creator_amount_cents=net_creator,
        net_platform_amount_cents=platform_fee,
        provider_invoice_id=invoice_id,
        provider_subscription_id=subscription_id,
        provider_charge_id=charge_id,
        provider_payment_intent_id=payment_intent_id,
        payment_option_id=plan.payment_option_id,
        payment_option_schedule_id=plan.payment_option_schedule_id,
        purchase_plan_id=plan.id,
        installment_number=plan.installments_paid + 1,
        stripe_mode=plan.stripe_mode,
        payout_status=PayoutStatus.pending,
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.flush()

    # ── Fulfilment — apply the snapshotted grants atomically ───────
    if plan.snapshot_grants_json is None:
        # Should never happen for FIP2-created plans — snapshot is
        # written at plan creation. Mark blocked so an operator
        # can inspect.
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        raise RuntimeError(
            f"FIP2 invoice: plan {plan.id} has no snapshot_grants_json"
        )

    try:
        intent = deserialise_intent(plan.snapshot_grants_json)
    except Exception as exc:
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        raise RuntimeError(
            f"FIP2 invoice: cannot deserialise plan snapshot: {exc}"
        )

    validation = validate_intent(db, intent)
    if not validation.ok:
        # A Pathway / Series in the snapshot no longer exists (Creator
        # deleted it between plan creation and first-invoice). Mark
        # blocked — the payment stands, access cannot be applied,
        # operator intervention required.
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        logger.error(
            "FIP2 invoice: fulfilment blocked plan=%s txn=%s errors=%s",
            plan.id, txn.id, list(validation.errors),
        )
        return

    result = apply_intent(
        db,
        intent=intent,
        txn=txn,
        payer_user_id=plan.member_user_id,
        space_id=plan.space_id,
        payment_option_id=plan.payment_option_id,
        payment_option_schedule_id=plan.payment_option_schedule_id,
        session_id=plan.provider_setup_session_id,
        payment_intent_id=payment_intent_id,
        now=now,
        purchase_plan_id=plan.id,
    )
    if result.status != FulfilmentStatus.APPLIED:  # pragma: no cover
        txn.fulfilment_status = PaymentFulfilmentStatus.blocked
        db.commit()
        raise RuntimeError(
            f"FIP2 invoice: apply_intent returned status={result.status}"
        )

    txn.fulfilment_status = PaymentFulfilmentStatus.applied

    # ── Activate the plan ──────────────────────────────────────────
    plan.status = PurchasePlanStatus.active
    plan.installments_paid = 1
    plan.activated_at = now
    plan.updated_at = now
    db.commit()

    logger.info(
        "FIP2 first invoice applied: plan=%s txn=%s invoice=%s "
        "entitlements=%d access_passes=%d",
        plan.id, txn.id, invoice_id,
        len(result.entitlements), len(result.access_passes),
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _load_plan_locked(db: Session, plan_id: str) -> PurchasePlan | None:
    """Row-locked plan load — mirrors the pay-in-full handler pattern."""
    return (
        db.query(PurchasePlan)
        .filter(PurchasePlan.id == plan_id)
        .with_for_update()
        .one_or_none()
    )


def _find_plan_by_subscription(
    db: Session, subscription_id: str,
) -> PurchasePlan | None:
    """Locate the plan owning a Stripe Subscription. Row-locks."""
    return (
        db.query(PurchasePlan)
        .filter(PurchasePlan.provider_subscription_id == subscription_id)
        .with_for_update()
        .one_or_none()
    )
