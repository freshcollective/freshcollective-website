/**
 * What a Ways to Join card shows once the member has bought it.
 *
 * The card carried a correct "You've purchased this" banner and then,
 * directly underneath, "Purchase Test Gathering Experience" and "Start
 * payment plan". The banner knew about the viewer; the schedule rows
 * below it never had — they are the creator's catalogue, rendered the
 * same way for everybody.
 *
 * Two rules pull against each other here, and both matter:
 *
 * 1. Don't sell someone what they have already bought.
 * 2. Don't stop someone buying something they are allowed to buy.
 *
 * The second is why the suppression signal is ``blocks_repurchase`` —
 * the backend's own ``find_same_option_hold``, the predicate behind the
 * 409 a duplicate checkout already receives. A button disappears
 * exactly when it would have been refused. Nothing here invents a
 * restriction the till does not have, so a legitimate repurchase (a new
 * term after a completed plan, a retry after a cancelled one) keeps
 * working.
 *
 * It also settles §8's awkward cases without a second rule. A completed
 * plan whose access is still live blocks, because the guard checks
 * entitlements and passes rather than plan status alone; a completed
 * plan whose access has lapsed does not, and buying again is then
 * genuinely right.
 *
 * Every figure comes from the member's own ``PurchasePlan``. Nothing is
 * computed here and nothing is read from the Option's current price: a
 * plan is an agreement, and the creator may have re-priced the Option
 * or edited the discount code since it was made.
 *
 * Pure, and imported with a relative ``.ts`` path by its test, so this
 * module must not use the ``@/`` alias.
 */

export interface MemberPlanSummaryLike {
  status: string
  currency: string
  installment_amount_cents: number
  final_installment_amount_cents?: number | null
  installments_expected: number
  installments_paid: number
  total_expected_cents: number
  paid_amount_cents: number
  remaining_amount_cents: number
  interval?: string | null
  interval_count?: number | null
  payment_option_schedule_id?: string | null
}

export interface MemberOptionPurchaseLike {
  payment_option_id: string
  kind: 'plan' | 'pay_in_full' | string
  blocks_repurchase: boolean
  plan?: MemberPlanSummaryLike | null
}

type PurchaseOrNull = MemberOptionPurchaseLike | null | undefined

/** Plans whose next step is repair, not another purchase. */
const NEEDS_ATTENTION = new Set(['payment_problem', 'suspended'])

/** Plans where billing has stopped for good. */
const ENDED = new Set(['completed', 'cancelled', 'failed'])

export function purchaseFor(
  purchases: readonly MemberOptionPurchaseLike[] | null | undefined,
  paymentOptionId: string | null | undefined,
): MemberOptionPurchaseLike | null {
  if (!purchases || !paymentOptionId) return null
  return purchases.find((p) => p.payment_option_id === paymentOptionId) ?? null
}

/**
 * Should this card still offer its schedules?
 *
 * ``blocks_repurchase`` is the backbone. The two attention states are
 * added because §8 asks that a plan needing repair not be answered with
 * "start another one" — and because the Pathway surface has suppressed
 * its purchase CTAs for a suspended plan since FIP4B1, so leaving them
 * on here would make two surfaces disagree about the same plan.
 */
export function hidesCheckout(
  purchase: MemberOptionPurchaseLike | null | undefined,
): boolean {
  if (!purchase) return false
  if (purchase.blocks_repurchase) return true
  const status = purchase.plan?.status
  return !!status && NEEDS_ATTENTION.has(status)
}

export type PurchasedTone = 'joined' | 'attention' | 'ended' | 'setup'

/**
 * The headline state, which decides the card's tone.
 *
 * ``setup`` is separate from ``joined`` because a plan whose card has
 * not been captured yet has bought nothing: §8 is explicit that it must
 * not claim the purchase is complete, and the member's next action is
 * to finish checkout rather than to go and use anything.
 */
export function purchasedTone(
  purchase: PurchaseOrNull,
): PurchasedTone | null {
  if (!purchase) return null
  const status = purchase.plan?.status
  if (!status) return 'joined'            // a settled pay-in-full purchase
  if (status === 'pending_setup') return 'setup'
  if (NEEDS_ATTENTION.has(status)) return 'attention'
  if (ENDED.has(status)) return 'ended'
  return 'joined'
}


export function purchasedHeading(
  tone: PurchasedTone | null,
  optionName: string,
): string | null {
  if (tone === null) return null
  if (tone === 'setup') return 'Payment setup in progress'
  if (tone === 'attention') return 'Your payment plan needs attention'
  if (tone === 'ended') return `You've purchased ${optionName}`
  return `You've joined ${optionName}`
}

/**
 * One line about the arrangement's standing.
 *
 * Says what is true and stops. A suspended plan is not described as
 * finished, a cancelled one is not described as active, and a failed
 * setup is not described as access.
 */
export function purchasedStatusLine(
  purchase: PurchaseOrNull,
): string | null {
  const status = purchase?.plan?.status
  if (!purchase) return null
  if (!status) return 'Your included experiences are ready.'
  switch (status) {
    case 'pending_setup':
      return 'Complete your payment setup to confirm this purchase.'
    case 'active':
      return 'Your payment plan is active.'
    case 'payment_problem':
      return 'A payment didn’t go through. Update your card to keep your access.'
    case 'suspended':
      return 'Your access is paused while this plan is unresolved.'
    case 'completed':
      return 'Your payment plan is complete.'
    case 'cancelled':
      return 'This payment plan was cancelled.'
    case 'failed':
      return 'This payment setup didn’t complete.'
    default:
      return null
  }
}

/**
 * The instalment summary, from the plan and only the plan.
 *
 * ``cadence`` is passed in rather than derived, so the one place that
 * turns an interval into a word stays in ``paymentPlan``.
 */
export function planProgressLines(
  plan: MemberPlanSummaryLike | null | undefined,
  fmt: (cents: number, currency: string) => string,
  cadence: string,
): { schedule: string; total: string; progress: string; remaining: string | null } | null {
  if (!plan) return null
  const count = plan.installments_expected
  if (!count || count < 1) return null

  const base = fmt(plan.installment_amount_cents, plan.currency)
  const last = plan.final_installment_amount_cents
  const uneven = last != null && last !== plan.installment_amount_cents

  // Named, never averaged — the remainder rides on the final payment of
  // a discounted plan, and "2 payments of A$43.33" would misdescribe it.
  const schedule = uneven
    ? (count - 1 === 1
        ? `1 ${cadence} payment of ${base}, then ${fmt(last!, plan.currency)}`
        : `${count - 1} ${cadence} payments of ${base}, then ${fmt(last!, plan.currency)}`)
    : `${count} ${cadence} payment${count === 1 ? '' : 's'} of ${base}`

  const ended = ENDED.has(plan.status)
  return {
    schedule,
    total: `${fmt(plan.total_expected_cents, plan.currency)} total`,
    progress: `${plan.installments_paid} of ${count} payment${count === 1 ? '' : 's'} completed`,
    // A plan that has stopped billing collects nothing further, so a
    // "remaining" figure there would read as a debt. Same rule as the
    // creator's Payment Plans view.
    remaining: ended || plan.remaining_amount_cents <= 0
      ? null
      : `${fmt(plan.remaining_amount_cents, plan.currency)} remaining`,
  }
}

/** Your World — the one destination every purchase has. */
export const YOUR_WORLD = { href: '/dashboard', label: 'Go to Your World' }
