# Fresh Collective — Stripe Implementation Plan

**Date:** 2026-06-06  
**Status:** Spec only — no code changed  
**Author:** Claude Code (audit + synthesis)

---

## Table of Contents

1. [Current Architecture Summary](#1-current-architecture-summary)
2. [Existing Models and Fields](#2-existing-models-and-fields)
3. [Existing Routes and Endpoints](#3-existing-routes-and-endpoints)
4. [Existing Frontend Payment UI](#4-existing-frontend-payment-ui)
5. [Existing Stripe TODOs](#5-existing-stripe-todos)
6. [Current Gaps and Risks](#6-current-gaps-and-risks)
7. [Q1: What can currently be bought?](#q1-what-can-currently-be-bought)
8. [Q2: How does access currently work?](#q2-how-does-access-currently-work)
9. [Q3: What payment records exist?](#q3-what-payment-records-exist)
10. [Q4: What Stripe pieces are scaffolded?](#q4-what-stripe-pieces-are-scaffolded)
11. [Q5: Recommended paid pathway purchase flow](#q5-recommended-paid-pathway-purchase-flow)
12. [Q6: Failure, cancellation, and refund handling](#q6-failure-cancellation-and-refund-handling)
13. [Q7: Platform fee calculation](#q7-platform-fee-calculation)
14. [Q8: Creator payouts](#q8-creator-payouts)
15. [Q9: Creator subscription billing](#q9-creator-subscription-billing)
16. [Q10: Bundle-ready design](#q10-bundle-ready-design)
17. [Q11: Paid booking-ready design](#q11-paid-booking-ready-design)
18. [Q12: Admin panel implications](#q12-admin-panel-implications)
19. [Q13: Creator Studio implications](#q13-creator-studio-implications)
20. [Q14: Member experience implications](#q14-member-experience-implications)
21. [Phased Implementation Plan](#phased-implementation-plan)
22. [Decisions needed from Lindsey](#decisions-needed-from-lindsey)
23. [Files involved in Phase 1](#files-involved-in-phase-1)

---

## 1. Current Architecture Summary

Fresh Collective has a **well-designed payment and entitlement architecture that is 80% ready for Stripe** — the database models, access control logic, admin tooling, and checkout UI shell are all in place. What is missing is the actual Stripe API wiring (session creation, webhooks, and Connect).

### What exists and works today

| Component | Status |
|-----------|--------|
| `PaymentTransaction` model with all Stripe fields pre-built | ✅ Model ready, all columns NULL for Stripe fields |
| `PathwayEntitlement` model with access_type, status, source | ✅ Controls paid access, works today |
| Admin manual purchase → creates entitlement + transaction | ✅ Fully working |
| Access check logic in backend (`_check_pathway_access`) | ✅ Correctly gates one_time/subscription pathways |
| Pathway checkout page with TODO integration points | ✅ Shell exists, shows correct UI states |
| Creator plan model (Basic 8% / Plus 3%) | ✅ Seeded and in use |
| Fee calculation logic in admin manual purchase | ✅ Calculates basis_points correctly |
| Admin revenue and payments dashboards | ✅ Working with manual data |
| Payout status tracking (pending/paid/held) | ✅ Fields exist, manual-only today |

### What is missing

| Component | Status |
|-----------|--------|
| `stripe` Python package | ❌ Not installed |
| Stripe env vars (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, etc.) | ❌ Not in `.env.example` |
| Stripe Checkout Session creation endpoint | ❌ Not implemented |
| Stripe webhook handler | ❌ Not implemented |
| `@stripe/stripe-js` in frontend | ❌ Not installed |
| Checkout page CTA wired to backend | ❌ Has TODO comments only |
| Success/cancel pages after Stripe redirect | ❌ Not implemented |
| Stripe Connect (creator payouts) | ❌ Not started |
| Creator subscription billing via Stripe | ❌ Not started |

### Verdict

The right first integration is **paid pathway checkout via Stripe Checkout**. Everything is scaffolded for it. Creator subscription billing and creator payouts should follow as Phase 2 and Phase 3.

---

## 2. Existing Models and Fields

### PaymentTransaction (`payment_transactions`)

`/home/lindsey/fc-production/backend/app/models/payment.py`

| Field | Type | Notes |
|-------|------|-------|
| `id` | str PK | |
| `transaction_type` | enum | `creator_subscription_payment`, `member_pathway_purchase`, `member_collective_purchase`, `member_pathway_subscription`, `member_collective_subscription`, `refund`, `adjustment` |
| `status` | enum | `pending`, `succeeded`, `failed`, `refunded`, `partially_refunded`, `disputed`, `cancelled` |
| `payment_provider` | enum | `manual`, `stripe` |
| `payer_user_id` | FK→users | SET NULL on delete |
| `creator_user_id` | FK→users | SET NULL on delete |
| `space_id` | FK→spaces | SET NULL on delete |
| `pathway_id` | FK→pathways | SET NULL on delete |
| `entitlement_id` | FK→pathway_entitlements | SET NULL on delete |
| `creator_plan_id` | FK→creator_plans | SET NULL on delete |
| `creator_subscription_id` | FK→creator_subscriptions | SET NULL on delete |
| `currency` | str(3) | default='AUD' |
| `gross_amount_cents` | int | Total member paid |
| `platform_fee_basis_points` | int | e.g., 800 = 8%; 0 for creator subs |
| `platform_fee_cents` | int | FC platform fee |
| `processing_fee_cents` | int \| NULL | **TODO: populate from Stripe webhook** |
| `net_creator_amount_cents` | int \| NULL | gross - platform_fee |
| `net_platform_amount_cents` | int \| NULL | platform_fee (or full gross for creator subs) |
| `provider_checkout_session_id` | str(200) \| NULL | **TODO: Stripe** |
| `provider_payment_intent_id` | str(200) \| NULL | **TODO: Stripe** |
| `provider_charge_id` | str(200) \| NULL | **TODO: Stripe** |
| `provider_invoice_id` | str(200) \| NULL | **TODO: Stripe (subscriptions)** |
| `provider_subscription_id` | str(200) \| NULL | **TODO: Stripe (subscriptions)** |
| `notes` | Text \| NULL | |
| `payout_status` | enum | `not_applicable`, `pending`, `paid`, `held`, `cancelled` |
| `payout_marked_at` | datetime \| NULL | When admin marked paid/held |
| `payout_reference` | str(200) \| NULL | Transfer ID or batch ref |
| `created_at` | datetime | |
| `updated_at` | datetime | |

**Missing fields (should be added before Phase 1 go-live):**

- `idempotency_key` — prevents duplicate webhook processing (see Q5)
- `stripe_fee_cents` — distinguish Stripe processing fee from platform fee (processing_fee_cents exists but is never set)
- `refunded_amount_cents` — track partial refunds separately from status

### PathwayEntitlement (`pathway_entitlements`)

`/home/lindsey/fc-production/backend/app/models/platform.py`

| Field | Type | Notes |
|-------|------|-------|
| `id` | str PK | |
| `user_id` | FK→users CASCADE | |
| `space_id` | FK→spaces CASCADE | |
| `pathway_id` | FK→pathways CASCADE | |
| `source` | enum | `free`, `included`, `manual_grant`, `one_time_purchase`, `subscription`, `admin` |
| `status` | enum | `active`, `revoked`, `expired`, `cancelled`, `pending` |
| `starts_at` | datetime | default=NOW() |
| `ends_at` | datetime \| NULL | NULL = perpetual access |
| `granted_by_user_id` | FK→users | Admin/creator who granted |
| `revoked_by_user_id` | FK→users \| NULL | |
| `revoked_at` | datetime \| NULL | |
| `notes` | Text \| NULL | |
| `stripe_checkout_session_id` | str(200) \| NULL | **TODO: Stripe** |
| `stripe_payment_intent_id` | str(200) \| NULL | **TODO: Stripe** |
| `stripe_subscription_id` | str(200) \| NULL | **TODO: Stripe subscriptions** |
| `created_at` | datetime | |
| `updated_at` | datetime | |

**Note:** There is **no unique constraint on `(user_id, pathway_id)`** in the current model. The admin manual purchase endpoint handles duplicate grants by reactivating an existing revoked entitlement. This pattern must be preserved for Stripe webhooks — check for existing entitlement before creating a new one.

### CreatorPlan (`creator_plans`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | str PK | |
| `slug` | str(100) unique | e.g., 'basic', 'plus' |
| `name` | str | |
| `monthly_price_cents` | int | Creator pays this to FC |
| `transaction_fee_basis_points` | int | % FC takes from member purchases (800=8%, 300=3%) |
| `collective_limit` | int | Max spaces |
| `pathway_limit` | int \| NULL | Not enforced yet |
| `is_active` | bool | |

**Seeded plans** (migration 018):
- Basic: $19/month (1900 cents), 800 bps (8%), 1 collective
- Plus: $79/month (7900 cents), 300 bps (3%), 3 collectives

### CreatorSubscription (`creator_subscriptions`)

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | FK→users | One active per creator |
| `creator_plan_id` | FK→creator_plans | |
| `status` | enum | `active`, `trialing`, `past_due`, `cancelled`, `unpaid` |
| `stripe_subscription_id` | str \| NULL | **TODO: Phase 3** |
| `stripe_customer_id` | str \| NULL | **TODO: Phase 3** |

---

## 3. Existing Routes and Endpoints

### Admin routes (`/api/admin/…`) — all require `role='admin'`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/admin/payments` | List all transactions (with filters) |
| GET | `/api/admin/payments/summary` | Aggregate metrics |
| POST | `/api/admin/payments/manual-pathway-purchase` | Simulate purchase → creates transaction + entitlement |
| POST | `/api/admin/payments/manual` | Raw placeholder transaction only |
| GET | `/api/admin/revenue/summary` | FC revenue vs creator sales split |
| GET | `/api/admin/revenue/by-creator` | Per-creator earnings breakdown |
| GET | `/api/admin/creator-billing` | All creators with plan + usage |
| PATCH | `/api/admin/creator-billing/{user_id}/plan` | Change creator plan |
| GET | `/api/admin/creator-plans` | List plans |
| POST | `/api/admin/creator-plans` | Create new plan |
| GET | `/api/admin/creator-subscriptions` | List creator subscriptions |
| GET | `/api/admin/users/simple` | Dropdown list of users |
| GET | `/api/admin/pathways/paid-simple` | Dropdown list of paid pathways |
| GET | `/api/admin/platform/overview` | Platform stats |
| GET | `/api/admin/platform/collectives` | All spaces |
| GET | `/api/admin/platform/creators` | All creators |
| GET | `/api/admin/platform/users` | All users |
| GET | `/api/admin/platform/access` | Access requests + invitations |

### Missing routes needed for Phase 1

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/checkout/pathway` | Create Stripe Checkout Session (authenticated member) |
| POST | `/api/webhooks/stripe` | Stripe webhook handler (no auth, uses sig verification) |
| GET | `/api/pathways/{pathway_id}/entitlement` | Check member's current entitlement status |

---

## 4. Existing Frontend Payment UI

### Checkout page — `src/app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx`

**Exists and shows correct states:**
- `access_type === 'free'` or `'included'` → redirects to pathway (no purchase needed)
- `status === 'coming_soon'` → "Coming soon" message
- `user_has_access === true` → "You already have access" with Begin/Continue/Review button
- `access_type === 'one_time'` and no access → checkout UI showing:
  - Pathway title, description, space name
  - Price (e.g., $50.00 AUD)
  - Fee breakdown (FC platform fee %)
  - Creator net
  - "Unlock pathway" button — **has TODO comment, not wired to backend**
  - Terms note

**TODO comment in checkout page (exact):**
```
// TODO: Stripe Checkout integration
// 1. Resolve creator/stripe_account_id
// 2. Create Stripe Checkout Session with price_id
// 3. Redirect member to Stripe Checkout
// 4. On Stripe webhook (checkout.session.completed):
//    - Create PathwayEntitlement (source='one_time_purchase')
//    - Mark PaymentTransaction as succeeded
```

### Pathway about page — `src/app/spaces/[slug]/pathways/[pathway-slug]/about/page.tsx`

- Shows pathway details
- Displays correct CTA based on `access_type` and `user_has_access`
- "Get access" → links to `/checkout` page
- No Stripe wiring yet

### Admin Manual Purchase modal (payments page)

- Fully functional today — lets admin simulate a purchase for testing
- Creates real `PaymentTransaction` + `PathwayEntitlement` records
- Used for testing and beta access grants

---

## 5. Existing Stripe TODOs

### Backend — `app/models/payment.py`
- TODO comments on `processing_fee_cents`: "TODO: Stripe webhook"
- TODO comments on all `provider_*` fields: "TODO: Stripe"
- TODO comments on `payout_status.paid`: "TODO: set when Stripe Connect transfer confirmed"
- TODO comments on `payout_status.held`: "TODO: set when payout on hold (dispute)"

### Backend — `app/models/platform.py` (PathwayEntitlement)
- TODO comments on all three `stripe_*` fields

### Backend — `app/models/creator_billing.py` (CreatorSubscription)
- TODO comments on `stripe_subscription_id` and `stripe_customer_id`

### Frontend — `src/app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx`
- Full 4-step TODO comment (see Section 4 above)

### Frontend — `src/app/for-creators/page.tsx`
- TODO about Stripe creator billing checkout

### Frontend — `src/app/admin/billing/page.tsx`
- Displays `stripe_subscription_id` and `stripe_customer_id` fields (always NULL today)

**No Stripe package installed anywhere. No Stripe env vars. No webhook routes. The scaffolding is clean and intentional.**

---

## 6. Current Gaps and Risks

### Critical gaps before Phase 1

1. **No idempotency key on PaymentTransaction** — without this, a duplicate webhook delivery creates a duplicate transaction and entitlement. Must add before Stripe goes live.

2. **No unique constraint on (user_id, pathway_id) for PathwayEntitlement** — the manual purchase code handles duplicates but the constraint should be enforced at DB level or handled explicitly. Current admin code does re-activate existing revoked entitlements, which is the right behaviour. Stripe webhook must follow the same pattern.

3. **No success/cancel redirect pages** — Stripe Checkout redirects to `success_url` and `cancel_url`. These pages don't exist yet. They need to be created before Stripe can be used.

4. **Checkout page CTA is not wired** — the "Unlock pathway" button has a TODO and does nothing. Must wire to backend before any real purchase.

5. **No `stripe` package in requirements.txt** — must add `stripe>=10.0.0` before backend development.

6. **No Stripe env vars** — must add to `.env.example` and production config.

### Design risks

7. **`processing_fee_cents` is not currently populated** — Stripe charges 1.7% + 30c (Australia). This should be populated from the webhook `charge.balance_transaction.fee`. The current `net_creator_amount_cents` calculation is `gross - platform_fee` which does not account for Stripe's own cut. The **real** creator net should be `gross - platform_fee - stripe_fee`. The admin revenue pages will need to clearly show the distinction.

8. **Creator fee is captured at transaction time** — this is correct and already implemented. `platform_fee_basis_points` is stored on the transaction. If a creator later upgrades their plan, old transactions correctly preserve the historical rate.

9. **No `stripe_customer_id` on User model** — when building Stripe Checkout, we may want to pass a customer ID for receipts. This should be stored on the user or on a separate table (not yet present). For Phase 1 Checkout, this is optional (Stripe creates an anonymous session) but recommended for Phase 2/3.

10. **No Stripe webhook secret in config** — Stripe webhooks must be verified with `stripe.Webhook.construct_event()`. The secret comes from the Stripe dashboard when you register the webhook endpoint. Must be added to settings before production.

11. **`space_id` on PaymentTransaction is set** — but `creator_user_id` must also be reliably populated. The manual purchase endpoint looks up `pathway.space.creator_id`. The same lookup must happen in the Stripe checkout session creation endpoint to correctly associate the transaction with the creator.

### Minor risks

12. **`access_type='subscription'` for pathways** — the model supports recurring pathway subscriptions but the checkout page and fee calculation are not fully designed for this case. For Phase 1, only `access_type='one_time'` should be wired to Stripe. Subscription pathways can follow.

13. **No currency conversion** — everything is AUD. Stripe supports multi-currency but Fresh Collective is currently single-currency. This is fine for Phase 1.

---

## Q1: What can currently be bought?

| Item | Status | Notes |
|------|--------|-------|
| **Paid pathways (one-time)** | Backend + model ready; frontend checkout shell exists; Stripe NOT wired | `PathwayEntitlement` created by admin manual purchase; checkout page has TODO |
| **Paid pathway subscriptions** | Model exists (`access_type='subscription'`); NOT wired anywhere | Would need recurring Stripe subscription |
| **Creator subscriptions (Basic/Plus)** | Internal record only; Stripe NOT wired | Admin can change plan; no billing happens |
| **Event bookings (paid)** | NOT supported — no price field on `Event` or `EventBooking` | Model has `booking_access_type` (pathway_required vs all_members) but no payment |
| **Bundles** | NOT supported — no Offer/Bundle model | |
| **Paid resources** | NOT supported — `SpaceResource` has no price field | |
| **Member platform subscriptions** | Tables exist (`subscription_plans`, `member_subscriptions`) but disconnected | Sales pipeline tracking only; no checkout |
| **Admin/manual pathway purchases** | ✅ Fully working | `POST /api/admin/payments/manual-pathway-purchase` |

---

## Q2: How does access currently work?

### Access decision tree (backend, `_check_pathway_access` in `app/spaces/routes.py`)

```
1. user.role in ('creator', 'admin')           → GRANT (platform-level bypass)
2. SpaceMembership.role in ('creator', 'moderator'), status='active'  → GRANT (space team)
3. pathway.status in ('draft', 'archived')     → DENY 403
4. pathway.status == 'coming_soon'             → DENY 403
5. pathway.access_type == 'free'               → GRANT (anyone authenticated)
6. pathway.access_type == 'included'           → GRANT if SpaceMembership.status='active'; else DENY
7. pathway.access_type in ('one_time', 'subscription'):
   → GRANT if PathwayEntitlement.status='active'; else DENY
```

### Gaps in access logic

- **Step 7 checks `status='active'` only** — `pending` entitlements (e.g., before webhook arrives) would be correctly denied. This is intentional: access is only granted after payment confirmation, not during checkout.
- **No check for `ends_at`** — expired entitlements (`ends_at < NOW()`) are not automatically revoked in the check. If we use subscription pathways with expiry dates, `_check_pathway_access` must also check `ends_at IS NULL OR ends_at > NOW()`. This is a **small bug** to fix before subscription pathways go live — not urgent for one-time purchases.
- **`PathwayEntitlement.status` field** — there is no background job to auto-expire entitlements when `ends_at` passes. For Phase 1 (one-time purchases), this is fine since `ends_at` will be NULL. For subscription pathways, this must be added.

### Resource access

- `SpaceResource` records have no access gate — all active space members can see published resources.
- Resources tied to a pathway (`scope='pathway'`, `pathway_id` set) are not access-gated separately — they are accessible to anyone who can see the pathway. This is probably fine.

### Booking access

- `Event.booking_access_type`:
  - `'all_members'` → any space member can book
  - `'pathway_required'` → member must have `SpaceMembership` AND the required pathway accessible
- No payment gate on bookings currently. Paid bookings are not supported.

### Manual access grants

- Admin can use `POST /api/admin/payments/manual-pathway-purchase` → creates `PathwayEntitlement(source='admin', status='active')` immediately.
- Creator Studio likely has a similar manual grant (not audited in detail, but `granted_by_user_id` field exists on the entitlement model).

### Creator/admin bypass

- Any user with `role='creator'` or `role='admin'` bypasses all pathway access checks (Step 1). This means creators can see all pathways across all spaces. This is intentional for the admin and creator team but is broad — creators at Space A can see all of Space B's content. Acceptable for current scale.

---

## Q3: What payment records exist?

### Currently tracked (fully)

| Field | Tracked | Notes |
|-------|---------|-------|
| payer/member | ✅ | `payer_user_id` FK→users |
| creator | ✅ | `creator_user_id` FK→users |
| space/collective | ✅ | `space_id` FK→spaces |
| pathway | ✅ | `pathway_id` FK→pathways |
| gross amount | ✅ | `gross_amount_cents` int |
| currency | ✅ | `currency` str(3) default=AUD |
| platform fee | ✅ | `platform_fee_cents`, `platform_fee_basis_points` |
| creator net | ✅ | `net_creator_amount_cents` |
| platform net | ✅ | `net_platform_amount_cents` |
| payout status | ✅ | `payout_status` enum with 5 states |
| payment provider | ✅ | `payment_provider` enum (manual/stripe) |
| transaction type | ✅ | 7 types covering all scenarios |
| status | ✅ | 7 statuses |
| manual/test marker | ✅ | `payment_provider='manual'` is the marker |
| timestamps | ✅ | `created_at`, `updated_at`, `payout_marked_at` |
| notes | ✅ | `notes` text field |

### Currently tracked (fields exist, not yet populated)

| Field | Status | Notes |
|-------|--------|-------|
| Stripe processing fee | `processing_fee_cents` exists, always NULL | Must populate from `charge.balance_transaction.fee` in webhook |
| Stripe checkout session ID | `provider_checkout_session_id` exists, NULL | Will be set when session created |
| Stripe payment intent ID | `provider_payment_intent_id` exists, NULL | Will be set from webhook |
| Stripe charge ID | `provider_charge_id` exists, NULL | Will be set from webhook |
| Stripe invoice ID | `provider_invoice_id` exists, NULL | For creator subscription payments |
| Stripe subscription ID | `provider_subscription_id` exists, NULL | For recurring payments |
| Payout reference | `payout_reference` exists, NULL | Transfer ID when Connect is live |
| Payout date | `payout_marked_at` exists, NULL | When admin marks as paid |

### Not tracked (missing, needs decision)

| Field | Recommendation |
|-------|---------------|
| `idempotency_key` | **Add before Phase 1** — prevents duplicate webhook processing. Use `stripe_checkout_session_id` or a separate field. |
| `refunded_amount_cents` | Add for partial refund tracking. Today status goes to `partially_refunded` but the refunded amount is not stored. |
| `stripe_fee_cents` | Rename or alias `processing_fee_cents` to make Stripe's cut explicit. |
| Booking/event link | `pathway_id` is set but there is no `event_id` or `booking_id` field for future paid booking transactions. |

---

## Q4: What Stripe pieces are scaffolded?

### Backend

- All provider ID fields on `PaymentTransaction`: `provider_checkout_session_id`, `provider_payment_intent_id`, `provider_charge_id`, `provider_invoice_id`, `provider_subscription_id` — all present, all NULL
- All Stripe fields on `PathwayEntitlement`: `stripe_checkout_session_id`, `stripe_payment_intent_id`, `stripe_subscription_id` — all present, all NULL
- All Stripe fields on `CreatorSubscription`: `stripe_subscription_id`, `stripe_customer_id` — both NULL
- `PaymentProvider` enum already has `stripe` as a value
- `PayoutStatus` enum has `paid` status with TODO comment for Stripe Connect
- `processing_fee_cents` field on `PaymentTransaction` with TODO comment

### Frontend

- Checkout page shell exists at `src/app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx`
- 4-step TODO comment describing the exact Stripe integration needed
- Admin billing page shows `stripe_subscription_id` and `stripe_customer_id` columns (both NULL)

### Config/env

- **No Stripe env vars** in `.env.example` or `app/core/config.py`
- **No stripe package** in `requirements.txt`
- **No `@stripe/stripe-js`** in frontend `package.json`

### Summary

The scaffolding is intentional and clean. The TODO comments describe exactly what needs to happen. There are no accidental partial integrations or conflicting code to clean up.

---

## Q5: Recommended paid pathway purchase flow

### Pre-conditions

- Pathway has `access_type='one_time'` and `price_cents > 0`
- Member is authenticated
- Creator has an active `CreatorSubscription` with a `CreatorPlan`

### Step-by-step flow

#### 1. Member clicks paid pathway CTA

- On the pathway about page or pathway card, member sees "Unlock — $XX.XX" button
- Clicks → navigates to `/spaces/{slug}/pathways/{pathway-slug}/checkout`

#### 2. System checks login status

- Frontend: if `user` is null → redirect to `/login?next={checkout_url}`
- Backend (on session creation endpoint): `get_current_user` dependency returns 401 if not authenticated

#### 3. System checks for existing entitlement

- Checkout page fetches pathway data which includes `user_has_access: bool`
- If `user_has_access === true` → show "You already have access" state (already implemented in checkout page)
- Backend session creation endpoint also checks for existing active entitlement → returns 409 if already purchased

#### 4. Member clicks "Unlock pathway" → frontend calls `POST /api/checkout/pathway`

**Request:**
```json
{
  "pathway_id": "uuid",
  "success_url": "https://app.freshcollective.com/spaces/{slug}/pathways/{pathway-slug}/checkout?success=true&session_id={CHECKOUT_SESSION_ID}",
  "cancel_url": "https://app.freshcollective.com/spaces/{slug}/pathways/{pathway-slug}/checkout?cancelled=true"
}
```

**Backend creates a `PaymentTransaction` in `pending` status immediately:**
```python
# Lookup: pathway, space, creator's current plan + fee rate
# Calculate: fee_bps from creator's active CreatorSubscription → CreatorPlan.transaction_fee_basis_points

txn = PaymentTransaction(
    transaction_type='member_pathway_purchase',
    status='pending',
    payment_provider='stripe',
    payer_user_id=current_user.id,
    creator_user_id=space.creator_id,
    space_id=pathway.space_id,
    pathway_id=pathway.id,
    currency=pathway.currency,
    gross_amount_cents=pathway.price_cents,
    platform_fee_basis_points=plan.transaction_fee_basis_points,
    platform_fee_cents=round(pathway.price_cents * plan.transaction_fee_basis_points / 10000),
    net_creator_amount_cents=pathway.price_cents - platform_fee_cents,
    net_platform_amount_cents=platform_fee_cents,
    payout_status='pending',
)
db.add(txn)
db.commit()
```

**Backend creates Stripe Checkout Session:**
```python
session = stripe.checkout.Session.create(
    mode='payment',
    line_items=[{
        'price_data': {
            'currency': pathway.currency.lower(),
            'product_data': {
                'name': pathway.title,
                'description': f'Access to {pathway.title} — {space.name}',
            },
            'unit_amount': pathway.price_cents,
        },
        'quantity': 1,
    }],
    metadata={
        'pathway_id': pathway.id,
        'payer_user_id': current_user.id,
        'transaction_id': txn.id,  # links webhook back to our pending transaction
    },
    customer_email=current_user.email,
    success_url=success_url,
    cancel_url=cancel_url,
    # For Stripe Connect (Phase 2):
    # payment_intent_data={'application_fee_amount': platform_fee_cents, 'transfer_data': {'destination': creator_stripe_account_id}}
)
```

**Store session ID on the pending transaction:**
```python
txn.provider_checkout_session_id = session.id
db.commit()
```

**Response: `{"checkout_url": session.url}`**

#### 5. Frontend redirects to Stripe Checkout

```typescript
window.location.href = data.checkout_url
```

Member completes payment on Stripe's hosted page.

#### 6. Stripe webhook fires `checkout.session.completed`

Stripe POSTs to `POST /api/webhooks/stripe`.

**Backend webhook handler:**
```python
event = stripe.Webhook.construct_event(
    payload=body, sig_header=stripe_sig, secret=settings.stripe_webhook_secret
)
if event.type == 'checkout.session.completed':
    session = event.data.object
    transaction_id = session.metadata['transaction_id']
    pathway_id = session.metadata['pathway_id']
    payer_user_id = session.metadata['payer_user_id']
    handle_checkout_completed(session, transaction_id, pathway_id, payer_user_id, db)
```

#### 7. PaymentTransaction is updated

```python
txn = db.get(PaymentTransaction, transaction_id)
if txn.status == 'succeeded':
    return  # idempotency — webhook already processed

# Retrieve charge for Stripe processing fee
payment_intent = stripe.PaymentIntent.retrieve(session.payment_intent, expand=['latest_charge.balance_transaction'])
balance_txn = payment_intent.latest_charge.balance_transaction

txn.status = 'succeeded'
txn.provider_payment_intent_id = session.payment_intent
txn.provider_charge_id = payment_intent.latest_charge.id
txn.processing_fee_cents = balance_txn.fee  # Stripe's cut (1.75% + 30c)
# Adjust net_creator if processing fee is to be absorbed by creator:
# txn.net_creator_amount_cents = txn.gross_amount_cents - txn.platform_fee_cents - txn.processing_fee_cents
db.commit()
```

#### 8. PathwayEntitlement is created

```python
# Check for existing (idempotency)
existing = db.query(PathwayEntitlement).filter_by(
    user_id=payer_user_id, pathway_id=pathway_id
).first()

if existing:
    existing.status = 'active'
    existing.stripe_checkout_session_id = session.id
    existing.stripe_payment_intent_id = session.payment_intent
    entitlement = existing
else:
    entitlement = PathwayEntitlement(
        user_id=payer_user_id,
        space_id=pathway.space_id,
        pathway_id=pathway_id,
        source='one_time_purchase',
        status='active',
        stripe_checkout_session_id=session.id,
        stripe_payment_intent_id=session.payment_intent,
    )
    db.add(entitlement)

# Link transaction to entitlement
txn.entitlement_id = entitlement.id
db.commit()
```

#### 9. Member gets access

- `_check_pathway_access` now finds `PathwayEntitlement.status='active'` → GRANT
- No additional action needed; access is immediate on next page load/request

#### 10. Admin Revenue updates automatically

- Revenue dashboard queries `PaymentTransaction` where `status='succeeded'`
- The new succeeded transaction is immediately visible in admin stats

#### 11. Creator earnings update

- `PaymentTransaction.net_creator_amount_cents` was set at creation time
- `payout_status='pending'` by default → visible in "Pending Payouts" admin metric
- Creator can see their earnings via Creator Studio (to be built Phase 2)

#### 12. Member sees confirmation

- Stripe redirects to `success_url`: `/spaces/{slug}/pathways/{pathway-slug}/checkout?success=true&session_id=cs_...`
- Frontend detects `?success=true` → shows "Payment successful! You now have access." with Begin button
- Pathway data refetches → `user_has_access === true`

#### 13. Creator sees sale

- Phase 2: Creator Studio sales/earnings page shows the transaction
- Phase 1: Admin can see it in Payments dashboard

#### 14. Admin sees transaction and revenue

- `GET /api/admin/payments` → new row with status=succeeded, provider=stripe
- `GET /api/admin/revenue/summary` → updated totals

---

## Q6: Failure, cancellation, and refund handling

### Checkout cancelled

- Member clicks "Back" on Stripe Checkout → redirected to `cancel_url`
- Frontend detects `?cancelled=true` → shows "Payment cancelled. No charge was made."
- The pending `PaymentTransaction` remains in `status='pending'`
- A background job (or on-demand cleanup) should eventually mark stale pending transactions as `cancelled`
- **Recommended:** Add a cron or on-checkout-load check: if a pending transaction exists for this user+pathway that is >1 hour old, mark it `cancelled`
- No `PathwayEntitlement` is created → member has no access → correct

### Payment failed

- Stripe Checkout handles most failures on its own page (bad card, etc.)
- If payment fails after Stripe confirms intent but before capture: Stripe fires `payment_intent.payment_failed`
- Backend should handle this event:
  ```python
  if event.type == 'payment_intent.payment_failed':
      payment_intent_id = event.data.object.id
      txn = db.query(PaymentTransaction).filter_by(
          provider_payment_intent_id=payment_intent_id
      ).first()
      if txn:
          txn.status = 'failed'
          db.commit()
  ```
- No entitlement is created → correct

### Webhook delayed (payment succeeded but webhook late)

- Member is on the success page but webhook hasn't fired yet
- Recommendation: success page should poll `GET /api/pathways/{pathway_id}/entitlement` for up to 10 seconds before showing the "access granted" confirmation
- Alternatively (simpler for Phase 1): success page fetches pathway data which includes `user_has_access`; if still false, show "Payment received — access being confirmed. Refresh in a moment."
- Do NOT rely solely on the Stripe `success_url` redirect to confirm payment — always verify via webhook or Stripe API

### Duplicate webhook event

- Stripe can deliver the same event more than once
- **Idempotency check required:** `if txn.status == 'succeeded': return` (already in the flow above)
- Similarly: `if existing entitlement and status == 'active': skip creation`
- Consider adding a `processed_webhook_events` table or at minimum checking `stripe_checkout_session_id` uniqueness

### Member already has entitlement

- Checkout page shows "You already have access" state (already implemented)
- Backend session creation endpoint returns 409 if `PathwayEntitlement.status='active'` already exists
- Do not create duplicate checkout sessions

### Refund requested

- Admin initiates refund via Stripe Dashboard or API call
- Stripe fires `charge.refunded` (full) or `charge.refund.updated` (partial)
- Backend webhook handler:
  ```python
  if event.type == 'charge.refunded':
      charge_id = event.data.object.id
      txn = db.query(PaymentTransaction).filter_by(provider_charge_id=charge_id).first()
      txn.status = 'refunded'
      txn.payout_status = 'cancelled'  # creator doesn't get paid for refunded transactions
      db.commit()
  ```
- For full refund: also revoke the entitlement
  ```python
  if entitlement:
      entitlement.status = 'revoked'
      entitlement.revoked_at = now()
      entitlement.notes = f'Revoked due to full refund (charge {charge_id})'
      db.commit()
  ```
- For partial refund:
  ```python
  txn.status = 'partially_refunded'
  # Entitlement remains active — partial refund = member retains access
  ```
- **Decision needed:** Does a full refund always revoke pathway access? Recommended: yes, but discuss with Lindsey.

### Chargeback/dispute

- Stripe fires `charge.dispute.created`
- Backend:
  ```python
  txn.status = 'disputed'
  txn.payout_status = 'held'  # put creator payout on hold
  ```
- Entitlement: leave active until dispute resolved (member likely still using the content)
- On `charge.dispute.funds_withdrawn`: creator payout remains held
- On `charge.dispute.closed` (lost): txn → `status='refunded'`, entitlement → `status='revoked'`
- On `charge.dispute.closed` (won): txn stays `disputed`, set `payout_status='pending'` to release payout

### Entitlement revocation

- Manual: admin sets `PathwayEntitlement.status='revoked'`, `revoked_at=now()`, `revoked_by_user_id=admin_id`
- Automatic on refund (full): as above
- On revocation, member immediately loses access (next `_check_pathway_access` call returns false)

---

## Q7: Platform fee calculation

### Where fee rate is stored

The fee rate comes from:
```
CreatorSubscription → CreatorPlan.transaction_fee_basis_points
```

When a member purchases a pathway, the backend looks up the **creator of the pathway's space**, finds their active `CreatorSubscription`, then gets the `transaction_fee_basis_points` from their current `CreatorPlan`.

### Snapshot at time of purchase (correct and already implemented)

The `PaymentTransaction.platform_fee_basis_points` field stores the rate that was in effect **at the time of purchase**. This means:

- Creator upgrades from Basic (8%) to Plus (3%) tomorrow → old transactions keep 8%, new transactions use 3%
- Creator downgrades → old transactions keep the lower rate
- **This is correct behavior.** The fee was earned at the rate in effect when the member paid.

### Fee calculation (current implementation, correct)

```python
platform_fee_cents = round(gross_amount_cents * platform_fee_basis_points / 10000)
net_creator_amount_cents = gross_amount_cents - platform_fee_cents
```

**Example (Basic plan, $50 pathway):**
```
gross = 5000 cents ($50.00)
fee_bps = 800 (8%)
platform_fee = round(5000 * 800 / 10000) = round(400) = 400 cents ($4.00)
creator_net = 5000 - 400 = 4600 cents ($46.00)
```

### Adding Stripe processing fee

When Stripe is live, we must also account for Stripe's processing fee (Australia: 1.75% + 30c for domestic cards).

**Recommended:** Treat Stripe processing fee as absorbed by Fresh Collective (FC keeps `platform_fee`, pays Stripe from that). This simplifies creator earnings:

```
gross = 5000
fc_platform_fee = 400 (8%)
stripe_processing_fee = round(5000 * 175 / 10000) + 30 = 88 + 30 = 118 cents
fc_net_after_stripe = 400 - 118 = 282 cents  # what FC actually keeps
creator_net = 4600 cents  # unchanged, simple for creators to understand
```

**Alternative:** Pass Stripe fee through to creator (common in marketplace platforms):
```
creator_net = 5000 - 400 - 118 = 4482 cents
```

**Recommendation:** Keep it simple for Phase 1. Absorb Stripe fee into FC margin. Creators see clean `gross - fee %`. Revisit when transaction volume is high enough to matter.

### Rounding

Always use `round()` (Python banker's rounding). Never use `floor()` for fee calculations — this slightly favors creators on odd amounts, which is a good default.

### Currency fields

Currently all AUD. The model supports multi-currency (`currency` field on Pathway and PaymentTransaction). For Phase 1, enforce AUD only. The `currency` field on `Pathway` should be validated to 'AUD' in the checkout endpoint.

---

## Q8: Creator payouts

### Current state

- `payout_status` field on `PaymentTransaction` with 5 states: `not_applicable`, `pending`, `paid`, `held`, `cancelled`
- Admin can manually mark payouts as paid via the admin panel (TODO: not yet implemented in UI)
- No Stripe Connect integration

### Recommendation: Manual payouts in Phase 1, Stripe Connect in Phase 2

**Phase 1 (manual):**
- Admin sees pending payout total in Revenue dashboard (already shows)
- Admin pays creators manually (bank transfer, etc.)
- Admin marks transactions as `payout_status='paid'` with `payout_reference='bank_transfer_ref'` via admin UI
- Creator sees earnings and "pending payout" in Creator Studio (basic earnings view)

**Phase 2 (Stripe Connect):**
- Creator onboards with Stripe Connect (Express account recommended for Australia)
- `stripe_connect_account_id` stored on a new `CreatorStripeAccount` model (or on the `User` model)
- When FC receives payment, automatic transfer to creator's connected account
- `payout_status='paid'` set automatically when transfer succeeds
- `payout_reference=transfer_id`

### New model needed for Phase 2 (do not build in Phase 1)

```python
class CreatorStripeAccount(Base):
    __tablename__ = 'creator_stripe_accounts'
    id: str (PK)
    user_id: str (FK→users, unique)
    stripe_account_id: str (e.g., 'acct_...')
    onboarding_completed: bool (default=False)
    charges_enabled: bool (default=False)  # from Stripe account object
    payouts_enabled: bool (default=False)  # from Stripe account object
    onboarding_link_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

### Admin needs (Phase 1)

- Revenue dashboard: "Pending payouts: $XXX" (already shows)
- Payments table: filter by `payout_status='pending'` to see who to pay
- Button: "Mark as paid" → sets `payout_status='paid'`, `payout_marked_at=now()`, `payout_reference=admin_notes`

### Creator needs (Phase 1)

- Earnings summary: total earned, pending payout amount
- List of purchases in their collectives
- Phase 2: Connect onboarding button, payout history

---

## Q9: Creator subscription billing

### Current state

- `CreatorPlan` model exists with Basic ($19/month, 8%) and Plus ($79/month, 3%) seeded
- `CreatorSubscription` has `stripe_subscription_id` and `stripe_customer_id` (both NULL)
- Admin can manually change creator plan assignment
- No Stripe billing happens

### Recommendation: Phase 3 (after pathway checkout and payout readiness)

**Reasoning:**
1. Pathway checkout (Phase 1) generates immediate member value and demonstrates payment infrastructure
2. Creator payouts (Phase 2) give creators confidence in the platform before being charged for it
3. Creator subscription billing (Phase 3) is a separate billing relationship that doesn't block member purchases

**Phase 3 implementation:**

1. Creator clicks "Subscribe" on the creator billing/pricing page
2. Backend creates a Stripe Customer for the creator
3. Backend creates a Stripe Subscription for the chosen plan (Basic/Plus)
4. Webhook `invoice.payment_succeeded` → creates `PaymentTransaction(type='creator_subscription_payment', status='succeeded')`
5. `CreatorSubscription.stripe_subscription_id` and `stripe_customer_id` populated
6. `CreatorSubscription.status` stays `'active'`

**Failed billing handling:**
- Stripe fires `invoice.payment_failed`
- `CreatorSubscription.status` → `'past_due'`
- After grace period (e.g., 3 failed attempts): `status` → `'cancelled'`
- When cancelled: creator's collectives become read-only (not deleted)
- Members retain access to purchased pathways (entitlements are not affected)

**Until Phase 3:**
- Keep existing internal/manual creator subscription state
- Admin manages plan changes manually
- No real billing — this is the current state and it is explicitly fine

---

## Q10: Bundle-ready design

### What bundles would require

A "bundle" or "offer" would allow selling multiple pathways together at a single price.

Example: "The Rooms Bundle — 3 pathways for $89" instead of $39 each.

### Recommended approach (do not build yet)

Add a lightweight `Offer` model when bundles are needed:

```python
class Offer(Base):
    __tablename__ = 'offers'
    id: str (PK)
    space_id: str (FK→spaces)
    title: str
    description: str | None
    price_cents: int
    currency: str
    access_type: str  # 'one_time', 'subscription'
    billing_interval: str | None
    is_active: bool
    stripe_price_id: str | None  # pre-created Stripe Price object

class OfferItem(Base):
    __tablename__ = 'offer_items'
    id: str (PK)
    offer_id: str (FK→offers)
    pathway_id: str (FK→pathways)
    position: int
```

**Purchasing an offer:**
- `PaymentTransaction.offer_id` (new FK field) — identifies the bundle purchased
- On webhook `checkout.session.completed`: create one `PathwayEntitlement` per `OfferItem`
- All entitlements share the same `PaymentTransaction`

### How to not block bundles in Phase 1

The current architecture is already bundle-compatible because:
- `PathwayEntitlement` is per-pathway (many entitlements per purchase is natural)
- `PaymentTransaction` can link to multiple entitlements via `entitlement_id` (though currently single) — this FK may need to become a one-to-many relationship or move to a join table
- `PaymentTransaction.pathway_id` would need to become `offer_id` OR we keep a single "primary pathway" and use the offer_id for grouping

**Recommendation for Phase 1:** Keep `PaymentTransaction.pathway_id` for single-pathway purchases. When bundles are added, add `offer_id` field. The entitlement logic is already per-pathway so it's naturally compatible.

---

## Q11: Paid booking-ready design

### Current state

- `Event.booking_access_type`: `'all_members'` or `'pathway_required'`
- `EventBooking` has no price field
- `Event` has no price field

### Recommended approach (do not build yet)

To add paid bookings later, add price fields to `Event`:

```python
# Add to Event model:
booking_price_cents: int | None  # NULL = free
booking_currency: str  # default='AUD'
```

Add `booking_id` FK to `PaymentTransaction`:
```python
booking_id: str | None  # FK→event_bookings, ondelete=SET NULL
```

**Flow would be identical to pathway checkout** except:
- Line item is the event title + date
- On payment completion: `EventBooking` status set to `'confirmed'` (or created if it didn't exist yet)
- `transaction_type='member_booking_purchase'` (add to enum)

### How to not block paid bookings in Phase 1

The `PaymentTransaction` model has `pathway_id` and `space_id` FKs. Adding `booking_id` later is a simple migration. The webhook handler pattern will be reusable.

**Recommendation:** No action needed in Phase 1 — the architecture supports it with one migration and a new transaction type.

---

## Q12: Admin panel implications

### Changes needed once Stripe is live

#### Admin Payments page

- Add `stripe_checkout_session_id` column (or link) — helpful for debugging
- Add filter by `payment_provider` (manual vs stripe)
- Add payout management: "Mark as paid" button per transaction or bulk action
- Consider adding a "Payout batch" concept: select transactions, set payout reference, mark all as paid

#### Admin Revenue page

- Add line for "Stripe processing fees" (once `processing_fee_cents` is populated)
- Show "FC net after Stripe fees" vs "FC gross platform fees"
- Add timeline chart (weekly/monthly)

#### Admin Creator Billing page

- Show `stripe_subscription_id` and `stripe_customer_id` as clickable links (Stripe Dashboard)
- Show `status` badge with real Stripe status (active, past_due, cancelled)
- Add "View in Stripe" link
- Add subscription start date and next billing date

#### Admin Pricing page

- May need `stripe_price_id` field per plan (for Stripe subscription creation)
- Currently shows static plans — fine for Phase 1

#### Admin Collectives page

- No changes needed for Phase 1

#### Admin Users page

- Show `stripe_customer_id` if/when added to User model

---

## Q13: Creator Studio implications

### What creators will need (Phase 2+, do not build in Phase 1)

1. **Earnings overview:**
   - Total earned (all time)
   - Pending payout
   - Paid out (all time)
   - Recent sales (list of pathway purchases with member name, date, amount)

2. **Payout status:**
   - "Your next payout is approximately $XXX" (pending transactions)
   - "Last payout: $XXX on [date]"
   - Phase 2: Stripe Connect onboarding button and status

3. **Pathway purchase stats:**
   - Per-pathway: number of purchases, total earned, average price paid
   - Useful for pricing decisions

4. **Stripe Connect onboarding (Phase 2):**
   - "Set up payouts" banner if `CreatorStripeAccount` not yet onboarded
   - Onboarding link (generated by backend, expires)
   - Status: "Payouts enabled" / "Verification pending" / "Action required"

5. **Failed payments/refunds:**
   - Show if any of their sales were refunded (affects earnings)
   - No action needed for creator on refunds — just visibility

6. **Creator subscription status (Phase 3):**
   - "Your plan: Creator Basic — $19/month"
   - "Next billing date: [date]"
   - "Upgrade to Creator Plus" CTA

---

## Q14: Member experience implications

### Paid pathway cards

Currently: pathway cards on the collectives page show an `access_label` (Free, Included, Purchased, Locked).

Recommendation for Phase 1:
- Locked pathways should show the price: "Unlock — $50"
- Clicking takes member to checkout page (already implemented)

### Pathway checkout page

Already implemented for state management. Needs:
- "Unlock pathway" button wired to `POST /api/checkout/pathway`
- Loading state while redirect happens
- Success state on return (`?success=true`)
- Cancel state on return (`?cancelled=true`)

### Success page

Stripe redirects to `success_url`. This can be the same checkout page with `?success=true` param:
- Show: "Payment successful! You now have access to [Pathway Title]."
- Button: "Start [Pathway Title]" → link to first step
- Should re-fetch pathway data to confirm `user_has_access === true`

### Cancel page

Stripe redirects to `cancel_url`. Same checkout page with `?cancelled=true`:
- Show: "Your payment was cancelled. No charge was made."
- Button: "Try again" (resets state, shows normal checkout UI)

### Already purchased

If member revisits checkout and already has access:
- Already implemented: shows "You already have access" state with Begin button

### Failed payment

- If Stripe's own failure UI doesn't handle it (rare), redirect to cancel URL
- Show: "Payment failed. Please check your card details and try again."

### No access (locked pathway)

- Currently: `_check_pathway_access` returns 403 when accessing locked step
- Recommendation: Add a friendly redirect — if 403 on a step, redirect to pathway checkout page
- Include note about why access is denied

### Receipt/history

- Not required for Phase 1
- Phase 2: Member account settings page showing purchase history

---

## Phased Implementation Plan

---

### Phase 1 — Paid pathway checkout (Stripe Checkout)

**Goal:** A member can purchase a paid pathway using a real Stripe payment. Access is granted automatically after payment. Admin can see the transaction.

**Estimated scope:** ~3–4 days of backend + frontend work.

#### Phase 1 tasks

**A. Backend setup**
1. Add `stripe>=10.0.0` to `requirements.txt`
2. Add Stripe env vars to `app/core/config.py` and `.env.example`:
   - `STRIPE_SECRET_KEY`
   - `STRIPE_WEBHOOK_SECRET`
   - `STRIPE_PUBLISHABLE_KEY` (for frontend)
3. Add `idempotency_key: str | None` field to `PaymentTransaction` (new migration 039)

**B. Backend — checkout session endpoint**

New file: `app/checkout/routes.py`  
New endpoint: `POST /api/checkout/pathway`  
- Requires `get_current_user`
- Validates pathway exists, is one_time, has price
- Checks for existing active entitlement → 409
- Gets creator's current plan fee rate
- Creates `PaymentTransaction(status='pending', provider='stripe')`
- Creates Stripe Checkout Session with metadata
- Stores session ID on transaction
- Returns `{"checkout_url": session.url}`

**C. Backend — webhook handler**

New file: `app/webhooks/routes.py`  
New endpoint: `POST /api/webhooks/stripe` (no auth, verify with `stripe.Webhook.construct_event`)  
- Handle `checkout.session.completed`:
  - Find pending transaction by session metadata `transaction_id`
  - Idempotency check: skip if `status='succeeded'`
  - Retrieve charge → populate `processing_fee_cents`
  - Update transaction to `succeeded` with all provider IDs
  - Create/reactivate `PathwayEntitlement(source='one_time_purchase', status='active')`
  - Link `txn.entitlement_id`
- Handle `payment_intent.payment_failed`:
  - Update transaction to `failed`
- Handle `checkout.session.expired`:
  - Update transaction to `cancelled`

**D. Frontend — wire checkout page**

File: `src/app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx`  
- Add `POST /api/checkout/pathway` call on "Unlock pathway" button click
- Handle loading state during redirect
- Add `?success=true` detection → show success state + fetch updated pathway data
- Add `?cancelled=true` detection → show cancelled state
- Install `@stripe/stripe-js` (optional for Phase 1 — only needed for Stripe Elements, not Checkout redirect)

**E. Backend — new router registration**

File: `app/main.py`  
- Register `app/checkout/routes.py` under `/api/checkout`
- Register `app/webhooks/routes.py` under `/api/webhooks`

**F. Pending transaction cleanup**

- Add logic to cleanup stale pending transactions (sessions expire after 24h by default in Stripe)
- Can be done on checkout page load: if pending transaction for this user+pathway is >2 hours old → mark cancelled (via an endpoint or the checkout page's fetch)

**G. Admin payout management (small addition)**

File: `src/app/admin/payments/page.tsx` + `app/admin/routes.py`  
- Add `PATCH /api/admin/payments/{txn_id}/payout` endpoint → mark as `paid` with reference
- Add "Mark paid" button per row in admin payments table (or bulk action)

**H. Test end-to-end**

- Use Stripe test mode (`sk_test_...`)
- Stripe CLI for local webhook delivery: `stripe listen --forward-to localhost:8000/api/webhooks/stripe`
- Test card: `4242 4242 4242 4242`
- Test all flows: success, cancel, failed card, duplicate webhook

---

### Phase 2 — Creator payout readiness

**Goal:** Creators can see their earnings. Admin can track and mark payouts as paid. Optional: Stripe Connect onboarding.

#### Phase 2 tasks

1. Admin payout management UI (mark transactions as paid, bulk payout, payout reference)
2. Creator Studio earnings page (total earned, pending payout, sales list)
3. Migration: `creator_stripe_accounts` table
4. Creator Stripe Connect onboarding endpoint (`GET /api/creator/stripe/onboarding-link`)
5. Webhook: `account.updated` → update `CreatorStripeAccount.charges_enabled`, `payouts_enabled`
6. Stripe Connect automatic transfers (application fee amount on checkout session)

**Note:** For Phase 2, the admin manual payout flow (mark as paid) must be kept even after Stripe Connect is live, for creators who haven't yet connected.

---

### Phase 3 — Creator subscription billing

**Goal:** Creators pay their monthly plan fee via Stripe. Failed billing suspends their account.

#### Phase 3 tasks

1. Create `stripe_customer_id` on `User` or `CreatorSubscription` (already has the field)
2. Creator subscription checkout endpoint (`POST /api/creator/subscribe`)
3. Stripe Customer and Subscription creation
4. Webhook: `invoice.payment_succeeded` → create `PaymentTransaction(type='creator_subscription_payment')`
5. Webhook: `invoice.payment_failed` → `CreatorSubscription.status='past_due'`
6. Webhook: `customer.subscription.deleted` → `status='cancelled'`, make spaces read-only
7. Creator Studio: billing status, next payment date, upgrade/downgrade

---

### Phase 4 — Bundles and paid bookings

**Goal:** Allow selling multiple pathways together and charging for event bookings.

#### Phase 4 tasks

1. `Offer` and `OfferItem` models + migration
2. Admin: create/manage offers
3. Checkout endpoint supports `offer_id` alongside `pathway_id`
4. Webhook creates multiple `PathwayEntitlement` records
5. Event model: add `booking_price_cents` field
6. `PaymentTransaction`: add `booking_id` FK
7. Booking checkout endpoint + webhook handler
8. Post-payment booking confirmation

---

## Decisions needed from Lindsey

Before Phase 1 implementation begins, please confirm:

1. **Who absorbs Stripe processing fees?**  
   Option A: Fresh Collective absorbs (creators see clean gross - fee %). Simpler, better creator experience.  
   Option B: Stripe fee passed to creator (more transparent at expense of complexity).  
   *Recommendation: Option A for now.*

2. **Does a full refund always revoke pathway access?**  
   Option A: Yes — member is refunded and loses access.  
   Option B: No — discretionary (admin can choose to refund and retain access).  
   *Recommendation: Option A as default, admin can manually re-grant if needed.*

3. **Stripe Connect timing**  
   Phase 1 has no Connect (FC collects all, pays creators manually). Is this acceptable for initial launch?  
   *Recommendation: Yes — Phase 2 is the right time for Connect.*

4. **Success/cancel URL structure**  
   The Stripe redirect goes back to the checkout page with query params. Is `/spaces/{slug}/pathways/{pathway-slug}/checkout?success=true` acceptable, or do you want a dedicated `/checkout/success` page?  
   *Recommendation: Stay on checkout page with state params — less URL surface area.*

5. **Stripe test data**  
   Existing manual transactions should be kept for admin testing. Any objection to having a mix of `provider='manual'` (test) and `provider='stripe'` (real) in the same payments table?  
   *Recommendation: No — this is already the design. The `Manual` badge in the admin table clearly distinguishes them.*

6. **Australia-only Stripe account initially?**  
   All amounts are AUD. Stripe account should be registered in Australia for Stripe Australia pricing (1.75% + 30c domestic).  
   Confirm: single-currency AUD for Phase 1?  
   *Recommendation: Yes.*

7. **Pathway subscription pathways (recurring)**  
   Some pathways have `access_type='subscription'`. Phase 1 will only wire `one_time` purchases to Stripe. Should subscription pathways show as "coming soon" on checkout until Phase 3?  
   *Recommendation: Yes — show "Subscription billing coming soon" on checkout for subscription pathways.*

8. **Creator plan fee rate with no active subscription**  
   If a creator has no active `CreatorSubscription` (e.g., trial, cancelled), what fee rate applies?  
   Option A: Default to Basic rate (8%)  
   Option B: Block pathway sales until creator has an active plan  
   *Recommendation: Option A for Phase 1 — treat as Basic if no plan found.*

---

## Files involved in Phase 1

### Backend — new files

| File | Purpose |
|------|---------|
| `app/checkout/__init__.py` | |
| `app/checkout/routes.py` | Checkout session creation endpoint |
| `app/checkout/schemas.py` | Request/response schemas |
| `app/webhooks/__init__.py` | |
| `app/webhooks/routes.py` | Stripe webhook handler |
| `alembic/versions/039_add_idempotency_key_to_payment_transactions.py` | DB migration |

### Backend — modified files

| File | Change |
|------|--------|
| `app/core/config.py` | Add Stripe env vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` |
| `.env.example` | Add Stripe var names (values blank) |
| `requirements.txt` | Add `stripe>=10.0.0` |
| `app/main.py` | Register checkout + webhook routers |
| `app/admin/routes.py` | Add `PATCH /api/admin/payments/{txn_id}/payout` endpoint |
| `app/admin/schemas.py` | Add payout update schema |

### Frontend — modified files

| File | Change |
|------|---------|
| `src/app/spaces/[slug]/pathways/[pathway-slug]/checkout/page.tsx` | Wire "Unlock pathway" CTA, handle success/cancel states |
| `src/app/admin/payments/page.tsx` | Add "Mark paid" button (optional Phase 1 addition) |

### Frontend — new files

| File | Purpose |
|------|---------|
| `src/lib/checkout.ts` | `createPathwayCheckoutSession()` helper |

### Stripe Dashboard (manual steps)

1. Create Stripe account (Australia)
2. Register webhook endpoint: `https://app.freshcollective.com/api/webhooks/stripe`
3. Subscribe to events: `checkout.session.completed`, `payment_intent.payment_failed`, `checkout.session.expired`, `charge.refunded`, `charge.dispute.created`
4. Copy webhook secret to `STRIPE_WEBHOOK_SECRET`
5. Test with Stripe CLI locally before deploying

---

*End of spec. No code was changed during this audit.*
