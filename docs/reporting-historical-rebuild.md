# Historical rebuild — what can honestly be reconstructed

The nightly job (`fc-reporting-nightly`) rebuilds a three-day window.
That keeps the recent past correct as late refunds and backfilled Stripe
fees arrive, but it means the historical charts on Growth and Money only
reach back as far as the stored aggregates go.

Extending that reach is a **bounded, one-off rebuild over an explicit
date range**. This document records which metrics such a rebuild can
reconstruct accurately, which it must not touch, and why nobody needs to
carve the second group out by hand.

## The three groups

Derived from the registry rather than kept by hand — regenerate with:

```bash
cd /home/lindsey/fc-merge/backend
.venv/bin/python -c "
import app.reporting.metrics, app.reporting.engagement
from app.reporting.registry import REGISTRY
from app.reporting.aggregates import store_eligible
for m in REGISTRY.all():
    kind = ('not stored' if not store_eligible(m)
            else 'observation-only' if m.observation_only else 'rebuildable')
    print(f'{kind:17} {m.key}')
"
```

**Rebuildable (21).** Reconstructed from rows that carry their own
dates, so a past day can be worked out today and the answer is the same
answer the day itself would have given.

- Membership: `unique_members`, `total_memberships`, `memberships_started`,
  `multi_collective_members`, `members_in_one_collective`,
  `members_in_two_collectives`, `members_in_three_plus_collectives` —
  all from `space_memberships.joined_at` / `removed_at`.
- Accounts: `registered_users`, `registered_creators` — from
  `users.created_at`.
- Money: `gross_collective_sales_cents`, `platform_fee_revenue_cents`,
  `creator_earnings_cents`, `processing_costs_cents`,
  `subscription_revenue_cents`, `refunds_cents`, `paid_out_cents`,
  `outstanding_payouts_cents`, `contribution_after_processing_cents` —
  each on its own date basis, from `app.reporting.dates`.
- Engagement: `participation_acts`, `pathway_steps_completed`,
  `gathering_attendance`.

**Observation-only (4).** `total_collectives`, `active_collectives`,
`draft_collectives`, `archived_collectives`. `spaces.status` holds one
value with no history behind it, so there is no honest past figure —
only the one recorded on the day.

These need no special handling and must not be excluded by a flag.
`_observation_quality` returns unavailable for any past day, so
`rebuild_day` records a skip rather than a value, and the upsert for an
`observation_only` metric is `ON CONFLICT DO NOTHING`, so a genuine
observation already on record is never replaced. **A historical rebuild
is therefore safe to run across every metric**: the ones that cannot be
reconstructed decline on their own.

**Never stored daily (8).** Distinct counts and ratios —
`active_members`, `active_creators`, `returning_participants`,
`participation_rate`, `memberships_per_member`, `retention_cohorts`,
`engagement_by_theme`, `overlap_vs_engagement`. Thirty daily unique
counts do not make a monthly one, so these are recomputed over whatever
window is asked for and never written to `metric_daily`.

## The one hazard already closed

`outstanding_payouts_cents` is a liability *at a moment*. Asked with a
window it reconstructs the balance as at the window's end; asked without
one it reads `payout_status` directly. Before that distinction existed
the nightly job stored today's balance under every reporting date and
the trend line was flat at the current value — a liability dated before
the sale that created it. The two modes are why it is in the
rebuildable group rather than the observation-only one.

## Running it

`scripts/reporting/rebuild_daily.py` already takes an explicit range, so
no new script is needed.

```bash
# What it would do. Writes nothing.
python scripts/reporting/rebuild_daily.py --from 2026-07-01 --to 2026-10-30 --dry-run

# The rebuild itself.
python scripts/reporting/rebuild_daily.py --from 2026-07-01 --to 2026-10-30
```

Properties worth knowing before running it:

- **Idempotent.** Every write is an upsert on
  `(metric_key, reporting_date, dimension)`. Running it twice over the
  same range recomputes and overwrites rather than duplicating.
- **Resumable.** Each day commits on its own, so a failure part-way
  keeps the days already done; re-run the same range.
- **Recorded.** It opens a `reporting_job_runs` row and closes it
  `succeeded` or `failed`, which Data Health reports either way.
- **Financially inert.** It reads `payment_transactions` and writes only
  `metric_daily`. No payment, payout, refund or classification is
  touched.

### Choosing the range

Start at the beginning of the current financial year (1 July) rather
than at the first row in the database. It covers everything the Money
page's "This financial year" range can ask for, it is a boundary the
business already reports on, and it keeps one run to roughly four
months of days rather than years of them.

Reach further back only when somebody actually asks for a longer
history, and expect the earliest months to carry `reconstructed`
provenance: before business-event recording began, a membership removed
without a stored removal date is invisible, so the member counts for
those dates are an upper bound. The charts disclose this per point
rather than leaving it to be discovered.

### Afterwards

`all_time` on the charts is floored at the oldest stored
`reporting_date`, so the range extends on its own once the rebuild
lands — there is nothing to configure.
