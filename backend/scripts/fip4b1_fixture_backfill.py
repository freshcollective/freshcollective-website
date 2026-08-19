"""FIP4B1 browser-fixture ledger backfill (idempotent).

Purpose
-------
The two FIP4B1 recovery-banner fixtures — ``fip4b1-grace@test.com``
and ``fip4b1-suspended@test.com`` — were created ad-hoc during
FIP4B1 (banner-only review) by directly setting
``PurchasePlan.installments_paid = 1`` without inserting the
matching succeeded ``PaymentTransaction`` row that real FIP2
first-invoice fulfilment would have produced. That inconsistency
was invisible for FIP4B1/FIP4B2 (they only rendered the banner +
member-side recovery), but FIP4C's Payment Plans view surfaces
``paid_amount_cents`` (SUM of succeeded ledger rows) alongside
``installments_paid`` (plan counter), so the mismatch became
visible to the creator as "1 of 3 paid · $0.00 paid to date".

Invariant this script enforces
------------------------------
For any FIP fixture with ``installments_paid > 0`` there MUST be
a corresponding chain of succeeded ``PaymentTransaction`` rows
(one per instalment ordinal, gross_amount_cents matching the
plan's per-instalment amount). Real fulfilment guarantees this
via :func:`app.webhooks.finite_plan_handlers._do_invoice_succeeded`
(first invoice) and
:func:`app.services.finite_plan_lifecycle.record_later_successful_instalment`
(later instalments); synthetic fixtures MUST mirror the same
shape or downstream accounting surfaces will misreport.

The FIP4B2 fixture script (``fip4b2_prepare_fixture.py``) already
observes this invariant because it drives the real FIP2 pipeline
end-to-end via Stripe Test Clocks. This script is the equivalent
guardrail for the older FIP4B1 fixtures.

Behaviour
---------
Idempotent. For each targeted plan, if a succeeded
``PaymentTransaction`` for instalment 1 already exists, skip.
Otherwise insert one matching what
``_do_invoice_succeeded`` would have written for the plan's
first invoice.

Does NOT touch Stripe. Does NOT modify plan state fields (the
current ``payment_problem`` / ``suspended`` status + grace
timestamps + provider id snapshots are preserved as-is).

USAGE

    cd backend
    .venv/bin/python scripts/fip4b1_fixture_backfill.py
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
import app.main  # noqa: F401 — force full model registry load
from app.core.database import SessionLocal
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.purchase_plan import PurchasePlan


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger("fip4b1_fixture_backfill")


# The two FIP4B1 fixture plan ids (created ad-hoc last session).
_FIXTURE_PLAN_IDS = (
    "pplan_fip4b1_grace_1",
    "pplan_fip4b1_susp_1",
)


def _backfill_plan(db, plan: PurchasePlan) -> str:
    """Insert instalment 1's succeeded PaymentTransaction if missing.

    Returns a short status string for logging: 'skipped' if the row
    already exists, 'created' if this run inserted it.
    """
    existing = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.purchase_plan_id == plan.id,
            PaymentTransaction.installment_number == 1,
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
        )
        .first()
    )
    if existing is not None:
        return "skipped"

    # Fee snapshot — mirror the plan's own fee bps, same as
    # real fulfilment does in record_later_successful_instalment.
    gross = plan.installment_amount_cents
    platform_fee = round(gross * plan.platform_fee_basis_points / 10000)
    net_creator = gross - platform_fee

    now = datetime.utcnow()
    # Synthetic invoice id — the FIP4B1 fixtures never touched Stripe
    # so there's no real invoice to reference. Namespaced so it's
    # unmistakably fixture-only.
    synthetic_invoice_id = f"in_fip4b1_synthetic_inst1_{plan.id}"

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
        provider_invoice_id=synthetic_invoice_id,
        provider_subscription_id=plan.provider_subscription_id,
        payment_option_id=plan.payment_option_id,
        payment_option_schedule_id=plan.payment_option_schedule_id,
        purchase_plan_id=plan.id,
        installment_number=1,
        stripe_mode=plan.stripe_mode,
        payout_status=PayoutStatus.pending,
        notes="FIP4B1 synthetic fixture — backfilled by fip4b1_fixture_backfill.py",
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    return "created"


def main() -> int:
    db = SessionLocal()
    try:
        for plan_id in _FIXTURE_PLAN_IDS:
            plan = (
                db.query(PurchasePlan)
                .filter(PurchasePlan.id == plan_id)
                .one_or_none()
            )
            if plan is None:
                logger.warning("plan %s not found — skipping", plan_id)
                continue

            # Sanity — only backfill if the plan legitimately claims
            # an instalment was paid but the ledger is missing it.
            # This is the exact inconsistency the script exists to
            # resolve; treat any other shape as caller error and skip.
            if plan.installments_paid < 1:
                logger.warning(
                    "plan %s has installments_paid=%d — nothing to backfill",
                    plan_id, plan.installments_paid,
                )
                continue

            outcome = _backfill_plan(db, plan)
            logger.info(
                "plan=%s status=%s installments_paid=%d/%d → %s",
                plan.id, plan.status.value,
                plan.installments_paid, plan.installments_expected,
                outcome,
            )
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
