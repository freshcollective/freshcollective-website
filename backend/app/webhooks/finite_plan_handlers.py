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
from app.services import (
    finite_plan_lifecycle,
    finite_plan_repair,
    stripe_finite_plan,
)
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


def _compose_balance_settlement_note(
    invoice: Any, *, invoice_total: int, provider_amount_paid: int,
) -> str | None:
    """Return an audit note for the PaymentTransaction row when the
    invoice was satisfied wholly or partly via Stripe customer
    balance credit (i.e. ``amount_paid < total``). Returns ``None``
    for normal card-funded invoices — those rows carry no note.

    The note is intentionally precise (cents, both balance
    boundaries) so a FIP4C payouts reconciliation can migrate the
    signal into a proper ``provider_amount_paid`` column later
    without needing a Stripe refetch. Format is stable and
    machine-parseable enough for a future migration to structure.
    """
    if provider_amount_paid >= invoice_total:
        return None
    starting_balance = _sfield(invoice, "starting_balance")
    ending_balance = _sfield(invoice, "ending_balance")
    return (
        f"Invoice satisfied partly/fully via Stripe customer balance. "
        f"invoice_total={invoice_total}c; "
        f"provider_amount_paid={provider_amount_paid}c; "
        f"starting_balance={starting_balance}c; "
        f"ending_balance={ending_balance}c."
    )


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

    # ── FIP4A — immediate first-invoice collection ─────────────────
    # Stripe's default `next_payment_attempt` for a
    # `subscription_create` invoice is ~1 hour after creation. That
    # leaves the member staring at "we're confirming your first
    # payment" for up to an hour. We finalise + pay the invoice
    # server-side right now so the normal
    # ``invoice.payment_succeeded`` webhook can activate access
    # in seconds, not minutes.
    #
    # Access is STILL granted only by that webhook — this call
    # doesn't touch the plan status, doesn't create the
    # PaymentTransaction, doesn't apply grants. All of that flows
    # through the existing ``_do_invoice_succeeded`` handler.
    #
    # Exception discipline is the key correctness detail. A
    # blanket ``except Exception: raise`` would treat a legitimate
    # card decline the same as a transient network blip and
    # cause the webhook (via the FIP1 lease) to endlessly redeliver.
    # We split:
    #
    #   * stripe.CardError → catch. Cancel the SubscriptionSchedule
    #     so Stripe stops charging, mark plan ``failed`` with
    #     ``cancelled_reason='first_payment_failed'``, log for
    #     operator visibility. Rule D unblocks; the member can
    #     retry with a different card on the same PaymentOption.
    #     Stripe will separately fire ``invoice.payment_failed``;
    #     the lifecycle handler's pending_setup branch is a no-op
    #     because the row is already ``failed``.
    #
    #   * Non-"paid" invoice status after Invoice.pay (e.g.
    #     `requires_action` from a 3DS card) → treat as effective
    #     failure. Same terminal handling as CardError. FIP4B may
    #     later introduce a proper authentication-required repair
    #     UX; for FIP4A we do the safe thing and terminate.
    #
    #   * Any other stripe.StripeError (rate limit, API 5xx,
    #     network) → rethrow. The webhook lease + Stripe redelivery
    #     retry.
    #
    # The plan-status guard at the top of _do_setup_completed
    # (checks plan.status == pending_setup) prevents a redelivery
    # from re-attempting the collection after the plan has been
    # activated or terminated by an earlier delivery.
    subscription_id = plan.provider_subscription_id
    if subscription_id is None:
        # Extremely rare — the SubscriptionSchedule.create response
        # sometimes lacks the subscription id. Refetch.
        sched = stripe_finite_plan.retrieve_subscription_schedule(
            plan.provider_subscription_schedule_id,
        )
        subscription_id = (
            sched["subscription"] if isinstance(sched, dict)
            else getattr(sched, "subscription", None)
        )
        if subscription_id:
            plan.provider_subscription_id = subscription_id
            db.commit()

    if subscription_id is None:
        logger.warning(
            "FIP4A first-invoice accel: plan=%s has no subscription id after "
            "schedule create — cannot accelerate; falling back to Stripe's "
            "1-hour attempt", plan.id,
        )
        return

    try:
        invoice_id, final_status = stripe_finite_plan.finalize_and_pay_first_invoice(
            plan=plan, subscription_id=subscription_id,
        )
    except stripe.CardError as exc:
        # Legitimate card decline on the initial invoice.
        logger.warning(
            "FIP4A first-invoice accel: card declined on plan=%s subscription=%s: %s",
            plan.id, subscription_id, exc,
        )
        _terminate_plan_on_first_payment_failure(
            db, plan=plan,
            reason="first_payment_failed",
            note=f"card declined: {(exc.user_message or str(exc))[:200]}",
        )
        return
    except stripe.StripeError:
        # Transient / API-level error. Let the webhook redelivery
        # + FIP1 lease retry — plan stays pending_setup for the
        # next attempt.
        raise

    if final_status != "paid":
        # Non-paid outcomes (e.g. requires_action from a 3DS card,
        # unexpected open status) — treat as effective first-payment
        # failure so the member is not left in indefinite pending_setup.
        logger.warning(
            "FIP4A first-invoice accel: plan=%s invoice=%s did not reach 'paid' "
            "(status=%s) — terminating as first_payment_failed",
            plan.id, invoice_id, final_status,
        )
        _terminate_plan_on_first_payment_failure(
            db, plan=plan,
            reason="first_payment_failed",
            note=f"initial invoice status={final_status!r} after Invoice.pay",
        )
        return

    # Success — Stripe just fired invoice.payment_succeeded (or is
    # about to). That webhook activates the plan via the existing
    # _do_invoice_succeeded handler; nothing more to do here.
    logger.info(
        "FIP4A first-invoice accel: plan=%s invoice=%s paid — "
        "awaiting invoice.payment_succeeded webhook for activation",
        plan.id, invoice_id,
    )


