# Stripe Connect — going live

What has to be true before Fresh Collective routes a real creator's sales
through Stripe Connect, and how the two background jobs that keep the money
straight are run.

Scope note: nothing in this document has been deployed. The Render job blocks
in §2 are written out ready to paste into `render.yaml`, deliberately **not**
added to it — a Blueprint sync creates and starts what it declares, and no
creator is enabled for Connect routing yet. Add them in the same change that
turns the first creator on, not before.

Background on the design decisions behind all of this:
`docs/stripe-implementation-plan.md`.


## 1. How the money actually moves

Worth having in mind before reading the rest, because both jobs exist because
of it.

Fresh Collective uses **separate charges and transfers**, not destination
charges. The member's payment lands in FC's own Stripe balance; a second call
transfers the creator's share to their connected account. The order is forced:
the creator's share is `net_creator_amount_cents − processing_fee_cents`, and
the processing fee is only knowable once the charge's balance transaction
exists — which is after the charge, not during it.

So each Connect sale has two separate moments, and either can be late:

1. **The charge succeeds.** Fulfilment happens here. The member has their
   purchase and their access, unconditionally — a transfer problem never
   revokes it.
2. **The transfer sends.** Attempted inline off the payment webhook. When that
   does not land, the row stays `pending` and the transfer sweeper (§2.1)
   retries it.

A refund runs the same shape backwards: the member is refunded immediately and
unconditionally, and the creator's share is recovered by reversing the
transfer. When the reversal cannot complete — almost always because the
creator's Stripe balance is empty — the row carries an outstanding amount and
the recovery sweeper (§2.2) keeps trying. Nothing is ever written off by a job.


## 2. Render jobs

Both jobs are `rootDir: backend`, `runtime: python`, `region: singapore`,
matching the existing crons. Both take `--dry-run` and `--limit N`; the
scheduled form takes neither.

Least-privilege env for both:

| Var | Value | Why |
|---|---|---|
| `FC_SERVICE_ROLE` | `job` | Skips the web-role `JWT_SECRET` and R2 validators. Neither job signs a token or touches uploads. |
| `APP_ENV` | `production` | Required for the live Stripe key to pass the "no `sk_live` outside production" guard. |
| `DATABASE_URL` | from `fc-db` | Same database as `fc-api`. |
| `STRIPE_SECRET_KEY` | `sync: false` | Both jobs call Stripe. `FC_JOB_REQUIRES_STRIPE` is left at its default `true` on purpose, so a missing key fails at boot instead of halfway through a pass. |

Deliberately **not** granted to either: `JWT_SECRET`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_V2_WEBHOOK_SECRET` (neither job consumes webhooks), any `R2_*`,
`RESEND_*`, `INTERNAL_BFF_SECRET`, `INTERNAL_COMMS_SECRET`.

### 2.1 `fc-connect-transfer-sweeper`

Sends the creator shares that are owed and still unsent.

```yaml
  # Connect transfer sweeper — sends the creator shares that are owed and
  # still unsent. The inline attempt off the payment webhook is the normal
  # path; this is the retry net for it. Every 15 minutes, matching the other
  # crons: the sweep selects on state, not on a time window, so a late run
  # catches everything correctly.
  #
  # The usual reason a transfer is waiting is not an outage — a transfer
  # against a charge that has not settled is refused for insufficient
  # balance, and the identical call succeeds shortly after. Those rows stay
  # pending and are retried, never written off.
  - type: cron
    name: fc-connect-transfer-sweeper
    runtime: python
    region: singapore
    branch: main
    rootDir: backend
    schedule: "*/15 * * * *"
    buildCommand: pip install -r requirements.txt
    startCommand: python scripts/fc_connect_transfer_sweeper.py
    envVars:
      - key: FC_SERVICE_ROLE
        value: "job"
      - key: APP_ENV
        value: production
      - key: DATABASE_URL
        fromDatabase:
          name: fc-db
          property: connectionString
      - key: STRIPE_SECRET_KEY
        sync: false
