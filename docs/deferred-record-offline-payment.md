# Deferred: Record offline payment

**Status:** deferred. Do not build until the requirements below are all in place.

## Background

Stage 3 of the World Management redesign replaced the old **Manual purchase**
action (which secretly fabricated a `PaymentTransaction` alongside an
entitlement) with a **Grant access** action that creates a `PathwayEntitlement`
only. See `backend/app/admin/routes.py::grant_pathway_access` and
`docs/stripe-implementation-plan.md`.

That replacement is Option **C** from the audit — the safe, immediate move. The
audit also identified Option **D**: split the operation into two explicit
actions, adding a real **Record offline payment** action alongside Grant access.

This document captures the requirements Option **D** must satisfy so we don't
lose the context when the time comes.

## When to build

All of the following must be true before we should introduce
`Record offline payment`:

1. Real off-Stripe cash actually flows into or out of the platform
   (invoiced sales, bank transfers, workshop cash, etc.) — i.e. there is a
   genuine reason to record a payment for which no Stripe webhook exists.
2. Stripe Connect (or equivalent) is live, so any transaction recorded as
   money owed to a creator can actually be paid out.
3. The financial team has a documented reconciliation process for offline
   payments against bank statements.

Before those exist, "Record offline payment" is a foot-gun: it would create
real payout obligations against no cash.

## Required fields on the action

Every field is required unless marked optional. Do not accept an "amount only"
form — that was the old bug.

- `member_user_id` — who paid
- `pathway_id` or `space_id` — what they paid for
- `amount_cents` — real gross amount
- `currency` — ISO 4217 uppercase (whitelist enforced at the API layer)
- `payment_method` — enum: `bank_transfer | cheque | cash | other`
- `reference` — external identifier (bank txn ID, cheque number,
  invoice number, receipt number). Required so payments can be reconciled.
- `payment_date` — the day the money actually moved (may differ from
  `created_at`)
- `reason` — enum: `invoiced_sale | offline_workshop | correction | other`.
  `other` requires a note.
- `note` — freeform, always accepted; required when `reason == 'other'`

## Required backend behaviour

1. Creates a `PaymentTransaction` with `payment_provider='manual'` and
   **`stripe_mode='live'`** when the platform is in live mode. The old
   default of `stripe_mode='test'` silently excluded manual transactions
   from live reports and must not repeat here.
2. Sets `platform_fee_basis_points` from the creator's active plan, mirroring
   Stripe-processed purchases. Fees are real revenue, not virtual.
3. Records `created_by_admin_id` on the transaction. **This requires a schema
   addition** — the current `PaymentTransaction` model does not carry the
   admin identity (only the entitlement does).
4. Optionally creates or reactivates a `PathwayEntitlement` in the same call
   if the payment corresponds to a purchase equivalent.
5. Sets `payout_status=pending` for creator-owed money and enters the same
   payout workflow as Stripe purchases. Do not add "Record offline payment"
   until that workflow exists.
6. Emits a creator notification: "Fresh Collective recorded an offline payment
   for {pathway} from {member}. Amount: {amount}. Reason: {reason}."
7. Rejects requests where the platform is in `stripe_mode='test'` unless the
   caller explicitly opts into a `test` mode payment — production off-Stripe
   money must never appear as test data.

## Audit trail requirements

At minimum:

- `PaymentTransaction.created_by_admin_id` (new column, backed by
  the users table)
- `PaymentTransaction.payment_method` (new column, enum)
- `PaymentTransaction.reference` (new column, string)
- `PaymentTransaction.reason` (new column, enum) — separate from the free-form
  `notes` field
- A structured record joining the transaction to its resulting entitlement
  (already possible via `entitlement_id`)

Free-form `notes` is not sufficient audit data on its own — same lesson as the
Grant access refactor.

## Migration notes

- Schema migration adds four columns to `payment_transactions`
- Backfill is unnecessary — the columns can be nullable for pre-existing rows
- CHECK constraints should enforce the enum values at the DB layer

## UI location

The action belongs alongside "Grant access" on the Transactions page — a
sibling primary action, not a replacement. Behaviours must be visually
distinct:

- **Grant access** stays teal (positive/active).
- **Record offline payment** should read as coral-adjacent or gold — it is
  higher-consequence than a grant, and touches real revenue.

## Cross-reference

- Migration `081_pathway_entitlement_grant_reason.py`
- Endpoint `POST /api/admin/entitlements/grant` (Grant access — Stage 3)
- Original audit conversation: Stage 3 of the World Management redesign.

## Do not build "Record offline payment" simply because someone asks for
"a way to add a purchase manually." That request often turns out to mean
Grant access. Check the requirements above first.