def _terminate_plan_on_first_payment_failure(
    db: Session, *,
    plan: PurchasePlan,
    reason: str,
    note: str | None,
) -> None:
    """First-payment-failure cleanup — PROVIDER-FIRST semantics.

    The local ``PurchasePlan`` does NOT transition to ``failed``
    until Stripe confirms the ``SubscriptionSchedule`` is
    cancelled (or already terminal). Reason: Rule D allows a
    replacement plan the moment the current one is out of the
    ``pending_setup`` / ``active`` / ``payment_problem`` set.
    Marking the local plan ``failed`` while the provider schedule
    is still live risks the member having two billable Stripe
    plans running simultaneously — one abandoned, one live.

    Sequence:

      1. Best-effort call ``cancel_finite_subscription_schedule``
         with ``invoice_now=False, prorate=False``.
      2. On success (or "already canceled/completed/not-found"):
         mark the plan ``failed`` locally and commit.
      3. On a transient ``stripe.StripeError``: leave the plan in
         its current state (``pending_setup``) and re-raise. The
         webhook lease + Stripe redelivery will re-run the whole
         setup handler; the top-of-handler status guard lets it
         through because the plan is still ``pending_setup``; the
         idempotency-keyed ``Invoice.pay`` returns Stripe's cached
         card-decline; we re-enter this helper and retry the
         cancel. Eventually succeeds (or a human intervenes).

    Idempotency at the entry:

      * If plan is already ``failed`` (an earlier delivery of this
        webhook already terminated it), still make a best-effort
        cancel call — the provider cancel is itself idempotent
        (no-op if already canceled). A transient Stripe error here
        is logged but not re-raised; the plan is already terminal
        and Rule D already unblocked, so there is no additional
        risk to defer.
    """
    if plan.status == PurchasePlanStatus.failed:
        try:
            stripe_finite_plan.cancel_finite_subscription_schedule(plan=plan)
        except stripe.StripeError as exc:
            logger.warning(
                "FIP4A terminate: stripe cancel raised on already-failed plan=%s: %s",
                plan.id, exc,
            )
        return

    # PROVIDER FIRST — a transient Stripe error here MUST propagate.
    # Do not mark ``failed`` unless we know the provider plan is
    # dead. The caller (setup handler / invoice_failed handler) sees
    # the exception, the FIP1 lease drops back to ``failed`` marker,
    # Stripe redelivery re-runs the whole webhook, we retry cancel.
    stripe_finite_plan.cancel_finite_subscription_schedule(plan=plan)

    # Only after Stripe confirms termination do we transition
    # locally and unblock Rule D.
    now = datetime.utcnow()
    plan.status = PurchasePlanStatus.failed
    plan.cancelled_at = plan.cancelled_at or now
    plan.cancelled_reason = reason
    if note:
        plan.cancelled_reason = f"{reason}: {note}"[:250]
    plan.updated_at = now
    db.commit()
    logger.info(
        "FIP4A terminate: plan=%s → failed after provider cleanup confirmed "
        "(reason=%s)", plan.id, plan.cancelled_reason,
    )


