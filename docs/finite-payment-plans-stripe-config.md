## Finite Payment Plans — Stripe configuration + deployment requirements (FIP3)

**Date:** 2026-08-16
**Status:** Configuration + deployment requirement document; no
code change lives here.
**Companions:** [`finite-payment-plans-lifecycle.md`](./finite-payment-plans-lifecycle.md),
[`finite-instalment-audit.md`](./finite-instalment-audit.md).

FIP3 introduces a 7-day member-facing grace window after a failed
later instalment. This document records the Stripe Dashboard
settings and deployment/scheduler requirements that make the grace
window enforceable end-to-end. **No live-mode Dashboard change may
be made without prior operator sign-off.**

---

### 1. Product rule (locked)

On the first ``invoice.payment_failed`` for a later instalment on a
finite ``PurchasePlan``:

- transition ``active → payment_problem``
- ``grace_expires_at = payment_problem_started_at + 7 days``
- **member's access remains live for those 7 days**
- if any subsequent invoice on the plan succeeds within that
  window (Smart Retries or a new invoice attempt), plan returns
  to ``active`` (or ``completed`` if final)
- if the window expires without recovery, the reconciler suspends
  the plan and its plan-owned access (source-aware)

Fresh Collective's grace window is our own product commitment. It
is NOT expressed in Stripe. Stripe manages the underlying retry
schedule + terminal cancellation independently.

---

### 2. Required Stripe subscription retry configuration

Stripe's current subscription-level retry behaviour is governed
by two Dashboard settings:

1. **Smart Retries** — the retry schedule Stripe uses when an
   invoice payment fails.
2. **What happens after all retries have been exhausted** — one
   of the three current Stripe options at the subscription level:
   - **Cancel the subscription**
   - **Mark the subscription as unpaid**
   - **Leave the subscription past due**

**Required setting for finite payment plans:** the after-retries
action MUST be **"Leave the subscription past due"**.

**Why not "Cancel the subscription":** cancelling fires
``customer.subscription.deleted`` mid-grace. The FIP3 hardened
reconciler then pulls Stripe's invoice inventory, sees the
outstanding invoice terminally dead, and transitions the plan to
``failed`` — before our 7-day grace has run. That defeats the
product promise.

**Why not "Mark the subscription as unpaid":** ``unpaid`` halts
further billing attempts. Any subsequent operator- or member-
driven successful payment on the still-outstanding invoice will
still fire ``invoice.payment_succeeded`` and drive our
``suspended → active`` / ``suspended → completed`` reinstatement
path, but Stripe itself will make no further automatic retries.
For v1 we deliberately keep Stripe retrying so a member whose
card recovers within the 2-week retry horizon needs no manual
intervention.

**Why "Leave the subscription past due":** Stripe automatically
retries the failed invoice according to the configured Smart
Retry schedule. When those scheduled attempts are exhausted,
**automatic retries stop** — the subscription does not keep
retrying indefinitely. Leaving the subscription ``past_due``
keeps it non-terminal and recoverable: an operator retry, a
member-driven card update + repayment, or any other subsequent
successful payment on the same overdue invoice still fires
``invoice.payment_succeeded``. Fresh Collective's FIP3 handler
reacts to that success and drives ``suspended → active`` (or
``suspended → completed``) via the recovery path. The critical
property is that the subscription never enters a *terminal*
state on its own — automatic cancellation is what we're
avoiding, not the finite retry horizon itself.

#### Recommended v1 configuration

| Setting | Value | Where |
|---|---|---|
| Smart Retries — retry horizon | **2 weeks** | Dashboard → Settings → Billing → Subscriptions and emails → Manage failed payments → Smart Retries |
| After retries exhausted | **Leave the subscription past due** | Same panel |
| Applies to | **Test AND Live modes** | Both mode-scoped panels |

