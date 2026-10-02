/**
 * Attention lines for the admin overview's "Today's Focus" panel.
 *
 * Pure, so the copy and the appear/disappear rules are unit-testable under
 * Node's test runner without importing JSX. The panel renders what this
 * returns.
 *
 * Why these items are derived rather than stored
 * ----------------------------------------------
 * Every signal on that panel is computed from current state each time the
 * page is read, and this one follows. That is what satisfies "tell me once
 * per transition, not on every webhook": nothing is ever *emitted*, so
 * there is nothing to emit twice. The line exists exactly while the
 * condition holds — it appears when a creator becomes ready and disappears
 * the moment routing is enabled or readiness lapses, with no dedup key, no
 * resolve step and no row that can be left stale after the world moved on.
 *
 * The cost of that choice is that these items cannot be dismissed,
 * snoozed, assigned or audited, and no email goes out. Any of those would
 * need a persisted admin queue, which the product does not have.
 */

import type {
  ConnectRecoveryOutstanding,
  ConnectRoutingReadyCreator,
} from '@/lib/serverApi'

export type AttentionSeverity = 'routine' | 'critical'

export interface AttentionItem {
  label: string
  href: string
  severity: AttentionSeverity
}

/**
 * One line per creator waiting on the Connect routing decision.
 *
 * Per creator rather than a count, because the useful thing is the link:
 * the decision is made on that creator's own page, where the readiness is
 * re-fetched and the guard enforced. A line saying "3 creators are ready"
 * would make an admin go looking for which.
 *
 * ``routine``, not ``critical``. Nothing is broken and no money is stuck —
 * the creator's earnings continue to reach them through the manual payout
 * process meanwhile. Colouring this like a payment failure would teach an
 * admin to discount the colour.
 */
export function connectRoutingItems(
  ready: ConnectRoutingReadyCreator[] | undefined,
): AttentionItem[] {
  return (ready ?? []).map((creator) => ({
    label: `${creator.name} is ready for Stripe Connect routing.`,
    href: `/admin/creators/${creator.user_id}`,
    severity: 'routine' as const,
  }))
}

/** "$1.51" — cents in the row's own currency, never summed across them. */
function formatMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: currency || 'AUD',
    minimumFractionDigits: 2,
  }).format(cents / 100)
}

/**
 * Money Fresh Collective is owed back by a creator.
 *
 * A creator may refund their own sale after the Connect transfer has
 * gone out. The member's refund commits first and is never contingent
 * on recovery, so when Stripe cannot take the creator's share back the
 * shortfall is recorded against the row. Until this item existed that
 * fact lived only in a log line and a sweeper report.
 *
 * The wording has three jobs and the order matters. It must say Fresh
 * Collective is owed money, by whom, and — before anything else can be
 * misread — that the member *was* refunded. An operator skimming a
 * panel of alerts should not come away thinking a customer is out of
 * pocket; nobody is, and treating it as a failed refund would send them
 * looking in the wrong place entirely.
 *
 * ``critical``: this is real money outstanding, not a prompt. It sits
 * with payment failures rather than with the routine items.
 */
export function connectRecoveryItems(
  outstanding: ConnectRecoveryOutstanding[] | undefined,
): AttentionItem[] {
  return (outstanding ?? []).map((row) => {
    const amount = formatMoney(row.outstanding_cents, row.currency)
    const scope = row.transaction_count === 1
      ? 'a refunded sale'
      : `${row.transaction_count} refunded sales`
    return {
      label:
        `${row.creator_name} owes Fresh Collective ${amount} — the member ` +
        `was refunded, but Stripe could not take the creator’s share back ` +
        `from ${scope}.`,
      // Straight to the payment when there is only one; otherwise the
      // payments list, which is where the context lives.
      href: row.sample_transaction_id
        ? `/admin/payments?txn=${row.sample_transaction_id}`
        : '/admin/payments',
      severity: 'critical' as const,
    }
  })
}
