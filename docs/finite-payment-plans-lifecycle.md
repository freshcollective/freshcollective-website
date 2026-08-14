## Finite Payment Plans — Lifecycle + Provider Contract (FIP1)

**Date:** 2026-08-14
**Status:** Foundation (FIP1) documentation. No live billing yet.
**Companion doc:** [`docs/finite-instalment-audit.md`](./finite-instalment-audit.md) — the audit that motivated this milestone.

This document captures the durable contracts introduced by FIP1 so
FIP2–FIP5 can be built without re-litigating design decisions.

---

### 1. What "finite payment plan" means (product)

A member agrees to pay:

- **amount per payment** (e.g. $30)
- **fixed number of payments** (e.g. 10)
- **cadence** (weekly / fortnightly / monthly)

After payment N, Stripe stops billing automatically. This is not an
indefinite subscription. The finiteness is enforced by Stripe via
`SubscriptionSchedule.end_behavior='cancel'`.

Access is granted after the **first successful payment** and stays
live through the plan (subject to the payment-problem grace policy
below).

---

### 2. Domain model

Two new tables, one linkage column set.

**`purchase_plans`** (migration 115). Parent record for a member's
finite-plan agreement. Full column list is on
`app/models/purchase_plan.py`. Stripe object ids
(`provider_customer_id`, `provider_setup_session_id`,
`provider_payment_method_id`, `provider_subscription_schedule_id`,
`provider_subscription_id`) all live here, not on individual
transactions. Partial-unique indexes ensure any Stripe object
anchors at most one plan.

**`webhook_events`** (migration 117). Durable
`(provider, provider_event_id)` idempotency store, consumed by
`services/webhook_idempotency.py::process_webhook_event()`.
Provider-agnostic.

**Linkage columns** (migration 116, all nullable):
`payment_transactions.purchase_plan_id`,
`access_passes.purchase_plan_id`,
`pathway_entitlements.purchase_plan_id`. Populated by FIP3
handlers. Legacy pay-in-full rows leave these NULL.

**Not introduced.** No new subscription/checkout tables — those
concepts belong to Stripe and are referenced by id.

---

### 3. Plan lifecycle

```
                    ┌─────────────────┐
                    │  pending_setup  │  ← plan row created;
                    └────────┬────────┘    setup Checkout Session open
                             │
       setup abandoned →     │     setup + first invoice OK
                             │
              ┌──────────────┼──────────────┐
              ▼                             ▼
          ┌────────┐                     ┌────────┐
          │ failed │                     │ active │
          └────────┘                     └───┬────┘
                                             │
                          invoice failed →   │
                                             ▼
                                     ┌─────────────────┐
                        recovery →   │ payment_problem │
                              ┌──────┤                 │
                              │      └────────┬────────┘
                              │               │
                              │        smart retries exhausted
                              │               │
                              │               ▼
                              │           ┌────────┐
                              │           │ failed │
                              │           └────────┘
                              │
                        ┌─────▼─────┐
                        │  active   │
                        └─────┬─────┘
                              │
                installments_paid == expected
                              │
                              ▼
                        ┌───────────┐
                        │ completed │
                        └───────────┘

  admin/creator cancel from any active-ish state → cancelled
```

State semantics are the source-of-truth docstrings on
`PurchasePlanStatus` in `app/models/purchase_plan.py`. Do not
duplicate them elsewhere.

---

### 4. v1 product rules — LOCKED

These four rules are the source of truth for FIP2+ implementation.
Do not override without an explicit product decision recorded here.

**Access grant** — the full Payment Option grant bundle is applied
after the first successful instalment. The `AccessPass` and
`PathwayEntitlement` rows the plan produces are marked
`status='active'` immediately when payment 1 clears. The member
does not experience "waiting for permission" between weekly
payments.

**Failed later instalment** — access remains live during a **7-day
grace / retry period** measured from the `invoice.payment_failed`
timestamp. Stripe's Smart Retries run during this window. On
recovery → plan returns to `active`. On exhaustion → plan
transitions to `failed`; final suspension / revocation mechanics
land in FIP3.

**Fee accounting** — `platform_fee_basis_points` is snapshot on
the `PurchasePlan` at creation. Every per-invoice
`PaymentTransaction` belonging to that plan uses that snapshot.
A later Creator plan / fee-rate change does NOT alter an already-
agreed finite payment plan.

