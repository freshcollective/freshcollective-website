## Finite-Instalment Payment Plans — Architecture Audit

**Date:** 2026-08-14
**Status:** Audit only. No code changed.
**Scope:** What it would take to safely enable member checkout for
`PaymentOptionSchedule.schedule_type='recurring_installments'` — a
finite plan such as "$20/week × 10 payments" attached to a Payment
Option. Explicitly not an indefinite subscription.

Written to answer the questions raised in the M1 palette/hero pass
before we commit to a Commerce milestone.

---

### 1. What's already in the database

The schedule model is fully shaped for finite instalments — the
storage is not the blocker.

`backend/app/models/payment_option_schedule.py`:

- `schedule_type` — enum, values `pay_in_full`, `recurring_installments`, `manual`.
- `installment_amount_cents` — per-instalment charge.
- `installment_count` — total number of instalments (this is what makes
  the plan *finite*).
- `stripe_interval` + `stripe_interval_count` — already comment-mapped to
  Stripe recurring params (`weekly → 'week'×1`, `fortnightly → 'week'×2`,
  `monthly → 'month'×1`).
- `total_amount_cents` — expected to ≈ `installment_amount_cents × installment_count`.

Model docstring already says:

> `recurring_installments → Stripe mode 'subscription' (Phase B: deferred)`

so the intended direction is documented in code even though the wiring
was never built.

### 2. Where checkout is gated today

There is exactly one guard.

`backend/app/services/checkout_orchestration.py:241-248`

```python
if payment_schedule.schedule_type == "recurring_installments":
    raise HTTPException(
        status_code=503,
        detail="Recurring instalment payment plans are not yet available…",
    )
```

Everything else in unified checkout — pricing, fee calc, duplicate
guard, PaymentTransaction insert, Session creation — is only reachable
for `pay_in_full`.

Frontend mirrors the same policy through the new
`_schedule_is_member_checkoutable()` helper
(`backend/app/spaces/routes.py:96`) which surfaces
`is_member_checkoutable=false` on any non-`pay_in_full` schedule so the
member UI never advertises a payment method the backend would refuse.

### 3. Current PaymentTransaction shape

`backend/app/models/payment.py` (~lines 121-305):

- One `PaymentTransaction` row = one money movement.
- Has `payment_option_id`, `payment_option_schedule_id`,
  `provider_checkout_session_id`, `provider_payment_intent_id`,
  `provider_subscription_id`, `provider_invoice_id`, `stripe_mode`.
- **No `parent_transaction_id` or `purchase_batch_id`.** There is no
  way today to link the ten weekly charges of a $20×10 plan back to
  one purchase. This will matter for the admin ledger and creator
  earnings view.
- `platform_fee_basis_points` is snapshot per-row, so a fee-rate
  change mid-plan wouldn't retro-apply.

### 4. Current webhook coverage

`backend/app/webhooks/routes.py`:

| Event | Handled? | What it does |
|---|---|---|
| `checkout.session.completed` | ✅ | Marks txn `succeeded`; calls `apply_intent()` → creates `PathwayEntitlement` + `AccessPass` + `PaymentOptionGrant`; sets `fulfilment_status='applied'`. |
| `checkout.session.expired` | ✅ | Cancels txn, releases capacity holds. |
| `payment_intent.payment_failed` | ✅ | Marks txn `failed`. |
| `invoice.payment_succeeded` | ❌ | Needed for every instalment charge after the first. |
| `invoice.payment_failed` | ❌ | Needed for dunning + access decisions. |
| `customer.subscription.updated` | ❌ | Needed to observe schedule advancement + completion. |
| `customer.subscription.deleted` | ❌ | Needed for end-of-plan and mid-plan cancellation. |
| `charge.refunded` | ❌ | Refund flow is scaffolded only. |
| `charge.dispute.created` | ❌ | Not wired. |

Idempotency today = row-lock (`SELECT … FOR UPDATE`) + status-guard on
the PaymentTransaction. There is **no `processed_webhook_events`
table**, so a re-delivered event of a *different* type against the same
session is not de-duped. This is fine for the one-shot pay-in-full
world; it will need a proper event ledger for recurring.

### 5. Access grant timing

For pay-in-full, access is granted synchronously inside
`_handle_checkout_completed` → `apply_intent()` in
`backend/app/services/purchase_fulfilment.py`.

For a finite instalment plan we need a **product decision** — see §9.

### 6. Existing subscription code

Grep for `Subscription`, `subscription_schedule`, `SetupIntent`, `invoice.*`:

- `CreatorSubscription` (`backend/app/models/creator_billing.py`) — for
  Creator plan billing (Phase 3). Never populated today; `stripe_subscription_id` always NULL.
- `MemberSubscription` (`backend/app/models/sales.py`) — sales pipeline
  tracking only, not connected to Stripe.
