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

import type { ConnectRoutingReadyCreator } from '@/lib/serverApi'

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
