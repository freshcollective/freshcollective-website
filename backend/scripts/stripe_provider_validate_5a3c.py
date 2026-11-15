"""Stage 5A.3c provider validation — real Stripe, test mode only.

Deliberately a script rather than a test: it creates objects in the
Stripe test account and advances a test clock, which is not something
an ordinary suite run should ever do. The automated tests mock Stripe;
this verifies the provider behaviour those mocks stand in for.

Run with::

    cd backend
    FC_STRIPE_PROVIDER_TESTS=1 .venv/bin/python \\
        scripts/stripe_provider_validate_5a3c.py

Refuses to start without the opt-in and without an ``sk_test`` key —
the same two gates the pytest marker uses, through the same helper, so
there is one definition of "allowed to talk to Stripe".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import stripe_guard  # noqa: E402

if not stripe_guard.opted_in():
    sys.exit(
        f"refusing to run: set {stripe_guard.OPT_IN_ENV}=1 to validate "
        f"against real Stripe"
    )
stripe_guard.assert_test_mode_credentials()

import stripe  # noqa: E402
from app.core.config import settings  # noqa: E402

stripe.api_key = settings.stripe_secret_key

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def card():
    return stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})


print("\n=== 1. Annual subscription on a test clock ===")
clock = stripe.test_helpers.TestClock.create(
    frozen_time=int(__import__("time").time()), name="FC 5A.3c annual",
)
cust = stripe.Customer.create(description="FC 5A.3c annual", test_clock=clock.id)
pm_a = card()
stripe.PaymentMethod.attach(pm_a.id, customer=cust.id)
stripe.Customer.modify(
    cust.id, invoice_settings={"default_payment_method": pm_a.id},
)
prod = stripe.Product.create(name="FC 5A.3c annual membership")
annual_price = stripe.Price.create(
    product=prod.id, unit_amount=29000, currency="aud",
    recurring={"interval": "year"},
)
check("annual Price has a yearly interval",
      annual_price.recurring.interval == "year",
      f"{annual_price.unit_amount} {annual_price.currency}/"
      f"{annual_price.recurring.interval}")

sub = stripe.Subscription.create(
    customer=cust.id, items=[{"price": annual_price.id}],
    expand=["latest_invoice"],
)
inv = sub.latest_invoice
check("initial annual invoice is paid",
      inv.status == "paid" and inv.amount_paid == 29000,
      f"{inv.status} {inv.amount_paid} {inv.currency}")
item = sub["items"].data[0]
period_end = item.current_period_end
check("the period is a year, not a month",
      period_end - item.current_period_start > 300 * 24 * 3600,
      f"{(period_end - item.current_period_start) // 86400} days")

print("\n=== 2. Annual renewal, by advancing the clock a year ===")
stripe.test_helpers.TestClock.advance(clock.id, frozen_time=period_end + 3600)
for _ in range(60):
    clock = stripe.test_helpers.TestClock.retrieve(clock.id)
    if clock.status == "ready":
        break
    __import__("time").sleep(2)
invoices = stripe.Invoice.list(subscription=sub.id, limit=10)
paid = [i for i in invoices.data if i.status == "paid"]
check("a second annual invoice was raised and paid",
      len(paid) >= 2, f"{len(paid)} paid invoices, clock={clock.status}")
if len(paid) >= 2:
    check("the renewal charged the same agreed amount",
          all(i.amount_paid == 29000 for i in paid),
          f"amounts={[i.amount_paid for i in paid]}")

print("\n=== 3. Cancel at period end, then resume ===")
stripe.Subscription.modify(sub.id, cancel_at_period_end=True)
s = stripe.Subscription.retrieve(sub.id)
check("cancelling keeps the subscription active to the period end",
      s.status == "active" and s.cancel_at_period_end is True,
      f"status={s.status}")
stripe.Subscription.modify(sub.id, cancel_at_period_end=False)
s = stripe.Subscription.retrieve(sub.id)
check("resuming restores the same agreement",
      s.id == sub.id and s.cancel_at_period_end is False, s.id)

print("\n=== 4. Payment-method update is scoped to one subscription ===")
sub2 = stripe.Subscription.create(
    customer=cust.id, items=[{"price": annual_price.id}],
)
pm_b = card()
stripe.PaymentMethod.attach(pm_b.id, customer=cust.id)
stripe.Subscription.modify(sub.id, default_payment_method=pm_b.id)
s1 = stripe.Subscription.retrieve(sub.id)
s2 = stripe.Subscription.retrieve(sub2.id)
c = stripe.Customer.retrieve(cust.id)
check("the chosen subscription takes the new card",
      s1.default_payment_method == pm_b.id)
check("the sibling subscription is untouched",
      s2.default_payment_method is None)
check("the customer default is untouched",
      c.invoice_settings.default_payment_method == pm_a.id)

print("\n=== 5. A setup-mode Session for collecting the card ===")
setup_session = stripe.checkout.Session.create(
    mode="setup", customer=cust.id, currency="aud",
    success_url="https://example.test/ok?session_id={CHECKOUT_SESSION_ID}",
    cancel_url="https://example.test/no",
    metadata={
        "purchase_type": "collective_membership_payment_method",
        "collective_membership_id": "cmem_probe",
    },
)
check("setup Session opens and carries our metadata",
      setup_session.mode == "setup"
      and setup_session.metadata["purchase_type"]
      == "collective_membership_payment_method",
      setup_session.id)
check("it exposes a SetupIntent for the webhook to resolve",
      bool(setup_session.setup_intent), str(setup_session.setup_intent))

print("\n=== 6. One-time membership: payment mode, no subscription ===")
one_time_customer = stripe.Customer.create(description="FC 5A.3c one-time")
one_time = stripe.checkout.Session.create(
    mode="payment",
    customer=one_time_customer.id,
    line_items=[{
        "quantity": 1,
        "price_data": {
            "currency": "aud",
            "unit_amount": 19900,
            "product_data": {
                "name": "Life in Full Colour — membership",
                "description": "One-time membership payment",
            },
        },
    }],
    success_url="https://example.test/ok",
    cancel_url="https://example.test/no",
    metadata={
        "purchase_type": "collective_membership_one_time",
        "collective_membership_id": "cmem_probe",
    },
    payment_intent_data={"metadata": {
        "purchase_type": "collective_membership_one_time",
    }},
)
check("one-time Session is payment mode", one_time.mode == "payment")
check("it creates no subscription",
      getattr(one_time, "subscription", None) is None)
check("it is priced inline at the agreed amount",
      one_time.amount_total == 19900, f"{one_time.amount_total} {one_time.currency}")
check("it starts unpaid, so a completed Session is not proof of payment",
      one_time.payment_status == "unpaid", one_time.payment_status)

print("\n=== cleanup ===")
for s_id in (sub.id, sub2.id):
    try:
        stripe.Subscription.cancel(s_id)
    except Exception as exc:
        print(f"  (subscription {s_id}: {exc})")
for c_id in (cust.id, one_time_customer.id):
    try:
        stripe.Customer.delete(c_id)
    except Exception as exc:
        print(f"  (customer {c_id}: {exc})")
print("  done")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} provider checks passed")
sys.exit(1 if failed else 0)