- No `SetupIntent` usage anywhere.
- `stripe_interval` / `stripe_interval_count` on `PaymentOptionSchedule`
  are populated but never read by any Stripe call.
- No use of `stripe.SubscriptionSchedule` or `stripe.Subscription`.

**Conclusion:** the SDK is in place (`stripe>=10.0.0` in
`backend/requirements.txt`), but the recurring surface area is entirely
un-implemented.

### 7. Duplicate-purchase guard

`check_same_option_not_active()` in
`backend/app/services/checkout_orchestration.py` blocks re-purchase of
the same Payment Option while the member has an active AccessPass or
entitlement from that option.

For finite plans this is *almost* enough — an in-flight plan issues an
active AccessPass on payment 1, so re-purchase is blocked from then on.
Gaps:

- No DB unique constraint on `(user_id, payment_option_id)` — the guard
  is application-layer only.
- If we choose to defer AccessPass creation until payment 10 (see §9),
  the guard fails between payment 1 and 10.

### 8. Creator payments ledger

Admin payments view (`backend/app/admin/routes.py`) shows one row per
PaymentTransaction. A 50-member × 10-week plan would produce 500 rows
per term — usable but noisy. The absence of a batch id means creator
earnings can't easily be aggregated as "this member bought Awaken on
2026-08-10 for $200 gross" — it looks like ten separate purchases.

Recommend: introduce a `purchase_batch_id` (UUID, indexed) at the same
time we ship recurring, and back-fill pay-in-full to a batch-of-one so
the ledger becomes uniformly groupable.

---

## Product decisions still open

The audit's real purpose. These need answers before code.

### 9. When is access granted?

Three defensible options:

- **A — Full access on payment 1.** Member gets the AccessPass and the
  full weekly allowance from day 1. Simple UX; matches how pay-in-full
  feels. Requires a robust *revoke on payment failure* story (see §11).
- **B — Access rolls forward one instalment at a time.** Payment N buys
  week N. Payment failure trivially stops future access. Cognitively
  heavier — a member who missed one week loses everything remaining.
- **C — Hybrid: full access on payment 1, but AccessPass valid_until
  advances only as payments clear.** Access is "conditional".
  Most complex; probably right if the Creator wants a "membership that
  keeps flowing while you pay".

**Recommendation:** **A**, with a clear cancellation/revocation policy
(§11). Matches the founder principle "no punitive UX", puts the risk
on the platform not the member.

### 10. Which Stripe object is the source of truth?

Two Stripe-native routes:

- **`stripe.SubscriptionSchedule`** with a single `phase` of length
  `installment_count` and `end_behavior='cancel'`.
  - ✅ Naturally finite. Stripe stops billing after N.
  - ✅ Single object per purchase → cleanly maps to a `purchase_batch_id`.
  - ✅ Emits `invoice.payment_succeeded` / `invoice.payment_failed`
    per instalment.
  - ⚠️ Requires a `Price` object with the right `recurring` params —
    either created ad-hoc per purchase or pre-provisioned per schedule.
  - ⚠️ Not directly startable from Stripe Checkout in `mode='subscription'`
    without extra plumbing. Cleanest is: use Checkout `mode='setup'` to
    collect a payment method + create Customer, then create the
    SubscriptionSchedule server-side and immediately advance to the
    first invoice.
- **`stripe.Subscription`** created directly with `cancel_at` set to
  now + N intervals, or with a scheduled cancellation via
  SubscriptionSchedule wrapping it.
  - ✅ Simpler to spin up from `mode='subscription'` Checkout.
  - ⚠️ "Finite" is enforced by our own `cancel_at` — a config drift can
    silently turn it into an indefinite subscription. Higher risk.

**Recommendation:** **SubscriptionSchedule with `end_behavior='cancel'`**.
The finiteness is enforced by Stripe, not by us. Worth the extra plumbing.

### 11. Failed payment on instalment 4 of 10

Stripe's Smart Retries will retry a failed invoice for up to 4 weeks
by default (dunning). Product needs to answer:

- **After first failure:** email member + hold access, or revoke immediately?
- **After Smart Retries exhausted:** cancel schedule + revoke AccessPass?
  Keep AccessPass valid for the weeks already paid?
- **Creator visibility:** does the Creator see "payment 4 failed"? Where?

