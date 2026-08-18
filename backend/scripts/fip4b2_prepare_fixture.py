"""FIP4B2 operator script — prepare a browser-testable repair fixture.

Bootstraps a real Stripe Test Mode payment plan whose most recent
instalment has failed, so a browser tester can click the FIP4B1
banner CTA and drive the real FIP4B2 repair flow end-to-end
against Stripe (Update payment details → save good card → overdue
invoice retried by webhook → plan returns active / access
reinstated).

Two output modes:

    --state grace       plan.status = payment_problem, access active
    --state suspended   plan.status = suspended,       access suspended

Both share the same shape: 3-instalment weekly plan, first
instalment paid (real Stripe invoice), second instalment failed
(real Stripe invoice), a persistent PurchasePlan + entitlement +
access pass + grant record in the FC DB with real provider ids.

Design shortcuts (operator only — production code uses none of
these):
  * Attach PaymentMethod directly via stripe.PaymentMethod.attach
    rather than a browser Checkout Session (setup is not what
    FIP4B2 tests — repair is).
  * Force ``plan.status = suspended`` + revoke access-grant records
    for the --state suspended fixture, mirroring what the grace
    reconciler would do.

The tester follows the normal member journey from the banner:

  1. Log in as the fixture user.
  2. Visit the granted Pathway (or Series) About page.
  3. Confirm the recovery banner shows (payment_problem or
     suspended state).
  4. Click ``Update payment details``.
  5. Complete Stripe Checkout with a good test card
     (4242 4242 4242 4242).
  6. Wait for redirect to /checkout/repair-return, then wait a
     second or two for the webhook chain to complete.
  7. Refresh the Pathway About page: banner should be gone,
     plan should be active, access restored (for the suspended
     fixture).

USAGE

    .venv/bin/python scripts/fip4b2_prepare_fixture.py \\
        --member-email fip4b2-grace@test.com \\
        --payment-option-id po_XXX \\
        --schedule-id sched_XXX \\
        --state grace

Payment Option must be recurring_installments × 3, weekly, and
must grant a Pathway (so the banner surfaces on that Pathway).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
import stripe

# Force full model registry load so SQLAlchemy can resolve all FK
# strings (e.g. 'creator_plans.id' referenced from purchase_plans).
import app.main  # noqa: F401
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    EntitlementSource, EntitlementStatus,
    Pathway, PathwayEntitlement, SpaceMembership,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services import access_grant_records as agr


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger("fip4b2_prepare_fixture")


GOOD_PM_TOKEN = "pm_card_visa"
FAILING_PM_TOKEN = "pm_card_chargeCustomerFail"


def _bind_stripe_key(allow_live: bool) -> None:
    if not settings.stripe_secret_key:
        raise SystemExit("STRIPE_SECRET_KEY is not configured; refuse to run.")
    if settings.stripe_secret_key.startswith("sk_live_") and not allow_live:
        raise SystemExit(
            "Refusing to run against a LIVE Stripe key. "
            "Pass --i-know-this-is-live to override."
        )
    stripe.api_key = settings.stripe_secret_key


def _prepare_fixture(args: argparse.Namespace) -> int:
    """Create the full Stripe + FC state for a browser-testable FIP4B2 fixture."""
    db = SessionLocal()
    try:
        member = db.query(User).filter(User.email == args.member_email).one_or_none()
        if member is None:
            raise SystemExit(f"user {args.member_email!r} not found")

        option = (
            db.query(PaymentOption)
            .filter(PaymentOption.id == args.payment_option_id)
            .one_or_none()
        )
        if option is None:
            raise SystemExit(f"payment option {args.payment_option_id!r} not found")
        schedule = (
            db.query(PaymentOptionSchedule)
            .filter(PaymentOptionSchedule.id == args.schedule_id)
            .one_or_none()
        )
        if schedule is None:
            raise SystemExit(f"schedule {args.schedule_id!r} not found")
        if schedule.installment_count != 3:
            raise SystemExit(
                f"schedule.installment_count={schedule.installment_count} "
                f"— FIP4B2 fixture expects 3 instalments"
            )

        # Refuse if the member already has an active plan on this option.
        existing = (
            db.query(PurchasePlan)
            .filter(
                PurchasePlan.member_user_id == member.id,
                PurchasePlan.payment_option_id == option.id,
                PurchasePlan.status.in_((
                    PurchasePlanStatus.pending_setup,
                    PurchasePlanStatus.active,
                    PurchasePlanStatus.payment_problem,
                    PurchasePlanStatus.suspended,
                )),
            )
            .first()
        )
        if existing is not None:
            raise SystemExit(
                f"member {member.email} already has a live plan "
                f"({existing.id}, status={existing.status.value}) for this option. "
                f"Cancel it first or use a fresh test user."
            )

        # Locate the pathway the option grants (so we can seed an
        # entitlement + access pass matching what a real purchase would).
        pathway_id = option.grants_pathway_id
        if not pathway_id:
            # Modern grant rows.
            from app.models.payment_option_grant import GRANT_KIND_PATHWAY
            g = [g for g in (option.grants or []) if g.grant_kind == GRANT_KIND_PATHWAY]
            if not g:
                raise SystemExit(
                    f"payment option {option.id} does not grant a Pathway — "
                    f"the FIP4B1 banner surfaces via Pathway/Series grants only"
                )
            pathway_id = g[0].pathway_id
        pathway = db.query(Pathway).filter(Pathway.id == pathway_id).one_or_none()
        if pathway is None:
            raise SystemExit(f"pathway {pathway_id} not found")

        # 1. Test Clock + Customer (Customer must be created ON the clock).
        clock_frozen = int(time.time())
        clock = stripe.test_helpers.TestClock.create(
            frozen_time=clock_frozen,
            name=f"FIP4B2 fixture ({args.state}) {datetime.utcnow().isoformat()}",
        )
        logger.info("test clock: %s", clock.id)
        customer = stripe.Customer.create(
            email=member.email,
            test_clock=clock.id,
            metadata={
                "fip4b2_fixture": args.state,
                "fip4b2_member_id": member.id,
            },
        )
        logger.info("customer: %s", customer.id)

        # 2. Attach a GOOD PM + set as default on the Customer.
        good_pm = stripe.PaymentMethod.attach(GOOD_PM_TOKEN, customer=customer.id)
        stripe.Customer.modify(
            customer.id,
            invoice_settings={"default_payment_method": good_pm.id},
        )
        logger.info("good pm attached: %s", good_pm.id)

        # 3. Product + Price + SubscriptionSchedule.
        product = stripe.Product.create(
            name=f"[FIP4B2 fixture] {option.name}",
            metadata={"fip4b2_fixture": args.state, "member_id": member.id},
        )
        price = stripe.Price.create(
            product=product.id,
            currency=schedule.currency.lower(),
            unit_amount=schedule.installment_amount_cents,
            recurring={
                "interval": schedule.stripe_interval,
                "interval_count": schedule.stripe_interval_count,
            },
        )
        sched = stripe.SubscriptionSchedule.create(
            customer=customer.id,
            start_date="now",
            end_behavior="cancel",
            default_settings={"default_payment_method": good_pm.id},
            phases=[{
                "items": [{"price": price.id, "quantity": 1}],
                "duration": {
                    "interval": schedule.stripe_interval,
                    "interval_count": schedule.stripe_interval_count * 3,
                },
                "metadata": {"fip4b2_fixture": args.state},
            }],
        )
        subscription_id = sched.subscription
        logger.info("schedule: %s subscription: %s", sched.id, subscription_id)

        # 4. Finalize + pay invoice #1 (the subscription-create invoice).
        sub = stripe.Subscription.retrieve(subscription_id)
        first_invoice_id = sub.latest_invoice
        stripe.Invoice.finalize_invoice(first_invoice_id, auto_advance=False)
        paid = stripe.Invoice.pay(first_invoice_id)
        assert paid.status == "paid", f"invoice #1 status={paid.status}"
        logger.info("invoice #1 paid: %s", first_invoice_id)

        # 5. Create the PurchasePlan row in FC DB with real provider ids.
        #    installments_paid=1 (invoice #1 already paid on Stripe).
        now = datetime.utcnow()
        plan = PurchasePlan(
            id=f"pplan_fip4b2_{args.state}_{uuid.uuid4().hex[:8]}",
            member_user_id=member.id,
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            space_id=option.space_id,
            creator_user_id=None,
            status=PurchasePlanStatus.active,
            currency=schedule.currency,
            installment_amount_cents=schedule.installment_amount_cents,
            installments_expected=3, installments_paid=1,
            total_expected_cents=schedule.installment_amount_cents * 3,
            stripe_interval=schedule.stripe_interval,
            stripe_interval_count=schedule.stripe_interval_count,
            platform_fee_basis_points=0,
            provider_customer_id=customer.id,
            provider_payment_method_id=good_pm.id,
            provider_subscription_id=subscription_id,
            provider_subscription_schedule_id=sched.id,
            stripe_product_id=product.id,
            stripe_price_id=price.id,
            stripe_mode="test",
            activated_at=now,
            created_at=now, updated_at=now,
        )
        db.add(plan); db.flush()

        # Ledger row for invoice #1.
        txn1 = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            payer_user_id=member.id,
            space_id=option.space_id,
            currency=schedule.currency,
            gross_amount_cents=schedule.installment_amount_cents,
            platform_fee_basis_points=0,
            platform_fee_cents=0, net_creator_amount_cents=0,
            net_platform_amount_cents=0,
            provider_invoice_id=first_invoice_id,
            provider_subscription_id=subscription_id,
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            purchase_plan_id=plan.id, installment_number=1,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(txn1)

        # Entitlement + access pass — mirror what the FIP2 first-invoice
        # webhook would apply from the snapshot grants bundle.
        ent = PathwayEntitlement(
            id=f"pe_{uuid.uuid4().hex[:12]}",
            user_id=member.id, space_id=option.space_id,
            pathway_id=pathway.id,
            source=EntitlementSource.one_time_purchase,
            status=EntitlementStatus.active, starts_at=now,
            purchase_plan_id=plan.id,
            created_at=now, updated_at=now,
        )
        ap = AccessPass(
            id=f"ap_{uuid.uuid4().hex[:12]}",
            user_id=member.id, space_id=option.space_id,
            payment_option_id=option.id,
            payment_option_schedule_id=schedule.id,
            purchase_plan_id=plan.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active, valid_from=now,
            grants_pathway_id=pathway.id,
            source=AccessPassSource.one_time_purchase,
            created_at=now, updated_at=now,
        )
        db.add_all([ent, ap]); db.flush()

        # Learner SpaceMembership — mirrors what
        # ``services.purchase_fulfilment._auto_join_membership`` would
        # have added during the real first-invoice fulfilment. Neither
        # the FIP3 suspension path nor _apply_access_effects_for_plan_state
        # touches membership, so the row stays ``active`` regardless of
        # payment_problem / suspended state. Without this row the
        # member is bounced to the "join the Collective" gate before
        # ever seeing the recovery banner.
        existing_mem = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == option.space_id,
                SpaceMembership.user_id == member.id,
            )
            .first()
        )
        if existing_mem is None:
            db.add(SpaceMembership(
                id=str(uuid.uuid4()),
                space_id=option.space_id,
                user_id=member.id,
                role="learner",
                status="active",
                source="purchase",
                joined_at=now,
            ))

        agr.record_pathway_grant(
            db, user_id=member.id, pathway_id=pathway.id,
            source_type=agr.SOURCE_PLAN_PAYMENT,
            source_purchase_plan_id=plan.id,
            source_payment_transaction_id=txn1.id,
            granted_at=now,
        )
        db.commit()

        # 6. Swap default PM to FAILING on all 3 surfaces (Customer,
        #    Subscription, SubscriptionSchedule.default_settings).
        failing_pm = stripe.PaymentMethod.attach(FAILING_PM_TOKEN, customer=customer.id)
        stripe.Customer.modify(
            customer.id,
            invoice_settings={"default_payment_method": failing_pm.id},
        )
        stripe.SubscriptionSchedule.modify(
            sched.id,
            default_settings={"default_payment_method": failing_pm.id},
        )
        stripe.Subscription.modify(
            subscription_id, default_payment_method=failing_pm.id,
        )
        logger.info("failing pm attached: %s (all 3 surfaces)", failing_pm.id)

        # 7. Advance the clock one week → Stripe generates invoice #2
        #    (as a draft, on Test Clock plans) and would attempt
        #    collection.
        new_frozen = clock_frozen + (7 * 24 * 60 * 60)
        stripe.test_helpers.TestClock.advance(clock.id, frozen_time=new_frozen)
        logger.info("clock advanced 1 week — Stripe will draft invoice #2")

        # Poll for the clock to settle.
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(3)
            fresh_clock = stripe.test_helpers.TestClock.retrieve(clock.id)
            if fresh_clock.status == "ready":
                break
        logger.info("clock ready (status=%s)", fresh_clock.status)

        # Locate invoice #2 (subscription_cycle billing_reason).
        # Poll — Stripe may take a moment after the clock settles.
        deadline = time.time() + 30
        second_invoice_id = None
        while time.time() < deadline:
            invoices = stripe.Invoice.list(subscription=subscription_id, limit=10).data
            for inv in invoices:
                inv_id = inv.id
                if inv_id == first_invoice_id:
                    continue
                second_invoice_id = inv_id
                break
            if second_invoice_id:
                break
            time.sleep(2)
        if second_invoice_id is None:
            raise SystemExit(
                f"invoice #2 was never created on subscription {subscription_id} "
                f"after clock advance. Cannot proceed."
            )
        logger.info("invoice #2 found: %s", second_invoice_id)

        # Force the failure now: finalize (if draft), then pay against
        # the failing PM. Stripe declines → invoice goes to 'open'.
        second_invoice = stripe.Invoice.retrieve(second_invoice_id)
        if second_invoice.status == "draft":
            stripe.Invoice.finalize_invoice(second_invoice_id, auto_advance=False)
            second_invoice = stripe.Invoice.retrieve(second_invoice_id)
            logger.info("invoice #2 finalized (status=%s)", second_invoice.status)
        if second_invoice.status == "open":
            try:
                stripe.Invoice.pay(second_invoice_id)
            except stripe.CardError as exc:
                logger.info(
                    "invoice #2 pay attempt correctly declined: %s", exc.user_message,
                )
        # Re-read status; should now be 'open' (Stripe leaves it open
        # after a decline and schedules Smart Retries).
        second_invoice = stripe.Invoice.retrieve(second_invoice_id)
        logger.info("invoice #2 post-fail status: %s", second_invoice.status)

        # In dev, the invoice.payment_failed webhook may not reach the
        # backend. Drive the FIP3 lifecycle handler synthetically —
        # exactly what the webhook would do — so the plan enters
        # payment_problem locally. Idempotent w.r.t. real webhook
        # delivery: if the webhook does arrive later, its natural-key
        # guard on provider_invoice_id detects the existing failed
        # ledger row and short-circuits.
        db.refresh(plan)
        if plan.status != PurchasePlanStatus.payment_problem:
            from app.services import finite_plan_lifecycle as fpl
            fpl.handle_invoice_failed_for_plan(
                db, plan=plan, invoice_id=second_invoice_id,
                failed_at=datetime.utcnow(),
            )
            db.commit()
            db.refresh(plan)
            assert plan.status == PurchasePlanStatus.payment_problem, (
                f"plan did not reach payment_problem after synthetic drive; "
                f"status={plan.status.value}"
            )
            logger.info(
                "plan %s now in payment_problem (invoice=%s)",
                plan.id, second_invoice_id,
            )

        # 8. For --state suspended: force grace expiry to move to suspended.
        if args.state == "suspended" and plan.status == PurchasePlanStatus.payment_problem:
            from app.services import finite_plan_lifecycle as fpl
            fpl.suspend_plan_now(db, plan=plan, now=datetime.utcnow())
            db.commit()
            db.refresh(plan)
            logger.info("plan forced to suspended: %s", plan.status.value)

        # Locate the space slug + pathway slug for the URL.
        from app.models.platform import Space
        space = db.query(Space).filter(Space.id == option.space_id).one()

        print("=" * 72)
        print(f"FIP4B2 fixture ready — state: {args.state}")
        print(f"  member email:   {member.email}")
        print(f"  plan id:        {plan.id}")
        print(f"  plan status:    {plan.status.value}")
        print(f"  provider ids:")
        print(f"    customer:     {plan.provider_customer_id}")
        print(f"    subscription: {plan.provider_subscription_id}")
        print(f"    schedule:     {plan.provider_subscription_schedule_id}")
        print(f"    failed inv:   {plan.last_failed_invoice_id}")
        print(f"  test clock:     {clock.id}")
        print()
        print(f"Browser URL (Pathway About with banner):")
        print(f"  http://localhost:3000/spaces/{space.slug}/pathways/{pathway.slug}/about")
        print("=" * 72)
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member-email", required=True)
    parser.add_argument("--payment-option-id", required=True)
    parser.add_argument("--schedule-id", required=True)
    parser.add_argument(
        "--state", required=True, choices=("grace", "suspended"),
        help="Terminal state for the fixture plan.",
    )
    parser.add_argument("--i-know-this-is-live", action="store_true")
    args = parser.parse_args()
    _bind_stripe_key(allow_live=args.i_know_this_is_live)
    return _prepare_fixture(args)


if __name__ == "__main__":
    raise SystemExit(main())