**Cancellation** — no member self-service cancellation or
proration in v1. Creator/admin cancellation is handled by admin
refund + Stripe Dashboard action, mirrored into our DB by the
`customer.subscription.deleted` handler.

---

### 5. Stripe provider contract

**Object:** `stripe.SubscriptionSchedule` with:
- One `phase`, length = `installments_expected`
- `end_behavior='cancel'`
- Anchored to a `Price` with `recurring={interval, interval_count}`
  derived from the schedule's `stripe_interval` / `stripe_interval_count`

**Bootstrapping (FIP2):**
1. Create Stripe `Customer` (or reuse existing).
2. Create Checkout Session in `mode='setup'` with `customer` set.
   Store `session.id` on `purchase_plans.provider_setup_session_id`.
3. On `checkout.session.completed` (mode=setup), retrieve the
   attached `PaymentMethod`, set it as the Customer's default.
4. Server-side, create the `SubscriptionSchedule` with the correct
   `Price` and phase length. Persist `subscription_schedule.id`.
5. When Stripe advances the schedule and fires the first invoice,
   `invoice.payment_succeeded` transitions the plan `pending_setup
   → active` and grants access.

**Idempotency keys.** Every Stripe write must pass an
`Idempotency-Key` header in the format
`{purchase_plan_id}:{operation}` — e.g.
`pplan_abc123:create_customer`,
`pplan_abc123:create_setup_session`,
`pplan_abc123:create_subscription_schedule`. This makes retry-safe
FIP2 handlers straightforward.

---

### 6. Webhook contract

FIP1 adds the idempotency infrastructure but does not implement
these business handlers yet.

| Stripe event | Phase | Domain effect |
|---|---|---|
| `checkout.session.completed` (mode=setup, metadata carries `purchase_plan_id`) | FIP2 | Retrieve PaymentMethod → attach to Customer → create SubscriptionSchedule → persist ids on `PurchasePlan`. Plan stays `pending_setup` until the first invoice. |
| `invoice.payment_succeeded` (subscription-driven, metadata carries `purchase_plan_id`) | FIP3 | Create per-invoice `PaymentTransaction` row (status=`succeeded`, `purchase_plan_id` populated). Increment `installments_paid`. On first payment: transition `pending_setup → active`, run `apply_intent()` to create AccessPass + PathwayEntitlement with `purchase_plan_id` populated. On last payment (`installments_paid == installments_expected`): transition `active → completed`. |
| `invoice.payment_failed` | FIP3 | Create per-invoice `PaymentTransaction` row (status=`failed`). Transition plan `active → payment_problem`. Access stays live during grace window. |
| `customer.subscription.updated` | FIP3 | Sync plan status where Stripe's view diverges (e.g. Stripe marks subscription `past_due` — mirror to `payment_problem`). |
| `customer.subscription.deleted` | FIP3 | Distinguish reasons: normal end → `completed`; retries exhausted → `failed`; admin cancel → `cancelled`. Revoke access if `failed` or `cancelled` (revocation mechanics land later). |
| `charge.refunded` | FIP4 | Mark corresponding `PaymentTransaction` refunded; evaluate whether to hold the plan (single refund) or cancel + revoke (full refund). |
| `charge.dispute.created` | FIP4 | Hold payout, surface to Creator. |

Every FIP2+ handler must run inside
`process_webhook_event(db, provider='stripe', provider_event_id=event.id, event_type=event.type, handler=...)`.

**Handler idempotency contract.** The idempotency helper uses a
lease-based recovery design so a worker that crashes mid-handler
(including *after* the handler committed domain writes but before
the outcome marker was recorded) does not permanently strand the
event. When the lease expires, a later delivery reclaims the row
and re-runs the handler. **Handlers must therefore be
idempotent** — check the natural key (`provider_invoice_id`,
`provider_payment_intent_id`, `provider_charge_id`) for an
existing row before writing, or use `INSERT ... ON CONFLICT DO
NOTHING` semantics. Do not assume the helper prevents
double-execution — it prevents it under normal timing, not after
a crash.

---

### 6b. Test vs. live mode

`PurchasePlan.stripe_mode` (`'test'` / `'live'`) is captured when
the plan row is created and never mutated afterwards.