```

**What it picks up.** `payout_model = 'connect'`,
`connect_transfer_status = 'pending'`, no `provider_transfer_id` yet.

**What it never touches.** `awaiting_payment` rows (a transfer applies but is
not due — an abandoned Checkout Session lives there forever), `manual` rows
(paid by the existing payout batches), rows that already carry a
`provider_transfer_id`, and rows held by an open dispute.

**Overlap safety.** Safe to run concurrently with itself and with the inline
webhook attempt, by three independent guards: the row is taken
`SELECT … FOR UPDATE` before the amount is computed, the Stripe call carries
the deterministic idempotency key `txn:{id}:transfer:v1`, and a partial unique
index on `provider_transfer_id` rejects a second transfer row at the database.
A sweep is also bounded (`--limit`, default 50), so a backlog is worked down
over several passes rather than in one long-running pass.

**Normal output.** One line per pass:

```
sweep complete: {'considered': 3, 'sent': 3, 'still_pending': 0, 'failed': 0,
 'skipped': 0, 'fee_resolved': 0, 'needs_attention': 0, 'held_by_dispute': 0}
```

A quiet pass logs `considered: 0` and nothing else. That is the expected
steady state — it means every transfer landed inline off its webhook.
`still_pending` above zero is also normal and not an error: those are charges
that have not settled yet. `fee_resolved` counts rows whose processing fee was
missing and has now been read from Stripe.

**Alert-worthy output.**

- `ERROR … still owed after repeated attempts: <txn ids>` — a row has passed
  6 attempts (`connect_transfers.ATTENTION_ATTEMPTS`). It is still queued and
  still being retried; it wants a person to find out why. This is the one line
  to alert on.
- `ERROR … connect transfer sweep failed` plus a traceback, exit code 1 — the
  pass aborted. Money is not lost; the next pass retries.
- `failed` above zero — a genuinely terminal condition (rejected account,
  closed account, unsupported currency). Needs a decision, not a retry.

**Reading the queue without moving money:**

```
cd /home/lindsey/fc-production/backend
.venv/bin/python scripts/fc_connect_transfer_sweeper.py --dry-run
```

On Render, the same thing from the `fc-connect-transfer-sweeper` shell is
`python scripts/fc_connect_transfer_sweeper.py --dry-run` (no `.venv/bin`
prefix — Render's Python buildpack installs to the system environment).

### 2.2 `fc-connect-recovery-sweeper`

Gets back the creator share of a refund or dispute when the transfer reversal
did not complete at the time.

```yaml
  # Connect recovery sweeper — the counterpart to the transfer sweeper. That
  # one sends money FC owes a creator; this one recovers money a creator owes
  # FC after a refund or dispute, where the reversal could not complete.
  #
  # Every 15 minutes, which is also the first retry cooldown. Pacing is the
  # sweep's own, not the schedule's: attempts back off exponentially from 15
  # minutes to a day, because the usual cause is an empty creator balance and
  # that does not change minute to minute. Rows inside their cooldown are
  # counted and skipped, so a frequent schedule costs nothing.
  #
  # All reversal arithmetic stays in the reversal service: the cumulative
  # target is recomputed under a row lock from stored refund and dispute
  # state, and only the remaining delta is reversed.
  - type: cron
    name: fc-connect-recovery-sweeper
    runtime: python
    region: singapore
    branch: main
    rootDir: backend
    schedule: "*/15 * * * *"
    buildCommand: pip install -r requirements.txt
    startCommand: python scripts/fc_connect_recovery_sweeper.py
    envVars:
      - key: FC_SERVICE_ROLE
        value: "job"
      - key: APP_ENV
        value: production
      - key: DATABASE_URL
        fromDatabase:
          name: fc-db
          property: connectionString
      - key: STRIPE_SECRET_KEY
        sync: false