# ---------------------------------------------------------------------------
# FIP4B2 — repair setup Session completion
# ---------------------------------------------------------------------------


_REPAIR_RECOVERABLE = (
    PurchasePlanStatus.payment_problem,
    PurchasePlanStatus.suspended,
)


def handle_finite_plan_repair_completed(
    session: dict, db: Session, metadata: dict,
    *,
    event_livemode: bool,
) -> None:
    """``checkout.session.completed`` handler for FIP4B2 repair Sessions.

    Wrapped in :func:`process_webhook_event` for durable idempotency
    keyed on the Stripe Session id. The handler itself is
    idempotent: it revalidates plan state, re-fetches the PM
    surfaces before retrying, and Stripe.Invoice.pay carries a
    per-invoice idempotency key so a replay cannot double-charge.
    """
    session_id: str = session.get("id", "")
    plan_id: str = metadata.get("purchase_plan_id", "")

    def _handler() -> None:
        _do_repair_completed(
            db,
            session=session,
            plan_id=plan_id,
            payer_user_id=metadata.get("payer_user_id", ""),
            event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=f"repair_session:{session_id}",
        event_type="checkout.session.completed:finite_plan_repair",
        handler=_handler,
    )


def _do_repair_completed(
    db: Session,
    *,
    session: dict,
    plan_id: str,
    payer_user_id: str,
    event_livemode: bool,
) -> None:
    if not plan_id:
        logger.error(
            "FIP4B2 repair: missing purchase_plan_id in metadata "
            "(session=%s)", session.get("id"),
        )
        raise SkipWebhookEvent("missing purchase_plan_id")

    plan = _load_plan_locked(db, plan_id)
    if plan is None:
        logger.error(
            "FIP4B2 repair: PurchasePlan %s not found (session=%s)",
            plan_id, session.get("id"),
        )
        raise SkipWebhookEvent(f"plan {plan_id} not found")

    # Ownership re-check — never trust the metadata alone. The
    # metadata was written server-side when the endpoint opened the
    # Session, but replay after a data migration / operator reassign
    # could see it drift. If they no longer match, refuse.
    if payer_user_id and plan.member_user_id != payer_user_id:
        logger.error(
            "FIP4B2 repair: metadata payer_user_id=%s does not match "
            "plan.member_user_id=%s (plan=%s) — refusing",
            payer_user_id, plan.member_user_id, plan.id,
        )
        raise SkipWebhookEvent("payer_user_id mismatch")

    # Mode boundary — same rule as the setup handler.
    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        logger.warning(
            "FIP4B2 repair: livemode mismatch event=%s plan=%s (plan.id=%s)",
            event_livemode, plan.stripe_mode, plan.id,
        )
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, "
            f"plan.stripe_mode={plan.stripe_mode})"
        )

    # Recoverability re-check — if the plan is no longer in a
    # recoverable state (e.g. an out-of-order invoice.payment_succeeded
    # already fired for a different retry attempt and lifted it back
    # to ``active``), skip. Nothing to repair.
    if plan.status not in _REPAIR_RECOVERABLE:
        logger.info(
            "FIP4B2 repair: plan %s in status=%s — not recoverable; skipping "
            "(session=%s)",
            plan.id, plan.status.value, session.get("id"),
        )
        raise SkipWebhookEvent(
            f"plan {plan.id} status={plan.status.value} — not recoverable"
        )

    # Retrieve the fully-hydrated Session so we can read setup_intent
    # → payment_method. Customer was pre-bound on Session creation.
    stripe_session = finite_plan_repair.retrieve_completed_repair_session(
        session.get("id", "")
    )
    setup_intent = getattr(stripe_session, "setup_intent", None)
    if setup_intent is None:
        raise RuntimeError(
            "FIP4B2 repair: no setup_intent on completed Session "
            f"(plan={plan.id})"
        )
    new_pm = getattr(setup_intent, "payment_method", None)
    if not new_pm:
        raise RuntimeError(
            f"FIP4B2 repair: setup_intent has no payment_method (plan={plan.id})"
        )

    # Verify the Session's Customer is still the plan's Customer.
    # A Session opened by our route is always bound to
    # plan.provider_customer_id (see finite_plan_repair.create_repair_setup_session),
    # so any mismatch is either a manual test-mode Session or
    # corrupted metadata — refuse.
    session_customer = getattr(stripe_session, "customer", None)
    if session_customer is not None and not isinstance(session_customer, str):
        session_customer = getattr(session_customer, "id", None)
    if session_customer and session_customer != plan.provider_customer_id:
        logger.error(
            "FIP4B2 repair: Session customer=%s != plan customer=%s "
            "(plan=%s session=%s)",
            session_customer, plan.provider_customer_id, plan.id,
            session.get("id"),
        )
        raise SkipWebhookEvent("session customer does not match plan customer")

    # Persist the new PM id on the plan BEFORE swapping surfaces, so
    # a mid-way crash leaves the domain state consistent with what
    # Stripe about to do.
    prior_pm = plan.provider_payment_method_id
    plan.provider_payment_method_id = new_pm
    plan.updated_at = datetime.utcnow()
    db.commit()

    # Swap on all three surfaces. Aborts (raises PaymentMethodSwapError)
    # if any surface can't be verified. If the swap fails, leave the
    # plan in its current state — a future repair attempt can try
    # again. Do NOT proceed to Invoice.pay against ambiguous state.
    try:
        finite_plan_repair.swap_default_payment_method_all_surfaces(
            plan=plan, new_payment_method_id=new_pm,
        )
    except finite_plan_repair.PaymentMethodSwapError as exc:
        # Roll the PM pointer back so the plan still reflects the
        # last confirmed provider state (whatever Stripe actually
        # has). Log loudly; the member can try again.
        logger.error(
            "FIP4B2 repair: PM swap failed on plan=%s new_pm=%s — reverting "
            "local pointer to %s. Error: %s",
            plan.id, new_pm, prior_pm, exc,
        )
        plan.provider_payment_method_id = prior_pm
        plan.updated_at = datetime.utcnow()
        db.commit()
        raise SkipWebhookEvent(
            f"PM swap failed on plan {plan.id}: {exc}"
        )

    # Retry the overdue invoice. Card decline is a legitimate
    # commerce outcome; leave the plan alone (existing
    # invoice.payment_failed already keeps it in payment_problem /
    # suspended). Success delegates to invoice.payment_succeeded
    # via the normal FIP3 pipeline — nothing further to do here.
    try:
        invoice_id, status = finite_plan_repair.retry_overdue_invoice(plan=plan)
    except finite_plan_repair.RepairInvoiceNotRetryable as exc:
        logger.warning(
            "FIP4B2 repair: overdue invoice not retryable on plan=%s: %s. "
            "PM swap already succeeded; Stripe's Smart Retries can still "
            "recover the plan.",
            plan.id, exc,
        )
        return

    if status == "declined":
        logger.info(
            "FIP4B2 repair: card declined on plan=%s invoice=%s — plan "
            "remains recoverable, member can try again.",
            plan.id, invoice_id,
        )
        return

    logger.info(
        "FIP4B2 repair: plan=%s invoice=%s → status=%s. "
        "Awaiting invoice.payment_succeeded webhook for plan transition + "
        "access reinstatement.",
        plan.id, invoice_id, status,
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

    if invoice.get("status") != "paid":
        raise SkipWebhookEvent(
            f"invoice {invoice_id} status={invoice.get('status')} != paid"
        )

    # FIP4A — accounting: gross_amount_cents uses ``invoice.total``
    # (the contractual invoice amount) NOT ``invoice.amount_paid``
    # (the fresh card charge). A legitimately paid invoice may be
    # satisfied wholly or partly via Stripe customer balance credit;
    # the member's instalment obligation is the contractual amount,
    # and that's what the fee snapshot + Creator revenue calc off.
    # If ``amount_paid < total`` (balance-satisfied), we compose an
    # audit note so the PaymentTransaction row carries the
    # settlement evidence for later reconciliation / FIP4C payouts.
    invoice_total = int(invoice.get("total") or 0)
    provider_amount_paid = int(invoice.get("amount_paid") or 0)
    invoice_currency = (invoice.get("currency") or "").upper()
    charge_id = invoice.get("charge")
    payment_intent_id = invoice.get("payment_intent")
    audit_note = _compose_balance_settlement_note(
        invoice, invoice_total=invoice_total,
        provider_amount_paid=provider_amount_paid,
    )

    # ── FIP3 later-instalment path ─────────────────────────────────
    # Plans already past the first invoice go through the lifecycle
    # service, which records the per-invoice PaymentTransaction with
    # the correct installment_number, may transition the plan
    # (payment_problem/suspended → active on recovery, active →
    # completed on final instalment), and reinstates access when
    # coming back from suspended. Access is NOT re-applied — the
    # snapshot was already applied at first-invoice fulfilment.
    #
    # ``failed`` is included so a late final-payment reconciliation
    # (out-of-order subscription.deleted → invoice.payment_succeeded)
    # can lift the plan back to ``completed`` / ``active`` and
    # restore any access we suspended incorrectly. See §1 of the
    # FIP3 hardening brief.
    if plan.status in (
        PurchasePlanStatus.active,
        PurchasePlanStatus.payment_problem,
        PurchasePlanStatus.suspended,
        PurchasePlanStatus.failed,
    ):
        later_outcome = finite_plan_lifecycle.record_later_successful_instalment(
            db,
            plan=plan,
            invoice_id=invoice_id,
            invoice_amount_cents=invoice_total,
            invoice_currency=invoice_currency,
            subscription_id=subscription_id,
            charge_id=charge_id,
            payment_intent_id=payment_intent_id,
            now=datetime.utcnow(),
            audit_note=audit_note,
        )
        db.commit()
        # R3 — schedule routing for the recovery / completion event
        # (if the lifecycle transition produced one) after commit. No
        # BackgroundTasks in webhook context → sync dispatch, matching
        # the R2A/R2B pattern for webhook-originated events.
        if later_outcome.comms_event is not None:
            from app.comms.rollout import schedule_routing_if_needed
            schedule_routing_if_needed(
                None, later_outcome.comms_event, later_outcome.comms_event.event_type,
            )
        return

    if plan.status != PurchasePlanStatus.pending_setup:
        # ``cancelled`` / ``completed`` — terminal-and-authoritative;
        # a late invoice event is a no-op.
        logger.warning(
            "FIP invoice: plan %s in terminal status=%s — skipping (invoice=%s)",
            plan.id, plan.status, invoice_id,
        )
        raise SkipWebhookEvent(
            f"plan status={plan.status} terminal; invoice ignored"
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

    # Sanity — expected amount + currency. FIP4A: the CONTRACTUAL
    # amount (``invoice.total``) is the fulfilment gate, not the
    # freshly-collected card charge (``invoice.amount_paid``). A
    # legitimately paid invoice may be satisfied wholly or partly
    # via a Stripe customer balance credit; the member's obligation
    # is the contractual amount.
    if invoice_total != plan.installment_amount_cents:
        logger.error(
            "FIP2 invoice: total mismatch invoice=%s total=%s expected=%s plan=%s",
            invoice_id, invoice_total, plan.installment_amount_cents, plan.id,
        )
        raise RuntimeError(
            f"invoice total {invoice_total} != plan instalment "
            f"{plan.installment_amount_cents}"
        )
    if invoice_currency != plan.currency:
        raise RuntimeError(
            f"invoice currency {invoice_currency} != plan {plan.currency}"
        )

    # ── Create PaymentTransaction (instalment #1) ──────────────────
    now = datetime.utcnow()
    gross = invoice_total  # contractual (FIP4A rule); NOT amount_paid
    platform_fee = round(gross * plan.platform_fee_basis_points / 10000)
    net_creator = gross - platform_fee

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
        notes=audit_note,
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

    # R3 — emit ``purchase.completed`` (payment_mode='plan') for the
    # FIP first-instalment confirmation. Only reached on the genuine
    # ``pending_setup → active`` transition; the pending_setup guard
    # + provider_invoice_id uniqueness above short-circuit replays
    # before this point, so no duplicate email is possible for the
    # same first-instalment success.
    comms_event = None
    from app.services import purchase_lifecycle_emit as _r3
    from app.models.payment_option import PaymentOption
    from app.models.user import User as _User
    payment_option = (
        db.query(PaymentOption).filter(PaymentOption.id == plan.payment_option_id).first()
        if plan.payment_option_id else None
    )
    member = db.query(_User).filter(_User.id == plan.member_user_id).first()
    if member is not None:
        comms_event = _r3.emit_purchase_completed(
            db, user=member, payment_option=payment_option,
            payment_mode="plan",
            amount_cents=plan.installment_amount_cents,
            currency=plan.currency,
            plan=plan,
        )

    db.commit()

    logger.info(
        "FIP2 first invoice applied: plan=%s txn=%s invoice=%s "
        "entitlements=%d access_passes=%d",
        plan.id, txn.id, invoice_id,
        len(result.entitlements), len(result.access_passes),
    )

    if comms_event is not None:
        from app.comms.rollout import schedule_routing_if_needed
        schedule_routing_if_needed(None, comms_event, "purchase.completed")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FIP3 — invoice.payment_failed
# ---------------------------------------------------------------------------


def handle_invoice_payment_failed(
    invoice: dict, db: Session, *,
    provider_event_id: str, event_livemode: bool,
) -> None:
    """``invoice.payment_failed`` handler for finite payment plans."""
    def _handler() -> None:
        _do_invoice_failed(
            db, invoice=invoice, event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=provider_event_id,
        event_type="invoice.payment_failed",
        handler=_handler,
    )


def _do_invoice_failed(
    db: Session, *, invoice: dict, event_livemode: bool,
) -> None:
    invoice_id = _sfield(invoice, "id", default="")
    subscription_id = _extract_subscription_id(invoice)
    if not subscription_id:
        raise SkipWebhookEvent(
            f"invoice {invoice_id} has no subscription — not a plan invoice"
        )

    plan = _find_plan_by_subscription(db, subscription_id)
    if plan is None:
        raise SkipWebhookEvent(
            f"no PurchasePlan for subscription {subscription_id}"
        )

    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, plan.stripe_mode={plan.stripe_mode})"
        )

    failure_outcome = finite_plan_lifecycle.handle_invoice_failed_for_plan(
        db,
        plan=plan,
        invoice_id=invoice_id,
        failed_at=datetime.utcnow(),
    )
    db.commit()
    # R3 — schedule routing for ``payment.instalment_failed`` (if the
    # transition genuinely opened the grace window). Sync dispatch —
    # webhook context has no BackgroundTasks.
    if failure_outcome.comms_event is not None:
        from app.comms.rollout import schedule_routing_if_needed
        schedule_routing_if_needed(
            None, failure_outcome.comms_event, "payment.instalment_failed",
        )