The 2-week Smart Retry window is deliberately **longer** than
Fresh Collective's 7-day grace so recovery inside the second week
(after our grace has already expired and we've suspended access)
can still lift ``suspended → active`` via our idempotent
recovery path. If the account's current setting is already
different from 2 weeks (e.g., 4 weeks), leave it alone unless
there's a concrete reason to shorten — longer horizons only
give Stripe more chances to recover money and never destabilise
our lifecycle.

#### Timeline

```
Day 0            invoice.payment_failed
                 FC:  active → payment_problem
                 access remains
                 Stripe: past_due (Smart Retries running)

Day 7            FC grace expires (in-process reconciler / cron)
                 FC:  payment_problem → suspended
                 plan-owned access suspended
                 Stripe: still past_due, still retrying

Day 7 – 14       Stripe retry succeeds (member card recovers,
                 or operator repairs and pays overdue invoice)
                 invoice.payment_succeeded
                 FC:  suspended → active
                 access reinstated (plan-owned rows only,
                 source-aware)

Day 14 (or later
if longer horizon)
                 Stripe's automatic retry schedule is
                 exhausted. NO further automatic retries.
                 Subscription remains past_due (non-
                 terminal — NOT cancelled).
                 FC: no state change from Stripe alone.
                 A subsequent successful payment on the
                 same overdue invoice (operator retry or
                 member-driven repair) still fires
                 invoice.payment_succeeded and drives our
                 reinstatement path.
```

---

### 3. Where the setting lives

Stripe Dashboard → **Settings → Billing → Subscriptions and
emails → Manage failed payments**.

Two independent instances of this setting to check:
- **Test mode** — used by all FIP2/FIP3 developer test scenarios.
- **Live mode** — the production billing account.

Per-subscription overrides (``subscription.pause_collection`` /
``collection_method``) are not used by FIP3 and should not be set
by application code.

---

### 4. Do not change live settings in this pass

This document identifies the required configuration; it does not
apply it. Any Dashboard change to live mode must be:

1. Scheduled with the operator team.
2. Applied outside code deploy time.
3. Verified by inspecting the Dashboard export post-change.

Test mode may be changed by the developer running FIP3 test-clock
scenarios so acceleration works end-to-end. Record any test-mode
change in the FIP3 browser-test log.

---

### 5. Production scheduler requirement

The FIP3 grace-expiry sweep — ``services.finite_plan_lifecycle.sweep_expired_grace_plans``
— is invoked in two ways today:

1. **In-process asyncio loop** (``services.finite_plan_reconciler``),
   started from the FastAPI lifespan hook. Ticks every 5 minutes.
   This is defence-in-depth: it runs on every backend replica,
   the sweep function is idempotent, and running from multiple
   replicas at once is harmless (each plan is row-locked).
2. **Operator script** — ``scripts/fip3_reconcile_grace.py``
   (with a ``--dry-run`` flag). Runnable ad hoc or under an
   external cron.

**Production deployment requirement — before flipping public
member-facing recurring-plan checkout:** a reliable production
schedule for the sweep must exist independent of the API
process. The in-process loop MUST remain as defence-in-depth,
but SHOULD NOT be the sole trigger — a rolling restart or
extended process pause would open a window where an expired
grace plan stays in ``payment_problem`` past its promised 7
days.

Two acceptable options (choice depends on production platform;
build the smallest that fits):

- **Platform cron** (Fly.io Machines cron, systemd timer, or
  equivalent) running ``scripts/fip3_reconcile_grace.py`` every
  15 minutes.
- **External task runner** (e.g. Cloud Scheduler → HTTP endpoint,
  or a dedicated worker process) invoking a callable that calls
  the sweep.

Either option is a small, well-scoped operational task and is
NOT built in this pass. It becomes a blocker at the point of
enabling public recurring-plan checkout (``is_member_checkoutable``).
Until then, the in-process loop is sufficient for FIP3
integration testing and staging validation.

---

### 6. Public checkout gating

Public recurring-plan checkout for members
(``PaymentOptionSchedule.schedule_type='recurring_installments'``)
MUST remain gated until:

1. The production scheduler above is in place.
2. The full FIP3 lifecycle has been exercised end-to-end in
   test mode against a real Stripe SubscriptionSchedule (see
   ``scripts/fip3_test_acceleration.py`` for the scenario
   playbook).
3. The live-mode Dashboard retry configuration has been set to
   ``mark_uncollectible`` (or ``leave_open``) and verified.

Gate lives at ``backend/app/spaces/routes.py::_schedule_is_member_checkoutable``
and the 503 guard in ``backend/app/services/checkout_orchestration.py``.

---

### 6a. Payment-method-repair implications for finite plans

FC's finite `SubscriptionSchedule.create` call establishes a
subscription-level `default_payment_method` via
`default_settings.default_payment_method`. That value takes
precedence over the Customer's
`invoice_settings.default_payment_method` when Stripe collects
the next scheduled invoice.

**Implication for any future member "update my card" repair flow:**
updating only the Customer default (the intuitive one-line
change) will NOT change the PM Stripe uses for the next
subscription invoice. Any FIP4+/repair UI that swaps the member's
card mid-plan must also update:

- `SubscriptionSchedule.default_settings.default_payment_method`
  (Stripe's recommended surface for schedule-backed
  subscriptions — a phase transition can otherwise overwrite
  direct subscription changes), AND
- `Subscription.default_payment_method` (belt-and-braces override
  effective immediately for the currently-running phase).

The FIP3 test harness (`scripts/fip3_test_acceleration.py`)
already implements this three-surface swap and asserts the new
PM shows on all three surfaces before advancing time. That
pattern is the reference for a production repair flow.

Do not build repair UI now — this is a documented lesson only.

**Companion UX note (also future FIP4+):** in the FIP3 v1
integration run, a member whose plan is in
`payment_problem` / `suspended` currently falls through to the
standard paywall (e.g. "Unlock for $397 AUD"). This is
acceptable *access-gating* behaviour — the suspended
entitlement correctly blocks pathway content — but the surface
copy is wrong for the situation. A real recovery UX should
distinguish "you're behind on payment — repair your card" from
"you don't own this yet — buy it". Track alongside the PM
repair flow above; both land together in a future milestone.

### 7. Successful-invoice event choice

Fresh Collective processes ``invoice.payment_succeeded`` only.
``invoice.paid`` is deliberately NOT wired; both events fire for
the same successful automatic payment and processing both would
duplicate transitions. Natural invoice-id idempotency
(``ux_payment_transactions_provider_invoice_id`` + the
``webhook_events`` durable lease) provides the safety net.

Out-of-band paid invoices (e.g. an operator marking an invoice
paid in Dashboard) fire ``invoice.paid`` without
``invoice.payment_succeeded``. For finite payment plans this is
not a supported operator action — the plan's invoices are paid
automatically via the SubscriptionSchedule + saved payment
method. If we ever need to support manual out-of-band payment,
adding an ``invoice.paid`` handler is straightforward, but until
then leaving it unhandled prevents double-processing.
