/**
 * What a payment plan can still collect — as distinct from what it
 * never collected.
 *
 * Creator Studio showed one "Remaining" figure for every plan, derived
 * the same way throughout: ``total - paid``. For a live plan that is
 * the outstanding obligation and exactly right. For a plan that had
 * been cancelled and refunded it read "Remaining A$5" beside the word
 * "Cancelled", which says the member still owes money. They do not —
 * cancelling the plan cancels the Stripe schedule, so there is nothing
 * left to collect and nothing left to chase.
 *
 * Both figures are real and worth keeping: the agreement was for A$10
 * and A$5 of it was never paid. What was wrong was presenting the
 * second as a debt. So nothing here recalculates money — the arithmetic
 * is the server's and untouched — it only decides which of the two
 * questions a given status is answering.
 *
 * ``suspended`` and ``payment_problem`` are deliberately *not* treated
 * as ended. A suspended plan can return to ``active`` if Stripe
 * collects while the schedule is still live, so its outstanding
 * balance is genuinely outstanding; saying otherwise would be the same
 * mistake in the opposite direction.
 *
 * Pure, and imported with a relative ``.ts`` path by its test, so this
 * module must not use the ``@/`` alias.
 */

export type PlanStatus =
  | 'pending_setup'
  | 'active'
  | 'payment_problem'
  | 'suspended'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | string

/** Statuses where billing has stopped for good. */
const ENDED = new Set(['completed', 'cancelled', 'failed'])

export function billingHasEnded(status: PlanStatus): boolean {
  return ENDED.has(status)
}

export interface PlanObligation {
  /** True when more money is expected from this member. */
  collectible: boolean
  /** What is still owed. Always 0 once billing has ended. */
  collectibleCents: number
  /**
   * Agreed but never collected, on a plan that has ended. 0 on a live
   * plan, where the same money is simply not due *yet* and lives in
   * ``collectibleCents`` instead.
   */
  uncollectedCents: number
}

/**
 * ``remainingCents`` is the server's ``remaining_amount_cents`` —
 * ``total - paid`` — passed straight in. It is never recomputed here;
 * it is only routed to the question it actually answers.
 */
export function planObligation(
  status: PlanStatus,
  remainingCents: number,
): PlanObligation {
  const remaining = Math.max(0, Math.round(remainingCents || 0))
  if (billingHasEnded(status)) {
    return {
      collectible: false,
      collectibleCents: 0,
      uncollectedCents: remaining,
    }
  }
  return {
    collectible: true,
    collectibleCents: remaining,
    uncollectedCents: 0,
  }
}

/**
 * The words for the "Remaining" cell when nothing more is coming.
 *
 * Named by what happened, because "A$0" alone would leave a creator
 * wondering whether the plan finished or was stopped — and those need
 * different follow-up.
 */
export function endedRemainingLabel(status: PlanStatus): string | null {
  if (status === 'cancelled') return 'No further payments — cancelled'
  if (status === 'completed') return 'No further payments — completed'
  if (status === 'failed') return 'No further payments — setup failed'
  return null
}

/**
 * "A$5 agreed but not collected" — the history, where there is any.
 *
 * Only worth saying when money was actually left on the table: a plan
 * that completed in full has nothing to explain, and a line reading
 * "A$0 not collected" would be noise on every finished plan.
 */
export function uncollectedNote(
  obligation: PlanObligation,
  formatted: string,
): string | null {
  if (obligation.collectible || obligation.uncollectedCents <= 0) return null
  return `${formatted} agreed but not collected`
}
