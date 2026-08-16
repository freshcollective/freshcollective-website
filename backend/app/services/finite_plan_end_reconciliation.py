"""FIP3 — order-independent finite-end reconciliation.

Stripe does not guarantee webhook delivery order. So a plan whose
final invoice successfully paid may see ``customer.subscription.deleted``
arrive BEFORE the ``invoice.payment_succeeded`` for its final
instalment. If the naive path from FIP3 v1 evaluated
``installments_paid == installments_expected`` at the instant the
end-event landed, it would misclassify the plan as an abnormal
end and suspend legitimately-earned access.

This module removes that risk. Both provider-end handlers
(``customer.subscription.deleted`` / ``subscription_schedule.completed``)
delegate here BEFORE making a terminal decision. The reconciler:

  1. Fetches the authoritative invoice inventory from Stripe
     (``services.stripe_finite_plan.list_invoices_for_subscription``).
  2. Reconciles any *paid* invoice not yet represented in
     ``payment_transactions`` through the existing idempotent
     later-instalment path
     (``services.finite_plan_lifecycle.record_later_successful_instalment``).
  3. Re-reads the plan's counters (now up-to-date with provider
     truth) and returns a deterministic outcome:
       * ``completed``   — all expected instalments paid
       * ``abnormal``    — provider confirms no more can arrive
                            and the plan is under-paid
       * ``deferred``    — provider state is ambiguous (open /
                            uncollectible / unknown invoices, or
                            we couldn't reach the provider)
     Callers translate ``completed`` / ``abnormal`` into the plan
     status transition and act on ``deferred`` by NOT making a
     terminal change and logging for later reconciliation.

The reconciler is idempotent. It never mints access; it never
revokes access. Access transitions are done by the plan-lifecycle
service using the counters this function reconciles.

Dependency injection
--------------------
The Stripe fetcher is injected as a callable so tests can seed
provider state deterministically without mocking the SDK. The
default is the real Stripe wrapper.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction, PaymentTransactionStatus
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import finite_plan_lifecycle
from app.services import stripe_finite_plan


logger = logging.getLogger(__name__)


ReconciliationDecision = str  # "completed" | "abnormal" | "deferred"

DECISION_COMPLETED = "completed"
DECISION_ABNORMAL = "abnormal"
DECISION_DEFERRED = "deferred"


InvoiceFetcher = Callable[[str], list[dict]]
"""Contract: given a Stripe subscription id, return a list of
invoice dicts (matching ``stripe.Invoice.to_dict()`` shape). Used
for dependency injection so tests do not talk to Stripe."""


@dataclass
class ReconciliationOutcome:
    decision: ReconciliationDecision
    plan_id: str
    installments_paid_before: int
    installments_paid_after: int
    installments_expected: int
    provider_paid_invoice_ids: list[str]
    reconciled_invoice_ids: list[str]
    ambiguous_invoice_ids: list[str]
    note: str | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reconcile_finite_plan_end(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
    invoice_fetcher: InvoiceFetcher | None = None,
) -> ReconciliationOutcome:
    """Reconcile a finite plan against Stripe's authoritative invoice
    inventory and return a deterministic terminal decision.

    Caller must hold the plan row lock. This function neither
    commits nor rolls back — the caller commits after acting on
    the returned decision.

    ``invoice_fetcher`` defaults to
    :func:`stripe_finite_plan.list_invoices_for_subscription`.
    Tests inject a callable returning canned invoice lists.
    """
    fetcher = invoice_fetcher or stripe_finite_plan.list_invoices_for_subscription

    subscription_id = plan.provider_subscription_id
    installments_paid_before = plan.installments_paid

    if not subscription_id:
        # No provider linkage — can't reconcile. Defer terminal
        # decision. The plan will be picked up by ops tooling.
        return ReconciliationOutcome(
            decision=DECISION_DEFERRED,
            plan_id=plan.id,
            installments_paid_before=installments_paid_before,
            installments_paid_after=installments_paid_before,
            installments_expected=plan.installments_expected,
            provider_paid_invoice_ids=[],
            reconciled_invoice_ids=[],
            ambiguous_invoice_ids=[],
            note="no provider_subscription_id on plan; cannot reconcile",
        )

    # ── Fetch provider truth ────────────────────────────────────────
    try:
        provider_invoices = fetcher(subscription_id)
    except Exception as exc:  # noqa: BLE001 — provider outage/network
        logger.warning(
            "FIP3 end-reconcile: failed to fetch invoices for plan=%s "
            "subscription=%s: %s", plan.id, subscription_id, exc,
        )
        return ReconciliationOutcome(
            decision=DECISION_DEFERRED,
            plan_id=plan.id,
            installments_paid_before=installments_paid_before,
            installments_paid_after=installments_paid_before,
            installments_expected=plan.installments_expected,
            provider_paid_invoice_ids=[],
            reconciled_invoice_ids=[],
            ambiguous_invoice_ids=[],
            note=f"invoice fetch failed: {exc}",
        )

    paid_invoices, ambiguous_invoices = _partition_invoices(provider_invoices)
    provider_paid_ids = [inv["id"] for inv in paid_invoices]
    ambiguous_ids = [inv["id"] for inv in ambiguous_invoices]

    # ── Reconcile paid invoices not yet ledgered ────────────────────
    reconciled_ids = _reconcile_missing_paid_invoices(
        db, plan=plan, paid_invoices=paid_invoices, now=now,
        subscription_id=subscription_id,
    )

    installments_paid_after = plan.installments_paid

    # ── Decide ──────────────────────────────────────────────────────
    expected = plan.installments_expected
    if installments_paid_after >= expected:
        return ReconciliationOutcome(
            decision=DECISION_COMPLETED,
            plan_id=plan.id,
            installments_paid_before=installments_paid_before,
            installments_paid_after=installments_paid_after,
            installments_expected=expected,
            provider_paid_invoice_ids=provider_paid_ids,
            reconciled_invoice_ids=reconciled_ids,
            ambiguous_invoice_ids=ambiguous_ids,
        )

    # Under-paid. Is the provider truly done?
    #
    # ``ambiguous_invoices`` = anything not clearly paid, not clearly
    # dead. If ANY of the outstanding invoices are open / draft /
    # uncollectible we defer — Stripe may still retry or a delayed
    # payment event may arrive. Only when every invoice is either
    # ``paid`` (already reconciled above) or terminally dead (``void``)
    # AND the paid count is still short do we call it abnormal.
    #
    # We also defer if provider inventory is shorter than expected;
    # invoice creation may be lagging behind the subscription end
    # event. Playing it safe here costs us at most one reconciliation
    # tick.
    provider_invoice_count = len(provider_invoices)
    if provider_invoice_count < expected:
        return ReconciliationOutcome(
            decision=DECISION_DEFERRED,
            plan_id=plan.id,
            installments_paid_before=installments_paid_before,
            installments_paid_after=installments_paid_after,
            installments_expected=expected,
            provider_paid_invoice_ids=provider_paid_ids,
            reconciled_invoice_ids=reconciled_ids,
            ambiguous_invoice_ids=ambiguous_ids,
            note=(
                f"provider shows {provider_invoice_count} invoice(s) but "
                f"plan expects {expected}; deferring terminal decision"
            ),
        )

    if ambiguous_invoices:
        return ReconciliationOutcome(
            decision=DECISION_DEFERRED,
            plan_id=plan.id,
            installments_paid_before=installments_paid_before,
            installments_paid_after=installments_paid_after,
            installments_expected=expected,
            provider_paid_invoice_ids=provider_paid_ids,
            reconciled_invoice_ids=reconciled_ids,
            ambiguous_invoice_ids=ambiguous_ids,
            note=(
                f"{len(ambiguous_invoices)} outstanding invoice(s) in "
                f"non-terminal state: {ambiguous_ids}"
            ),
        )

    # Provider inventory ≥ expected, none paid over the shortfall,
    # none ambiguous. Legitimate abnormal end.
    return ReconciliationOutcome(
        decision=DECISION_ABNORMAL,
        plan_id=plan.id,
        installments_paid_before=installments_paid_before,
        installments_paid_after=installments_paid_after,
        installments_expected=expected,
        provider_paid_invoice_ids=provider_paid_ids,
        reconciled_invoice_ids=reconciled_ids,
        ambiguous_invoice_ids=ambiguous_ids,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _partition_invoices(
    invoices: Iterable[dict],
) -> tuple[list[dict], list[dict]]:
    """Split provider invoices into (paid, ambiguous).

    ``paid``       — ``status == 'paid'`` (and ``amount_paid > 0``
                     when present — a zero-amount 'paid' invoice is
                     an artefact we should never see on a finite
                     plan; safest to leave it out of the ledgered
                     count).
    ``ambiguous``  — anything not clearly paid and not clearly
                     terminal-dead. ``void`` invoices are dropped
                     (Stripe won't retry a void). ``open`` /
                     ``draft`` / ``uncollectible`` remain in play.
    """
    paid: list[dict] = []
    ambiguous: list[dict] = []
    for inv in invoices:
        status = (inv.get("status") or "").lower()
        if status == "paid":
            amount = inv.get("amount_paid")
            # amount_paid may be missing on very old test fixtures;
            # trust ``status='paid'`` in that case.
            if amount is None or amount > 0:
                paid.append(inv)
                continue
        if status in ("void",):
            # Terminally dead — Stripe will not collect on this.
            continue
        ambiguous.append(inv)
    return paid, ambiguous


def _reconcile_missing_paid_invoices(
    db: Session, *,
    plan: PurchasePlan,
    paid_invoices: list[dict],
    subscription_id: str,
    now: datetime,
) -> list[str]:
    """Drive every paid provider invoice through the idempotent
    later-instalment path if we don't already have a succeeded
    PaymentTransaction row for it. Returns the list of invoice ids
    the reconciler actually posted.

    Sort by ``created`` so instalment ordinals track wall time.
    """
    if not paid_invoices:
        return []

    invoice_ids = [inv["id"] for inv in paid_invoices]
    existing_rows = (
        db.query(PaymentTransaction.provider_invoice_id)
        .filter(
            PaymentTransaction.provider_invoice_id.in_(invoice_ids),
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
        )
        .all()
    )
    already_ledgered = {row.provider_invoice_id for row in existing_rows}

    posted: list[str] = []
    ordered = sorted(paid_invoices, key=lambda i: i.get("created") or 0)
    for inv in ordered:
        inv_id = inv["id"]
        if inv_id in already_ledgered:
            continue
        try:
            finite_plan_lifecycle.record_later_successful_instalment(
                db,
                plan=plan,
                invoice_id=inv_id,
                invoice_amount_cents=int(inv.get("amount_paid") or 0),
                invoice_currency=(inv.get("currency") or "").upper(),
                subscription_id=subscription_id,
                charge_id=inv.get("charge"),
                payment_intent_id=inv.get("payment_intent"),
                now=now,
            )
            posted.append(inv_id)
        except Exception:
            logger.exception(
                "FIP3 end-reconcile: failed to reconcile invoice %s for plan %s",
                inv_id, plan.id,
            )
            # Continue — a single bad invoice must not block the
            # reconciliation of the rest.
    if posted:
        logger.info(
            "FIP3 end-reconcile: reconciled %d missing paid invoice(s) for "
            "plan=%s: %s", len(posted), plan.id, posted,
        )
    return posted
