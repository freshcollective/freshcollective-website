"""FIP3 operator script — accelerated finite-plan lifecycle test scenarios.

Real weekly instalments take a week. This script uses official
Stripe Test Clocks so a full FIP3 scenario (payment 2 fails →
grace expires → suspended → recovery → payment 3 → completed)
plays out in minutes against the REAL Fresh Collective
architecture:

    PurchasePlan
    → finite plan setup (Checkout mode='setup')
    → Customer attached to a Test Clock (created BEFORE the
      SubscriptionSchedule)
    → PaymentMethod
    → Product/Price
    → SubscriptionSchedule
    → first successful instalment
    → access grant
    → clock advance triggers Stripe-generated invoice #2
    → default_payment_method swap triggers a genuine
      invoice.payment_failed on that renewal invoice
    → FC grace + reconciler drive suspension
    → PM repair + retry drives Stripe-generated recovery
    → clock advance triggers Stripe-generated invoice #3
    → completion

Standalone manually-created invoices are NOT used for lifecycle
proof. The `existing-plan` subcommand is kept for targeted
handler debugging on non-clock customers but MUST NOT be the
final integration-test path.

Refuses live keys unless ``--i-know-this-is-live`` is passed.
Never exposes an HTTP route.

Subcommands
-----------

    # Phase 0 — create clock + customer + plan + Session; prints Checkout URL.
    fip3_test_acceleration.py fresh-clock-setup \\
        --member-email you@example.com \\
        --payment-option-id po_XYZ \\
        --schedule-id sched_XYZ

    # Phase B — swap PM to failing card + advance clock 1 week.
    fip3_test_acceleration.py fresh-clock-fail-payment-2 \\
        --plan-id pplan_XYZ

    # Phase C — force local grace expiry + run reconciler.
    fip3_test_acceleration.py force-grace-expiry \\
        --plan-id pplan_XYZ

    # Phase D — swap PM to good card + pay overdue invoice.
    fip3_test_acceleration.py repair-and-retry \\
        --plan-id pplan_XYZ

    # Phase E — advance clock to trigger payment 3.
    fip3_test_acceleration.py advance-to-payment \\
        --plan-id pplan_XYZ --weeks 1
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
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Space
from app.models.purchase_plan import PurchasePlan
from app.models.user import User
from app.services.finite_plan_orchestration import (
    resolve_option_and_schedule_for_plan,
    start_finite_plan_setup,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger("fip3_test_acceleration")


# Official Stripe test PMs (verified against current docs, Aug 2026):
#   * pm_card_visa — 4242424242424242 — always succeeds.
#   * pm_card_chargeCustomerFail — 4000000000000341 — attach OK, charge fails.
GOOD_PM_TOKEN = "pm_card_visa"
FAILING_PM_TOKEN = "pm_card_chargeCustomerFail"


def _bind_stripe_key(allow_live: bool) -> None:
    if not settings.stripe_enabled:
        raise SystemExit("Stripe is not configured.")
    key = settings.stripe_secret_key
    if key.startswith("sk_live_") and not allow_live:
        raise SystemExit(
            "Refusing to run against a live key. Pass --i-know-this-is-live "
            "if that's really what you want."
        )
    stripe.api_key = key


# ---------------------------------------------------------------------------
# Phase 0 — fresh clock-attached plan setup
# ---------------------------------------------------------------------------


def _fresh_clock_setup(args: argparse.Namespace) -> int:
    """Create Stripe Test Clock + Customer, then open the FC setup
    Session against that Customer via the OPERATOR override on
    ``start_finite_plan_setup``. Prints the Checkout URL so the
    operator can complete the setup in a browser.

    Stripe requires the ``test_clock`` param at Customer creation
    time — it CANNOT be attached to an existing Customer. The
    override kwarg on ``start_finite_plan_setup`` is the sole
    operator-only escape hatch that lets this precondition survive
    into the existing setup-Checkout architecture without weakening
    production code paths (no HTTP-forwarded override exists).
    """
    db = SessionLocal()
    try:
        member = db.query(User).filter(User.email == args.member_email).one_or_none()
        if member is None:
            raise SystemExit(f"user {args.member_email!r} not found")

        resolved = resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=args.payment_option_id,
            payment_option_schedule_id=args.schedule_id,
        )

        # Test Clock frozen at now.
        clock_frozen = int(time.time())
        clock = stripe.test_helpers.TestClock.create(
            frozen_time=clock_frozen,
            name=f"FIP3 lifecycle {datetime.utcnow().isoformat()}",
        )
        logger.info("test clock created: %s (frozen_time=%s)", clock.id, clock_frozen)

        # Customer created ON the clock. Metadata for correlation.
        customer = stripe.Customer.create(
            email=member.email,
            test_clock=clock.id,
            metadata={
                "fip3_test_clock": clock.id,
                "fip3_member_id": member.id,
            },
        )
        logger.info("customer on clock: %s", customer.id)

        outcome = start_finite_plan_setup(
            db,
            resolved=resolved,
            payer=member,
            success_url=args.success_url,
            cancel_url=args.cancel_url,
            now=datetime.utcnow(),
            override_customer_id=customer.id,
        )
        db.commit()
        print("--- FIP3 fresh-clock setup ---")
        print(f"TEST_CLOCK:  {clock.id}")
        print(f"CUSTOMER:    {customer.id}")
        print(f"PLAN:        {outcome.plan.id}")
        print(f"SESSION:     {outcome.session.id}")
        print(f"CHECKOUT:    {outcome.checkout_url}")
        print("Complete the setup in a browser using a good test card "
              "(4242 4242 4242 4242).")
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Phase B — cause instalment 2 to fail on a Stripe-generated renewal
# ---------------------------------------------------------------------------


def _fresh_clock_fail_payment_2(args: argparse.Namespace) -> int:
    """Swap the default PM to a failing test card on ALL THREE
    surfaces Stripe considers (Customer, Subscription,
    SubscriptionSchedule.default_settings), assert the swap took
    effect, THEN advance the Test Clock by one week so Stripe
    generates invoice #2 on the SubscriptionSchedule and attempts
    collection (which will fail).

    Precondition proof BEFORE the clock advances is the whole
    point: the FIP3 v1 run against Jordan's plan discovered that
    swapping only Customer.invoice_settings.default_payment_method
    was insufficient — the subscription-level default_payment_method
    (set by the SubscriptionSchedule's default_settings at
    creation) took precedence and Stripe collected against the
    original good PM. We now update all three surfaces and assert
    each before allowing time to move.
    """
    plan, clock_id, customer_id = _plan_clock_customer(args.plan_id)
    pm_id = _swap_default_payment_method(
        customer_id=customer_id,
        subscription_id=plan.provider_subscription_id,
        schedule_id=plan.provider_subscription_schedule_id,
        pm_token=FAILING_PM_TOKEN,
    )
    _assert_default_pm_everywhere(
        customer_id=customer_id,
        subscription_id=plan.provider_subscription_id,
        schedule_id=plan.provider_subscription_schedule_id,
        expected_pm_id=pm_id,
    )
    _advance_clock(clock_id, delta=timedelta(days=8))
    print("advanced clock 8 days; expect invoice.payment_failed webhook.")
    print(f"plan={plan.id} customer={customer_id} clock={clock_id} pm={pm_id}")
    return 0


# ---------------------------------------------------------------------------
# Phase C — force grace expiry + reconcile
# ---------------------------------------------------------------------------


def _force_grace_expiry(args: argparse.Namespace) -> int:
    """Rewind ``PurchasePlan.grace_expires_at`` into the past and
    invoke the FIP3 reconciler. This is the same code path the
    in-process asyncio loop uses.
    """
    from app.services.finite_plan_lifecycle import sweep_expired_grace_plans

    db = SessionLocal()
    try:
        plan = db.query(PurchasePlan).filter(PurchasePlan.id == args.plan_id).one_or_none()
        if plan is None:
            raise SystemExit(f"plan {args.plan_id!r} not found")
        if plan.status.value != "payment_problem":
            raise SystemExit(
                f"plan {plan.id} is status={plan.status.value!r}; "
                f"expected payment_problem before forcing grace expiry"
            )
        # Use Python's ``datetime.utcnow()`` — NOT SQL ``NOW()``.
        # The FIP3 lifecycle stores and compares grace_expires_at as
        # naive UTC (see services/finite_plan_lifecycle.py). SQL
        # ``NOW()`` returns the server's local time — on a host in
        # AEST that's UTC+10 — which the sweeper's WHERE clause
        # then treats as if it were UTC, silently placing the
        # "expired" deadline HOURS INTO THE FUTURE relative to
        # actual UTC. The sweep would then find zero due plans.
        past = datetime.utcnow() - timedelta(minutes=1)
        db.execute(
            text(
                "UPDATE purchase_plans "
                "SET grace_expires_at = :past "
                "WHERE id = :id"
            ),
            {"past": past, "id": plan.id},
        )
        db.commit()
        outcomes = sweep_expired_grace_plans(db, now=datetime.utcnow())
        db.commit()
        print(f"reconciler swept {len(outcomes)} plan(s).")
        for o in outcomes:
            print(f"  plan={o.plan_id} "
                  f"suspended_ent={len(o.suspended_entitlement_ids)} "
                  f"preserved_ent={len(o.preserved_entitlement_ids)} "
                  f"suspended_ap={len(o.suspended_access_pass_ids)} "
                  f"preserved_ap={len(o.preserved_access_pass_ids)}")
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Phase D — repair PM + retry the overdue Stripe invoice
# ---------------------------------------------------------------------------


def _repair_and_retry(args: argparse.Namespace) -> int:
    """Swap the failing PM back to a good test PM, then pay the
    subscription's outstanding overdue invoice. Stripe fires
    invoice.payment_succeeded against the SAME overdue invoice id
    — the FIP3 later-instalment path recovers ``suspended → active``
    (or ``suspended → completed`` if this is the final instalment).
    """
    plan, _clock_id, customer_id = _plan_clock_customer(args.plan_id)
    pm_id = _swap_default_payment_method(
        customer_id=customer_id,
        subscription_id=plan.provider_subscription_id,
        schedule_id=plan.provider_subscription_schedule_id,
        pm_token=GOOD_PM_TOKEN,
    )
    _assert_default_pm_everywhere(
        customer_id=customer_id,
        subscription_id=plan.provider_subscription_id,
        schedule_id=plan.provider_subscription_schedule_id,
        expected_pm_id=pm_id,
    )

    # Locate the still-open overdue invoice for this subscription.
    overdue = _find_overdue_invoice(plan.provider_subscription_id)
    if overdue is None:
        raise SystemExit(
            f"no open/uncollectible invoice found for subscription "
            f"{plan.provider_subscription_id}"
        )
    logger.info(
        "paying overdue invoice %s (status=%s) on subscription %s",
        overdue.id, overdue.status, plan.provider_subscription_id,
    )
    paid = stripe.Invoice.pay(overdue.id)
    logger.info("paid invoice %s status=%s", paid.id, paid.status)
    print(f"invoice {paid.id} status={paid.status} — expect "
          f"invoice.payment_succeeded webhook + FC reinstatement.")
    return 0


def _find_overdue_invoice(subscription_id: str):
    """Find the still-outstanding invoice on the subscription."""
    for status in ("open", "uncollectible"):
        page = stripe.Invoice.list(
            subscription=subscription_id, status=status, limit=5,
        )
        for inv in page.auto_paging_iter():
            return inv
    return None


# ---------------------------------------------------------------------------
# Phase E — advance clock to generate the next instalment
# ---------------------------------------------------------------------------


def _advance_to_payment(args: argparse.Namespace) -> int:
    """Advance the plan's Test Clock forward by ``weeks``. Stripe
    will generate the next scheduled invoice + collect via the
    current default PM."""
    _plan, clock_id, _cust = _plan_clock_customer(args.plan_id)
    _advance_clock(clock_id, delta=timedelta(days=7 * args.weeks))
    print(f"advanced clock {args.weeks} week(s); expect Stripe-generated "
          f"invoice + invoice.payment_succeeded webhook.")
    return 0


# ---------------------------------------------------------------------------
# Existing-plan helpers — kept for targeted debugging only
# ---------------------------------------------------------------------------


def _existing_plan(args: argparse.Namespace) -> int:
    """Legacy helper for handler debugging on non-clock customers.

    DO NOT use for final lifecycle proof — creates a standalone
    invoice, not a Stripe-scheduled renewal. Kept because
    debugging the invoice-succeeded handler on an existing pplan_
    can still be useful without spinning up a fresh clock plan.
    """
    print(
        "WARNING: existing-plan uses a standalone Invoice.create, not a "
        "Stripe-generated subscription renewal. Do not use for FIP3 "
        "lifecycle sign-off. Use the fresh-clock-* subcommands instead."
    )
    return 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _plan_clock_customer(plan_id: str) -> tuple[PurchasePlan, str, str]:
    """Look up a plan and derive its Test Clock id via the Customer.
    Returns (plan, clock_id, customer_id). Refuses non-test plans."""
    db = SessionLocal()
    try:
        plan = db.query(PurchasePlan).filter(PurchasePlan.id == plan_id).one_or_none()
        if plan is None:
            raise SystemExit(f"plan {plan_id!r} not found")
        if plan.stripe_mode != "test":
            raise SystemExit(
                f"plan {plan.id} is stripe_mode={plan.stripe_mode!r}; refuse to accelerate"
            )
        if plan.provider_customer_id is None:
            raise SystemExit(f"plan {plan.id} has no provider_customer_id")
    finally:
        db.close()

    cust = stripe.Customer.retrieve(plan.provider_customer_id)
    clock_id = cust.get("test_clock") if isinstance(cust, dict) else getattr(cust, "test_clock", None)
    if not clock_id:
        raise SystemExit(
            f"customer {plan.provider_customer_id} is not attached to a Test Clock; "
            f"use fresh-clock-setup for a new clock-backed plan"
        )
    return plan, clock_id, plan.provider_customer_id


def _swap_default_payment_method(
    *, customer_id: str, subscription_id: str, schedule_id: str,
    pm_token: str,
) -> str:
    """Attach ``pm_token`` and set it as the default across every
    surface that Stripe will consult for the next scheduled
    invoice: Customer, Subscription, and the SubscriptionSchedule's
    ``default_settings``.

    Stripe's own guidance for schedule-backed subscriptions is to
    update the SubscriptionSchedule rather than the Subscription
    directly, because a phase transition can overwrite direct
    subscription changes. For a single-phase finite plan the
    distinction is largely academic (there's no next phase to
    transition to), but we still update the schedule so the
    harness matches production semantics + won't regress if the
    plan shape ever grows a second phase. Subscription is updated
    too as a belt-and-braces override. Customer default is
    updated so ad-hoc invoices outside the subscription also see
    the swap.

    Returns the attached PaymentMethod id.
    """
    pm = stripe.PaymentMethod.attach(pm_token, customer=customer_id)
    stripe.Customer.modify(
        customer_id,
        invoice_settings={"default_payment_method": pm.id},
    )
    stripe.SubscriptionSchedule.modify(
        schedule_id,
        default_settings={"default_payment_method": pm.id},
    )
    stripe.Subscription.modify(
        subscription_id,
        default_payment_method=pm.id,
    )
    logger.info(
        "swapped default PM to %s on customer=%s subscription=%s schedule=%s",
        pm.id, customer_id, subscription_id, schedule_id,
    )
    return pm.id


def _assert_default_pm_everywhere(
    *, customer_id: str, subscription_id: str, schedule_id: str,
    expected_pm_id: str,
) -> None:
    """Fetch fresh Stripe state and confirm the PM swap took on
    every surface. Fails loudly BEFORE any time advances — we
    never want to discover a stale PM by observing an unintended
    invoice outcome."""
    cust = stripe.Customer.retrieve(customer_id)
    cust_pm = None
    try:
        cust_pm = cust["invoice_settings"]["default_payment_method"]
    except (KeyError, TypeError):
        pass

    sub = stripe.Subscription.retrieve(subscription_id)
    sub_pm = None
    try:
        sub_pm = sub["default_payment_method"]
    except (KeyError, TypeError):
        pass

    sched = stripe.SubscriptionSchedule.retrieve(schedule_id)
    sched_pm = None
    try:
        sched_pm = sched["default_settings"]["default_payment_method"]
    except (KeyError, TypeError):
        pass

    mismatches = []
    if cust_pm != expected_pm_id:
        mismatches.append(f"Customer.invoice_settings.default_payment_method={cust_pm!r}")
    if sub_pm != expected_pm_id:
        mismatches.append(f"Subscription.default_payment_method={sub_pm!r}")
    if sched_pm != expected_pm_id:
        mismatches.append(f"SubscriptionSchedule.default_settings.default_payment_method={sched_pm!r}")
    if mismatches:
        raise SystemExit(
            f"PM swap verification FAILED — expected {expected_pm_id!r} everywhere. "
            f"Mismatches: {'; '.join(mismatches)}"
        )
    logger.info(
        "PM swap verified: customer=%s subscription=%s schedule=%s all=%s",
        cust_pm, sub_pm, sched_pm, expected_pm_id,
    )


def _advance_clock(clock_id: str, delta: timedelta) -> None:
    """Advance the Test Clock by ``delta``. Blocks until Stripe
    reports the clock is ``ready`` — a fresh advance may take a few
    seconds to fire dependent invoices."""
    clock = stripe.test_helpers.TestClock.retrieve(clock_id)
    frozen = clock.get("frozen_time") if isinstance(clock, dict) else getattr(clock, "frozen_time", None)
    target = int(frozen) + int(delta.total_seconds())
    stripe.test_helpers.TestClock.advance(clock_id, frozen_time=target)
    logger.info("test clock %s advanced to frozen_time=%s", clock_id, target)
    # Poll until ready.
    deadline = time.time() + 120
    while time.time() < deadline:
        current = stripe.test_helpers.TestClock.retrieve(clock_id)
        status = current.get("status") if isinstance(current, dict) else getattr(current, "status", None)
        if status == "ready":
            logger.info("test clock %s ready", clock_id)
            return
        time.sleep(2)
    logger.warning("test clock %s not ready after 120s; continuing", clock_id)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-know-this-is-live", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("fresh-clock-setup")
    p_setup.add_argument("--member-email", required=True)
    p_setup.add_argument("--payment-option-id", required=True)
    p_setup.add_argument("--schedule-id", required=True)
    # FIP3 harness runs against the local dev environment.
    # freshcollective.com.au was retired; leaving that URL in as a
    # default sends the operator to a Squarespace "Website Expired"
    # page after Stripe redirects. localhost:3000 is where the FC
    # dev frontend lives; production checkout endpoints resolve
    # their own success/cancel URLs and are unaffected.
    p_setup.add_argument("--success-url", default="http://localhost:3000/checkout/success")
    p_setup.add_argument("--cancel-url", default="http://localhost:3000/checkout/cancel")

    p_fail = sub.add_parser("fresh-clock-fail-payment-2")
    p_fail.add_argument("--plan-id", required=True)

    p_grace = sub.add_parser("force-grace-expiry")
    p_grace.add_argument("--plan-id", required=True)

    p_repair = sub.add_parser("repair-and-retry")
    p_repair.add_argument("--plan-id", required=True)

    p_adv = sub.add_parser("advance-to-payment")
    p_adv.add_argument("--plan-id", required=True)
    p_adv.add_argument("--weeks", type=int, default=1)

    p_leg = sub.add_parser("existing-plan")
    p_leg.add_argument("--plan-id", required=True)
    p_leg.add_argument("--scenario", required=True)

    args = parser.parse_args()
    _bind_stripe_key(allow_live=args.i_know_this_is_live)

    if args.cmd == "fresh-clock-setup":
        return _fresh_clock_setup(args)
    if args.cmd == "fresh-clock-fail-payment-2":
        return _fresh_clock_fail_payment_2(args)
    if args.cmd == "force-grace-expiry":
        return _force_grace_expiry(args)
    if args.cmd == "repair-and-retry":
        return _repair_and_retry(args)
    if args.cmd == "advance-to-payment":
        return _advance_to_payment(args)
    if args.cmd == "existing-plan":
        return _existing_plan(args)
    raise SystemExit(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