**Recommendation:** hold access after first failure (7-day grace
matching Stripe's first retry window), revoke on Smart Retries
exhaustion, refund any weeks not yet consumed. Surface every state
change in the Creator's Payments view.

### 12. Cancellation

Two vectors:

- **Member-initiated:** UI does not exist. Decision: allow at all?
  If yes, do we refund unconsumed weeks?
- **Creator-initiated:** UI does not exist. Same question.
- **Admin-initiated:** possible today via Stripe Dashboard; won't
  reflect in our DB until `charge.refunded` webhook is wired.

**Recommendation:** ship v1 with **no member self-cancel**, Creator
can request cancellation via an Admin request, Admin refunds unused
weeks in Stripe Dashboard, and we wire `customer.subscription.deleted`
to update our DB accordingly. Adds friction on purpose.

### 13. Early completion + refunds

- **Early completion:** if the plan bills 10 of 10 and Stripe emits
  `subscription.deleted`, we should mark the batch complete and leave
  the AccessPass validity untouched.
- **Refunds:** `charge.refunded` handler is a stub. Must be built. On
  full refund of a single instalment, mark that txn refunded and hold
  the batch; on batch refund, revoke AccessPass.

### 14. Idempotency + replay

Before enabling recurring:

- Add explicit `Idempotency-Key` header on every Stripe write —
  format `{purchase_batch_id}:{stripe_operation}`.
- Add a `processed_webhook_events` table keyed on Stripe `event.id`
  with a `first_seen_at` / `processed_at` pair, checked at the very
  top of the webhook.

### 15. Fee calculation per instalment

`platform_fee_basis_points` is snapshot per PaymentTransaction. For an
instalment plan we should snapshot the rate on the *batch* (at
purchase time) and copy it to each child txn — so if we change fees
on 2026-09-01, an August purchase still bills at August's rate for
all 10 weeks. Requires a `purchase_batch_id` (§8) or an equivalent
parent row.

---

## What has to exist before we can ship

Minimum viable finite-instalment support:

1. `purchase_batch_id` (UUID) column on `PaymentTransaction` + a
   `purchase_batches` table with `payment_option_schedule_id`, `total_expected_installments`, `installments_paid`, `status`,
   `stripe_subscription_schedule_id`.
2. `processed_webhook_events(event_id PK, processed_at)` table.
3. Webhook handlers for:
   - `invoice.payment_succeeded` → create per-instalment PaymentTransaction row, increment `installments_paid`.
   - `invoice.payment_failed` → hold access; email member.
   - `customer.subscription.updated` → track schedule state.
   - `customer.subscription.deleted` → mark batch complete or cancelled per reason.
   - `charge.refunded` → refund handling.
4. Checkout path for `recurring_installments`:
   - Use `mode='setup'` Checkout to collect payment method + create Customer.
   - On `setup_intent.succeeded`, create SubscriptionSchedule with
     `end_behavior='cancel'` and a single phase whose
     `duration = {interval, interval_count}` covers the finite plan
     (Stripe removed `phases[].iterations`; the current supported
     field is `duration`, encoding the same idea).
   - Create the AccessPass immediately (option A above) with a
     conditional-active status.
5. Remove the 503 guard in
   `backend/app/services/checkout_orchestration.py:241-248`.
6. Update `_schedule_is_member_checkoutable()` in
   `backend/app/spaces/routes.py:96` to also return True for
   `recurring_installments` — the frontend then automatically starts
   surfacing weekly plans on the member Series sidebar (the UI is
   already multi-schedule ready).
7. Creator-visible surfaces:
   - Payments view: group by batch, show "$200 · 4 of 10 paid".
   - Series member list: show pass state incl. "on plan".
8. Admin refund tooling — at minimum a webhook-driven refund that
   updates our records when the admin refunds in Stripe Dashboard.

Order-of-magnitude sizing: **not a bolt-on**. Two to three weeks of
focused work, own commerce milestone. Do not casually attach to M1.

---

## What we should ship in M1 (this pass)

Only what makes the *deferral* safe and structurally future-ready:

- ✅ `_schedule_is_member_checkoutable()` — done.
- ✅ Frontend `SidebarWaysToJoin` filters to checkoutable schedules — done.
- ✅ `ScheduleChoice` renders multi-schedule shape ready for "Pay in
  full + $X/week × N" without further refactor — done.
- ✅ Tests: `backend/tests/test_series_member_schedule_flag.py` covers
  the four cases — done.
- ✅ 503 guard remains in place — done.

M1 does **not** need to touch the Stripe recurring path. It only needs
to guarantee no member ever sees a payment method that would 503.
That guarantee is met.

---

## Files referenced

- `backend/app/models/payment_option_schedule.py`
- `backend/app/models/payment.py`
- `backend/app/services/checkout_orchestration.py`
- `backend/app/services/purchase_fulfilment.py`
- `backend/app/webhooks/routes.py`
- `backend/app/spaces/routes.py`
- `backend/app/spaces/_series_member_routes.py`
- `backend/tests/test_series_member_schedule_flag.py`
- `frontend/src/app/spaces/[slug]/gathering-series/[series-slug]/SeriesSidebar.tsx`
- `backend/requirements.txt` (`stripe>=10.0.0`)
- `docs/stripe-implementation-plan.md` (2026-06 audit, pre-dates this work)
