"""FIP4B2 — member payment-method repair for a finite payment plan.

Three thin wrappers around the Stripe API, all mode-guarded, all
idempotency-keyed, all reusable by the HTTP route + the completion
webhook + the test harness:

* :func:`create_repair_setup_session` — open a Stripe Checkout
  Session in ``mode='setup'`` bound to the plan's existing
  Customer. Collects a NEW reusable PaymentMethod; does NOT create
  a subscription, invoice, or PurchasePlan. Metadata carries
  ``purchase_type='finite_plan_repair'`` + the plan id + the payer
  user id so the completion webhook can re-load and re-validate.

* :func:`swap_default_payment_method_all_surfaces` — after the
  member saves a new PaymentMethod, update the default on ALL
  three surfaces Stripe uses when auto-billing a plan's remaining
  instalments:

    1. ``Customer.invoice_settings.default_payment_method``
    2. ``SubscriptionSchedule.default_settings.default_payment_method``
    3. ``Subscription.default_payment_method``

  Then re-fetch each and assert the new PaymentMethod is present.
  Any missing surface aborts BEFORE the retry — better to leave the
  member recoverable than to charge against ambiguous provider state.

  The three-surface requirement is the hard lesson from FIP3: a
  Customer-only update leaves the underlying Subscription pointing
  at the old (declining) card via
  ``SubscriptionSchedule.default_settings.default_payment_method``,
  and Stripe's Smart Retries + our repair retry both bill the
  wrong card. The old card can be a legitimate reason for
  cascading failure loops.

* :func:`retry_overdue_invoice` — call ``stripe.Invoice.pay`` on
  the plan's ``last_failed_invoice_id`` with a per-invoice
  idempotency key so a webhook redelivery or double-processing
  cannot cause a double-charge. Validates that the invoice
  belongs to the plan's Subscription and is still open/retryable
  before touching it.

  Discipline:
    * ``stripe.CardError`` → return (invoice_id, 'declined').
      Legitimate commerce outcome. The existing
      ``invoice.payment_failed`` webhook has already/will re-mark
      the plan as ``payment_problem`` / ``suspended`` accordingly.
    * ``stripe.StripeError`` (anything else — network, 5xx, rate
      limit) → re-raise. Infrastructure failure; the caller lets
      the webhook lease retry.

The three functions never mutate ``PurchasePlan`` rows. That's the
webhook handler's job — this module is Stripe-only. Keeping the
split clean lets the FIP4B2 tests mock this module rather than
mocking the Stripe SDK directly.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.core.config import settings
from app.models.purchase_plan import PurchasePlan
from app.services.stripe_finite_plan import _bind_key, _idem


logger = logging.getLogger(__name__)


class PaymentMethodSwapError(RuntimeError):
    """Raised when a required PM surface cannot be updated or verified.

    Deliberately distinct from ``stripe.StripeError`` so the caller
    (the completion webhook) can react differently: abort the retry
    (leaving the plan recoverable via a fresh repair attempt) rather
    than treating it as a transient infrastructure failure.
    """


class RepairInvoiceNotRetryable(RuntimeError):
    """Raised when ``plan.last_failed_invoice_id`` is missing, points
    at an invoice that doesn't belong to the plan's Subscription, or
    is not in an open/retryable state. Signals: don't retry, but
    saving the PM was still valid — Stripe's ongoing Smart Retries or
    a future ``invoice.payment_succeeded`` webhook can still recover
    the plan."""


# ---------------------------------------------------------------------------
# Setup Session — collect a new PaymentMethod, do NOT create a subscription
# ---------------------------------------------------------------------------


def create_repair_setup_session(
    *,
    plan: PurchasePlan,
    member_email: str,
    success_url: str,
    cancel_url: str,
) -> Any:
    """Open a Stripe Checkout Session in ``mode='setup'`` bound to
    the plan's existing Customer.

    Preconditions the CALLER must have already checked:
      * plan.status in {payment_problem, suspended}
      * plan.provider_customer_id is set (there's no plan to repair
        without a Customer)

    Metadata:
      * ``purchase_type='finite_plan_repair'`` — the discriminator
        the completion webhook uses to route to
        :func:`app.webhooks.finite_plan_handlers.handle_finite_plan_repair_completed`.
        Never overlaps with ``finite_plan_setup`` (the initial
        purchase setup) because the completion handler for a repair
        deliberately does NOT create a SubscriptionSchedule / grant
        access; it only swaps the PM + retries the overdue invoice.
      * ``purchase_plan_id`` — how the webhook re-finds the plan.
      * ``payer_user_id`` — server-side re-validation of ownership
        (the webhook re-loads the plan and asserts
        ``plan.member_user_id == payer_user_id`` before touching
        Stripe).

    No new PaymentMethod is charged at setup; no new subscription is
    created; no PurchasePlan is created. The setup Session ONLY
    saves a reusable PaymentMethod against the Customer.

    Idempotency key: NOT used on this call. A member may
    legitimately need to open multiple setup Sessions (they closed
    the browser, tried a card that failed on Stripe's side and
    wants to try another, etc.). Each attempt is a fresh Session;
    the completion webhook is what needs to be idempotent, and
    that's handled by the durable ``webhook_events`` lease.
    """
    _bind_key()

    if not plan.provider_customer_id:
        raise ValueError(
            f"create_repair_setup_session: plan {plan.id} has no "
            f"provider_customer_id — cannot open a repair setup Session."
        )

    return stripe.checkout.Session.create(
        mode="setup",
        payment_method_types=["card"],
        customer=plan.provider_customer_id,
        success_url=success_url,
        cancel_url=cancel_url,
        custom_text={
            "submit": {
                "message": (
                    "Save these payment details to retry your overdue "
                    "instalment. This does not start a new plan."
                )
            }
        },
        metadata={
            "purchase_type": "finite_plan_repair",
            "purchase_plan_id": plan.id,
            "payer_user_id": plan.member_user_id,
        },
    )


def retrieve_completed_repair_session(session_id: str) -> Any:
    """Retrieve a completed repair Session with setup_intent expanded."""
    _bind_key()
    return stripe.checkout.Session.retrieve(
        session_id,
        expand=["setup_intent"],
    )


# ---------------------------------------------------------------------------
# Swap default PaymentMethod on ALL THREE surfaces
# ---------------------------------------------------------------------------


def swap_default_payment_method_all_surfaces(
    *,
    plan: PurchasePlan,
    new_payment_method_id: str,
) -> None:
    """Update the default PaymentMethod on every surface Stripe uses
    to bill this plan's remaining instalments, then re-fetch each
    and assert the update took.

    Order of updates is deliberate but not critical — the assertion
    step is the correctness gate. If any assertion fails, raise
    :class:`PaymentMethodSwapError` so the caller aborts the retry
    (leaving the plan recoverable rather than charging against
    ambiguous provider state).

    Idempotent under replay: setting the same PaymentMethod twice
    is a no-op on Stripe's side. A webhook redelivery re-runs the
    same swap; nothing breaks.
    """
    _bind_key()

    if not plan.provider_customer_id:
        raise ValueError(
            f"swap PM: plan {plan.id} has no provider_customer_id"
        )
    if not plan.provider_subscription_schedule_id:
        raise ValueError(
            f"swap PM: plan {plan.id} has no provider_subscription_schedule_id"
        )
    if not plan.provider_subscription_id:
        raise ValueError(
            f"swap PM: plan {plan.id} has no provider_subscription_id"
        )
    if not new_payment_method_id:
        raise ValueError("swap PM: new_payment_method_id required")

    # 1. Customer — invoice_settings.default_payment_method.
    stripe.Customer.modify(
        plan.provider_customer_id,
        invoice_settings={"default_payment_method": new_payment_method_id},
    )

    # 2. SubscriptionSchedule — default_settings.default_payment_method.
    stripe.SubscriptionSchedule.modify(
        plan.provider_subscription_schedule_id,
        default_settings={"default_payment_method": new_payment_method_id},
    )

    # 3. Subscription — default_payment_method.
    stripe.Subscription.modify(
        plan.provider_subscription_id,
        default_payment_method=new_payment_method_id,
    )

    # ── Re-fetch + assert all three. Do NOT trust the mutation
    #    responses — Stripe echoes what you sent, not what it stored.
    #    Only a fresh GET confirms persistence. ──
    customer = stripe.Customer.retrieve(plan.provider_customer_id)
    cust_pm = _sfield(customer, "invoice_settings", "default_payment_method")
    if cust_pm != new_payment_method_id:
        raise PaymentMethodSwapError(
            f"Customer.invoice_settings.default_payment_method="
            f"{cust_pm!r} != expected {new_payment_method_id!r} "
            f"(plan={plan.id})"
        )

    schedule = stripe.SubscriptionSchedule.retrieve(
        plan.provider_subscription_schedule_id,
    )
    sched_pm = _sfield(schedule, "default_settings", "default_payment_method")
    if sched_pm != new_payment_method_id:
        raise PaymentMethodSwapError(
            f"SubscriptionSchedule.default_settings.default_payment_method="
            f"{sched_pm!r} != expected {new_payment_method_id!r} "
            f"(plan={plan.id})"
        )

    subscription = stripe.Subscription.retrieve(plan.provider_subscription_id)
    sub_pm = _sfield(subscription, "default_payment_method")
    if sub_pm != new_payment_method_id:
        raise PaymentMethodSwapError(
            f"Subscription.default_payment_method={sub_pm!r} != "
            f"expected {new_payment_method_id!r} (plan={plan.id})"
        )

    logger.info(
        "FIP4B2 swap PM: plan=%s pm=%s verified on customer + schedule + subscription",
        plan.id, new_payment_method_id,
    )


# ---------------------------------------------------------------------------
# Retry the overdue invoice
# ---------------------------------------------------------------------------


def retry_overdue_invoice(*, plan: PurchasePlan) -> tuple[str, str]:
    """Retry ``plan.last_failed_invoice_id`` via ``stripe.Invoice.pay``.

    Validates:
      * ``plan.last_failed_invoice_id`` is set.
      * The invoice belongs to ``plan.provider_subscription_id``
        (defence against a stale ptr from an unrelated Subscription).
      * The invoice status is one of the retryable states —
        ``open`` (Stripe's default for a failed collection),
        ``uncollectible`` (Smart Retries gave up but member can
        still pay). ``paid`` short-circuits as an already-recovered
        no-op; ``draft`` / ``void`` are refused.

    Idempotency key: ``pplan:{plan.id}:retry_invoice:{invoice_id}:v1``
    — same invoice, same plan → same key. Stripe returns the cached
    result on a webhook redelivery; no double-charge.

    Returns ``(invoice_id, final_status)`` where ``final_status`` is
    the observed status after the pay attempt. Common values:
      * ``paid`` — success; the ``invoice.payment_succeeded`` webhook
        will fire (or has fired) and handle the domain state
        transition + access reinstatement via the existing FIP3
        pipeline.
      * ``declined`` — synthetic status used when
        ``stripe.CardError`` is caught (a legitimate commerce
        outcome). The existing ``invoice.payment_failed`` webhook
        keeps the plan in its recoverable state; the member can try
        the repair flow again with a different card.

    Exception discipline:
      * ``stripe.CardError`` → caught, returns
        ``(invoice_id, 'declined')``.
      * All other ``stripe.StripeError`` → re-raised so the caller
        (webhook lease) can retry.
      * :class:`RepairInvoiceNotRetryable` → raised for missing /
        stale / non-retryable invoice pointers, so the caller can
        skip the pay attempt cleanly without treating it as
        infrastructure failure.
    """
    _bind_key()

    invoice_id = plan.last_failed_invoice_id
    if not invoice_id:
        raise RepairInvoiceNotRetryable(
            f"plan {plan.id} has no last_failed_invoice_id — nothing to retry"
        )
    if not plan.provider_subscription_id:
        raise RepairInvoiceNotRetryable(
            f"plan {plan.id} has no provider_subscription_id"
        )

    invoice = stripe.Invoice.retrieve(invoice_id)
    inv_status = _sfield(invoice, "status")
    inv_subscription = _extract_invoice_subscription(invoice)

    # Ownership — the invoice must belong to our Subscription.
    if inv_subscription and inv_subscription != plan.provider_subscription_id:
        raise RepairInvoiceNotRetryable(
            f"invoice {invoice_id} subscription={inv_subscription!r} does not "
            f"match plan.provider_subscription_id="
            f"{plan.provider_subscription_id!r} (plan={plan.id})"
        )

    if inv_status == "paid":
        logger.info(
            "FIP4B2 retry: invoice %s already paid (plan=%s) — no-op",
            invoice_id, plan.id,
        )
        return invoice_id, "paid"

    if inv_status not in ("open", "uncollectible"):
        raise RepairInvoiceNotRetryable(
            f"invoice {invoice_id} status={inv_status!r} not retryable "
            f"(plan={plan.id})"
        )

    try:
        paid = stripe.Invoice.pay(
            invoice_id,
            idempotency_key=_idem(
                plan.id, f"retry_invoice:{invoice_id}", version="v1",
            ),
        )
    except stripe.CardError as exc:
        logger.warning(
            "FIP4B2 retry: card declined on plan=%s invoice=%s: %s",
            plan.id, invoice_id, exc,
        )
        return invoice_id, "declined"

    paid_status = _sfield(paid, "status") or ""
    logger.info(
        "FIP4B2 retry: plan=%s invoice=%s → status=%s",
        plan.id, invoice_id, paid_status,
    )
    return invoice_id, paid_status


# ---------------------------------------------------------------------------
# Small helpers — dict OR StripeObject safe access
# ---------------------------------------------------------------------------


def _sfield(obj: Any, *path: str, default: Any = None) -> Any:
    """Local mirror of ``webhooks.finite_plan_handlers._sfield``.

    Kept private to this module so the repair service has no
    dependency on the webhook handler module. Same semantics:
    dict-safe + StripeObject-safe subscript walk, returning
    ``default`` on any miss.
    """
    cur: Any = obj
    for key in path:
        if cur is None:
            return default
        try:
            if isinstance(cur, dict):
                if key in cur:
                    cur = cur[key]
                else:
                    return default
            else:
                # StripeObject supports subscript + ``in`` but not .get()
                try:
                    if key in cur:
                        cur = cur[key]
                    else:
                        return default
                except TypeError:
                    val = getattr(cur, key, default)
                    if val is default:
                        return default
                    cur = val
        except (KeyError, AttributeError):
            return default
    return cur


def _extract_invoice_subscription(invoice: Any) -> str | None:
    """Return the Subscription id linked to a Stripe Invoice payload.

    Mirrors the extraction logic in
    :func:`app.webhooks.finite_plan_handlers._extract_subscription_id`
    so the repair service does NOT import from the webhook module.
    Current API surfaces it at
    ``invoice.parent.subscription_details.subscription``; older SDKs
    exposed a top-level ``invoice.subscription``.
    """
    parent_type = _sfield(invoice, "parent", "type")
    if parent_type == "subscription_details":
        current = _sfield(invoice, "parent", "subscription_details", "subscription")
        if current:
            return current
    legacy = _sfield(invoice, "subscription")
    if legacy:
        return legacy
    return None