# ---------------------------------------------------------------------------
# FIP3 — customer.subscription.deleted
# ---------------------------------------------------------------------------


def handle_subscription_deleted(
    subscription: dict, db: Session, *,
    provider_event_id: str, event_livemode: bool,
) -> None:
    """``customer.subscription.deleted`` — reconcile plan state.

    Distinguishes normal finite end (installments_paid == expected →
    completed) from abnormal end (paid < expected → failed + access
    suspended, source-aware).
    """
    def _handler() -> None:
        _do_subscription_deleted(
            db, subscription=subscription, event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=provider_event_id,
        event_type="customer.subscription.deleted",
        handler=_handler,
    )


def _do_subscription_deleted(
    db: Session, *, subscription: dict, event_livemode: bool,
) -> None:
    subscription_id = _sfield(subscription, "id", default="")
    if not subscription_id:
        raise SkipWebhookEvent("subscription payload missing id")

    plan = _find_plan_by_subscription(db, subscription_id)
    if plan is None:
        # Not ours — Creator subscriptions or unrelated test noise.
        raise SkipWebhookEvent(
            f"no PurchasePlan for subscription {subscription_id}"
        )

    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, plan.stripe_mode={plan.stripe_mode})"
        )

    finite_plan_lifecycle.handle_subscription_deleted_for_plan(
        db, plan=plan, now=datetime.utcnow(),
    )
    db.commit()