**Webhook reconciliation must validate against the Stripe event's
`livemode` field**, not by inspecting API-key prefixes. Every
Stripe event object carries a boolean `livemode` — `false` when
delivered by a test-mode key, `true` when live. FIP3 handlers
should:

1. Look the plan up by the provider id in the event (usually
   `subscription`, `invoice.subscription`, or `customer`).
2. Reject the event when `event.livemode != (plan.stripe_mode == 'live')`
   — return a 200 (so Stripe stops retrying) but mark the
   `WebhookEvent` row `skipped` with a descriptive error. This
   defends against a test-mode webhook ever mutating a live plan
   (or vice-versa).

Do not attempt to derive the mode from the delivery — the webhook
does not carry an API key, and `stripe.api_key` at the point of
signature verification is our own choice. `event.livemode` is the
only authoritative signal.

---

### 7. Fee calculation

`platform_fee_basis_points` is snapshot on the `PurchasePlan` at
creation and copied to each per-invoice `PaymentTransaction`. This
preserves the fee rate promised at purchase time even if the
platform fee is changed later.

Per-instalment fee math (per `PaymentTransaction`):
```
platform_fee_cents        = gross_amount_cents * platform_fee_basis_points / 10000
net_creator_amount_cents  = gross_amount_cents - platform_fee_cents
```

---

### 8. Duplicate-purchase strategy (FIP2)

FIP2 will extend `check_same_option_not_active()` in
`services/checkout_orchestration.py` with a fourth rule:

**Rule D — active plan.** If there exists a `PurchasePlan` row
with:
- `member_user_id = user.id`
- `payment_option_id = option.id`
- `status IN ('pending_setup', 'active', 'payment_problem')`

… the guard raises 409 with a member-facing message. This blocks
the accidental double-start of the same plan without needing an
`AccessPass` to be materialised (which for FIP2's option A only
happens on invoice 1).

Does NOT block:
- Completed plans (`status='completed'`) — repurchase of a future
  term is legitimate.
- Cancelled or failed plans — the member is free to try again.
- A different Payment Option (upgrade to a bundled tier).
- A pay-in-full purchase — routing to the existing rules A/B/C
  which check AccessPass / PathwayEntitlement.

---

### 9. Schedule validation

`services/schedule_validation.py::validate_recurring_installments_payload()`
runs on Creator schedule create/update **only when the row is being
saved as `status='published'`**. Draft rows can be incomplete so a
Creator can save mid-authoring. Rules:

- `installment_amount_cents > 0`
- `installment_count >= 2`
- Cadence in `{(week, 1), (week, 2), (month, 1)}`
- `currency` is a 3-letter ISO 4217 code
- If `total_amount_cents` is present, it matches
  `installment_amount_cents × installment_count` within a
  1-cent-per-instalment rounding tolerance

Same rules apply to plan creation in FIP2 via
`validate_recurring_installments_row()` on the persisted row.

---

### 10. What FIP1 does NOT change

- `services/checkout_orchestration.py:241` — recurring_installments
  still returns 503.
- `_schedule_is_member_checkoutable()` in `spaces/routes.py:96`
  still returns False for recurring_installments.
- Pay-in-full checkout, its webhook, and its fulfilment path.
- Standalone Gathering ticket flow, capacity holds, pending-
  payment behaviour.
- EMBODY weekly/fortnightly draft schedules stay draft.
- The three existing webhook handlers
  (`checkout.session.completed`, `checkout.session.expired`,
  `payment_intent.payment_failed`) are not retrofitted with the
  new idempotency helper — that is a future housekeeping pass.

---

### 11. Phase roadmap

| Phase | Scope |
|---|---|
| **FIP1** (this) | Foundation: models, migrations, webhook idempotency, schedule validation, docs, tests. |
| **FIP2** | Stripe setup checkout + SubscriptionSchedule creation + first payment/access. Removes the 503 guard for `recurring_installments`. |
| **FIP3** | Recurring invoice reconciliation, Smart Retries + grace, plan completion. |
| **FIP4** | Member payment-plan progress UI + Creator grouped Payments-received UI. |
| **FIP5** | Hardening: refunds, cancellation, operational tooling. |

Do not merge phases. Each phase should independently be safe to
ship even if the next is delayed.
