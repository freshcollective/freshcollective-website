"""FIP3 — later-instalment lifecycle for finite payment plans.

Owns every state transition beyond FIP2's first-invoice activation:

    active            → active            (later successful instalment)
    active            → payment_problem   (invoice.payment_failed opens grace)
    payment_problem   → active            (recovery inside grace)
    payment_problem   → suspended         (grace expired, reconciler)
    suspended         → active            (recovery after suspension)
    active            → completed         (final successful instalment)

Source-aware access effects are applied via
:func:`_apply_access_effects_for_plan_state`, which consults
``services.access_grant_records`` to answer "does the user still
have this access from an unrelated source?" before touching
entitlement / access-pass rows.

Handler entrypoints
-------------------
* :func:`record_later_successful_instalment` — called from
  ``invoice.payment_succeeded`` for a plan already in ``active`` /
  ``payment_problem`` / ``suspended``.
* :func:`handle_invoice_failed_for_plan` — called from
  ``invoice.payment_failed``.
* :func:`sweep_expired_grace_plans` — called by the reconciler
  loop and the operator script.
* :func:`handle_subscription_deleted_for_plan` — called from
  ``customer.subscription.deleted``. Reconciles normal finite
  end vs. abnormal end.
* :func:`handle_schedule_completed_for_plan` — called from
  ``subscription_schedule.completed``. Same reconciliation.

Every entrypoint is idempotent (see the natural-key guards on
PaymentTransaction inserts and the state-check guards on
transitions). All are called from webhook handlers wrapped in the
FIP1 idempotency helper — but must themselves be replay-safe per
the durable-lease contract.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.access_grant_record import AccessGrantRecord
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementStatus,
    PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as _agr


logger = logging.getLogger(__name__)


# Locked v1 grace policy. Named constant so tests can override
# without editing the handler, but production must not vary it —
# the docstring on ``PurchasePlan.grace_expires_at`` promises
# 7 days.
GRACE_PERIOD_DAYS = 7


# ---------------------------------------------------------------------------
# Small dataclasses for reporting outcomes back to callers/tests
# ---------------------------------------------------------------------------


@dataclass
class LaterInstalmentOutcome:
    plan_id: str
    installment_number: int
    installments_paid: int
    installments_expected: int
    transaction_id: str | None
    transitioned_to: str | None  # PurchasePlanStatus value or None if no change


@dataclass
class FailureOutcome:
    plan_id: str
    invoice_id: str
    transitioned_to: str | None
    grace_expires_at: datetime | None
    reason: str | None = None


@dataclass
class SuspensionOutcome:
    plan_id: str
    suspended_entitlement_ids: list[str]
    suspended_access_pass_ids: list[str]
    preserved_entitlement_ids: list[str]
    preserved_access_pass_ids: list[str]


@dataclass
class ReinstatementOutcome:
    plan_id: str
    reinstated_entitlement_ids: list[str]
    reinstated_access_pass_ids: list[str]


# ---------------------------------------------------------------------------
# Later successful instalments
# ---------------------------------------------------------------------------


def record_later_successful_instalment(
    db: Session,
    *,
    plan: PurchasePlan,
    invoice_id: str,
    invoice_amount_cents: int,
    invoice_currency: str,
    subscription_id: str,
    charge_id: str | None,
    payment_intent_id: str | None,
    now: datetime,
    audit_note: str | None = None,
) -> LaterInstalmentOutcome:
    """Record a successful non-first instalment for an already-activated plan.

    Preconditions (caller must have verified):

    * ``plan`` is row-locked (``SELECT … FOR UPDATE``).
    * ``plan.status`` is ``active`` / ``payment_problem`` /
      ``suspended``. First-invoice activation is handled by
      :mod:`app.webhooks.finite_plan_handlers` (FIP2 path).
    * ``event.livemode`` already matches ``plan.stripe_mode``.
    * ``invoice.status == 'paid'``.

    Guarantees:

    * At most one :class:`PaymentTransaction` per Stripe invoice
      (natural-key check + the partial-unique index on
      ``provider_invoice_id``).
    * ``installment_number`` is derived under the row lock as
      ``plan.installments_paid + 1`` — deterministic when the
      caller holds the lock, safe under replay because a
      duplicate delivery finds the txn already exists and skips.

    ``invoice_amount_cents`` is the CONTRACTUAL invoice total
    (``invoice.total``), not ``invoice.amount_paid``. A legitimately
    paid invoice may be satisfied wholly or partly via a Stripe
    customer balance credit; the contractual amount is what the
    member's instalment obligation was and what FC's fee snapshot +
    Creator revenue are calculated against. See
    ``docs/finite-payment-plans-lifecycle.md`` and the accounting
    audit in the FIP4A brief.

    ``audit_note``, when supplied, is stored on the created/upgraded
    PaymentTransaction. Used to record balance-satisfaction
    evidence (invoice_total vs provider_amount_paid + Stripe
    starting/ending balance) so operators / FIP4C reconciliation
    can audit later without re-fetching Stripe.
    * On final instalment (``installments_paid == installments_expected``)
      the plan transitions to ``completed`` in the same commit.
    * On recovery from ``payment_problem`` or ``suspended`` the
      plan transitions to ``active`` (or ``completed``), grace
      fields are cleared, plan-scoped grant records are
      reinstated, and previously-suspended plan-owned
      entitlements / passes are restored.
    * The snapshot grants bundle is NOT re-applied — access already
      exists from the first-invoice fulfilment.
    """
    # Domain rule (FIP3): one finite-plan instalment = one Stripe
    # invoice = one ``PaymentTransaction`` row. Failed collection
    # attempts against that invoice are represented as
    # ``status='failed'`` on that same row (written by
    # :func:`handle_invoice_failed_for_plan`). When Stripe
    # ultimately collects on the same invoice — whether via a Smart
    # Retry, an operator retry, or a member-driven repair — we
    # UPGRADE the existing row from ``failed → succeeded`` rather
    # than creating a second ledger row. Failed-attempt evidence is
    # preserved via the Stripe/webhook event history and the row's
    # updated_at trail; the domain does not represent them as
    # separate instalments.
    existing_txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_invoice_id == invoice_id)
        .first()
    )
    if existing_txn is not None and existing_txn.status == PaymentTransactionStatus.succeeded:
        # True replay — plan counters already reflect this success.
        logger.info(
            "FIP3 later-instalment: replay — txn for invoice %s already "
            "succeeded (plan=%s txn=%s installment=%s)",
            invoice_id, plan.id, existing_txn.id,
            existing_txn.installment_number,
        )
        return LaterInstalmentOutcome(
            plan_id=plan.id,
            installment_number=existing_txn.installment_number or 0,
            installments_paid=plan.installments_paid,
            installments_expected=plan.installments_expected,
            transaction_id=existing_txn.id,
            transitioned_to=None,
        )

    # Sanity checks — same rules as first-invoice handler.
    if invoice_amount_cents != plan.installment_amount_cents:
        raise RuntimeError(
            f"FIP3 later-instalment: amount mismatch invoice={invoice_id} "
            f"got={invoice_amount_cents} expected={plan.installment_amount_cents} "
            f"plan={plan.id}"
        )
    if (invoice_currency or "").upper() != plan.currency:
        raise RuntimeError(
            f"FIP3 later-instalment: currency mismatch invoice={invoice_id} "
            f"got={invoice_currency!r} expected={plan.currency!r} plan={plan.id}"
        )

    # Instalment number under row lock — deterministic.
    installment_number = plan.installments_paid + 1
    if installment_number > plan.installments_expected:
        # Shouldn't happen — Stripe stops after the schedule's phase
        # duration. If it does, refuse rather than record a phantom.
        raise RuntimeError(
            f"FIP3 later-instalment: instalment_number {installment_number} "
            f"exceeds expected {plan.installments_expected} for plan {plan.id}"
        )

    # Fee snapshot — reuse the plan's fee bps for every instalment.
    gross = invoice_amount_cents
    platform_fee = round(gross * plan.platform_fee_basis_points / 10000)
    net_creator = gross - platform_fee

    if existing_txn is not None:
        # Recovery — upgrade the failed row in-place. Preserves the
        # original ``id``, the fk linkage to ``purchase_plan_id``, and
        # the invoice's natural-key uniqueness. Only the final-
        # outcome fields (status, fee math, provider payment ids,
        # installment_number, payout_status, timestamps, notes) change.
        txn = existing_txn
        txn.status = PaymentTransactionStatus.succeeded
        txn.fulfilment_status = PaymentFulfilmentStatus.applied
        txn.gross_amount_cents = gross
        txn.platform_fee_basis_points = plan.platform_fee_basis_points
        txn.platform_fee_cents = platform_fee
        txn.net_creator_amount_cents = net_creator
        txn.net_platform_amount_cents = platform_fee
        txn.provider_charge_id = charge_id
        txn.provider_payment_intent_id = payment_intent_id
        txn.installment_number = installment_number
        txn.payout_status = PayoutStatus.pending
        if audit_note:
            txn.notes = audit_note
        txn.updated_at = now
        logger.info(
            "FIP3 later-instalment: recovered failed txn %s "
            "(plan=%s invoice=%s installment=%d)",
            txn.id, plan.id, invoice_id, installment_number,
        )
    else:
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
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
            installment_number=installment_number,
            stripe_mode=plan.stripe_mode,
            payout_status=PayoutStatus.pending,
            notes=audit_note,
            created_at=now,
            updated_at=now,
        )
        db.add(txn)
    db.flush()

    # Advance the counter.
    prev_status = plan.status
    plan.installments_paid = installment_number
    plan.updated_at = now

    transitioned_to: str | None = None
    is_final = plan.installments_paid >= plan.installments_expected

    if is_final:
        # Final instalment — commercial obligation complete.
        plan.status = PurchasePlanStatus.completed
        plan.completed_at = now
        transitioned_to = PurchasePlanStatus.completed.value
        # If we were in payment_problem/suspended/failed when the
        # final payment landed, clear grace/suspension fields and
        # reinstate any plan-owned access that was suspended by a
        # prior (possibly out-of-order) provider-end event.
        _clear_grace_fields(plan)
        if prev_status in (PurchasePlanStatus.suspended, PurchasePlanStatus.failed):
            _reinstate_plan_access(db, plan=plan, now=now)
    else:
        if prev_status in (PurchasePlanStatus.payment_problem, PurchasePlanStatus.suspended):
            # Recovery — clear grace, restore access if we were suspended.
            _clear_grace_fields(plan)
            plan.status = PurchasePlanStatus.active
            transitioned_to = PurchasePlanStatus.active.value
            if prev_status == PurchasePlanStatus.suspended:
                _reinstate_plan_access(db, plan=plan, now=now)
        elif prev_status == PurchasePlanStatus.failed:
            # A delayed non-final instalment success on a plan we
            # previously marked failed (out-of-order provider-end
            # event). Recover to active + restore access so the
            # remaining payments can play out.
            _clear_grace_fields(plan)
            plan.status = PurchasePlanStatus.active
            transitioned_to = PurchasePlanStatus.active.value
            _reinstate_plan_access(db, plan=plan, now=now)

    # Ensure the plan-status change is flushed to the DB before we
    # return. The webhook wrapper commits, but tests + the
    # end-reconciliation caller both interrogate the DB right after
    # the function returns; a stale attribute would appear "active"
    # even though we transitioned.
    db.flush()

    logger.info(
        "FIP3 later-instalment applied: plan=%s installment=%d/%d "
        "invoice=%s txn=%s transitioned=%s",
        plan.id, installment_number, plan.installments_expected,
        invoice_id, txn.id, transitioned_to,
    )

    return LaterInstalmentOutcome(
        plan_id=plan.id,
        installment_number=installment_number,
        installments_paid=plan.installments_paid,
        installments_expected=plan.installments_expected,
        transaction_id=txn.id,
        transitioned_to=transitioned_to,
    )


# ---------------------------------------------------------------------------
# Failed instalments — opens the grace window
# ---------------------------------------------------------------------------


def handle_invoice_failed_for_plan(
    db: Session, *,
    plan: PurchasePlan,
    invoice_id: str,
    failed_at: datetime,
) -> FailureOutcome:
    """Record a failed instalment. Preserves an existing grace window on replay.

    Preconditions:
      * ``plan`` is row-locked.
      * The caller has confirmed the invoice belongs to this plan
        and event.livemode matches.

    Behaviour:
      * If the plan is already ``payment_problem`` with the SAME
        ``last_failed_invoice_id`` — noop (idempotent replay).
      * If the plan is already ``payment_problem`` with a
        DIFFERENT ``last_failed_invoice_id`` — a fresh failure on
        a fresh invoice. Preserve the ORIGINAL
        ``payment_problem_started_at`` + ``grace_expires_at`` (do
        not extend the window; the original commitment is what
        matters), but update ``last_failed_invoice_id`` so
        recovery correlates to the current invoice.
      * If the plan is ``active`` — open the window.
      * If the plan is ``suspended`` — leave the plan suspended;
        record the failure via an inserted failed-status txn so
        the ledger reflects reality.
      * If the plan is ``completed`` / ``cancelled`` / ``failed``
        / ``pending_setup`` — refuse (log + skip).
    """
    # Ledger: create a failed-status PaymentTransaction for the
    # invoice IF we haven't already. Guarded by the natural-key
    # check on provider_invoice_id.
    existing_txn = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_invoice_id == invoice_id)
        .first()
    )
    if existing_txn is not None and existing_txn.status == PaymentTransactionStatus.succeeded:
        # A delayed replay of a failure event on an invoice that
        # has ALREADY been recovered (out-of-order webhook delivery).
        # Do NOT downgrade the ledger and do NOT reopen a grace
        # window — the invoice has been paid, the plan is in its
        # correct post-recovery state.
        logger.info(
            "FIP3 invoice_failed: invoice %s already succeeded — "
            "ignoring replayed failure event (plan=%s txn=%s)",
            invoice_id, plan.id, existing_txn.id,
        )
        return FailureOutcome(
            plan_id=plan.id,
            invoice_id=invoice_id,
            transitioned_to=None,
            grace_expires_at=plan.grace_expires_at,
            reason="invoice already succeeded; failure event ignored",
        )
    if existing_txn is None:
        # We may see the failure before we've seen the succeed on the
        # same invoice (Stripe retries the same invoice id). Record
        # the failure ledger row so operators see it; a later
        # invoice.payment_succeeded for the same invoice will still
        # find *this* row via provider_invoice_id and short-circuit —
        # so recovery will fire via the plan.status transition rather
        # than a second PaymentTransaction row. Detection of "was
        # this invoice previously failed then recovered" is
        # available via txn.status transitions on this same row.
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.failed,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.pending,
            payer_user_id=plan.member_user_id,
            creator_user_id=plan.creator_user_id,
            space_id=plan.space_id,
            creator_plan_id=plan.creator_plan_id,
            currency=plan.currency,
            gross_amount_cents=plan.installment_amount_cents,
            platform_fee_basis_points=plan.platform_fee_basis_points,
            platform_fee_cents=0,
            net_creator_amount_cents=0,
            net_platform_amount_cents=0,
            provider_invoice_id=invoice_id,
            provider_subscription_id=plan.provider_subscription_id,
            payment_option_id=plan.payment_option_id,
            payment_option_schedule_id=plan.payment_option_schedule_id,
            purchase_plan_id=plan.id,
            # installment_number intentionally NULL — a failed row
            # does not consume an ordinal (Stripe will retry against
            # the same invoice or move to the next).
            installment_number=None,
            stripe_mode=plan.stripe_mode,
            payout_status=PayoutStatus.not_applicable,
            created_at=failed_at,
            updated_at=failed_at,
        )
        db.add(txn)
        db.flush()

    if plan.status == PurchasePlanStatus.pending_setup:
        # FIP4A — first-invoice failure semantics. A member who has
        # not yet earned access should NOT get the 7-day grace
        # window (that policy is for members with live access).
        # We use PROVIDER-FIRST termination: cancel the Stripe
        # SubscriptionSchedule BEFORE marking the plan ``failed``
        # so Rule D never unblocks while the abandoned Stripe
        # schedule could still bill autonomously. A transient
        # provider error propagates and lets Stripe redeliver
        # the invoice.payment_failed event.
        #
        # This is the exact same helper the setup-handler's
        # synchronous CardError path uses — one implementation,
        # both entry points.
        from app.webhooks.finite_plan_handlers import (
            _terminate_plan_on_first_payment_failure,
        )
        _terminate_plan_on_first_payment_failure(
            db, plan=plan,
            reason="first_payment_failed",
            note=f"invoice {invoice_id} failed while plan was pending_setup",
        )
        logger.warning(
            "FIP4A first-invoice fail (async): plan=%s → failed on invoice=%s; "
            "provider schedule cancelled, no access granted, Rule D unblocked",
            plan.id, invoice_id,
        )
        return FailureOutcome(
            plan_id=plan.id,
            invoice_id=invoice_id,
            transitioned_to=PurchasePlanStatus.failed.value,
            grace_expires_at=None,
            reason="first_payment_failed; no grace window applies",
        )

    if plan.status in (
        PurchasePlanStatus.completed,
        PurchasePlanStatus.cancelled,
        PurchasePlanStatus.failed,
    ):
        logger.warning(
            "FIP3 invoice_failed: plan %s in status=%s — recording ledger row only",
            plan.id, plan.status,
        )
        return FailureOutcome(
            plan_id=plan.id,
            invoice_id=invoice_id,
            transitioned_to=None,
            grace_expires_at=plan.grace_expires_at,
            reason=f"plan status={plan.status.value}; no transition",
        )

    if plan.status == PurchasePlanStatus.suspended:
        # Already suspended — grace expired earlier. Update the
        # last_failed_invoice_id pointer so a subsequent recovery
        # via this invoice correlates cleanly.
        plan.last_failed_invoice_id = invoice_id
        plan.updated_at = failed_at
        return FailureOutcome(
            plan_id=plan.id,
            invoice_id=invoice_id,
            transitioned_to=None,
            grace_expires_at=plan.grace_expires_at,
            reason="plan already suspended",
        )

    if plan.status == PurchasePlanStatus.payment_problem:
        # Replay OR follow-up failure on a different invoice inside
        # the same grace window. Never extend the deadline.
        if plan.last_failed_invoice_id != invoice_id:
            plan.last_failed_invoice_id = invoice_id
            plan.updated_at = failed_at
            logger.info(
                "FIP3 invoice_failed: plan %s already in payment_problem — "
                "updated last_failed_invoice_id to %s (grace deadline unchanged: %s)",
                plan.id, invoice_id, plan.grace_expires_at,
            )
        else:
            logger.info(
                "FIP3 invoice_failed: plan %s replay for same invoice %s — no-op",
                plan.id, invoice_id,
            )
        return FailureOutcome(
            plan_id=plan.id,
            invoice_id=invoice_id,
            transitioned_to=None,
            grace_expires_at=plan.grace_expires_at,
            reason="already in payment_problem",
        )

    # plan.status == active → open the grace window
    plan.status = PurchasePlanStatus.payment_problem
    plan.payment_problem_started_at = failed_at
    plan.grace_expires_at = failed_at + timedelta(days=GRACE_PERIOD_DAYS)
    plan.last_failed_invoice_id = invoice_id
    plan.updated_at = failed_at
    logger.info(
        "FIP3 invoice_failed: plan %s active → payment_problem, "
        "grace_expires_at=%s, invoice=%s",
        plan.id, plan.grace_expires_at, invoice_id,
    )
    return FailureOutcome(
        plan_id=plan.id,
        invoice_id=invoice_id,
        transitioned_to=PurchasePlanStatus.payment_problem.value,
        grace_expires_at=plan.grace_expires_at,
    )


# ---------------------------------------------------------------------------
# Grace expiry — reconciler
# ---------------------------------------------------------------------------


def sweep_expired_grace_plans(
    db: Session, *,
    now: datetime,
    max_plans: int = 200,
) -> list[SuspensionOutcome]:
    """Suspend every plan whose grace window has expired.

    Deterministic; safe to run on any cadence. Idempotent: only
    plans in ``payment_problem`` with
    ``grace_expires_at <= now`` are touched. Callers are the
    :mod:`app.services.finite_plan_reconciler` loop and the
    ``scripts/fip3_reconcile_grace.py`` operator script.
    """
    outcomes: list[SuspensionOutcome] = []

    due_plan_ids = [
        row.id for row in
        db.query(PurchasePlan.id)
        .filter(
            PurchasePlan.status == PurchasePlanStatus.payment_problem,
            PurchasePlan.grace_expires_at.is_not(None),
            PurchasePlan.grace_expires_at <= now,
        )
        .order_by(PurchasePlan.grace_expires_at)
        .limit(max_plans)
        .all()
    ]

    for plan_id in due_plan_ids:
        plan = (
            db.query(PurchasePlan)
            .filter(PurchasePlan.id == plan_id)
            .with_for_update()
            .one_or_none()
        )
        if plan is None:
            continue
        # Re-check under lock — someone may have recovered between
        # our scan and this lock.
        if plan.status != PurchasePlanStatus.payment_problem:
            continue
        if plan.grace_expires_at is None or plan.grace_expires_at > now:
            continue

        outcome = _suspend_plan_and_access(db, plan=plan, now=now)
        outcomes.append(outcome)
        db.commit()

    return outcomes


def suspend_plan_now(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
) -> SuspensionOutcome:
    """Test / operator helper — suspend a plan regardless of clock."""
    return _suspend_plan_and_access(db, plan=plan, now=now)


def _suspend_plan_and_access(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
) -> SuspensionOutcome:
    """Core transition: payment_problem → suspended with source-aware access effects."""
    prev = plan.status
    plan.status = PurchasePlanStatus.suspended
    plan.suspended_at = now
    plan.updated_at = now
    # Preserve grace_expires_at / last_failed_invoice_id for audit.

    # Step 1: mark plan-owned grant records as revoked with the
    # standard reason. This must run BEFORE the overlap query
    # below or overlap would still count these records.
    _agr.revoke_records_for_plan(
        db,
        purchase_plan_id=plan.id,
        reason="plan_suspended",
        now=now,
    )

    outcome = _apply_access_effects_for_plan_state(
        db, plan=plan,
        new_ap_status=AccessPassStatus.suspended,
        new_ent_status=EntitlementStatus.suspended,
        now=now,
    )
    logger.info(
        "FIP3 suspend: plan=%s (was %s) suspended_entitlements=%d preserved=%d "
        "suspended_passes=%d preserved=%d",
        plan.id, prev.value,
        len(outcome.suspended_entitlement_ids),
        len(outcome.preserved_entitlement_ids),
        len(outcome.suspended_access_pass_ids),
        len(outcome.preserved_access_pass_ids),
    )
    return outcome


def _reinstate_plan_access(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
) -> ReinstatementOutcome:
    """Reinstate this plan's suspended entitlements / passes on recovery.

    Called from :func:`record_later_successful_instalment` when the
    previous status was ``suspended``. Also usable directly by the
    operator/test path.
    """
    plan.reinstated_at = now
    plan.updated_at = now

    # Reinstate grant records first so overlap queries see them.
    _agr.reinstate_records_for_plan(db, purchase_plan_id=plan.id, now=now)

    ent_ids: list[str] = []
    for ent in (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.purchase_plan_id == plan.id,
            PathwayEntitlement.status == EntitlementStatus.suspended,
        )
        .all()
    ):
        ent.status = EntitlementStatus.active
        ent.updated_at = now
        ent_ids.append(ent.id)

    pass_ids: list[str] = []
    for ap in (
        db.query(AccessPass)
        .filter(
            AccessPass.purchase_plan_id == plan.id,
            AccessPass.status == AccessPassStatus.suspended,
        )
        .all()
    ):
        ap.status = AccessPassStatus.active
        ap.updated_at = now
        pass_ids.append(ap.id)

    logger.info(
        "FIP3 reinstate: plan=%s entitlements_restored=%d passes_restored=%d",
        plan.id, len(ent_ids), len(pass_ids),
    )
    return ReinstatementOutcome(
        plan_id=plan.id,
        reinstated_entitlement_ids=ent_ids,
        reinstated_access_pass_ids=pass_ids,
    )


# ---------------------------------------------------------------------------
# Source-aware access transitions — used by suspension
# ---------------------------------------------------------------------------


def _apply_access_effects_for_plan_state(
    db: Session, *,
    plan: PurchasePlan,
    new_ap_status: AccessPassStatus,
    new_ent_status: EntitlementStatus,
    now: datetime,
) -> SuspensionOutcome:
    """For every entitlement / pass linked to this plan, transition to
    the new status IF the user has no other active grant record for
    the same target.

    Preserves rows whose target has independent access via a
    different plan / manual grant / admin grant / pay-in-full.
    """
    suspended_entitlement_ids: list[str] = []
    preserved_entitlement_ids: list[str] = []
    suspended_pass_ids: list[str] = []
    preserved_pass_ids: list[str] = []

    entitlements = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.purchase_plan_id == plan.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .all()
    )
    for ent in entitlements:
        other_source = _agr.user_has_other_active_grant_for_pathway(
            db,
            user_id=ent.user_id,
            pathway_id=ent.pathway_id,
            excluding_purchase_plan_id=plan.id,
        )
        if other_source:
            preserved_entitlement_ids.append(ent.id)
            logger.info(
                "FIP3 access-effect: preserved entitlement %s user=%s pathway=%s "
                "— overlapping active grant record exists",
                ent.id, ent.user_id, ent.pathway_id,
            )
            continue
        ent.status = new_ent_status
        ent.updated_at = now
        suspended_entitlement_ids.append(ent.id)

    # AccessPass: each grant is its OWN row (no collapse). Every
    # AccessPass with ``purchase_plan_id == plan.id`` was minted
    # BY this plan and represents this plan's grant. Suspending it
    # does not strand the member — any unrelated overlapping
    # AccessPass (from a manual grant, a different plan, or a
    # pay-in-full purchase) is a separate row with a different
    # ``purchase_plan_id`` (or NULL) and stays active.
    #
    # We deliberately do NOT run the overlap check here — the
    # brief's rule is "suspend access attributable to this
    # PurchasePlan; preserve unrelated overlapping access". For
    # AccessPass the attribution is unambiguous per-row; the
    # overlap check would perversely preserve THIS plan's own pass
    # whenever another pass happens to cover the same target.
    access_passes = (
        db.query(AccessPass)
        .filter(
            AccessPass.purchase_plan_id == plan.id,
            AccessPass.status == AccessPassStatus.active,
        )
        .all()
    )
    for ap in access_passes:
        ap.status = new_ap_status
        ap.updated_at = now
        suspended_pass_ids.append(ap.id)

    # Flush so a caller that immediately queries / refreshes sees
    # the transitioned rows without waiting for an outer commit.
    db.flush()
    return SuspensionOutcome(
        plan_id=plan.id,
        suspended_entitlement_ids=suspended_entitlement_ids,
        suspended_access_pass_ids=suspended_pass_ids,
        preserved_entitlement_ids=preserved_entitlement_ids,
        preserved_access_pass_ids=preserved_pass_ids,
    )


def _clear_grace_fields(plan: PurchasePlan) -> None:
    """Recovery helper — clear the current grace/failure window fields."""
    plan.payment_problem_started_at = None
    plan.grace_expires_at = None
    plan.last_failed_invoice_id = None


# ---------------------------------------------------------------------------
# Subscription / schedule end reconciliation
# ---------------------------------------------------------------------------


def handle_subscription_deleted_for_plan(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
    invoice_fetcher=None,
) -> str | None:
    """Reconcile ``customer.subscription.deleted`` against our plan state.

    ORDER-INDEPENDENT: never decides "abnormal end" from the local
    counter alone. Delegates to
    :mod:`app.services.finite_plan_end_reconciliation`, which pulls
    the authoritative invoice inventory from Stripe, reconciles any
    paid invoices we haven't yet ledgered (may itself transition
    the plan to ``completed`` via the later-instalment path), and
    returns a deterministic decision (``completed`` / ``abnormal``
    / ``deferred``).

    * ``completed`` → confirm ``status=completed`` if not already,
      leave access active.
    * ``abnormal``  → transition to ``failed`` and suspend
      plan-owned access (source-aware).
    * ``deferred``  → log for later reconciliation, do NOT make
      any destructive terminal change. A later invoice.paid webhook
      or a subsequent reconcile call will resolve.

    ``invoice_fetcher`` is passed through to the reconciler for
    dependency injection in tests.

    Returns the terminal ``PurchasePlanStatus`` value the plan
    reached (or ``None`` if unchanged, incl. deferred).
    """
    prev = plan.status

    if plan.status in (PurchasePlanStatus.cancelled,
                       PurchasePlanStatus.completed,
                       PurchasePlanStatus.failed):
        # Already terminal. A subscription.deleted event on a
        # ``failed`` plan is EXPECTED (the FIP4A first-payment
        # failure path calls schedule.cancel, which cascades to a
        # subscription.deleted webhook). Suppress the reconciler
        # path so it can't accidentally re-run the abnormal-end
        # transition and revoke access — a first-payment failure
        # never had any access to revoke, but ``completed`` and
        # ``cancelled`` similarly must stay put.
        logger.info(
            "FIP3 subscription_deleted: plan=%s already terminal (%s); no-op",
            plan.id, plan.status.value,
        )
        return None

    if plan.status == PurchasePlanStatus.suspended:
        # Suspended + provider ended — reinstatement no longer
        # possible. Reconcile to catch a possibly-paid final
        # invoice we haven't seen; if it moved us to completed,
        # honour that (recovery via the reconciler applies).
        outcome = _reconcile_end(db, plan=plan, now=now, invoice_fetcher=invoice_fetcher)
        if outcome.decision == "completed":
            return PurchasePlanStatus.completed.value
        logger.info(
            "FIP3 subscription_deleted: plan=%s already suspended (%s); "
            "reconcile decision=%s note=%s",
            plan.id, prev.value, outcome.decision, outcome.note,
        )
        return None

    # active / payment_problem / failed / pending_setup — reconcile.
    outcome = _reconcile_end(db, plan=plan, now=now, invoice_fetcher=invoice_fetcher)

    if outcome.decision == "completed":
        # The reconciler's inner call to
        # ``record_later_successful_instalment`` transitions the
        # plan to ``completed`` itself when it applies the final
        # invoice. If it didn't (paid == expected already), confirm.
        if plan.status != PurchasePlanStatus.completed:
            plan.status = PurchasePlanStatus.completed
            plan.completed_at = plan.completed_at or now
            plan.updated_at = now
            _clear_grace_fields(plan)
        logger.info(
            "FIP3 subscription_deleted: plan=%s completed via reconcile "
            "(was %s, reconciled %d invoice(s))",
            plan.id, prev.value, len(outcome.reconciled_invoice_ids),
        )
        return PurchasePlanStatus.completed.value

    if outcome.decision == "deferred":
        logger.warning(
            "FIP3 subscription_deleted: plan=%s deferring terminal decision "
            "(was %s, %d/%d paid; ambiguous=%s note=%s)",
            plan.id, prev.value, outcome.installments_paid_after,
            outcome.installments_expected, outcome.ambiguous_invoice_ids,
            outcome.note,
        )
        return None

    # abnormal — plan.status is one of (active, payment_problem,
    # failed, pending_setup). If already ``failed``, we've been
    # here before; still ensure access is suspended source-aware.
    plan.status = PurchasePlanStatus.failed
    plan.cancelled_at = plan.cancelled_at or now
    plan.updated_at = now
    _agr.revoke_records_for_plan(
        db,
        purchase_plan_id=plan.id,
        reason="plan_failed",
        now=now,
    )
    _apply_access_effects_for_plan_state(
        db, plan=plan,
        new_ap_status=AccessPassStatus.suspended,
        new_ent_status=EntitlementStatus.suspended,
        now=now,
    )
    logger.warning(
        "FIP3 subscription_deleted: plan=%s abnormal end (was %s, %d/%d) → failed",
        plan.id, prev.value, plan.installments_paid, plan.installments_expected,
    )
    return PurchasePlanStatus.failed.value


def handle_schedule_completed_for_plan(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
    invoice_fetcher=None,
) -> str | None:
    """Handle ``subscription_schedule.completed``. ORDER-INDEPENDENT.

    ``subscription_schedule.completed`` fires when the schedule
    reaches its natural finite end. Same reconciliation as
    :func:`handle_subscription_deleted_for_plan` but with a
    softer "abnormal" branch — a schedule that Stripe considers
    complete but that we show under-paid, after reconciliation,
    is a real data-integrity warning; we still don't destroy
    access on the basis of one event.
    """
    prev = plan.status
    outcome = _reconcile_end(db, plan=plan, now=now, invoice_fetcher=invoice_fetcher)

    if outcome.decision == "completed":
        if plan.status != PurchasePlanStatus.completed:
            plan.status = PurchasePlanStatus.completed
            plan.completed_at = plan.completed_at or now
            plan.updated_at = now
            _clear_grace_fields(plan)
            logger.info(
                "FIP3 schedule_completed: plan=%s (was %s) → completed",
                plan.id, prev.value,
            )
        return PurchasePlanStatus.completed.value

    if outcome.decision == "deferred":
        logger.warning(
            "FIP3 schedule_completed: plan=%s deferring — %d/%d paid; note=%s",
            plan.id, outcome.installments_paid_after,
            outcome.installments_expected, outcome.note,
        )
        return None

    # abnormal — schedule complete but under-paid AND no ambiguity.
    # Do NOT suspend access here yet — a schedule.completed is
    # softer than subscription.deleted. Log for operator review;
    # the subscription.deleted for the same plan will apply the
    # access effect if it agrees.
    logger.warning(
        "FIP3 schedule_completed: plan=%s under-paid after reconcile "
        "(%d/%d) — flagging for operator review; leaving status=%s",
        plan.id, outcome.installments_paid_after,
        outcome.installments_expected, plan.status.value,
    )
    return None


def _reconcile_end(
    db: Session, *,
    plan: PurchasePlan,
    now: datetime,
    invoice_fetcher,
):
    """Local import to avoid circular dep with the reconciler
    (which itself calls back into :func:`record_later_successful_instalment`)."""
    from app.services.finite_plan_end_reconciliation import (
        reconcile_finite_plan_end,
    )
    return reconcile_finite_plan_end(
        db, plan=plan, now=now, invoice_fetcher=invoice_fetcher,
    )