# ---------------------------------------------------------------------------
# FIP3 — subscription_schedule.completed
# ---------------------------------------------------------------------------


def handle_schedule_completed(
    schedule: dict, db: Session, *,
    provider_event_id: str, event_livemode: bool,
) -> None:
    """``subscription_schedule.completed`` — belt-and-braces confirmation
    that the finite plan reached its natural end. Complements
    ``customer.subscription.deleted``; whichever arrives first
    performs the transition, the other is a no-op.
    """
    def _handler() -> None:
        _do_schedule_completed(
            db, schedule=schedule, event_livemode=event_livemode,
        )

    process_webhook_event(
        db,
        provider="stripe",
        provider_event_id=provider_event_id,
        event_type="subscription_schedule.completed",
        handler=_handler,
    )


def _do_schedule_completed(
    db: Session, *, schedule: dict, event_livemode: bool,
) -> None:
    schedule_id = _sfield(schedule, "id", default="")
    if not schedule_id:
        raise SkipWebhookEvent("schedule payload missing id")

    plan = (
        db.query(PurchasePlan)
        .filter(PurchasePlan.provider_subscription_schedule_id == schedule_id)
        .with_for_update()
        .one_or_none()
    )
    if plan is None:
        raise SkipWebhookEvent(
            f"no PurchasePlan for subscription_schedule {schedule_id}"
        )

    plan_livemode = (plan.stripe_mode == "live")
    if event_livemode != plan_livemode:
        raise SkipWebhookEvent(
            f"livemode mismatch (event={event_livemode}, plan.stripe_mode={plan.stripe_mode})"
        )

    finite_plan_lifecycle.handle_schedule_completed_for_plan(
        db, plan=plan, now=datetime.utcnow(),
    )
    db.commit()


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
