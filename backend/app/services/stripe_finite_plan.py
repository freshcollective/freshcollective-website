"""Stripe API wrappers for finite payment plans (FIP2).

Every function is a thin wrapper around one Stripe SDK call. Keeping
them separate from the orchestration + webhook code makes the flow
testable — the tests mock this module rather than mocking the
Stripe SDK directly, and the caller-side flow reads cleanly without
inline Stripe boilerplate.

Idempotency
-----------
Every Stripe write passes an idempotency key derived from the
``PurchasePlan.id`` and the operation name, e.g.
``pplan_abc:setup_session:v1``. This means a duplicate call (a
webhook redelivery reclaiming a stale lease, a network retry) does
NOT create a second Stripe object.

Test / live mode
----------------
The Stripe SDK's ``api_key`` is bound from
``settings.stripe_secret_key`` at the start of every call. Every
function returns the Stripe object; callers persist provider ids on
``PurchasePlan`` immediately after the call returns.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.core.config import settings
from app.models.purchase_plan import PurchasePlan
from app.services.finite_plan_disclosure import compose_setup_disclosure


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Idempotency-key helpers
# ---------------------------------------------------------------------------


def _idem(plan_id: str, op_name: str, *, version: str = "v1") -> str:
    """Stable per-plan-per-operation idempotency key.

    ``version`` lets us cleanly retry an operation whose earlier call
    was cached by Stripe (both success and 4xx errors are cached for
    24h against the same key). Bump the version only for the
    operation whose payload has changed — sibling operations under
    the same plan keep their existing keys so we don't re-hit
    Stripe for work that already succeeded.
    """
    return f"pplan:{plan_id}:{op_name}:{version}"


def _bind_key() -> None:
    if not settings.stripe_enabled:
        raise RuntimeError(
            "Stripe is not configured — cannot create finite payment plan."
        )
    stripe.api_key = settings.stripe_secret_key


# ---------------------------------------------------------------------------
# Customer creation / reuse
# ---------------------------------------------------------------------------


def find_reusable_customer_id(db, member_user_id: str) -> str | None:
    """Look for a Stripe customer id already attached to any prior
    ``PurchasePlan`` for this member. Reusing one customer keeps
    Stripe Dashboard tidy and lets Stripe consolidate a member's
    payment methods.

    Returns None if no prior plan exists — the setup Session will
    create a fresh Customer via ``customer_email``.
    """
    from sqlalchemy import text
    row = db.execute(
        text(
            "SELECT provider_customer_id FROM purchase_plans "
            "WHERE member_user_id = :uid "
            "AND provider_customer_id IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"uid": member_user_id},
    ).first()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Setup Session (mode='setup')
# ---------------------------------------------------------------------------


def create_setup_session(
    *,
    plan: PurchasePlan,
    option_name: str,
    member_email: str,
    success_url: str,
    cancel_url: str,
    reuse_customer_id: str | None,
) -> Any:
    """Create a Stripe Checkout Session in ``mode='setup'``.

    Collects the member's payment method + establishes/reuses a
    Stripe Customer. On completion, ``session.setup_intent`` carries
    the SetupIntent id and ``session.customer`` carries the Customer
    id — both persisted onto ``PurchasePlan`` in the webhook.

    Metadata:
      * ``purchase_type='finite_plan_setup'`` — the discriminator
        the webhook uses to route to the FIP2 handler (existing
        pay-in-full sessions carry no ``purchase_type`` or the
        ``'standalone_gathering'`` value).
      * ``purchase_plan_id`` — how the webhook re-finds the plan.
      * ``payer_user_id`` — cross-check.

    Payment-plan disclosure: a hard-coded ``custom_text.submit.message``
    composed by :func:`compose_setup_disclosure` from the immutable
    ``PurchasePlan`` snapshot + ``option_name`` makes the financial
    commitment unmistakable directly on the Stripe-hosted setup page.
    Members otherwise see a bare "save payment information" form and
    could reasonably interpret it as merely saving a card.
    """
    _bind_key()
    disclosure = compose_setup_disclosure(plan=plan, option_name=option_name)
    kwargs: dict[str, Any] = dict(
        mode="setup",
        payment_method_types=["card"],
        success_url=success_url,
        cancel_url=cancel_url,
        custom_text={"submit": {"message": disclosure}},
        metadata={
            "purchase_type": "finite_plan_setup",
            "purchase_plan_id": plan.id,
            "payer_user_id": plan.member_user_id,
            "payment_option_id": plan.payment_option_id,
            "payment_option_schedule_id": plan.payment_option_schedule_id,
        },
    )
    if reuse_customer_id is not None:
        kwargs["customer"] = reuse_customer_id
    else:
        kwargs["customer_email"] = member_email
        # Force Stripe to always create a Customer object (default
        # for ``mode='setup'`` is already ``always``, but stating it
        # explicitly avoids drift if Stripe defaults ever change).
        kwargs["customer_creation"] = "always"

    return stripe.checkout.Session.create(
        idempotency_key=_idem(plan.id, "setup_session"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Post-setup fetch: SetupIntent + PaymentMethod
# ---------------------------------------------------------------------------


def retrieve_completed_setup_session(session_id: str) -> Any:
    """Retrieve a completed Session with SetupIntent + Customer expanded."""
    _bind_key()
    return stripe.checkout.Session.retrieve(
        session_id,
        expand=["setup_intent", "customer"],
    )


def attach_payment_method_as_default(
    *, customer_id: str, payment_method_id: str,
) -> None:
    """Set the given payment method as the Customer's default for
    invoice payments. Required so the SubscriptionSchedule's
    invoices charge automatically without member interaction.
    """
    _bind_key()
    stripe.Customer.modify(
        customer_id,
        invoice_settings={"default_payment_method": payment_method_id},
    )


# ---------------------------------------------------------------------------
# Product + Price creation
# ---------------------------------------------------------------------------


def create_product_and_price(
    *,
    plan: PurchasePlan,
    product_name: str,
    product_description: str,
) -> tuple[str, str]:
    """Create a Stripe Product and a recurring Price tuned to the
    plan's cadence + per-instalment amount. Returns (product_id, price_id).

    Two Stripe objects, both idempotent per-plan.
    """
    _bind_key()

    product = stripe.Product.create(
        name=product_name,
        description=product_description,
        metadata={
            "purchase_plan_id": plan.id,
            "payment_option_id": plan.payment_option_id,
        },
        idempotency_key=_idem(plan.id, "product"),
    )

    price = stripe.Price.create(
        product=product.id,
        currency=plan.currency.lower(),
        unit_amount=plan.installment_amount_cents,
        recurring={
            "interval": plan.stripe_interval,
            "interval_count": plan.stripe_interval_count,
        },
        metadata={
            "purchase_plan_id": plan.id,
        },
        idempotency_key=_idem(plan.id, "price"),
    )
    return product.id, price.id


# ---------------------------------------------------------------------------
# SubscriptionSchedule — the finite billing agreement
# ---------------------------------------------------------------------------


def create_finite_subscription_schedule(
    *,
    plan: PurchasePlan,
    customer_id: str,
    price_id: str,
    default_payment_method_id: str,
) -> tuple[str, str | None]:
    """Create the SubscriptionSchedule Stripe will use to bill N
    invoices then stop.

    Returns ``(schedule_id, subscription_id)``. ``subscription_id``
    may be ``None`` on the very first response — it becomes
    available once the schedule advances to its active phase (Stripe
    typically fills it on the same response, but the caller should
    handle a nullable return).

    Shape:
      * One phase whose ``duration`` covers the full finite plan:
        ``interval`` = the recurring Price's cadence unit,
        ``interval_count`` = the Price's cadence multiplier × the
        instalment count. The single item points at the recurring
        Price. Stripe bills once per Price cadence for the phase's
        duration and produces exactly N invoices.
      * ``end_behavior='cancel'`` — Stripe cancels the underlying
        Subscription when the phase's duration ends. This is where
        the "finite" guarantee lives; we don't calculate calendar
        end dates ourselves.
      * ``default_settings.default_payment_method`` — the payment
        method saved during setup is used for every invoice.

    History
    -------
    Stripe removed ``phases[].iterations`` from
    ``SubscriptionSchedule.create``; the replacement is
    ``phases[].duration = {interval, interval_count}``. The two
    encode the same idea (Stripe multiplies phase duration by the
    Price cadence to produce N charges) — the API shape is
    different, our product semantics are unchanged.
    """
    _bind_key()

    # ── Phase duration = Price cadence × instalment count ──────────
    # e.g. weekly × 3       → week × 1 Price   → phase duration week × 3
    #      fortnightly × 5  → week × 2 Price   → phase duration week × 10
    #      monthly × 6      → month × 1 Price  → phase duration month × 6
    phase_interval_count = (
        plan.stripe_interval_count * plan.installments_expected
    )

    schedule = stripe.SubscriptionSchedule.create(
        customer=customer_id,
        start_date="now",
        end_behavior="cancel",
        default_settings={
            "default_payment_method": default_payment_method_id,
        },
        phases=[
            {
                "items": [
                    {"price": price_id, "quantity": 1},
                ],
                "duration": {
                    "interval": plan.stripe_interval,
                    "interval_count": phase_interval_count,
                },
                "metadata": {
                    "purchase_plan_id": plan.id,
                },
            }
        ],
        metadata={
            "purchase_plan_id": plan.id,
            "payment_option_id": plan.payment_option_id,
            "payment_option_schedule_id": plan.payment_option_schedule_id,
        },
        # v2 bump: the v1 key was consumed by the initial 400
        # response Stripe returned when we still passed ``iterations``;
        # Stripe caches error responses under an idempotency key for
        # 24h, so a retry with v1 would replay the same 400.
        idempotency_key=_idem(plan.id, "subscription_schedule", version="v2"),
    )

    subscription_id = getattr(schedule, "subscription", None)
    return schedule.id, subscription_id


def retrieve_subscription_schedule(schedule_id: str) -> Any:
    """Retrieve a schedule to re-read its ``subscription`` field.

    Called on later reconciliation events when we need the
    underlying Subscription id and didn't get it on create.
    """
    _bind_key()
    return stripe.SubscriptionSchedule.retrieve(schedule_id)


# ---------------------------------------------------------------------------
# FIP4A — immediate first-invoice finalise + pay
# ---------------------------------------------------------------------------


def finalize_and_pay_first_invoice(
    *, plan: PurchasePlan, subscription_id: str,
) -> tuple[str, str]:
    """Finalise + pay the initial ``subscription_create`` invoice
    for a freshly-created SubscriptionSchedule.

    Returns ``(invoice_id, final_status)`` where ``final_status`` is
    the Stripe invoice status after the pay attempt — usually
    ``paid`` on success. Non-``paid`` values (``open``, still-open
    after a ``requires_action`` payment intent, etc.) are the
    caller's signal that the initial collection did NOT immediately
    succeed and the setup handler should terminate the plan.

    Preconditions the CALLER must have already checked:
      * plan.status == pending_setup
      * plan.stripe_mode matches the current API key mode

    Guards enforced here:
      * refuses if the subscription's ``latest_invoice`` is missing
      * refuses if invoice ``billing_reason != 'subscription_create'``
      * skips (returns the current status) if invoice is already
        past ``draft`` (someone else already progressed it)

    Idempotency: both Stripe calls carry per-plan versioned keys.
    A lease-triggered replay of the setup handler will re-send the
    same key; Stripe returns the cached result — no double-charge.

    Exception discipline:
      * ``stripe.CardError`` propagates — caller decides whether to
        rethrow (letting the webhook retry) or catch and terminate.
        For a card decline we specifically catch and terminate;
        for a truly transient issue the caller lets Stripe redeliver.
      * All other Stripe errors propagate to the caller.
    """
    _bind_key()
    sub = stripe.Subscription.retrieve(subscription_id)
    latest_invoice_id = (
        sub["latest_invoice"] if isinstance(sub, dict)
        else getattr(sub, "latest_invoice", None)
    )
    if not latest_invoice_id:
        raise RuntimeError(
            f"finalize_and_pay_first_invoice: subscription {subscription_id} "
            f"has no latest_invoice (plan={plan.id})"
        )

    invoice = stripe.Invoice.retrieve(latest_invoice_id)
    inv_status = invoice["status"] if isinstance(invoice, dict) else getattr(invoice, "status", None)
    billing_reason = (
        invoice["billing_reason"] if isinstance(invoice, dict)
        else getattr(invoice, "billing_reason", None)
    )
    inv_subscription = (
        invoice["subscription"] if isinstance(invoice, dict)
        else getattr(invoice, "subscription", None)
    )
    if inv_subscription and inv_subscription != subscription_id:
        raise RuntimeError(
            f"finalize_and_pay_first_invoice: invoice {latest_invoice_id} "
            f"subscription={inv_subscription!r} != expected {subscription_id!r}"
        )
    if billing_reason != "subscription_create":
        raise RuntimeError(
            f"finalize_and_pay_first_invoice: invoice {latest_invoice_id} "
            f"billing_reason={billing_reason!r} != 'subscription_create'"
        )
    if inv_status not in ("draft", "open"):
        # Already progressed — nothing for us to do. Return the
        # observed status so the caller sees the outcome.
        logger.info(
            "FIP4A first-invoice accel: invoice %s already status=%s — skipping "
            "finalize/pay (plan=%s)",
            latest_invoice_id, inv_status, plan.id,
        )
        return latest_invoice_id, inv_status or ""

    if inv_status == "draft":
        stripe.Invoice.finalize_invoice(
            latest_invoice_id,
            auto_advance=False,
            idempotency_key=_idem(plan.id, "finalize_first_invoice"),
        )

    # Pay the (now-open) invoice. The card decline case propagates
    # ``stripe.CardError``; caller decides what to do with it.
    #
    # State-based race recovery for ``stripe.InvalidRequestError``:
    # Stripe's own auto-progression can pay the invoice between our
    # retrieve and our pay call — the balance-satisfied case where
    # Stripe pays a $0-due invoice as soon as it exists is one real
    # trigger. When this happens ``Invoice.pay`` raises. We do NOT
    # match on the error message text (Stripe wording is not a
    # contract). Instead we refetch and validate state: if the same
    # invoice is now ``paid`` and still belongs to the same
    # subscription + ``subscription_create`` reason, the pay step
    # succeeded via Stripe's own progression — treat as success.
    try:
        paid = stripe.Invoice.pay(
            latest_invoice_id,
            idempotency_key=_idem(plan.id, "pay_first_invoice"),
        )
    except stripe.InvalidRequestError as exc:
        refetched = stripe.Invoice.retrieve(latest_invoice_id)
        ref_status = (
            refetched["status"] if isinstance(refetched, dict)
            else getattr(refetched, "status", None)
        )
        ref_sub = (
            refetched["subscription"] if isinstance(refetched, dict)
            else getattr(refetched, "subscription", None)
        )
        ref_reason = (
            refetched["billing_reason"] if isinstance(refetched, dict)
            else getattr(refetched, "billing_reason", None)
        )
        if (ref_status == "paid"
                and ref_sub == subscription_id
                and ref_reason == "subscription_create"):
            logger.info(
                "FIP4A first-invoice accel: benign race — invoice %s already "
                "paid by Stripe (plan=%s). Original error: %s",
                latest_invoice_id, plan.id, exc,
            )
            return latest_invoice_id, "paid"
        # Genuine InvalidRequestError — re-raise so the webhook
        # lease/retry can recover or the operator can inspect.
        raise
    paid_status = paid["status"] if isinstance(paid, dict) else getattr(paid, "status", None)
    logger.info(
        "FIP4A first-invoice accel: plan=%s invoice=%s → status=%s",
        plan.id, latest_invoice_id, paid_status,
    )
    return latest_invoice_id, paid_status or ""


# ---------------------------------------------------------------------------
# FIP4A — terminate an abandoned finite-plan Subscription/Schedule
# ---------------------------------------------------------------------------


def cancel_finite_subscription_schedule(*, plan: PurchasePlan) -> None:
    """Cancel the SubscriptionSchedule tied to a PurchasePlan so its
    underlying Subscription terminates and no future automatic
    charges can occur.

    Used by the FIP4A first-payment-failed path when the initial
    invoice cannot be collected. Also usable for one-off operator
    cleanup of abandoned test-mode plans.

    **Semantics** for first-payment-failure cleanup:

      * ``invoice_now=False`` — do NOT emit a final proration
        invoice; the member never earned access, so any residual
        billing would be inappropriate.
      * ``prorate=False`` — do NOT apply any proration credit.
      * ``cancel`` (vs. ``release``) — cancel cascades to the
        underlying Subscription so no future scheduled invoices
        can fire. ``release`` would detach the schedule and let
        the subscription continue autonomously — exactly what we
        must avoid.

    **Idempotency** — if the schedule is already ``canceled`` or
    ``completed``, this is a no-op (fetch + short-circuit). If the
    schedule is not found on Stripe (``InvalidRequestError``),
    treated as already-terminated: no exception. Any other Stripe
    error propagates so the caller can decide whether the
    surrounding local transition should proceed or be deferred
    until provider cleanup succeeds.
    """
    _bind_key()
    schedule_id = plan.provider_subscription_schedule_id
    if not schedule_id:
        logger.info(
            "FIP4A cancel: plan=%s has no SubscriptionSchedule id; nothing to cancel",
            plan.id,
        )
        return
    try:
        current = stripe.SubscriptionSchedule.retrieve(schedule_id)
    except stripe.InvalidRequestError as exc:
        # Not found → treat as already-terminated. Any other
        # InvalidRequestError shape would still be an API-level
        # signal we can't recover from, but retrieve failures with
        # "No such subscription_schedule" are the specific case we
        # want to allow through.
        logger.warning(
            "FIP4A cancel: schedule %s not found on Stripe (plan=%s): %s",
            schedule_id, plan.id, exc,
        )
        return
    status = (
        current["status"] if isinstance(current, dict)
        else getattr(current, "status", None)
    )
    if status in ("canceled", "completed"):
        logger.info(
            "FIP4A cancel: schedule %s already status=%s (plan=%s); no-op",
            schedule_id, status, plan.id,
        )
        return
    stripe.SubscriptionSchedule.cancel(
        schedule_id,
        invoice_now=False,
        prorate=False,
    )
    logger.info(
        "FIP4A cancel: SubscriptionSchedule %s cancelled with "
        "invoice_now=False prorate=False (plan=%s)",
        schedule_id, plan.id,
    )


# ---------------------------------------------------------------------------
# FIP3 hardening — invoice inventory for the finite-end reconciler
# ---------------------------------------------------------------------------


def list_invoices_for_subscription(
    subscription_id: str, *, limit: int = 100,
) -> list[dict]:
    """Return every invoice Stripe has for the given Subscription.

    Called from the finite-end reconciler
    (``services.finite_plan_end_reconciliation``) to answer the
    order-independence question: "is Stripe hiding a paid invoice
    we haven't yet seen a webhook for?".

    Uses cursor pagination via ``auto_paging_iter`` under the hood
    (falls back to a manual loop if unavailable) so a plan with
    many retries still returns the full inventory. Each element is
    a plain dict — ``StripeObject.to_dict()`` — so the caller
    doesn't need to know about ``StripeObject`` quirks.

    Only invoices Stripe still knows about are returned. Deleted
    Stripe test-mode invoices vanish, which is fine — the caller
    treats "no record" the same as "not paid".
    """
    _bind_key()
    invoices: list[dict] = []
    try:
        iterator = stripe.Invoice.list(
            subscription=subscription_id, limit=limit,
        ).auto_paging_iter()
        for inv in iterator:
            invoices.append(inv.to_dict())
    except AttributeError:  # pragma: no cover — very old SDKs
        page = stripe.Invoice.list(
            subscription=subscription_id, limit=limit,
        )
        for inv in page.data:
            invoices.append(inv.to_dict() if hasattr(inv, "to_dict") else dict(inv))
    return invoices