```

**What it picks up.** `payout_model = 'connect'`, a transfer that was actually
sent, `connect_recovery_state = 'required'`, and
`connect_unrecovered_amount_cents` still above zero — oldest attempt first.

**What it never touches.** `manual` rows, and the member's refund. A recovery
failure never undoes a completed customer refund; that money has left and
stays gone.

**Overlap safety.** Same three guards, reversal-side: the row is locked before
the remaining delta is computed, the Stripe call carries
`reversal_idempotency_key(txn_id, target)` — keyed on the cumulative target, so
a re-delivered refund webhook and a sweep racing each other cannot
over-reverse — and the cooldown gate is evaluated under the same lock.

**Normal output.**

```
sweep complete: {'attempted': 1, 'reversed': 1, 'still_retryable': 0,
 'recovery_required': 0, 'skipped': 0, 'cooling_off': 2, 'needs_attention': 0,
 'outstanding_cents': 0}
```

`cooling_off` above zero is the healthy state for a row waiting on a creator
balance. `outstanding_cents` is what is still owed back to FC across the rows
this pass considered.

**Alert-worthy output.**

- `ERROR … still owed after repeated attempts: <txn ids>` — past 5 attempts
  (`connect_recovery_sweeper.ATTENTION_ATTEMPTS`). Still queued, still
  retried, wants a person. Alert on this.
- `ERROR … connect recovery sweep failed`, exit 1 — pass aborted; next pass
  retries.
- `outstanding_cents` climbing across passes without `reversed` moving — the
  creator's balance is not covering it and the recovery is becoming a
  conversation rather than a retry.

**Reading the queue, including when each row is next due:**

```
python scripts/fc_connect_recovery_sweeper.py --dry-run
```

### 2.3 What these jobs are not

Neither job enables anything. `connect_payouts_enabled_at` has exactly one
writer in the codebase — `app/services/connect_routing_enablement.py`, reached
only from the admin route — and a test asserts that stays true. No webhook, no
sweep and no onboarding completion can switch a creator's routing on.


## 3. Pre-live verification checklist

Work top to bottom. Everything above the enablement step is reversible;
nothing below it is invisible to a creator.

### Schema and build

- [ ] `alembic upgrade head` applied — migrations **141** (`creator_stripe_accounts`),
      **142** (transaction routing columns), **143** (recovery state),
      **144** (`purchase_plans.payout_model`), **145** (fee acknowledgement).
- [ ] `alembic downgrade` / `upgrade` cycles clean on a scratch database for
      each of the five. (Done pre-merge; re-check only if any were amended.)
- [ ] Every existing `purchase_plans` row is `payout_model = 'manual'`. No
      historical plan silently becomes Connect-routed.
- [ ] Every existing `payment_transactions` row is `payout_model = 'manual'`
      or `not_applicable`. Existing live payments are unchanged.
- [ ] `stripe==15.2.0` in `requirements.txt` and installed. The pin *is* the
      API version — the SDK sends `Stripe-Version: 2026-05-27.dahlia` on every
      request, so bumping the package changes the API version.

### Stripe platform

- [ ] Connect is enabled on the FC platform account, and Accounts v2 with the
      `recipient` configuration is available on it.
- [ ] `fees_collector` and `losses_collector` are `application` on new
      accounts — FC collects the fees and bears the losses.
- [ ] `STRIPE_V2_WEBHOOK_SECRET` set on `fc-api`. It is a **different** secret
      from `STRIPE_WEBHOOK_SECRET`: v1 events and v2 core events arrive on
      separate endpoints with separate signing secrets, and crossing them
      fails signature verification on everything.
- [ ] The v2 event destination exists, created with
      `scripts/create_connect_event_destination.py`. Confirm the URL it
      reports under `--list` is the intended one: the script derives it from
      `PUBLIC_APP_URL` (falling back to `FRONTEND_ORIGIN`), so it is
      `{public FC origin}/api/webhooks/stripe/v2` and reaches `fc-api` through
      the Next.js proxy. That is a different shape from the v1 Stripe webhook,
      which points straight at `{fc-api}/api/webhooks/stripe` — worth checking
      rather than assuming. Stripe returns the signing secret **once at
      creation**: it is printed once, never persisted to source or logs, and
      goes straight into the Render environment.
- [ ] A v2 account event has been delivered and accepted end to end (Stripe
      dashboard shows 2xx; a `stripe_v2` row exists in `webhook_events`).
      Thin-event payloads are never trusted as state — every one triggers a
      fetch of the full account.

### Jobs

- [ ] Both cron blocks from §2 added to `render.yaml` and synced.
- [ ] Each job's first run logs a clean `considered: 0` / `attempted: 0` pass.
- [ ] `--dry-run` has been run against production for both, and both report an
      empty queue.
- [ ] Alerting is set up on `still owed after repeated attempts` from either
      job.

### The first creator, end to end in test mode

Do this whole sequence against a test-mode account before any of it against a
real one.

- [ ] **Onboarding.** Creator completes Stripe-hosted onboarding from Creator
      Studio → Billing. Panel reaches `ready`. Onboarding links are minted
      fresh per click and never persisted.
- [ ] **The panel does not overclaim.** With routing still off, the panel says
      earnings continue through FC's existing payout process. `ready` means
      Stripe *can* pay them; it is not a claim that FC is routing sales.
- [ ] **Fee disclosure.** The creator sees: Stripe's processing fee comes out
      of each sale first, then FC's platform fee, and the remainder is paid to
      them. On a 0% plan they also see that their FC platform fee is 0% and
      Stripe processing fees still apply.
- [ ] **Acknowledgement.** Creator acknowledges. `fee_disclosure_acknowledged_at`
      and `fee_disclosure_version` are both stored. Routing is still off —
      acknowledging is not enabling, and the UI says so.
- [ ] **Enablement.** Admin enables routing via
      `POST /api/admin/creators/{id}/stripe-connect/enable`. It refuses unless
      all five hold: an account row for the current Stripe mode, a Stripe
      account id, `payouts_status = active`, payouts enabled, and the fee
      disclosure acknowledged. Confirm at least one refusal by removing one
      condition, and confirm the refusal names *every* unmet condition rather
      than the first.
- [ ] **A pay-in-full sale.** Member buys. Fulfilment and access are immediate.
      `payout_model = 'connect'`, `payout_status = 'not_applicable'` (the
      manual payout vocabulary does not apply), and
      `transfer_amount_cents = net_creator_amount_cents − processing_fee_cents`.
- [ ] **The transfer.** `connect_transfer_status` reaches `sent` with a
      `provider_transfer_id`, and the amount appears in the connected account's
      Stripe balance. If it is still `pending`, confirm the reason is
      `balance_insufficient` on an unsettled charge and that the next sweep
      sends it.
- [ ] **The earnings UI.** Creator Studio → Billing shows the sale with all
      four lines, and they add up: sale − Stripe fee − FC fee = their share.
      No Stripe account or transfer id, no attempt counts, no raw Stripe
      errors, no outstanding-recovery amount. The summary says *sent to
      Stripe*, never *paid* — a transfer reaches their Stripe balance and
      Stripe pays their bank on its own schedule.
- [ ] **A refund and its reversal.** Refund the sale. The member is refunded
      unconditionally. The creator share is reversed against
      `refunded_creator_amount_cents` scaled onto `transfer_amount_cents` — FC
      absorbs the processing fee on a refund. Re-deliver the refund webhook and
      confirm it does not over-reverse.
- [ ] **A reversal that cannot complete.** With the creator's balance below the
      amount, confirm the row lands in `connect_recovery_state = 'required'`
      with an outstanding amount, that the recovery sweeper reports it and
      backs off, and that nothing writes it off.
- [ ] **An instalment plan.** A finite plan on a Connect-enabled creator
      snapshots `payout_model` and the destination account at plan creation.
      Each paid instalment — and only positive payment success, not schedule or
      invoice creation — routes its own creator share through the same transfer
      service. A failed instalment does not carry a payout status it has not
      earned.

### Then, and only then

- [ ] Enable exactly one real creator, ideally one who can be spoken to
      directly, and watch the first few real sales through both the Stripe
      dashboard and the earnings panel before enabling a second.
